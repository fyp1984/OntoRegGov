"""资产层 PostgreSQL 投影只读服务（v1.8.0，docs/09 §2/§4.3）。

大白话：canonical.ttl 是"账本原件"（RDF 图，唯一正本）；本模块按 docs/09 §2 的 9 张表
把它"复印"成关系台账（kb_entity / control / inspection_check / check_element …），只读、
只查、绝不写库（写库只发生在 kb_publish 入库钩子，本服务不碰）。

降级哲学（docs/09 §4.3）：库不可达（psycopg2 未装 / 连接拒绝 / 表不存在 / 查询异常）
→ health()=False → 上层自动回落 canonical 图（canonical_kb）→ 再回落 SQLite 旧链路，
永远不把 PG 的故障抛给调用方、不中断 200。

输出形状与 canonical_kb 严格一致，保证 /api/* 在 json/canonical/db 三态下结构不变。
"""
from __future__ import annotations

import time
from typing import Any

from ..config import KB_PG_DSN

# 连接健康探测 TTL：避免每次请求都 TCP 探测一次；库挂了最多 30s 内自动降级。
_HEALTH_TTL_SEC = 30.0
_health_cache: bool | None = None
_health_ts: float = 0.0


def _dsn_candidates() -> list[str]:
    """连接串候选：容器内（/.dockerenv 存在）把 127.0.0.1 改写为 host.docker.internal。

    宿主直连时只返回配置原值。与 `_pg_connect_optional()` 保持同一容器改写范式，
    否则容器内 `_connect()` 会因 127.0.0.1 不可达而 health()=False（v1.15.0 修复）。
    """
    dsn = KB_PG_DSN
    if "127.0.0.1" in dsn and _os.path.exists("/.dockerenv"):
        return [dsn.replace("127.0.0.1", "host.docker.internal"), dsn]
    return [dsn]


def _connect():
    """懒加载 psycopg2 并建立只读连接。任何失败都抛给调用方捕获。

    依次尝试 DSN 候选（容器内首试 host.docker.internal 改写版），全部失败才抛出。
    """
    import psycopg2  # 可选依赖（工作包 B 落地；未装时整体降级）
    import psycopg2.extras
    last_err: Exception | None = None
    for dsn in _dsn_candidates():
        try:
            conn = psycopg2.connect(dsn, connect_timeout=3)
            conn.set_session(readonly=True, autocommit=True)
            return conn
        except Exception as e:  # noqa: BLE001 — 换下一个候选，全失败后抛出
            last_err = e
    raise last_err if last_err else RuntimeError("no PostgreSQL DSN candidate")


def health(force: bool = False) -> bool:
    """PostgreSQL 投影是否可用。带 30s 缓存；force=True 立即重探。"""
    global _health_cache, _health_ts
    now = time.time()
    if not force and _health_cache is not None and (now - _health_ts) < _HEALTH_TTL_SEC:
        return _health_cache
    ok = False
    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        conn.close()
        ok = True
    except Exception:  # noqa: BLE001 — 任何不可达都按降级处理
        ok = False
    _health_cache = ok
    _health_ts = now
    return ok


def _q(sql: str, args: tuple = ()) -> list[dict[str, Any]]:
    """只读查询包装：任何异常都向上抛，由各公开函数决定如何回落。"""
    conn = _connect()
    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, args)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ---------------- 与 canonical_kb 同形的四个读函数（全部异常→None/空） ----------------

def get_entity(slug: str) -> dict | None:
    """按 slug 查任意实体（kb_entity 主键 uri、业务键 slug）， relations 来自 kb_relation。"""
    try:
        rows = _q("""
            SELECT uri, entity_type, slug, label, title, summary, status,
                   ct_code, check_code, domain, source_path
            FROM kb_entity WHERE slug = %s LIMIT 1
        """, (slug,))
        if not rows:
            return None
        r = rows[0]
        rels = []
        try:
            erows = _q("""
                SELECT predicate, object_uri
                FROM kb_relation WHERE subject_uri = %s
            """, (r["uri"],))
            for er in erows:
                obj = er["object_uri"] or ""
                # object_uri → kb/<type>/<slug> → (type, slug)
                if "/kb/" in obj:
                    tail = obj.split("/kb/", 1)[1]
                    parts = tail.split("/", 1)
                    rtype, rslug = (parts + [""])[:2] if len(parts) >= 2 else ("", tail)
                else:
                    rtype, rslug = "", obj
                rels.append({"p": (er["predicate"] or "").split("#")[-1].split("/")[-1],
                             "type": rtype, "slug": rslug})
        except Exception:  # noqa: BLE001 — 边表缺了不影响实体本体返回
            pass
        return {
            "id": r["slug"],
            "type": r["entity_type"] or "",
            "label": r["label"] or "",
            "title": r["title"] or r["label"] or "",
            "summary": r["summary"] or "",
            "level": "",
            "status": r["status"] or "",
            "checkCode": r["check_code"] or "",
            "domain": r["domain"] or "",
            "ctCode": r["ct_code"] or "",
            "sourcePath": r["source_path"] or "",
            "relations": rels,
        }
    except Exception:  # noqa: BLE001
        return None


def search(q: str, limit: int = 20) -> dict:
    """kb_entity 按 label/title/summary/check_code/domain ILIKE 子串检索。"""
    q = (q or "").strip()
    try:
        like = f"%{q}%"
        rows = _q("""
            SELECT slug, entity_type, label, title, check_code
            FROM kb_entity
            WHERE (%s = ''
                   OR label ILIKE %s OR title ILIKE %s OR summary ILIKE %s
                   OR check_code ILIKE %s OR domain ILIKE %s
                   OR data_json::text ILIKE %s)
            ORDER BY entity_type, slug
            LIMIT %s
        """, (q, like, like, like, like, like, like, int(limit)))
        results = [{
            "id": r["slug"], "type": r["entity_type"] or "",
            "label": r["label"] or r["title"] or "",
            "checkCode": r["check_code"] or "",
        } for r in rows]
        return {"query": q, "total": len(results), "results": results}
    except Exception:  # noqa: BLE001
        return {"query": q, "total": 0, "results": []}


def list_controls() -> dict:
    """control 特化表 JOIN kb_entity，输出与 canonical_kb.list_controls 同形。"""
    try:
        rows = _q("""
            SELECT e.slug, c.ct_code, c.title, c.layer, c.control_type
            FROM control c
            JOIN kb_entity e ON e.uri = c.entity_uri
            ORDER BY c.ct_code
        """)
        controls = [{
            "id": r["slug"], "ctCode": r["ct_code"] or "",
            "title": r["title"] or "", "layer": r["layer"] or "",
            "controlType": r["control_type"] or "",
        } for r in rows]
        return {"total": len(controls), "controls": controls}
    except Exception:  # noqa: BLE001
        return {"total": 0, "controls": []}


def get_check(check_code: str) -> dict | None:
    """inspection_check JOIN check_element 查六维；citesClause 来自 kb_relation。

    投影口径（线A 补全后，以库实读为准）：
      - check 标题入 kb_entity.title/label 与 inspection_check.title（346/346 非空）；
      - check_element.text 取正本 rdfs:label、law_clause.text 取同条号 article_text（均 100% 覆盖）；
      - 投影后若 title 与正文双双为空 → 视为"该检查未被投影覆盖"，返回 None 让上层回落 canonical。
    """
    try:
        rows = _q("""
            SELECT c.check_code, e.uri, e.slug,
                   COALESCE(NULLIF(e.title, ''), NULLIF(e.label, ''), NULLIF(c.title, '')) AS title,
                   c.domain, c.domain_label, c.priority, c.regulation,
                   c.article_no,
                   COALESCE(NULLIF(e.summary, ''), NULLIF(c.article_text, '')) AS summary
            FROM inspection_check c
            JOIN kb_entity e ON e.uri = c.entity_uri
            WHERE c.check_code = %s LIMIT 1
        """, (check_code,))
        if not rows:
            return None
        r = rows[0]
        if not (r["title"] or r["summary"]):
            return None  # 投影未覆盖该检查（如 93-x.y 早期版本）→ 回落 canonical
        elements = []
        try:
            erows = _q("""
                SELECT element_code,
                       COALESCE(NULLIF(text, ''), NULLIF(criteria, '')) AS text
                FROM check_element WHERE check_code = %s ORDER BY element_code
            """, (check_code,))
            elements = [{"elementCode": e["element_code"] or "", "text": e["text"] or ""}
                        for e in erows]
        except Exception:  # noqa: BLE001
            pass
        clauses = []
        try:
            crow = _q("""
                SELECT e2.slug
                FROM kb_relation rel
                JOIN kb_entity e2 ON e2.uri = rel.object_uri
                WHERE rel.predicate = 'citesClause'
                  AND rel.subject_uri = %s
            """, (r["uri"],))
            clauses = [c["slug"] for c in crow]
        except Exception:  # noqa: BLE001
            pass
        return {
            "checkCode": r["check_code"],
            "id": r["slug"],
            "title": r["title"] or "",
            "domain": r["domain"] or "",
            "domainLabel": r["domain_label"] or "",
            "priority": r["priority"] or "",
            "regulation": r["regulation"] or "",
            "articleNo": r["article_no"] or "",
            "summary": r["summary"] or "",
            "citesClause": clauses,
            "elements": elements,
            "source": "db",
        }
    except Exception:  # noqa: BLE001
        return None


# ===========================================================================
# P0 三路检索（向量路 / 图谱路 / RAG 路）+ 关键词 ILIKE 路融合
# ---------------------------------------------------------------------------
# 设计纪律：
#   - 每一路独立探测、独立降级，任何一路不可用都不抛错、不影响其余路与既有结果；
#   - 关键词 ILIKE 路（本模块 search()）保留；canonical+JSON 双源在 kb_read 层保留；
#   - 向量路：pgvector 余弦（TEI bge-m3 嵌入），TEI/PG 不可用 → 降级关键词；
#   - 图谱路：Fuseki SPARQL 优先，不可用 → PG kb_relation 实体关联兜底；
#   - RAG 路：RAGFlow /retrieval 只读，绝不写入既有知识库。
# ===========================================================================
import json as _json  # noqa: E402
import os as _os  # noqa: E402
import urllib.request as _urlreq  # noqa: E402
import urllib.parse as _urlparse  # noqa: E402

from .. import config as _cfg

# ---- 路由端点（环境变量可覆盖；容器内 127.0.0.1 自动改写 host.docker.internal）----
def _host(url: str) -> str:
    """容器内访问宿主服务：127.0.0.1 → host.docker.internal（宿主直连时原样返回）。"""
    if not url:
        return url
    return url.replace("127.0.0.1", "host.docker.internal") if _os.path.exists("/.dockerenv") else url


TEI_EMBED_URL = _os.environ.get("TEI_EMBED_URL", "http://127.0.0.1:18002/embed")
RAGFLOW_BASE = _os.environ.get("RAGFLOW_BASE", "http://127.0.0.1:19380").rstrip("/")
RAGFLOW_API_TOKEN = _os.environ.get(
    "RAGFLOW_API_TOKEN", "ragflow-6gBYDi-FMuZ7zY7sqdDfG-IkSNCILhbDurLJ0qQ5k54")
RAGFLOW_DATASET_ID = _os.environ.get(
    "RAGFLOW_DATASET_ID", "bf1312d28b3d11f1847f73b364e50e19")
FUSEKI_ENDPOINT = _cfg.GRAPH_STORE_ENDPOINT
FUSEKI_DATASET = _cfg.GRAPH_STORE_DATASET


def _http_json(method: str, url: str, payload: dict | None = None,
               headers: dict | None = None, timeout: float = 8.0):
    body = _json.dumps(payload).encode("utf-8") if payload is not None else None
    req = _urlreq.Request(url, data=body, method=method,
                          headers={"Content-Type": "application/json",
                                   "Accept": "application/json", **(headers or {})})
    with _urlreq.urlopen(req, timeout=timeout) as resp:
        return _json.loads(resp.read().decode("utf-8"))


def _pg_connect_optional():
    """三路检索专用连接：按 DSN 候选依次尝试（容器内首试 host.docker.internal 改写版）。
    任何失败返回 None（调用方降级），不抛给上层。"""
    for dsn in _dsn_candidates():
        try:
            import psycopg2  # noqa: E402
            conn = psycopg2.connect(dsn, connect_timeout=3)
            conn.set_session(readonly=True, autocommit=True)
            return conn
        except Exception:  # noqa: BLE001
            continue
    return None


# ---------------- 路 1：向量（pgvector 余弦，TEI 嵌入）----------------
def _tei_embed(text: str) -> list[float] | None:
    try:
        data = _http_json("POST", _host(TEI_EMBED_URL), {"inputs": [text], "normalize": True})
        return data[0] if data else None
    except Exception:  # noqa: BLE001
        return None


def _pgvec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in v) + "]"


def vector_search(q: str, limit: int = 8) -> list[dict]:
    """TEI 嵌入 + kb_embedding 余弦 top-N；TEI/PG 不可用返回空（调用方降级关键词）。"""
    vec = _tei_embed(q)
    if vec is None:
        return []
    conn = _pg_connect_optional()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT k.ref_code, k.doc_key, k.embed_text, c.title,
                          1 - (k.embedding <=> %s::vector) AS score
                   FROM kb_embedding k
                   LEFT JOIN inspection_check c ON c.check_code = k.ref_code
                   WHERE k.ref_type='inspection_check'
                   ORDER BY k.embedding <=> %s::vector LIMIT %s""",
                (_pgvec(vec), _pgvec(vec), int(limit)),
            )
            rows = cur.fetchall()

        def _label(embed_text: str, title: str) -> str:
            # embed_text 形如 "[93-20.10] 标题。正文"；剥掉编号前缀
            body = embed_text.split("] ", 1)[-1] if "] " in embed_text else embed_text
            cand = (title or "").strip()
            # jg93 标题/正文常以"其他。"占位开头，剥掉占位后取分类或冒号后实质段
            def _clean(s: str) -> str:
                s = s.strip()
                while s.startswith("其他"):
                    s = s.lstrip("其他").lstrip("。. ").strip()
                if "：" in s:
                    head, tail = s.rsplit("：", 1)
                    if tail.strip() and tail.strip() != "其他":
                        return tail.strip()
                    s = head
                return s
            if cand and not cand.startswith("其他"):
                return cand[:60]
            return (_clean(body) or body)[:60]

        return [{
            "id": r[0], "type": "check", "label": _label(r[2], r[3]),
            "checkCode": r[0], "docKey": r[1], "score": round(float(r[4]), 4),
            "route": "vector",
        } for r in rows]
    except Exception:  # noqa: BLE001
        return []
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------- 路 2：图谱（Fuseki SPARQL → PG kb_relation 兜底）----------------
def graph_search(q: str, limit: int = 8) -> list[dict]:
    """Fuseki 关键词命中 label/summary 并返回实体；Fuseki 不可用走 PG 关系两跳。"""
    hits = _fuseki_search(q, limit)
    if hits:
        return hits
    return _pg_graph_search(q, limit)


PLATFORM_GRAPH = "http://dsec/platform"


def _fuseki_search(q: str, limit: int) -> list[dict]:
    """P2：优先查平台权威命名图 <http://dsec/platform>；空结果回退整库默认图，再由调用方走 PG 兜底。"""
    try:
        q_esc = q.replace("\\", "\\\\").replace('"', '\\"')
        def _query(platform: bool) -> list:
            scope = (f"GRAPH <{PLATFORM_GRAPH}> {{ ?s rdfs:label ?label . }}"
                     if platform else "?s rdfs:label ?label .")
            sparql = (
                "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
                "SELECT ?s ?label WHERE { " + scope +
                " FILTER(CONTAINS(LCASE(?label), LCASE(\"" + q_esc + "\"))) } "
                "LIMIT " + str(int(limit))
            )
            url = _host(FUSEKI_ENDPOINT) + "/" + FUSEKI_DATASET + "/query"
            data = _fuseki_post(url, sparql)
            out = []
            for b in data.get("results", {}).get("bindings", []):
                s = b["s"]["value"]
                slug = s.rsplit("/", 1)[-1]
                out.append({"id": slug, "type": "graph",
                            "label": b.get("label", {}).get("value", slug),
                            "score": None, "route": "graph:fuseki", "uri": s})
            return out

        out = _query(platform=True)
        if out:
            return out
        return _query(platform=False)  # 回退 EKOS 默认图只读
    except Exception:  # noqa: BLE001
        return []


def _fuseki_post(url: str, sparql: str) -> dict:
    req = _urlreq.Request(url, data=sparql.encode("utf-8"), method="POST",
                          headers={"Accept": "application/sparql-results+json",
                                   "Content-Type": "application/sparql-query"})
    with _urlreq.urlopen(req, timeout=6) as resp:
        return _json.loads(resp.read().decode("utf-8"))


def _pg_graph_search(q: str, limit: int) -> list[dict]:
    """兜底：kb_entity ILIKE 种子 → kb_relation 两跳邻居。"""
    conn = _pg_connect_optional()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            like = f"%{q}%"
            cur.execute(
                """SELECT DISTINCT e2.slug, e2.entity_type,
                          COALESCE(NULLIF(e2.label,''),e2.title,e2.slug) AS label
                   FROM kb_relation r
                   JOIN kb_entity e1 ON e1.uri = r.subject_uri
                   JOIN kb_entity e2 ON e2.uri = r.object_uri
                   WHERE (e1.label ILIKE %s OR e1.title ILIKE %s OR e1.summary ILIKE %s)
                   LIMIT %s""",
                (like, like, like, int(limit)),
            )
            rows = cur.fetchall()
        return [{"id": r[0], "type": (r[1] or "entity").lower(), "label": r[2] or r[0],
                 "score": None, "route": "graph:pg"} for r in rows]
    except Exception:  # noqa: BLE001
        return []
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------- 路 3：RAG（RAGFlow 只读检索）----------------
def rag_search(q: str, limit: int = 5) -> list[dict]:
    """只检索既有 RAGFlow 知识库，绝不写入。返回 chunk 片段。"""
    if not RAGFLOW_API_TOKEN:
        return []
    try:
        data = _http_json(
            "POST", f"{_host(RAGFLOW_BASE)}/api/v1/retrieval",
            {"question": q, "dataset_ids": [RAGFLOW_DATASET_ID],
             "page": 1, "page_size": int(limit), "similarity_threshold": 0.1},
            headers={"Authorization": f"Bearer {RAGFLOW_API_TOKEN}"},
            timeout=10,
        )
        if data.get("code") != 0:
            return []
        chunks = data.get("data", {}).get("chunks", [])
        out = []
        for ch in chunks:
            out.append({
                "id": ch.get("id"), "type": "rag",
                "label": ch.get("document_keyword") or "RAG 片段",
                "snippet": (ch.get("content") or "")[:160],
                "score": round(float(ch.get("similarity", 0)), 4),
                "route": "rag",
                "documentId": ch.get("document_id"),
                "datasetId": ch.get("dataset_id"),
            })
        return out
    except Exception:  # noqa: BLE001
        return []


# ---------------- 三路 + 关键词融合 ----------------
def fused_search(q: str, limit: int = 20) -> dict:
    """融合向量/图谱/RAG/关键词四路，按路由去重合并；任一路失败自动跳过。

    返回形状与 search() 兼容：{query,total,results:[{id,type,label,checkCode?,route,score?}]}。
    """
    q = (q or "").strip()
    seen: dict[str, dict] = {}

    def _merge_routes(ex: dict, incoming: dict) -> None:
        """同一实体被多路命中时合并路由来源，不剔除首条（基线）结果。"""
        ex.setdefault("routes", [ex.get("route", "keyword")])
        r = incoming.get("route")
        if r and r not in ex["routes"]:
            ex["routes"].append(r)
        if str(r).startswith("graph"):
            ex["graph"] = True
            # 展示路由叠加 graph，便于前端/探针识别图谱参与
            if "graph" not in str(ex.get("route", "")):
                ex["route"] = f"{ex.get('route', 'keyword')}+graph"

    def _add(item: dict) -> None:
        iid = item.get("id")
        if not iid:
            return
        if iid in seen:
            _merge_routes(seen[iid], item)
            return
        seen[iid] = item

    # 关键词 ILIKE 路（既有）
    try:
        for it in search(q, limit).get("results", []):
            it = dict(it)
            it.setdefault("route", "keyword")
            _add(it)
    except Exception:  # noqa: BLE001
        pass
    # 向量路
    for it in vector_search(q, limit=8):
        _add(it)
    # 图谱路
    for it in graph_search(q, limit=8):
        _add(it)
    # RAG 路
    for it in rag_search(q, limit=5):
        _add(it)
    # WeKnora 向量路（P0-4）：直连 WeKnora Postgres 做 pgvector 检索
    try:
        from . import weknora_retriever
        for it in weknora_retriever.search(q, limit=5):
            _add(it)
    except Exception:  # noqa: BLE001
        pass

    results = list(seen.values())[:limit]
    return {"query": q, "total": len(results), "results": results,
            "routes": ["keyword", "vector", "graph", "rag", "weknora"]}
