"""RDF 语义层：从 SQLite 已发布实体物化为内存图，支持 SPARQL 与导出。
变更即失效重建：每次 materialize 都从 entities(status=published) 重新构建。
"""
from __future__ import annotations
import json
from rdflib import Graph, URIRef, Literal, RDF, RDFS, XSD, SKOS
from .ns import DSEC, DSECR, DSECB
from .tbox import build_tbox, build_shacl_shapes
from ..db import db
from ..config import BASE_SNAPSHOT_TTL

# 实体类型 -> RDF 类
TYPE_TO_CLASS = {
    "Law": DSEC.Law, "Clause": DSEC.Clause, "Obligation": DSEC.Obligation,
    "Control": DSEC.Control, "DataAsset": DSEC.DataAsset,
    "EvidenceRequirement": DSEC.EvidenceRequirement, "EvidenceRecord": DSEC.EvidenceRecord,
    "Assessment": DSEC.Assessment, "CheckItem": DSEC.CheckItem,
    "Finding": DSEC.Finding, "Remediation": DSEC.Remediation,
    "KnowledgeGapProposal": DSEC.KnowledgeGapProposal,
    # v1.1.0 监管检查语义层
    "InspectionCheck": DSEC.InspectionCheck, "CheckElement": DSEC.CheckElement,
    "Metric": DSEC.Metric, "InspectionMethodStep": DSEC.InspectionMethodStep,
    "InterviewQuestion": DSEC.InterviewQuestion, "VerdictRule": DSEC.VerdictRule,
    "FindingPattern": DSEC.FindingPattern, "InspectionRun": DSEC.InspectionRun,
    "CheckResult": DSEC.CheckResult, "FocusLevel": DSEC.FocusLevel,
    "ControlPlaceholder": DSEC.ControlPlaceholder,
}

# dataJSON 中哪些键是对象属性（指向其他实体/概念），其余为数据属性
OBJ_KEYS = {
    "clauseOf", "imposes", "implementsObligation", "requiresEvidence", "governed_by",
    "hasEvidenceRecord", "evidencesControl", "fulfillsRequirement", "hasClassification",
    "evaluatesObligation", "evaluatesControl", "evaluatesAsset", "producesFinding",
    "triggersRemediation", "raisesProposal", "proposesTarget",
    # v1.1.0
    "citesClause", "hasElement", "elementFocus", "measuredBy", "hasMethodStep",
    "hasInterview", "verdictRule", "hasFindingPattern", "relatedCheck",
    "mapsToTerm", "mapsToControl", "runsCheck", "producesResult",
    "checkResultOfCheck", "resultRun",
    # v1.1.2
    "suggestsControl", "provisionalBaseControl",
}
DATE_KEYS = {"issued", "effective", "collectedAt", "ranAt", "dueDate"}


def res_uri(etype: str, eid: str) -> URIRef:
    return DSECR[f"{etype.lower()}/{eid}"]


def _class_uri_for_ref(ref: str) -> URIRef:
    """关系目标 ref 形如 'Obligation:ob03' / 'cls/important' / 'focus/L1' / 'baseTerm:slug'。"""
    if ref.startswith("cls/") or ref.startswith("focus/"):
        return DSEC[ref]
    if ref.startswith("baseTerm:"):
        return DSECB["term/" + ref.split(":", 1)[1]]
    if ref.startswith("baseControl:"):
        return DSECB["control/" + ref.split(":", 1)[1]]
    if ":" in ref:
        cid, rid = ref.split(":", 1)
        return res_uri(cid, rid)
    return DSECR[ref]


_TYPE_BY_REF_PREFIX = {
    "Law": DSEC.Law, "Clause": DSEC.Clause, "Obligation": DSEC.Obligation,
    "Control": DSEC.Control, "DataAsset": DSEC.DataAsset,
    "EvidenceRequirement": DSEC.EvidenceRequirement,
    "EvidenceRecord": DSEC.EvidenceRecord, "CheckItem": DSEC.CheckItem,
    "Finding": DSEC.Finding, "Remediation": DSEC.Remediation,
    "KnowledgeGapProposal": DSEC.KnowledgeGapProposal,
    "InspectionCheck": DSEC.InspectionCheck, "CheckElement": DSEC.CheckElement,
    "Metric": DSEC.Metric, "InspectionMethodStep": DSEC.InspectionMethodStep,
    "InterviewQuestion": DSEC.InterviewQuestion, "VerdictRule": DSEC.VerdictRule,
    "FindingPattern": DSEC.FindingPattern, "InspectionRun": DSEC.InspectionRun,
    "CheckResult": DSEC.CheckResult, "ControlPlaceholder": DSEC.ControlPlaceholder,
}


def _declare_ref_type(g: Graph, ref: str) -> None:
    """为被引用节点补 rdf:type，使 sh:class 约束在单实体校验图中可判定。"""
    if ref.startswith("cls/") or ref.startswith("focus/"):
        g.add((DSEC[ref], RDF.type, SKOS.Concept))
    elif ref.startswith("baseTerm:"):
        g.add((DSECB["term/" + ref.split(":", 1)[1]], RDF.type, DSECB["term"]))
    elif ref.startswith("baseControl:"):
        g.add((DSECB["control/" + ref.split(":", 1)[1]], RDF.type, DSECB["control"]))
    elif ":" in ref:
        cid, _ = ref.split(":", 1)
        t = _TYPE_BY_REF_PREFIX.get(cid)
        if t:
            g.add((res_uri(cid, ref.split(":", 1)[1]), RDF.type, t))


def add_entity_triples(g: Graph, etype: str, eid: str, data: dict, relations: list) -> None:
    subj = res_uri(etype, eid)
    g.add((subj, RDF.type, TYPE_TO_CLASS[etype]))
    for k, v in data.items():
        if v is None or v == "" or v == []:
            continue
        pred = DSEC[k]
        if k in OBJ_KEYS:
            targets = v if isinstance(v, list) else [v]
            for t in targets:
                _declare_ref_type(g, str(t))
                g.add((subj, pred, _class_uri_for_ref(str(t))))
        else:
            if k in DATE_KEYS:
                g.add((subj, pred, Literal(str(v), datatype=XSD.date)))
            else:
                g.add((subj, pred, Literal(str(v))))
    # relations: [{p, o}]  o 形如 'Obligation:ob03'
    for rel in relations:
        _declare_ref_type(g, rel["o"])
        g.add((subj, DSEC[rel["p"]], _class_uri_for_ref(rel["o"])))


def materialize(include_base: bool = True, include_candidates: bool = False) -> Graph:
    g = build_tbox()
    if include_base and BASE_SNAPSHOT_TTL.exists():
        g.parse(BASE_SNAPSHOT_TTL.as_posix(), format="turtle")
    where = "status != 'rejected'" if include_candidates else "status='published'"
    with db() as conn:
        rows = conn.execute(
            f"SELECT id,type,dataJSON,relationsJSON FROM entities WHERE {where}"
        ).fetchall()
    for r in rows:
        add_entity_triples(g, r["type"], r["id"],
                          json.loads(r["dataJSON"]), json.loads(r["relationsJSON"]))
    return g


def export_turtle() -> str:
    g = materialize()
    return g.serialize(format="turtle")


def export_shapes() -> str:
    return build_shacl_shapes().serialize(format="turtle")


def graph_for_entity(etype: str, eid: str, data: dict, relations: list) -> Graph:
    """校验图：全量实体(含候选，使被引用节点完整) + 覆盖焦点实体最新(可能编辑过)数据。"""
    g = materialize(include_candidates=True)
    subj = res_uri(etype, eid)
    for p, o in list(g.predicate_objects(subj)):
        g.remove((subj, p, o))
    add_entity_triples(g, etype, eid, data, relations)
    return g
