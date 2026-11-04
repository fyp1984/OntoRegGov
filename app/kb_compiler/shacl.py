"""编译期 SHACL 形状 + 确定性阻断断言（把 10 工程 validate --strict 规则形式化）。

大白话：给编译出来的权威知识画一张"体检表"，不合规就不产 RDF、CI 直接失败。
覆盖 MVP 三类（term / control / inspectioncheck-1.1）。
"""
from __future__ import annotations
import re
from rdflib import Graph, URIRef, Literal, RDF, XSD
from rdflib.namespace import SH

from . import iris

CT_RE = re.compile(r"^CT-(EP|NW|SVC|PROTO|MGMT)-\d{3}$")
_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")


def build_compile_shapes() -> Graph:
    """针对权威知识 ABox 的 closed-ish NodeShape。枚举从 ontology.yaml（schema 权威）读取，
    不再在代码里硬编码——schema 与校验词表单一来源，漂移即被发现。"""
    from . import schema as _sch
    sch = _sch.load_ontology_schema()
    EN = sch["enums"]
    layer_codes = [_sch.LAYER_TO_CODE[x] for x in EN["layer"]]
    O = iris.ONT
    g = Graph()
    g.bind("sh", iris.W3_SH)
    g.bind("ont", iris.ONT_IRI.rstrip("/") + "/#")

    def node_shape(name, target):
        s = O[name]
        g.add((s, RDF.type, SH.NodeShape))
        g.add((s, SH.targetClass, target))
        return s

    def prop(shape, path, min_count=None, in_list=None, pattern=None, datatype=None):
        from rdflib import BNode
        b = BNode()
        g.add((shape, SH.property, b))
        g.add((b, SH.path, path))
        if min_count is not None:
            g.add((b, SH.minCount, Literal(min_count)))
        if pattern:
            g.add((b, SH.pattern, Literal(pattern)))
        if datatype:
            g.add((b, SH.datatype, datatype))
        if in_list:
            lst = [Literal(x) for x in in_list]
            # sh:in list
            from rdflib import BNode as _B
            head = _B()
            g.add((b, SH["in"], head))
            cur = head
            for i, x in enumerate(lst):
                g.add((cur, RDF.first, x))
                nxt = _B() if i < len(lst) - 1 else None
                g.add((cur, RDF.rest, nxt if nxt else RDF.nil))
                cur = nxt

    # 通用：title/level/status/summary 必填
    t = node_shape("TermShape", O["Term"])
    prop(t, O["title"], min_count=1)
    prop(t, O["level"], min_count=1, in_list=EN["level"])
    prop(t, O["status"], min_count=1, in_list=EN["status"])
    prop(t, O["summary"], min_count=1)
    prop(t, O["sourcePath"], min_count=1)

    c = node_shape("ControlShape", O["Control"])
    prop(c, O["title"], min_count=1)
    prop(c, O["level"], min_count=1, in_list=EN["level"])
    prop(c, O["status"], min_count=1, in_list=EN["status"])
    prop(c, O["summary"], min_count=1)
    prop(c, O["ctCode"], min_count=1, pattern=r"^CT-(EP|NW|SVC|PROTO|MGMT)-\d{3}$")
    prop(c, O["ctLayer"], min_count=1, in_list=layer_codes)
    prop(c, O["lifecycle"], min_count=1, in_list=EN["lifecycle"])
    prop(c, O["controlType"], min_count=1, in_list=EN["controlType"])
    prop(c, O["sourcePath"], min_count=1)
    return g


def assert_compile_constraints(g: Graph) -> list[str]:
    """SHACL 1.0 表达不了的跨节点约束，用确定性脚本断言。返回违例列表（空=通过）。"""
    O = iris.ONT
    errs: list[str] = []
    # 1) CT 编号正则 + 全局唯一
    seen: dict[str, URIRef] = {}
    for s, _, _ in g.triples((None, O["ctCode"], None)):
        code = str(g.value(s, O["ctCode"]))
        if not CT_RE.match(code):
            errs.append(f"CT 编号正则不合法: {code} ({s})")
        if code in seen:
            errs.append(f"CT 编号全局唯一冲突: {code} ({seen[code]} 与 {s})")
        else:
            seen[code] = s
    # 2) control 至少 1 条法规/标准依据：对象属性(implements/cites*/governedBy) 或 standard_mappings(hasMapping)
    basis = [O["implements"], O["citesStandard"], O["citesLaw"], O["governedBy"]]
    for s in sorted(set(g.subjects(RDF.type, O["Control"]))):
        has = any((s, p, None) for p in basis for _ in g.triples((s, p, None)))
        if not has:
            has = any(True for _ in g.triples((s, O["hasMapping"], None)))
        if not has:
            errs.append(f"Control 缺法规/标准依据: {s}")
    # 3) 零断链：所有对象属性宾语必须是已存在实例 URI（byid 占位不应残留）
    for s, p, o in g:
        if isinstance(o, URIRef) and "/byid/" in str(o):
            errs.append(f"断链残留(未解析 byid): {s} {p} {o}")
    return errs


def count_by_layer(g: Graph) -> dict:
    """按 CT 层码统计控制数（EP/NW/SVC/PROTO/MGMT）。"""
    O = iris.ONT
    out = {"EP": 0, "NW": 0, "SVC": 0, "PROTO": 0, "MGMT": 0}
    for s in g.subjects(RDF.type, O["Control"]):
        lay = g.value(s, O["ctLayer"])
        if lay and str(lay) in out:
            out[str(lay)] += 1
    return out


def count_ct_coded(g: Graph) -> int:
    O = iris.ONT
    return sum(1 for _ in g.triples((None, O["ctCode"], None)))
