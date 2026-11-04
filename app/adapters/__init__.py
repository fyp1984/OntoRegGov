"""app.adapters：统一 SPI 适配层（EKOS P2/P3/P4 最小落地）。

装配（P3 配置驱动）：按 app.config.ADAPTERS 构造注册中心。
- retriever：memory/oxigraph/fuseki 三后端全部注册（可列出、可按 capability 过滤、可配置切换）；
  ADAPTERS['retriever'] 决定默认激活哪个；
- llm / policy / masker：按配置名注册单一实现。

向后兼容（硬要求）：旧调用路径（main.py / mcp_server 直调 graph_backend、/api/extract 直调
extractor_llm）完全不受影响；新路径经 get_registry() / get_retriever() / get_llm() 取用。
平台主流程不改。
"""
from __future__ import annotations

from .base import Adapter
from .registry import Registry
from .retriever import RetrieverAdapter
from .llm import LLMAdapter
from .policy import PolicyAdapter
from .masker import MaskerAdapter
from ..config import ADAPTERS

_REGISTRY: Registry | None = None


def build_registry() -> Registry:
    """按 ADAPTERS 配置装配注册中心（每次新建，便于测试/多配置对比）。"""
    reg = Registry()
    # retriever：四后端全部注册 → list() 可见全部，get(backend) 取任一，实现 P4 可替换
    for be in ("memory", "oxigraph", "fuseki", "neo4j"):
        reg.register(RetrieverAdapter(be))
    # llm / policy / masker：按配置注册单一实现
    reg.register(LLMAdapter(name=ADAPTERS["llm"]))
    reg.register(PolicyAdapter())
    reg.register(MaskerAdapter())
    return reg


def get_registry() -> Registry:
    """进程级单例注册中心（首次调用时装配）。"""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_registry()
    return _REGISTRY


def get_retriever() -> RetrieverAdapter:
    """当前配置激活的检索适配器（ADAPTERS['retriever']）。"""
    return get_registry().get(ADAPTERS["retriever"])  # type: ignore[return-value]


def get_llm() -> LLMAdapter:
    return get_registry().get(ADAPTERS["llm"])  # type: ignore[return-value]


def get_policy() -> PolicyAdapter:
    return get_registry().get(ADAPTERS["policy"])  # type: ignore[return-value]


def get_masker() -> MaskerAdapter:
    return get_registry().get(ADAPTERS["masker"])  # type: ignore[return-value]


__all__ = [
    "Adapter", "Registry",
    "RetrieverAdapter", "LLMAdapter", "PolicyAdapter", "MaskerAdapter",
    "build_registry", "get_registry",
    "get_retriever", "get_llm", "get_policy", "get_masker",
]
