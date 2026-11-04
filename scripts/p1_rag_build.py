#!/usr/bin/env python3
"""P1 RAGFlow 法规原文库：聚合四文号 article_text + law_clause → markdown → 上传新数据集 → 解析。

只读既有 EKOS 库，只写本次新建数据集 f589ba28...。用法：
  .venv/bin/python scripts/p1_rag_build.py build      # 仅生成 markdown 到 reports/p1_rag/
  .venv/bin/python scripts/p1_rag_build.py upload     # 上传+触发解析
  .venv/bin/python scripts/p1_rag_build.py qa "问题"  # 带引用问答
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.config import BASE_DIR  # noqa: E402

RAG_BASE = "http://127.0.0.1:19380"
TOKEN = "ragflow-6gBYDi-FMuZ7zY7sqdDfG-IkSNCILhbDurLJ0qQ5k54"
DATASET_ID = "f589ba28ce6d11f18c605b5ce040edea"
OUT = ROOT / "reports" / "p1_rag"
DOCS = {"jg24": "金规24号（银行保险机构数据安全管理办法）",
        "jg93": "93号文（银保数据安全专项整治自查表）",
        "pboc3": "人民银行令〔2025〕第3号（业务领域数据安全管理办法）",
        "jf8": "金发〔2026〕8号（人工智能安全开发应用治理）"}


def _load(dk):
    p = BASE_DIR / "data" / "checks" / f"{dk}-checks.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("checks") or data.get("items") or next(iter(data.values()))
    return data


def build_markdown():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for dk, label in DOCS.items():
        items = _load(dk)
        lines = [f"# {label}", f"> 文号标识：{dk}｜来源：data/checks/{dk}-checks.json 聚合", ""]
        for it in items:
            art = (it.get("article_text") or "").strip()
            if not art:
                continue
            lines.append(f"## [{dk}] {it.get('article_no','')} {it.get('title','')}")
            lines.append(f"- 章节：{it.get('chapter','')}")
            lines.append(f"- 依据：{it.get('regulation','')}")
            lines.append(f"- 检查项编号：{it.get('id','')}")
            lines.append("")
            lines.append(art)
            lines.append("")
        fp = OUT / f"{dk}_法规原文.md"
        fp.write_text("\n".join(lines), encoding="utf-8")
        manifest.append((dk, fp, len(items)))
    # law_clause 聚合（经 PG 只读）
    try:
        import psycopg2
        from app.config import KB_PG_DSN
        conn = psycopg2.connect(KB_PG_DSN, connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT clause_id, law_uri, article_no, text FROM law_clause WHERE text IS NOT NULL AND text<>''")
        rows = cur.fetchall()
        conn.close()
        if rows:
            lines = ["# law_clause 法规条款聚合（ekos_ds_kb.law_clause）", ""]
            for cid, uri, no, text in rows:
                lines.append(f"## {cid} {no}")
                lines.append(f"- law_uri: {uri}")
                lines.append("")
                lines.append(text)
                lines.append("")
            fp = OUT / "law_clause_聚合.md"
            fp.write_text("\n".join(lines), encoding="utf-8")
            manifest.append(("law_clause", fp, len(rows)))
    except Exception as e:  # noqa: BLE001
        print("[warn] law_clause 跳过:", e)
    for dk, fp, n in manifest:
        print(f"[build] {dk}: {n} 条 → {fp.name} ({fp.stat().st_size} bytes)")
    return manifest


def _req(method, path, body=None, headers=None, raw=None, ctype=None):
    url = RAG_BASE + path
    h = {"Authorization": f"Bearer {TOKEN}", **(headers or {})}
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if ctype:
        h["Content-Type"] = ctype
    r = urllib.request.Request(url, data=data, method=method, headers=h)
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read().decode())


def _existing_docs() -> dict:
    st = _req("GET", f"/api/v1/datasets/{DATASET_ID}/documents?page=1&page_size=50")
    data = st.get("data")
    docs = data if isinstance(data, list) else (data or {}).get("docs") or (data or {}).get("documents", [])
    return {d.get("name"): d.get("id") for d in docs}


def upload():
    manifest = build_markdown()
    existing = _existing_docs()
    doc_ids = list(existing.values())  # 保留已有文档 id，避免重复上传
    # multipart 上传每个 md（已存在同名则跳过）
    for dk, fp, _ in manifest:
        if fp.name in existing:
            print(f"[upload {dk}] 已存在，跳过 {fp.name}")
            continue
        boundary = "----p1boundary7ma7X"
        content = fp.read_bytes()
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{fp.name}"\r\n'
            f"Content-Type: text/markdown\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
        res = _req("POST", f"/api/v1/datasets/{DATASET_ID}/documents",
                   raw=body, ctype=f"multipart/form-data; boundary={boundary}")
        print(f"[upload {dk}] code={res.get('code')} {res.get('message','')}")
        data = res.get("data")
        docs = data if isinstance(data, list) else (data or {}).get("documents", [])
        for d in docs or []:
            doc_ids.append(d["id"])
    time.sleep(2)
    # 触发解析
    res = _req("POST", f"/api/v1/datasets/{DATASET_ID}/chunks",
               body={"document_ids": doc_ids})
    print(f"[parse] code={res.get('code')} {res.get('message','')} doc_ids={len(doc_ids)}")
    # 轮询解析完成
    for _ in range(30):
        time.sleep(5)
        st = _req("GET", f"/api/v1/datasets/{DATASET_ID}/documents?page=1&page_size=20")
        data = st.get("data")
        docs = data if isinstance(data, list) else (data or {}).get("docs") or (data or {}).get("documents", [])
        statuses = [d.get("run") or d.get("status") for d in docs]
        print("  poll:", statuses)
        if all(s in ("DONE", "done", 1, "1") for s in statuses) and statuses:
            break
    print("[upload] doc_ids:", doc_ids)
    return doc_ids


def qa(question: str):
    res = _req("POST", "/api/v1/retrieval", body={
        "question": question, "dataset_ids": [DATASET_ID],
        "page": 1, "page_size": 5, "similarity_threshold": 0.15})
    chunks = res.get("data", {}).get("chunks", [])
    print(f"Q: {question}\ncode={res.get('code')} hits={len(chunks)}")
    for c in chunks:
        print(f"\n— sim={c.get('similarity'):.4f} doc={c.get('document_id')} "
              f"《{c.get('document_keyword')}》")
        print("  ", (c.get("content") or "")[:300].replace("\n", " "))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        build_markdown()
    elif cmd == "upload":
        upload()
    elif cmd == "qa":
        qa(" ".join(sys.argv[2:]))
