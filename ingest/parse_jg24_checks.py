# -*- coding: utf-8 -*-
"""
金规〔2024〕24号《银行保险机构数据安全管理办法》检查知识库 —— HTML -> 规范化 JSON 解析器

纯只读 ETL：
  * 仅读取 SOURCE_HTML（源文件，绝不修改）；
  * 仅写出 OUTPUT_JSON（本平台 data/checks/ 下，幂等覆盖）；
  * 依赖：beautifulsoup4 + 标准库（html.parser，无需 lxml）。

用法（建议使用独立 venv，勿污染项目 .venv）：
  python3 -m venv /tmp/jgparse_venv
  /tmp/jgparse_venv/bin/pip install beautifulsoup4
  /tmp/jgparse_venv/bin/python ingest/parse_jg24_checks.py

重跑会覆盖同一 JSON（幂等），并在 stdout 打印统计；脚本末尾自带完整性断言。
"""

import json
import os
import re
from datetime import datetime, timezone, timedelta

from bs4 import BeautifulSoup, NavigableString

# ---------------------------------------------------------------------------
# 路径常量（按部署位置修改这里即可）
# ---------------------------------------------------------------------------
BASE = "/Users/FYP/Documents/WorkSpace/OntoRegGov"
SOURCE_HTML = "/Users/FYP/Documents/@西北人的成长/20-Areas/信息安全/数据安全/04_解决方案/知识库产品/金规2024-24号数据安全检查知识库.html"
OUTPUT_JSON = os.path.join(BASE, "data", "checks", "jg24-checks.json")

SOURCE_FILE_NAME = "金规2024-24号数据安全检查知识库.html"
LAW_TITLE = "银行保险机构数据安全管理办法"
DOC_NO = "金规〔2024〕24号"
ISSUER = "国家金融监督管理总局"

EXPECTED_TOTAL = 116
DOMAIN_LABEL_MAP = {"gov": "治理域", "tech": "技术域", "cross": "跨域"}


# ---------------------------------------------------------------------------
# 文本抽取工具
# ---------------------------------------------------------------------------
def cell_text(el):
    """单元格/段落纯文本：<br> 转换行保留，其余空白折叠为单空格，去首尾空行。"""
    if el is None:
        return ""
    parts = []
    for node in el.descendants:
        if isinstance(node, NavigableString):
            parts.append(str(node))
        elif node.name == "br":
            parts.append("\n")
    raw = "".join(parts)
    lines = []
    for ln in raw.split("\n"):
        ln = re.sub(r"\s+", " ", ln).strip()
        if ln:
            lines.append(ln)
    return "\n".join(lines)


def following_table(el):
    """取 el 之后、作为兄弟节点紧邻的第一张 table。"""
    nxt = el.next_sibling
    while nxt is not None:
        if getattr(nxt, "name", None) == "table":
            return nxt
        nxt = nxt.next_sibling
    return None


def table_rows(table):
    """返回数据行（跳过表头行），每行是单元格文本列表。"""
    if table is None:
        return []
    rows = table.find_all("tr")
    out = []
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"])
        out.append([cell_text(c) for c in cells])
    return out


def parse_focus_levels(raw):
    """'L1-L3' -> ['L1','L2','L3']；'L4' -> ['L4']；'L1,L2' -> ['L1','L2']。"""
    levels = []
    for tok in re.findall(r"L\d(?:\s*[-~—–]\s*L?\d+)?", raw or ""):
        m = re.match(r"L(\d)\s*[-~—–]\s*L?(\d)", tok)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            levels.extend(f"L{i}" for i in range(a, b + 1))
        else:
            mm = re.match(r"L(\d)", tok)
            if mm:
                levels.append(f"L{mm.group(1)}")
    seen = []
    for lv in levels:
        if lv not in seen:
            seen.append(lv)
    seen.sort(key=lambda x: int(x[1:]))
    return seen


# ---------------------------------------------------------------------------
# 领域：导航树 data-domain 为权威 code，meta 中文作交叉校验
# ---------------------------------------------------------------------------
def build_domain_nav_map(soup):
    navmap = {}
    for node in soup.find_all(attrs={"data-domain": True}):
        m = re.match(r"^\s*(\d+\.\d+)", node.get_text(strip=True))
        if m:
            navmap[m.group(1)] = node.get("data-domain")
    return navmap


def cn_to_domain_label(cn):
    if "跨" in cn:
        return "跨域"
    if "技术" in cn:
        return "技术域"
    if "治理" in cn:
        return "治理域"
    return cn


# ---------------------------------------------------------------------------
# 单个检查项解析
# ---------------------------------------------------------------------------
def parse_entry(entry, navmap, anomalies):
    eid = entry["id"].replace("entry-", "")

    # --- h2：优先级 + 标题 ---
    h2 = entry.find("h2")
    prio_span = h2.find("span", class_=re.compile(r"priority-tag"))
    pcls = (prio_span.get("class") or [""])[-1] if prio_span else ""
    priority = {"p0": "P0", "p1": "P1", "p2": "P2"}.get(pcls)
    if priority is None:
        anomalies.append(f"{eid}: 无法识别优先级 class={pcls!r}")
    h2clone = BeautifulSoup(str(h2), "html.parser")
    for s in h2clone.find_all("span"):
        s.decompose()
    title = re.sub(r"^[\d.]+\s*[—–-]\s*", "", cell_text(h2clone)).strip()

    # --- meta ---
    meta = entry.select_one("div.meta")
    spans = meta.find_all("span") if meta else []
    regulation = cell_text(spans[0]) if len(spans) >= 1 else ""
    domain_cn = cell_text(spans[1]) if len(spans) >= 2 else ""

    management_stage = None
    institution_level = None
    for s in spans[2:]:
        t = cell_text(s)
        if t == "管理阶段":
            continue  # 占位标签，无真实值
        if t.startswith("关联制度："):
            institution_level = t[len("关联制度："):].strip() or None
        elif re.match(r"^L\d", t):  # 形如 L1 总纲 / L2-4 技术保护
            institution_level = t
        else:
            # 真实阶段值（如 看 / 测 / 看+问）
            management_stage = t

    # 领域 code：导航 data-domain 权威；与中文交叉校验
    domain = navmap.get(eid)
    if domain is None:
        anomalies.append(f"{eid}: 导航树缺 data-domain，按中文兜底")
        domain = {"治理域": "gov", "技术域": "tech", "跨域": "cross"}.get(cn_to_domain_label(domain_cn))
    domain_label = DOMAIN_LABEL_MAP.get(domain, cn_to_domain_label(domain_cn))
    cn_label = cn_to_domain_label(domain_cn)
    if domain_label != cn_label and not (domain == "cross" and cn_label == "跨域"):
        if not (DOMAIN_LABEL_MAP.get(domain) == cn_label):
            anomalies.append(f"{eid}: 领域交叉校验 code={domain} vs 中文={domain_cn!r}")

    # --- 六个 module（按 header 前缀定位，不依赖顺序；header 可能带计数如"检查清单（11项）"） ---
    def pick_module(prefix):
        for mod in entry.select("div.module"):
            mh = mod.select_one("div.module-header")
            name = cell_text(mh).lstrip("▶").strip()
            if name.startswith(prefix):
                return mod.select_one("div.module-body")
        return None

    modules = {
        "条文原文": pick_module("条文原文"),
        "检查清单": pick_module("检查清单"),
        "检查方法": pick_module("检查方法"),
        "预期结果": pick_module("预期结果"),
        "常见问题": pick_module("常见问题"),
        "关联检查项": pick_module("关联检查项"),
    }

    # 1) 条文原文
    article_no = None
    article_text = ""
    bq_body = modules.get("条文原文")
    if bq_body is not None:
        bq = bq_body.find("blockquote")
        if bq is not None:
            strong = bq.find("strong")
            if strong is not None:
                article_no = cell_text(strong)
            bqclone = BeautifulSoup(str(bq), "html.parser")
            for st in bqclone.find_all("strong"):
                st.decompose()
            article_text = cell_text(bqclone)
    else:
        anomalies.append(f"{eid}: 缺条文原文模块")

    # 2) 检查清单
    checklist = []
    cl_body = modules.get("检查清单")
    if cl_body is not None:
        for row in table_rows(cl_body.find("table")):
            if len(row) < 4:
                anomalies.append(f"{eid}: 检查清单行列数异常 {row}")
                continue
            code, text, focus_raw, criteria = row[0], row[1], row[2], row[3]
            checklist.append({
                "code": code,
                "text": text,
                "focus_level_raw": focus_raw,
                "focus_levels": parse_focus_levels(focus_raw),
                "criteria": criteria,
            })
    else:
        anomalies.append(f"{eid}: 缺检查清单模块")

    # 3) 检查方法
    policy_steps, evidence_steps, metrics, interviews, tip = [], [], [], [], None
    mth_body = modules.get("检查方法")
    if mth_body is not None:
        # 杀手锏：橙色提示块
        for d in mth_body.find_all("div"):
            style = d.get("style") or ""
            if "fff3e0" in style:
                t = cell_text(d)
                if t.startswith("杀手锏："):
                    t = t[len("杀手锏："):].strip()
                tip = t or None
                break
        for st in mth_body.select("div.sub-title"):
            stt = cell_text(st)
            tbl = following_table(st)
            rows = table_rows(tbl)
            if "查制度" in stt:
                for r in rows:
                    if len(r) >= 3:
                        policy_steps.append({"step": r[0], "action": r[1], "focus": r[2]})
            elif "查证据" in stt:
                for r in rows:
                    if len(r) >= 3:
                        evidence_steps.append({"step": r[0], "evidence_required": r[1], "criteria": r[2]})
            elif "查效果" in stt:
                for r in rows:
                    if len(r) >= 3:
                        metrics.append({"name": r[0], "data_source": r[1], "threshold": r[2]})
            elif "访谈" in stt:
                for r in rows:
                    if len(r) >= 3:
                        interviews.append({"target": r[0], "question": r[1], "cross_check": r[2]})
    else:
        anomalies.append(f"{eid}: 缺检查方法模块")

    # 4) 预期结果
    verdict = {"pass": [], "partial": [], "fail": []}
    vd_body = modules.get("预期结果")
    if vd_body is not None:
        key_map = {"合格": "pass", "部分合格": "partial", "不合格": "fail"}
        for st in vd_body.select("div.sub-title"):
            k = key_map.get(cell_text(st))
            ul = st.find_next_sibling("ul")
            if k and ul is not None:
                verdict[k] = [cell_text(li) for li in ul.find_all("li")]
    else:
        anomalies.append(f"{eid}: 缺预期结果模块")

    # 5) 常见问题
    findings = []
    fq_body = modules.get("常见问题")
    if fq_body is not None:
        for row in table_rows(fq_body.find("table")):
            if len(row) < 4:
                continue
            findings.append({
                "rank": row[0], "problem": row[1],
                "root_cause": row[2], "remediation": row[3],
            })
    else:
        anomalies.append(f"{eid}: 缺常见问题模块")

    # 6) 关联检查项
    related = []
    rl_body = modules.get("关联检查项")
    if rl_body is not None:
        rl_table = rl_body.find("table")
        if rl_table is not None:
            for tr in rl_table.find_all("tr")[1:]:
                cells = tr.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                a = cells[0].find("a")
                ref = None
                if a is not None:
                    m = re.search(r"selectItem\(['\"]([\d.]+)['\"]", a.get("onclick") or "")
                    if m:
                        ref = m.group(1)
                if not ref:
                    ref = cell_text(cells[0]).strip()
                relation = cell_text(cells[1])
                related.append({"ref": ref, "relation": relation})
    else:
        anomalies.append(f"{eid}: 缺关联检查项模块")

    return {
        "id": eid,
        "title": title,
        "priority": priority,
        "domain": domain,
        "domain_label": domain_label,
        "regulation": regulation,
        "article_no": article_no,
        "management_stage": management_stage,
        "institution_level": institution_level,
        "article_text": article_text,
        "checklist": checklist,
        "method": {
            "policy_steps": policy_steps,
            "evidence_steps": evidence_steps,
            "tip": tip,
            "metrics": metrics,
            "interviews": interviews,
        },
        "verdict": verdict,
        "findings": findings,
        "related": related,
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    with open(SOURCE_HTML, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    navmap = build_domain_nav_map(soup)

    entries = [e for e in soup.select("div.entry") if (e.get("id") or "").startswith("entry-")]
    anomalies = []
    checks = [parse_entry(e, navmap, anomalies) for e in entries]

    # 计数
    by_domain = {"gov": 0, "tech": 0, "cross": 0}
    by_priority = {"P0": 0, "P1": 0, "P2": 0}
    for c in checks:
        by_domain[c["domain"]] = by_domain.get(c["domain"], 0) + 1
        by_priority[c["priority"]] = by_priority.get(c["priority"], 0) + 1

    cn_tz = timezone(timedelta(hours=8))
    result = {
        "source": {
            "file": SOURCE_FILE_NAME,
            "law_title": LAW_TITLE,
            "doc_no": DOC_NO,
            "issuer": ISSUER,
        },
        "generated_at": datetime.now(cn_tz).isoformat(timespec="seconds"),
        "counts": {
            "total": len(checks),
            "by_domain": by_domain,
            "by_priority": by_priority,
        },
        "checks": checks,
    }

    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # ---------------- 完整性断言 ----------------
    ids = [c["id"] for c in checks]
    assert len(checks) == EXPECTED_TOTAL, f"检查项数量={len(checks)}，期望 {EXPECTED_TOTAL}"
    assert len(ids) == len(set(ids)), "存在重复 id"
    assert result["counts"]["total"] == len(checks)

    for c in checks:
        assert c["regulation"], f"{c['id']} regulation 为空"
        assert c["domain"] in ("gov", "tech", "cross"), f"{c['id']} domain={c['domain']}"
        assert c["priority"] in ("P0", "P1", "P2"), f"{c['id']} priority={c['priority']}"
        assert len(c["checklist"]) >= 1, f"{c['id']} checklist 为空"
        assert c["article_text"], f"{c['id']} article_text 为空"
        for k in ("pass", "partial", "fail"):
            assert k in c["verdict"], f"{c['id']} verdict 缺 {k}"

    # 悬空引用检查
    idset = set(ids)
    dangling = sorted({r["ref"] for c in checks for r in c["related"] if r["ref"] not in idset})

    print(f"[OK] 写出 {OUTPUT_JSON}")
    print(f"[OK] 总数={len(checks)}  by_domain={by_domain}  by_priority={by_priority}")
    print(f"[OK] 悬空引用={dangling if dangling else '无'}")
    print(f"[OK] 异常条数={len(anomalies)}")
    for a in anomalies:
        print("  - " + a)


if __name__ == "__main__":
    main()
