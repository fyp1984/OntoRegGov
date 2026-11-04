"""v1.4.0 可插拔图存储后端（标准 SPARQL 层）。

三个后端，环境变量切换：
  GRAPH_STORE_BACKEND = memory（默认，进程内 RDFLib，保持既有行为）
                       | oxigraph（进程内 pyoxigraph，可选落盘 GRAPH_STORE_FILE）
                       | fuseki（HTTP SPARQL 端点，兼容 Apache Jena Fuseki；本地容器或远程均可）
  GRAPH_STORE_ENDPOINT = Fuseki 基址，如 http://127.0.0.1:3030（默认）
  GRAPH_STORE_DATASET  = Fuseki 数据集名（默认 ds）
  GRAPH_STORE_FILE     = oxigraph 落盘路径（默认不落盘）

职责边界（刻意保持）：
- 判定引擎 / SHACL 闸门 / why 溯源仍走进程内 RDFLib 物化（materialize），保证确定性；
- 本模块提供"持久化 + 标准 SPARQL 查询端点"层：sync() 把当前物化图全量镜像到所选后端，
  query()/ask() 以标准 SPARQL 读取，供外部工具/BI/多进程共享访问；
- Neo4j（属性图，非 SPARQL 原生）以适配器方式接入：实现 sync/query 两个接口即可，见
  deploy/README-fuseki-neo4j.md 中的 Cypher 映射草案。
"""
from __future__ import annotations
import io, json, os, base64, urllib.request, urllib.parse, urllib.error
from pathlib import Path

from . import graph_store as gs
from ..config import APP_DATA

# P2：Fuseki 为图权威（平台命名图 <http://dsec/platform>）。
# 镜像/compose 可能烘焙了遗留 GRAPH_STORE_BACKEND=memory，此处以代码权威为准；
# 仅当显式设置 GRAPH_FORCE_MEMORY=1 时才回退进程内 memory（只读逃生舱，便于排障）。
if os.environ.get("GRAPH_FORCE_MEMORY", "").strip().lower() in ("1", "on", "true"):
    BACKEND = "memory"
elif os.environ.get("GRAPH_STORE_BACKEND", "").strip().lower() == "neo4j":
    BACKEND = "neo4j"
else:
    BACKEND = "fuseki"
FUSEKI_ENDPOINT = os.environ.get("GRAPH_STORE_ENDPOINT", "http://127.0.0.1:3030").rstrip("/")
# 容器内 127.0.0.1 指向自身，需回退 host.docker.internal 访问宿主 Fuseki
if os.path.exists("/.dockerenv") and "127.0.0.1" in FUSEKI_ENDPOINT:
    FUSEKI_ENDPOINT = FUSEKI_ENDPOINT.replace("127.0.0.1", "host.docker.internal")
FUSEKI_DATASET = os.environ.get("GRAPH_STORE_DATASET", "ds").strip() or "ds"
FUSEKI_USER = os.environ.get("GRAPH_STORE_USER", "admin").strip()
FUSEKI_PASSWORD = os.environ.get("GRAPH_STORE_PASSWORD", "admin").strip()
OXI_FILE = os.environ.get("GRAPH_STORE_FILE", "").strip()
# P2：平台权威命名图（只增，EKOS 默认图 19,927 三元组只读不动）
PLATFORM_GRAPH = os.environ.get("GRAPH_PLATFORM_GRAPH", "http://dsec/platform")
STATS_CACHE = {}          # backend -> {"triples": int, "syncedAt": str}


# ---------------------------------------------------------------------------
# 内存后端（默认：复用 RDFLib 物化；行为与历史一致）
# ---------------------------------------------------------------------------
def _memory_query(sparql: str) -> list:
    g = gs.materialize()
    out = []
    for row in g.query(sparql):
        d = {}
        for k in row.asdict():
            v = row.asdict()[k]
            d[k] = _lit(v)
        out.append(d)
    return out


def _lit(v):
    if v is None:
        return None
    if hasattr(v, "toPython"):          # rdflib / pyoxigraph Literal
        return v.toPython()
    return getattr(v, "value", str(v))  # pyoxigraph NamedNode/BlankNode


# ---------------------------------------------------------------------------
# oxigraph 后端（进程内标准 SPARQL 存储，可落盘）
# ---------------------------------------------------------------------------
_oxi_store = None


def _oxi() -> "Store":
    global _oxi_store
    if _oxi_store is None:
        import pyoxigraph as px
        _oxi_store = px.Store(path=OXI_FILE or None)
    return _oxi_store


def _oxi_sync(ttl: str) -> dict:
    import pyoxigraph as px
    s = _oxi()
    s.clear()
    s.load(io.BytesIO(ttl.encode("utf-8")), format=px.RdfFormat.TURTLE)
    if OXI_FILE:
        s.dump(Path(OXI_FILE), format=px.RdfFormat.TURTLE)
    return _oxi_stats()


def _oxi_query(sparql: str) -> list:
    # pyoxigraph QuerySolution 不暴露键名：优先取 AS 别名，否则取 SELECT 投影变量，按位置取值
    import re
    m = re.search(r"SELECT\s+(?:DISTINCT\s+)?(.*?)\s+WHERE", sparql, re.S)
    proj = m.group(1) if m else sparql
    names = re.findall(r"AS\s+\?([A-Za-z_][A-Za-z0-9_]*)", proj) or \
            re.findall(r"\?([A-Za-z_][A-Za-z0-9_]*)", proj)
    out = []
    for row in _oxi().query(sparql):
        if names:
            d = {name: _lit(row[i]) for i, name in enumerate(names) if i < len(row)}
        else:
            d = {str(i): _lit(row[i]) for i in range(len(row))}
        out.append(d)
    return out


def _oxi_stats() -> dict:
    rows = _oxi_query("SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }")
    n = rows[0]["n"] if rows else 0
    return {"triples": int(n), "syncedAt": STATS_CACHE.get("oxigraph", {}).get("syncedAt")}


# ---------------------------------------------------------------------------
# Fuseki 后端（HTTP SPARQL：标准 query/update/data 端点）
# ---------------------------------------------------------------------------
def _fuseki_url(kind: str) -> str:
    return f"{FUSEKI_ENDPOINT}/{FUSEKI_DATASET}/{kind}"


def _http(method: str, url: str, body: bytes, ctype: str, accept: str, auth: bool = True):
    headers = {"Content-Type": ctype, "Accept": accept}
    if auth and FUSEKI_USER:
        token = base64.b64encode(f"{FUSEKI_USER}:{FUSEKI_PASSWORD}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Fuseki HTTP {e.code}: {e.read()[:300]!r}") from e


def _fuseki_sync(ttl: str) -> dict:
    """P2 安全版：只向平台命名图 **增量合并**（MERGE），绝不 CLEAR 默认图。

    EKOS 既有 ds 默认图（19,927 三元组）只读不动；提供的 TTL 追加到平台命名图，
    重复 POST 同一三元组由 RDF 去重，不删除任何既有三元组。
    """
    data_url = f"{FUSEKI_ENDPOINT}/{FUSEKI_DATASET}/data?graph={urllib.parse.quote(PLATFORM_GRAPH)}"
    _http("POST", data_url, ttl.encode("utf-8"), "text/turtle", "*/*")
    return _fuseki_stats()


def _fuseki_query(sparql: str) -> list:
    raw = _http("POST", _fuseki_url("query"), sparql.encode("utf-8"),
                "application/sparql-query", "application/sparql-results+json")
    data = json.loads(raw.decode("utf-8"))
    out = []
    for b in data.get("results", {}).get("bindings", []):
        d = {}
        for k, v in b.items():
            if v["type"] == "uri":
                d[k] = v["value"]
            elif v["type"] == "literal":
                d[k] = v["value"]
            else:
                d[k] = v.get("value")
        out.append(d)
    return out


def _fuseki_stats() -> dict:
    try:
        rows = _fuseki_query(
            f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{PLATFORM_GRAPH}> {{ ?s ?p ?o }} }}")
        n = int(rows[0]["n"]) if rows else 0
    except RuntimeError:
        n = -1
    return {"backend": "fuseki", "graph": PLATFORM_GRAPH, "triples": n,
            "syncedAt": STATS_CACHE.get("fuseki", {}).get("syncedAt")}


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------
def current_backend() -> str:
    return BACKEND


def sync(ttl: str | None = None) -> dict:
    """把当前物化图（含 TBox + 底座快照 + 已发布实体）全量镜像到所选后端。幂等。"""
    if BACKEND == "memory":
        return {"backend": "memory", "note": "进程内 RDFLib 即物化态，无需镜像"}
    ttl = ttl if ttl is not None else gs.export_turtle()
    import datetime
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    if BACKEND == "oxigraph":
        stats = _oxi_sync(ttl)
    elif BACKEND == "fuseki":
        stats = _fuseki_sync(ttl)
    elif BACKEND == "neo4j":
        from . import neo4j_backend as nb
        stats = nb.sync(ttl)
    else:
        raise ValueError(f"未知 GRAPH_STORE_BACKEND={BACKEND}")
    stats["syncedAt"] = ts
    STATS_CACHE[BACKEND] = stats
    return {"backend": BACKEND, "syncedAt": ts, "triples": stats.get("triples", -1)}


def query(sparql: str) -> list:
    """标准 SPARQL SELECT 查询，返回 [{var: value}, ...]。

    权威=Fuseki 平台命名图；Fuseki 不可达时只读降级进程内 memory 物化，不中断 200。
    Neo4j 后端：仅支持有限 Cypher 等价查询，其余回退 memory。
    """
    if BACKEND == "memory":
        return _memory_query(sparql)
    if BACKEND == "oxigraph":
        return _oxi_query(sparql)
    if BACKEND == "fuseki":
        try:
            return _fuseki_query(sparql)
        except Exception:  # noqa: BLE001  只读降级，再失败返回空，不中断 200
            try:
                return _memory_query(sparql)
            except Exception:  # noqa: BLE001
                return []
    if BACKEND == "neo4j":
        from . import neo4j_backend as nb
        try:
            rows = nb.query(sparql)
            if rows:
                return rows
        except Exception:  # noqa: BLE001
            pass
        return _memory_query(sparql)
    raise ValueError(f"未知 GRAPH_STORE_BACKEND={BACKEND}")


def ask(sparql: str) -> bool:
    if BACKEND == "memory":
        return bool(gs.materialize().query(sparql))
    if BACKEND == "oxigraph":
        return bool(_oxi().query(sparql))
    if BACKEND == "fuseki":
        try:
            raw = _http("POST", _fuseki_url("query"), sparql.encode("utf-8"),
                        "application/sparql-query", "application/sparql-results+json",
                        auth=False)
            return bool(json.loads(raw.decode("utf-8")).get("boolean", False))
        except Exception:  # noqa: BLE001  只读降级
            return bool(gs.materialize().query(sparql))
    raise ValueError(f"未知 GRAPH_STORE_BACKEND={BACKEND}")


def stats() -> dict:
    if BACKEND == "memory":
        g = gs.materialize()
        return {"backend": "memory", "triples": len(g), "syncedAt": "（进程内物化态）"}
    if BACKEND == "oxigraph":
        return {"backend": "oxigraph", **(_oxi_stats() if _oxi_store is not None
                                          else {"triples": 0, "syncedAt": None})}
    if BACKEND == "fuseki":
        st = _fuseki_stats()
        if st.get("triples", -1) < 0:
            g = gs.materialize()
            return {"backend": "fuseki", "degraded": "memory-readonly",
                    "triples": len(g), "note": "Fuseki 不可达，只读降级 memory 物化"}
        return st
    if BACKEND == "neo4j":
        from . import neo4j_backend as nb
        return {"backend": "neo4j", **nb.stats()}
    raise ValueError(f"未知 GRAPH_STORE_BACKEND={BACKEND}")
