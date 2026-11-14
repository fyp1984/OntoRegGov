"""演示库（SQLite）：连接、建表与通用读写工具。

大白话：这是"全量功能 Demo"自己的笔记本（app/data/demo.db），与现有平台的
app.db 完全隔离——绝不改动现有库与现有接口。所有演示数据都落在这里，随时可重置。

设计要点：
- WAL + busy_timeout，范式与 app/db.py 一致（sqlite3.Row 行工厂）。
- 全部建表 CREATE TABLE IF NOT EXISTS，可反复执行。
- 通用 q/x/insert 工具 + demo_state 键值表（记录 seeded_version / 当前账号等）。
"""
from __future__ import annotations

import hashlib
import json
import datetime
import sqlite3
from contextlib import contextmanager

from ..config import APP_DATA

DEMO_DB = APP_DATA / "demo.db"

# ---- §3 数据模型：约 30 张表（JSON 字段一律以 TEXT 存字符串）----
SCHEMA = r"""
-- 组织与人员
CREATE TABLE IF NOT EXISTS org_node(
  node_id TEXT PRIMARY KEY, parent_id TEXT, level TEXT, name TEXT, kind TEXT,
  line_code TEXT, industry TEXT, sort INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS org_position(
  position_id TEXT PRIMARY KEY, org_node_id TEXT, name TEXT, status TEXT DEFAULT 'active');

CREATE TABLE IF NOT EXISTS user_account(
  account TEXT PRIMARY KEY, display_name TEXT, idp_subject TEXT, idp_type TEXT,
  org_node_id TEXT, position_id TEXT, email TEXT, status TEXT DEFAULT 'active',
  last_login_at TEXT, is_bootstrap INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS role_def(
  role_id TEXT PRIMARY KEY, name TEXT, capabilities_json TEXT, scope_json TEXT,
  level_visibility TEXT, status TEXT DEFAULT 'active', builtin INTEGER DEFAULT 0,
  updated_by TEXT, updated_at TEXT);

CREATE TABLE IF NOT EXISTS role_binding(
  binding_id TEXT PRIMARY KEY, account TEXT, role_id TEXT, org_node_id TEXT, position_id TEXT);

-- 行业档案与文号
CREATE TABLE IF NOT EXISTS industry_profile(
  profile_id TEXT PRIMARY KEY, industry TEXT, name TEXT, org_types_json TEXT,
  lines_json TEXT, sensitive_types_json TEXT, doc_focus_json TEXT, report_template TEXT);

CREATE TABLE IF NOT EXISTS doc_registry(
  doc_key TEXT PRIMARY KEY, doc_no TEXT, title TEXT, issuing_body TEXT, effective_date TEXT,
  structure_profile_json TEXT, status TEXT, check_count INTEGER DEFAULT 0,
  registered_by TEXT, registered_at TEXT);

-- 自查主链
CREATE TABLE IF NOT EXISTS inspection_plan(
  plan_id TEXT PRIMARY KEY, name TEXT, industry TEXT, scope_json TEXT,
  checklist_version TEXT, status TEXT, created_by TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS selfcheck_task(
  task_id TEXT PRIMARY KEY, plan_id TEXT, industry TEXT, org_name TEXT, org_type TEXT,
  org_node_id TEXT, cycle TEXT, owner TEXT, assignees_json TEXT, scope_json TEXT,
  stage TEXT, topic TEXT, status TEXT, progress INTEGER, risk_level TEXT,
  start_date TEXT, end_date TEXT, created_by TEXT, created_at TEXT, updated_at TEXT);

CREATE TABLE IF NOT EXISTS selfcheck_section(
  section_id TEXT PRIMARY KEY, task_id TEXT, line_code TEXT, line_label TEXT,
  owner TEXT, due_date TEXT, status TEXT, progress INTEGER);

CREATE TABLE IF NOT EXISTS selfcheck_item_state(
  state_id TEXT PRIMARY KEY, task_id TEXT, check_code TEXT, line_code TEXT,
  applicability TEXT, status TEXT, owner TEXT, has_policy INTEGER DEFAULT 0,
  evidence_json TEXT, actual_value TEXT, note TEXT, updated_at TEXT);

CREATE TABLE IF NOT EXISTS inspection_run(
  run_id TEXT PRIMARY KEY, plan_id TEXT, task_id TEXT, run_type TEXT, inspected_target TEXT,
  inspector TEXT, assignees_json TEXT, ran_at TEXT, submitter_account TEXT);

CREATE TABLE IF NOT EXISTS check_result(
  result_id TEXT PRIMARY KEY, run_id TEXT, check_code TEXT, elements_json TEXT,
  metrics_json TEXT, result TEXT, judge_source TEXT, confidence REAL, why_json TEXT);

CREATE TABLE IF NOT EXISTS inspection_evidence(
  evidence_id TEXT PRIMARY KEY, run_id TEXT, task_id TEXT, check_code TEXT,
  file_name TEXT, storage_ref TEXT, file_hash TEXT, size INTEGER,
  uploaded_by TEXT, uploaded_at TEXT);

CREATE TABLE IF NOT EXISTS inspection_signoff(
  signoff_id TEXT PRIMARY KEY, run_id TEXT, task_id TEXT, signer TEXT, signer_name TEXT,
  role TEXT, decision TEXT, comment TEXT, signed_at TEXT);

CREATE TABLE IF NOT EXISTS selfcheck_finding(
  finding_id TEXT PRIMARY KEY, task_id TEXT, check_code TEXT, severity TEXT, problem TEXT,
  root_cause TEXT, status TEXT, owner TEXT, due_date TEXT, created_at TEXT, source_run_id TEXT);

CREATE TABLE IF NOT EXISTS remediation_task(
  remediation_id TEXT PRIMARY KEY, finding_id TEXT, task_id TEXT, owner TEXT, due_date TEXT,
  measures TEXT, status TEXT, evidence_ref TEXT, created_at TEXT, updated_at TEXT);

-- 责任分配
CREATE TABLE IF NOT EXISTS check_assignment_rule(
  rule_id TEXT PRIMARY KEY, check_code TEXT, industry TEXT, org_scope_json TEXT,
  stage TEXT, topic TEXT, target_dept_id TEXT, target_position_id TEXT,
  target_role_id TEXT, version INTEGER DEFAULT 1, status TEXT DEFAULT 'active');

CREATE TABLE IF NOT EXISTS assignment_batch(
  batch_id TEXT PRIMARY KEY, task_id TEXT, rule_version INTEGER, scope_json TEXT,
  mapping_snapshot_json TEXT, unmatched_json TEXT, conflicts_json TEXT,
  coverage REAL, confirmed_by TEXT, confirmed_at TEXT);

CREATE TABLE IF NOT EXISTS check_assignment_override(
  override_id TEXT PRIMARY KEY, batch_id TEXT, check_code TEXT, target_dept_id TEXT,
  target_position_id TEXT, target_role_id TEXT, reason TEXT, changed_by TEXT, changed_at TEXT);

-- 知识治理 / 回流 / 审核
CREATE TABLE IF NOT EXISTS hitl_candidate(
  candidate_id TEXT PRIMARY KEY, source_type TEXT, source_id TEXT, check_code TEXT,
  title TEXT, confidence REAL, status TEXT, assigned_reviewer TEXT, payload_json TEXT,
  created_at TEXT, decided_at TEXT);

CREATE TABLE IF NOT EXISTS knowledge_proposal(
  proposal_id TEXT PRIMARY KEY, category TEXT, title TEXT, payload_json TEXT,
  raised_from TEXT, status TEXT, raised_by TEXT, reviewed_by TEXT,
  review_comment TEXT, created_at TEXT, decided_at TEXT);

CREATE TABLE IF NOT EXISTS review_task(
  task_id TEXT PRIMARY KEY, target_type TEXT, target_id TEXT, status TEXT,
  reviewer TEXT, created_at TEXT, decided_at TEXT);

CREATE TABLE IF NOT EXISTS kb_publish_manifest(
  doc_id TEXT PRIMARY KEY, doc_key TEXT, title TEXT, content_hash TEXT, artifact_path TEXT,
  pipeline_fingerprint TEXT, status TEXT, built_at TEXT);

CREATE TABLE IF NOT EXISTS kb_publish_run(
  run_id TEXT PRIMARY KEY, trigger TEXT, mode TEXT, started_at TEXT, finished_at TEXT,
  status TEXT, version_dir TEXT, changed_docs INTEGER, total_docs INTEGER,
  duration_ms INTEGER, error TEXT, operator TEXT);

-- 审计（只追加 哈希链）
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, actor_name TEXT, action TEXT,
  target TEXT, params_json TEXT, result TEXT, prev_hash TEXT, hash TEXT);

-- 场景与插件
CREATE TABLE IF NOT EXISTS scenario_pack(
  pack_id TEXT PRIMARY KEY, name TEXT, industry TEXT, status TEXT, scope_json TEXT,
  mapping_json TEXT, form_json TEXT, report_template TEXT, builtin INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS plugin_registry(
  plugin_id TEXT PRIMARY KEY, name TEXT, capability TEXT, io_schema_json TEXT,
  auth_type TEXT, rate_limit TEXT, status TEXT, vendor TEXT, latency_ms INTEGER);

CREATE TABLE IF NOT EXISTS plugin_invocation(
  invocation_id TEXT PRIMARY KEY, plugin_id TEXT, task_id TEXT, input_ref TEXT,
  output_ref TEXT, status TEXT, latency_ms INTEGER, actor TEXT, created_at TEXT);

-- 采集与分类映射
CREATE TABLE IF NOT EXISTS collect_task(
  collect_id TEXT PRIMARY KEY, title TEXT, source_url TEXT, issuing_body TEXT,
  content_type TEXT, publish_date TEXT, collected_at TEXT, status TEXT,
  credibility REAL, proposal_id TEXT);

CREATE TABLE IF NOT EXISTS kb_category_mapping(
  mapping_id TEXT PRIMARY KEY, type_prefix TEXT, category TEXT, sort INTEGER DEFAULT 0);

-- 第八轮：8 个扩展视图功能化（可写作业表）
-- 口径：每张表承载一个"作业流程"的输入与状态，写操作一律校验 + 审计留痕。
CREATE TABLE IF NOT EXISTS frame_chain_case(
  case_id TEXT PRIMARY KEY, title TEXT, issue_no TEXT, status TEXT DEFAULT 'in_progress',
  current_ring INTEGER DEFAULT 1, owner TEXT, created_by TEXT, created_at TEXT, updated_at TEXT);

CREATE TABLE IF NOT EXISTS frame_ring_record(
  record_id TEXT PRIMARY KEY, case_id TEXT, ring_no INTEGER, ring_name TEXT,
  output TEXT, evidence TEXT, operator TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS diag_assessment(
  assessment_id TEXT PRIMARY KEY, title TEXT, status TEXT DEFAULT 'draft', owner TEXT,
  created_by TEXT, created_at TEXT, updated_at TEXT, submitted_at TEXT);

CREATE TABLE IF NOT EXISTS diag_answer(
  answer_id TEXT PRIMARY KEY, assessment_id TEXT, dim_no INTEGER, dim_name TEXT,
  q TEXT, state TEXT, note TEXT, evidence TEXT, updated_at TEXT);

CREATE TABLE IF NOT EXISTS ledger_row(
  row_id TEXT PRIMARY KEY, scene TEXT, level TEXT, should TEXT, actual TEXT,
  result TEXT, owner TEXT, created_by TEXT, created_at TEXT, updated_at TEXT);

CREATE TABLE IF NOT EXISTS issue_disposal(
  disposal_id TEXT PRIMARY KEY, issue_no TEXT, issue_name TEXT, layer TEXT,
  status TEXT DEFAULT 'open', org_name TEXT, position TEXT, plan TEXT, evidence TEXT,
  owner TEXT, created_by TEXT, created_at TEXT, updated_at TEXT, closed_at TEXT);

-- 第九轮：多角色闭环工作流 / 知识发布治理 / 资产台账 / 插件治理 / 权限精细化
-- 口径：每张表承载一个"作业流程"的输入与状态，写操作一律校验 + 审计留痕。

-- 插件治理（启停开关 / 逐插件配置项 / 三种装载方式）
CREATE TABLE IF NOT EXISTS plugin_setting(
  plugin_id TEXT PRIMARY KEY, enabled INTEGER DEFAULT 1, kind TEXT DEFAULT 'builtin',
  config_json TEXT, config_schema_json TEXT, loaded_at TEXT, updated_by TEXT, updated_at TEXT);

-- 安全治理闭环（登记→定级→派单→接收→整改→回复→复检→核查确认→归档）
CREATE TABLE IF NOT EXISTS gov_issue(
  issue_id TEXT PRIMARY KEY, issue_no TEXT, title TEXT, source TEXT, category TEXT,
  severity TEXT, dept_id TEXT, dept_name TEXT, position_id TEXT, position_name TEXT,
  owner TEXT, status TEXT DEFAULT 'open', due_date TEXT, plan TEXT, recheck_result TEXT,
  created_by TEXT, created_at TEXT, updated_at TEXT, closed_at TEXT);

CREATE TABLE IF NOT EXISTS gov_transition(
  transition_id TEXT PRIMARY KEY, issue_id TEXT, from_status TEXT, to_status TEXT,
  action TEXT, actor TEXT, actor_name TEXT, comment TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS gov_evidence(
  evidence_id TEXT PRIMARY KEY, issue_id TEXT, step TEXT, file_name TEXT, note TEXT,
  uploaded_by TEXT, uploaded_at TEXT);

-- 知识发布治理（目标知识库 / 文档 / 版本 / 变更清单 / 调用日志 / 专家审核）
CREATE TABLE IF NOT EXISTS kb_target(
  kb_id TEXT PRIMARY KEY, name TEXT, kind TEXT, doc_count INTEGER DEFAULT 0, synced_at TEXT);

CREATE TABLE IF NOT EXISTS kb_document(
  doc_id TEXT PRIMARY KEY, kb_id TEXT, title TEXT, doc_type TEXT, source TEXT,
  version TEXT, status TEXT, owner TEXT, uploaded_by TEXT, created_at TEXT, updated_at TEXT);

CREATE TABLE IF NOT EXISTS kb_doc_version(
  version_id TEXT PRIMARY KEY, doc_id TEXT, version TEXT, content_hash TEXT, note TEXT,
  created_by TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS kb_change_log(
  change_id TEXT PRIMARY KEY, doc_id TEXT, change_type TEXT, summary TEXT,
  actor TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS kb_call_log(
  call_id TEXT PRIMARY KEY, doc_id TEXT, caller TEXT, scene TEXT, query TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS kb_review(
  review_id TEXT PRIMARY KEY, doc_id TEXT, reviewer TEXT, reviewer_name TEXT,
  decision TEXT, comment TEXT, created_at TEXT, decided_at TEXT);

-- 资产台账（应用资产 / 配置管理 / 制度办法 分类汇总 + 知识库联动）
CREATE TABLE IF NOT EXISTS asset_record(
  asset_id TEXT PRIMARY KEY, name TEXT, category TEXT, source TEXT, dept_id TEXT, dept_name TEXT,
  owner TEXT, version TEXT, status TEXT, kb_doc_id TEXT, note TEXT,
  created_by TEXT, created_at TEXT, updated_at TEXT);

-- 场景包扩展（知识来源 / 调用的知识库 / 部门岗位角色 / 工具 / 系统 / 模板）
CREATE TABLE IF NOT EXISTS scenario_detail(
  pack_id TEXT PRIMARY KEY, knowledge_source TEXT, kb_ids_json TEXT, depts_json TEXT,
  positions_json TEXT, roles_json TEXT, tools_json TEXT, systems_json TEXT, templates_json TEXT,
  updated_by TEXT, updated_at TEXT);

-- 权限精细化（角色-菜单操作权限 / 角色-数据权限）+ 轻量单点登录配置
CREATE TABLE IF NOT EXISTS role_menu_perm(
  perm_id TEXT PRIMARY KEY, role_id TEXT, menu_key TEXT, actions_json TEXT);

CREATE TABLE IF NOT EXISTS role_data_scope(
  scope_id TEXT PRIMARY KEY, role_id TEXT, scope_type TEXT, scope_json TEXT,
  updated_by TEXT, updated_at TEXT);

CREATE TABLE IF NOT EXISTS sso_config(k TEXT PRIMARY KEY, v TEXT);

-- 现状诊断输入材料（历史自查报告 / 工作佐证 / 资产配置 / 资产清单）
CREATE TABLE IF NOT EXISTS diag_input(
  input_id TEXT PRIMARY KEY, assessment_id TEXT, kind TEXT, file_name TEXT, note TEXT,
  size INTEGER, uploaded_by TEXT, uploaded_at TEXT);

-- 演示状态（键值）
CREATE TABLE IF NOT EXISTS demo_state(k TEXT PRIMARY KEY, v TEXT);
"""


def get_conn() -> sqlite3.Connection:
    """建立演示库连接（WAL + busy_timeout + Row 工厂），范式与 app/db.py 一致。"""
    conn = sqlite3.connect(str(DEMO_DB), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 8000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def demo_db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


ALL_TABLES = [
    "org_node", "org_position", "user_account", "role_def", "role_binding",
    "industry_profile", "doc_registry", "inspection_plan", "selfcheck_task",
    "selfcheck_section", "selfcheck_item_state", "inspection_run", "check_result",
    "inspection_evidence", "inspection_signoff", "selfcheck_finding", "remediation_task",
    "check_assignment_rule", "assignment_batch", "check_assignment_override",
    "hitl_candidate", "knowledge_proposal", "review_task", "kb_publish_manifest",
    "kb_publish_run", "audit_log", "scenario_pack", "plugin_registry", "plugin_invocation",
    "collect_task", "kb_category_mapping", "demo_state",
    # 第八轮：8 个扩展视图功能化表
    "frame_chain_case", "frame_ring_record",
    "diag_assessment", "diag_answer", "ledger_row", "issue_disposal",
    # 第九轮：多角色闭环工作流 / 知识发布治理 / 资产台账 / 插件治理 / 权限精细化
    "plugin_setting", "gov_issue", "gov_transition", "gov_evidence",
    "kb_target", "kb_document", "kb_doc_version", "kb_change_log", "kb_call_log", "kb_review",
    "asset_record", "scenario_detail", "role_menu_perm", "role_data_scope", "sso_config",
    "diag_input",
]


def init_demo_db() -> None:
    """建表（幂等）。"""
    with demo_db() as conn:
        conn.executescript(SCHEMA)


def reset_demo_db() -> None:
    """清空全部演示表（保留表结构），用于演示重置。"""
    with demo_db() as conn:
        for t in ALL_TABLES:
            conn.execute(f"DELETE FROM {t}")


# ---------------- 通用读写 ----------------
def q(sql: str, args=()) -> list[dict]:
    """查询：返回 dict 列表（JSON 友好）。"""
    with demo_db() as conn:
        rows = conn.execute(sql, tuple(args or ())).fetchall()
        return [dict(r) for r in rows]


def q1(sql: str, args=()) -> dict | None:
    rows = q(sql, args)
    return rows[0] if rows else None


def x(sql: str, args=()) -> int:
    """执行写操作：返回受影响行数。"""
    with demo_db() as conn:
        cur = conn.execute(sql, tuple(args or ()))
        return cur.rowcount


def insert(table: str, data: dict) -> int:
    """按 dict 插入（INSERT OR REPLACE，固定主键天然幂等）。"""
    cols = list(data.keys())
    ph = ",".join(["?"] * len(cols))
    sql = f"INSERT OR REPLACE INTO {table}({','.join(cols)}) VALUES({ph})"
    return x(sql, [data[c] for c in cols])


# ---------------- demo_state 读写 ----------------
def get_state(k: str, default=None):
    row = q1("SELECT v FROM demo_state WHERE k=?", (k,))
    if not row:
        return default
    try:
        return json.loads(row["v"])
    except Exception:  # noqa: BLE001 — 兼容存字符串的场景
        return row["v"]


def set_state(k: str, v) -> None:
    insert("demo_state", {"k": k, "v": json.dumps(v, ensure_ascii=False)})


# ---------------- 审计（只追加 哈希链） ----------------
def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def write_audit(actor: str, action: str, target: str = "", params: dict | None = None,
                result: str = "ok", actor_name: str = "", ts: str | None = None) -> dict:
    """写一条审计记录，串联 prev_hash→hash（篡改可验）。ts 可显式指定（种子回放用）。"""
    ts = ts or _now()
    with demo_db() as conn:
        last = conn.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        prev = (last["hash"] if last and last["hash"] else "GENESIS")
        payload = json.dumps(params or {}, ensure_ascii=False, sort_keys=True)
        h = hashlib.sha256(f"{prev}|{ts}|{actor}|{action}|{target}|{payload}".encode("utf-8")).hexdigest()
        conn.execute(
            "INSERT INTO audit_log(ts,actor,actor_name,action,target,params_json,result,prev_hash,hash) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (ts, actor, actor_name, action, target, payload, result, prev, h))
    return {"ts": ts, "prev_hash": prev, "hash": h}


def audit_chain_ok() -> bool:
    """校验审计哈希链是否自洽（供治理看板展示）。"""
    rows = q("SELECT ts,actor,action,target,params_json,prev_hash,hash FROM audit_log ORDER BY id")
    prev = "GENESIS"
    for r in rows:
        expect = hashlib.sha256(
            f"{prev}|{r['ts']}|{r['actor']}|{r['action']}|{r['target']}|{r['params_json']}"
            .encode("utf-8")).hexdigest()
        if r["prev_hash"] != prev or r["hash"] != expect:
            return False
        prev = r["hash"]
    return True
