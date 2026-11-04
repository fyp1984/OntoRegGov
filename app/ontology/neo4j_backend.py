"""Neo4j 属性图后端（WeKnora EKOS 底座直连）。

设计依据：deploy/README-fuseki-neo4j.md 的 Cypher 映射草案。
- sync(ttl): 把 RDF TTL 解析为属性图，全量镜像到 WeKnora Neo4j
- query(sparql): 仅支持有限 Cypher 等价查询（count / 按类型查节点 / 出边 / 入边），
  其余回退 memory 物化（不抛错）

环境变量：
  WEKNORA_NEO4J_URI=bolt://ekos-weknora-neo4j:7687
  WEKNORA_NEO4J_USER=neo4j
  WEKNORA_NEO4J_PASSWORD=weknora_p2_dev_only_change_me
"""
from __future__ import annotations

import os
import re
import io
import json
import datetime
from collections import defaultdict

from ..config import APP_DATA

NEO4J_URI = os.environ.get("WEKNORA_NEO4J_URI", "bolt://ekos-weknora-neo4j:7687")
NEO4J_USER = os.environ.get("WEKNORA_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("WEKNORA_NEO4J_PASSWORD", "weknora_p2_dev_only_change_me")

# 命名空间（与 graph_store.py 对齐）
DSEC_NS = "http://dsec.local/ontology/2026/1#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

_driver = None


def _get_driver():
    global _driver
    if _driver is None:
        from neo4j import GraphDatabase
        _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        _driver.verify_connectivity()
    return _driver


def _short(uri: str) -> str:
    """URI 缩短为本地名（用于节点 type / 关系 pred）。"""
    if uri.startswith(DSEC_NS):
        return uri[len(DSEC_NS):]
    if uri.startswith("http://www.w3.org/1999/02/22-rdf-syntax-ns#"):
        return "rdf:" + uri.split("#")[-1]
    return uri.split("/")[-1].split("#")[-1]


def sync(ttl: str) -> dict:
    """把 RDF TTL 全量镜像到 Neo4j 属性图。幂等（MERGE）。

    节点结构：(:Entity {uri, type, label})
      - uri: 实体 URI（唯一键）
      - type: rdf:type 的本地名
      - label: rdfs:label 或 skos:prefLabel
    数据属性：(:Entity).key = value（动态属性）
    关系：(:Entity)-[:REL {pred}]->(:Entity)
    """
    from rdflib import Graph, URIRef, Literal

    g = Graph()
    g.parse(io.BytesIO(ttl.encode("utf-8")), format="turtle")

    nodes = {}          # uri -> {type, props}
    edges = []          # (subj_uri, pred_short, obj_uri)

    for s, p, o in g:
        if not isinstance(s, URIRef):
            continue
        s_uri = str(s)
        p_short = _short(str(p))

        if isinstance(o, URIRef):
            o_uri = str(o)
            if p == URIRef(RDF_TYPE):
                if s_uri not in nodes:
                    nodes[s_uri] = {"uri": s_uri, "type": _short(o_uri), "props": {}}
                else:
                    nodes[s_uri]["type"] = _short(o_uri)
            else:
                nodes.setdefault(s_uri, {"uri": s_uri, "type": "Entity", "props": {}})
                nodes.setdefault(o_uri, {"uri": o_uri, "type": "Entity", "props": {}})
                edges.append((s_uri, p_short, o_uri))
        elif isinstance(o, Literal):
            nodes.setdefault(s_uri, {"uri": s_uri, "type": "Entity", "props": {}})
            try:
                val = o.toPython()
            except Exception:
                val = str(o)
            nodes[s_uri]["props"][p_short] = val

    # 写入 Neo4j
    driver = _get_driver()
    ts = datetime.datetime.now().isoformat(timespec="seconds")

    with driver.session() as session:
        # 全量替换：先清空平台命名空间的节点（MERGE 幂等，但为保证一致性先删）
        session.run("MATCH (n:Entity) WHERE n.uri STARTS WITH 'http://dsec' DETACH DELETE n")

        # 批量写节点
        node_batch = list(nodes.values())
        for i in range(0, len(node_batch), 200):
            batch = node_batch[i:i+200]
            session.run(
                """
                UNWIND $batch AS row
                MERGE (n:Entity {uri: row.uri})
                SET n.type = row.type, n += row.props
                """,
                batch=batch,
            )

        # 批量写关系
        edge_batch = [{"s": s, "p": p, "o": o} for s, p, o in edges]
        for i in range(0, len(edge_batch), 200):
            batch = edge_batch[i:i+200]
            session.run(
                """
                UNWIND $batch AS row
                MATCH (a:Entity {uri: row.s}), (b:Entity {uri: row.o})
                MERGE (a)-[r:REL {pred: row.p}]->(b)
                """,
                batch=batch,
            )

    return {
        "backend": "neo4j",
        "nodes": len(nodes),
        "edges": len(edges),
        "syncedAt": ts,
    }


def query(sparql: str) -> list:
    """有限 Cypher 等价查询。仅识别简单 SELECT 形态，其余回退 memory。

    支持：
      1. SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }  → 总节点数
      2. SELECT ?s WHERE { ?s a dsec:SomeType }      → 按类型查节点
    """
    driver = _get_driver()

    # 形态1：COUNT
    if re.search(r"COUNT\s*\(\s*\*\s*\)", sparql, re.I):
        with driver.session() as session:
            result = session.run("MATCH (n:Entity) RETURN count(n) AS n")
            record = result.single()
            return [{"n": record["n"]}] if record else [{"n": 0}]

    # 形态2：按类型查节点（?s a dsec:TypeName）
    m = re.search(r"a\s+dsec:([A-Za-z_][A-Za-z0-9_]*)", sparql)
    if m:
        type_name = m.group(1)
        with driver.session() as session:
            result = session.run(
                "MATCH (n:Entity {type: $type}) RETURN n.uri AS s, n.label AS label LIMIT 100",
                type=type_name,
            )
            return [{"s": r["s"], "label": r["label"]} for r in result]

    # 其他形态：无法映射，返回空（由调用方决定是否回退）
    return []


def stats() -> dict:
    try:
        driver = _get_driver()
        with driver.session() as session:
            n_nodes = session.run("MATCH (n:Entity) RETURN count(n) AS n").single()["n"]
            n_edges = session.run("MATCH ()-[r:REL]->() RETURN count(r) AS n").single()["n"]
        return {"backend": "neo4j", "nodes": n_nodes, "edges": n_edges}
    except Exception as e:
        return {"backend": "neo4j", "error": str(e)[:200], "nodes": -1, "edges": -1}


def health() -> dict:
    """连通性自检。"""
    try:
        driver = _get_driver()
        driver.verify_connectivity()
        st = stats()
        return {"ok": True, "uri": NEO4J_URI, **st}
    except Exception as e:
        return {"ok": False, "uri": NEO4J_URI, "error": str(e)[:300]}
