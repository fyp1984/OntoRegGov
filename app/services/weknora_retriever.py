"""WeKnora 向量检索适配器（P0-4）。

大白话：直接连 WeKnora 的 Postgres，用 pgvector 做余弦相似度检索，
绕过 WeKnora API 端点不明确的问题。8420 与 WeKnora 已在同一 docker 网络。
"""
from __future__ import annotations

import os
import urllib.request
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


def health() -> dict:
    """WeKnora 向量检索健康检查。"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=_WK_PG_HOST, port=_WK_PG_PORT,
            user=_WK_PG_USER, password=_WK_PG_PASSWORD, dbname=_WK_PG_DB,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM embeddings WHERE knowledge_base_id = %s", (_KB_ID,))
            cnt = cur.fetchone()[0]
        conn.close()
        return {"ok": True, "embedding_count": cnt}
    except Exception as e:
        return {"ok": False, "error": str(e)}
