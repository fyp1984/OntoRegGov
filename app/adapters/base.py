"""统一 Adapter SPI 契约基类（对齐 EKOS §4.5：name / version / health() / capabilities() / execute()）。

大白话——"插座标准"：任何外部能力（图检索引擎 / LLM / 权限源 / 脱敏网关）要接进平台，
就实现本基类，按统一形状插进来；主机（注册中心 / 主流程）只认这套形状，不关心内部怎么实现。

EKOS 六大原则落点：P2 适配器（一切外部能力过统一 Adapter）、P3 配置驱动（用谁写配置不写死）、
P4 可替换（同能力多实现并存，配置切换）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Adapter(ABC):
    """所有适配器的统一抽象。子类至少给定 name/version/kind，并实现 health/capabilities/execute。"""

    #: 适配器能力域（retriever | llm | policy | masker），用于按域分组
    kind: str = "unknown"

    @property
    @abstractmethod
    def name(self) -> str:
        """SPI 实例名（注册中心主键），如 retriever=memory / llm=openai+rule / policy=open-dev。"""

    @property
    def version(self) -> str:
        """适配器实现版本号，默认 1.0.0；有对齐来源时覆写为对应模块版本。"""
        return "1.0.0"

    @abstractmethod
    def health(self) -> dict:
        """健康检查。统一返回 {"status": ok|degraded|unavailable|not_applicable, ...detail}。"""

    @abstractmethod
    def capabilities(self) -> list[str]:
        """声明本适配器提供的能力点，如 ["sparql.select","sparql.ask"] / ["extract"]。"""

    @abstractmethod
    def execute(self, payload: dict) -> dict:
        """SPI 统一执行入口。payload 的具体形状由各适配器在 docstring 中声明。"""

    @property
    def ok(self) -> bool:
        """便捷判断：健康状态是否为 ok。"""
        try:
            return self.health().get("status") == "ok"
        except Exception:
            return False

    def describe(self) -> dict:
        """注册中心 / 装配自检用的一行摘要。"""
        try:
            hp = self.health()
        except Exception as e:  # 健康检查本身崩了也要如实上报
            hp = {"status": "unavailable", "error": repr(e)}
        return {"name": self.name, "kind": self.kind, "version": self.version,
                "capabilities": self.capabilities(), "health": hp}
