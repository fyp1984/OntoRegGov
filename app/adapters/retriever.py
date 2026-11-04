"""RetrieverAdapter：把 graph_backend 三后端（memory / oxigraph / fuseki）包成统一检索适配器。

对齐 EKOS RetrieverAdapter（三路召回可换引擎）。本平台的"检索"= 图查询 + 标准 SPARQL。

硬约束（与 graph_backend.py 注释一致）：
- 判定引擎 / SHACL 闸门 / why 溯源仍走进程内 RDFLib materialize()，保证确定性；
- 本适配器只承接"只读查询 / 对外 SPARQL 端点"，不承接判定。

P4 可替换：memory / oxigraph / fuseki 三个实现并存于注册中心，按配置（ADAPTERS['retriever']）
选中其一；新后端有问题改配置切回 memory，上层（/api/graph/sparql、MCP dsec_graph_sparql）零改动。
"""
from __future__ import annotations

from .base import Adapter
from ..ontology import graph_store as gs
from ..ontology import graph_backend as gb

_BACKENDS = ("memory", "oxigraph", "fuseki", "neo4j")


def _normalize(v):
    """把 oxigraph 返回的数字字符串归一化为 int/float，使 memory/oxigraph 结果形状一致。"""
    if isinstance(v, str):
        s = v.strip()
        if s.lstrip("+-").isdigit():
            try:
                return int(s)
            except ValueError:
                pass
        try:
            if s not in ("", ".") and _is_float(s):
                return float(s)
        except ValueError:
            pass
    return v


def _is_float(s: str) -> bool:
    return s.replace(".", "", 1).lstrip("+-").isdigit() and ("." in s)


class RetrieverAdapter(Adapter):
    """一个实例绑定一个图后端；三个实例（memory/oxigraph/fuseki）即 P4 可替换的三个零件。"""

    kind = "retriever"

    def __init__(self, backend: str = "memory") -> None:
        if backend not in _BACKENDS:
            raise ValueError(f"未知 retriever backend={backend!r}，可选: {_BACKENDS}")
        self._backend = backend

    # ---- SPI 元信息 ----
    @property
    def name(self) -> str:
        return self._backend

    @property
    def version(self) -> str:
        return "1.4.0"   # 与 graph_backend.py 引入版本对齐

    @property
    def backend(self) -> str:
        return self._backend

    # ---- 后端分发（直调 graph_backend 的具体实现，绕过其全局 BACKEND 开关，实现真正可插拔）----
    def query(self, sparql: str) -> list[dict]:
        if self._backend == "memory":
            rows = gb._memory_query(sparql)
        elif self._backend == "oxigraph":
            rows = gb._oxi_query(sparql)
        elif self._backend == "neo4j":
            from ..ontology import neo4j_backend as nb
            rows = nb.query(sparql)
        else:
            rows = gb._fuseki_query(sparql)
        return [{k: _normalize(v) for k, v in row.items()} for row in rows]

    def ask(self, sparql: str) -> bool:
        if self._backend == "memory":
            return bool(gs.materialize().query(sparql))
        if self._backend == "oxigraph":
            return bool(gb._oxi().query(sparql))
        # fuseki
        import json as _json
        raw = gb._http("POST", gb._fuseki_url("query"), sparql.encode("utf-8"),
                       "application/sparql-query", "application/sparql-results+json")
        return bool(_json.loads(raw.decode("utf-8")).get("boolean", False))

    def sync(self, ttl: str | None = None) -> dict:
        """把当前物化图全量镜像到本后端。memory 即物化态，无需镜像。"""
        if self._backend == "memory":
            return {"backend": "memory", "synced": False,
                    "note": "进程内 RDFLib 即物化态，无需镜像"}
        ttl = ttl if ttl is not None else gs.export_turtle()
        if self._backend == "oxigraph":
            stats = gb._oxi_sync(ttl)
        elif self._backend == "neo4j":
            from ..ontology import neo4j_backend as nb
            stats = nb.sync(ttl)
        else:
            stats = gb._fuseki_sync(ttl)
        return {"backend": self._backend, "synced": True,
                "triples": stats.get("triples", stats.get("nodes", -1))}

    def stats(self) -> dict:
        if self._backend == "memory":
            return {"backend": "memory", "triples": len(gs.materialize())}
        if self._backend == "oxigraph":
            if gb._oxi_store is None:
                return {"backend": "oxigraph", "triples": 0, "synced": False}
            return {"backend": "oxigraph", **gb._oxi_stats()}
        if self._backend == "neo4j":
            from ..ontology import neo4j_backend as nb
            return {"backend": "neo4j", **nb.stats()}
        return {"backend": "fuseki", **gb._fuseki_stats()}

    # ---- SPI 契约 ----
    def health(self) -> dict:
        if self._backend == "memory":
            return {"status": "ok", "reachable": True,
                    "triples": len(gs.materialize()),
                    "note": "进程内 RDFLib 物化态，恒可达"}
        if self._backend == "oxigraph":
            try:
                import pyoxigraph  # noqa: F401
            except Exception as e:
                return {"status": "unavailable", "reachable": False,
                        "error": f"pyoxigraph 未安装: {e!r}"}
            synced = gb._oxi_store is not None
            n = self.stats().get("triples", 0) if synced else 0
            return {"status": "ok", "reachable": True, "synced": synced, "triples": n,
                    "note": "进程内 pyoxigraph（可落盘 GRAPH_STORE_FILE）"
                            + ("" if synced else "；尚未 sync()，查询前需先同步")}
        if self._backend == "neo4j":
            from ..ontology import neo4j_backend as nb
            h = nb.health()
            if not h.get("ok"):
                return {"status": "degraded", "reachable": False,
                        "endpoint": h.get("uri"), "error": h.get("error")}
            return {"status": "ok", "reachable": True,
                    "endpoint": h.get("uri"), "nodes": h.get("nodes"), "edges": h.get("edges"),
                    "note": "WeKnora Neo4j 属性图（EKOS 底座直连）"}
        # fuseki：真实探活一次
        try:
            n = self.stats().get("triples", -1)
            if n < 0:
                return {"status": "degraded", "reachable": False,
                        "endpoint": gb.FUSEKI_ENDPOINT,
                        "note": "Fuseki 端点不可达（未启动/地址错）；配置可切回 memory"}
            return {"status": "ok", "reachable": True, "triples": n,
                    "endpoint": gb.FUSEKI_ENDPOINT, "dataset": gb.FUSEKI_DATASET}
        except Exception as e:
            return {"status": "unavailable", "error": repr(e)}

    def capabilities(self) -> list[str]:
        base = ["sparql.select", "sparql.ask"]
        if self._backend == "memory":
            return base + ["materialize", "deterministic"]
        if self._backend == "oxigraph":
            return base + ["sync", "in_process_store", "optional_persist"]
        if self._backend == "neo4j":
            return base + ["sync", "cypher", "property_graph", "ekos_base", "graph_algorithms"]
        return base + ["sync", "remote_endpoint", "http_sparql"]

    def execute(self, payload: dict) -> dict:
        """SPI 统一入口。payload: {"op": "query|ask|sync|stats", "sparql": "..."}。"""
        op = (payload or {}).get("op", "query")
        sparql = (payload or {}).get("sparql", "")
        if op == "query":
            return {"rows": self.query(sparql)}
        if op == "ask":
            return {"ask": self.ask(sparql)}
        if op == "sync":
            return self.sync()
        if op == "stats":
            return self.stats()
        raise ValueError(f"RetrieverAdapter.execute 未知 op={op!r}（query|ask|sync|stats）")
