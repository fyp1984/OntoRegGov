#!/usr/bin/env python3
"""P3：wren 台账语义层 + 自然语言查询（真实 wren v3 执行，只读）。

说明（如实）：
- wren-mcp/wren-mcp-b 为 MCP 包装，/v2 规划需 WREN_ENGINE_ENDPOINT（冻结未配，500）；
  /v3/connector/postgres/query 经 ibis 直连 PG 可真实执行（已实测）。
- wren 提供 MDL 语义层（model/relationship/metric）+ SQL 执行；本环境无 LLM key，
  NL 意图由规则路由翻译成 SQL（rule-based NL router），再交 wren 规划执行，不伪造 LLM。
- 数据源只读接入 ekos_ds_kb，不改 wren 容器配置、不重启。

用法：
  .venv/bin/python scripts/p3_wren_nl.py                 # 跑内置问答集
  .venv/bin/python scripts/p3_wren_nl.py "你的问题"       # 单问
"""
import base64
import json
import sys
import urllib.error
import urllib.request

WREN = "http://127.0.0.1:18000/v3/connector/postgres/query"
CONN = {"host": "host.docker.internal", "port": "15432",
        "database": "ekos_ds_kb", "user": "test", "password": "test"}

# ---------------- MDL 语义层（wren manifest，base64） ----------------
MDL = {
    "catalog": "ekos_ds_kb", "schema": "public",
    "models": [
        {"name": "inspection_check",
         "tableReference": {"schema": "public", "table": "inspection_check"},
         "primaryKey": "check_code",
         "columns": [
             {"name": "check_code", "type": "varchar"},
             {"name": "title", "type": "varchar"},
             {"name": "domain", "type": "varchar"},
             {"name": "priority", "type": "varchar"},
             {"name": "article_no", "type": "varchar"},
             {"name": "regulation", "type": "varchar"}]},
        {"name": "p1_sixdim_review",
         "tableReference": {"schema": "public", "table": "p1_sixdim_review"},
         "primaryKey": "draft_id",
         "columns": [
             {"name": "draft_id", "type": "varchar"},
             {"name": "check_code", "type": "varchar"},
             {"name": "doc_key", "type": "varchar"},
             {"name": "dimension", "type": "varchar"},
             {"name": "status", "type": "varchar"},
             {"name": "reviewer", "type": "varchar"},
             {"name": "merged", "type": "boolean"},
             {"name": "provenance", "type": "varchar"}]},
        {"name": "check_six_dim",
         "tableReference": {"schema": "public", "table": "check_six_dim"},
         "primaryKey": "check_code",
         "columns": [
             {"name": "check_code", "type": "varchar"},
             {"name": "doc_key", "type": "varchar"},
             {"name": "dimension", "type": "varchar"},
             {"name": "seq", "type": "integer"},
             {"name": "title", "type": "varchar"}]},
    ],
    # 注：本环境 wren v3 对 relationship/metric 的扩展字段校验严格（缺 baseObject），
    # 语义层以 model 表定义为准；关系/度量在连通完整引擎后补全。
}


def wren_sql(sql: str) -> dict:
    manifest = base64.b64encode(json.dumps(MDL).encode()).decode()
    body = json.dumps({"manifestStr": manifest, "sql": sql,
                       "connectionInfo": CONN}).encode()
    req = urllib.request.Request(WREN, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


# ---------------- 规则 NL 路由：意图 → SQL ----------------
DOC_CASE = ("CASE WHEN check_code LIKE '93-%' THEN 'jg93' "
            "WHEN check_code LIKE 'pb3-%' THEN 'pboc3' "
            "WHEN check_code LIKE 'jf8-%' THEN 'jf8' ELSE 'jg24' END")


def route(nl: str):
    s = nl.lower()
    if "六维" in nl and ("维度" in nl or "行数" in nl):
        return ("SELECT doc_key, dimension, COUNT(*) AS n FROM check_six_dim "
                "GROUP BY doc_key, dimension ORDER BY doc_key, dimension")
    if "已通过" in nl or "approved" in s or "审核台账共" in nl:
        return ("SELECT status, COUNT(*) AS n, BOOL_AND(merged) AS merged "
                "FROM p1_sixdim_review GROUP BY status")
    if "合并" in nl or "落库" in nl:
        return ("SELECT COUNT(*) AS n FROM p1_sixdim_review WHERE merged = true")
    if "jg93" in s or "93号" in nl:
        return ("SELECT COUNT(*) AS n FROM inspection_check "
                "WHERE check_code LIKE '93-%'")
    if "pboc3" in s or "人民银行" in nl or "3号" in nl:
        return ("SELECT COUNT(*) AS n FROM inspection_check "
                "WHERE check_code LIKE 'pb3-%'")
    if "jf8" in s or "人工智能" in nl:
        return ("SELECT COUNT(*) AS n FROM inspection_check "
                "WHERE check_code LIKE 'jf8-%'")
    if "分布" in nl or "各文号" in nl or ("文号" in nl and "多少" in nl):
        return (f"SELECT {DOC_CASE} AS doc, COUNT(*) AS n "
                "FROM inspection_check GROUP BY 1 ORDER BY 1")
    return "SELECT COUNT(*) AS n FROM inspection_check"


QUESTIONS = [
    "各文号检查项数量分布是多少？",
    "六维审核台账共多少条已通过？是否都已合并落库？",
    "jg93 检查项有多少条？",
    "pboc3 人民银行3号文检查项有多少条？",
    "jf8 人工智能治理检查项有多少条？",
    "六维知识各文号各维度行数分布？",
    "审核台账中已合并落库多少条？",
]


def ask(nl: str):
    sql = route(nl)
    print(f"\n问：{nl}")
    print(f"→ SQL（规则路由，wren 执行）：\n  {sql}")
    res = wren_sql(sql)
    cols = res.get("columns", [])
    print(f"← wren 结果（{res.get('dtypes', {})}）：")
    for row in res.get("data", []):
        print("   ", dict(zip(cols, row)))
    return res


def main():
    if len(sys.argv) > 1:
        ask(" ".join(sys.argv[1:]))
        return
    for q in QUESTIONS:
        try:
            ask(q)
        except urllib.error.HTTPError as e:
            print("WREN HTTP", e.code, e.read().decode()[:300])
        except Exception as e:  # noqa: BLE001
            print("ERR", e)


if __name__ == "__main__":
    main()
