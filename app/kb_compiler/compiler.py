"""确定性编译：编辑源(YAML/MD/CSV) → canonical RDF 图。

大白话：把人写的 Markdown"翻译"成统一编号的三元组，像源码编译成字节码——
单向、可重复、同输入同输出，绝不回写编辑源。
"""
from __future__ import annotations
import csv
import json
import re
from pathlib import Path

from rdflib import Graph, URIRef, Literal, RDF, RDFS, OWL, XSD, BNode

from ..config import KB_ROOT, BASE_DIR
from . import iris
from .parse import scan_mvp, parse_md, load_registry

# layer 英文词 → CT 层码（docs/05 §4.2）
LAYER_TO_CODE = {"endpoint": "EP", "network": "NW", "service": "SVC",
                 "protocol": "PROTO", "management": "MGMT"}

# frontmatter 关系键(蛇形) → camelCase 对象属性名
def _rel_prop(rel: str) -> str:
    parts = rel.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _add_tbox(g: Graph) -> None:
    """克制 OWL/RDFS 骨架：类、对象/数据属性、domain/range、inverseOf。"""
    O = iris.ONT
    for cls in ["Term", "Law", "Standard", "Control", "Role", "Case", "Organization",
                "Scenario", "Solution", "Guide", "Topic", "Clause", "InspectionCheck",
                "CheckElement"]:
        g.add((O[cls], RDF.type, OWL.Class))
    # 数据属性
    for dp in ["title", "titleEn", "level", "summary", "status", "updatedOn", "tag",
               "alias", "ctCode", "ctLayer", "layer", "lifecycle", "controlType",
               "controlFamily", "evidenceExample", "sourcePath", "contentHash",
               "checkCode", "domain", "priority", "articleNo", "elementCode", "criteria",
               # v1.8.0：law/standard/organization 富字段（append-only，不改既有语义）
               "authority", "docNo", "issued", "effective", "validity", "hierarchy",
               "stdNo", "issuer", "kind", "statusStd", "orgKind", "region", "mandate"]:
        g.add((O[dp], RDF.type, OWL.DatatypeProperty))
    # 对象属性（含对称/逆）
    for op in ["implements", "citesLaw", "citesStandard", "governedBy", "seeAlso",
               "relatedTerm", "broader", "narrower", "memberOf", "synonym",
               "mitigates", "deployedWith", "citesClause", "hasElement", "mentions",
               # v1.6.0：law/topic 关系（93号文 MD 用到）
               "publishedBy", "governs", "citedBy",
               # v1.8.0：法规/标准/机构全量关系（publish/publishes 机构发文、defines 标准定规则）
               "publishes", "defines", "definedBy"]:
        g.add((O[op], RDF.type, OWL.ObjectProperty))
    g.add((O["broader"], OWL.inverseOf, O["narrower"]))
    g.add((O["seeAlso"], RDF.type, OWL.SymmetricProperty))
    g.add((O["synonym"], RDF.type, OWL.SymmetricProperty))
    g.add((O["relatedTerm"], RDF.type, OWL.SymmetricProperty))


def _entity_common(g: Graph, subj: URIRef, rec: dict) -> None:
    fm = rec["fm"]
    O = iris.ONT
    g.add((subj, RDF.type, O[rec["type"].capitalize() if rec["type"] != "control" else "Control"]))
    g.add((subj, RDFS.label, Literal(fm.get("title", rec["id"]), lang="zh")))
    g.add((subj, O["title"], Literal(fm.get("title", rec["id"]), lang="zh")))
    if fm.get("title_en"):
        g.add((subj, O["titleEn"], Literal(fm["title_en"])))
    if fm.get("level"):
        g.add((subj, O["level"], Literal(fm["level"])))
    if fm.get("summary"):
        g.add((subj, O["summary"], Literal(fm["summary"], lang="zh")))
    if fm.get("status"):
        g.add((subj, O["status"], Literal(fm["status"])))
    if fm.get("updated"):
        g.add((subj, O["updatedOn"], Literal(str(fm["updated"]), datatype=XSD.date)))
    for tag in fm.get("tags", []) or []:
        g.add((subj, O["tag"], Literal(str(tag))))
    for al in fm.get("aliases", []) or []:
        g.add((subj, O["alias"], Literal(str(al))))
    if fm.get("official_url"):
        g.add((subj, RDFS.seeAlso, URIRef(fm["official_url"])))
    # 溯源标注（编译产物自带）
    g.add((subj, O["sourcePath"], Literal(rec["sourcePath"])))
    g.add((subj, O["contentHash"], Literal(rec["contentHash"])))


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _doc_extras(g: Graph, subj: URIRef, rec: dict) -> None:
    """v1.8.0：law/standard/organization 富字段投影（数据属性，append-only）。

    law: authority/doc_no/issued/effective/validity/hierarchy
    standard: std_no/issuer/issued/effective/kind/status_std
    organization: org_kind/region/mandate
    仅在 frontmatter 存在时写三元组，缺字段不造值；日期统一 xsd:date。
    """
    fm = rec["fm"]
    O = iris.ONT
    if rec["type"] == "law":
        for fm_key, ont_key in [("authority", "authority"), ("doc_no", "docNo"),
                                ("validity", "validity"), ("hierarchy", "hierarchy")]:
            if fm.get(fm_key):
                g.add((subj, O[ont_key], Literal(str(fm[fm_key]), lang="zh")))
        for dk in ("issued", "effective"):
            if fm.get(dk):
                v = str(fm[dk])
                if _ISO_DATE.match(v):
                    g.add((subj, O[dk], Literal(v, datatype=XSD.date)))
                else:
                    g.add((subj, O[dk], Literal(v)))  # 年月/模糊值：普通字面量
    elif rec["type"] == "standard":
        for fm_key, ont_key in [("std_no", "stdNo"), ("issuer", "issuer"),
                                ("kind", "kind"), ("status_std", "statusStd")]:
            if fm.get(fm_key):
                g.add((subj, O[ont_key], Literal(str(fm[fm_key]), lang="zh")))
        for dk in ("issued", "effective"):
            if fm.get(dk):
                v = str(fm[dk])
                if _ISO_DATE.match(v):
                    g.add((subj, O[dk], Literal(v, datatype=XSD.date)))
                else:
                    g.add((subj, O[dk], Literal(v)))
    elif rec["type"] == "organization":
        for fm_key, ont_key in [("org_kind", "orgKind"), ("region", "region"),
                                ("mandate", "mandate")]:
            if fm.get(fm_key):
                g.add((subj, O[ont_key], Literal(str(fm[fm_key]), lang="zh")))


def _compile_entities(g: Graph, recs: list[dict], codes: dict) -> dict:
    """编译 term/control 实体。返回 id→(type,uri) 索引供关系/校验解析。

    control 的 ctCode/ctLayer 以 control-codes.csv（权威登记表）为写入值，
    不从 frontmatter 手抄；lifecycle/standard_mappings 等富字段仍取 MD。
    """
    O = iris.ONT
    index: dict[str, tuple[str, URIRef]] = {}
    for rec in sorted(recs, key=lambda r: r["id"]):
        eid, ttype = rec["id"], rec["type"]
        subj = URIRef(iris.kb_instance_iri(ttype, eid))
        index[eid] = (ttype, subj)
        _entity_common(g, subj, rec)
        _doc_extras(g, subj, rec)  # v1.8.0：law/standard/organization 富字段
        fm = rec["fm"]
        # control 特有字段
        if ttype == "control":
            csv_row = codes.get(eid)  # CSV 权威值
            # ctCode：CSV 权威（缺失则回退 MD code，由对账暴露漂移）
            code = csv_row["code"] if csv_row else fm.get("code", "")
            g.add((subj, O["ctCode"], Literal(code)))
            layer_en = csv_row["layer"] if csv_row else fm.get("layer", "")
            g.add((subj, O["layer"], Literal(layer_en)))
            g.add((subj, O["ctLayer"], Literal(LAYER_TO_CODE.get(layer_en, ""))))
            for lc in fm.get("lifecycle", []) or []:
                g.add((subj, O["lifecycle"], Literal(lc)))
            # control_type/family 同样以 CSV 权威为准
            ctype = csv_row["control_type"] if csv_row else fm.get("control_type", "")
            g.add((subj, O["controlType"], Literal(ctype)))
            fam = csv_row["family"] if csv_row else (fm.get("family") or fm.get("control_family"))
            g.add((subj, O["controlFamily"], Literal(fam)))
            for ex in fm.get("evidence_examples", []) or []:
                g.add((subj, O["evidenceExample"], Literal(str(ex))))
            # standard_mappings 匿名节点
            for m in fm.get("standard_mappings", []) or []:
                b = BNode()
                g.add((subj, O["hasMapping"], b))
                if m.get("framework"):
                    g.add((b, O["framework"], Literal(m["framework"])))
                if m.get("ref"):
                    g.add((b, O["ref"], Literal(str(m["ref"]))))
                if m.get("note"):
                    g.add((b, O["mappingNote"], Literal(str(m["note"]))))
    return index


def _resolve_relations(g: Graph, recs: list[dict], index: dict, registry: dict) -> None:
    """frontmatter relations + 正文 [[wikilink]] → 对象属性。

    目标解析：MVP 内已编译 → 编译 URI；注册表内其他类型(law/standard/solution…)
    → <kb>/<type>/<id>（合法实例 URI，属 MVP 外但不断链）；注册表都没有 → 断链，跳过。
    """
    O = iris.ONT
    all_ids = set(index)

    def tgt_uri(to: str):
        if to in all_ids:
            return index[to][1]
        if to in registry:
            return URIRef(iris.kb_instance_iri(registry[to], to))
        return None  # 断链

    for rec in sorted(recs, key=lambda r: r["id"]):
        eid, ttype = rec["id"], rec["type"]
        subj = index[eid][1]
        seen = set()
        for rel_obj in rec["fm"].get("relations", []) or []:
            rel, to = rel_obj.get("rel"), rel_obj.get("to")
            if not rel or not to:
                continue
            tgt = tgt_uri(to)
            if tgt is None:
                continue  # 断链在校验层报告，这里跳过
            prop = O[_rel_prop(rel)]
            triple = (subj, prop, tgt)
            if triple not in seen:
                seen.add(triple)
                g.add(triple)
        # 正文 [[id]] → mentions
        for wl in rec["wikilinks"]:
            tgt = tgt_uri(wl["id"])
            if tgt is not None:
                g.add((subj, O["mentions"], tgt))


# 中文条号 → 阿拉伯（第十条→10），金规 116 检查 article_no → clause/cl-{n}
_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_to_int(s: str) -> int:
    s = (s or "").replace("第", "").replace("条", "").strip()
    if s.isdigit():
        return int(s)
    if "十" in s:
        left, _, right = s.partition("十")
        tens = _CN_DIGIT.get(left, 1) if left else 1
        total = tens * 10
        if right:
            total += _CN_DIGIT.get(right, 0)
        return total
    return _CN_DIGIT.get(s, 0)


def _compile_jg24_checks(g: Graph, index: dict) -> dict:
    """把金规〔2024〕24号 116 项检查（data/checks/jg24-checks.json）编入 canonical RDF。

    形状与 v1.6.0 93号文检查、原硬编码 1.1 完全一致（InspectionCheck + CheckElement +
    Clause + citesClause/hasElement 边）。只编"检查项+检查要素+法条引用"这一骨架；
    度量/方法步骤/访谈问题/常见问题等 richer 形态仍留 SQLite 平台语义层（checks_import.py），
    不进 canonical（TBox 暂无对应类，避免越界扩骨架）。
    """
    O = iris.ONT
    jpath = BASE_DIR / "data" / "checks" / "jg24-checks.json"
    data = json.loads(jpath.read_text(encoding="utf-8"))
    checks = data["checks"]

    clause_uris: set[URIRef] = set()
    n_check = n_el = 0
    for c in checks:
        subj = URIRef(iris.KB_IRI + "inspectioncheck/ic-" + c["id"].replace(".", "-"))
        g.add((subj, RDF.type, O["InspectionCheck"]))
        g.add((subj, RDFS.label, Literal(c["title"], lang="zh")))
        g.add((subj, O["checkCode"], Literal(c["id"])))
        g.add((subj, O["domain"], Literal(c["domain"])))
        g.add((subj, O["priority"], Literal(c["priority"])))
        g.add((subj, O["articleNo"], Literal(c.get("article_no", ""))))
        g.add((subj, O["sourcePath"], Literal(f"data/checks/jg24-checks.json#{c['id']}")))
        # 法条节点（article_no 第X条 → clause/cl-X）；同一法条被多检查引用时幂等
        clause = URIRef(iris.KB_IRI + "clause/cl-" + str(_cn_to_int(c.get("article_no", ""))))
        if clause not in clause_uris:
            g.add((clause, RDF.type, O["Clause"]))
            g.add((clause, O["articleNo"], Literal(c.get("article_no", ""))))
            clause_uris.add(clause)
        g.add((subj, O["citesClause"], clause))
        # 检查要素（含 focus L1-L5）
        for el in c.get("checklist", []):
            en = URIRef(iris.KB_IRI + "checkelement/" + el["code"].replace(".", "-"))
            g.add((en, RDF.type, O["CheckElement"]))
            g.add((en, RDFS.label, Literal(el["text"], lang="zh")))
            g.add((en, O["elementCode"], Literal(el["code"])))
            if el.get("criteria"):
                g.add((en, O["criteria"], Literal(el["criteria"], lang="zh")))
            for lv in el.get("focus_levels", []):
                g.add((en, O["focusLevel"], Literal(lv)))
            g.add((subj, O["hasElement"], en))
            n_el += 1
        n_check += 1
    return {"checks": n_check, "elements": n_el, "clauses": len(clause_uris)}


def cross_check_codes(recs: list[dict], codes: dict) -> list[str]:
    """MD frontmatter 控制 ↔ control-codes.csv 权威登记表 双向对账。

    返回漂移差异列表（空=一致）：集合不等、CSV 有 MD 缺、MD 有码 CSV 未登记、
    同 code/layer/title 不一致。干净数据应为 0。
    """
    md_ctrl = {r["id"]: r for r in recs if r["type"] == "control"}
    errs: list[str] = []
    if len(md_ctrl) != len(codes):
        errs.append(f"控制集合数量不一致: MD={len(md_ctrl)} vs CSV={len(codes)}")
    only_csv = set(codes) - set(md_ctrl)
    only_md = set(md_ctrl) - set(codes)
    for rid in sorted(only_csv):
        errs.append(f"CSV 有登记但 MD 缺该控制: {rid}")
    for rid in sorted(only_md):
        errs.append(f"MD 有控制但 CSV 未登记: {rid}")
    for rid in sorted(set(md_ctrl) & set(codes)):
        fm = md_ctrl[rid]["fm"]
        csv = codes[rid]
        if str(fm.get("code", "")).strip() != csv["code"]:
            errs.append(f"{rid} code 漂移: MD={fm.get('code')!r} vs CSV={csv['code']!r}")
        if str(fm.get("layer", "")).strip() != csv["layer"]:
            errs.append(f"{rid} layer 漂移: MD={fm.get('layer')!r} vs CSV={csv['layer']!r}")
        if str(fm.get("title", "")).strip() != csv["title"]:
            errs.append(f"{rid} title 漂移: MD={fm.get('title')!r} vs CSV={csv['title']!r}")
    return errs


def assert_tbox_consistency(schema: dict) -> list[str]:
    """编译器 TBox 与 ontology.yaml schema 一致性断言：类/关系/枚举不漂移。"""
    from . import schema as _sch
    errs: list[str] = []
    # 编译器内置实体类（_add_tbox 声明的）应覆盖 yaml 全部 11 类型
    builtin_types = {"Term", "Law", "Standard", "Control", "Role", "Case", "Organization",
                     "Scenario", "Solution", "Guide", "Topic", "Clause", "InspectionCheck",
                     "CheckElement"}
    yaml_types = set(schema["entity_types"])  # 11
    # yaml 11 类型都应有对应类（首字母大写）
    for yt in sorted(yaml_types):
        cls = yt.capitalize() if yt != "standard" else "Standard"
        if cls not in builtin_types:
            errs.append(f"ontology.yaml 实体类型 {yt} 未在编译器 TBox 声明")
    # 枚举必须来自 yaml（在 shacl.py 消费），这里只校验 yaml 解析非空
    for k in ("level", "status", "layer", "lifecycle", "controlType"):
        if not schema["enums"].get(k):
            errs.append(f"ontology.yaml 枚举缺失或解析失败: {k}")
    return errs


def compile_canonical() -> tuple[Graph, dict]:
    """编译主入口：返回 (canonical RDF 图, 统计 dict)。确定性。"""
    from . import schema as _sch
    g = Graph()
    g.bind("ont", iris.ONT_IRI.rstrip("/") + "/#")
    g.bind("kb", iris.KB_IRI)
    g.bind("run", iris.RUN_IRI)
    g.bind("skos", iris.W3_SKOS)
    _add_tbox(g)
    recs = scan_mvp()
    codes = _sch.load_control_codes()           # CT 编码权威登记表（只读）
    schema = _sch.load_ontology_schema()        # TBox schema 权威（只读）
    index = _compile_entities(g, recs, codes)
    registry = load_registry()
    _resolve_relations(g, recs, index, registry)
    jg = _compile_jg24_checks(g, index)
    # v1.6.0：93号文 13 个自查检查项（复用 InspectionCheck 形状）；law/topic 已由通用管线编入 index
    from . import doc93
    d93 = doc93.compile_doc93(g, index)
    n_term = sum(1 for t, _ in index.values() if t == "term")
    n_ctrl = sum(1 for t, _ in index.values() if t == "control")
    n_law = sum(1 for t, _ in index.values() if t == "law")
    n_std = sum(1 for t, _ in index.values() if t == "standard")
    n_org = sum(1 for t, _ in index.values() if t == "organization")
    n_topic = sum(1 for t, _ in index.values() if t == "topic")
    n_sol = sum(1 for t, _ in index.values() if t == "solution")
    n_guide = sum(1 for t, _ in index.values() if t == "guide")
    code_drift = cross_check_codes(recs, codes)
    tbox_drift = assert_tbox_consistency(schema)
    stats = {"terms": n_term, "controls": n_ctrl,
              "check11": jg["checks"], "check11_elements": jg["elements"], "triples": len(g),
              "code_drift": code_drift, "tbox_drift": tbox_drift,
              "csv_rows": len(codes), "entity_types": len(schema["entity_types"]),
              "relation_types": len(schema["relation_types"]),
              "solutions": n_sol, "guides": n_guide, "topics": n_topic,
              "jg24_checks": jg["checks"], "jg24_elements": jg["elements"],
              "jg24_clauses": jg["clauses"],
              "doc93_law": n_law, "doc93_topic": n_topic,
              "doc93_checks": d93["checks"], "doc93_elements": d93["elements"],
              "laws": n_law, "standards": n_std, "organizations": n_org}
    return g, stats
