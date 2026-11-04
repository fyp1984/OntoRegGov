"""LLMAdapter：包 extractor_llm（OpenAI 兼容）+ rule 降级链。

对齐 EKOS LLMAdapter（LiteLLM 模型路由 + Prompt 外置）——本期只做薄壳：
把现有 extractor_llm 包成 Adapter 形状，不引入 LiteLLM、不做多模型路由（那是 EKOS 企业版）。

降级链（与 extractor_llm.extract 行为一致，不另起逻辑）：
- 有 API key → 走 OpenAI 兼容接口抽取（provenance=llm）；
- 无 key / 调用异常 → 自动降级 extractor_rule（degraded=true，provenance=llm-degraded），不阻断端到端。
"""
from __future__ import annotations

from .base import Adapter
from .. import settings_store
from ..services import extractor_llm


class LLMAdapter(Adapter):
    kind = "llm"

    def __init__(self, name: str = "openai+rule",
                 primary: str = "openai-compatible", fallback: str = "rule") -> None:
        self._name = name
        self.primary = primary      # 主模型实现名（薄壳，本期固定 openai-compatible）
        self.fallback = fallback    # 降级实现名（rule）

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return "1.0.0"

    def health(self) -> dict:
        cfg = settings_store.get_runtime_llm()
        has_key = cfg["api_key_set"]
        return {"status": "ok" if has_key else "degraded",
                "hasApiKey": has_key, "model": cfg["model"],
                "source": cfg["source"], "ui_configured": cfg["ui_configured"],
                "primary": self.primary, "fallback": self.fallback,
                "note": ("已配置 API key，主链可用" if has_key
                         else "无 API key：execute 将自动降级为规则抽取（degraded=true）")}

    def capabilities(self) -> list[str]:
        caps = ["extract", "extract.rule-fallback"]
        cfg = settings_store.get_runtime_llm()
        if cfg["api_key_set"]:
            caps.append("extract.llm")
        return caps

    def execute(self, payload: dict) -> dict:
        """SPI 统一入口。payload: {"text": "...", "documentId": "..."}。
        返回 extractor_llm.extract 的结果：{"candidates":[...], "degraded":bool, "reason"?:str}。"""
        text = payload.get("text", "")
        doc = payload.get("documentId", payload.get("document_id", "doc"))
        return extractor_llm.extract(text, doc)
