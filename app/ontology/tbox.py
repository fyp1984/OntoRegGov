"""TBox：领域类、对象/数据属性、SKOS 词表、SHACL NodeShapes。
所有形状以真实 RDFLib 图构造，pyshacl 可直接执行。
"""
from __future__ import annotations
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, OWL, XSD, SKOS
from .ns import (DSEC, DSECR, DSECB, SH, NEW_CLASSES, CHECK_CLASSES, DATA_CLASSIFICATION,
                 FORCE, VALIDITY, CONTROL_KIND, PRIORITY, EVIDENCE_KIND,
                 RECORD_STATUS, CHECK_RESULT, SEVERITY, DOMAIN, FOCUS_LEVEL, CHECK3,
                 STEPS_KIND, RELTYPE, CONTROL_LAYER, ALIGN_STATUS)


def _lit(v, lang="zh"):
    return Literal(v, lang=lang)


def build_tbox() -> Graph:
    g = Graph()
    g.bind("dsec", DSEC)
    g.bind("dsecr", DSECR)
    g.bind("skos", SKOS)
    g.bind("owl", OWL)
    g.bind("sh", SH)

    # ---- 类（复用底座类做 owl:equivalentClass）----
    base_equiv = {
        "Law": "law", "Standard": "standard", "Term": "term", "Role": "role",
        "Organization": "organization", "Control": "baseControl",
        "Case": "case", "Scenario": "scenario",
    }
    for cls in ["Law", "Standard"] + NEW_CLASSES + CHECK_CLASSES:
        c = DSEC[cls]
        g.add((c, RDF.type, OWL.Class))
        g.add((c, RDFS.label, _lit(CLS_ZH[cls])))
    for ours, base in base_equiv.items():
        g.add((DSEC[ours], OWL.equivalentClass, DSECB[base]))
        g.add((DSEC[ours], RDFS.seeAlso, DSECB[base]))

    # ---- 数据属性 ----
    dataprops = {
        "title": XSD.string, "docNo": XSD.string, "authority": XSD.string,
        "issued": XSD.date, "effective": XSD.date, "validity": XSD.string,
        "clauseNo": XSD.string, "text": XSD.string, "force": XSD.string,
        "subject": XSD.string, "code": XSD.string, "controlKind": XSD.string,
        "priority": XSD.string, "judgementCriteria": XSD.string, "method": XSD.string,
        "assetId": XSD.string, "name": XSD.string, "owner": XSD.string, "system": XSD.string,
        "evidenceKind": XSD.string, "points": XSD.string, "recordId": XSD.string,
        "status": XSD.string, "collectedAt": XSD.string, "locator": XSD.string,
        "checkNo": XSD.string, "result": XSD.string, "findingNo": XSD.string,
        "severity": XSD.string, "gapKind": XSD.string, "detail": XSD.string,
        "remNo": XSD.string, "action": XSD.string, "dueDate": XSD.string,
        "propNo": XSD.string, "reason": XSD.string, "targetKind": XSD.string,
        "runId": XSD.string, "ranAt": XSD.string, "overall": XSD.string,
        "summary": XSD.string, "chapter": XSD.string,
        # v1.1.0 监管检查语义层
        "checkCode": XSD.string, "domain": XSD.string, "domainLabel": XSD.string,
        "regulation": XSD.string, "articleNo": XSD.string, "articleText": XSD.string,
        "tip": XSD.string, "criteria": XSD.string, "focusLevels": XSD.string,
        "stepKind": XSD.string, "stepNo": XSD.string, "action": XSD.string,
        "focus": XSD.string, "evidenceRequired": XSD.string, "dataSource": XSD.string,
        "threshold": XSD.string, "target": XSD.string, "question": XSD.string,
        "crossCheck": XSD.string, "verdictPass": XSD.string, "verdictPartial": XSD.string,
        "verdictFail": XSD.string, "rank": XSD.string, "problem": XSD.string,
        "rootCause": XSD.string, "remediation": XSD.string, "relType": XSD.string,
        "relatedRaw": XSD.string, "inspectedTarget": XSD.string, "inspector": XSD.string,
        "summaryJSON": XSD.string, "elementVerdict": XSD.string, "metricActual": XSD.string,
        "gapKind": XSD.string, "why": XSD.string,
        # v1.1.2/v1.2.0 控制需求占位（v1.2.0 起支持与 v1.5 权威控制正式对齐）
        "controlCodeHint": XSD.string, "controlName": XSD.string,
        "suggestedLayer": XSD.string, "controlTypeHint": XSD.string,
        "alignmentStatus": XSD.string, "rationale": XSD.string,
        "sourceCheckCodes": XSD.string, "articleRefs": XSD.string,
        "baseControlTitle": XSD.string, "baseControlId": XSD.string,
        "ctCode": XSD.string, "ctLayer": XSD.string,
    }
    for p, dt in dataprops.items():
        g.add((DSEC[p], RDF.type, OWL.DatatypeProperty))
        g.add((DSEC[p], RDFS.range, dt))

    # ---- 对象属性 ----
    objprops = {
        "hasClause": (DSEC.Law, DSEC.Clause),
        "clauseOf": (DSEC.Clause, DSEC.Law),
        "imposes": (DSEC.Clause, DSEC.Obligation),
        "implementsObligation": (DSEC.Control, DSEC.Obligation),
        "requiresEvidence": (DSEC.Control, DSEC.EvidenceRequirement),
        "governed_by": (DSEC.DataAsset, DSEC.Obligation),
        "hasEvidenceRecord": (DSEC.DataAsset, DSEC.EvidenceRecord),
        "evidencesControl": (DSEC.EvidenceRecord, DSEC.Control),
        "fulfillsRequirement": (DSEC.EvidenceRecord, DSEC.EvidenceRequirement),
        "hasClassification": (DSEC.DataAsset, SKOS.Concept),
        "evaluatesObligation": (DSEC.CheckItem, DSEC.Obligation),
        "evaluatesControl": (DSEC.CheckItem, DSEC.Control),
        "evaluatesAsset": (DSEC.CheckItem, DSEC.DataAsset),
        "producesFinding": (DSEC.CheckItem, DSEC.Finding),
        "triggersRemediation": (DSEC.Finding, DSEC.Remediation),
        "raisesProposal": (DSEC.CheckItem, DSEC.KnowledgeGapProposal),
        "proposesTarget": (DSEC.KnowledgeGapProposal, DSEC.Control),
        # v1.1.0 监管检查语义层
        "citesClause": (DSEC.InspectionCheck, DSEC.Clause),
        "hasElement": (DSEC.InspectionCheck, DSEC.CheckElement),
        "elementFocus": (DSEC.CheckElement, DSEC.FocusLevel),
        "measuredBy": (DSEC.InspectionCheck, DSEC.Metric),
        "hasMethodStep": (DSEC.InspectionCheck, DSEC.InspectionMethodStep),
        "hasInterview": (DSEC.InspectionCheck, DSEC.InterviewQuestion),
        "verdictRule": (DSEC.InspectionCheck, DSEC.VerdictRule),
        "hasFindingPattern": (DSEC.InspectionCheck, DSEC.FindingPattern),
        "relatedCheck": (DSEC.InspectionCheck, DSEC.InspectionCheck),
        "mapsToControl": (DSEC.InspectionCheck, DSEC.Control),
        "runsCheck": (DSEC.InspectionRun, DSEC.InspectionCheck),
        "producesResult": (DSEC.InspectionRun, DSEC.CheckResult),
        "checkResultOfCheck": (DSEC.CheckResult, DSEC.InspectionCheck),
        "resultRun": (DSEC.CheckResult, DSEC.InspectionRun),
        # v1.1.2 控制需求占位
        "suggestsControl": (DSEC.InspectionCheck, DSEC.ControlPlaceholder),
        # v1.2.0 正式对齐：占位 → v1.5 权威控制（底座投影 control）
        "mapsToFormalControl": (DSEC.ControlPlaceholder, DSEC.Control),
    }
    for p, (d, r) in objprops.items():
        g.add((DSEC[p], RDF.type, OWL.ObjectProperty))
        g.add((DSEC[p], RDFS.domain, d))
        g.add((DSEC[p], RDFS.range, r))
    g.add((DSEC.clauseOf, OWL.inverseOf, DSEC.hasClause))

    # ---- SKOS 数据分级词表（据第十八条）----
    scheme = DSEC.DataClassificationScheme
    g.add((scheme, RDF.type, SKOS.ConceptScheme))
    g.add((scheme, RDFS.label, _lit("数据分级概念方案（金规24号第十八条）")))
    for slug, label, parent in DATA_CLASSIFICATION:
        c = DSEC["cls/" + slug]
        g.add((c, RDF.type, SKOS.Concept))
        g.add((c, SKOS.prefLabel, _lit(label)))
        g.add((c, SKOS.inScheme, scheme))
        if parent:
            g.add((c, SKOS.broader, DSEC["cls/" + parent]))
            g.add((DSEC["cls/" + parent], SKOS.narrower, c))

    # ---- SKOS 检查关注层级 FocusLevel（L1-L5；L1-L3制度层/L4证据层/L5效果层）----
    focus_scheme = DSEC.FocusLevelScheme
    g.add((focus_scheme, RDF.type, SKOS.ConceptScheme))
    g.add((focus_scheme, RDFS.label, _lit("监管检查关注层级（L1-L5）")))
    focus_defs = {
        "L1": "制度层·是否建立", "L2": "制度层·是否明确", "L3": "制度层·是否闭环",
        "L4": "证据层·是否有运行记录/证据", "L5": "效果层·实际运行效果与度量",
    }
    for lv in FOCUS_LEVEL:
        c = DSEC["focus/" + lv]
        g.add((c, RDF.type, SKOS.Concept))
        g.add((c, SKOS.prefLabel, _lit(lv)))
        g.add((c, SKOS.definition, _lit(focus_defs[lv])))
        g.add((c, SKOS.inScheme, focus_scheme))
    return g


CLS_ZH = {
    "Law": "法律法规", "Standard": "标准", "Clause": "条款", "Obligation": "义务",
    "Control": "控制项", "DataAsset": "数据资产", "EvidenceRequirement": "证据要求",
    "EvidenceRecord": "证据记录", "CheckItem": "检查项", "Finding": "风险发现",
    "Remediation": "整改", "KnowledgeGapProposal": "知识缺口提案", "Assessment": "检查运行",
    "InspectionCheck": "监管检查项", "CheckElement": "检查要素", "Metric": "度量指标",
    "InspectionMethodStep": "检查方法步骤", "InterviewQuestion": "访谈问题",
    "VerdictRule": "三档判定要点", "FindingPattern": "常见问题范式",
    "InspectionRun": "监管检查运行", "CheckResult": "检查结论", "FocusLevel": "关注层级",
    "ControlPlaceholder": "控制需求占位(待对齐)",
}


def _node_shape(g: Graph, name: str, focus: URIRef) -> URIRef:
    s = DSEC[name]
    g.add((s, RDF.type, SH.NodeShape))
    g.add((s, SH.targetClass, focus))
    g.add((s, SH.closed, Literal(True)))
    g.add((s, SH.ignoredProperties, RDF.type))
    return s


def build_shacl_shapes() -> Graph:
    """构造 SHACL shapes 图（每类一个 NodeShape，closed）。"""
    g = Graph()
    g.bind("sh", SH); g.bind("dsec", DSEC); g.bind("skos", SKOS); g.bind("xsd", XSD)

    def shape(name, focus):
        s = DSEC[name]
        g.add((s, RDF.type, SH.NodeShape))
        g.add((s, SH.targetClass, focus))
        g.add((s, SH.closed, Literal(True)))
        # ignoredProperties 必须是 RDF list
        from rdflib import BNode, RDF as _R
        lst = BNode()
        g.add((s, SH.ignoredProperties, lst))
        g.add((lst, _R.first, RDF.type))
        g.add((lst, _R.rest, _R.nil))
        return s

    def sc(shape_node, path, min_count=None, in_list=None, datatype=None, klass=None):
        from rdflib import BNode
        b = BNode()
        g.add((shape_node, SH.property, b))
        g.add((b, SH.path, path))
        if min_count is not None:
            g.add((b, SH.minCount, Literal(min_count)))
        if in_list:
            lst = [Literal(x) for x in in_list]
            rn = _rdf_list(g, lst)
            g.add((b, SH["in"], rn))
        if datatype:
            g.add((b, SH.datatype, datatype))
        if klass:
            g.add((b, SH["class"], klass))

    # Law
    s = shape("LawShape", DSEC.Law)
    sc(s, DSEC.title, min_count=1)
    sc(s, DSEC.authority, min_count=1)
    sc(s, DSEC.issued, min_count=1, datatype=XSD.date)
    sc(s, DSEC.effective, min_count=1, datatype=XSD.date)
    sc(s, DSEC.validity, min_count=1, in_list=VALIDITY)
    sc(s, DSEC.docNo); sc(s, DSEC.summary); sc(s, DSEC.official_url)

    # Clause
    s = shape("ClauseShape", DSEC.Clause)
    sc(s, DSEC.clauseNo, min_count=1)
    sc(s, DSEC.title, min_count=1)
    sc(s, DSEC.clauseOf, min_count=1, klass=DSEC.Law)
    sc(s, DSEC.chapter); sc(s, DSEC.articleText)

    # Obligation
    s = shape("ObligationShape", DSEC.Obligation)
    sc(s, DSEC.code, min_count=1)
    sc(s, DSEC.text, min_count=1)
    sc(s, DSEC.force, min_count=1, in_list=FORCE)
    sc(s, DSEC.clauseOf, min_count=1, klass=DSEC.Clause)  # obligation 归属条款 imposes
    sc(s, DSEC.subject)

    # Control
    s = shape("ControlShape", DSEC.Control)
    sc(s, DSEC.code, min_count=1)
    sc(s, DSEC.title, min_count=1)
    sc(s, DSEC.priority, min_count=1, in_list=PRIORITY)
    sc(s, DSEC.controlKind, min_count=1, in_list=CONTROL_KIND)
    sc(s, DSEC.implementsObligation, min_count=1, klass=DSEC.Obligation)
    sc(s, DSEC.requiresEvidence, min_count=1, klass=DSEC.EvidenceRequirement)
    sc(s, DSEC.judgementCriteria); sc(s, DSEC.method)

    # DataAsset
    s = shape("DataAssetShape", DSEC.DataAsset)
    sc(s, DSEC.name, min_count=1)
    sc(s, DSEC.owner, min_count=1)
    sc(s, DSEC.hasClassification, min_count=1, klass=SKOS.Concept)
    sc(s, DSEC.governed_by, min_count=1, klass=DSEC.Obligation)
    sc(s, DSEC.system); sc(s, DSEC.assetId)

    # EvidenceRequirement
    s = shape("EvidenceRequirementShape", DSEC.EvidenceRequirement)
    sc(s, DSEC.code, min_count=1)
    sc(s, DSEC.name, min_count=1)
    sc(s, DSEC.evidenceKind, min_count=1, in_list=EVIDENCE_KIND)
    sc(s, DSEC.points)

    # EvidenceRecord
    s = shape("EvidenceRecordShape", DSEC.EvidenceRecord)
    sc(s, DSEC.recordId, min_count=1)
    sc(s, DSEC.name, min_count=1)
    sc(s, DSEC.status, min_count=1, in_list=RECORD_STATUS)
    sc(s, DSEC.evidencesControl, min_count=1, klass=DSEC.Control)
    sc(s, DSEC.fulfillsRequirement, min_count=1, klass=DSEC.EvidenceRequirement)
    sc(s, DSEC.collectedAt); sc(s, DSEC.locator); sc(s, DSEC.asset)

    # CheckItem
    s = shape("CheckItemShape", DSEC.CheckItem)
    sc(s, DSEC.evaluatesObligation, min_count=1, klass=DSEC.Obligation)
    sc(s, DSEC.evaluatesControl, min_count=1, klass=DSEC.Control)
    sc(s, DSEC.evaluatesAsset, min_count=1, klass=DSEC.DataAsset)
    sc(s, DSEC.result, min_count=1, in_list=CHECK_RESULT)

    # Finding
    s = shape("FindingShape", DSEC.Finding)
    sc(s, DSEC.severity, min_count=1, in_list=SEVERITY)
    sc(s, DSEC.gapKind, min_count=1)

    # KnowledgeGapProposal
    s = shape("ProposalShape", DSEC.KnowledgeGapProposal)
    sc(s, DSEC.reason, min_count=1)
    sc(s, DSEC.status, min_count=1)
    sc(s, DSEC.targetKind, min_count=1)

    # ---- v1.1.0 监管检查语义层（closed；仅列出实际物化的谓词）----
    # InspectionCheck（定义层·检查项）
    s = shape("InspectionCheckShape", DSEC.InspectionCheck)
    sc(s, DSEC.checkCode, min_count=1)
    sc(s, DSEC.title, min_count=1)
    sc(s, DSEC.domain, min_count=1, in_list=DOMAIN)
    sc(s, DSEC.priority, min_count=1, in_list=PRIORITY)
    sc(s, DSEC.citesClause, min_count=1, klass=DSEC.Clause)
    sc(s, DSEC.hasElement, min_count=1, klass=DSEC.CheckElement)
    for p in [DSEC.domainLabel, DSEC.regulation, DSEC.articleNo, DSEC.articleText,
              DSEC.tip, DSEC.chapter, DSEC.relatedRaw, DSEC.verdictRule,
              DSEC.hasFindingPattern, DSEC.measuredBy, DSEC.hasMethodStep,
              DSEC.hasInterview, DSEC.relatedCheck, DSEC.mapsToTerm,
              DSEC.suggestsControl]:
        sc(s, p)

    # CheckElement（检查要素）
    s = shape("CheckElementShape", DSEC.CheckElement)
    sc(s, DSEC.code, min_count=1)
    sc(s, DSEC.text, min_count=1)
    sc(s, DSEC.elementFocus, min_count=1, klass=SKOS.Concept)
    sc(s, DSEC.criteria); sc(s, DSEC.requiresEvidence); sc(s, DSEC.focusLevels)

    # CheckResult（运行层·对某检查项的三档结论）
    s = shape("CheckResultShape", DSEC.CheckResult)
    sc(s, DSEC.code); sc(s, DSEC.result, min_count=1, in_list=CHECK3)
    sc(s, DSEC.checkResultOfCheck, min_count=1, klass=DSEC.InspectionCheck)
    sc(s, DSEC.resultRun, min_count=1, klass=DSEC.InspectionRun)
    sc(s, DSEC.elementVerdict); sc(s, DSEC.metricActual); sc(s, DSEC.why)

    # ---- v1.1.2/v1.2.0 控制需求占位（closed；与权威 Control 严格区分）----
    s = shape("ControlPlaceholderShape", DSEC.ControlPlaceholder)
    sc(s, DSEC.controlCodeHint, min_count=1)
    sc(s, DSEC.controlName, min_count=1)
    sc(s, DSEC.suggestedLayer, min_count=1, in_list=CONTROL_LAYER)
    sc(s, DSEC.alignmentStatus, min_count=1, in_list=ALIGN_STATUS)
    for p in [DSEC.controlTypeHint, DSEC.rationale, DSEC.sourceCheckCodes,
              DSEC.articleRefs, DSEC.baseControlTitle, DSEC.baseControlId,
              DSEC.provisionalBaseControl, DSEC.ctCode, DSEC.ctLayer,
              DSEC.mapsToFormalControl]:
        sc(s, p)

    return g


def _rdf_list(g: Graph, items) -> URIRef:
    from rdflib import RDF as _R
    first = items[0]
    rest_uri = None
    rest = items[1:]
    if rest:
        rest_uri = _rdf_list(g, rest)
    node = _BNode(g)
    g.add((node, _R.first, first))
    g.add((node, _R.rest, rest_uri if rest_uri else _R.nil))
    return node


def _BNode(g):
    from rdflib import BNode
    return BNode()
