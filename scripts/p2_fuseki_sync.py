#!/usr/bin/env python3
"""P2：把 PG ekos_ds_kb.kb_entity / kb_relation 增量、幂等写入 Fuseki 平台命名图。

硬约束：
- 只向命名图 <http://dsec/platform> **增**三元组（FILTER NOT EXISTS 防重）；
- 绝不 CLEAR / 改写 EKOS 默认图（既有 19,927 三元组写入前后计数必须不变）；
- 不改 Fuseki 容器配置、不重启。

用法：
  .venv/bin/python scripts/p2_fuseki_sync.py            # dry-run，只对账不写
  .venv/bin/python scripts/p2_fuseki_sync.py --apply    # 真实增量写入
"""
import base64
import json
import sys
import urllib.request

import psycopg2

DSN = "postgresql://test:test@127.0.0.1:15432/ekos_ds_kb"
FUSEKI = "http://127.0.0.1:3030/ds"
# Fuseki /update 需 admin Basic（shiro /*/update/**=authcBasic,user[admin]；/query 匿名只读）
FUSEKI_USER = "admin"
FUSEKI_PASSWORD = "admin"
PLATFORM_GRAPH = "http://dsec/platform"
PNS = "http://dsec.local/platform/"
REL_BASE = PNS + "rel#"
BASELINE_DEFAULT = 19927          # P2 启动时 EKOS 默认图三元组基线（只读验证不降）
BATCH = 150


def sparql_post(kind: str, query: str, accept="application/sparql-results+json"):
    url = f"{FUSEKI}/{kind}"
    hdrs = {"Content-Type": "application/sparql-update" if kind == "update"
            else "application/sparql-query", "Accept": accept}
    if kind == "update":
        tok = base64.b64encode(f"{FUSEKI_USER}:{FUSEKI_PASSWORD}".encode()).decode()
        hdrs["Authorization"] = f"Basic {tok}"
    req = urllib.request.Request(url, data=query.encode("utf-8"),
                                 method="POST", headers=hdrs)
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    if kind == "query" and body:
        return json.loads(body.decode())
    return {}


def count_default() -> int:
    q = "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"
    b = sparql_post("query", q)
    return int(b["results"]["bindings"][0]["n"]["value"])


def count_graph(g: str) -> int:
    q = (f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{g}> {{ ?s ?p ?o }} }}")
    b = sparql_post("query", q)
    return int(b["results"]["bindings"][0]["n"]["value"])


def esc_lit(s) -> str:
    if s is None:
        return '""'
    s = str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
    return f'"{s}"'


def esc_iri(u: str) -> str:
    # 本工程实体 URI 均为 https://schema.cheersai.local/...，已合法；防御性转义空格
    return "<" + u.replace(">", "\\>") + ">"


def build_triples(conn) -> list:
    rows = []
    with conn.cursor() as cur:
        cur.execute("""SELECT uri,entity_type,slug,label,title,summary,domain,priority,status
                       FROM kb_entity ORDER BY uri""")
        for uri, etype, slug, label, title, summary, domain, priority, status in cur.fetchall():
            subj = esc_iri(uri)
            rows.append((subj, f"<{PNS}entityType>", esc_lit(etype), "lit"))
            rows.append((subj, "<http://www.w3.org/2000/01/rdf-schema#label>",
                         esc_lit(label or title or slug), "lit"))
            if slug:
                rows.append((subj, f"<{PNS}slug>", esc_lit(slug), "lit"))
            if title:
                rows.append((subj, f"<{PNS}title>", esc_lit(title), "lit"))
            if summary:
                rows.append((subj, f"<{PNS}summary>", esc_lit(summary), "lit"))
            if domain:
                rows.append((subj, f"<{PNS}domain>", esc_lit(domain), "lit"))
            if priority:
                rows.append((subj, f"<{PNS}priority>", esc_lit(priority), "lit"))
        cur.execute("""SELECT subject_uri,predicate,object_uri FROM kb_relation
                       ORDER BY subject_uri,predicate,object_uri""")
        for s, pred, o in cur.fetchall():
            rows.append((esc_iri(s), f"<{REL_BASE}{pred}>", esc_iri(o), "iri"))
    return rows


def apply(rows: list, dry: bool) -> dict:
    inserted = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        vals = []
        for s, p, o, kind in chunk:
            obj = o if kind == "iri" else o  # literal already quoted
            vals.append(f"({s} {p} {obj})")
        update = (
            f"PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            f"INSERT {{ GRAPH <{PLATFORM_GRAPH}> {{ ?s ?p ?o }} }} "
            f"WHERE {{ VALUES (?s ?p ?o) {{ {' '.join(vals)} }} "
            f"FILTER NOT EXISTS {{ GRAPH <{PLATFORM_GRAPH}> {{ ?s ?p ?o }} }} }}"
        )
        if dry:
            inserted += len(chunk)
            continue
        sparql_post("update", update, accept="*/*")
        inserted += len(chunk)
    return {"triples_planned": len(rows), "batches": (len(rows) + BATCH - 1) // BATCH,
            "processed": inserted}


def main():
    dry = "--apply" not in sys.argv
    conn = psycopg2.connect(DSN, connect_timeout=5)
    try:
        rows = build_triples(conn)
    finally:
        conn.close()

    before_default = count_default()
    before_platform = count_graph(PLATFORM_GRAPH)
    print(f"[baseline] EKOS 默认图={before_default}（基线 {BASELINE_DEFAULT}） "
          f"平台命名图已有={before_platform}")
    res = apply(rows, dry)
    print(f"[{'dry-run' if dry else 'applied'}] 三元组计划={res['triples_planned']} "
          f"批次={res['batches']} 处理={res['processed']}")

    after_default = count_default()
    after_platform = count_graph(PLATFORM_GRAPH)
    print(f"[after] EKOS 默认图={after_default} 平台命名图={after_platform}")

    if after_default != BASELINE_DEFAULT:
        print(f"FAIL: 默认图三元组变化 {BASELINE_DEFAULT} -> {after_default}")
        sys.exit(1)
    print("PASS: EKOS 默认图 19,927 未变（只增平台命名图）")


if __name__ == "__main__":
    main()
