"""WeKnora 知识库适配器（P0-4 向量检索 + v1.16.0 Wiki 页面读取）。

大白话：直接连 WeKnora 的 Postgres，用 pgvector 做余弦相似度检索，
绕过 WeKnora API 端点不明确的问题。8420 与 WeKnora 已在同一 docker 网络。

v1.16.0 扩展（PRD M1/M6）：新增 Wiki 页面读取（knowledges + chunks）与
"检查项实时覆盖"查询，供 kb_source 取数适配器作为"实时源"调用。

v1.17.0 扩展（PRD M11.4 / D5）：新增知识加工**写路径**（官方 API `knowledge/manual`
投递，不直写库表）与加工状态查询（`knowledge_status`），供 /api/kb/ingest 使用。
"""
from __future__ import annotations

import os
import urllib.request
import urllib.error
import json

# WeKnora Postgres 连接配置（从环境变量读，默认值为本地开发）
_WK_PG_HOST = os.getenv("WEKNORA_PG_HOST", "ekos-weknora-postgres")
_WK_PG_PORT = os.getenv("WEKNORA_PG_PORT", "5432")
_WK_PG_USER = os.getenv("WEKNORA_PG_USER", "weknora")
_WK_PG_PASSWORD = os.getenv("WEKNORA_PG_PASSWORD", "weknora_p2_dev_only_change_me")
_WK_PG_DB = os.getenv("WEKNORA_PG_DB", "weknora")

# Ollama embedding 服务（和 WeKnora 用同一个）
_OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://host.docker.internal:11434")
_EMBED_MODEL = os.getenv("WEKNORA_EMBED_MODEL", "nomic-embed-text")

# 知识库 ID（数据安全知识库）
_KB_ID = os.getenv("WEKNORA_KB_ID", "71fbeecd-fada-46b7-8643-a86793a73a9b")


def _ollama_embed(text: str) -> list[float] | None:
    """调用 Ollama 生成 embedding 向量。"""
    try:
        req = urllib.request.Request(
            f"{_OLLAMA_BASE}/api/embeddings",
            data=json.dumps({"model": _EMBED_MODEL, "prompt": text}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("embedding")
    except Exception:
        return None


def search(q: str, limit: int = 8) -> list[dict]:
    """WeKnora 向量检索：query → Ollama embedding → pgvector 余弦 top-N。

    返回形状与 vector_search 一致：[{id, type, label, route, score}]
    """
    q = (q or "").strip()
    if not q:
        return []

    # 1. 生成 query embedding
    qvec = _ollama_embed(q)
    if qvec is None:
        return []

    # 2. 连接 WeKnora Postgres 并做向量检索
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=_WK_PG_HOST, port=_WK_PG_PORT,
            user=_WK_PG_USER, password=_WK_PG_PASSWORD, dbname=_WK_PG_DB,
        )
    except Exception:
        return []

    try:
        with conn.cursor() as cur:
            # 用 halfvec 做余弦相似度（WeKnora 的 embeddings 表用的是 halfvec）
            # 维度自动适配：先查 dimension=1024 的
            vec_str = "[" + ",".join(str(x) for x in qvec) + "]"
            cur.execute(
                """SELECT e.id, e.knowledge_id, e.content, k.title,
                          1 - (e.embedding <=> %s::halfvec) AS score
                   FROM embeddings e
                   JOIN knowledges k ON e.knowledge_id = k.id
                   WHERE e.knowledge_base_id = %s
                     AND e.is_enabled = true
                     AND e.dimension = %s
                   ORDER BY e.embedding <=> %s::halfvec
                   LIMIT %s""",
                (vec_str, _KB_ID, len(qvec), vec_str, int(limit)),
            )
            rows = cur.fetchall()

        results = []
        for row in rows:
            eid, kid, content, title, score = row
            results.append({
                "id": str(eid),
                "type": "weknora_chunk",
                "label": title or (content[:80] + "..." if len(content) > 80 else content),
                "route": "weknora_vector",
                "score": float(score),
                "knowledge_id": str(kid),
                "content": content[:200] if content else "",
            })
        return results
    except Exception:
        return []
    finally:
        conn.close()


def _conn():
    """建立 WeKnora Postgres 只读连接（失败抛给调用方）。"""
    import psycopg2
    return psycopg2.connect(
        host=_WK_PG_HOST, port=_WK_PG_PORT,
        user=_WK_PG_USER, password=_WK_PG_PASSWORD, dbname=_WK_PG_DB,
        connect_timeout=3,
    )


def _q(sql: str, args: tuple = ()) -> list[dict]:
    """只读查询：RealDictCursor → list[dict]。异常向上抛，由调用方降级。"""
    conn = _conn()
    try:
        import psycopg2.extras
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, args)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def health() -> dict:
    """WeKnora 向量检索健康检查（含知识条目数）。"""
    try:
        conn = _conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM embeddings WHERE knowledge_base_id = %s", (_KB_ID,))
                emb = cur.fetchone()[0]
                cur.execute(
                    "SELECT COUNT(*) FROM knowledges WHERE knowledge_base_id = %s AND deleted_at IS NULL",
                    (_KB_ID,))
                pages = cur.fetchone()[0]
        finally:
            conn.close()
        return {"ok": True, "embedding_count": emb, "knowledge_count": pages}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ===========================================================================
# v1.16.0 Wiki 页面读取（PRD M1.1 / M6）
# 大白话：知识库平台把每条知识存成"页面"（knowledges），正文切成"段落"（chunks）。
# 这里按页面 id/标题读回整页正文，并把页面按 [type] 前缀聚成 Wiki 目录树。
# 全部只读，任何异常返回空，由 kb_source 决定降级。
# ===========================================================================

_PAGE_COLS = "id::text AS id, title, type, parse_status, enable_status, folder_path, updated_at"


def wiki_list(limit: int = 500) -> list[dict]:
    """列出知识库页面（Wiki 目录）。按标题排序，返回精简页面清单。"""
    rows = _q(
        f"""SELECT {_PAGE_COLS} FROM knowledges
            WHERE knowledge_base_id = %s AND deleted_at IS NULL AND enable_status = 'enabled'
            ORDER BY title LIMIT %s""",
        (_KB_ID, int(limit)),
    )
    out = []
    for r in rows:
        title = r.get("title") or ""
        # 标题形如 "[law] 互联网信息服务算法推荐管理规定" → 拆出 type 前缀
        ptype = r.get("type") or ""
        name = title
        if title.startswith("[") and "]" in title:
            head, _, tail = title[1:].partition("]")
            ptype = ptype or head.strip()
            name = tail.strip() or title
        out.append({
            "pageId": r["id"], "title": title, "name": name, "type": ptype,
            "folder": r.get("folder_path") or "",
            "parseStatus": r.get("parse_status") or "",
            "updatedAt": str(r.get("updated_at") or ""),
        })
    return out


def wiki_get(page_id: str) -> dict | None:
    """按页面 id 或精确标题读取整页正文（正文 = 各 chunk 按序拼接）。"""
    page_id = (page_id or "").strip()
    if not page_id:
        return None
    rows = _q(
        f"""SELECT {_PAGE_COLS} FROM knowledges
            WHERE knowledge_base_id = %s AND deleted_at IS NULL
              AND (id::text = %s OR title = %s)
            LIMIT 1""",
        (_KB_ID, page_id, page_id),
    )
    if not rows:
        return None
    r = rows[0]
    chunks = _q(
        """SELECT content FROM chunks
           WHERE knowledge_id = %s AND is_enabled = true AND deleted_at IS NULL
           ORDER BY chunk_index""",
        (r["id"],),
    )
    content = "\n\n".join((c.get("content") or "").strip() for c in chunks if c.get("content"))
    return {
        "pageId": r["id"], "title": r.get("title") or "",
        "type": r.get("type") or "", "folder": r.get("folder_path") or "",
        "content": content, "chunkCount": len(chunks),
        "updatedAt": str(r.get("updated_at") or ""),
    }


def wiki_find(query: str, limit: int = 5) -> list[dict]:
    """按标题子串查找页面（用于实时覆盖：给定检查项关键词找对应知识页）。"""
    q = (query or "").strip()
    if not q:
        return []
    rows = _q(
        f"""SELECT {_PAGE_COLS} FROM knowledges
            WHERE knowledge_base_id = %s AND deleted_at IS NULL
              AND title ILIKE %s
            ORDER BY title LIMIT %s""",
        (_KB_ID, f"%{q}%", int(limit)),
    )
    return [{"pageId": r["id"], "title": r.get("title") or "",
             "type": r.get("type") or ""} for r in rows]


# ===========================================================================
# v1.17.0 知识加工写路径（PRD M11.4 / D5）
# 大白话：加工**不直写知识库的表**（会绕过它的解析/分块/向量化管线、破坏一致性），
# 一律走知识库平台**官方 API** 投递，由平台自己解析；进度再读它的 knowledges 状态。
# 纪律：所有异常由调用方（kb_source）降级处理，本层不吞错但也不主动崩溃进程。
# ===========================================================================

_API_BASE = os.getenv("WEKNORA_API_BASE", "http://ekos-weknora:8080").rstrip("/")
_API_TOKEN = os.getenv("WEKNORA_API_TOKEN", "")


def api_configured() -> bool:
    """加工通道是否可用（配置了官方 API 地址与令牌）。"""
    return bool(_API_BASE and _API_TOKEN)


def submit_manual(title: str, content: str, timeout: int = 30) -> dict:
    """投递一条知识到知识库平台（官方 API `knowledge/manual`）。

    返回：{ok, knowledgeId?, title, status, detail?}。失败不抛错，`ok=False` 由上层降级。
    """
    title = (title or "").strip()
    content = (content or "").strip()
    if not title or not content:
        return {"ok": False, "status": "invalid", "detail": "标题与正文不能为空"}
    if not api_configured():
        return {"ok": False, "status": "unconfigured",
                "detail": "WEKNORA_API_BASE / WEKNORA_API_TOKEN 未配置"}
    url = f"{_API_BASE}/api/v1/knowledge-bases/{_KB_ID}/knowledge/manual"
    payload = json.dumps({"title": title, "content": content}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Authorization": f"Bearer {_API_TOKEN}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "ignore")
        data = {}
        try:
            data = json.loads(body) if body else {}
        except Exception:  # noqa: BLE001
            data = {}
        inner = data.get("data") if isinstance(data.get("data"), dict) else data
        kid = (inner.get("id") or inner.get("knowledge_id")
               or data.get("id") or data.get("knowledge_id") or "")
        return {"ok": True, "knowledgeId": str(kid), "title": title,
                "status": (inner.get("parse_status") or inner.get("status") or "submitted")}
    except urllib.error.HTTPError as e:  # noqa: F821 — urllib.error 已隐含导入
        detail = ""
        try:
            detail = e.read().decode("utf-8", "ignore")[:300]
        except Exception:  # noqa: BLE001
            detail = ""
        return {"ok": False, "status": f"http_{e.code}", "detail": detail or str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "status": "error", "detail": str(e)[:300]}


def knowledge_status(knowledge_id: str) -> dict | None:
    """读取某条知识的加工状态（解析/分块/向量化）：knowledges 主表 + chunks/embeddings 计数。"""
    kid = (knowledge_id or "").strip()
    if not kid:
        return None
    rows = _q(
        f"""SELECT {_PAGE_COLS} FROM knowledges
            WHERE knowledge_base_id = %s AND id::text = %s
            LIMIT 1""",
        (_KB_ID, kid),
    )
    if not rows:
        return None
    r = rows[0]
    chunk_n = 0
    emb_n = 0
    try:
        c = _q("SELECT COUNT(*) AS n FROM chunks WHERE knowledge_id = %s AND deleted_at IS NULL",
               (r["id"],))
        chunk_n = int(c[0]["n"]) if c else 0
    except Exception:  # noqa: BLE001
        chunk_n = 0
    try:
        e = _q("""SELECT COUNT(*) AS n FROM embeddings
                  WHERE knowledge_id = %s AND is_enabled = true""", (r["id"],))
        emb_n = int(e[0]["n"]) if e else 0
    except Exception:  # noqa: BLE001
        emb_n = 0
    return {
        "knowledgeId": r["id"], "title": r.get("title") or "",
        "parseStatus": r.get("parse_status") or "",
        "enableStatus": r.get("enable_status") or "",
        "chunkCount": chunk_n, "embeddingCount": emb_n,
        "updatedAt": str(r.get("updated_at") or ""),
        # 分块与向量化都就绪即视为加工完成
        "ready": bool(chunk_n > 0 and emb_n > 0),
    }
