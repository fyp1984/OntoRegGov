"""平台适配器：把 canonical RDF（新 base IRI）投影成平台 dsecb 命名空间底座快照。

大白话：canonical 图用的是新网址式编号（https://schema.cheersai.local/ds/...），
平台旧代码认的是 dsecb: 前缀。这个适配器把同一份知识按平台习惯的前缀"换个门牌"，
并带上旧路漏投的结构化字段（CT 码/分层/生命周期/标准映射）。默认不影响旧 json 源。
"""
from __future__ import annotations
from rdflib import Graph, URIRef, Literal, RDF, RDFS, Namespace
from . import iris
from .compiler import compile_canonical
from ..config import BASE_NS, BASE_SNAPSHOT_TTL, KB_READ_FROM

DSECB = Namespace(BASE_NS)


def build_platform_snapshot() -> str:
    """编译 canonical → 写成 dsecb 命名空间底座快照（富字段）。返回 ttl。"""
    g, _ = compile_canonical()
    out = Graph()
    out.bind("dsecb", DSECB)
    O = iris.ONT
    # 类声明
    for t in ["term", "control", "law", "standard", "organization", "case", "scenario",
              "role", "solution", "guide", "topic"]:
        out.add((DSECB[t], RDF.type, URIRef("http://www.w3.org/2002/07/owl#Class")))

    def slug_of(subj: URIRef, ttype: str) -> str:
        return str(subj)[len(iris.KB_IRI) + len(ttype) + 1:]

    # term
    for s in sorted(set(g.subjects(RDF.type, O["Term"]))):
        slug = slug_of(s, "term")
        subj = DSECB[f"term/{slug}"]
        out.add((subj, RDF.type, DSECB["term"]))
        out.add((subj, RDFS.label, g.value(s, RDFS.label) or Literal(slug, lang="zh")))
        if g.value(s, O["summary"]):
            out.add((subj, DSECB["summary"], g.value(s, O["summary"])))
        if g.value(s, O["level"]):
            out.add((subj, DSECB["level"], g.value(s, O["level"])))

    # control（富字段：ctCode/ctLayer/lifecycle/controlType/family）
    for s in sorted(set(g.subjects(RDF.type, O["Control"]))):
        slug = slug_of(s, "control")
        subj = DSECB[f"control/{slug}"]
        out.add((subj, RDF.type, DSECB["control"]))
        out.add((subj, RDFS.label, g.value(s, RDFS.label) or Literal(slug, lang="zh")))
        if g.value(s, O["summary"]):
            out.add((subj, DSECB["summary"], g.value(s, O["summary"])))
        if g.value(s, O["ctCode"]):
            out.add((subj, DSECB["ctCode"], g.value(s, O["ctCode"])))
        if g.value(s, O["ctLayer"]):
            out.add((subj, DSECB["ctLayer"], g.value(s, O["ctLayer"])))
        if g.value(s, O["controlType"]):
            out.add((subj, DSECB["controlType"], g.value(s, O["controlType"])))
        if g.value(s, O["controlFamily"]):
            out.add((subj, DSECB["controlFamily"], g.value(s, O["controlFamily"])))
        for lc in g.objects(s, O["lifecycle"]):
            out.add((subj, DSECB["lifecycle"], lc))
    return out.serialize(format="turtle")


def write_snapshot():
    ttl = build_platform_snapshot()
    BASE_SNAPSHOT_TTL.write_text(ttl, encoding="utf-8")
    return ttl
