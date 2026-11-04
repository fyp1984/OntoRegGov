"""MaskerAdapter：脱敏网关空占位（本期不做，按默认决策 D3 留位）。

理由：本平台知识是公开法规/标准/控制，无 PII 场景；EKOS 的 Vault 脱敏属于"内容层安全"，
本平台是"监管治理层"，二者不重叠。待未来出现 PII 场景，再在此补真实 MaskerAdapter 实现。
"""
from __future__ import annotations

from .base import Adapter


class MaskerAdapter(Adapter):
    kind = "masker"

    @property
    def name(self) -> str:
        return "none"

    @property
    def version(self) -> str:
        return "0.0.0-placeholder"

    def health(self) -> dict:
        return {"status": "not_applicable",
                "note": "本期不做脱敏网关（D3 默认决策）：留 SPI 占位，待 PII 场景再补"}

    def capabilities(self) -> list[str]:
        return []   # 本期不提供任何脱敏能力

    def execute(self, payload: dict) -> dict:
        raise NotImplementedError(
            "MaskerAdapter 本期不做（D3 默认决策）：不落脱敏逻辑；待 PII 场景再补真实实现。")
