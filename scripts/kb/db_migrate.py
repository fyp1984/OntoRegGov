#!/usr/bin/env python3
"""PostgreSQL 投影库迁移脚本（docs/09 §2 ER + §3 迁移策略）。

大白话：把"知识库里的表结构"做成版本化脚本——每改一次表结构留一个可回滚的版本；
跑一遍登记在案，重跑不重复生效（幂等）；库是 canonical.ttl 的派生只读投影，
表结构改错了就 down 回滚，数据坏了整批重建即可（知识不丢）。

用法（连接串取自 app/config.py 的 KB_PG_DSN，可用环境变量 KB_PG_DSN 覆盖）：
    python scripts/kb/db_migrate.py up                 # 跑所有未执行的迁移（默认）
    python scripts/kb/db_migrate.py status            # 查看台账 + 待跑迁移
    python scripts/kb/db_migrate.py rollback 1         # 回滚最近 1 个迁移（执行其 down）
    python scripts/kb/db_migrate.py rollback-to 1      # 回滚到指定版本（保留该版本及以下）

设计要点（docs/09 §3.1）：
  - schema_migrations 台账：version/name/checksum/applied_at；
  - 每迁移一个事务：BEGIN…COMMIT，失败即 ROLLBACK，不留半成品表；
  - 幂等：建表一律 IF NOT EXISTS，已登记版本跳过；字节级重跑结果一致；
  - down 回滚：每个迁移配 down SQL，rollback 时按版本逆序执行。
"""
from __future__ import annotations
import argparse
import hashlib
import sys
from pathlib import Path

# 允许从项目根直接跑：python scripts/kb/db_migrate.py
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402

from app.config import KB_PG_DSN  # noqa: E402

# ---------------------------------------------------------------------------
# 迁移清单：顺序即版本号（从 1 递增）。每项 = (name, up_sql, down_sql)。
# 新增迁移只追加，不改老迁移的 up（历史已生效，改了也不会重跑）。
# ---------------------------------------------------------------------------

M0001_UP = r"""
-- 台账表（迁移版本登记）
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  checksum    TEXT NOT NULL,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 1. 知识对象总表：所有法规/标准/术语/控制/方案/专题/检查/要素/法条都有一行
CREATE TABLE IF NOT EXISTS kb_entity (
  uri           TEXT PRIMARY KEY,           -- canonical 地址（复印件对回原件的门牌号）
  entity_type   TEXT NOT NULL,              -- Term/Control/Law/Solution/Guide/Topic/InspectionCheck/CheckElement/Clause
  slug          TEXT,                       -- URI 末段（/api/entity/{id} 用它）
  label         TEXT,
  title         TEXT,
  summary       TEXT,
  status        TEXT,
  ct_code       TEXT,                       -- 控制 CT 码（CT-EP-001…）
  check_code    TEXT,                       -- 检查编号（1.1 / 93-3.1）
  element_code  TEXT,                       -- 要素编号（1.1.1）
  domain        TEXT,
  priority      TEXT,
  layer         TEXT,
  source_path   TEXT,                       -- 10 工程编辑源文件
  content_hash  TEXT,                       -- 编译 md5
  data_json     JSONB,                      -- 长尾属性（alias/tag/evidenceExample/lifecycle…）
  loaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kb_entity_type  ON kb_entity(entity_type);
CREATE INDEX IF NOT EXISTS idx_kb_entity_ct    ON kb_entity(ct_code);
CREATE INDEX IF NOT EXISTS idx_kb_entity_check  ON kb_entity(check_code);
CREATE INDEX IF NOT EXISTS idx_kb_entity_slug  ON kb_entity(slug);

-- 2. 关系边表：知识图谱的"连线"
CREATE TABLE IF NOT EXISTS kb_relation (
  id            BIGSERIAL PRIMARY KEY,
  subject_uri   TEXT NOT NULL REFERENCES kb_entity(uri),
  predicate     TEXT NOT NULL,              -- citesClause/suggestsControl/hasElement/mentions…
  object_uri    TEXT NOT NULL REFERENCES kb_entity(uri),
  subject_type  TEXT,
  object_type   TEXT,
  UNIQUE (subject_uri, predicate, object_uri)
);
CREATE INDEX IF NOT EXISTS idx_rel_pred      ON kb_relation(predicate);
CREATE INDEX IF NOT EXISTS idx_rel_subject    ON kb_relation(subject_uri);
CREATE INDEX IF NOT EXISTS idx_rel_object     ON kb_relation(object_uri);

-- 3. 控制措施特化表（CT 码体系，control-codes.csv 104 行）
CREATE TABLE IF NOT EXISTS control (
  ct_code       TEXT PRIMARY KEY,           -- CT-EP-001…
  entity_uri    TEXT NOT NULL UNIQUE REFERENCES kb_entity(uri),
  title         TEXT,
  layer         TEXT,                       -- endpoint/network/service/protocol/management
  control_type  TEXT,                       -- protect/detect/identify/govern/respond/recover
  family        TEXT
);

-- 4. 监管检查项主表（金规24号 116 + 93号文 13）
CREATE TABLE IF NOT EXISTS inspection_check (
  check_code        TEXT PRIMARY KEY,       -- 1.1 / 93-3.1
  entity_uri        TEXT NOT NULL UNIQUE REFERENCES kb_entity(uri),
  title             TEXT,
  domain            TEXT,
  domain_label      TEXT,
  priority          TEXT,
  regulation        TEXT,                   -- §10
  article_no        TEXT,                   -- 第十条
  article_text      TEXT,
  institution_level TEXT                    -- L1 总纲…
);

-- 5. 检查要素表（检查员照着打的逐条小问）
CREATE TABLE IF NOT EXISTS check_element (
  element_code  TEXT PRIMARY KEY,           -- 1.1.1
  entity_uri    TEXT NOT NULL UNIQUE REFERENCES kb_entity(uri),
  check_code    TEXT REFERENCES inspection_check(check_code),
  text          TEXT,
  focus_levels  JSONB,                      -- ["L1","L2","L3"]
  criteria      TEXT
);
CREATE INDEX IF NOT EXISTS idx_el_check ON check_element(check_code);

-- 6. 法条 Clause 表
CREATE TABLE IF NOT EXISTS law_clause (
  clause_id   TEXT PRIMARY KEY,             -- cl-11 / cl-93-att1
  law_uri     TEXT REFERENCES kb_entity(uri),
  article_no  TEXT,
  text        TEXT
);

-- 7. 93号文报送表模板表（139 项稳定知识；独立表以便 GROUP BY 六大类）
CREATE TABLE IF NOT EXISTS doc93_selfcheck_item (
  item_seq            TEXT PRIMARY KEY,       -- 校准后问题序号 1.1…13.6
  category            TEXT,                   -- 六大类名（数据安全治理…）
  category_no         INTEGER,                -- 1..6
  problem_type        TEXT,                   -- 问题类型名（数据安全责任…）
  problem_type_no     INTEGER,                -- 1..22
  problem_text        TEXT,                   -- 主要问题环节原文
  is_supervision_version BOOLEAN NOT NULL DEFAULT FALSE,  -- 是否140监管版
  normalized_seq      TEXT,                   -- 全局连续编号 001..139
  topic_uri           TEXT,                   -- 93号文 topic
  data_json           JSONB
);

-- 8. 93号文填报实例表（每机构每批次填报；本期空表，随填报增长）
CREATE TABLE IF NOT EXISTS doc93_report_entry (
  id            BIGSERIAL PRIMARY KEY,
  item_seq      TEXT REFERENCES doc93_selfcheck_item(item_seq),
  org_name      TEXT,
  batch         TEXT,                       -- 报送批次/节点
  filled_json   JSONB,                      -- 问题个数/已整改/待整改/措施/计划完成时间
  submitted_at  TIMESTAMPTZ
);
"""

M0001_DOWN = r"""
-- 逆序 DROP（先子表后主表，避开外键）。不动 schema_migrations 台账表——
-- 台账行由迁移 runner 在 down 之后删除（_ensure_ledger 下次 up 时 IF NOT EXISTS 自愈）。
DROP TABLE IF EXISTS doc93_report_entry;
DROP TABLE IF EXISTS doc93_selfcheck_item;
DROP TABLE IF EXISTS law_clause;
DROP TABLE IF EXISTS check_element;
DROP TABLE IF EXISTS inspection_check;
DROP TABLE IF EXISTS control;
DROP TABLE IF EXISTS kb_relation;
DROP TABLE IF EXISTS kb_entity;
"""

M0002_UP = r"""
-- 检查方法·富层 5 表（jg24 金规24号检查法：度量 / 方法步骤 / 访谈 / 判定 / 常见问题）。
-- 全部由 data/checks/jg24-checks.json 投影而来，外键挂 inspection_check(check_code)。
-- （对应 app/ontology/checks_import.py 的 Metric/InspectionMethodStep/InterviewQuestion/
--   VerdictRule/FindingPattern 实体形状，保持字段语义一致。）

-- 9. 度量表（检查方法·量化指标 method.metrics）
CREATE TABLE IF NOT EXISTS check_metric (
  metric_id    TEXT PRIMARY KEY,            -- ic-1-1-m1
  check_code   TEXT NOT NULL REFERENCES inspection_check(check_code) ON DELETE CASCADE,
  seq          INTEGER NOT NULL,
  name         TEXT,
  data_source  TEXT,                        -- 数据来源台账
  threshold    TEXT                         -- 判定阈值
);
CREATE INDEX IF NOT EXISTS idx_check_metric_check ON check_metric(check_code);

-- 10. 检查方法步骤表（查制度 policy / 查证据 evidence，method.policy_steps + evidence_steps）
CREATE TABLE IF NOT EXISTS check_method_step (
  step_id     TEXT PRIMARY KEY,             -- ic-1-1-msp1 / ic-1-1-mse1
  check_code  TEXT NOT NULL REFERENCES inspection_check(check_code) ON DELETE CASCADE,
  step_kind   TEXT NOT NULL,                -- policy | evidence
  seq         INTEGER NOT NULL,
  step_no     TEXT,
  action      TEXT,                         -- 调阅/取证动作
  focus       TEXT                          -- 关注点 / 取证标准
);
CREATE INDEX IF NOT EXISTS idx_check_step_check ON check_method_step(check_code);

-- 11. 访谈问题表（method.interviews）
CREATE TABLE IF NOT EXISTS check_interview (
  interview_id TEXT PRIMARY KEY,            -- ic-1-1-i1
  check_code   TEXT NOT NULL REFERENCES inspection_check(check_code) ON DELETE CASCADE,
  seq          INTEGER NOT NULL,
  target       TEXT,                        -- 访谈对象
  question     TEXT,
  cross_check  TEXT                         -- 交叉验证方式
);
CREATE INDEX IF NOT EXISTS idx_check_interview_check ON check_interview(check_code);

-- 12. 判定规则表（三档判定要点 verdict）
CREATE TABLE IF NOT EXISTS check_verdict_rule (
  check_code      TEXT PRIMARY KEY REFERENCES inspection_check(check_code) ON DELETE CASCADE,
  verdict_pass    JSONB,                    -- ["…通过情形…"]
  verdict_partial JSONB,                    -- ["…部分符合…"]
  verdict_fail    JSONB                     -- ["…不通过…"]
);

-- 13. 常见问题模式表（findings）
CREATE TABLE IF NOT EXISTS check_finding_pattern (
  finding_id   TEXT PRIMARY KEY,            -- ic-1-1-fp1
  check_code   TEXT NOT NULL REFERENCES inspection_check(check_code) ON DELETE CASCADE,
  seq          INTEGER NOT NULL,
  rank         TEXT,
  problem      TEXT,
  root_cause   TEXT,
  remediation  TEXT
);
CREATE INDEX IF NOT EXISTS idx_check_finding_check ON check_finding_pattern(check_code);
"""

M0002_DOWN = r"""
-- 逆序 DROP（子表先删）。inspection_check 由 M0001 管，不在此动。
DROP TABLE IF EXISTS check_finding_pattern;
DROP TABLE IF EXISTS check_verdict_rule;
DROP TABLE IF EXISTS check_interview;
DROP TABLE IF EXISTS check_method_step;
DROP TABLE IF EXISTS check_metric;
"""

# (version, name, up, down)
MIGRATIONS: list[tuple[int, str, str, str]] = [
    (1, "init_core_9tables", M0001_UP, M0001_DOWN),
    (2, "add_check_rich_layer_5tables", M0002_UP, M0002_DOWN),
]


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16]


def _connect():
    return psycopg2.connect(KB_PG_DSN)


def _ensure_ledger(conn):
    """schema_migrations 可能尚未创建（首次 up 前）；用裸连接建。"""
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY, name TEXT NOT NULL,"
            " checksum TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
    conn.commit()


def _applied_versions(conn) -> dict[int, dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version")
        return {r["version"]: dict(r) for r in cur.fetchall()}


def cmd_up(conn) -> int:
    applied = _applied_versions(conn)
    ran = 0
    for version, name, up, _down in MIGRATIONS:
        if version in applied:
            continue
        # 每迁移一个事务
        try:
            with conn.cursor() as cur:
                cur.execute(up)
                cur.execute(
                    "INSERT INTO schema_migrations(version,name,checksum) VALUES(%s,%s,%s)",
                    (version, name, _checksum(up)),
                )
            conn.commit()
            print(f"[up]   {version:>4} {name}  applied")
            ran += 1
        except Exception as e:
            conn.rollback()
            print(f"[up]   {version:>4} {name}  FAILED -> rollback: {e}", file=sys.stderr)
            return 1
    if ran == 0:
        print("[up]   nothing to do (all migrations already applied)")
    return 0


def cmd_status(conn) -> int:
    applied = _applied_versions(conn)
    print("=== schema_migrations 台账 ===")
    if not applied:
        print("  (empty — no migration applied yet)")
    for v, r in applied.items():
        print(f"  v{v:<4} {r['name']:<24} checksum={r['checksum']} at={r['applied_at']}")
    pending = [(v, n) for v, n, _, _ in MIGRATIONS if v not in applied]
    print("=== 待跑迁移 ===")
    if not pending:
        print("  (none)")
    for v, n in pending:
        print(f"  v{v:<4} {n}")
    return 0


def cmd_rollback(conn, count: int | None, to_version: int | None) -> int:
    applied = _applied_versions(conn)
    if not applied:
        print("[rollback] ledger empty, nothing to roll back")
        return 0
    # 决定要回滚哪些版本
    applied_sorted = sorted(applied, reverse=True)
    if to_version is not None:
        targets = [v for v in applied_sorted if v > to_version]
        if not targets:
            print(f"[rollback-to] current max={max(applied)}; nothing above v{to_version}")
            return 0
    else:
        count = count or 1
        targets = applied_sorted[:count]
    down_map = {v: (n, d) for v, n, _u, d in MIGRATIONS}
    for v in targets:
        name, down = down_map.get(v, (f"v{v}", ""))
        try:
            with conn.cursor() as cur:
                cur.execute(down)
                cur.execute("DELETE FROM schema_migrations WHERE version=%s", (v,))
            conn.commit()
            print(f"[down] {v:>4} {name}  rolled back")
        except Exception as e:
            conn.rollback()
            print(f"[down] {v:>4} {name}  FAILED -> rollback: {e}", file=sys.stderr)
            return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="OntoRegGov PostgreSQL 投影库迁移")
    ap.add_argument("command", nargs="?", default="up",
                    choices=["up", "status", "rollback", "rollback-to"])
    ap.add_argument("arg", nargs="?", type=int, default=None,
                    help="rollback 的个数，或 rollback-to 的目标版本")
    args = ap.parse_args()

    print(f"[migrate] DSN={KB_PG_DSN}")
    try:
        conn = _connect()
    except Exception as e:
        print(f"[migrate] 无法连接 PostgreSQL：{e}", file=sys.stderr)
        print("[migrate] 请先启动本地 PG（pg_ctl start），或检查 KB_PG_DSN。", file=sys.stderr)
        return 2

    try:
        _ensure_ledger(conn)
        if args.command == "up":
            return cmd_up(conn)
        if args.command == "status":
            return cmd_status(conn)
        if args.command == "rollback":
            return cmd_rollback(conn, count=args.arg, to_version=None)
        if args.command == "rollback-to":
            return cmd_rollback(conn, count=None, to_version=args.arg)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
