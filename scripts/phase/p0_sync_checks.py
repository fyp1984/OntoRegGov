#!/usr/bin/env python3
"""P0 增量同步：把四文号检查项 / jg24 六维 / 10工程缺失实体与 typed 关系增量补进 ekos_ds_kb。

纪律（硬约束）：
  - 只 INSERT（ON CONFLICT DO NOTHING），绝不 DELETE / UPDATE 既有行，绝不改动既有表结构；
  - 既有 1127 kb_entity / 8011 kb_relation / 116 inspection_check 原样保留；
  - 六维（method/verdict/findings/related + checklist 镜像）仅 jg24 有，写入新建表 check_six_dim；
  - 10工程实体/关系只补缺失：实体按 canonical IRI 段对齐；关系只补谓词可一一映射的 typed 边，
    编辑器侧的泛化 related 网（6424 条）不批量重灌（canonical 已用 mentions/relatedTerm/seeAlso 表达）。

权威源口径（详见 scripts/phase/p0_consistency_check.py 文档串）：
  - 检查项权威 = data/checks/{jg24,jg93,pboc3,jf8}-checks.json（344），与平台 app.db published 实体互证；
  - 知识实体/关系权威 = 10_知识库工程 data/knowledge.json + graph.json，对齐 canonical IRI。

用法：
  .venv/bin/python scripts/phase/p0_sync_checks.py --dry-run     # 只规划，不写库（默认）
  .venv/bin/python scripts/phase/p0_sync_checks.py --apply       # 真实增量写入
连接串取自 app/config.py KB_PG_DSN，可用环境变量 KB_PG_DSN 覆盖。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2  # noqa: E402

from app.config import KB_PG_DSN, BASE_DIR, KB_ROOT  # noqa: E402

KB_IRI = "https://schema.cheersai.local/ds/kb/"
CHECKS_DIR = BASE_DIR / "data" / "checks"
KB_DATA = KB_ROOT / "data"

DOC_FILES = ["jg24", "jg93", "pboc3", "jf8"]
# 10工程 type(小写) → canonical IRI 段 / kb_entity.entity_type 首字母大写
TYPE_MAP = {
    "case": ("case", "Case"), "control": ("control", "Control"),
    "law": ("law", "Law"), "standard": ("standard", "Standard"),
    "solution": ("solution", "Solution"), "guide": ("guide", "Guide"),
    "topic": ("topic", "Topic"), "role": ("role", "Role"),
    "organization": ("organization", "Organization"), "scenario": ("scenario", "Scenario"),
    "term": ("term", "Term"),
}
# graph.json snake_case 谓词 → canonical camelCase（只补可一一对应的 typed 边）
REL_MAP = {
    "cites_law": "citesLaw", "cites_standard": "citesStandard",
    "governed_by": "governedBy", "deployed_with": "deployedWith",
    "published_by": "publishedBy", "contrasts_with": "contrastsWith",
    "defined_by": "definedBy", "member_of": "memberOf",
    "involves_role": "involvesRole", "related_term": "relatedTerm",
    "see_also": "seeAlso", "instance_of": "hasInstance",
    "part_of_path": "partOfPath", "occurs_in": "occursIn",
    "implements": "implements", "mitigates": "mitigates",
    "broader": "broader", "prerequisite": "prerequisite", "antonym": "antonym",
}


def slugify_code(code: str) -> str:
    """10.1 -> 10-1；93-1.1 -> 93-1-1；pb3-1 -> pb3-1；jf8-1 -> jf8-1。"""
    return re.sub(r"[^a-zA-Z0-9]+", "-", code).strip("-").lower()


def load_checks() -> dict[str, dict]:
    """{check_code: record}，附带 doc 元信息。"""
    out: dict[str, dict] = {}
    for f in DOC_FILES:
        d = json.loads((CHECKS_DIR / f"{f}-checks.json").read_text(encoding="utf-8"))
        meta = {
            "docKey": f, "docNo": d.get("doc_no", ""), "docTitle": d.get("doc_title", ""),
            "sourceNote": d.get("source_note", ""),
        }
        for c in d["checks"]:
            rec = dict(c)
            rec.update(meta)
            out[c["id"]] = rec
    return out


def ensure_six_dim_table(cur) -> None:
    """新建六维表（additive；既有表不动）。"""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS check_six_dim (
          check_code  TEXT NOT NULL,
          doc_key     TEXT NOT NULL,
          dimension   TEXT NOT NULL,          -- checklist|method|verdict|findings|related
          seq         INTEGER NOT NULL DEFAULT 0,
          title       TEXT,
          payload     JSONB NOT NULL,
          created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (check_code, dimension, seq)
        )
        """
    )


def sync_checks(conn, checks: dict[str, dict], dry: bool, stats: dict) -> None:
    cur = conn.cursor()
    # 既有 inspection_check.check_code 集合；既有 kb_entity InspectionCheck by check_code
    cur.execute("SELECT check_code FROM inspection_check")
    have_check = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT check_code, uri FROM kb_entity WHERE entity_type='InspectionCheck'")
    ent_by_code = {r[0]: r[1] for r in cur.fetchall() if r[0]}

    for code, c in checks.items():
        # 1) 实体：复用既有，否则按确定性 IRI 新建
        uri = ent_by_code.get(code)
        if uri is None:
            slug = f"ic-{slugify_code(code)}"
            uri = f"{KB_IRI}inspectioncheck/{slug}"
            if not dry:
                cur.execute(
                    """INSERT INTO kb_entity(uri,entity_type,slug,label,title,summary,status,
                       check_code,domain,priority,data_json)
                       VALUES(%s,'InspectionCheck',%s,%s,%s,%s,'published',%s,%s,%s,%s)
                       ON CONFLICT (uri) DO NOTHING""",
                    (uri, slug, c.get("title", ""), c.get("title", ""),
                     c.get("article_text", ""), code, c.get("domain", ""),
                     c.get("priority", ""),
                     json.dumps({
                         "docKey": c.get("docKey"), "docNo": c.get("docNo"),
                         "docTitle": c.get("docTitle"), "chapter": c.get("chapter", ""),
                         "regulation": c.get("regulation", ""),
                         "sourceNote": c.get("sourceNote", ""),
                     }, ensure_ascii=False)),
                )
            stats["kb_entity_new"] += 1
        # 2) inspection_check：ON CONFLICT DO NOTHING，既有 116 不覆盖
        if code not in have_check:
            if not dry:
                cur.execute(
                    """INSERT INTO inspection_check(check_code,entity_uri,title,domain,domain_label,
                       priority,regulation,article_no,article_text,institution_level)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (check_code) DO NOTHING""",
                    (code, uri, c.get("title", ""), c.get("domain", ""),
                     c.get("domain_label", ""), c.get("priority", ""),
                     c.get("regulation", ""), c.get("article_no", ""),
                     c.get("article_text", ""), c.get("institution_level", "")),
                )
            stats["inspection_check_new"] += 1
        # 3) jg24 六维 → check_six_dim（仅 jg24 有）
        if c.get("docKey") == "jg24":
            dims = {
                "checklist": c.get("checklist"),
                "method": c.get("method"),
                "verdict": c.get("verdict"),
                "findings": c.get("findings"),
                "related": c.get("related"),
            }
            for dim, payload in dims.items():
                if payload is None:
                    continue
                seq_items = payload if isinstance(payload, list) else [payload]
                for i, item in enumerate(seq_items):
                    title = ""
                    if isinstance(item, dict):
                        title = item.get("text") or item.get("action") or item.get("problem") or ""
                    if dry:
                        stats["six_dim_new"] += 1
                        continue
                    cur.execute(
                        """INSERT INTO check_six_dim(check_code,doc_key,dimension,seq,title,payload)
                           VALUES(%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (check_code,dimension,seq) DO NOTHING""",
                        (code, "jg24", dim, i, title,
                         json.dumps(item, ensure_ascii=False)),
                    )
                    if cur.rowcount:
                        stats["six_dim_new"] += 1


def sync_entities_relations(conn, dry: bool, stats: dict) -> None:
    kpath = KB_DATA / "knowledge.json"
    gpath = KB_DATA / "graph.json"
    if not kpath.exists():
        print(f"[skip] 10工程 knowledge.json 不存在：{kpath}")
        return
    kj = json.loads(kpath.read_text(encoding="utf-8"))
    gj = json.loads(gpath.read_text(encoding="utf-8")) if gpath.exists() else {"nodes": [], "edges": []}
    ntype = {n["id"]: n.get("type") for n in gj["nodes"]}

    cur = conn.cursor()
    cur.execute("SELECT uri FROM kb_entity")
    have_ent = {r[0] for r in cur.fetchall()}

    # --- 实体补缺失 ---
    for e in kj["entities"]:
        seg, etype = TYPE_MAP.get(e["type"], (e["type"], e["type"].capitalize()))
        uri = f"{KB_IRI}{seg}/{e['id']}"
        if uri in have_ent:
            continue
        if not dry:
            cur.execute(
                """INSERT INTO kb_entity(uri,entity_type,slug,label,title,summary,status,data_json)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (uri) DO NOTHING""",
                (uri, etype, e["id"], e.get("title", ""), e.get("title", ""),
                 e.get("summary", ""), e.get("status", ""),
                 json.dumps({k: e.get(k) for k in
                             ("aliases", "tags", "level", "official_url", "md_path",
                              "code", "layer", "control_type", "family", "lifecycle")
                             if e.get(k) is not None}, ensure_ascii=False)),
            )
        have_ent.add(uri)
        stats["kb10_entity_new"] += 1

    # --- typed 关系补缺失（仅可映射谓词；端点必须存在）---
    cur.execute("SELECT subject_uri,predicate,object_uri FROM kb_relation")
    have_rel = {(r[0], r[1], r[2]) for r in cur.fetchall()}
    for ed in gj["edges"]:
        pred = REL_MAP.get(ed.get("rel"))
        if pred is None:
            continue  # 泛化 related/related_term(未映射)/see_also 等编辑器导航网不重灌
        st, ot = ntype.get(ed["source"]), ntype.get(ed["target"])
        sseg, _ = TYPE_MAP.get(st, (st, ""))
        oseg, _ = TYPE_MAP.get(ot, (ot, ""))
        su = f"{KB_IRI}{sseg}/{ed['source']}"
        ou = f"{KB_IRI}{oseg}/{ed['target']}"
        if su not in have_ent or ou not in have_ent:
            continue
        if (su, pred, ou) in have_rel:
            continue
        if not dry:
            cur.execute(
                """INSERT INTO kb_relation(subject_uri,predicate,object_uri,subject_type,object_type)
                   VALUES(%s,%s,%s,%s,%s) ON CONFLICT (subject_uri,predicate,object_uri) DO NOTHING""",
                (su, pred, ou, st, ot),
            )
        have_rel.add((su, pred, ou))
        stats["kb10_rel_new"] += 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真实写入；缺省为 dry-run")
    args = ap.parse_args()
    dry = not args.apply

    stats = {"inspection_check_new": 0, "kb_entity_new": 0, "six_dim_new": 0,
             "kb10_entity_new": 0, "kb10_rel_new": 0}

    print(f"[sync] DSN={KB_PG_DSN}  mode={'APPLY' if not dry else 'DRY-RUN'}")
    checks = load_checks()
    by_doc: dict[str, int] = {}
    for c in checks.values():
        by_doc[c["docKey"]] = by_doc.get(c["docKey"], 0) + 1
    print("[sync] 检查项权威源计数:", dict(sorted(by_doc.items())), "合计", len(checks))

    conn = psycopg2.connect(KB_PG_DSN)
    try:
        conn.autocommit = False
        cur = conn.cursor()
        if not dry:
            ensure_six_dim_table(cur)
        sync_checks(conn, checks, dry, stats)
        sync_entities_relations(conn, dry, stats)
        if dry:
            conn.rollback()
            print("[sync] DRY-RUN 未写库。规划新增：")
        else:
            conn.commit()
            print("[sync] APPLY 已提交。新增：")
        for k, v in stats.items():
            print(f"   {k:<20} {v}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
