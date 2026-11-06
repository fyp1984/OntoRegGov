#!/usr/bin/env python3
"""WeKnora 知识库批量重解析（线③ 语义检索增强）。

背景：数据安全知识库 515 篇 Markdown 以 manual 方式上传后停留 draft，未触发
分块（chunks≈90）与向量化（embeddings 仅覆盖 ~12 篇）。本脚本批量调用 WeKnora
重解析接口，把文档转为 completed：分块入 chunks → 经 Ollama(nomic-embed-text,
768 维) 生成 embedding，覆盖率从 ~2% 提到 95%+，从而打通平台"五路融合检索"
（keyword / vector / graph / rag / weknora）里的 WeKnora 语义向量路。

用法（仓库根目录执行）：
  PYTHONPATH=. .venv/bin/python scripts/weknora_reparse_batch.py --dry-run
  PYTHONPATH=. .venv/bin/python scripts/weknora_reparse_batch.py --limit 20 --watch
  PYTHONPATH=. .venv/bin/python scripts/weknora_reparse_batch.py --watch

参数：
  --limit N          只处理前 N 篇（小批量试跑）
  --batch N          每批提交条数（默认 40）
  --poll-interval S  轮询间隔秒（默认 10）
  --batch-timeout S  单批等待上限秒（默认 1800）
  --include-processing 把滞留 processing 的文档也纳入重提交（默认跳过）
  --dry-run          只列出待解析清单，不提交
  --watch            提交后轮询至终态并打印覆盖率

环境变量：
  WEKNORA_API_BASE  默认 http://127.0.0.1:18180
  WEKNORA_TOKEN     默认取环境变量 WEKNORA_TOKEN（需为知识库所属租户令牌）
  WEKNORA_KB_ID     默认 59ad56fe-6673-49af-9380-b7d11f194a0d
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# 复用上传脚本里的演示 token / KB 配置，避免同一凭据在多处硬编码
sys.path.insert(0, str(Path(__file__).resolve().parent))
from upload_kb_to_weknora import TOKEN as _DEMO_TOKEN, KB_ID as _DEMO_KB_ID  # noqa: E402

API_BASE = os.environ.get("WEKNORA_API_BASE", "http://127.0.0.1:18180").rstrip("/")
TOKEN = os.environ.get("WEKNORA_TOKEN", _DEMO_TOKEN)
KB_ID = os.environ.get("WEKNORA_KB_ID", _DEMO_KB_ID)

# 待解析状态：draft/failed/pending/unprocessed 为未完成；processing 默认视为在飞
TARGET_STATUS = {"draft", "failed", "pending", "unprocessed"}
TERMINAL_STATUS = {"completed", "failed"}
PAGE_SIZE = 100


def _api(method: str, path: str, body: dict | None = None, timeout: int = 30) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{API_BASE}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_docs() -> list[dict]:
    """分页拉取知识库全部文档的 {id, title, parse_status, enable_status}。"""
    out: list[dict] = []
    page = 1
    while True:
        d = _api("GET", f"/api/v1/knowledge-bases/{KB_ID}/knowledge"
                        f"?page={page}&page_size={PAGE_SIZE}")
        rows = d.get("data") or []
        for r in rows:
            out.append({
                "id": r.get("id"),
                "title": r.get("title", ""),
                "parse_status": r.get("parse_status", ""),
                "enable_status": r.get("enable_status", ""),
            })
        total = int(d.get("total") or 0)
        if not rows or len(out) >= total:
            break
        page += 1
    return out


def submit(ids: list[str]) -> int:
    """提交一批重解析，返回服务端受理条数。"""
    d = _api("POST", "/api/v1/knowledge/batch-reparse",
             {"kb_id": KB_ID, "ids": ids})
    return int((d.get("data") or {}).get("reparse_count") or 0)


def _status_map() -> dict[str, dict]:
    return {d["id"]: d for d in list_docs()}


def wait_batch(ids: list[str], interval: int, timeout: int) -> dict:
    """轮询一批文档直到全部进入终态（或超时）。返回 {status: count} 与未完成列表。"""
    deadline = time.time() + timeout
    pending = set(ids)
    while pending and time.time() < deadline:
        time.sleep(interval)
        smap = _status_map()
        pending = {i for i in pending
                   if smap.get(i, {}).get("parse_status") not in TERMINAL_STATUS}
        done = len(ids) - len(pending)
        print(f"    进度 {done}/{len(ids)} 终态，剩余 {len(pending)} 在飞…", flush=True)
    smap = _status_map()
    counts: dict[str, int] = {}
    for i in ids:
        st = smap.get(i, {}).get("parse_status", "missing")
        counts[st] = counts.get(st, 0) + 1
    return {"counts": counts, "unfinished": sorted(pending)}


def coverage() -> dict:
    """全库文档级覆盖率（parse_status 分布 + completed 占比）。"""
    docs = list_docs()
    dist: dict[str, int] = {}
    for d in docs:
        dist[d["parse_status"]] = dist.get(d["parse_status"], 0) + 1
    total = len(docs)
    done = dist.get("completed", 0)
    return {"total": total, "dist": dist,
            "completed": done,
            "ratio": (done / total) if total else 0.0}


def _print_coverage(tag: str) -> None:
    c = coverage()
    dist = " / ".join(f"{k}={v}" for k, v in sorted(c["dist"].items()))
    print(f"[{tag}] 文档 {c['total']} 篇 | {dist} | completed 覆盖率 {c['ratio']:.1%}")


def main() -> None:
    ap = argparse.ArgumentParser(description="WeKnora 知识库批量重解析")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 篇")
    ap.add_argument("--batch", type=int, default=40, help="每批提交条数")
    ap.add_argument("--poll-interval", type=int, default=10, help="轮询间隔秒")
    ap.add_argument("--batch-timeout", type=int, default=1800, help="单批等待上限秒")
    ap.add_argument("--include-processing", action="store_true",
                    help="把滞留 processing 的文档也纳入重提交")
    ap.add_argument("--dry-run", action="store_true", help="只列清单不提交")
    ap.add_argument("--watch", action="store_true", help="提交后轮询至终态")
    args = ap.parse_args()

    print(f"WeKnora: {API_BASE}  知识库: {KB_ID}")
    _print_coverage("起始")

    docs = list_docs()
    targets = [d for d in docs if d["parse_status"] in TARGET_STATUS]
    if args.include_processing:
        targets += [d for d in docs if d["parse_status"] == "processing"]
    if args.limit:
        targets = targets[: args.limit]

    print(f"\n待解析 {len(targets)} 篇（{' + '.join(sorted(TARGET_STATUS))}"
          f"{' + processing' if args.include_processing else ''}）")
    for d in targets[:10]:
        print(f"  - [{d['parse_status']:8}] {d['title'][:70]}")
    if len(targets) > 10:
        print(f"  … 其余 {len(targets) - 10} 篇")

    if args.dry_run or not targets:
        if args.dry_run:
            print("\n--dry-run：未提交任何任务。")
        return

    ids = [d["id"] for d in targets]
    submitted = 0
    total_batches = (len(ids) + args.batch - 1) // args.batch
    for bi in range(total_batches):
        chunk = ids[bi * args.batch: (bi + 1) * args.batch]
        n = submit(chunk)
        submitted += n
        print(f"\n[{bi + 1}/{total_batches}] 提交 {n} 篇（累计 {submitted}/{len(ids)}）", flush=True)
        if args.watch:
            res = wait_batch(chunk, args.poll_interval, args.batch_timeout)
            stat = " / ".join(f"{k}={v}" for k, v in sorted(res["counts"].items()))
            print(f"  本批终态：{stat}")
            if res["unfinished"]:
                print(f"  ⚠ 超时未完成 {len(res['unfinished'])} 篇（可重跑续处理）")

    print(f"\n提交完成：{submitted}/{len(ids)} 篇。")
    _print_coverage("收尾")


if __name__ == "__main__":
    main()
