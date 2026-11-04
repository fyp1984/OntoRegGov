"""运行态统一数据库（v1.16.0，PRD §6.2 / D1）。

大白话：知识态归知识库平台（只读），运行态（自查运行/结果/证据/签署/计划/提案/队列/审计）
归平台自己写。本模块把运行态的"权威落点"从进程内 SQLite 收敛到 PostgreSQL 独立库
（`dsec_run`），与资产投影库 `ekos_ds_kb` 物理分离、互不污染（红线 3）。

迁移策略（非破坏式，对齐 PRD R5「一次性迁移 + 影子比对门禁」）：
  - 现有 SQLite 写路径**保持权威**，行为零变更；
  - 每次运行态写操作**影子镜像**到 PG（best-effort，失败只记不抛，绝不影响主流程）；
  - 启动时 `ensure_schema()` 幂等建表，`backfill_from_sqlite()` 幂等回填历史数据；
  - `compare()` 提供 SQLite↔PG 影子比对，作为切换读路径前的门禁。

表结构严格对齐 PRD §6.2 的 9 张目标表命名（plan/run/result/evidence/signoff/
knowledge_proposal/review_task/kb_snapshot_cache/audit_log）。
"""
from __future__ import annotations

import json
import os
import urllib.parse

from ..config import KB_PG_DSN

# 运行态独立库名（PRD §4.4：复用既有 PG 实例、独立 database）
RUN_DB_NAME = os.environ.get("RUN_PG_DB", "dsec_run")
_MAINT_DB = os.environ.get("RUN_PG_MAINT_DB", "postgres")

_health_cache: bool | None = None
_health_ts: float = 0.0
_HEALTH_TTL_SEC = 30.0


def _dsn() -> str:
    """运行态库 DSN：显式 RUN_PG_DSN 优先，否则由 KB_PG_DSN 换库名派生。"""
    explicit = os.environ.get("RUN_PG_DSN", "")
    if explicit:
        return explicit
    p = urllib.parse.urlsplit(KB_PG_DSN)
    return urllib.parse.urlunsplit((p.scheme, p.netloc, "/" + RUN_DB_NAME, p.query, p.fragment))


def _maint_dsn() -> str:
    """维护库 DSN（用于 CREATE DATABASE）：同主机，库名换成 postgres。"""
    p = urllib.parse.urlsplit(_dsn())
    return urllib.parse.urlunsplit((p.scheme, p.netloc, "/" + _MAINT_DB, p.query, p.fragment))


def _candidates(dsn: str) -> list[str]:
    """容器内（/.dockerenv）把 127.0.0.1 改写为 host.docker.internal（与 db_kb 同范式）。"""
    if "127.0.0.1" in dsn and os.path.exists("/.dockerenv"):
        return [dsn.replace("127.0.0.1", "host.docker.internal"), dsn]
    return [dsn]


def _connect(dsn: str):
    """建立可写连接（尝试 DSN 候选）；失败抛给调用方。"""
    import psycopg2
    last: Exception | None = None
    for cand in _candidates(dsn):
        try:
            conn = psycopg2.connect(cand, connect_timeout=3)
            conn.autocommit = True
            return conn
        except Exception as e:  # noqa: BLE001
            last = e
    raise last if last else RuntimeError("no runtime DSN candidate")


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS inspection_plan(
  plan_id text PRIMARY KEY, name text, scope text, cycle text, owner text,
  check_scope jsonb, status text, start_date text, end_date text,
  created_at text, updated_at text);
CREATE TABLE IF NOT EXISTS inspection_run(
  run_id text PRIMARY KEY, plan_id text, inspected_target text, inspector text,
  assignees jsonb, ran_at text, data jsonb, updated_at text);
CREATE TABLE IF NOT EXISTS check_result(
  result_id text PRIMARY KEY, run_id text, check_code text, elements_json jsonb,
  metrics_json jsonb, result text, why_json jsonb, created_at text);
CREATE TABLE IF NOT EXISTS inspection_evidence(
  evidence_id text PRIMARY KEY, run_id text, check_code text, file_name text,
  file_path text, uploaded_by text, note text, uploaded_at text);
CREATE TABLE IF NOT EXISTS inspection_signoff(
  signoff_id text PRIMARY KEY, run_id text, signer text, role text, decision text,
  comment text, signed_at text);
CREATE TABLE IF NOT EXISTS knowledge_proposal(
  proposal_id text PRIMARY KEY, reason text, target_kind text, raised_from text,
  status text, payload jsonb, reviewer text, decided_at text, created_at text);
CREATE TABLE IF NOT EXISTS review_task(
  task_id text PRIMARY KEY, target_type text, target_id text, status text,
  reviewer text, note text, created_by text, created_at text, decided_at text);
CREATE TABLE IF NOT EXISTS kb_snapshot_cache(
  cache_key text PRIMARY KEY, content_hash text, payload jsonb,
  fetched_at text, ttl integer);
CREATE TABLE IF NOT EXISTS audit_log(
  id bigserial PRIMARY KEY, ts text, actor text, action text, target text, params jsonb);
"""

# 逻辑表名 → 主键列（upsert 用）
_PK = {
    "inspection_plan": "plan_id", "inspection_run": "run_id", "check_result": "result_id",
    "inspection_evidence": "evidence_id", "inspection_signoff": "signoff_id",
    "knowledge_proposal": "proposal_id", "review_task": "task_id",
    "kb_snapshot_cache": "cache_key",
}
_JSON_COLS = {"check_scope", "assignees", "data", "elements_json", "metrics_json",
              "why_json", "payload", "params"}


def ensure_database() -> bool:
    """确保 dsec_run 独立库存在（不存在则创建）。返回是否可用。"""
    try:
        conn = _connect(_maint_dsn())
    except Exception:  # noqa: BLE001
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (RUN_DB_NAME,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{RUN_DB_NAME}"')
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        conn.close()


def ensure_schema() -> bool:
    """幂等建表；库不存在先建库。返回 schema 是否就绪。"""
    if not ensure_database():
        return False
    try:
        conn = _connect(_dsn())
    except Exception:  # noqa: BLE001
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        conn.close()


def health(force: bool = False) -> bool:
    """运行态库是否可用（30s 缓存）。"""
    global _health_cache, _health_ts
    import time
    now = time.time()
    if not force and _health_cache is not None and (now - _health_ts) < _HEALTH_TTL_SEC:
        return _health_cache
    ok = False
    try:
        conn = _connect(_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            ok = True
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        ok = False
    _health_cache, _health_ts = ok, now
    return ok


def upsert(table: str, row: dict) -> bool:
    """按主键 upsert 一行；任何失败返回 False（best-effort，绝不抛给调用方）。"""
    pk = _PK.get(table)
    if not pk or not row.get(pk):
        return False
    cols = [k for k in row.keys()]
    vals = []
    for c in cols:
        v = row[c]
        if c in _JSON_COLS and not isinstance(v, str):
            v = json.dumps(v, ensure_ascii=False)
        elif isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        vals.append(v)
    placeholders = ", ".join("%s" for _ in cols)
    colnames = ", ".join(f'"{c}"' for c in cols)
    updates = ", ".join(f'"{c}"=EXCLUDED."{c}"' for c in cols if c != pk)
    sql = (f'INSERT INTO {table}({colnames}) VALUES({placeholders}) '
           f'ON CONFLICT ("{pk}") DO UPDATE SET {updates}')
    try:
        conn = _connect(_dsn())
    except Exception:  # noqa: BLE001
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(sql, vals)
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        conn.close()


def insert_audit(ts: str, actor: str, action: str, target: str = "",
                 params: dict | None = None) -> bool:
    """审计留痕（自增主键，无 upsert 语义）。"""
    try:
        conn = _connect(_dsn())
    except Exception:  # noqa: BLE001
        return False
    try:
        with conn.cursor() as cur:
            cur.execute('INSERT INTO audit_log(ts,actor,action,target,params) '
                        'VALUES(%s,%s,%s,%s,%s::jsonb)',
                        (ts, actor, action, target,
                         json.dumps(params or {}, ensure_ascii=False)))
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        conn.close()


def counts() -> dict:
    """各运行态表当前行数（用于影子比对与健康看板）。"""
    out: dict[str, int] = {}
    try:
        conn = _connect(_dsn())
    except Exception:  # noqa: BLE001
        return out
    try:
        with conn.cursor() as cur:
            for t in list(_PK.keys()) + ["audit_log"]:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {t}")
                    out[t] = int(cur.fetchone()[0])
                except Exception:  # noqa: BLE001
                    out[t] = -1
    finally:
        conn.close()
    return out


# ===========================================================================
# 影子镜像：SQLite 权威写 → PG 副本（服务层各写点调用，一行接入）
# ===========================================================================
def mirror_plan(row: dict) -> bool:
    return upsert("inspection_plan", row)


def mirror_run(row: dict) -> bool:
    return upsert("inspection_run", row)


def mirror_result(row: dict) -> bool:
    return upsert("check_result", row)


def mirror_evidence(row: dict) -> bool:
    return upsert("inspection_evidence", row)


def mirror_signoff(row: dict) -> bool:
    return upsert("inspection_signoff", row)


def mirror_proposal(row: dict) -> bool:
    return upsert("knowledge_proposal", row)


def mirror_review_task(row: dict) -> bool:
    return upsert("review_task", row)


# ===========================================================================
# 回填 + 影子比对（启动幂等；切换读路径前门禁）
# ===========================================================================
def backfill_from_sqlite() -> dict:
    """把 SQLite 运行台账幂等回填到 PG 运行库（重复调用安全）。"""
    if not health(force=True):
        return {"ok": False, "reason": "runtime db unreachable"}
    from ..db import db as _db        # 延迟导入避免循环
    n: dict[str, int] = {}

    def _bump(k: str):
        n[k] = n.get(k, 0) + 1

    with _db() as conn:
        for r in conn.execute("SELECT * FROM inspection_plans").fetchall():
            d = dict(r)
            if mirror_plan({"plan_id": d["id"], "name": d.get("name"),
                            "scope": d.get("scope"), "cycle": d.get("cycle"),
                            "owner": d.get("owner"),
                            "check_scope": d.get("checkScopeJSON") or "[]",
                            "status": d.get("status"), "start_date": d.get("startDate") or "",
                            "end_date": d.get("endDate") or "",
                            "created_at": d.get("createdAt") or "",
                            "updated_at": d.get("updatedAt") or ""}):
                _bump("inspection_plan")
        for r in conn.execute("SELECT id,dataJSON FROM entities WHERE type='InspectionRun'").fetchall():
            d = json.loads(r["dataJSON"])
            if mirror_run({"run_id": r["id"], "plan_id": d.get("planId"),
                           "inspected_target": d.get("inspectedTarget"),
                           "inspector": d.get("inspector"),
                           "assignees": (d.get("assignees") or "").split(",") if d.get("assignees") else [],
                           "ran_at": d.get("ranAt"), "data": d, "updated_at": d.get("ranAt") or ""}):
                _bump("inspection_run")
        for r in conn.execute("SELECT id,dataJSON FROM entities WHERE type='CheckResult'").fetchall():
            d = json.loads(r["dataJSON"])
            run_ref = d.get("resultRun") or ""
            if mirror_result({"result_id": r["id"], "run_id": run_ref.split(":", 1)[-1],
                              "check_code": (json.loads(d.get("why") or "{}") or {}).get("checkCode"),
                              "elements_json": d.get("elementVerdict"),
                              "metrics_json": d.get("metricActual"),
                              "result": d.get("result"), "why_json": d.get("why"),
                              "created_at": ""}):
                _bump("check_result")
        for r in conn.execute("SELECT * FROM inspection_evidence").fetchall():
            d = dict(r)
            if mirror_evidence({"evidence_id": d["id"], "run_id": d.get("runId"),
                                "check_code": d.get("checkCode"), "file_name": d.get("fileName"),
                                "file_path": d.get("filePath"), "uploaded_by": d.get("uploadedBy"),
                                "note": d.get("note"), "uploaded_at": d.get("uploadedAt") or ""}):
                _bump("inspection_evidence")
        for r in conn.execute("SELECT * FROM inspection_signoffs").fetchall():
            d = dict(r)
            if mirror_signoff({"signoff_id": d["id"], "run_id": d.get("runId"),
                               "signer": d.get("signer"), "role": d.get("role"),
                               "decision": d.get("decision"), "comment": d.get("comment"),
                               "signed_at": d.get("signedAt") or ""}):
                _bump("inspection_signoff")
        for r in conn.execute("SELECT * FROM proposals").fetchall():
            d = dict(r)
            if mirror_proposal({"proposal_id": d["id"], "reason": d.get("reason"),
                                "target_kind": d.get("targetKind"), "raised_from": d.get("raisedFrom"),
                                "status": d.get("status"), "payload": d.get("payloadJSON") or "{}",
                                "reviewer": d.get("reviewer"), "decided_at": d.get("decidedAt") or "",
                                "created_at": d.get("createdAt") or ""}):
                _bump("knowledge_proposal")
        for r in conn.execute("SELECT * FROM review_tasks").fetchall():
            d = dict(r)
            if mirror_review_task({"task_id": d["id"], "target_type": d.get("targetType"),
                                   "target_id": d.get("targetId"), "status": d.get("status"),
                                   "reviewer": d.get("reviewer"), "note": d.get("note"),
                                   "created_by": d.get("createdBy"),
                                   "created_at": d.get("createdAt") or "",
                                   "decided_at": d.get("decidedAt") or ""}):
                _bump("review_task")
    return {"ok": True, "mirrored": n,
            "pgCounts": {k: v for k, v in counts().items()
                         if k in n or k == "audit_log"}}


def compare() -> dict:
    """SQLite↔PG 影子比对（门禁：切换读路径前要求各表计数一致）。"""
    from ..db import db as _db
    with _db() as conn:
        sqlite_n = {
            "inspection_plan": conn.execute("SELECT COUNT(*) n FROM inspection_plans").fetchone()["n"],
            "inspection_run": conn.execute("SELECT COUNT(*) n FROM entities WHERE type='InspectionRun'").fetchone()["n"],
            "check_result": conn.execute("SELECT COUNT(*) n FROM entities WHERE type='CheckResult'").fetchone()["n"],
            "inspection_evidence": conn.execute("SELECT COUNT(*) n FROM inspection_evidence").fetchone()["n"],
            "inspection_signoff": conn.execute("SELECT COUNT(*) n FROM inspection_signoffs").fetchone()["n"],
            "knowledge_proposal": conn.execute("SELECT COUNT(*) n FROM proposals").fetchone()["n"],
            "review_task": conn.execute("SELECT COUNT(*) n FROM review_tasks").fetchone()["n"],
        }
    pg_n = counts()
    rows, ok = [], True
    for k, v in sqlite_n.items():
        pv = pg_n.get(k, -1)
        same = pv >= v  # PG 允许≥（多轮写入的副本不删）
        ok = ok and same
        rows.append({"table": k, "sqlite": v, "pg": pv, "consistent": same})
    return {"consistent": ok, "rows": rows}
