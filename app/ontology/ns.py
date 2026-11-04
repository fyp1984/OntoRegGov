"""命名空间与受控词表（枚举集中处）。"""
from rdflib import Namespace
from rdflib.namespace import RDF, RDFS, OWL, XSD, SKOS, SH

from ..config import ONTO_NS, RESOURCE_NS, BASE_NS

DSEC = Namespace(ONTO_NS)        # dsec:  TBox
DSECR = Namespace(RESOURCE_NS)  # dsecr: ABox
DSECB = Namespace(BASE_NS)      # dsecb: 底座只读投影

# ---------- 受控枚举（前端下拉/自动补全只取这里与底座词汇） ----------
FORCE = ["mandatory", "recommended"]
VALIDITY = ["effective", "amended", "repealed", "draft"]
CONTROL_KIND = ["preventive", "detective", "corrective"]
PRIORITY = ["P0", "P1", "P2"]
EVIDENCE_KIND = ["documentary", "system_log", "config_snapshot"]
RECORD_STATUS = ["provided", "missing", "invalid"]
CHECK_RESULT = ["conform", "partial", "nonconform", "unknown"]
OVERALL = ["compliant", "partial", "noncompliant"]
SEVERITY = ["high", "med", "low"]
REM_STATUS = ["open", "remediated", "verified"]
PROPOSAL_STATUS = ["open", "in_review", "accepted", "rejected", "closed"]
ENTITY_STATUS = ["candidate", "published", "rejected", "stale", "archived"]

# ---------- 监管检查语义层（v1.1.0：金规24号 116 项检查知识库） ----------
DOMAIN = ["gov", "tech", "cross"]                 # 治理域/科技域/跨域
FOCUS_LEVEL = ["L1", "L2", "L3", "L4", "L5"]      # 制度层L1-L3/证据层L4/效果层L5
CHECK3 = ["pass", "partial", "fail"]              # 运行层三档判定
STEPS_KIND = ["policy", "evidence"]                # 检查方法步骤：查制度/查证据
RELTYPE = ["upper", "extend", "other", "range"]   # relatedCheck 关系类型
# v1.1.2/v1.2.0 控制需求占位（v1.2.0 起 aligned 占位携带权威 CT 编码，唯一事实源=10工程 v1.5）
CONTROL_LAYER = ["EP", "NW", "SVC", "PROTO", "MGMT"]   # 环境/网络/服务/协议/管理层
ALIGN_STATUS = ["pending_alignment", "provisional", "aligned"]

# SKOS 数据分级词表（据金规24号第十八条：核心/重要/一般，一般细分 敏感/其他一般）
DATA_CLASSIFICATION = [
    ("core", "核心数据", None),
    ("important", "重要数据", None),
    ("general", "一般数据", None),
    ("sensitive", "敏感数据", "general"),       # skos:narrower of 一般数据
    ("other-general", "其他一般数据", "general"),
]

# 类型中文标签（本体浏览类树）
CLASS_LABELS = {
    "Law": "法律法规", "Clause": "条款", "Obligation": "义务", "Control": "控制项",
    "DataAsset": "数据资产", "EvidenceRequirement": "证据要求", "EvidenceRecord": "证据记录",
    "CheckItem": "检查项", "Finding": "风险发现", "Remediation": "整改",
    "KnowledgeGapProposal": "知识缺口提案", "Assessment": "检查运行",
    # v1.1.0 监管检查语义层
    "InspectionCheck": "监管检查项(定义)", "CheckElement": "检查要素",
    "Metric": "度量指标", "InspectionMethodStep": "检查方法步骤",
    "InterviewQuestion": "访谈问题", "VerdictRule": "三档判定要点",
    "FindingPattern": "常见问题范式", "InspectionRun": "监管检查运行",
    "CheckResult": "检查结论", "FocusLevel": "关注层级",
    "ControlPlaceholder": "控制需求占位(待对齐)",
    # 底座投影类
    "law": "底座·法律法规", "standard": "底座·标准", "term": "底座·术语",
    "role": "底座·角色", "organization": "底座·机构", "control": "底座·控制措施",
    "case": "底座·案例", "scenario": "底座·行业场景",
}

NEW_CLASSES = ["Clause", "Obligation", "DataAsset", "EvidenceRequirement",
               "EvidenceRecord", "CheckItem", "Finding", "Remediation",
               "KnowledgeGapProposal", "Assessment"]

# v1.1.0 新增定义层/运行层类
CHECK_CLASSES = ["InspectionCheck", "CheckElement", "Metric", "InspectionMethodStep",
                 "InterviewQuestion", "VerdictRule", "FindingPattern",
                 "InspectionRun", "CheckResult", "FocusLevel",
                 "ControlPlaceholder"]
BASE_PROJECTED_CLASSES = ["law", "standard", "term", "role", "organization",
                          "control", "case", "scenario"]
