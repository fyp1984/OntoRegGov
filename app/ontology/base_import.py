"""底座只读投影：一次性把 10_知识库工程/data/knowledge.json 投影为 base-snapshot.ttl。
绝不写回底座、不 import 底座脚本、不读其运行态；靠重跑刷新。
"""
from __future__ import annotations
import json
from rdflib import Graph, URIRef, Literal, RDF, RDFS, OWL
from .ns import DSECB
from ..config import KB_KNOWLEDGE_JSON, BASE_SNAPSHOT_TTL, KB_READ_FROM

# 底座实体类型 -> 投影类（与 ns.BASE_PROJECTED_CLASSES 对齐）
PROJECTED_TYPES = {"law", "standard", "term", "role", "organization",
                   "control", "case", "scenario"}


def project() -> str:
    # v1.5.0：KB_READ_FROM=canonical 时改读 10 工程编辑源经编译器+适配器生成富字段快照
    if KB_READ_FROM == "canonical":
        from ..kb_compiler.adapter import write_snapshot
        return write_snapshot()
    if not KB_KNOWLEDGE_JSON.exists():
        # 底座不可达时生成空快照（保证零依赖可跑）
        g = Graph()
        g.bind("dsecb", DSECB)
        g.add((DSECB["Note"], RDF.type, OWL.Class))
        out = g.serialize(format="turtle")
        BASE_SNAPSHOT_TTL.write_text(out, encoding="utf-8")
        return out
    data = json.loads(KB_KNOWLEDGE_JSON.read_text(encoding="utf-8"))
    g = Graph()
    g.bind("dsecb", DSECB)
    # 类声明
    for t in PROJECTED_TYPES:
        g.add((DSECB[t], RDF.type, OWL.Class))
        g.add((DSECB[t], RDFS.label, Literal(t, lang="en")))
    n = 0
    for e in data.get("entities", []):
        etype = e.get("type")
        if etype not in PROJECTED_TYPES:
            continue
        eid = e["id"]
        subj = DSECB[f"{etype}/{eid}"]
        g.add((subj, RDF.type, DSECB[etype]))
        g.add((subj, RDFS.label, Literal(e.get("title", eid), lang="zh")))
        if e.get("summary"):
            g.add((subj, DSECB["summary"], Literal(e["summary"], lang="zh")))
        if e.get("official_url"):
            g.add((subj, RDFS.seeAlso, URIRef(e["official_url"])))
        n += 1
    out = g.serialize(format="turtle")
    BASE_SNAPSHOT_TTL.write_text(out, encoding="utf-8")
    return out


if __name__ == "__main__":
    project()
    print(f"base snapshot -> {BASE_SNAPSHOT_TTL}")
