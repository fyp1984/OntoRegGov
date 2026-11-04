#!/usr/bin/env python3
"""PostgreSQL 投影入库管线（docs/09 §2/§3.3：canonical.ttl → 关系表的只读投影）。

大白话：把"知识正本" canonical.ttl 从"一张 RDF 图"翻成"一张一张能按列过滤的表"。
库是正本的复印件——坏了删掉重跑本脚本即可，知识不丢。

数据源（全部只读）：
  - app/data/canonical.ttl            权威正本（RDFLib 读图 → kb_entity/kb_relation）
  - 10工程 data/control-codes.csv     控制登记表 104 行（★ct_code）
  - data/checks/jg24-checks.json       金规116检查（要素/法条 enrichment）
  - 10工程 ingest/v17/att2-form.txt    93号文报送表模板 139 项

幂等：整批重建（派生表 DELETE+INSERT，kb_entity UPSERT），连跑两次计数不变；
对账：跑完打印各表行数，与 docs/09 §2.2 期望核对。

用法：
    python scripts/db_seed_kb.py            # 入库（幂等重建）
    python scripts/db_seed_kb.py --check    # 只对账（打印期望 vs 实际，不写）
"""
from __future__ import annotations
import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2  # noqa: E402
from rdflib import Graph, RDF, RDFS, URIRef, Literal  # noqa: E402

from app.config import KB_PG_DSN, APP_DATA, KB_ROOT, BASE_DIR  # noqa: E402

ONT = "https://schema.cheersai.local/ds/ontology/"
KB_IRI = "https://schema.cheersai.local/ds/kb/"
RDFS_LABEL = RDFS.label
CANONICAL_TTL = APP_DATA / "canonical.ttl"

# control-codes.csv（10工程只读）
CONTROL_CSV = KB_ROOT / "data" / "control-codes.csv"
# 金规检查 JSON（本工程 data/）
JG24_JSON = BASE_DIR / "data" / "checks" / "jg24-checks.json"
# 93号文报送表模板（10工程只读）
ATT2_TXT = KB_ROOT / "ingest" / "v17" / "att2-form.txt"

# 提升为独立列的数据属性（其余进 data_json）
PROMOTED = {"label", "title", "summary", "status", "ctCode", "checkCode",
            "elementCode", "domain", "priority", "layer", "sourcePath", "contentHash"}


# ---------------------------------------------------------------------------
# canonical.ttl 解析
# ---------------------------------------------------------------------------
def parse_canonical(ttl_path: Path):
    g = Graph()
    g.parse(ttl_path, format="turtle")

    # entity_type 映射
    type_of: dict[str, str] = {}
    for s, _p, o in g.triples((None, RDF.type, None)):
        if isinstance(s, URIRef) and isinstance(o, URIRef) and str(o).startswith(ONT):
            type_of[str(s)] = str(o)[len(ONT):]

    # 每实体的数据属性（Literal）与对象边（URIRef→URIRef）
    data_attrs: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    edges: list[tuple[str, str, str]] = []
    for s, p, o in g:
        if not isinstance(s, URIRef):
            continue
        ps = str(p)
        if not ps.startswith(ONT):
            continue
        pname = ps[len(ONT):]
        if isinstance(o, Literal):
            data_attrs[str(s)][pname].append(str(o))
        elif isinstance(o, URIRef):
            edges.append((str(s), pname, str(o)))

    return g, type_of, data_attrs, edges


def _first(d: dict, key: str):
    v = d.get(key)
    return v[0] if v else None


def _infer_type(uri: str) -> str:
    """按 KB_IRI 路径段推断实体类型（图里未声明 rdf:type 的引用节点，如 kb/standard/*）。"""
    if uri.startswith(KB_IRI):
        seg = uri[len(KB_IRI):].split("/", 1)[0]
        # path segment 单数 → 类名首字母大写
        return {"term": "Term", "control": "Control", "law": "Law", "standard": "Standard",
                "solution": "Solution", "guide": "Guide", "topic": "Topic",
                "inspectioncheck": "InspectionCheck", "checkelement": "CheckElement",
                "clause": "Clause", "role": "Role", "case": "Case"}.get(seg, seg.capitalize())
    return "External"


def build_type_map(type_of, edges) -> dict:
    """所有边端点（subject+object）都要在 kb_entity 里有行（FK 完整）。
    图里有 rdf:type 的用声明类型；被边引用但未声明类型的按 URI 路径段推断。"""
    tmap = dict(type_of)
    for s, _p, o in edges:
        for u in (s, o):
            if u.startswith(KB_IRI) and u not in tmap:
                tmap[u] = _infer_type(u)
    return tmap


def build_kb_entities(type_of, data_attrs, edges):
    tmap = build_type_map(type_of, edges)
    rows = []
    for uri, etype in tmap.items():
        d = data_attrs.get(uri, {})
        slug = uri[len(KB_IRI):].rsplit("/", 1)[-1] if uri.startswith(KB_IRI) else uri.rsplit("/", 1)[-1]
        label = _first(d, "label")
        title = _first(d, "title") or label
        # data_json = 未提升的数据属性
        data_json = {}
        for k, vlist in d.items():
            if k in PROMOTED:
                continue
            data_json[k] = vlist[0] if len(vlist) == 1 else vlist
        rows.append({
            "uri": uri, "entity_type": etype, "slug": slug,
            "label": label, "title": title, "summary": _first(d, "summary"),
            "status": _first(d, "status"), "ct_code": _first(d, "ctCode"),
            "check_code": _first(d, "checkCode"), "element_code": _first(d, "elementCode"),
            "domain": _first(d, "domain"), "priority": _first(d, "priority"),
            "layer": _first(d, "layer"), "source_path": _first(d, "sourcePath"),
            "content_hash": _first(d, "contentHash"),
            "data_json": json.dumps(data_json, ensure_ascii=False),
        })
    return rows


def build_relations(edges, type_of):
    tmap = build_type_map(type_of, edges)
    rows = []
    for s, pred, o in edges:
        rows.append({
            "subject_uri": s, "predicate": pred, "object_uri": o,
            "subject_type": tmap.get(s), "object_type": tmap.get(o),
        })
    return rows


# ---------------------------------------------------------------------------
# control（control-codes.csv 权威登记表）
# ---------------------------------------------------------------------------
def build_control_rows():
    rows = []
    with open(CONTROL_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            entity_uri = f"{KB_IRI}control/{r['id']}"
            rows.append({
                "ct_code": r["code"], "entity_uri": entity_uri,
                "title": r["title"], "layer": r["layer"],
                "control_type": r["control_type"], "family": r["family"],
            })
    return rows


# ---------------------------------------------------------------------------
# inspection_check / check_element / law_clause（TTL + jg24 enrichment）
# ---------------------------------------------------------------------------
def build_check_rows(type_of, data_attrs, edges):
    # 金规检查 enrichment（by id）
    j = json.loads(JG24_JSON.read_text(encoding="utf-8"))
    jg = {c["id"]: c for c in j["checks"]}

    # check entity → fields
    check_rows = []
    checkcode_by_uri = {}
    for uri, etype in type_of.items():
        if etype != "InspectionCheck":
            continue
        d = data_attrs.get(uri, {})
        code = _first(d, "checkCode")
        checkcode_by_uri[uri] = code
        enrich = jg.get(code, {})
        check_rows.append({
            "check_code": code, "entity_uri": uri,
            "title": _first(d, "label"),
            "domain": _first(d, "domain"),
            "domain_label": enrich.get("domain_label", ""),
            "priority": _first(d, "priority"),
            "regulation": enrich.get("regulation", ""),
            "article_no": _first(d, "articleNo"),
            "article_text": enrich.get("article_text", ""),
            "institution_level": enrich.get("institution_level", ""),
        })

    # check_element：走 hasElement 边
    el_rows = {}
    for s, pred, o in edges:
        if pred != "hasElement":
            continue
        d = data_attrs.get(o, {})
        el_rows[o] = {
            "element_code": _first(d, "elementCode"), "entity_uri": o,
            "check_code": checkcode_by_uri.get(s),
            "text": _first(d, "label"), "criteria": _first(d, "criteria"),
            "focus_levels": json.dumps(d.get("focusLevel", []), ensure_ascii=False),
        }
    # 兜底：未挂到 hasElement 的 CheckElement（理论上无）
    for uri, etype in type_of.items():
        if etype == "CheckElement" and uri not in el_rows:
            d = data_attrs.get(uri, {})
            el_rows[uri] = {
                "element_code": _first(d, "elementCode"), "entity_uri": uri,
                "check_code": None, "text": _first(d, "label"),
                "criteria": _first(d, "criteria"),
                "focus_levels": json.dumps(d.get("focusLevel", []), ensure_ascii=False),
            }

    # law_clause：Clause 实体
    clause_rows = []
    citeslaw = {s: o for s, pred, o in edges if pred == "citesLaw"}
    for uri, etype in type_of.items():
        if etype != "Clause":
            continue
        d = data_attrs.get(uri, {})
        clause_id = uri[len(KB_IRI):].rsplit("/", 1)[-1]
        clause_rows.append({
            "clause_id": clause_id, "law_uri": citeslaw.get(s),
            "article_no": _first(d, "articleNo"),
            "text": _first(d, "label"),
        })
    return check_rows, list(el_rows.values()), clause_rows


# ---------------------------------------------------------------------------
# doc93_selfcheck_item（att2-form.txt 标准版 139 项）
# ---------------------------------------------------------------------------
_CAT_RE = re.compile(r"●\s*([一二三四五六])、(.+?)\s*／\s*(\d+)\.(.+)")
_ITEM_RE = re.compile(r"^(\d+\.\d+)\s+(.+)")
_CAT_NO = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}


def build_doc93_items(topic_uri: str | None):
    """解析 att2-form.txt 标准版【一】区段，按"问题类型组内连续序号"校准编号。

    xls 编号瑕疵（1.10 误显为 1.1、13.x 重复 13.3、15.10/20.10 误显）在此自动校准：
    每组内按出现顺序取连续 ordinal，item_seq = f"{问题类型号}.{ordinal}"。
    """
    text = ATT2_TXT.read_text(encoding="utf-8")
    lines = text.splitlines()
    items = []
    in_std = False
    cat_cn = cat_name = pt_name = None
    pt_no = None
    ordinal = 0
    global_no = 0
    for line in lines:
        s = line.strip()
        if s.startswith("【一】"):
            in_std = True
            continue
        if s.startswith("【二】") or s.startswith("行数统计"):
            break
        if not in_std:
            continue
        mc = _CAT_RE.match(s)
        if mc:
            cat_cn, cat_name, pt_no, pt_name = mc.groups()
            ordinal = 0
            continue
        mi = _ITEM_RE.match(s)
        if mi and cat_cn:
            raw_seq, problem_text = mi.groups()
            ordinal += 1
            global_no += 1
            item_seq = f"{pt_no}.{ordinal}"
            items.append({
                "item_seq": item_seq,
                "category": cat_name, "category_no": _CAT_NO[cat_cn],
                "problem_type": pt_name, "problem_type_no": int(pt_no),
                "problem_text": problem_text.strip(),
                "is_supervision_version": False,
                "normalized_seq": f"{global_no:03d}",
                "topic_uri": topic_uri,
                "data_json": json.dumps({"raw_display_seq": raw_seq}, ensure_ascii=False),
            })
    return items


# ---------------------------------------------------------------------------
# 入库（整批重建，单事务）
# ---------------------------------------------------------------------------
def seed(conn, dry_run: bool = False) -> dict:
    g, type_of, data_attrs, edges = parse_canonical(CANONICAL_TTL)

    kb_entities = build_kb_entities(type_of, data_attrs, edges)
    relations = build_relations(edges, type_of)
    control_rows = build_control_rows()
    check_rows, element_rows, clause_rows = build_check_rows(type_of, data_attrs, edges)

    # 93号文 topic URI（从 TTL Topic 实体找）
    topic_uri = next((u for u, t in type_of.items() if t == "Topic"
                      and u.endswith("topic-finance-data-security-special-action")), None)
    doc93_items = build_doc93_items(topic_uri)

    counts = {
        "kb_entity": len(kb_entities),
        "kb_relation": len(relations),
        "control": len(control_rows),
        "inspection_check": len(check_rows),
        "check_element": len(element_rows),
        "law_clause": len(clause_rows),
        "doc93_selfcheck_item": len(doc93_items),
    }

    if dry_run:
        return counts

    cur = conn.cursor()
    try:
        # kb_entity UPSERT（按 uri）
        cur.executemany(
            """INSERT INTO kb_entity(uri,entity_type,slug,label,title,summary,status,
               ct_code,check_code,element_code,domain,priority,layer,source_path,content_hash,data_json)
               VALUES(%(uri)s,%(entity_type)s,%(slug)s,%(label)s,%(title)s,%(summary)s,%(status)s,
               %(ct_code)s,%(check_code)s,%(element_code)s,%(domain)s,%(priority)s,%(layer)s,
               %(source_path)s,%(content_hash)s,%(data_json)s)
               ON CONFLICT (uri) DO UPDATE SET
                 entity_type=EXCLUDED.entity_type, slug=EXCLUDED.slug, label=EXCLUDED.label,
                 title=EXCLUDED.title, summary=EXCLUDED.summary, status=EXCLUDED.status,
                 ct_code=EXCLUDED.ct_code, check_code=EXCLUDED.check_code,
                 element_code=EXCLUDED.element_code, domain=EXCLUDED.domain,
                 priority=EXCLUDED.priority, layer=EXCLUDED.layer,
                 source_path=EXCLUDED.source_path, content_hash=EXCLUDED.content_hash,
                 data_json=EXCLUDED.data_json, loaded_at=now()""",
            kb_entities,
        )

        # 派生表整批重建（DELETE + INSERT）
        cur.execute("DELETE FROM kb_relation")
        cur.executemany(
            """INSERT INTO kb_relation(subject_uri,predicate,object_uri,subject_type,object_type)
               VALUES(%(subject_uri)s,%(predicate)s,%(object_uri)s,%(subject_type)s,%(object_type)s)
               ON CONFLICT (subject_uri,predicate,object_uri) DO NOTHING""",
            relations,
        )

        cur.execute("DELETE FROM control")
        cur.executemany(
            """INSERT INTO control(ct_code,entity_uri,title,layer,control_type,family)
               VALUES(%(ct_code)s,%(entity_uri)s,%(title)s,%(layer)s,%(control_type)s,%(family)s)""",
            control_rows,
        )

        # 派生表整批重建（DELETE + INSERT）。注意外键顺序：子表先删、父表先插。
        # check_element.check_code → inspection_check(check_code)：先删 check_element，
        # 再删/插 inspection_check，最后插 check_element。
        cur.execute("DELETE FROM check_element")
        cur.execute("DELETE FROM inspection_check")
        cur.executemany(
            """INSERT INTO inspection_check(check_code,entity_uri,title,domain,domain_label,priority,
               regulation,article_no,article_text,institution_level)
               VALUES(%(check_code)s,%(entity_uri)s,%(title)s,%(domain)s,%(domain_label)s,%(priority)s,
               %(regulation)s,%(article_no)s,%(article_text)s,%(institution_level)s)""",
            check_rows,
        )
        cur.executemany(
            """INSERT INTO check_element(element_code,entity_uri,check_code,text,criteria,focus_levels)
               VALUES(%(element_code)s,%(entity_uri)s,%(check_code)s,%(text)s,%(criteria)s,%(focus_levels)s)""",
            element_rows,
        )

        cur.execute("DELETE FROM law_clause")
        cur.executemany(
            """INSERT INTO law_clause(clause_id,law_uri,article_no,text)
               VALUES(%(clause_id)s,%(law_uri)s,%(article_no)s,%(text)s)""",
            clause_rows,
        )

        cur.execute("DELETE FROM doc93_selfcheck_item")
        cur.executemany(
            """INSERT INTO doc93_selfcheck_item(item_seq,category,category_no,problem_type,
               problem_type_no,problem_text,is_supervision_version,normalized_seq,topic_uri,data_json)
               VALUES(%(item_seq)s,%(category)s,%(category_no)s,%(problem_type)s,%(problem_type_no)s,
               %(problem_text)s,%(is_supervision_version)s,%(normalized_seq)s,%(topic_uri)s,%(data_json)s)""",
            doc93_items,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="OntoRegGov PostgreSQL 投影入库")
    ap.add_argument("--check", action="store_true", help="只解析对账，不写库")
    args = ap.parse_args()

    print(f"[seed] DSN={KB_PG_DSN}")
    if args.check:
        g, type_of, data_attrs, edges = parse_canonical(CANONICAL_TTL)
        topic_uri = next((u for u, t in type_of.items() if t == "Topic"
                          and u.endswith("topic-finance-data-security-special-action")), None)
        ch, el, cl = build_check_rows(type_of, data_attrs, edges)
        c = {
            "kb_entity": len(build_kb_entities(type_of, data_attrs, edges)),
            "kb_relation": len(edges),
            "control": len(build_control_rows()),
            "inspection_check": len(ch),
            "check_element": len(el),
            "law_clause": len(cl),
            "doc93_selfcheck_item": len(build_doc93_items(topic_uri)),
        }
        print("[seed] 解析对账（不写库）：")
        for k, v in c.items():
            print(f"   {k:<22} {v}")
        return 0

    try:
        conn = psycopg2.connect(KB_PG_DSN)
    except Exception as e:
        print(f"[seed] 无法连接 PostgreSQL：{e}", file=sys.stderr)
        return 2
    try:
        counts = seed(conn)
    finally:
        conn.close()
    print("[seed] 入库完成，各表行数：")
    for k, v in counts.items():
        print(f"   {k:<22} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
