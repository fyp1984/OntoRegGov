"""置信度：来源权重 + 独立验证源加成 − 时间衰减；LLM 折减与单源封顶。"""
from __future__ import annotations
from ..config import SOURCE_GRADE_WEIGHT, LLM_CONFIDENCE_FACTOR, SINGLE_SOURCE_CAP


def compute(source_grade: str = "B", independent_sources: int = 1,
            age_days: float = 0.0, provenance: str = "rule") -> float:
    base = SOURCE_GRADE_WEIGHT.get(source_grade, 0.5)
    bonus = 0.05 * max(0, independent_sources - 1)     # 独立验证源加成
    decay = min(0.15, age_days / 365.0 * 0.15)          # 时间衰减（上限0.15）
    conf = base + bonus - decay
    if provenance == "llm":
        conf *= LLM_CONFIDENCE_FACTOR
    if independent_sources <= 1:
        conf = min(conf, SINGLE_SOURCE_CAP)             # 单源 N=1 封顶 0.60
    return round(max(0.0, min(1.0, conf)), 3)


def badge(conf: float) -> str:
    if conf >= 0.85:
        return "高"
    if conf >= 0.60:
        return "中"
    return "低"
