#!/usr/bin/env python3
"""NFRA(国家金融监督管理总局) 行政处罚案例采集器。

数据来源(静态 CDN 路径, 无 WAF, 可直连):
  列表: https://www.nfra.gov.cn/cn/static/data/DocInfo/SelectDocByItemIdAndChild/data_itemId=<ID>,pageIndex=<N>,pageSize=<S>.json
  正文: row.docFileUrl (.doc/.xls 等) 或 row.pdfFileUrl, 域名前缀 https://www.nfra.gov.cn

默认采集 itemId=4114 (监管局本级 / 行政处罚), 当前 total≈32993 条。

用法:
  # 试跑 2 页 (36 条)
  python3 scripts/research/nfra_penalty_crawler.py --pages 2

  # 全量增量采集 (已采过的 docId 自动跳过)
  python3 scripts/research/nfra_penalty_crawler.py --all --sleep 1.0

  # 指定页码范围
  python3 scripts/research/nfra_penalty_crawler.py --start-page 3 --pages 5
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://www.nfra.gov.cn"
LIST_API = BASE + "/cn/static/data/DocInfo/SelectDocByItemIdAndChild/data_itemId={item_id},pageIndex={page},pageSize={size}.json"
DETAIL_PAGE = BASE + "/cn/view/pages/ItemDetail.html?docId={doc_id}&itemId={item_id}"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

TEXTUTIL_TYPES = {".doc", ".docx", ".rtf", ".html", ".htm", ".txt", ".odt", ".wordml"}


def fetch(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": BASE + "/"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_json(url: str) -> dict:
    return json.loads(fetch(url).decode("utf-8", errors="ignore"))


def safe_name(text: str, limit: int = 60) -> str:
    text = re.sub(r"[\r\n\t]+", " ", text or "").strip()
    text = re.sub(r"[\\/:*?\"<>|]", "_", text)
    text = re.sub(r"\s+", " ", text)
    return text[:limit].strip() or "untitled"


def doc_to_text(doc_path: Path) -> str:
    """用 macOS textutil 把 .doc/.docx/.rtf 等转成纯文本。"""
    if doc_path.suffix.lower() not in TEXTUTIL_TYPES:
        return ""
    try:
        out = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(doc_path)],
            capture_output=True, timeout=60,
        )
        return out.stdout.decode("utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        print(f"    ! textutil 失败: {exc}", file=sys.stderr)
        return ""


def pdf_to_text(pdf_path: Path) -> str:
    """可选: 有 pdftotext 时提取 PDF; 否则返回空。"""
    import shutil
    if not shutil.which("pdftotext"):
        return ""
    try:
        out = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"],
                             capture_output=True, timeout=60)
        return out.stdout.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return ""


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_markdown(row: dict, body: str, item_id: str) -> str:
    doc_id = row["docId"]
    title = (row.get("docTitle") or "").strip()
    publish = (row.get("publishDate") or "").strip()
    summary = (row.get("docSummary") or "").strip()
    fm = [
        "---",
        f'docId: "{doc_id}"',
        f'title: "{title.replace(chr(34), chr(39))}"',
        f'publishDate: "{publish}"',
        f'source: "{DETAIL_PAGE.format(doc_id=doc_id, item_id=item_id)}"',
        f'publisher: "国家金融监督管理总局"',
        f'category: "行政处罚/监管局本级"',
        'tags: ["金融监管处罚", "行政处罚", "nfra"]',
        "---",
        "",
        f"# {title}",
        "",
        f"- 发布日期：{publish}",
        f"- 来源：{DETAIL_PAGE.format(doc_id=doc_id, item_id=item_id)}",
        "",
    ]
    if summary:
        fm += [f"> {summary}", ""]
    fm += ["## 处罚公示表", "", body or "（未解析到正文，请查看来源链接）", ""]
    return "\n".join(fm)


def crawl(args: argparse.Namespace) -> int:
    out_dir: Path = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "_state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"done": {}}
    done: dict = state.setdefault("done", {})

    tmp = out_dir / "_tmp"
    tmp.mkdir(exist_ok=True)

    page = args.start_page
    saved = skipped = failed = 0
    total = None

    while True:
        if args.limit and (saved + skipped) >= args.limit:
            break
        if not args.all and page >= args.start_page + args.pages:
            break
        url = LIST_API.format(item_id=args.item_id, page=page, size=args.page_size)
        try:
            payload = fetch_json(url)
        except urllib.error.HTTPError as exc:
            print(f"[page {page}] 列表请求失败 HTTP {exc.code}，停止。")
            break
        data = payload.get("data") or {}
        rows = data.get("rows") or []
        total = data.get("total", total)
        if not rows:
            print(f"[page {page}] 无数据，结束。total={total}")
            break
        print(f"[page {page}] 命中 {len(rows)} 条 (服务器 total={total})")

        for row in rows:
            if args.limit and (saved + skipped) >= args.limit:
                break
            doc_id = str(row["docId"])
            if doc_id in done:
                skipped += 1
                continue

            title = (row.get("docTitle") or "").strip()
            doc_url = row.get("docFileUrl")
            pdf_url = row.get("pdfFileUrl")
            body = ""
            src_ext = ""

            for rel in (doc_url, pdf_url):
                if not rel:
                    continue
                ext = Path(rel).suffix.lower()
                local = tmp / f"{doc_id}{ext}"
                try:
                    local.write_bytes(fetch(BASE + rel if rel.startswith("/") else rel))
                except Exception as exc:  # noqa: BLE001
                    print(f"    ! 下载失败 {rel}: {exc}", file=sys.stderr)
                    continue
                text = doc_to_text(local) if ext in TEXTUTIL_TYPES else pdf_to_text(local)
                if text.strip():
                    body, src_ext = clean_text(text), ext
                    break

            fname = f"nfra-{doc_id}-{safe_name(title)}.md"
            (out_dir / fname).write_text(build_markdown(row, body, args.item_id), encoding="utf-8")

            done[doc_id] = {"title": title, "file": fname, "publishDate": row.get("publishDate"),
                            "ext": src_ext, "chars": len(body)}
            saved += 1
            flag = "OK " if body else "EMPTY"
            print(f"    [{flag}] {fname}  ({len(body)} 字, {src_ext or 'no-attachment'})")
            if saved % 20 == 0:
                state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1))
            time.sleep(args.sleep)

        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1))
        page += 1

    print(f"\n完成：新增 {saved}，跳过(已采) {skipped}，输出目录 {out_dir}")
    if total:
        print(f"该栏目服务器端总数 {total} 条，本次覆盖 {len(done)} 条。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="NFRA 行政处罚案例采集器")
    ap.add_argument("--item-id", default="4114", help="栏目 ID，默认 4114(监管局本级/行政处罚)")
    ap.add_argument("--page-size", type=int, default=18, help="每页条数，默认 18")
    ap.add_argument("--start-page", type=int, default=1, help="起始页(从 1 开始)")
    ap.add_argument("--pages", type=int, default=2, help="采集页数(不含 --all 时生效)")
    ap.add_argument("--all", action="store_true", help="持续翻页直到没有数据")
    ap.add_argument("--limit", type=int, default=0, help="最多新增条数(0=不限)")
    ap.add_argument("--sleep", type=float, default=0.8, help="每条间隔秒数，默认 0.8")
    ap.add_argument("--out", default="/Users/FYP/Documents/WorkSpace/OntoRegGov/data/nfra_penalty_cases",
                    help="输出目录")
    args = ap.parse_args()
    return crawl(args)


if __name__ == "__main__":
    raise SystemExit(main())
