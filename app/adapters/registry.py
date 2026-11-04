"""适配器注册中心：装配时把已实现的 Adapter 注册进来，按 name 查询、按 capability 过滤。

对齐 EKOS §4.5：启动扫描注册到注册中心，配置里写 retriever.backend=... 切实现。
本实现刻意保持极简——进程内字典，无外部依赖；注册即"插上插座"。
"""
from __future__ import annotations

from .base import Adapter


class Registry:
    """name -> Adapter 的注册中心。支持 register/get/list/by_capability。"""

    def __init__(self) -> None:
        self._adapters: dict[str, Adapter] = {}

    def register(self, adapter: Adapter) -> Adapter:
        if not getattr(adapter, "name", None):
            raise ValueError("adapter.name 不能为空，无法注册")
        self._adapters[adapter.name] = adapter
        return adapter

    def get(self, name: str) -> Adapter:
        if name not in self._adapters:
            raise KeyError(f"未注册适配器: {name!r}；已注册: {sorted(self._adapters)}")
        return self._adapters[name]

    def list(self, kind: str | None = None) -> list[Adapter]:
        """列出全部适配器；可选按能力域（kind）过滤。按 (kind, name) 排序，输出稳定。"""
        items = list(self._adapters.values())
        if kind:
            items = [a for a in items if a.kind == kind]
        return sorted(items, key=lambda a: (a.kind, a.name))

    def by_capability(self, cap: str) -> list[Adapter]:
        """按能力点过滤，如 by_capability('sparql.select') 列出所有能跑 SPARQL 的检索器。"""
        return [a for a in self._adapters.values() if cap in a.capabilities()]

    def names(self) -> list[str]:
        return sorted(self._adapters)

    def health_report(self) -> list[dict]:
        """装配自检：每个适配器一行 describe（含 health）。"""
        return [a.describe() for a in self.list()]

    def __len__(self) -> int:
        return len(self._adapters)

    def __contains__(self, name: str) -> bool:
        return name in self._adapters
