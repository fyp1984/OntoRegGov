#!/usr/bin/env python3
"""P2 多存储双向一致性校验（只读；--fix 预留，本期无修复动作）。

对账口径（权威来源）：
- 检查项编号：data/checks/*.json 为源权威；与 PG inspection_check、SQLite entities 三向集合一致；
- 六维：PG check_six_dim（含 P1 新增 jg93/pboc3/jf8），覆盖 140/56/32 + jg24 116；
- 实体/关系：PG ekos_ds_kb.kb_entity/kb_relation 为权威，与 Fuseki 平台命名图 <http://dsec/platform>
  双向一致（库有图有、库无图无）；
- 嵌入：kb_embedding 344 全有向量；law_chunk 344 全嵌入（jg24 116/jg93 140/pboc3 56/jf8 32）；
- 10_知识库工程 498 实体被 kb_entity.slug 全覆盖；
- RAGFlow 既有库只读快照：bf1312… 6 docs/35 chunks 不变；
- EKOS 不变量：check_element=470/control=115/law_clause=57/doc93_selfcheck_item=139/
  doc93_report_entry=0；Fuseki 默认图 19,927 不降。

退出码：全绿 0，任一 FAIL 1。
"""
import json
import os
import sqlite3
import sys
import urllib.request

import psycopg2

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DSN = "postgresql://test:test@127.0.0.1:15432/ekos_ds_kb"
FUSEKI = "http://127.0.0.1:3030/ds"
PLATFORM_GRAPH = "http://dsec/platform"
REL_BASE = "http://dsec.local/platform/rel#"
RAGFLOW = "http://127.0.0.1:19380"
RAG_TOKEN = "ragflow-6gBYDi-FMuZ7zY7sqdDfG-IkSNCILhbDurLJ0qQ5k54"
OLD_RAGFLOW = "bf1312d28b3d11f1847f73b364e50e19"
KB10 = "/Users/FYP/Documents/@西北人的成长/20-Areas/信息安全/数据安全/10_知识库工程"
DOC_EXPECT = {"jg24": 116, "jg93": 140, "pboc3": 56, "jf8": 32}
FAILS = []
RESULTS = []


def check(name: str, ok: bool, detail: str = ""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} — {detail}")
    if not ok:
        FAILS.append(name)


def pg():
    return psycopg2.connect(DSN, connect_timeout=8)


def fuseki_query(sparql: str, auth=False):
    body = sparql.encode()
    hdrs = {"Accept": "application/sparql-results+json",
            "Content-Type": "application/sparql-query"}
    if auth:
        import base64
        hdrs["Authorization"] = "Basic " + base64.b64encode(b"admin:admin").decode()
    req = urllib.request.Request(FUSEKI + "/query", data=body, method="POST", headers=hdrs)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())["results"]["bindings"]


# ---------------------------------------------------------------- 1. 检查项三源
def check_checks():
    json_ids, pg_ids, sq_ids = {}, set(), set()
    for dk, n in DOC_EXPECT.items():
        data = json.load(open(os.path.join(BASE, "data/checks", f"{dk}-checks.json")))
        items = data.get("checks") or data.get("items") or next(iter(data.values()))
        json_ids[dk] = {it["id"] for it in items}

    conn = pg()
    with conn.cursor() as cur:
        cur.execute("SELECT check_code FROM inspection_check")
        pg_ids = {r[0] for r in cur.fetchall()}
    conn.close()

    sq = sqlite3.connect(os.path.join(BASE, "app/data/app.db"))
    for r in sq.execute(
            "SELECT dataJSON FROM entities WHERE type='InspectionCheck' AND status='published'"):
        d = json.loads(r[0])
        sq_ids.add(d.get("checkCode"))
    sq.close()

    for dk, n in DOC_EXPECT.items():
        j = json_ids[dk]
        # PG/SQLite 不按文号分，用全局集合 + 前缀核对
        if dk == "jg24":
            pg_dk = {c for c in pg_ids if not c.startswith(("93-", "pb3-", "jf8-"))}
            sq_dk = {c for c in sq_ids if not c.startswith(("93-", "pb3-", "jf8-"))}
        elif dk == "jg93":
            pg_dk = {c for c in pg_ids if c.startswith("93-")}
            sq_dk = {c for c in sq_ids if c.startswith("93-")}
        elif dk == "pboc3":
            pg_dk = {c for c in pg_ids if c.startswith("pb3-")}
            sq_dk = {c for c in sq_ids if c.startswith("pb3-")}
        else:
            pg_dk = {c for c in pg_ids if c.startswith("jf8-")}
            sq_dk = {c for c in sq_ids if c.startswith("jf8-")}

        check(f"检查项 {dk} 数量={n}", len(j) == n and len(pg_dk) == n and len(sq_dk) == n,
              f"json={len(j)} pg={len(pg_dk)} sqlite={len(sq_dk)}")
        miss_jp = j - pg_dk
        miss_js = j - sq_dk
        check(f"检查项 {dk} 编号三源一致", not miss_jp and not miss_js,
              f"json-pg差={sorted(miss_jp)[:5]} json-sqlite差={sorted(miss_js)[:5]}")


# ---------------------------------------------------------------- 2. 六维覆盖
def check_sixdim():
    conn = pg()
    with conn.cursor() as cur:
        for dk, n in DOC_EXPECT.items():
            if dk == "jg24":
                cond = "doc_key='jg24'"
            else:
                cond = f"doc_key='{dk}'"
            cur.execute(f"""SELECT COUNT(DISTINCT check_code) FROM check_six_dim
                            WHERE {cond} AND check_code IN
                            (SELECT check_code FROM check_six_dim WHERE {cond} AND dimension='method')
                            AND check_code IN
                            (SELECT check_code FROM check_six_dim WHERE {cond} AND dimension='verdict')""")
            got = cur.fetchone()[0]
            check(f"六维 {dk} 覆盖 method+verdict={n}", got == n, f"covered={got}/{n}")
    conn.close()


# ---------------------------------------------------------------- 3. 实体/关系 PG↔Fuseki 双向
def check_graph():
    conn = pg()
    pg_ents, pg_rels = set(), set()
    with conn.cursor() as cur:
        cur.execute("SELECT uri FROM kb_entity")
        pg_ents = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT subject_uri,predicate,object_uri FROM kb_relation")
        pg_rels = {(s, REL_BASE + p, o) for s, p, o in cur.fetchall()}
    conn.close()

    g_ents, g_rels = set(), set()
    for b in fuseki_query(
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
            f"SELECT DISTINCT ?s WHERE {{ GRAPH <{PLATFORM_GRAPH}> {{ ?s rdfs:label ?l }} }}"):
        g_ents.add(b["s"]["value"])
    for b in fuseki_query(
            f"SELECT ?s ?p ?o WHERE {{ GRAPH <{PLATFORM_GRAPH}> {{ ?s ?p ?o . "
            f"FILTER(STRSTARTS(STR(?p),\"{REL_BASE}\")) }} }}"):
        g_rels.add((b["s"]["value"], b["p"]["value"], b["o"]["value"]))

    check("实体 PG→图全覆盖", pg_ents <= g_ents,
          f"pg={len(pg_ents)} graph={len(g_ents)} 缺={len(pg_ents - g_ents)}")
    check("实体 图→PG 无多余", g_ents <= pg_ents,
          f"graph={len(g_ents)} pg={len(pg_ents)} 多余={len(g_ents - pg_ents)}")
    check("关系 PG→图全覆盖", pg_rels <= g_rels,
          f"pg={len(pg_rels)} graph={len(g_rels)} 缺={len(pg_rels - g_rels)}")
    check("关系 图→PG 无多余", g_rels <= pg_rels,
          f"graph={len(g_rels)} pg={len(pg_rels)} 多余={len(g_rels - pg_rels)}")


# ---------------------------------------------------------------- 4. 嵌入
def check_embeddings():
    conn = pg()
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), count(embedding) FROM kb_embedding")
        t, e = cur.fetchone()
        check("kb_embedding 344 全有向量", t == 344 and e == 344, f"rows={t} embedded={e}")
        cur.execute("SELECT count(*), count(embedding) FROM law_chunk")
        t, e = cur.fetchone()
        check("law_chunk 344 全嵌入", t == 344 and e == 344, f"rows={t} embedded={e}")
        cur.execute("SELECT doc_key,count(*) FROM law_chunk GROUP BY doc_key ORDER BY doc_key")
        by = dict(cur.fetchall())
        check("law_chunk 分文号=116/140/56/32",
              by.get("jg24") == 116 and by.get("jg93") == 140
              and by.get("pboc3") == 56 and by.get("jf8") == 32, str(by))
    conn.close()


# ---------------------------------------------------------------- 5. 10工程实体覆盖
def check_kb10():
    g = json.load(open(os.path.join(KB10, "data/graph.json")))
    ids = {n["id"] for n in g["nodes"]}
    conn = pg()
    with conn.cursor() as cur:
        cur.execute("SELECT slug FROM kb_entity WHERE slug IS NOT NULL")
        pg_slug = {r[0] for r in cur.fetchall()}
    conn.close()
    missing = ids - pg_slug
    check("10工程 498 实体被 kb_entity 全覆盖", not missing and len(ids) == 498,
          f"nodes={len(ids)} missing={len(missing)}")


# ---------------------------------------------------------------- 6. RAGFlow 旧库只读
def check_ragflow():
    req = urllib.request.Request(RAGFLOW + "/api/v1/datasets?page=1&page_size=20",
                                 headers={"Authorization": "Bearer " + RAG_TOKEN})
    data = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
    old = next((x for x in data["data"] if x["id"] == OLD_RAGFLOW), None)
    ok = old and old["document_count"] == 6 and old["chunk_count"] == 35
    check("RAGFlow 既有库只读快照 6docs/35chunks", bool(ok),
          f"docs={old and old['document_count']} chunks={old and old['chunk_count']}")


# ---------------------------------------------------------------- 7. EKOS 不变量
def check_invariants():
    expect = {"check_element": 470, "control": 115, "law_clause": 57,
              "doc93_selfcheck_item": 139, "doc93_report_entry": 0}
    conn = pg()
    with conn.cursor() as cur:
        for tbl, n in expect.items():
            cur.execute(f"SELECT count(*) FROM {tbl}")
            got = cur.fetchone()[0]
            check(f"EKOS 不变量 {tbl}={n}", got == n, f"got={got}")
    conn.close()
    # Fuseki 默认图不降
    b = fuseki_query("SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }")
    n = int(b[0]["n"]["value"])
    check("Fuseki 默认图 19,927 不降", n == 19927, f"default={n}")


# ---------------------------------------------------------------- 8. 后端权威
def check_backend():
    try:
        req = urllib.request.Request("http://127.0.0.1:8420/api/graph/backend")
        d = json.loads(urllib.request.urlopen(req, timeout=8).read().decode())
        check("图后端权威=fuseki", d.get("backend") == "fuseki",
              f"backend={d.get('backend')} triples={d.get('stats', {}).get('triples')}")
    except Exception as e:  # noqa: BLE001
        check("图后端权威=fuseki", False, f"不可达: {e}")


def main():
    if "--fix" in sys.argv:
        print("（--fix 预留：本期只读校验，无自动修复动作）")
    check_checks()
    check_sixdim()
    check_graph()
    check_embeddings()
    check_kb10()
    check_ragflow()
    check_invariants()
    check_backend()
    total = len(RESULTS)
    print(f"\n合计 {total} 项，PASS {total - len(FAILS)}，FAIL {len(FAILS)}")
    if FAILS:
        print("FAILED:", FAILS)
        sys.exit(1)
    print("P2 一致性全绿")


if __name__ == "__main__":
    main()
