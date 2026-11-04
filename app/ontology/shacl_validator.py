"""pySHACL 闸门：候选过不了 SHACL 不允许 published。"""
from __future__ import annotations
from pyshacl import validate
from .tbox import build_shacl_shapes
from .graph_store import graph_for_entity, materialize

_SHAPES = None


def _shapes_graph():
    global _SHAPES
    if _SHAPES is None:
        _SHAPES = build_shacl_shapes()
    return _SHAPES


def validate_entity(etype: str, eid: str, data: dict, relations: list) -> dict:
    """对单个候选实体跑 SHACL。返回 {conforms, messages}。"""
    data_g = graph_for_entity(etype, eid, data, relations)
    conforms, result_g, text = validate(
        data_g, shacl_graph=_shapes_graph(), inference="none",
        abort_on_first=False, meta_shacl=False, debug=False)
    msgs = []
    if not conforms:
        # 从结果图抽取可读消息
        from rdflib import RDF
        from .ns import SH
        for s, _, _ in result_g.triples((None, RDF.type, SH.ValidationResult)):
            o = result_g.value(s, SH.resultMessage)
            p = result_g.value(s, SH.focusNode)
            if o:
                msgs.append(f"{p}: {o}")
    return {"conforms": bool(conforms), "messages": msgs[:20]}


def validate_full() -> dict:
    """对已发布全图跑一次 SHACL（导出/冒烟用）。"""
    g = materialize()
    conforms, _, text = validate(g, shacl_graph=_shapes_graph(),
                                 inference="none", abort_on_first=False)
    return {"conforms": bool(conforms), "report": text[:2000]}
