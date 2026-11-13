#!/usr/bin/env python3
"""P0 一致性校验：ekos_ds_kb(PG) ↔ 权威源（data/checks/*.json + 10工程 knowledge/graph.json + 平台 app.db）。

==================== 一致性口径（权威源定义）====================
1. 检查项权威源 = data/checks/{jg24,jg93,pboc3,jf8}-checks.json（344，ETL 种子正本）；
   平台 app.db entities(type=InspectionCheck,status=published) 为前端运行投影，与之互证。
   ekos_ds_kb.inspection_check 是上述正本的只读派生台账，P0 只增量补齐，不回写正本。
2. 既有 116 条 jg24 为 P0 之前已投影行（标题列在旧投影中留空，属历史状态），
   硬约束禁止修改既有数据 → 对这 116 条只对账 domain/priority/regulation/article_no/article_text，
   **不对 title 做相等断言**；其余 228 条为 P0 新增，title/domain/priority/article_text 必须与 JSON 一致。
3. 六维（checklist/method/verdict/findings/related）仅 jg24 有；checklist 已投影进 check_element(470)，
   method/verdict/findings/related 镜像进 P0 新建表 check_six_dim。
4. 知识实体/关系权威源 = 10_知识库工程 data/knowledge.json(498) + graph.json；
   ekos_ds_kb.kb_entity/kb_relation 只增量补齐，行数不得低于 P0 前基线（1127 / 8011）。
5. kb_embedding 为 P0 新建向量表，344 条检查项、1024 维，不校验既有表。

用法：
  .venv/bin/python scripts/phase/p0_consistency_check.py            # 全量校验，全绿 exit 0
  报告落盘 reports/p0-consistency.md
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2  # noqa: E402
from app.config import KB_PG_DSN, BASE_DIR, KB_ROOT  # noqa: E402

CHECKS_DIR = BASE_DIR / "data" / "checks"
APP_DB = BASE_DIR / "app" / "data" / "app.db"
KB_DATA = KB_ROOT / "data"
EXPECTED = {"jg24": 116, "jg93": 140, "pboc3": 56, "jf8": 32}
BASELINE_ENTITY = 1127
BASELINE_REL = 8011

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def norm(s) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def doc_of(code: str) -> str:
    if code.startswith("93-"):
        return "jg93"
    if code.startswith("pb3-"):
        return "pboc3"
    if code.startswith("jf8-"):
        return "jf8"
    return "jg24"


def load_json_checks() -> dict[str, dict]:
    out = {}
    for f in EXPECTED:
        d = json.loads((CHECKS_DIR / f"{f}-checks.json").read_text(encoding="utf-8"))
        for c in d["checks"]:
            c["_doc"] = f
            out[c["id"]] = c
    return out


def main() -> int:
    jchecks = load_json_checks()
    conn = psycopg2.connect(KB_PG_DSN)
    cur = conn.cursor()

    # ---- C1 每文号计数 ----
    cur.execute("SELECT check_code FROM inspection_check")
    pg_codes = [r[0] for r in cur.fetchall()]
    pg_by_doc: dict[str, set] = {}
    for code in pg_codes:
        pg_by_doc.setdefault(doc_of(code), set()).add(code)
    c1_ok = True
    for d, n in EXPECTED.items():
        got = len(pg_by_doc.get(d, set()))
        if got != n:
            c1_ok = False
    check("C1 inspection_check 四文号计数 116/140/56/32=344", c1_ok,
          " / ".join(f"{d}={len(pg_by_doc.get(d,set()))}" for d in EXPECTED) +
          f" | 合计={len(pg_codes)}")

    # ---- C2 check_code 集合与 JSON 完全一致 ----
    json_by_doc: dict[str, set] = {}
    for code, c in jchecks.items():
        json_by_doc.setdefault(c["_doc"], set()).add(code)
    c2_missing = []
    c2_extra = []
    for d in EXPECTED:
        miss = json_by_doc[d] - pg_by_doc.get(d, set())
        extra = pg_by_doc.get(d, set()) - json_by_doc[d]
        c2_missing += [f"{d}:{x}" for x in sorted(miss)]
        c2_extra += [f"{d}:{x}" for x in sorted(extra)]
    check("C2 inspection_check 编号集合与 JSON 完全一致（无缺无多）",
          not c2_missing and not c2_extra,
          f"缺{len(c2_missing)} 多{len(c2_extra)}" +
          (f"；缺例 {c2_missing[:3]}" if c2_missing else ""))

    # ---- C3 关键字段对账（jg24 旧行豁免 title）----
    cur.execute("SELECT check_code,title,domain,priority,regulation,article_no,article_text FROM inspection_check")
    pg_rows = {r[0]: r for r in cur.fetchall()}
    jg24_baseline = json_by_doc["jg24"]
    field_bad = []
    for code, jc in jchecks.items():
        row = pg_rows.get(code)
        if not row:
            continue
        _code, ptitle, pdomain, pprio, preg, part, ptext = row
        if code in jg24_baseline:
            pairs = [("domain", pdomain, jc.get("domain")),
                     ("priority", pprio, jc.get("priority")),
                     ("regulation", preg, jc.get("regulation")),
                     ("article_no", part, jc.get("article_no")),
                     ("article_text", ptext, jc.get("article_text"))]
        else:
            pairs = [("title", ptitle, jc.get("title")),
                     ("domain", pdomain, jc.get("domain")),
                     ("priority", pprio, jc.get("priority")),
                     ("article_text", ptext, jc.get("article_text"))]
        for fname, pv, jv in pairs:
            if norm(pv) != norm(jv):
                field_bad.append(f"{code}.{fname}: pg={str(pv)[:20]!r} vs json={str(jv)[:20]!r}")
                break
    check("C3 关键字段与 JSON 一致（jg24 旧行豁免 title）", len(field_bad) == 0,
          f"不一致 {len(field_bad)} 处" + (f"；例 {field_bad[:3]}" if field_bad else ""))

    # ---- C4 六维（仅 jg24）----
    cur.execute("SELECT dimension,count(*) FROM check_six_dim GROUP BY dimension")
    six = {r[0]: r[1] for r in cur.fetchall()}
    cur.execute("SELECT count(*) FROM check_element")
    el_count = cur.fetchone()[0]
    cur.execute("SELECT count(DISTINCT check_code) FROM check_six_dim WHERE dimension='method'")
    method_codes = cur.fetchone()[0]
    cur.execute("SELECT count(DISTINCT check_code) FROM check_six_dim WHERE dimension='verdict'")
    verdict_codes = cur.fetchone()[0]
    c4_ok = (six.get("checklist") == el_count == 470 and method_codes == 116
             and verdict_codes == 116 and six.get("findings", 0) > 0 and six.get("related", 0) > 0)
    check("C4 jg24 六维入库（checklist=%d=check_element, method=%d, verdict=%d, findings=%d, related=%d）"
          % (six.get("checklist", 0), method_codes, verdict_codes, six.get("findings", 0), six.get("related", 0)),
          c4_ok, f"check_element={el_count}")

    # ---- C5 10工程实体全部在 PG，且 kb_entity 不低于基线 ----
    kj = json.loads((KB_DATA / "knowledge.json").read_text(encoding="utf-8"))
    TYPESEG = {"case": "case", "control": "control", "law": "law", "standard": "standard",
               "solution": "solution", "guide": "guide", "topic": "topic", "role": "role",
               "organization": "organization", "scenario": "scenario", "term": "term"}
    need_uri = {f"https://schema.cheersai.local/ds/kb/{TYPESEG[e['type']]}/{e['id']}"
                for e in kj["entities"]}
    cur.execute("SELECT uri FROM kb_entity")
    have_uri = {r[0] for r in cur.fetchall()}
    miss_ent = sorted(need_uri - have_uri)
    cur.execute("SELECT count(*) FROM kb_entity")
    ent_total = cur.fetchone()[0]
    check("C5 10工程 498 实体均在 kb_entity 且总数≥基线",
          not miss_ent and ent_total >= BASELINE_ENTITY,
          f"缺失{len(miss_ent)} kb_entity={ent_total}(基线{BASELINE_ENTITY})" +
          (f"；例{miss_ent[:2]}" if miss_ent else ""))

    # ---- C6 kb_relation 不低于基线 ----
    cur.execute("SELECT count(*) FROM kb_relation")
    rel_total = cur.fetchone()[0]
    check("C6 kb_relation 行数≥P0前基线", rel_total >= BASELINE_REL,
          f"kb_relation={rel_total}(基线{BASELINE_REL})")

    # ---- C7 平台 app.db published 检查项与 JSON 互证 ----
    adb = sqlite3.connect(APP_DB)
    adb.row_factory = sqlite3.Row
    rows = adb.execute(
        "SELECT dataJSON FROM entities WHERE type='InspectionCheck' AND status='published'").fetchall()
    app_by_doc: dict[str, set] = {}
    for r in rows:
        d = json.loads(r["dataJSON"])
        app_by_doc.setdefault(d.get("docKey") or "jg24", set()).add(d.get("checkCode"))
    app_ok = all(len(app_by_doc.get(d, set())) == n for d, n in EXPECTED.items())
    check("C7 平台 app.db published 检查项 116/140/56/32 与 JSON 互证", app_ok,
          " / ".join(f"{d}={len(app_by_doc.get(d,set()))}" for d in EXPECTED))
    adb.close()

    # ---- C8 向量表 344 / 1024 维 ----
    cur.execute("SELECT count(*), count(DISTINCT ref_code), count(embedding) FROM kb_embedding WHERE ref_type='inspection_check'")
    n, ndist, nvec = cur.fetchone()
    cur.execute("SELECT dim FROM kb_embedding LIMIT 1")
    dim = cur.fetchone()[0]
    check("C8 kb_embedding 344 条 / 1024 维 / 无空向量",
          n == 344 and ndist == 344 and nvec == 344 and dim == 1024,
          f"rows={n} distinct={ndist} vec={nvec} dim={dim}")

    conn.close()

    # ---- 汇总 + 报告 ----
    n_fail = sum(1 for _, ok, _ in results if not ok)
    print("\n" + "=" * 60)
    print(f"合计 {len(results)} 项，PASS {len(results)-n_fail}，FAIL {n_fail}")
    report = ROOT / "reports" / "p0-consistency.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# P0 一致性校验报告", "",
             f"- 结果：**{'全绿 ✅' if n_fail == 0 else f'{n_fail} 项 FAIL ❌'}**",
             f"- PG DSN：{KB_PG_DSN}", ""]
    for name, ok, detail in results:
        lines.append(f"- [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"报告 → {report}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
