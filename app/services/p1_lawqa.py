"""P1 法规原文带引用问答（TEI bge-m3 + pgvector）。

说明：本环境 RAGFlow 新文档上传仅落 DB、minio 对象写入失败（冻结 EKOS 不可改，
见交付文档遗留问题），故法规问答复用已验证可用的 TEI+pgvector 栈，新建 additive
表 law_chunk + law_chunk_embedding，绝不改动既有 RAGFlow 库。

链路：index() 聚合 data/checks/*.json article_text → TEI 嵌入 → pgvector；
search(q) 余弦 top-N，返回带文号/条号/出处的引用片段。
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from ..config import KB_PG_DSN, BASE_DIR

CHECKS_DIR = BASE_DIR / "data" / "checks"
TEI_URL = os.environ.get("TEI_EMBED_URL", "http://127.0.0.1:18002/embed")
if os.path.exists("/.dockerenv"):
    TEI_URL = TEI_URL.replace("127.0.0.1", "host.docker.internal")
DOC_LABELS = {
    "jg24": "金规24号 银行保险机构数据安全管理办法",
    "jg93": "93号文 银保数据安全专项整治自查表",
    "pboc3": "人民银行令〔2025〕第3号 业务领域数据安全管理办法",
    "jf8": "金发〔2026〕8号 人工智能安全开发应用治理",
}


def _dsn_candidates():
    c = [KB_PG_DSN]
    if os.path.exists("/.dockerenv") and "127.0.0.1" in KB_PG_DSN:
        c.append(KB_PG_DSN.replace("127.0.0.1", "host.docker.internal"))
    return c


def _connect(readonly=False):
    import psycopg2
    last = None
    for dsn in _dsn_candidates():
        try:
            conn = psycopg2.connect(dsn, connect_timeout=5)
            conn.set_session(readonly=readonly, autocommit=True)
            return conn
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def ensure_schema():
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                """CREATE TABLE IF NOT EXISTS law_chunk (
                    chunk_id   text PRIMARY KEY,
                    doc_key    text NOT NULL,
                    article_no text,
                    check_code text,
                    chapter    text,
                    regulation text,
                    title      text,
                    content    text NOT NULL,
                    model      text,
                    dim        integer,
                    embedding  vector(1024)
                )"""
            )
    finally:
        conn.close()


def _tei_embed(text: str):
    body = json.dumps({"inputs": [text], "normalize": True}).encode()
    req = urllib.request.Request(TEI_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    return data[0] if data else None


def _load(dk):
    p = CHECKS_DIR / f"{dk}-checks.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("checks") or data.get("items") or next(iter(data.values()))
    return data


def index() -> dict:
    """聚合四文号 article_text 分块嵌入，幂等 ON CONFLICT DO NOTHING。"""
    ensure_schema()
    conn = _connect()
    inserted = 0
    try:
        with conn.cursor() as cur:
            for dk in DOC_LABELS:
                for it in _load(dk):
                    text = (it.get("article_text") or "").strip()
                    if len(text) < 10:
                        continue
                    cid = f"{dk}-{it.get('id')}"
                    emb = _tei_embed(text)
                    vec = "[" + ",".join(f"{x:.8f}" for x in emb) + "]"
                    cur.execute(
                        """INSERT INTO law_chunk
                           (chunk_id,doc_key,article_no,check_code,chapter,regulation,title,content,model,dim,embedding)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'bge-m3',1024,%s)
                           ON CONFLICT (chunk_id) DO NOTHING""",
                        (cid, dk, it.get("article_no"), it.get("id"), it.get("chapter"),
                         it.get("regulation"), it.get("title"), text, vec))
                    inserted += cur.rowcount or 0
    finally:
        conn.close()
    return {"indexed": inserted}


def search(q: str, limit: int = 5, threshold: float = 0.35) -> dict:
    ensure_schema()
    emb = _tei_embed(q)
    vec = "[" + ",".join(f"{x:.8f}" for x in emb) + "]"
    conn = _connect(readonly=True)
    hits = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT chunk_id,doc_key,article_no,check_code,chapter,regulation,title,content,
                          (embedding <=> %s) AS dist
                   FROM law_chunk ORDER BY embedding <=> %s LIMIT %s""",
                (vec, vec, limit))
            for r in cur.fetchall():
                sim = 1 - float(r[8])
                if sim < threshold:
                    continue
                hits.append({
                    "chunkId": r[0], "docKey": r[1],
                    "docLabel": DOC_LABELS.get(r[1], r[1]),
                    "articleNo": r[2], "checkCode": r[3], "chapter": r[4],
                    "regulation": r[5], "title": r[6],
                    "content": r[7], "score": round(sim, 4),
                    "citation": f"《{DOC_LABELS.get(r[1], r[1])}》{r[2] or ''} {r[6] or ''}".strip(),
                })
    finally:
        conn.close()
    return {"query": q, "total": len(hits), "hits": hits}


def stats() -> dict:
    ensure_schema()
    conn = _connect(readonly=True)
    out = {}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT doc_key,count(*) FROM law_chunk GROUP BY doc_key ORDER BY doc_key")
            out["by_doc"] = {r[0]: r[1] for r in cur.fetchall()}
            cur.execute("SELECT count(*) FROM law_chunk WHERE embedding IS NOT NULL")
            out["embedded"] = cur.fetchone()[0]
    finally:
        conn.close()
    return out
