#!/usr/bin/env python3
"""P0 向量化：TEI(bge-m3, 1024维) 为 344 检查项生成向量，写入新建表 kb_embedding。

纪律：只新建 kb_embedding 表 / 只 INSERT（ON CONFLICT DO NOTHING），不动既有表与既有数据。
嵌入文本 = 编号 + 标题 + 条文要点（权威源 data/checks/*.json，保证 jg24 标题不丢）。

用法：
  .venv/bin/python scripts/phase/p0_embed_checks.py            # 增量嵌入缺失项
  .venv/bin/python scripts/phase/p0_embed_checks.py --selftest # 只跑语义自测（不写）
  .venv/bin/python scripts/phase/p0_embed_checks.py --reembed   # 清空本脚本自建表后重建（仅 kb_embedding）
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2  # noqa: E402
from app.config import KB_PG_DSN, BASE_DIR  # noqa: E402

TEI_URL = "http://127.0.0.1:18002/embed"
MODEL = "bge-m3"
DIM = 1024
BATCH = 8
CHECKS_DIR = BASE_DIR / "data" / "checks"
DOC_FILES = ["jg24", "jg93", "pboc3", "jf8"]


def tei_embed(texts: list[str]) -> list[list[float]]:
    body = json.dumps({"inputs": texts, "normalize": True}).encode("utf-8")
    req = urllib.request.Request(TEI_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data


def load_checks() -> list[dict]:
    out = []
    for f in DOC_FILES:
        d = json.loads((CHECKS_DIR / f"{f}-checks.json").read_text(encoding="utf-8"))
        for c in d["checks"]:
            title = c.get("title", "")
            body = c.get("article_text", "")
            embed_text = f"[{c['id']}] {title}。{body}".strip()
            out.append({
                "ref_code": c["id"], "doc_key": f,
                "title": title, "embed_text": embed_text,
            })
    return out


def ensure_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_embedding (
          embedding_id BIGSERIAL PRIMARY KEY,
          ref_type     TEXT NOT NULL DEFAULT 'inspection_check',
          ref_code     TEXT NOT NULL,
          doc_key      TEXT,
          embed_text   TEXT,
          model        TEXT,
          dim          INTEGER,
          embedding    vector(%d),
          created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (ref_type, ref_code)
        )
        """ % DIM
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_emb_ref ON kb_embedding(ref_type,ref_code)")


def pgvec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in v) + "]"


def embed_all(records: list[dict], reembed: bool) -> None:
    conn = psycopg2.connect(KB_PG_DSN)
    cur = conn.cursor()
    ensure_table(cur)
    if reembed:
        cur.execute("DELETE FROM kb_embedding")
    conn.commit()

    cur.execute("SELECT ref_code FROM kb_embedding WHERE ref_type='inspection_check'")
    done = {r[0] for r in cur.fetchall()}
    todo = [r for r in records if r["ref_code"] not in done]
    print(f"[embed] 已嵌入 {len(done)}，待嵌入 {len(todo)}")

    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        vecs = tei_embed([r["embed_text"] for r in chunk])
        for r, v in zip(chunk, vecs):
            cur.execute(
                """INSERT INTO kb_embedding(ref_type,ref_code,doc_key,embed_text,model,dim,embedding)
                   VALUES('inspection_check',%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (ref_type,ref_code) DO NOTHING""",
                (r["ref_code"], r["doc_key"], r["embed_text"], MODEL, DIM, pgvec(v)),
            )
        conn.commit()
        print(f"[embed] {min(i+BATCH,len(todo))}/{len(todo)}")
    cur.execute("SELECT count(*) FROM kb_embedding WHERE ref_type='inspection_check'")
    print("[embed] kb_embedding inspection_check 行数 =", cur.fetchone()[0])
    conn.close()


def selftest(queries: list[str], topn: int = 5) -> None:
    conn = psycopg2.connect(KB_PG_DSN)
    cur = conn.cursor()
    ensure_table(cur)
    conn.commit()
    for q in queries:
        qv = tei_embed([q])[0]
        cur.execute(
            """SELECT ref_code, doc_key, left(embed_text,80) txt,
                      1 - (embedding <=> %s::vector) AS cosine
               FROM kb_embedding WHERE ref_type='inspection_check'
               ORDER BY embedding <=> %s::vector LIMIT %s""",
            (pgvec(qv), pgvec(qv), topn),
        )
        print(f"\n=== 查询: {q} ===")
        for code, dk, txt, cos in cur.fetchall():
            print(f"  {cos:.4f}  [{dk}] {code}  {txt}")
    conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--reembed", action="store_true")
    args = ap.parse_args()
    records = load_checks()
    if args.selftest:
        selftest(["个人信息保护", "数据出境", "风险评估"])
        return 0
    embed_all(records, reembed=args.reembed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
