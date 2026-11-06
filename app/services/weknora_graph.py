"""weknora_graph — 从 WeKnora EKOS 底座的 Neo4j 只读知识图谱。

大白话：知识图谱页要「调用底层 weknora 知识库的知识图谱」。WeKnora 把图谱落在
Neo4j（bolt://ekos-weknora-neo4j:7687），本项目本体也镜像在同一实例。这里以只读
方式把两类图读成与站点图谱（kb_knowledge.build 的 nodes+edges）**同形状**，供
`/api/kb/knowledge/graph?source=` 切换展示：

  - ``native``   ：WeKnora 抽取图（``:ENTITY*`` 实体 + 中文关系 处罚/隶属/任职于）
  - ``ontology`` ：平台本体镜像图（``:Entity``，dsec.local：检查项/要素/度量/控制体系）

为什么直连 Neo4j 而不是走 WeKnora HTTP API：
  1) 与 `weknora_retriever` 一致——该模块同样直连 WeKnora Postgres，只为绕开
     「API 端点不明确 + 需要令牌」的问题；本模块沿用同一纪律。
  2) 平台自身的本体镜像（`ontology/neo4j_backend.py`）已经写在这套 Neo4j 上，
     直连可以同时覆盖「weknora 原生图」与「平台本体图」。

纪律：只读、零副作用；本层不缓存、不降级，异常直接抛给 kb_source 决定回落。
"""
from __future__ import annotations

import os

NEO4J_URI = os.environ.get("WEKNORA_NEO4J_URI", "bolt://ekos-weknora-neo4j:7687")
NEO4J_USER = os.environ.get("WEKNORA_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("WEKNORA_NEO4J_PASSWORD", "weknora_p2_dev_only_change_me")

# 平台本体命名空间（与 ontology/neo4j_backend.py 的 DSEC_NS 对齐）
_DSEC_PREFIX = "http://dsec"

# 图谱来源键：前端切换用；"site" 不走本模块（由 Markdown 装配，见 kb_source）。
SOURCES = ("site", "native", "ontology")

_driver = None


def _driver_singleton():
    """惰性建 Neo4j 驱动（进程内复用；驱动自带连接池，勿每次新建）。"""
    global _driver
    if _driver is None:
        from neo4j import GraphDatabase
        _driver = GraphDatabase.driver(
            NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD), connection_timeout=5)
        _driver.verify_connectivity()
    return _driver


def _rows(cypher: str, **params) -> list[dict]:
    drv = _driver_singleton()
    with drv.session() as s:
        return [dict(r) for r in s.run(cypher, **params)]


def _assign_levels(nodes: list[dict], edges: list[dict]) -> None:
    """按度数分位给节点打 L1/L2/L3 段位（前端用段位做半径 + 筛选）。

    Neo4j 图没有现成段位，用「连接度」近似分层：枢纽=高层，便于图例筛选与视觉分级。
    """
    deg = {n["id"]: 0 for n in nodes}
    for e in edges:
        if e["source"] in deg:
            deg[e["source"]] += 1
        if e["target"] in deg:
            deg[e["target"]] += 1
    vals = sorted(deg.values(), reverse=True)
    if not vals:
        return
    n = len(vals)
    hi = vals[max(0, int(n * 0.05) - 1)]      # 前 5% 阈值 -> L3
    mid = vals[max(0, int(n * 0.25) - 1)]     # 前 25% 阈值 -> L2
    for node in nodes:
        d = deg.get(node["id"], 0)
        node["level"] = "L3" if d >= hi and d > 0 else ("L2" if d >= mid and d > 0 else "L1")
        node["degree"] = d


def _payload(source: str, nodes: list[dict], edges: list[dict]) -> dict:
    _assign_levels(nodes, edges)
    counts: dict[str, int] = {}
    for node in nodes:
        counts[node["type"]] = counts.get(node["type"], 0) + 1
    import datetime
    return {
        "graphSource": source,
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "version": "1.0.0",
        "counts": counts,
        "nodes": nodes,
        "edges": edges,
    }


def read_graph(source: str) -> dict | None:
    """读取指定来源的 Neo4j 图谱；未知来源返回 None。异常向上抛。"""
    if source == "native":
        return _read_native()
    if source == "ontology":
        return _read_ontology()
    return None


def _read_native() -> dict:
    """WeKnora 抽取图：标签以 ENTITY 开头的实体 + 它们之间的关系。"""
    node_rows = _rows(
        """MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'ENTITY')
           RETURN elementId(n) AS id,
                  coalesce(n.name, n.title, n.uri, '未命名实体') AS title,
                  coalesce(n.type, 'entity') AS type,
                  n.attributes AS attrs""")
    nodes = [{"id": r["id"], "title": str(r["title"] or "").strip() or "未命名实体",
              "type": (r["type"] or "entity"),
              "tags": [str(a) for a in (r.get("attrs") or []) if a]}
             for r in node_rows]
    edge_rows = _rows(
        """MATCH (a)-[r]->(b)
           WHERE any(l IN labels(a) WHERE l STARTS WITH 'ENTITY')
             AND any(l IN labels(b) WHERE l STARTS WITH 'ENTITY')
           RETURN elementId(a) AS s, elementId(b) AS t, type(r) AS rel""")
    edges = _dedupe_edges([{"source": r["s"], "target": r["t"],
                            "rel": r["rel"] or "related",
                            "label": r["rel"] or "相关"} for r in edge_rows])
    return _payload("native", nodes, edges)


def _read_ontology() -> dict:
    """平台本体镜像图：Neo4j 中的 dsec.local :Entity（检查项/要素/度量/控制体系）。"""
    node_rows = _rows(
        """MATCH (n:Entity) WHERE n.uri STARTS WITH $prefix
           RETURN elementId(n) AS id,
                  coalesce(n.label, n.title, n.name, n.code, n.uri) AS title,
                  coalesce(n.type, 'Entity') AS type,
                  n.uri AS uri""",
        prefix=_DSEC_PREFIX)
    nodes = []
    for r in node_rows:
        title = str(r.get("title") or "").strip()
        if not title or title == r.get("uri"):
            title = str(r.get("uri") or "").rstrip("/").split("/")[-1] or "未命名实体"
        nodes.append({"id": r["id"], "title": title, "type": r["type"] or "Entity",
                      "uri": r.get("uri")})
    edge_rows = _rows(
        """MATCH (a:Entity)-[r]->(b:Entity)
           WHERE a.uri STARTS WITH $prefix AND b.uri STARTS WITH $prefix
           RETURN elementId(a) AS s, elementId(b) AS t,
                  coalesce(r.pred, type(r)) AS rel""",
        prefix=_DSEC_PREFIX)
    edges = _dedupe_edges([{"source": r["s"], "target": r["t"],
                            "rel": r["rel"] or "related",
                            "label": r["rel"] or "相关"} for r in edge_rows])
    return _payload("ontology", nodes, edges)


def _dedupe_edges(edges: list[dict]) -> list[dict]:
    """同一 (source,target,rel) 只保留一条（Neo4j 同名多边合并为一条展示边）。"""
    seen, out = set(), []
    for e in edges:
        key = (e["source"], e["target"], e["rel"])
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def stats() -> dict:
    """各来源规模快照（供排障/状态页；失败返回 error）。"""
    try:
        native = _rows(
            """MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'ENTITY')
               RETURN count(n) AS n""")[0]["n"]
        onto = _rows("MATCH (n:Entity) WHERE n.uri STARTS WITH $p RETURN count(n) AS n",
                     p=_DSEC_PREFIX)[0]["n"]
        return {"native_nodes": native, "ontology_nodes": onto, "uri": NEO4J_URI}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200], "uri": NEO4J_URI}
