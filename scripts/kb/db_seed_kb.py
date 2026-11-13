#!/usr/bin/env python3
"""PostgreSQL 投影入库管线（docs/09 §2/§3.3：源正本 → 关系表的只读投影）。

大白话：把"知识正本"翻成"一张一张能按列过滤的表"。库是正本的复印件——坏了删掉
重跑本脚本即可，知识不丢。

数据源（全部只读）：
  - app/data/canonical.ttl            权威正本（RDFLib 读图 → kb_entity/kb_relation/要素/法条）
  - data/checks/*-checks.json         四文号检查定义层（jg24 金规116 / jg93 金办发140 /
                                      pboc3 人行56 / jf8 金发32）→ inspection_check + check_element
  - data/checks/jg24-checks.json      检查方法·富层（度量/方法步骤/访谈/判定/常见问题）
  - 10工程 data/control-codes.csv      控制登记表（★ct_code）
  - 10工程 ingest/v17/att2-form.txt    93号文报送表模板 139 项

幂等：整批重建（派生表 DELETE+INSERT，kb_entity UPSERT），连跑两次计数不变；
对账：跑完打印各表行数，与 docs/09 §2.2 期望核对。

用法：
    python scripts/kb/db_seed_kb.py            # 入库（幂等重建）
    python scripts/kb/db_seed_kb.py --check    # 只对账（打印期望 vs 实际，不写）
"""
from __future__ import annotations
import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2  # noqa: E402
from rdflib import Graph, RDF, RDFS, URIRef, Literal  # noqa: E402

from app.config import KB_PG_DSN, APP_DATA, KB_ROOT, BASE_DIR  # noqa: E402

ONT = "https://schema.cheersai.local/ds/ontology/"
KB_IRI = "https://schema.cheersai.local/ds/kb/"
RDFS_NS = str(RDFS)
# 允许纳入投影的非 ONT 命名空间谓词（canonical 正本用 rdfs:label 承载实体名）
EXTRA_PREDICATES = {RDFS_NS + "label": "label", RDFS_NS + "seeAlso": "seeAlso"}
CANONICAL_TTL = APP_DATA / "canonical.ttl"

# control-codes.csv（10工程只读）
CONTROL_CSV = KB_ROOT / "data" / "control-codes.csv"
# 四文号检查定义 JSON（本工程 data/）：定义层权威
CHECKS_DIR = BASE_DIR / "data" / "checks"
CHECKS_FILES = ["jg24-checks.json", "jg93-checks.json", "pboc3-checks.json", "jf8-checks.json"]
# 金规检查 JSON（富层：度量/方法/访谈/判定/发现，仅 jg24 具备）
JG24_JSON = CHECKS_DIR / "jg24-checks.json"
# 93号文报送表模板（10工程只读）
ATT2_TXT = KB_ROOT / "ingest" / "v17" / "att2-form.txt"

# 提升为独立列的数据属性（其余进 data_json）
PROMOTED = {"label", "title", "summary", "status", "ctCode", "checkCode",
            "elementCode", "domain", "priority", "layer", "sourcePath", "contentHash"}


def _dots(s: str) -> str:
    """1.1 → 1-1（用于 URI/slug 末段，与 checks_import 一致）。"""
    return str(s).replace(".", "-")



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
        # ONT 命名空间为主；另纳入 rdfs:label / rdfs:seeAlso（正本用 rdfs:label 承载实体名）
        if ps.startswith(ONT):
            pname = ps[len(ONT):]
        elif ps in EXTRA_PREDICATES:
            pname = EXTRA_PREDICATES[ps]
        else:
            continue
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
    图里有 rdf:type 的用声明类型；被边引用但未声明类型的按 URI 路径段推断，
    外部链接（rdfs:seeAlso 指向的官网地址）推断为 External 实体，保证边不悬空。"""
    tmap = dict(type_of)
    for s, _p, o in edges:
        for u in (s, o):
            if u not in tmap:
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
# 检查定义层（四文号 JSON → inspection_check + kb_entity）与富层（jg24 → 5 表）
# ---------------------------------------------------------------------------
def load_checks_docs() -> list[dict]:
    """只读加载 data/checks 下四文号检查 JSON，回填 doc_key / _file。"""
    docs = []
    for fname in CHECKS_FILES:
        p = CHECKS_DIR / fname
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        d.setdefault("doc_key", fname.replace("-checks.json", ""))
        d["_file"] = fname
        docs.append(d)
    return docs


def build_check_definitions(docs: list[dict]):
    """定义层权威：四文号 JSON → inspection_check 行 + 新增 kb_entity 行 + 富层 5 表行。

    返回 (check_rows, defn_entities, metrics, steps, interviews, verdicts, findings)。
    - check_rows：344 行（jg24 116 + jg93 140 + pboc3 56 + jf8 32），token 与 canonical 对齐。
    - defn_entities：仅 JSON 有、canonical 无的检查实体（供 kb_entity 补行，保证外键完整）。
    - 富层仅 jg24 具备（度量/方法步骤/访谈/判定/发现），字段形状对齐 checks_import.py。
    """
    check_rows: list[dict] = []
    defn_entities: list[dict] = []
    metrics: list[dict] = []
    steps: list[dict] = []
    interviews: list[dict] = []
    verdicts: list[dict] = []
    findings: list[dict] = []

    for d in docs:
        doc_key = d.get("doc_key", "")
        doc_no = d.get("doc_no", "")
        doc_title = d.get("doc_title", "")
        fname = d.get("_file", "")
        for c in d.get("checks", []):
            code = c["id"]
            cid = f"ic-{_dots(code)}"
            uri = f"{KB_IRI}inspectioncheck/{cid}"
            title = c.get("title", "")
            check_rows.append({
                "check_code": code, "entity_uri": uri, "title": title,
                "domain": c.get("domain"), "domain_label": c.get("domain_label", ""),
                "priority": c.get("priority"), "regulation": c.get("regulation", ""),
                "article_no": c.get("article_no", ""), "article_text": c.get("article_text", ""),
                "institution_level": c.get("institution_level", ""),
            })
            defn_entities.append({
                "uri": uri, "entity_type": "InspectionCheck", "slug": cid,
                "label": title, "title": title, "summary": None, "status": None,
                "ct_code": None, "check_code": code, "element_code": None,
                "domain": c.get("domain"), "priority": c.get("priority"), "layer": None,
                "source_path": f"data/checks/{fname}#{code}", "content_hash": None,
                "data_json": json.dumps({
                    "docKey": doc_key, "docNo": doc_no, "docTitle": doc_title,
                    "chapter": c.get("chapter", ""), "articleText": c.get("article_text", ""),
                    "domainLabel": c.get("domain_label", ""),
                }, ensure_ascii=False),
            })

            # ---- 富层（仅 jg24 有 method/verdict/findings）----
            m = c.get("method") or {}
            for j, x in enumerate(m.get("metrics") or [], 1):
                metrics.append({
                    "metric_id": f"{cid}-m{j}", "check_code": code, "seq": j,
                    "name": x.get("name", ""), "data_source": x.get("data_source", ""),
                    "threshold": x.get("threshold", ""),
                })
            for j, x in enumerate(m.get("policy_steps") or [], 1):
                steps.append({
                    "step_id": f"{cid}-msp{j}", "check_code": code, "step_kind": "policy",
                    "seq": j, "step_no": str(x.get("step", j)),
                    "action": x.get("action", ""), "focus": x.get("focus", ""),
                })
            for j, x in enumerate(m.get("evidence_steps") or [], 1):
                steps.append({
                    "step_id": f"{cid}-mse{j}", "check_code": code, "step_kind": "evidence",
                    "seq": j, "step_no": str(x.get("step", j)),
                    "action": x.get("evidence_required", ""), "focus": x.get("criteria", ""),
                })
            for j, x in enumerate(m.get("interviews") or [], 1):
                interviews.append({
                    "interview_id": f"{cid}-i{j}", "check_code": code, "seq": j,
                    "target": x.get("target", ""), "question": x.get("question", ""),
                    "cross_check": x.get("cross_check", ""),
                })
            v = c.get("verdict") or {}
            if v.get("pass") or v.get("partial") or v.get("fail"):
                verdicts.append({
                    "check_code": code,
                    "verdict_pass": json.dumps(v.get("pass", []), ensure_ascii=False),
                    "verdict_partial": json.dumps(v.get("partial", []), ensure_ascii=False),
                    "verdict_fail": json.dumps(v.get("fail", []), ensure_ascii=False),
                })
            for j, x in enumerate(c.get("findings") or [], 1):
                findings.append({
                    "finding_id": f"{cid}-fp{j}", "check_code": code, "seq": j,
                    "rank": str(x.get("rank", j)), "problem": x.get("problem", ""),
                    "root_cause": x.get("root_cause", ""), "remediation": x.get("remediation", ""),
                })

    return check_rows, defn_entities, metrics, steps, interviews, verdicts, findings


def build_canonical_check_rows(type_of, data_attrs, covered_codes: set) -> list[dict]:
    """canonical 正本中、四文号 JSON 未覆盖的检查定义（追加补齐，不覆盖）。

    四文号 JSON 是定义层权威主集；但正本 canonical.ttl 另有 JSON 未收录的检查
    （如 93号文附件1 自查要点 93-3.4/93-3.5）。按"零删除/零断链"原则追加补齐，
    使 check_element.hasElement 的外键不悬空、知识不丢。
    """
    rows = []
    for uri, etype in type_of.items():
        if etype != "InspectionCheck":
            continue
        d = data_attrs.get(uri, {})
        code = _first(d, "checkCode")
        if not code or code in covered_codes:
            continue
        rows.append({
            "check_code": code, "entity_uri": uri,
            "title": _first(d, "title") or _first(d, "label"),
            "domain": _first(d, "domain"), "domain_label": "",
            "priority": _first(d, "priority"), "regulation": "",
            "article_no": _first(d, "articleNo"), "article_text": _first(d, "summary"),
            "institution_level": "",
        })
    return rows


# ---------------------------------------------------------------------------
# check_element / law_clause（canonical 正本 → 要素 / 法条）
# ---------------------------------------------------------------------------
def build_check_rows(type_of, data_attrs, edges, article_text_by_no: dict | None = None):
    """canonical 正本 → check_element 行 / law_clause 行。

    - check_element：走 hasElement 边，text 取 rdfs:label（正本要素正文）。
    - law_clause：Clause 实体；正本多数 Clause 只存 articleNo，故 text 用同条号
      InspectionCheck.article_text 富化（H1 条款文本 ETL 完整性）。
    """
    article_text_by_no = article_text_by_no or {}
    checkcode_by_uri = {}
    for uri, etype in type_of.items():
        if etype != "InspectionCheck":
            continue
        checkcode_by_uri[uri] = _first(data_attrs.get(uri, {}), "checkCode")

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
        article_no = _first(d, "articleNo")
        clause_rows.append({
            "clause_id": clause_id, "law_uri": citeslaw.get(uri),
            "article_no": article_no,
            "text": _first(d, "label") or article_text_by_no.get(article_no),
        })
    return list(el_rows.values()), clause_rows


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
def _article_text_by_no(docs: list[dict]) -> dict:
    """条号（第N条）→ 检查原文，用于富化 law_clause.text（H1 条款文本 ETL）。"""
    out: dict[str, str] = {}
    for d in docs:
        for c in d.get("checks", []):
            no = c.get("article_no") or ""
            txt = c.get("article_text") or ""
            if no and txt and no not in out:
                out[no] = txt
    return out


def build_all() -> tuple[dict, dict]:
    """解析全部只读源 → 各表行（纯函数，不碰库）。返回 (data, counts)。"""
    g, type_of, data_attrs, edges = parse_canonical(CANONICAL_TTL)
    docs = load_checks_docs()
    article_text_by_no = _article_text_by_no(docs)

    kb_entities = build_kb_entities(type_of, data_attrs, edges)
    relations = build_relations(edges, type_of)
    control_rows = build_control_rows()
    element_rows, clause_rows = build_check_rows(type_of, data_attrs, edges, article_text_by_no)
    (check_rows, defn_entities, metrics, steps,
     interviews, verdicts, findings) = build_check_definitions(docs)

    # inspection_check 合并：JSON 定义层为权威主集，canonical 独有检查追加补齐
    # （零删除/零断链：保证 check_element 等子表外键不悬空）
    covered = {r["check_code"] for r in check_rows}
    check_rows = check_rows + build_canonical_check_rows(type_of, data_attrs, covered)

    # kb_entity 合并：canonical 优先，JSON 定义层补缺（保证 inspection_check FK 完整）
    seen = {r["uri"] for r in kb_entities}
    for r in defn_entities:
        if r["uri"] not in seen:
            kb_entities.append(r)
            seen.add(r["uri"])

    # 93号文 topic URI（从 TTL Topic 实体找）
    topic_uri = next((u for u, t in type_of.items() if t == "Topic"
                      and u.endswith("topic-finance-data-security-special-action")), None)
    doc93_items = build_doc93_items(topic_uri)

    data = {
        "kb_entities": kb_entities, "relations": relations, "control_rows": control_rows,
        "check_rows": check_rows, "element_rows": element_rows, "clause_rows": clause_rows,
        "doc93_items": doc93_items, "metrics": metrics, "steps": steps,
        "interviews": interviews, "verdicts": verdicts, "findings": findings,
    }
    counts = {
        "kb_entity": len(kb_entities),
        "kb_relation": len(relations),
        "control": len(control_rows),
        "inspection_check": len(check_rows),
        "check_element": len(element_rows),
        "law_clause": len(clause_rows),
        "doc93_selfcheck_item": len(doc93_items),
        "check_metric": len(metrics),
        "check_method_step": len(steps),
        "check_interview": len(interviews),
        "check_verdict_rule": len(verdicts),
        "check_finding_pattern": len(findings),
    }
    return data, counts


def seed(conn, dry_run: bool = False) -> dict:
    data, counts = build_all()
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
            data["kb_entities"],
        )

        # 派生表整批重建（DELETE + INSERT）
        cur.execute("DELETE FROM kb_relation")
        cur.executemany(
            """INSERT INTO kb_relation(subject_uri,predicate,object_uri,subject_type,object_type)
               VALUES(%(subject_uri)s,%(predicate)s,%(object_uri)s,%(subject_type)s,%(object_type)s)
               ON CONFLICT (subject_uri,predicate,object_uri) DO NOTHING""",
            data["relations"],
        )

        cur.execute("DELETE FROM control")
        cur.executemany(
            """INSERT INTO control(ct_code,entity_uri,title,layer,control_type,family)
               VALUES(%(ct_code)s,%(entity_uri)s,%(title)s,%(layer)s,%(control_type)s,%(family)s)""",
            data["control_rows"],
        )

        # 派生表整批重建（DELETE + INSERT）。注意外键顺序：子表先删、父表先插。
        # 富层 5 表 + check_element 均外键指向 inspection_check(check_code)：
        # 先删所有子表，再删/插 inspection_check，最后按父表已就位插子表。
        cur.execute("DELETE FROM check_finding_pattern")
        cur.execute("DELETE FROM check_verdict_rule")
        cur.execute("DELETE FROM check_interview")
        cur.execute("DELETE FROM check_method_step")
        cur.execute("DELETE FROM check_metric")
        cur.execute("DELETE FROM check_element")
        cur.execute("DELETE FROM inspection_check")
        cur.executemany(
            """INSERT INTO inspection_check(check_code,entity_uri,title,domain,domain_label,priority,
               regulation,article_no,article_text,institution_level)
               VALUES(%(check_code)s,%(entity_uri)s,%(title)s,%(domain)s,%(domain_label)s,%(priority)s,
               %(regulation)s,%(article_no)s,%(article_text)s,%(institution_level)s)""",
            data["check_rows"],
        )
        cur.executemany(
            """INSERT INTO check_element(element_code,entity_uri,check_code,text,criteria,focus_levels)
               VALUES(%(element_code)s,%(entity_uri)s,%(check_code)s,%(text)s,%(criteria)s,%(focus_levels)s)""",
            data["element_rows"],
        )
        cur.executemany(
            """INSERT INTO check_metric(metric_id,check_code,seq,name,data_source,threshold)
               VALUES(%(metric_id)s,%(check_code)s,%(seq)s,%(name)s,%(data_source)s,%(threshold)s)""",
            data["metrics"],
        )
        cur.executemany(
            """INSERT INTO check_method_step(step_id,check_code,step_kind,seq,step_no,action,focus)
               VALUES(%(step_id)s,%(check_code)s,%(step_kind)s,%(seq)s,%(step_no)s,%(action)s,%(focus)s)""",
            data["steps"],
        )
        cur.executemany(
            """INSERT INTO check_interview(interview_id,check_code,seq,target,question,cross_check)
               VALUES(%(interview_id)s,%(check_code)s,%(seq)s,%(target)s,%(question)s,%(cross_check)s)""",
            data["interviews"],
        )
        cur.executemany(
            """INSERT INTO check_verdict_rule(check_code,verdict_pass,verdict_partial,verdict_fail)
               VALUES(%(check_code)s,%(verdict_pass)s,%(verdict_partial)s,%(verdict_fail)s)""",
            data["verdicts"],
        )
        cur.executemany(
            """INSERT INTO check_finding_pattern(finding_id,check_code,seq,rank,problem,root_cause,remediation)
               VALUES(%(finding_id)s,%(check_code)s,%(seq)s,%(rank)s,%(problem)s,%(root_cause)s,%(remediation)s)""",
            data["findings"],
        )

        cur.execute("DELETE FROM law_clause")
        cur.executemany(
            """INSERT INTO law_clause(clause_id,law_uri,article_no,text)
               VALUES(%(clause_id)s,%(law_uri)s,%(article_no)s,%(text)s)""",
            data["clause_rows"],
        )

        cur.execute("DELETE FROM doc93_selfcheck_item")
        cur.executemany(
            """INSERT INTO doc93_selfcheck_item(item_seq,category,category_no,problem_type,
               problem_type_no,problem_text,is_supervision_version,normalized_seq,topic_uri,data_json)
               VALUES(%(item_seq)s,%(category)s,%(category_no)s,%(problem_type)s,%(problem_type_no)s,
               %(problem_text)s,%(is_supervision_version)s,%(normalized_seq)s,%(topic_uri)s,%(data_json)s)""",
            data["doc93_items"],
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
        _, c = build_all()
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
