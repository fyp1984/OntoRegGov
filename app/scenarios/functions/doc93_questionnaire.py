"""函数适配器：93号文自查问卷装载（只读 PG 投影 doc93_selfcheck_item）。

大白话：93号文（银保数据安全专项整治自查表）共 139 个细项，落在 PG 投影表
doc93_selfcheck_item。本适配器把它按"6大类 category → 22小类 problem_type"两级分组，
供被监管方逐项勾选"是否存在问题"并统计。与 app/services/db_kb.py 同风格：
只读、懒加载、连接超时 3s；库不可达时返回结构化错误（{ok:false, error}）而非抛崩。

run(params) 入参：无必需。可传 supervisionOnly=true 只看监管版（is_supervision_version）。
"""
from __future__ import annotations

import time
from typing import Any

from ...config import KB_PG_DSN

_HEALTH_TTL = 30.0
_health_cache: bool | None = None
_health_ts = 0.0


def _dsn_candidates() -> list[str]:
    """容器内 127.0.0.1 指向容器自身，回退 host.docker.internal 访问宿主 PG。"""
    cands = [KB_PG_DSN]
    import os
    if os.path.exists("/.dockerenv") and "127.0.0.1" in KB_PG_DSN:
        cands.append(KB_PG_DSN.replace("127.0.0.1", "host.docker.internal"))
    return cands


def _connect():
    import psycopg2  # 可选依赖；未装/连不上 → 上层降级
    last = None
    for dsn in _dsn_candidates():
        try:
            conn = psycopg2.connect(dsn, connect_timeout=3)
            conn.set_session(readonly=True, autocommit=True)
            return conn
        except Exception as e:  # noqa: BLE001 — 试下一个候选
            last = e
    raise last


def health(force: bool = False) -> bool:
    global _health_cache, _health_ts
    now = time.time()
    if not force and _health_cache is not None and (now - _health_ts) < _HEALTH_TTL:
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


def run(params: dict | None = None) -> dict:
    params = params or {}
    if not health():
        return {
            "ok": False,
            "error": {"code": "pg_unreachable",
                      "message": "PostgreSQL 投影不可达（doc93_selfcheck_item），93号文问卷暂不可用"},
            "total": 0, "groups": [],
        }
    import psycopg2.extras
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            sql = """
                SELECT item_seq, category, category_no, problem_type, problem_type_no,
                       problem_text, is_supervision_version, normalized_seq, topic_uri
                FROM doc93_selfcheck_item
                ORDER BY category_no, problem_type_no, item_seq
            """
            cur.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:  # noqa: BLE001 — 查询异常 → 结构化错误，不崩
        return {
            "ok": False,
            "error": {"code": "pg_query_failed", "message": f"93号文问卷查询失败: {e}"},
            "total": 0, "groups": [],
        }
    finally:
        conn.close()

    sup_only = bool(params.get("supervisionOnly"))
    if sup_only:
        rows = [r for r in rows if r.get("is_supervision_version")]

    # 两级分组：category → problem_type → items
    cat_map: dict[str, dict[str, Any]] = {}
    for r in rows:
        cat = r.get("category") or "未分类"
        pt = r.get("problem_type") or "未分类"
        cat_node = cat_map.setdefault(cat, {
            "category": cat, "categoryNo": r.get("category_no"),
            "problemTypes": {}, "count": 0, "supervisionCount": 0,
        })
        pt_node = cat_node["problemTypes"].setdefault(pt, {"problemType": pt, "problemTypeNo": r.get("problem_type_no"), "items": []})
        pt_node["items"].append({
            "itemSeq": r.get("item_seq"),
            "problemText": r.get("problem_text"),
            "isSupervisionVersion": bool(r.get("is_supervision_version")),
            "normalizedSeq": r.get("normalized_seq"),
            "topicUri": r.get("topic_uri"),
        })
        cat_node["count"] += 1
        if r.get("is_supervision_version"):
            cat_node["supervisionCount"] += 1

    groups = sorted(cat_map.values(), key=lambda c: (c.get("categoryNo") or 0))
    total_pt = sum(len(c["problemTypes"]) for c in groups)
    return {
        "ok": True,
        "source": "pg:doc93_selfcheck_item",
        "total": len(rows),
        "categoryCount": len(groups),
        "problemTypeCount": total_pt,
        "supervisionVersionTotal": sum(c["supervisionCount"] for c in groups),
        "fields": {"groupBy": ["category", "problem_type"],
                   "itemFields": ["itemSeq", "problemText", "isSupervisionVersion", "normalizedSeq", "topicUri"]},
        "groups": groups,
    }
