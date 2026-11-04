"""接入层最小读源（v1.6.0）：从 canonical RDF（app/data/canonical.ttl）进程内读，返回 JSON。

大白话：以前前端只能吃 SQLite（运行态）。这一层直接把"编译好的权威本体知识库"
（RDF 三元组）读出来转成 JSON，证明"前端 HTML ← 后端本体知识库"这条链路是通的。
不绑端口、不写库——只读 canonical.ttl，进程内 RDFLib 内存图。

环境纪律：本会话"按需确认"模式不绑端口起 uvicorn；API 一律用 fastapi.testclient.TestClient
进程内验证。KB_READ_FROM=canonical 时，/api/checks/{code} 在 SQLite 未命中后回落到本层；
KB_READ_FROM=json 时保持旧 SQLite 行为不变（回退语义保留）。
"""
from __future__ import annotations
from functools import lru_cache

from rdflib import Graph, URIRef, RDF, RDFS

from ..config import APP_DATA, KB_READ_FROM
from ..kb_compiler.iris import KB_IRI, ONT

CANONICAL_TTL = APP_DATA / "canonical.ttl"


@lru_cache(maxsize=1)
def _graph() -> Graph:
    g = Graph()
    if CANONICAL_TTL.exists():
        g.parse(str(CANONICAL_TTL), format="turtle")
    return g


def reload_cache() -> None:
    """重编译后清缓存（测试用）。"""
    _graph.cache_clear()


def _split(uri: str) -> tuple[str, str]:
    """kb/<type>/<slug> → (type_key, slug)。非 kb 实例返回 ('', uri)。"""
    u = str(uri)
    prefix = KB_IRI
    if u.startswith(prefix):
        rest = u[len(prefix):]
        parts = rest.split("/", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
    return "", u


def _lit(g: Graph, s, p):
    v = g.value(s, p)
    return "" if v is None else str(v)


def _subjects_by_type(type_cls: str):
    return sorted(set(_graph().subjects(RDF.type, ONT[type_cls])))


def get_entity(slug: str) -> dict | None:
    """按 URI 末段 slug 查任意实体（跨类型）。返回扁平 JSON + relations 列表。"""
    g = _graph()
    for s in sorted(set(g.subjects())):
        if not isinstance(s, URIRef):
            continue
        tkey, sl = _split(str(s))
        if sl != slug:
            continue
        etype_class = g.value(s, RDF.type)
        rels = []
        for _, p, o in g.triples((s, None, None)):
            if isinstance(o, URIRef) and str(o).startswith(KB_IRI):
                rels.append({"p": str(p).split("#")[-1].split("/")[-1],
                             "type": _split(str(o))[0], "slug": _split(str(o))[1]})
        return {
            "id": sl, "type": tkey,
            "label": _lit(g, s, RDFS.label),
            "title": _lit(g, s, ONT["title"]) or _lit(g, s, RDFS.label),
            "titleEn": _lit(g, s, ONT["titleEn"]),
            "summary": _lit(g, s, ONT["summary"]),
            "level": _lit(g, s, ONT["level"]),
            "status": _lit(g, s, ONT["status"]),
            "checkCode": _lit(g, s, ONT["checkCode"]),
            "domain": _lit(g, s, ONT["domain"]),
            "ctCode": _lit(g, s, ONT["ctCode"]),
            "sourcePath": _lit(g, s, ONT["sourcePath"]),
            # v1.8.0：law/standard/organization 富字段（缺省空串，append-only）
            "authority": _lit(g, s, ONT["authority"]),
            "docNo": _lit(g, s, ONT["docNo"]),
            "stdNo": _lit(g, s, ONT["stdNo"]),
            "issuer": _lit(g, s, ONT["issuer"]),
            "issued": _lit(g, s, ONT["issued"]),
            "effective": _lit(g, s, ONT["effective"]),
            "validity": _lit(g, s, ONT["validity"]),
            "hierarchy": _lit(g, s, ONT["hierarchy"]),
            "kind": _lit(g, s, ONT["kind"]),
            "orgKind": _lit(g, s, ONT["orgKind"]),
            "region": _lit(g, s, ONT["region"]),
            "mandate": _lit(g, s, ONT["mandate"]),
            "relations": rels,
        }
    return None


def search(q: str, limit: int = 20) -> dict:
    """跨类型子串检索：label/title/summary/checkCode/domain。"""
    g = _graph()
    q = (q or "").strip()
    hits = []
    for s in sorted(set(g.subjects(RDF.type, None))):
        if not isinstance(s, URIRef) or not str(s).startswith(KB_IRI):
            continue
        blob = " ".join([
            _lit(g, s, RDFS.label), _lit(g, s, ONT["title"]),
            _lit(g, s, ONT["summary"]), _lit(g, s, ONT["checkCode"]),
            _lit(g, s, ONT["domain"]),
        ])
        if q and q not in blob:
            continue
        cls = g.value(s, RDF.type)
        hits.append({
            "id": _split(str(s))[1], "type": _split(str(s))[0],
            "label": _lit(g, s, RDFS.label) or _lit(g, s, ONT["title"]),
            "checkCode": _lit(g, s, ONT["checkCode"]),
        })
        if len(hits) >= limit:
            break
    return {"query": q, "total": len(hits), "results": hits}


def list_controls() -> dict:
    """canonical 控制列表（91 条，带 CT 码/层）。"""
    g = _graph()
    out = []
    for s in _subjects_by_type("Control"):
        out.append({
            "id": _split(str(s))[1],
            "ctCode": _lit(g, s, ONT["ctCode"]),
            "title": _lit(g, s, RDFS.label),
            "layer": _lit(g, s, ONT["ctLayer"]),
            "controlType": _lit(g, s, ONT["controlType"]),
        })
    return {"total": len(out), "controls": out}


def get_check(check_code: str) -> dict | None:
    """按 checkCode 查 InspectionCheck（含 93号文 93-x.y 与金规 1.1），含要素与条款。"""
    g = _graph()
    for s in sorted(set(g.subjects(RDF.type, ONT["InspectionCheck"]))):
        if _lit(g, s, ONT["checkCode"]) != check_code:
            continue
        elements = []
        for el in g.objects(s, ONT["hasElement"]):
            elements.append({
                "elementCode": _lit(g, el, ONT["elementCode"]),
                "text": _lit(g, el, RDFS.label),
            })
        clauses = [_split(str(c))[1] for c in g.objects(s, ONT["citesClause"])]
        return {
            "checkCode": check_code,
            "id": _split(str(s))[1],
            "title": _lit(g, s, RDFS.label),
            "domain": _lit(g, s, ONT["domain"]),
            "priority": _lit(g, s, ONT["priority"]),
            "articleNo": _lit(g, s, ONT["articleNo"]),
            "summary": _lit(g, s, ONT["summary"]),
            "citesClause": clauses,
            "elements": elements,
            "source": "canonical",
        }
    return None
