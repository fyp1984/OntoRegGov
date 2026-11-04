"""准入门禁：人在回路、角色分离、AI 候选未复核拦截。"""
from __future__ import annotations


class GateError(Exception):
    code = "gate_blocked"

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


def check_review_separation(actor: str, task_created_by: str) -> None:
    """提交人 ≠ 审核人：同一人不能批准自己的提交。"""
    if actor and task_created_by and actor == task_created_by:
        raise GateError(
            "提交人不能审核自己提交的内容（角色分离）",
            {"actor": actor, "createdBy": task_created_by})


def check_candidate_reviewed(provenance: str, has_review_decision: bool,
                             confidence: float) -> None:
    """AI/自动候选未经人工复核不能 published。"""
    if provenance in ("llm", "rule") and not has_review_decision:
        raise GateError(
            "自动抽取候选未经人工复核，不能直接发布",
            {"provenance": provenance, "confidence": confidence})


def check_source_quality(source_grade: str, has_provenance_span: bool,
                         validity: str = "effective") -> list[str]:
    """自动阻断（可判定子集）：返回阻断原因列表，空=通过。"""
    reasons = []
    if not has_provenance_span:
        reasons.append("无正式出处片段")
    if source_grade not in ("A", "B"):
        reasons.append("来源等级过低/二手转载")
    if validity == "repealed":
        reasons.append("已失效未标用途")
    return reasons
