#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.8 工作包 C 冒烟（进程内 TestClient，不起 uvicorn / 不起浏览器）。

覆盖：
  ① DB_READ_FROM 三态（json/canonical/db）四路由 200 + 结构一致 + controls=115；
  ② 网关认证：无 token / 坏 token 401，白名单 token 200 且落审计；
  ③ 限流件单测（RateLimiter）；
  ④ MCP 工具进程内调用（dsec_check_detail 三态读源）。

运行前置：先跑 scripts/demo/demo_e2e.py 与 scripts/demo/demo_checks.py（SQLite 已种 116 检查）。
退出码 0=全绿。
"""
from __future__ import annotations
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name} {extra}")
    if not cond:
        FAILS.append(name)


def reset_state():
    """清掉模块级缓存，避免跨用例串味。"""
    from app.services import canonical_kb, db_kb
    canonical_kb.reload_cache()
    db_kb._health_cache = None
    db_kb._health_ts = 0.0


def test_three_states(client):
    import app.config as cfg
    for mode in ("json", "canonical", "db"):
        cfg.DB_READ_FROM = mode
        reset_state()
        degraded = "（库不可达→回落 canonical）" if mode == "db" else ""
        print(f"--- DB_READ_FROM={mode} {degraded} ---")
        r = client.get("/api/health")
        check(f"{mode}: /api/health 200", r.status_code == 200)
        r = client.get("/api/entity/control-abac")
        check(f"{mode}: /api/entity/control-abac 200", r.status_code == 200,
              f"(type={r.json().get('type') if r.status_code==200 else r.text[:60]})")
        if r.status_code == 200:
            b = r.json()
            check(f"{mode}: entity 结构字段齐",
                  all(k in b for k in ("id", "type", "title", "relations")))
        r = client.get("/api/search?q=%E5%85%9A%E5%A7%94")  # 党委
        check(f"{mode}: /api/search 200", r.status_code == 200,
              f"(total={r.json().get('total') if r.status_code==200 else '?'})")
        r = client.get("/api/controls")
        check(f"{mode}: /api/controls 200", r.status_code == 200)
        if r.status_code == 200:
            check(f"{mode}: controls=115（与 canonical 对账一致）",
                  r.json().get("total") == 115, f"(total={r.json().get('total')})")
        r = client.get("/api/checks/1.1")
        check(f"{mode}: /api/checks/1.1 200", r.status_code == 200,
              f"(title={str(r.json().get('title'))[:30] if r.status_code==200 else r.text[:60]})")
        if r.status_code == 200:
            b = r.json()
            # v1.15.1 回归守卫：三态下检查详情必须返回完整六维，不得被图/库精简形状短路，
            # 否则前端「检查清单/检查方法/三档判定/常见问题/建议控制」会 undefined / 空白。
            check(f"{mode}: 检查详情六维完整（未被图/库精简形状短路）",
                  all(k in b for k in ("elements", "methodSteps", "metrics", "interviews",
                                       "verdict", "findings", "related", "suggestedControls")),
                  f"(keys={sorted(b.keys())})")
            check(f"{mode}: 要素含 code（前端表格首列非 undefined）",
                  bool(b.get("elements")) and "code" in (b["elements"][0] or {}))
        if mode == "db":
            check(f"db 态：PG 未就绪时自动降级未中断", r.status_code == 200)
        # 兜底守卫：仅存本体的检查（93号文 93-3.4）→ 回落图/库轨道精简形状
        if mode in ("canonical", "db"):
            r = client.get("/api/checks/93-3.4")
            check(f"{mode}: 仅存本体的检查 93-3.4 回落图/库轨道",
                  r.status_code == 200 and r.json().get("source") in ("db", "canonical"),
                  f"({r.status_code}, source={r.json().get('source') if r.status_code==200 else '-'})")
    cfg.DB_READ_FROM = "json"
    reset_state()


def test_gateway(client):
    import app.config as cfg
    from app.db import db
    print("--- 网关认证（GATEWAY_AUTH_ENABLED=on）---")
    cfg.GATEWAY_AUTH_ENABLED = True
    try:
        from app.db import db
        with db() as conn:
            n0 = conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]

        r = client.get("/api/controls")
        check("无 token → 401", r.status_code == 401, f"({r.status_code})")
        r = client.get("/api/controls", headers={"Authorization": "Bearer wrong-key"})
        check("坏 token → 401", r.status_code == 401, f"({r.status_code})")
        r = client.get("/api/health")
        check("/api/health 免鉴权", r.status_code == 200)
        r = client.get("/api/controls", headers={"Authorization": "Bearer dsec-demo-2026"})
        check("allowlist 内 token → 200", r.status_code == 200, f"({r.status_code})")
        with db() as conn:
            n1 = conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
            row = conn.execute(
                "SELECT actor, action, target FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        check("网关请求落审计 audit_log（行数+1）", n1 == n0 + 1, f"({n0}→{n1})")
        check("审计条目 actor/action/target 正确",
              row is not None and "演示" in str(row["actor"])
              and row["action"] == "api.get" and row["target"] == "/api/controls",
              f"({dict(row) if row else None})")
    finally:
        cfg.GATEWAY_AUTH_ENABLED = False
    r = client.get("/api/controls")
    check("开关复位 off → /api/controls 裸跑 200", r.status_code == 200)


def test_sparql_acl(client):
    print("--- SPARQL 只读 ACL（线④：图存储禁写）---")
    r = client.post("/api/graph/sparql", json={"query": "INSERT DATA { <a> <b> <c> }"})
    check("REST /api/graph/sparql INSERT → 400 拒绝", r.status_code == 400, f"({r.status_code})")
    r = client.post("/api/graph/sparql", json={"query": "DROP GRAPH <http://dsec/platform>"})
    check("REST /api/graph/sparql DROP → 400 拒绝", r.status_code == 400, f"({r.status_code})")
    r = client.post("/api/graph/sparql", json={"query": "SELECT ?s WHERE { ?s ?p ?o } LIMIT 1"})
    check("REST /api/graph/sparql SELECT → 200 放行", r.status_code == 200, f"({r.status_code})")
    from app.mcp_server.server import make_server
    fn = make_server()._tool_manager._tools["dsec_graph_sparql"].fn
    r = fn("CLEAR ALL")
    check("MCP dsec_graph_sparql CLEAR → error 拒绝", "error" in r, f"({r})")
    r = fn("SELECT ?s WHERE { ?s ?p ?o } LIMIT 1")
    check("MCP dsec_graph_sparql SELECT → rows 放行",
          "rows" in r or "ask" in r, f"(keys={sorted(r.keys())})")


def test_rate_limiter():
    print("--- 限流件单测（复用 mcp_server.auth.RateLimiter）---")
    from app.mcp_server.auth import RateLimiter
    lim = RateLimiter(window_sec=60)
    check("rpm=2 前两次放行", lim.allow("k-test", 2) and lim.allow("k-test", 2))
    check("rpm=2 第三次拒绝（429 语义）", not lim.allow("k-test", 2))
    check("rpm=0 不限流", lim.allow("k-unlimited", 0))


def test_mcp_tools():
    print("--- MCP 工具进程内调用（dsec_check_detail 六维 + 图/库兜底）---")
    from app.mcp_server.server import make_server
    import app.config as cfg
    mcp = make_server()
    fn = mcp._tool_manager._tools["dsec_check_detail"].fn
    for mode in ("json", "canonical", "db"):
        cfg.DB_READ_FROM = mode
        reset_state()
        r = fn("1.1")
        # v1.15.1 回归守卫：三态下 MCP 必须返回完整六维，不得被图/库精简形状短路。
        check(f"{mode} 态：MCP dsec_check_detail(1.1) 返回六维（未被短路）",
              r.get("checkCode") == "1.1"
              and all(k in r for k in ("elements", "suggestedControls"))
              and "code" in ((r.get("elements") or [{}])[0] or {}),
              f"(keys={sorted(r.keys())[:6]})")
    # 兜底：仅存本体的检查（93号文 93-3.4）→ 回落 kb_read（db→canonical）精简形状
    for mode in ("canonical", "db"):
        cfg.DB_READ_FROM = mode
        reset_state()
        r = fn("93-3.4")
        check(f"{mode} 态：MCP 回落图/库轨道（93-3.4）",
              r.get("checkCode") == "93-3.4" and r.get("source") in ("db", "canonical"),
              f"(source={r.get('source')})")
    cfg.DB_READ_FROM = "json"
    reset_state()


def test_search_always_fused(client):
    """v1.15.2 回归守卫：/api/search 关键词命中时不得提前返回，必须继续融合。

    monkeypatch db_kb.search / db_kb.fused_search 返回互不相交命中，断言两条都在结果里。
    """
    print("--- /api/search 始终融合（v1.15.2：关键词命中不跳过融合）---")
    import app.config as cfg
    from app.services import db_kb
    orig_search, orig_fused, orig_mode = db_kb.search, db_kb.fused_search, cfg.DB_READ_FROM
    try:
        cfg.DB_READ_FROM = "db"
        db_kb.search = lambda q, limit=20: {
            "query": q, "total": 1,
            "results": [{"id": "kw-1", "type": "Term", "label": "关键词命中", "checkCode": ""}]}
        db_kb.fused_search = lambda q, limit=20: {
            "query": q, "total": 1,
            "results": [{"id": "vec-1", "type": "weknora_chunk", "label": "向量命中",
                         "route": "weknora_vector"}],
            "routes": ["keyword", "vector", "graph", "rag", "weknora"]}
        r = client.get("/api/search?q=__fusion_probe__")
        ids = {x.get("id") for x in (r.json().get("results") or [])}
        check("/api/search 关键词命中时仍合并融合结果（不提前返回）",
              r.status_code == 200 and {"kw-1", "vec-1"} <= ids, f"(ids={sorted(ids)})")
    finally:
        db_kb.search, db_kb.fused_search, cfg.DB_READ_FROM = orig_search, orig_fused, orig_mode


def main():
    from app.main import app
    with TestClient(app) as client:
        test_three_states(client)
        test_gateway(client)
        test_sparql_acl(client)
        test_search_always_fused(client)
    test_rate_limiter()
    test_mcp_tools()
    print("=" * 60)
    if FAILS:
        print(f"[smoke_v18_gateway] 失败 {len(FAILS)} 项: {FAILS}")
        sys.exit(1)
    print("[smoke_v18_gateway] 全部断言通过 ✅")
    sys.exit(0)


if __name__ == "__main__":
    main()
