"""全量功能 Demo 路由（契约 §5 全部接口）。

大白话：这是演示平台的"服务员"——把 app/demo/store.py 里的演示数据传输给前端，
并按契约做最小限度的过程模拟（知识发布分阶段、一键演示 9 幕、登录切换身份、
身份源不可用演示、职责分离互斥校验等）。所有写操作都会落审计（哈希链）。

约定：
- 知识取数类接口（/api/kb/qa、/api/selfcheck/templates）返回统一信封
  {content, source, sourceDetail, fetchedAt, version, contractVersion:"3.0"}；
  其余接口返回直接业务 JSON。
- 失败统一返回 {"error":{code,message,details},"traceId"}，HTTP 状态码按契约 §2。
"""
from __future__ import annotations

import csv
import io
import json
import time
import uuid
import datetime

from fastapi import APIRouter, Query, Body
from fastapi.responses import JSONResponse, PlainTextResponse

from . import store
from . import seed

router = APIRouter(prefix="/api")

CONTRACT_VERSION = "3.0"
_SRC_DETAIL = {
    "weknora": "知识库平台（实时）",
    "canonical": "RDF 正本图（正本文件）",
    "db": "PostgreSQL 结构化投影",
    "sqlite": "运行台账（SQLite）",
    "none": "无可用来源",
}
_CODE_STATUS = {"AUTH_REQUIRED": 401, "FORBIDDEN": 403, "NOT_FOUND": 404,
                "VALIDATION_FAILED": 422, "DEPENDENCY_DOWN": 503, "RATE_LIMITED": 429}


# ===========================================================================
# 通用小工具
# ===========================================================================
def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _trace() -> str:
    return "trc_" + uuid.uuid4().hex[:12]


def _err(code: str, message: str, status: int | None = None, details: dict | None = None):
    return JSONResponse(status_code=status or _CODE_STATUS.get(code, 400),
                        content={"error": {"code": code, "message": message,
                                           "details": details or {}}, "traceId": _trace()})


def _env(content, source: str, version: str = "v3") -> dict:
    """统一知识信封（PRD §7.3）。"""
    return {"content": content, "source": source, "sourceDetail": _SRC_DETAIL.get(source, ""),
            "fetchedAt": _now(), "version": version, "contractVersion": CONTRACT_VERSION}


def _audit(actor: str, action: str, target: str = "", params: dict | None = None,
           result: str = "ok") -> None:
    name = ""
    row = store.q1("SELECT display_name FROM user_account WHERE account=?", (actor,))
    if row:
        name = row["display_name"]
    store.write_audit(actor, action, target, params, result=result, actor_name=name)


def _jloads(s, default):
    try:
        return json.loads(s) if s else default
    except Exception:  # noqa: BLE001
        return default


def _lookup_name(table: str, key: str, val):
    """按主键取组织 / 岗位名称；缺失返回空串（用于责任归属展示）。"""
    if not val:
        return ""
    row = store.q1(f"SELECT name FROM {table} WHERE {key}=?", (val,))
    return row["name"] if row else ""


# ---------------- 演示故障开关（统一错误信封 / 降级演示） ----------------
_ERROR_MESSAGES = {
    "AUTH_REQUIRED": "未登录或会话已过期，请先登录",
    "FORBIDDEN": "职责分离校验不通过：经办与复核不得为同一账号",
    "NOT_FOUND": "请求的资源不存在",
    "VALIDATION_FAILED": "请求参数校验失败",
    "DEPENDENCY_DOWN": "依赖服务不可用：权威正本图暂不可达",
    "RATE_LIMITED": "请求过于频繁，请稍后重试",
}
_RL_HITS: dict = {}

# 作业 / 调用 / 任务状态的中文展示（页面语言统一：不直接暴露英文枚举）
_RUN_STATUS = {"running": "进行中", "success": "成功", "succeeded": "成功",
               "failed": "失败", "error": "失败", "degraded": "降级"}
_TASK_STATUS = {"in_progress": "进行中", "closed": "已闭环", "draft": "草稿",
                "pending": "待处理", "done": "已完成", "open": "待处理"}

# 经验回流 14 类目（PRD §6.2 / L3）
PROPOSAL_CATEGORIES = ["RA1", "RA2", "RA3", "RB1", "RB2", "RB3", "RB4", "RB5",
                       "RC1", "RC2", "RD1", "RD2", "RD3", "RH1"]


def _rate_limit_hit(key: str, limit: int, window_sec: int) -> bool:
    """滑动窗口限流。仅当 demo_state.rate_limit 开启时生效；True=已超限。"""
    if not store.get_state("rate_limit", False):
        return False
    now = time.time()
    hits = [t for t in _RL_HITS.get(key, []) if now - t < window_sec]
    hits.append(now)
    _RL_HITS[key] = hits
    return len(hits) > limit


def _has_session() -> bool:
    """是否存在有效会话（区别于 _current_account 的 admin 兜底）。"""
    acc = store.get_state("current_account", "")
    return bool(acc) and bool(_account_row(acc))


def _require_auth():
    """开启 demo_state.require_auth 时，无有效会话 → 401。返回错误信封或 None。"""
    if store.get_state("require_auth", False) and not _has_session():
        return _err("AUTH_REQUIRED", _ERROR_MESSAGES["AUTH_REQUIRED"], 401)
    return None


# ---------------- 会话与可见范围 ----------------
def _current_account() -> str:
    return store.get_state("current_account", "admin") or "admin"


def _account_row(account: str) -> dict | None:
    return store.q1("SELECT * FROM user_account WHERE account=?", (account,))


def _roles_of(account: str) -> list[str]:
    rows = store.q("SELECT role_id FROM role_binding WHERE account=?", (account,))
    return [r["role_id"] for r in rows]


def _expand_caps(roles: list[str]) -> list[str]:
    caps = set()
    for rid in roles:
        for c in seed.ROLE_CAPS.get(rid, []):
            if c == "*":
                caps.update(seed.CAPABILITY_LABELS.keys())
            else:
                caps.add(c)
    return sorted(caps)


def _session_info(account: str) -> dict:
    row = _account_row(account)
    if not row:
        return {"account": account, "displayName": account, "roles": [], "capabilities": [],
                "org": None, "isBootstrap": False, "authenticated": False}
    roles = _roles_of(account)
    node = store.q1("SELECT node_id,name,level,industry FROM org_node WHERE node_id=?",
                    (row["org_node_id"],)) if row["org_node_id"] else None
    lv = None
    rrow = store.q1("SELECT level_visibility FROM role_def WHERE role_id=?",
                    (roles[0],)) if roles else None
    if rrow:
        lv = rrow["level_visibility"]
    return {"account": account, "displayName": row["display_name"], "roles": roles,
            "capabilities": _expand_caps(roles), "org": node,
            "position": row["position_id"], "levelVisibility": lv,
            "isBootstrap": bool(row["is_bootstrap"]),
            "status": row["status"], "authenticated": True}


def _children_map() -> dict:
    rows = store.q("SELECT node_id,parent_id FROM org_node")
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(r["parent_id"] or "", []).append(r["node_id"])
    return out


def _subtree(node_id: str, cmap: dict) -> set:
    """含自身的子树节点集合。"""
    seen, stack = set(), [node_id]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(cmap.get(n, []))
    return seen


def _visible_tasks(account: str | None) -> list[dict]:
    """按账号可见范围过滤任务：L0/系统管理员见全部；L1/L2/L3 见本级子树。"""
    acc = account or _current_account()
    tasks = store.q("SELECT * FROM selfcheck_task ORDER BY created_at DESC")
    row = _account_row(acc)
    roles = _roles_of(acc)
    if not row or "sys_admin" in roles:
        return tasks
    node = row["org_node_id"]
    nrow = store.q1("SELECT level,industry FROM org_node WHERE node_id=?", (node,)) if node else None
    if not nrow:
        return tasks
    if nrow["level"] == "L0":
        return [t for t in tasks if t["industry"] == nrow["industry"]]
    cmap = _children_map()
    visible = _subtree(node, cmap)
    return [t for t in tasks if t["org_node_id"] in visible]


def _task_or_404(task_id: str):
    return store.q1("SELECT * FROM selfcheck_task WHERE task_id=?", (task_id,))


# ===========================================================================
# 5.1 演示控制
# ===========================================================================
@router.get("/demo/overview")
def demo_overview():
    tasks = store.q("SELECT status,progress,risk_level,industry FROM selfcheck_task")
    findings = store.q("SELECT status,severity FROM selfcheck_finding")
    proposals = store.q("SELECT status FROM knowledge_proposal")
    hitl = store.q("SELECT status FROM hitl_candidate")
    plugins = store.q("SELECT status FROM plugin_registry")
    audit_n = (store.q1("SELECT COUNT(*) AS n FROM audit_log") or {}).get("n", 0)
    running = store.q1("SELECT * FROM kb_publish_run WHERE run_id=?",
                       (store.get_state("publish_current", ""),))
    kpi = [
        {"key": "tasks", "label": "自查任务", "value": len(tasks),
         "sub": f"进行中 {sum(1 for t in tasks if t['status'] == 'in_progress')}"},
        {"key": "findings", "label": "发现问题", "value": len(findings),
         "sub": f"未闭环 {sum(1 for f in findings if f['status'] not in ('closed', 'passed'))}"},
        {"key": "proposals", "label": "知识提案", "value": len(proposals),
         "sub": f"待审 {sum(1 for p in proposals if p['status'] == 'pending')}"},
        {"key": "hitl", "label": "待人工确认", "value": len(hitl),
         "sub": f"待确认 {sum(1 for h in hitl if h['status'] == 'pending')}"},
        {"key": "plugins", "label": "插件在线", "value": f"{sum(1 for p in plugins if p['status'] == '在线')}/{len(plugins)}",
         "sub": "降级自动转人工"},
        {"key": "audit", "label": "审计留痕", "value": audit_n, "sub": "哈希链可验"},
    ]
    modules = [
        {"key": "pipeline", "label": "知识发布", "health": "ok",
         "detail": f"当前版本 {store.get_state('publish_current', '-')}"},
        {"key": "selfcheck", "label": "安全自查", "health": "ok",
         "detail": f"{len(tasks)} 个任务"},
        {"key": "governance", "label": "回流审核", "health": "warn" if any(
            p["status"] == "pending" for p in proposals) else "ok",
         "detail": f"{sum(1 for p in proposals if p['status'] == 'pending')} 条待审"},
        {"key": "plugins", "label": "场景与插件", "health": "warn" if any(
            p["status"] != "在线" for p in plugins) else "ok", "detail": "降级不阻断"},
        {"key": "audit", "label": "审计与合规", "health": "ok",
         "detail": "只追加不可改写"},
    ]
    return {"kpi": kpi, "modules": modules, "session": _session_info(_current_account()),
            "now": _now(), "demo": True, "dataLabel": "演示数据 / 脱敏合成",
            "currentVersion": store.get_state("publish_current", "-")}


@router.get("/demo/activity")
def demo_activity(limit: int = 30):
    items = []
    for r in store.q("SELECT ts,actor,actor_name,action,target,result FROM audit_log "
                     "ORDER BY id DESC LIMIT ?", (limit,)):
        items.append({"ts": r["ts"], "kind": "audit", "actor": r["actor"],
                      "actorName": r["actor_name"], "title": r["action"],
                      "detail": r["target"], "result": r["result"]})
    for r in store.q("SELECT task_id,org_name,status,updated_at FROM selfcheck_task "
                     "ORDER BY updated_at DESC LIMIT ?", (limit,)):
        items.append({"ts": r["updated_at"], "kind": "task", "actor": "system",
                      "actorName": "系统", "title": "自查任务",
                      "detail": f"{r['org_name']} · {_TASK_STATUS.get(r['status'], r['status'])}", "result": "ok"})
    for r in store.q("SELECT run_id,status,finished_at,duration_ms FROM kb_publish_run "
                     "ORDER BY started_at DESC LIMIT ?", (limit,)):
        items.append({"ts": r["finished_at"] or "", "kind": "publish", "actor": "system",
                      "actorName": "系统", "title": "知识重建",
                      "detail": f"{r['run_id']} · {_RUN_STATUS.get(r['status'], r['status'])} · {r['duration_ms']} 毫秒",
                      "result": r["status"]})
    for r in store.q("SELECT invocation_id,plugin_id,status,created_at FROM plugin_invocation "
                     "ORDER BY created_at DESC LIMIT ?", (limit,)):
        items.append({"ts": r["created_at"], "kind": "plugin", "actor": "system",
                      "actorName": "系统", "title": "插件调用",
                      "detail": f"{r['plugin_id']} · {_RUN_STATUS.get(r['status'], r['status'])}", "result": r["status"]})
    items.sort(key=lambda x: x.get("ts") or "", reverse=True)
    return {"activity": items[:limit]}


@router.post("/demo/reset")
def demo_reset():
    res = seed.reset_seed()
    _audit("admin", "demo.reset", "demo", {"version": res["version"]})
    return {"ok": True, "version": res["version"], "resetAt": res["reset_at"],
            "resetCount": res["reset_count"]}


SCENARIO_STEPS = [
    {"step": 0, "title": "知识取数：实时知识库优先 + 多源降级",
     "desc": "展示取数来源与知识问答的统一信封（实时知识库 → 权威正本图 → 结构化投影 → 运行台账 逐级回落）"},
    {"step": 1, "title": "知识发布：变更感知 → 增量重建 → 质量校验 → 整版发布",
     "desc": "发起一次增量重建，观察分阶段推进与版本目录切换"},
    {"step": 2, "title": "行业建档：行业档案与行业化清单",
     "desc": "按行业/条线取清单模板（含 snapshotVersion + 六维摘要）"},
    {"step": 3, "title": "自查任务：下发与单项登记",
     "desc": "创建任务，登记四录入项（制度/证据/实际值/备注）"},
    {"step": 4, "title": "责任分配：预览 → 覆盖 → 下发",
     "desc": "条款责任自动映射 + 未匹配/冲突 + 版本批次"},
    {"step": 5, "title": "证据与签署：职责分离（经办 ≠ 复核）",
     "desc": "上传证据元数据 + 签核；同一账号签核将被拒绝（职责分离拦截）"},
    {"step": 6, "title": "判定与报告：三色判定 + 计分依据 + 报告导出",
     "desc": "按最差项聚合出结论，导出行业版报告"},
    {"step": 7, "title": "整改与复检：问题整改 → 复跑同一检查项 → 前后对比",
     "desc": "登记整改并复检，导出复检前后对比（对应 PRD §2.7 走查幕7）"},
    {"step": 8, "title": "回流审核：缺口提案 + 人工确认",
     "desc": "提案审核（审核人 ≠ 提出人）+ 人工确认决策"},
]


@router.get("/demo/scenario/steps")
def scenario_steps():
    return {"steps": SCENARIO_STEPS, "total": len(SCENARIO_STEPS)}


@router.post("/demo/scenario/run")
def scenario_run(body: dict = Body(default=None)):
    body = body or {}
    step = int(body.get("step", 0))
    if step < 0 or step >= len(SCENARIO_STEPS):
        return _err("VALIDATION_FAILED", f"步骤号必须在 0..{len(SCENARIO_STEPS) - 1} 之间", 422)
    tasks = store.q("SELECT task_id,org_name,status,progress FROM selfcheck_task LIMIT 3")
    tid = tasks[0]["task_id"] if tasks else "t-bank-2026q4"
    meta = SCENARIO_STEPS[step]
    logs, result, artifacts = [], {}, {}
    if step == 0:
        logs = ["探测知识来源可达性 …", "实时知识库未配置令牌 → 降级结构化投影", "取到检查项 116 条",
                "统一取数信封：来源=结构化投影，契约版本=3.0"]
        result = {"取数来源": "结构化投影", "检查项数": 116,
                  "降级顺序": ["实时知识库", "权威正本图", "结构化投影", "运行台账"]}
        artifacts = {"知识问答接口": "/api/kb/qa", "来源清单接口": "/api/kb/sources"}
    elif step == 1:
        run = _new_publish_run("manual", "incremental", "kbops")
        logs = ["变更感知：识别 6 个变更文档", "增量重建：重建受影响分片", "质量校验：校验内容哈希",
                "整版发布：切换当前版本指针"]
        result = {"作业编号": run["runId"], "当前阶段": "增量重建"}
        artifacts = {"作业详情接口": f"/api/kb/publish/run/{run['runId']}"}
    elif step == 2:
        env = selfcheck_templates("bank", "")
        result = {"行业": "银行", "取数来源": env["source"],
                  "分组数": len((env["content"] or {}).get("groups", []))}
        artifacts = {"行业模板接口": "/api/selfcheck/templates?industry=bank"}
        logs = ["加载行业档案：银行", "按条线分组：账户与支付/信贷/征信/理财", "生成清单快照"]
    elif step == 3:
        result = {"任务编号": tid,
                  "状态": _TASK_STATUS.get(tasks[0]["status"], tasks[0]["status"]) if tasks else "进行中"}
        logs = ["下发自查任务", "登记四录入项：制度/证据/实际值/备注", "自动计算进度与风险分级"]
        artifacts = {"任务详情接口": f"/api/selfcheck/tasks/{tid}"}
    elif step == 4:
        prev = _assignment_preview(tid, {"stage": "季度自查", "topic": "数据安全专项", "scope": {}})
        result = {"覆盖率": prev.get("coverage"), "匹配条款数": prev.get("matchedCount")}
        logs = ["按规则生成映射预览", f"覆盖率 {prev.get('coverage')}%",
                f"未匹配 {len(prev.get('unmatched', []))} 条"]
        artifacts = {"映射预览接口": f"/api/selfcheck/tasks/{tid}/assignments/preview"}
    elif step == 5:
        logs = ["上传证据元数据（不落真实文件，仅登记哈希）", "提交签核（经办 lijb）",
                "复核账号必须与经办账号不同（职责分离）"]
        result = {"职责分离": "签署人 ≠ 提交人", "提交人": "lijb"}
        artifacts = {"签署接口": f"/api/selfcheck/tasks/{tid}/signoff"}
    elif step == 6:
        rep = task_report(tid, "json")
        result = {"任务编号": tid, "结论摘要": rep.get("summary")}
        logs = ["按最差项聚合逐项判定", "生成计分依据", "导出行业版报告"]
        artifacts = {"报告接口": f"/api/selfcheck/tasks/{tid}/report"}
    elif step == 7:
        # 幕7：整改与复检（张经办整改 → 复跑同一检查项 → 前后对比）
        trow = store.q1("SELECT task_id FROM selfcheck_task WHERE status='closed' LIMIT 1")
        rtid = trow["task_id"] if trow else tid
        logs = ["问题登记并按责任人分派整改", "整改完成 → 发起复检（复跑同一检查项集合）",
                "生成复检前后对比（按 通过数/总数 现算）"]
        result = {"任务编号": rtid, "作业类型": "复检"}
        try:
            d = recheck_diff(rtid)
            if isinstance(d, dict) and "taskLevel" in d:
                result["复检前"] = d.get("beforeRun")
                result["复检后"] = d.get("afterRun")
                result["变化量"] = (d.get("taskLevel") or {}).get("delta")
        except Exception:  # noqa: BLE001 — 无复检数据时不影响演示
            pass
        artifacts = {"复检接口": f"/api/selfcheck/tasks/{rtid}/recheck",
                     "前后对比接口": f"/api/selfcheck/tasks/{rtid}/recheck/diff"}
    else:
        props = store.q("SELECT status FROM knowledge_proposal")
        cands = store.q("SELECT status FROM hitl_candidate")
        result = {"待审提案": sum(1 for p in props if p["status"] == "pending"),
                  "待人工确认": sum(1 for c in cands if c["status"] == "pending")}
        logs = ["沉淀缺口提案", "低置信度项转人工确认", "审核记录留痕"]
        artifacts = {"提案接口": "/api/review/proposals", "人工确认接口": "/api/hitl/candidates"}
    _audit(_current_account(), "demo.scenario.run", f"step-{step}", {"title": meta["title"]})
    return {"step": step, "title": meta["title"], "status": "done", "logs": logs,
            "result": result, "artifacts": artifacts}


# ---------------- 演示故障开关（统一错误信封 / 降级演示） ----------------
def _fault_state() -> dict:
    return {"requireAuth": bool(store.get_state("require_auth", False)),
            "rateLimit": bool(store.get_state("rate_limit", False)),
            "storeDown": bool(store.get_state("store_down", False))}


@router.get("/demo/fault/state")
def demo_fault_state():
    return {**_fault_state(), "errorCodes": list(_CODE_STATUS.keys())}


@router.post("/demo/fault/state")
def demo_fault_state_set(body: dict = Body(default=None)):
    body = body or {}
    mapping = {"requireAuth": "require_auth", "rateLimit": "rate_limit", "storeDown": "store_down"}
    changed = {}
    for in_key, state_key in mapping.items():
        if in_key in body:
            store.set_state(state_key, bool(body[in_key]))
            changed[in_key] = bool(body[in_key])
    _audit(_current_account(), "demo.fault.switch", "fault", changed,
           result="degraded" if any(changed.values()) else "ok")
    return {"ok": True, "changed": changed, **_fault_state()}


@router.post("/demo/fault")
def demo_fault(body: dict = Body(default=None)):
    """错误信封演示：按错误码返回统一错误信封（HTTP 状态码 + traceId 齐全）。"""
    body = body or {}
    code = str(body.get("code") or "").upper()
    if code not in _CODE_STATUS:
        return _err("VALIDATION_FAILED", "不支持的错误码", 422, {"supported": sorted(_CODE_STATUS)})
    _audit(_current_account(), "demo.fault", code, {"code": code}, result="degraded")
    return _err(code, body.get("message") or _ERROR_MESSAGES.get(code, "演示错误"), None,
                {"demo": True, "hint": "统一错误信封演示（PRD §7.3）"})


# ===========================================================================
# 数据保存策略（设置页 · 演示口径）
# ===========================================================================
# 大白话：设置页里的"数据保存策略"表单。字段名保持机器可读（英文键），
# 界面文案由前端负责中文化；策略只落 demo_state 键值，复位演示数据即回默认值。
_RETENTION_DEFAULTS = {
    "taskOnlineCycles": 1,          # 自查任务与结果：关闭后在线保留（核查周期数）
    "taskArchiveYears": 3,          # 自查任务与结果：归档只读保留（年）
    "auditOnlineYears": 1,          # 审计日志：在线保留（年）
    "auditArchiveYears": 3,         # 审计日志：归档保留（年）
    "backupDays": 90,               # 备份：保留（天）
    "backupDrillQuarterly": True,   # 备份：季度恢复演练
    "purgeApprovalLevel": "dual",   # 超期销毁审批：single | dual
}
# 字段 → (最小值, 最大值)；数值型策略的合法区间
_RETENTION_RANGES = {
    "taskOnlineCycles": (1, 12), "taskArchiveYears": (1, 30),
    "auditOnlineYears": (1, 10), "auditArchiveYears": (1, 30),
    "backupDays": (30, 730),
}
_RETENTION_STATE_KEY = "retention_policy"


def _retention_policy() -> dict:
    saved = store.get_state(_RETENTION_STATE_KEY, {}) or {}
    merged = dict(_RETENTION_DEFAULTS)
    if isinstance(saved, dict):
        for k in _RETENTION_DEFAULTS:
            if k in saved:
                merged[k] = saved[k]
    return merged


@router.get("/demo/retention-policy")
def get_retention_policy():
    meta = store.get_state(_RETENTION_STATE_KEY + "_meta", {}) or {}
    return {**_retention_policy(), "defaults": dict(_RETENTION_DEFAULTS),
            "updatedAt": meta.get("updatedAt"), "updatedBy": meta.get("updatedBy")}


@router.put("/demo/retention-policy")
def put_retention_policy(payload: dict = Body(default=None)):
    """保存数据保存策略：数值型做区间校验，审批级别只接受 single / dual。"""
    payload = payload or {}
    policy = _retention_policy()
    changed = {}
    for key, (lo, hi) in _RETENTION_RANGES.items():
        if key not in payload:
            continue
        try:
            val = int(payload[key])
        except (TypeError, ValueError):
            return _err("VALIDATION_FAILED", f"{key} 需为整数", 422, {"field": key})
        if not (lo <= val <= hi):
            return _err("VALIDATION_FAILED", f"{key} 需在 {lo}–{hi} 之间", 422,
                        {"field": key, "min": lo, "max": hi})
        policy[key] = val
        changed[key] = val
    if "backupDrillQuarterly" in payload:
        policy["backupDrillQuarterly"] = bool(payload["backupDrillQuarterly"])
        changed["backupDrillQuarterly"] = policy["backupDrillQuarterly"]
    if "purgeApprovalLevel" in payload:
        level = str(payload["purgeApprovalLevel"])
        if level not in ("single", "dual"):
            return _err("VALIDATION_FAILED", "purgeApprovalLevel 仅支持 single / dual", 422,
                        {"field": "purgeApprovalLevel"})
        policy["purgeApprovalLevel"] = level
        changed["purgeApprovalLevel"] = level
    actor = _current_account()
    store.set_state(_RETENTION_STATE_KEY, policy)
    store.set_state(_RETENTION_STATE_KEY + "_meta",
                    {"updatedAt": _now(), "updatedBy": actor})
    _audit(actor, "settings.retention.update", "retention", changed)
    return {"ok": True, **_retention_policy(), "updatedAt": _now(), "updatedBy": actor}


@router.post("/demo/retention-policy/reset")
def reset_retention_policy():
    store.set_state(_RETENTION_STATE_KEY, dict(_RETENTION_DEFAULTS))
    store.set_state(_RETENTION_STATE_KEY + "_meta", {})
    actor = _current_account()
    _audit(actor, "settings.retention.reset", "retention", dict(_RETENTION_DEFAULTS))
    return {"ok": True, **_retention_policy(), "defaults": dict(_RETENTION_DEFAULTS)}


# ===========================================================================
# 5.2 知识发布 / 知识治理
# ===========================================================================
_PUBLISH_STAGES = [
    ("变更感知", 0, 1200), ("增量重建", 1200, 3800), ("质量校验", 3800, 5400), ("整版发布", 5400, 6400)]


def _new_publish_run(trigger: str, mode: str, operator: str) -> dict:
    rid = "run-live-" + uuid.uuid4().hex[:8]
    total = 26 if mode == "full" else 24
    store.insert("kb_publish_run", {
        "run_id": rid, "trigger": trigger, "mode": mode, "started_at": _now(), "finished_at": None,
        "status": "running", "version_dir": None, "changed_docs": 0, "total_docs": total,
        "duration_ms": 0, "error": None, "operator": operator})
    store.set_state("active_run", {"runId": rid, "startedTs": time.time(), "mode": mode,
                                   "total": total})
    return {"runId": rid, "mode": mode, "status": "running"}


def _advance_run(run_id: str) -> dict:
    """按经过时间推进阶段；超过总时长则置为成功并切换当前版本。"""
    row = store.q1("SELECT * FROM kb_publish_run WHERE run_id=?", (run_id,))
    if not row:
        return {}
    if row["status"] != "running":
        return row
    act = store.get_state("active_run") or {}
    if act.get("runId") != run_id:
        elapsed_ms = 9999
    else:
        elapsed_ms = (time.time() - act.get("startedTs", time.time())) * 1000
    if elapsed_ms >= _PUBLISH_STAGES[-1][2]:
        vdir = "v" + datetime.datetime.now().strftime("%Y.%m.%d.%H%M")
        store.x("UPDATE kb_publish_run SET status=?,finished_at=?,version_dir=?,duration_ms=?,"
                "changed_docs=? WHERE run_id=?",
                ("success", _now(), vdir, int(elapsed_ms), (act.get("total") or 24) - 18, run_id))
        store.set_state("publish_current", vdir)
        store.set_state("active_run", None)
        _audit(row["operator"], "kb.publish", run_id, {"versionDir": vdir, "status": "success"})
        return store.q1("SELECT * FROM kb_publish_run WHERE run_id=?", (run_id,)) or {}
    return row


def _run_stage(run_id: str) -> dict:
    act = store.get_state("active_run") or {}
    elapsed = (time.time() - act.get("startedTs", time.time())) * 1000 if act.get("runId") == run_id else 99999
    idx = 0
    for i, (name, _s, end) in enumerate(_PUBLISH_STAGES):
        if elapsed >= end:
            idx = min(i + 1, len(_PUBLISH_STAGES) - 1)
    stage = _PUBLISH_STAGES[idx][0]
    logs = [f"[{_PUBLISH_STAGES[i][0]}] 完成" for i in range(idx)]
    logs.append(f"[{stage}] 进行中 …")
    return {"stage": stage, "stageIndex": idx, "elapsedMs": int(elapsed), "logs": logs}


@router.get("/kb/publish/status")
def publish_status():
    act = store.get_state("active_run") or {}
    if act.get("runId"):
        _advance_run(act["runId"])
    row = store.q1("SELECT * FROM kb_publish_run ORDER BY started_at DESC LIMIT 1")
    if not row:
        return {"currentVersion": store.get_state("publish_current", "-"), "run": None}
    detail = _run_stage(row["run_id"]) if row["status"] == "running" else {
        "stage": "已完成", "stageIndex": len(_PUBLISH_STAGES), "elapsedMs": row["duration_ms"],
        "logs": [f"[{s[0]}] 完成" for s in _PUBLISH_STAGES]}
    return {"currentVersion": store.get_state("publish_current", "-"), "run": {
        "runId": row["run_id"], "trigger": row["trigger"], "mode": row["mode"],
        "status": row["status"], "startedAt": row["started_at"], "finishedAt": row["finished_at"],
        "changedDocs": row["changed_docs"], "totalDocs": row["total_docs"],
        "durationMs": row["duration_ms"], "error": row["error"], **detail}}


@router.get("/kb/publish/history")
def publish_history():
    cur = store.get_state("publish_current", "")
    rows = store.q("SELECT * FROM kb_publish_run ORDER BY started_at DESC")
    return {"history": [{
        "runId": r["run_id"], "versionDir": r["version_dir"], "status": r["status"],
        "startedAt": r["started_at"], "finishedAt": r["finished_at"],
        "changedDocs": r["changed_docs"], "totalDocs": r["total_docs"],
        "diffSummary": (r["error"] or f"变更 {r['changed_docs']} / 共 {r['total_docs']} 文档"),
        "current": bool(r["version_dir"] and r["version_dir"] == cur)} for r in rows]}


@router.post("/kb/publish")
def publish_create(body: dict = Body(default=None)):
    if _rate_limit_hit("kb.publish", 20, 10):
        return _err("RATE_LIMITED", _ERROR_MESSAGES["RATE_LIMITED"], 429, {"retryAfterSec": 10})
    if store.get_state("store_down", False):
        _audit(_current_account(), "kb.publish.start", "store", {"storeDown": True}, result="degraded")
        return _err("DEPENDENCY_DOWN", _ERROR_MESSAGES["DEPENDENCY_DOWN"], 503,
                    {"dependency": "权威正本图"})
    body = body or {}
    mode = body.get("mode", "incremental")
    if mode not in ("incremental", "full"):
        return _err("VALIDATION_FAILED", "重建模式仅支持「增量」或「全量」", 422)
    operator = body.get("operator") or _current_account()
    run = _new_publish_run(body.get("trigger", "manual"), mode, operator)
    _audit(operator, "kb.publish.start", run["runId"], {"mode": mode})
    return run


@router.get("/kb/publish/run/{runId}")
def publish_run_detail(runId: str):
    row = store.q1("SELECT * FROM kb_publish_run WHERE run_id=?", (runId,))
    if not row:
        return _err("NOT_FOUND", "重建作业不存在", 404)
    _advance_run(runId)
    row = store.q1("SELECT * FROM kb_publish_run WHERE run_id=?", (runId,)) or row
    detail = _run_stage(runId) if row["status"] == "running" else {
        "stage": "已完成", "stageIndex": len(_PUBLISH_STAGES), "elapsedMs": row["duration_ms"],
        "logs": [f"[{s[0]}] 完成" for s in _PUBLISH_STAGES]}
    changed = [{"docKey": m["doc_key"], "title": m["title"]}
               for m in store.q("SELECT doc_key,title FROM kb_publish_manifest LIMIT 6")]
    return {"runId": row["run_id"], "trigger": row["trigger"], "mode": row["mode"],
            "status": row["status"], "startedAt": row["started_at"], "finishedAt": row["finished_at"],
            "versionDir": row["version_dir"], "changedDocs": row["changed_docs"],
            "totalDocs": row["total_docs"], "durationMs": row["duration_ms"], "error": row["error"],
            "changedDocumentList": changed, **detail}


@router.post("/kb/publish/rollback")
def publish_rollback(body: dict = Body(default=None)):
    body = body or {}
    vdir = (body or {}).get("versionDir")
    if not vdir:
        return _err("VALIDATION_FAILED", "版本目录必填", 422)
    exists = store.q1("SELECT run_id FROM kb_publish_run WHERE version_dir=?", (vdir,))
    if not exists:
        return _err("NOT_FOUND", f"版本 {vdir} 不存在", 404)
    store.set_state("publish_current", vdir)
    _audit(_current_account(), "kb.rollback", vdir, {"ok": True})
    return {"ok": True, "currentVersion": vdir}


@router.get("/kb/publish/manifest")
def publish_manifest():
    rows = store.q("SELECT * FROM kb_publish_manifest ORDER BY doc_id")
    return {"manifest": [{"docId": r["doc_id"], "docKey": r["doc_key"], "title": r["title"],
                          "contentHash": r["content_hash"], "status": r["status"],
                          "builtAt": r["built_at"]} for r in rows]}


@router.post("/kb/qa")
def kb_qa(body: dict = Body(default=None)):
    if _rate_limit_hit("kb.qa", 5, 10):
        return _err("RATE_LIMITED", _ERROR_MESSAGES["RATE_LIMITED"], 429, {"retryAfterSec": 10})
    body = body or {}
    query = (body.get("query") or "").strip()
    types = body.get("types") or []
    if not query:
        return _env({"answer": "", "citations": [], "refused": True,
                     "refusedReason": "查询为空，无法作答"}, "none")
    cites, hits = [], []
    for m in store.q("SELECT doc_key,title FROM kb_publish_manifest LIMIT 40"):
        if query in (m["title"] or "") or query in (m["doc_key"] or ""):
            hits.append(m)
    for t in store.q("SELECT task_id,org_name,topic FROM selfcheck_task LIMIT 20"):
        if query in (t["topic"] or "") or query in (t["org_name"] or ""):
            hits.append({"doc_key": t["task_id"], "title": f"{t['org_name']}·{t['topic']}"})
    for i, h in enumerate(hits[:5]):
        cites.append({"text": h["title"], "type": "knowledge", "source": "db",
                      "ref": h.get("doc_key"), "span": f"片段{i+1}"})
    if not cites:
        return _env({"answer": "知识库中未检索到直接依据，建议补充查询关键词或先发起重建。",
                     "citations": [], "refused": True,
                     "refusedReason": "无匹配引用（拒答以避免臆造）"}, "db")
    if types and not any(c["type"] in types for c in cites):
        return _env({"answer": "所选类型下无匹配内容。", "citations": [], "refused": True,
                     "refusedReason": "type 过滤后无结果"}, "db")
    answer = f"依据 {len(cites)} 条引用，围绕「{query}」的要点：{cites[0]['text']}。"
    return _env({"answer": answer, "citations": cites, "refused": False}, "db")


@router.get("/kb/category-mapping")
def category_mapping():
    rows = store.q("SELECT * FROM kb_category_mapping ORDER BY sort")
    return {"mappings": [{"mappingId": r["mapping_id"], "typePrefix": r["type_prefix"],
                          "category": r["category"]} for r in rows]}


@router.put("/kb/category-mapping")
def category_mapping_put(body: dict = Body(default=None)):
    body = body or {}
    items = body.get("items") or []
    if not isinstance(items, list):
        return _err("VALIDATION_FAILED", "待采集明细需为数组", 422)
    store.x("DELETE FROM kb_category_mapping")
    for i, it in enumerate(items):
        store.insert("kb_category_mapping", {"mapping_id": f"km-{i}",
                                             "type_prefix": it.get("typePrefix", ""),
                                             "category": it.get("category", ""), "sort": i})
    _audit(_current_account(), "kb.category.update", "category_mapping", {"n": len(items)})
    return {"ok": True, "saved": len(items)}


@router.get("/kb/collect/tasks")
def collect_tasks(status: str = ""):
    rows = store.q("SELECT * FROM collect_task" + (" WHERE status=?" if status else "") +
                   " ORDER BY collected_at DESC", (status,) if status else ())
    return {"tasks": [{"collectId": r["collect_id"], "title": r["title"], "sourceUrl": r["source_url"],
                       "issuingBody": r["issuing_body"], "contentType": r["content_type"],
                       "publishDate": r["publish_date"], "status": r["status"],
                       "credibility": r["credibility"], "proposalId": r["proposal_id"]} for r in rows]}


@router.post("/kb/collect/run")
def collect_run():
    new_ids = []
    for i in range(2):
        cid = "ct-live-" + uuid.uuid4().hex[:6]
        store.insert("collect_task", {
            "collect_id": cid, "title": f"演示采集：监管动态 #{i+1}",
            "source_url": f"https://example.gov.cn/live-{cid}", "issuing_body": "国家金融监督管理总局",
            "content_type": "notice", "publish_date": _now()[:10], "collected_at": _now(),
            "status": "pending", "credibility": round(0.6 + i * 0.1, 2), "proposal_id": None})
        new_ids.append(cid)
    _audit(_current_account(), "kb.collect.run", "collect", {"new": len(new_ids)})
    return {"ok": True, "newCollectIds": new_ids}


@router.post("/kb/collect/{collect_id}/decision")
def collect_decision(collect_id: str, body: dict = Body(default=None)):
    body = body or {}
    row = store.q1("SELECT * FROM collect_task WHERE collect_id=?", (collect_id,))
    if not row:
        return _err("NOT_FOUND", "采集任务不存在", 404)
    decision = body.get("decision")
    if decision not in ("approve", "reject"):
        return _err("VALIDATION_FAILED", "决策仅支持「通过」或「驳回」", 422)
    reviewer = body.get("reviewer") or _current_account()
    pid = None
    if decision == "approve":
        pid = "p-live-" + uuid.uuid4().hex[:6]
        store.insert("knowledge_proposal", {
            "proposal_id": pid, "category": "RA2", "title": f"采集回流：{row['title']}",
            "payload_json": json.dumps({"sourceUrl": row["source_url"]}, ensure_ascii=False),
            "raised_from": "collect", "status": "pending", "raised_by": reviewer,
            "reviewed_by": None, "review_comment": body.get("comment"),
            "created_at": _now(), "decided_at": None})
    store.x("UPDATE collect_task SET status=?,proposal_id=? WHERE collect_id=?",
            ("approved" if decision == "approve" else "rejected", pid, collect_id))
    _audit(reviewer, "kb.collect.decision", collect_id, {"decision": decision})
    return {"ok": True, "collectId": collect_id, "status": "approved" if decision == "approve" else "rejected",
            "proposalId": pid}


# ===========================================================================
# 5.3 行业档案与清单
# ===========================================================================
@router.get("/selfcheck/industries")
def selfcheck_industries():
    rows = store.q("SELECT * FROM industry_profile")
    out = []
    for r in rows:
        out.append({"profileId": r["profile_id"], "industry": r["industry"], "name": r["name"],
                    "orgTypes": _jloads(r["org_types_json"], []),
                    "lines": _jloads(r["lines_json"], {}).get("lines", []),
                    "sensitiveTypes": _jloads(r["sensitive_types_json"], {}).get("sensitiveTypes", []),
                    "docFocus": _jloads(r["doc_focus_json"], {}).get("docFocus", []),
                    "reportTemplate": r["report_template"]})
    return {"industries": out}


@router.get("/selfcheck/templates")
def selfcheck_templates(industry: str = "bank", line: str = ""):
    prof = store.q1("SELECT * FROM industry_profile WHERE industry=?", (industry,))
    if not prof:
        return _env(None, "none")
    lines = _jloads(prof["lines_json"], {}).get("lines", [])
    doc_focus = _jloads(prof["doc_focus_json"], {}).get("docFocus", [])
    primary = doc_focus[-1] if industry == "insurance" and len(doc_focus) > 1 else (doc_focus[0] if doc_focus else "jg24")
    checks = seed._real_checks("jg93" if industry == "insurance" else "jg24")
    groups = []
    for i, ln in enumerate(lines):
        items = []
        for j in range(3):
            k = (i * 3 + j) % len(checks)
            c = checks[k]
            items.append({"checkCode": c["checkCode"], "title": c["title"],
                          "priority": c["priority"], "domain": c["domain"],
                          "sixDim": {"elements": 3, "metrics": 2, "evidence": 2, "method": 2,
                                     "interview": 1, "related": 1}})
        groups.append({"line": ln["code"], "lineLabel": ln["label"], "items": items})
    content = {"industry": industry, "name": prof["name"], "snapshotVersion": "v3.0",
               "generatedAt": _now(), "docFocus": doc_focus, "primaryDoc": primary,
               "groups": groups}
    return _env(content, "db", version="v3.0")


# ===========================================================================
# 5.4 自查任务与单项
# ===========================================================================
@router.post("/selfcheck/tasks")
def selfcheck_task_create(body: dict = Body(default=None)):
    body = body or {}
    if not body.get("industry") or not body.get("orgName"):
        return _err("VALIDATION_FAILED", "行业与机构名称必填", 422)
    tid = "t-live-" + uuid.uuid4().hex[:8]
    assignees = body.get("assignees") or []
    store.insert("selfcheck_task", {
        "task_id": tid, "plan_id": body.get("planId") or "plan-live", "industry": body["industry"],
        "org_name": body["orgName"], "org_type": body.get("orgType") or "分行",
        "org_node_id": body.get("orgNodeId") or "bank-east", "cycle": body.get("cycle") or "2026Q4",
        "owner": body.get("owner") or _current_account(),
        "assignees_json": json.dumps(assignees, ensure_ascii=False),
        "scope_json": json.dumps(body.get("scope") or {}, ensure_ascii=False),
        "stage": body.get("stage") or "季度自查", "topic": body.get("topic") or "数据安全专项",
        "status": "draft", "progress": 0, "risk_level": "medium",
        "start_date": body.get("startDate") or _now()[:10], "end_date": body.get("endDate") or "",
        "created_by": _current_account(), "created_at": _now(), "updated_at": _now()})
    _audit(_current_account(), "selfcheck.create", tid, {"industry": body["industry"]})
    return {"taskId": tid, "status": "draft"}


@router.get("/selfcheck/tasks")
def selfcheck_task_list(account: str = "", industry: str = "", status: str = ""):
    tasks = _visible_tasks(account or None)
    if industry:
        tasks = [t for t in tasks if t["industry"] == industry]
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    out = []
    for t in tasks:
        out.append({"taskId": t["task_id"], "industry": t["industry"], "orgName": t["org_name"],
                    "orgType": t["org_type"], "orgNodeId": t["org_node_id"], "cycle": t["cycle"],
                    "owner": t["owner"], "stage": t["stage"], "topic": t["topic"],
                    "status": t["status"], "progress": t["progress"], "riskLevel": t["risk_level"],
                    "startDate": t["start_date"], "endDate": t["end_date"]})
    return {"tasks": out, "visibleAccount": account or _current_account(), "total": len(out)}


@router.get("/selfcheck/tasks/{task_id}")
def selfcheck_task_detail(task_id: str):
    t = _task_or_404(task_id)
    if not t:
        return _err("NOT_FOUND", "自查任务不存在", 404)
    sections = store.q("SELECT * FROM selfcheck_section WHERE task_id=? ORDER BY section_id", (task_id,))
    items = store.q("SELECT status FROM selfcheck_item_state WHERE task_id=?", (task_id,))
    n = len(items)
    by = {}
    for it in items:
        by[it["status"]] = by.get(it["status"], 0) + 1
    verdict = _verdict(by, n)
    return {"taskId": t["task_id"], "industry": t["industry"], "orgName": t["org_name"],
            "orgNodeId": t["org_node_id"], "cycle": t["cycle"], "owner": t["owner"],
            "assignees": _jloads(t["assignees_json"], []), "scope": _jloads(t["scope_json"], {}),
            "stage": t["stage"], "topic": t["topic"], "status": t["status"],
            "progress": t["progress"], "riskLevel": t["risk_level"],
            "startDate": t["start_date"], "endDate": t["end_date"],
            "sections": [{"sectionId": s["section_id"], "lineCode": s["line_code"],
                          "lineLabel": s["line_label"], "owner": s["owner"],
                          "dueDate": s["due_date"], "status": s["status"],
                          "progress": s["progress"]} for s in sections],
            "itemCount": n, "verdict": verdict}


def _verdict(by: dict, total: int) -> dict:
    """按最差项聚合：任一「不符合」→ 不符合；否则「部分符合」→ 部分符合；全部符合 → 符合。"""
    fail = by.get("fail", 0)
    partial = by.get("partial", 0)
    supplement = by.get("supplement", 0)
    if fail:
        result = "fail"
    elif partial:
        result = "partial"
    elif supplement:
        result = "supplement"
    else:
        result = "pass"
    score = round((by.get("pass", 0) / total) * 100, 1) if total else 0.0
    risk = "high" if fail >= 3 else ("medium" if fail or partial else "low")
    return {"result": result, "score": score, "riskLevel": risk,
            "basis": {"pass": by.get("pass", 0), "partial": partial, "fail": fail,
                      "supplement": supplement, "total": total}}


@router.get("/selfcheck/tasks/{task_id}/items")
def selfcheck_items(task_id: str):
    t = _task_or_404(task_id)
    if not t:
        return _err("NOT_FOUND", "自查任务不存在", 404)
    rows = store.q("SELECT * FROM selfcheck_item_state WHERE task_id=? ORDER BY check_code", (task_id,))
    return {"taskId": task_id, "items": [{
        "checkCode": r["check_code"], "lineCode": r["line_code"], "applicability": r["applicability"],
        "status": r["status"], "owner": r["owner"], "hasPolicy": bool(r["has_policy"]),
        "evidence": _jloads(r["evidence_json"], []), "actualValue": r["actual_value"],
        "note": r["note"], "updatedAt": r["updated_at"]} for r in rows]}


@router.post("/selfcheck/tasks/{task_id}/items")
def selfcheck_item_update(task_id: str, body: dict = Body(default=None)):
    body = body or {}
    t = _task_or_404(task_id)
    if not t:
        return _err("NOT_FOUND", "自查任务不存在", 404)
    code = body.get("checkCode")
    if not code:
        return _err("VALIDATION_FAILED", "检查项编号必填", 422)
    sid = f"it-{task_id}-{code}"
    exists = store.q1("SELECT * FROM selfcheck_item_state WHERE state_id=?", (sid,))
    actor = body.get("actor") or _current_account()
    store.insert("selfcheck_item_state", {
        "state_id": sid, "task_id": task_id, "check_code": code,
        "line_code": body.get("lineCode") or (exists["line_code"] if exists else ""),
        "applicability": body.get("applicability") or "applicable",
        "status": body.get("status") or (exists["status"] if exists else "supplement"),
        "owner": actor, "has_policy": 1 if body.get("hasPolicy") else 0,
        "evidence_json": json.dumps(body.get("evidence") or [], ensure_ascii=False),
        "actual_value": body.get("actualValue"), "note": body.get("note"), "updated_at": _now()})
    _audit(actor, "selfcheck.item.update", f"{task_id}#{code}", {"status": body.get("status")})
    return {"ok": True, "taskId": task_id, "checkCode": code, "stateId": sid}


@router.get("/selfcheck/tasks/{task_id}/verdict")
def selfcheck_verdict(task_id: str):
    t = _task_or_404(task_id)
    if not t:
        return _err("NOT_FOUND", "自查任务不存在", 404)
    items = store.q("SELECT status FROM selfcheck_item_state WHERE task_id=?", (task_id,))
    by = {}
    for it in items:
        by[it["status"]] = by.get(it["status"], 0) + 1
    v = _verdict(by, len(items))
    return {"taskId": task_id, **v, "taskLevel": t["status"], "computedAt": _now()}


@router.post("/selfcheck/tasks/{task_id}/items/{check_code}/ai-match")
def selfcheck_ai_match(task_id: str, check_code: str, body: dict = Body(default=None)):
    t = _task_or_404(task_id)
    if not t:
        return _err("NOT_FOUND", "自查任务不存在", 404)
    h = int(uuid.uuid5(uuid.NAMESPACE_URL, f"{task_id}-{check_code}").hex[:6], 16)
    confidence = round(0.35 + (h % 60) / 100, 2)
    segments = [{"text": f"与检查项 {check_code} 相关的制度条款（演示片段 1）", "source": "db", "score": confidence},
                {"text": "现场抽查记录（演示片段 2）", "source": "db", "score": round(confidence - 0.12, 2)}]
    if confidence >= 0.8:
        suggestion = "pass"
    elif confidence >= 0.6:
        suggestion = "partial"
    elif confidence >= 0.45:
        suggestion = "supplement"
    else:
        suggestion = "fail"
    routed = confidence < 0.6 or t["risk_level"] == "high"
    if routed:
        store.insert("hitl_candidate", {
            "candidate_id": "h-live-" + uuid.uuid4().hex[:6], "source_type": "ai_match",
            "source_id": task_id, "check_code": check_code,
            "title": f"AI 匹配低置信度：{check_code}", "confidence": confidence,
            "status": "pending", "assigned_reviewer": None,
            "payload_json": json.dumps({"suggestion": suggestion}, ensure_ascii=False),
            "created_at": _now(), "decided_at": None})
    reason = "置信度低于 0.6 或任务高风险，已转人工确认" if routed else "置信度达标，采纳 AI 建议"
    _audit(_current_account(), "selfcheck.ai_match", f"{task_id}#{check_code}",
           {"confidence": confidence, "routedToHuman": routed})
    return {"checkCode": check_code, "segments": segments, "confidence": confidence,
            "suggestion": suggestion, "routedToHuman": routed, "reason": reason}


# ===========================================================================
# 5.5 责任分配
# ===========================================================================
def _assignment_preview(task_id: str, body: dict) -> dict:
    t = _task_or_404(task_id) or {}
    industry = t.get("industry", "bank")
    scope = body.get("scope") or {}
    titles = {c["checkCode"]: c["title"]
              for c in seed._real_checks("jg93" if industry == "insurance" else "jg24")}
    # 分配范围 = 本任务清单（selfcheck_item_state）；无清单时回退该行业全部检查项
    rows = store.q("SELECT check_code FROM selfcheck_item_state WHERE task_id=? ORDER BY check_code",
                   (task_id,))
    if rows:
        checks = [{"checkCode": r["check_code"], "title": titles.get(r["check_code"], r["check_code"])}
                  for r in rows]
    else:
        checks = seed._real_checks("jg93" if industry == "insurance" else "jg24")
    rules = store.q("SELECT * FROM check_assignment_rule WHERE industry=? AND status='active'",
                    (industry,))
    # 同一检查项可能命中多条规则 → 冲突演示（需人工裁定）
    rules_by_code: dict = {}
    for r in rules:
        rules_by_code.setdefault(r["check_code"], []).append(r)
    mapping, unmatched, conflicts = [], [], []
    for c in checks:
        code = c["checkCode"]
        rs = rules_by_code.get(code)
        if not rs:
            unmatched.append(code)
            continue
        if len(rs) > 1:
            conflicts.append({"checkCode": code, "reason": "同一检查项命中多条规则，需人工裁定"})
        r = rs[0]
        dept = store.q1("SELECT name FROM org_node WHERE node_id=?", (r["target_dept_id"],))
        pos = store.q1("SELECT name FROM org_position WHERE position_id=?", (r["target_position_id"],))
        mapping.append({"checkCode": code, "title": c["title"], "deptId": r["target_dept_id"],
                        "deptName": dept["name"] if dept else r["target_dept_id"],
                        "positionId": r["target_position_id"],
                        "positionName": pos["name"] if pos else r["target_position_id"],
                        "roleId": r["target_role_id"], "source": "rule"})
    total = len(checks) or 1
    coverage = round(len(mapping) / total * 100, 1)
    return {"coverage": coverage, "matchedCount": len(mapping), "unmatched": unmatched,
            "conflicts": conflicts, "mapping": mapping}


@router.get("/selfcheck/tasks/{task_id}/assignments")
def assignments_get(task_id: str):
    t = _task_or_404(task_id)
    if not t:
        return _err("NOT_FOUND", "自查任务不存在", 404)
    batches = store.q("SELECT * FROM assignment_batch WHERE task_id=? ORDER BY confirmed_at DESC",
                      (task_id,))
    cur = batches[0] if batches else None
    mapping = _jloads(cur["mapping_snapshot_json"], []) if cur else []
    overrides = store.q("SELECT * FROM check_assignment_override WHERE batch_id=?",
                        (cur["batch_id"],)) if cur else []
    for m in mapping:
        for o in overrides:
            if o["check_code"] == m["checkCode"]:
                m["source"] = "override"
                m["deptId"] = o["target_dept_id"]
                m["positionId"] = o["target_position_id"]
                m["roleId"] = o["target_role_id"]
    return {"taskId": task_id, "current": {"batchId": cur["batch_id"], "coverage": cur["coverage"],
                                           "ruleVersion": cur["rule_version"],
                                           "confirmedBy": cur["confirmed_by"],
                                           "confirmedAt": cur["confirmed_at"]} if cur else None,
            "mapping": mapping,
            "history": [{"batchId": b["batch_id"], "ruleVersion": b["rule_version"],
                         "coverage": b["coverage"], "confirmedBy": b["confirmed_by"],
                         "confirmedAt": b["confirmed_at"]} for b in batches]}


@router.post("/selfcheck/tasks/{task_id}/assignments/preview")
def assignments_preview(task_id: str, body: dict = Body(default=None)):
    if not _task_or_404(task_id):
        return _err("NOT_FOUND", "自查任务不存在", 404)
    return _assignment_preview(task_id, body or {})


@router.patch("/selfcheck/tasks/{task_id}/assignments/{check_code}")
def assignments_override(task_id: str, check_code: str, body: dict = Body(default=None)):
    body = body or {}
    if not _task_or_404(task_id):
        return _err("NOT_FOUND", "自查任务不存在", 404)
    cur = store.q1("SELECT * FROM assignment_batch WHERE task_id=? ORDER BY confirmed_at DESC LIMIT 1",
                   (task_id,))
    if not cur:
        return _err("NOT_FOUND", "该任务暂无分配批次，请先预览并下发", 404)
    oid = "ov-" + uuid.uuid4().hex[:6]
    actor = body.get("actor") or _current_account()
    store.insert("check_assignment_override", {
        "override_id": oid, "batch_id": cur["batch_id"], "check_code": check_code,
        "target_dept_id": body.get("targetDeptId"), "target_position_id": body.get("targetPositionId"),
        "target_role_id": body.get("targetRoleId"), "reason": body.get("reason"),
        "changed_by": actor, "changed_at": _now()})
    _audit(actor, "assignment.override", f"{task_id}#{check_code}", {"reason": body.get("reason")})
    return {"ok": True, "overrideId": oid, "checkCode": check_code, "batchId": cur["batch_id"]}


@router.post("/selfcheck/tasks/{task_id}/assignments/dispatch")
def assignments_dispatch(task_id: str, body: dict = Body(default=None)):
    body = body or {}
    if not _task_or_404(task_id):
        return _err("NOT_FOUND", "自查任务不存在", 404)
    confirmed_by = body.get("confirmedBy") or _current_account()
    preview = _assignment_preview(task_id, body)
    batch_id = "batch-" + task_id + "-" + uuid.uuid4().hex[:6]
    store.insert("assignment_batch", {
        "batch_id": batch_id, "task_id": task_id, "rule_version": 1,
        "scope_json": json.dumps(body.get("scope") or {}, ensure_ascii=False),
        "mapping_snapshot_json": json.dumps(preview["mapping"], ensure_ascii=False),
        "unmatched_json": json.dumps(preview["unmatched"], ensure_ascii=False),
        "conflicts_json": json.dumps(preview["conflicts"], ensure_ascii=False),
        "coverage": preview["coverage"], "confirmed_by": confirmed_by, "confirmed_at": _now()})
    _audit(confirmed_by, "assignment.dispatch", batch_id, {"coverage": preview["coverage"]})
    return {"batchId": batch_id, "ruleVersion": 1, "mappingSnapshot": preview["mapping"],
            "dispatchedAt": _now()}


# ===========================================================================
# 5.6 证据与签署
# ===========================================================================
@router.get("/selfcheck/tasks/{task_id}/evidence")
def evidence_list(task_id: str):
    if not _task_or_404(task_id):
        return _err("NOT_FOUND", "自查任务不存在", 404)
    rows = store.q("SELECT * FROM inspection_evidence WHERE task_id=? ORDER BY uploaded_at DESC",
                   (task_id,))
    return {"taskId": task_id, "evidence": [{
        "evidenceId": r["evidence_id"], "checkCode": r["check_code"], "fileName": r["file_name"],
        "storageRef": r["storage_ref"], "fileHash": r["file_hash"], "size": r["size"],
        "uploadedBy": r["uploaded_by"], "uploadedAt": r["uploaded_at"]} for r in rows]}


@router.post("/selfcheck/tasks/{task_id}/evidence")
def evidence_create(task_id: str, body: dict = Body(default=None)):
    body = body or {}
    if not _task_or_404(task_id):
        return _err("NOT_FOUND", "自查任务不存在", 404)
    if not body.get("fileName"):
        return _err("VALIDATION_FAILED", "文件名必填", 422)
    run = store.q1("SELECT run_id FROM inspection_run WHERE task_id=? ORDER BY ran_at DESC LIMIT 1",
                   (task_id,))
    eid = "ev-" + uuid.uuid4().hex[:8]
    uploader = body.get("uploadedBy") or _current_account()
    store.insert("inspection_evidence", {
        "evidence_id": eid, "run_id": run["run_id"] if run else None, "task_id": task_id,
        "check_code": body.get("checkCode"), "file_name": body["fileName"],
        "storage_ref": f"demo://evidence/{eid}", "file_hash": body.get("contentHash") or uuid.uuid4().hex,
        "size": body.get("size") or 0, "uploaded_by": uploader, "uploaded_at": _now()})
    _audit(uploader, "evidence.upload", eid, {"fileName": body["fileName"], "size": body.get("size")})
    return {"ok": True, "evidenceId": eid, "taskId": task_id}


@router.get("/selfcheck/tasks/{task_id}/signoff")
def signoff_list(task_id: str):
    if not _task_or_404(task_id):
        return _err("NOT_FOUND", "自查任务不存在", 404)
    rows = store.q("SELECT * FROM inspection_signoff WHERE task_id=? ORDER BY signed_at DESC",
                   (task_id,))
    latest = store.q1("SELECT submitter_account FROM inspection_run WHERE task_id=? "
                      "ORDER BY ran_at DESC LIMIT 1", (task_id,))
    return {"taskId": task_id, "submitterAccount": latest["submitter_account"] if latest else None,
            "signoffs": [{"signoffId": r["signoff_id"], "signer": r["signer"],
                          "signerName": r["signer_name"], "role": r["role"],
                          "decision": r["decision"], "comment": r["comment"],
                          "signedAt": r["signed_at"]} for r in rows]}


@router.post("/selfcheck/tasks/{task_id}/signoff")
def signoff_create(task_id: str, body: dict = Body(default=None)):
    guard = _require_auth()
    if guard:
        return guard
    body = body or {}
    if not _task_or_404(task_id):
        return _err("NOT_FOUND", "自查任务不存在", 404)
    account = body.get("account") or _current_account()
    run = store.q1("SELECT run_id,submitter_account FROM inspection_run WHERE task_id=? "
                   "ORDER BY ran_at DESC LIMIT 1", (task_id,))
    # ---- 职责分离强校验：经办与复核不得为同一账号 ----
    if run and run["submitter_account"] and account == run["submitter_account"]:
        _audit(account, "selfcheck.signoff", task_id, {"decision": body.get("decision")},
               result="forbidden_sod")
        return _err("FORBIDDEN", "职责分离校验不通过：经办与复核不得为同一账号", 403,
                    {"submitter": run["submitter_account"], "signer": account})
    sid = "so-" + uuid.uuid4().hex[:8]
    row = _account_row(account) or {}
    store.insert("inspection_signoff", {
        "signoff_id": sid, "run_id": run["run_id"] if run else None, "task_id": task_id,
        "signer": account, "signer_name": row.get("display_name") or account,
        "role": body.get("role") or (_roles_of(account) or [None])[0],
        "decision": body.get("decision") or "approve", "comment": body.get("comment"),
        "signed_at": _now()})
    _audit(account, "selfcheck.signoff", task_id, {"decision": body.get("decision")})
    return {"ok": True, "signoffId": sid, "taskId": task_id, "decision": body.get("decision") or "approve"}


# ===========================================================================
# 5.7 问题 / 整改 / 复检
# ===========================================================================
@router.get("/selfcheck/tasks/{task_id}/findings")
def findings_list(task_id: str):
    if not _task_or_404(task_id):
        return _err("NOT_FOUND", "自查任务不存在", 404)
    rows = store.q("SELECT * FROM selfcheck_finding WHERE task_id=? ORDER BY created_at DESC",
                   (task_id,))
    out = []
    for f in rows:
        rems = store.q("SELECT * FROM remediation_task WHERE finding_id=?", (f["finding_id"],))
        out.append({"findingId": f["finding_id"], "checkCode": f["check_code"],
                    "severity": f["severity"], "problem": f["problem"], "rootCause": f["root_cause"],
                    "status": f["status"], "owner": f["owner"], "dueDate": f["due_date"],
                    "sourceRunId": f["source_run_id"],
                    "remediations": [{"remediationId": r["remediation_id"], "owner": r["owner"],
                                      "dueDate": r["due_date"], "measures": r["measures"],
                                      "status": r["status"], "evidenceRef": r["evidence_ref"]}
                                     for r in rems]})
    return {"taskId": task_id, "findings": out}


@router.post("/selfcheck/tasks/{task_id}/findings")
def findings_create(task_id: str, body: dict = Body(default=None)):
    body = body or {}
    if not _task_or_404(task_id):
        return _err("NOT_FOUND", "自查任务不存在", 404)
    if not body.get("checkCode") or not body.get("problem"):
        return _err("VALIDATION_FAILED", "检查项编号与问题描述必填", 422)
    fid = "f-" + uuid.uuid4().hex[:8]
    actor = body.get("actor") or _current_account()
    store.insert("selfcheck_finding", {
        "finding_id": fid, "task_id": task_id, "check_code": body["checkCode"],
        "severity": body.get("severity") or "medium", "problem": body["problem"],
        "root_cause": body.get("rootCause"), "status": "open",
        "owner": body.get("owner") or actor, "due_date": body.get("dueDate"),
        "created_at": _now(), "source_run_id": body.get("sourceRunId")})
    _audit(actor, "finding.create", fid, {"severity": body.get("severity")})
    return {"ok": True, "findingId": fid, "taskId": task_id}


@router.post("/selfcheck/tasks/{task_id}/remediations")
def remediations_create(task_id: str, body: dict = Body(default=None)):
    body = body or {}
    if not _task_or_404(task_id):
        return _err("NOT_FOUND", "自查任务不存在", 404)
    fid = body.get("findingId")
    if not fid:
        return _err("VALIDATION_FAILED", "问题编号必填", 422)
    if not store.q1("SELECT finding_id FROM selfcheck_finding WHERE finding_id=?", (fid,)):
        return _err("NOT_FOUND", "问题不存在", 404)
    rid = "rem-" + uuid.uuid4().hex[:8]
    actor = body.get("actor") or _current_account()
    store.insert("remediation_task", {
        "remediation_id": rid, "finding_id": fid, "task_id": task_id,
        "owner": body.get("owner") or actor, "due_date": body.get("dueDate"),
        "measures": body.get("measures"), "status": "assigned", "evidence_ref": None,
        "created_at": _now(), "updated_at": _now()})
    store.x("UPDATE selfcheck_finding SET status='assigned' WHERE finding_id=?", (fid,))
    _audit(actor, "remediation.create", rid, {"findingId": fid})
    return {"ok": True, "remediationId": rid, "findingId": fid}


@router.patch("/selfcheck/remediations/{remediation_id}")
def remediations_update(remediation_id: str, body: dict = Body(default=None)):
    body = body or {}
    row = store.q1("SELECT * FROM remediation_task WHERE remediation_id=?", (remediation_id,))
    if not row:
        return _err("NOT_FOUND", "整改任务不存在", 404)
    actor = body.get("actor") or _current_account()
    store.x("UPDATE remediation_task SET status=?,evidence_ref=?,updated_at=? WHERE remediation_id=?",
            (body.get("status") or row["status"], body.get("evidenceRef") or row["evidence_ref"],
             _now(), remediation_id))
    _audit(actor, "remediation.update", remediation_id, {"status": body.get("status")})
    return {"ok": True, "remediationId": remediation_id, "status": body.get("status") or row["status"]}


@router.post("/selfcheck/tasks/{task_id}/recheck")
def recheck_run(task_id: str):
    t = _task_or_404(task_id)
    if not t:
        return _err("NOT_FOUND", "自查任务不存在", 404)
    run_id = f"run-{task_id}-recheck"
    store.insert("inspection_run", {
        "run_id": run_id, "plan_id": t["plan_id"], "task_id": task_id, "run_type": "recheck",
        "inspected_target": t["org_name"], "inspector": _current_account(),
        "assignees_json": t["assignees_json"], "ran_at": _now(),
        "submitter_account": _current_account()})
    checks = store.q("SELECT check_code FROM selfcheck_item_state WHERE task_id=? ORDER BY check_code",
                     (task_id,))
    for c in checks:
        store.insert("check_result", {
            "result_id": f"res-{run_id}-{c['check_code']}", "run_id": run_id,
            "check_code": c["check_code"], "elements_json": json.dumps([{"element": "制度", "ok": True}]),
            "metrics_json": json.dumps([{"metric": "覆盖率", "value": "92%"}]),
            "result": "pass", "judge_source": "symbolic", "confidence": 0.9,
            "why_json": json.dumps(["复检：整改后要素齐备"])})
    _audit(_current_account(), "recheck.run", task_id, {"runId": run_id})
    return {"runId": run_id, "runType": "recheck", "taskId": task_id}


@router.get("/selfcheck/tasks/{task_id}/recheck/diff")
def recheck_diff(task_id: str):
    if not _task_or_404(task_id):
        return _err("NOT_FOUND", "自查任务不存在", 404)
    runs = store.q("SELECT * FROM inspection_run WHERE task_id=? ORDER BY ran_at", (task_id,))
    if len(runs) < 2:
        return _err("NOT_FOUND", "该任务暂无复检运行，无法比对", 404)
    before_run, after_run = runs[0], runs[-1]

    def results(run_id):
        return {r["check_code"]: r for r in
                store.q("SELECT * FROM check_result WHERE run_id=?", (run_id,))}
    b, a = results(before_run["run_id"]), results(after_run["run_id"])
    def tally(d):
        c = {"pass": 0, "partial": 0, "fail": 0, "supplement": 0}
        for r in d.values():
            c[r["result"]] = c.get(r["result"], 0) + 1
        return c
    tb, ta = tally(b), tally(a)
    score_b = round(tb["pass"] / max(1, len(b)) * 100, 1)
    score_a = round(ta["pass"] / max(1, len(a)) * 100, 1)
    items = []
    for code in sorted(set(b) | set(a)):
        rb = b.get(code, {}).get("result")
        ra = a.get(code, {}).get("result")
        items.append({"checkCode": code, "title": f"检查项 {code}", "before": rb, "after": ra,
                      "changed": rb != ra, "evidenceAdded": ra is not None and rb != ra})
    return {"taskId": task_id,
            "taskLevel": {"before": {"pass": score_b, **tb}, "after": {"pass": score_a, **ta},
                          "delta": {"pass": round(score_a - score_b, 1)}},
            "beforeRun": before_run["run_id"], "afterRun": after_run["run_id"],
            "items": items}


# ===========================================================================
# 5.8 报告与看板
# ===========================================================================
# 报告五项结构（白皮书第 3 章 / 附录 B）：问题清单 / 依据条款 / 责任归属 /
# 证据缺口 / 下一步建议。逐项由本任务的检查项与责任映射派生，仅做只读聚合。
_REPORT_BASES = [
    {"requirement": "数据处理、导出与接口返回应按数据分级结果实施相应控制",
     "criterion": "以「控制是否在数据实际被使用的链路上生效」为判定口径，不以页面展示为准"},
    {"requirement": "各处理环节应明确发起、审批、复核、问责岗位",
     "criterion": "以能否指名到岗、能否逐项举证为判定口径"},
    {"requirement": "发现的问题应形成台账、整改时限与复测验收记录",
     "criterion": "以台账、时限、复测验收与根因分析记录是否完整为判定口径"},
]


def _report_five_items(t: dict, items: list) -> dict:
    src = "jg93" if t["industry"] == "insurance" else "jg24"
    titles = {c["checkCode"]: c["title"] for c in seed._real_checks(src)}
    batch = store.q("SELECT * FROM assignment_batch WHERE task_id=? "
                    "ORDER BY confirmed_at DESC LIMIT 1", (t["task_id"],))
    mapping = _jloads(batch[0]["mapping_snapshot_json"], []) if batch else []
    if not mapping:  # 尚未下发：回退为按分配规则预览出的责任映射
        mapping = _assignment_preview(t["task_id"], {}).get("mapping", [])
    by_code = {m["checkCode"]: m for m in mapping}
    lead = t.get("org_name") or "牵头部门"

    problems, ownership, ev_gaps = [], [], []
    for it in items:
        code = it["check_code"]
        title = titles.get(code, code)
        if it["status"] != "pass":
            problems.append({"code": code, "text": f"{title}（{code}）未完全符合，需逐项对照"})
            m = by_code.get(code) or {}
            dept = m.get("deptName") or _lookup_name("org_node", "node_id", m.get("deptId"))
            pos = m.get("positionName") or _lookup_name("org_position", "position_id", m.get("positionId"))
            ownership.append({"code": code, "title": title,
                              "initiator": pos or "责任岗位（未映射）",
                              "approver": (dept + "负责人") if dept else "责任部门负责人",
                              "reviewer": lead, "accountable": dept or "责任部门（未映射）"})
        if not _jloads(it["evidence_json"], []):
            ev_gaps.append({"code": code, "text": f"{title}（{code}）的举证材料尚未归集，无法逐项举证"})

    return {
        "problems": problems,
        "bases": _REPORT_BASES,
        "ownership": ownership,
        "evidenceGaps": ev_gaps,
        "nextSteps": [
            {"priority": "优先级一", "text": "补一份应用与业务层台账，把导出、接口、角色权限、报表与应用日志逐项对账"},
            {"priority": "优先级二", "text": "按对账结果补齐审批记录与核对记录，形成下一轮的起点"},
        ],
        "note": "由牵头部门认领，复核确认后作为机构自己的结论；报告固定由五项构成，逐项对应一项用途。",
    }


def task_report(task_id: str, fmt: str = "json") -> dict:
    t = _task_or_404(task_id)
    if not t:
        return {}
    items = store.q("SELECT * FROM selfcheck_item_state WHERE task_id=? ORDER BY check_code", (task_id,))
    rows = []
    by = {}
    for it in items:
        by[it["status"]] = by.get(it["status"], 0) + 1
        gaps = [] if it["status"] == "pass" else [f"{it['check_code']} 未完全符合"]
        rows.append({"checkCode": it["check_code"], "title": it["check_code"],
                     "result": it["status"],
                     "priority": "P1",
                     "evidenceComplete": bool(_jloads(it["evidence_json"], [])),
                     "contentAdequate": bool(it["has_policy"]),
                     "compliant": it["status"] == "pass",
                     "gaps": gaps,
                     "remediation": "见整改任务" if it["status"] in ("fail", "partial") else "",
                     "expertOpinion": _jloads(it["evidence_json"], []) and "证据齐备" or "建议补充"})
    v = _verdict(by, len(items))
    return {"meta": {"taskId": task_id, "orgName": t["org_name"], "industry": t["industry"],
                     "cycle": t["cycle"], "generatedAt": _now(), "template": "行业版报告",
                     "dataLabel": "脱敏样例"},
            "summary": {"verdict": v["result"], "score": v["score"], "riskLevel": v["riskLevel"],
                        "total": len(items), "pass": by.get("pass", 0)},
            "items": rows,
            "five": _report_five_items(t, items),
            "gapSummary": {"fail": by.get("fail", 0), "partial": by.get("partial", 0),
                           "supplement": by.get("supplement", 0)},
            "expertOpinions": ["演示：建议优先整改高风险项", "演示：闭环后复核归档"],
            "footer": "本报告为脱敏样例，示例机构、系统与岗位均为代号化内容；报告固定由五项构成："
                      "问题清单、依据条款、责任归属、证据缺口、下一步建议。"}


@router.get("/selfcheck/tasks/{task_id}/report")
def task_report_ep(task_id: str, fmt: str = "json"):
    rep = task_report(task_id, fmt)
    if not rep:
        return _err("NOT_FOUND", "自查任务不存在", 404)
    return rep


@router.get("/selfcheck/tasks/{task_id}/report/md")
def task_report_md(task_id: str):
    rep = task_report(task_id)
    if not rep:
        return _err("NOT_FOUND", "自查任务不存在", 404)
    m = rep["meta"]
    five = rep.get("five") or {}
    lines = [f"# {m['orgName']} · {m['cycle']} 安全自查报告", "",
             f"- 行业：{m['industry']}", f"- 生成时间：{m['generatedAt']}",
             f"- 数据标识：{m['dataLabel']}", "",
             f"## 结论", f"- 判定：**{rep['summary']['verdict']}**",
             f"- 得分：{rep['summary']['score']}", f"- 风险：{rep['summary']['riskLevel']}", "",
             "## 一、问题清单"]
    for p in five.get("problems", []):
        lines.append(f"- {p['text']}")
    if not five.get("problems"):
        lines.append("- 无")
    lines += ["", "## 二、依据条款", "", "| 监管要求 | 判定口径 |", "|---|---|"]
    for b in five.get("bases", []):
        lines.append(f"| {b['requirement']} | {b['criterion']} |")
    lines += ["", "## 三、责任归属", "", "| 环节 | 发起 | 审批 | 复核 | 问责 |", "|---|---|---|---|---|"]
    for o in five.get("ownership", []):
        lines.append(f"| {o['title']}（{o['code']}） | {o['initiator']} | {o['approver']} | "
                     f"{o['reviewer']} | {o['accountable']} |")
    lines += ["", "## 四、证据缺口"]
    for g in five.get("evidenceGaps", []):
        lines.append(f"- {g['text']}")
    if not five.get("evidenceGaps"):
        lines.append("- 无")
    lines += ["", "## 五、下一步建议"]
    for n in five.get("nextSteps", []):
        lines.append(f"- {n['priority']}：{n['text']}")
    if five.get("note"):
        lines += ["", f"> {five['note']}"]
    lines += ["", "## 附：逐条检查项明细", "",
              "| 检查项 | 结论 | 证据完整 | 内容完备 |", "|---|---|---|---|"]
    for it in rep["items"]:
        lines.append(f"| {it['checkCode']} | {it['result']} | "
                     f"{'是' if it['evidenceComplete'] else '否'} | "
                     f"{'是' if it['contentAdequate'] else '否'} |")
    lines += ["", f"> {rep['footer']}"]
    return PlainTextResponse("\n".join(lines), media_type="text/markdown; charset=utf-8")


@router.get("/selfcheck/progress")
def selfcheck_progress():
    tasks = store.q("SELECT * FROM selfcheck_task ORDER BY created_at DESC")
    kpis = {"tasks": len(tasks),
            "inProgress": sum(1 for t in tasks if t["status"] == "in_progress"),
            "closed": sum(1 for t in tasks if t["status"] == "closed"),
            "draft": sum(1 for t in tasks if t["status"] == "draft"),
            "avgProgress": round(sum(t["progress"] for t in tasks) / max(1, len(tasks)), 1)}
    by_line, by_risk, by_result = {}, {}, {}
    for t in tasks:
        by_risk[t["risk_level"]] = by_risk.get(t["risk_level"], 0) + 1
    for s in store.q("SELECT line_label,progress FROM selfcheck_section"):
        d = by_line.setdefault(s["line_label"], {"progress": 0, "n": 0})
        d["progress"] += s["progress"]
        d["n"] += 1
    by_line = {k: round(v["progress"] / max(1, v["n"]), 1) for k, v in by_line.items()}
    for r in store.q("SELECT result FROM check_result"):
        by_result[r["result"]] = by_result.get(r["result"], 0) + 1
    trend = [{"cycle": c, "closed": sum(1 for t in tasks if t["cycle"] == c and t["status"] == "closed"),
              "total": sum(1 for t in tasks if t["cycle"] == c)}
             for c in sorted({t["cycle"] for t in tasks})]
    return {"tasks": [{"taskId": t["task_id"], "orgName": t["org_name"], "cycle": t["cycle"],
                       "status": t["status"], "progress": t["progress"], "riskLevel": t["risk_level"],
                       "topic": t["topic"]} for t in tasks],
            "kpis": kpis, "byLine": [{"line": k, "progress": v} for k, v in by_line.items()],
            "byRisk": [{"risk": k, "count": v} for k, v in by_risk.items()],
            "byResult": [{"result": k, "count": v} for k, v in by_result.items()],
            "trend": trend}


# ===========================================================================
# 5.9 回流 / 审核 / 人工确认
# ===========================================================================
@router.get("/review/proposals")
def proposals_list(status: str = "", category: str = ""):
    sql = "SELECT * FROM knowledge_proposal"
    args, where = [], []
    if status:
        where.append("status=?"); args.append(status)
    if category:
        where.append("category=?"); args.append(category)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC"
    rows = store.q(sql, args)
    return {"proposals": [{"proposalId": r["proposal_id"], "category": r["category"],
                           "title": r["title"], "status": r["status"], "raisedFrom": r["raised_from"],
                           "raisedBy": r["raised_by"], "reviewedBy": r["reviewed_by"],
                           "createdAt": r["created_at"], "decidedAt": r["decided_at"]} for r in rows]}


@router.get("/review/proposals/{proposal_id}")
def proposal_detail(proposal_id: str):
    r = store.q1("SELECT * FROM knowledge_proposal WHERE proposal_id=?", (proposal_id,))
    if not r:
        return _err("NOT_FOUND", "提案不存在", 404)
    return {"proposalId": r["proposal_id"], "category": r["category"], "title": r["title"],
            "payload": _jloads(r["payload_json"], {}), "raisedFrom": r["raised_from"],
            "status": r["status"], "raisedBy": r["raised_by"], "reviewedBy": r["reviewed_by"],
            "reviewComment": r["review_comment"], "createdAt": r["created_at"],
            "decidedAt": r["decided_at"]}


@router.post("/review/proposals")
def proposal_create(body: dict = Body(default=None)):
    body = body or {}
    if not body.get("category") or not body.get("title"):
        return _err("VALIDATION_FAILED", "类目与标题必填", 422)
    if body["category"] not in PROPOSAL_CATEGORIES:
        return _err("VALIDATION_FAILED", "类目必须为 14 类回流类目之一", 422,
                    {"supported": PROPOSAL_CATEGORIES})
    pid = "p-" + uuid.uuid4().hex[:8]
    raiser = body.get("raisedBy") or _current_account()
    store.insert("knowledge_proposal", {
        "proposal_id": pid, "category": body["category"], "title": body["title"],
        "payload_json": json.dumps(body.get("payload") or {}, ensure_ascii=False),
        "raised_from": body.get("raisedFrom") or "manual", "status": "pending",
        "raised_by": raiser, "reviewed_by": None, "review_comment": None,
        "created_at": _now(), "decided_at": None})
    _audit(raiser, "proposal.create", pid, {"category": body["category"]})
    return {"ok": True, "proposalId": pid, "status": "pending"}


@router.post("/review/proposals/{proposal_id}/decision")
def proposal_decision(proposal_id: str, body: dict = Body(default=None)):
    guard = _require_auth()
    if guard:
        return guard
    body = body or {}
    r = store.q1("SELECT * FROM knowledge_proposal WHERE proposal_id=?", (proposal_id,))
    if not r:
        return _err("NOT_FOUND", "提案不存在", 404)
    reviewer = body.get("reviewer") or _current_account()
    decision = body.get("decision")
    if decision not in ("approve", "reject", "return"):
        return _err("VALIDATION_FAILED", "决策仅支持「通过」「驳回」或「退回」", 422)
    # ---- 职责分离：审核人不得为提出人 ----
    if reviewer == r["raised_by"]:
        _audit(reviewer, "review.decision", proposal_id, {"decision": decision}, result="forbidden_sod")
        return _err("FORBIDDEN", "职责分离校验不通过：经办与复核不得为同一账号", 403,
                    {"raisedBy": r["raised_by"], "reviewer": reviewer})
    new_status = {"approve": "approved", "reject": "rejected", "return": "pending"}[decision]
    store.x("UPDATE knowledge_proposal SET status=?,reviewed_by=?,review_comment=?,decided_at=? "
            "WHERE proposal_id=?",
            (new_status, reviewer, body.get("comment"), _now(), proposal_id))
    _audit(reviewer, "review.decision", proposal_id, {"decision": decision})
    return {"ok": True, "proposalId": proposal_id, "status": new_status, "reviewedBy": reviewer}


@router.get("/hitl/candidates")
def hitl_list(status: str = ""):
    rows = store.q("SELECT * FROM hitl_candidate" + (" WHERE status=?" if status else "") +
                   " ORDER BY created_at DESC", (status,) if status else ())
    return {"candidates": [{"candidateId": r["candidate_id"], "sourceType": r["source_type"],
                            "sourceId": r["source_id"], "checkCode": r["check_code"],
                            "title": r["title"], "confidence": r["confidence"], "status": r["status"],
                            "assignedReviewer": r["assigned_reviewer"],
                            "payload": _jloads(r["payload_json"], {}),
                            "createdAt": r["created_at"], "decidedAt": r["decided_at"]} for r in rows]}


@router.post("/hitl/candidates/{candidate_id}/decision")
def hitl_decision(candidate_id: str, body: dict = Body(default=None)):
    body = body or {}
    r = store.q1("SELECT * FROM hitl_candidate WHERE candidate_id=?", (candidate_id,))
    if not r:
        return _err("NOT_FOUND", "候选不存在", 404)
    decision = body.get("decision")
    if decision not in ("approve", "reject"):
        return _err("VALIDATION_FAILED", "决策仅支持「通过」或「驳回」", 422)
    reviewer = body.get("reviewer") or _current_account()
    store.x("UPDATE hitl_candidate SET status=?,assigned_reviewer=?,decided_at=? WHERE candidate_id=?",
            ("approved" if decision == "approve" else "rejected", reviewer, _now(), candidate_id))
    _audit(reviewer, "hitl.decide", candidate_id, {"decision": decision})
    return {"ok": True, "candidateId": candidate_id,
            "status": "approved" if decision == "approve" else "rejected"}


# ===========================================================================
# 5.10 权限与组织 / 认证
# ===========================================================================
@router.get("/admin/org-nodes")
def org_nodes(industry: str = ""):
    rows = store.q("SELECT * FROM org_node" + (" WHERE industry=?" if industry else "") +
                   " ORDER BY sort", (industry,) if industry else ())
    nodes = {r["node_id"]: {"node_id": r["node_id"], "parentId": r["parent_id"], "level": r["level"],
                            "name": r["name"], "kind": r["kind"], "lineCode": r["line_code"],
                            "industry": r["industry"], "children": []} for r in rows}
    roots = []
    for r in rows:
        n = nodes[r["node_id"]]
        if r["parent_id"] and r["parent_id"] in nodes:
            nodes[r["parent_id"]]["children"].append(n)
        else:
            roots.append(n)
    return {"tree": roots, "total": len(rows)}


@router.post("/admin/org-nodes")
def org_node_create(body: dict = Body(default=None)):
    body = body or {}
    if not body.get("name"):
        return _err("VALIDATION_FAILED", "名称必填", 422)
    nid = "node-" + uuid.uuid4().hex[:6]
    store.insert("org_node", {
        "node_id": nid, "parent_id": body.get("parentId"), "level": body.get("level") or "L3",
        "name": body["name"], "kind": body.get("kind") or "outlet",
        "line_code": body.get("lineCode"), "industry": body.get("industry") or "bank",
        "sort": body.get("sort") or 999})
    _audit(_current_account(), "admin.org.create", nid, {"name": body["name"]})
    return {"ok": True, "nodeId": nid}


@router.get("/admin/org-positions")
def org_positions():
    rows = store.q("SELECT p.*,n.name AS node_name FROM org_position p "
                   "LEFT JOIN org_node n ON n.node_id=p.org_node_id ORDER BY p.position_id")
    return {"positions": [{"positionId": r["position_id"], "orgNodeId": r["org_node_id"],
                           "orgNodeName": r["node_name"], "name": r["name"],
                           "status": r["status"]} for r in rows]}


@router.get("/admin/roles")
def roles_list():
    rows = store.q("SELECT * FROM role_def ORDER BY role_id")
    return {"roles": [{"roleId": r["role_id"], "name": r["name"],
                       "capabilities": _jloads(r["capabilities_json"], []),
                       "scope": _jloads(r["scope_json"], {}), "levelVisibility": r["level_visibility"],
                       "status": r["status"], "builtin": bool(r["builtin"]),
                       "updatedBy": r["updated_by"], "updatedAt": r["updated_at"]} for r in rows]}


@router.post("/admin/roles")
def role_upsert(body: dict = Body(default=None)):
    body = body or {}
    if not body.get("roleId"):
        return _err("VALIDATION_FAILED", "角色编号必填", 422)
    rid = body["roleId"]
    exists = store.q1("SELECT * FROM role_def WHERE role_id=?", (rid,))
    actor = body.get("actor") or _current_account()
    store.insert("role_def", {
        "role_id": rid, "name": body.get("name") or (exists["name"] if exists else rid),
        "capabilities_json": json.dumps(body.get("capabilities") or
                                        (_jloads(exists["capabilities_json"], []) if exists else []),
                                        ensure_ascii=False),
        "scope_json": json.dumps(body.get("scope") or
                                 (_jloads(exists["scope_json"], {}) if exists else {}), ensure_ascii=False),
        "level_visibility": body.get("levelVisibility") or (exists["level_visibility"] if exists else "L1"),
        "status": body.get("status") or (exists["status"] if exists else "active"),
        "builtin": body.get("builtin") if body.get("builtin") is not None else (exists["builtin"] if exists else 0),
        "updated_by": actor, "updated_at": _now()})
    _audit(actor, "role.update", rid, {"new": not exists})
    return {"ok": True, "roleId": rid}


@router.get("/admin/role-bindings")
def role_bindings():
    rows = store.q("SELECT rb.*, u.display_name AS disp, n.name AS node_name, p.name AS pos_name, "
                   "r.level_visibility AS lv FROM role_binding rb "
                   "LEFT JOIN user_account u ON u.account=rb.account "
                   "LEFT JOIN org_node n ON n.node_id=rb.org_node_id "
                   "LEFT JOIN org_position p ON p.position_id=rb.position_id "
                   "LEFT JOIN role_def r ON r.role_id=rb.role_id ORDER BY rb.binding_id")
    return {"bindings": [{"bindingId": r["binding_id"], "account": r["account"],
                          "displayName": r["disp"], "roleId": r["role_id"],
                          "orgNodeId": r["org_node_id"], "orgNodeName": r["node_name"],
                          "positionId": r["position_id"], "positionName": r["pos_name"],
                          "levelVisibility": r["lv"]} for r in rows]}


@router.post("/admin/role-bindings")
def role_binding_create(body: dict = Body(default=None)):
    body = body or {}
    if not body.get("account") or not body.get("roleId"):
        return _err("VALIDATION_FAILED", "账号与角色编号必填", 422)
    bid = "rb-" + uuid.uuid4().hex[:6]
    store.insert("role_binding", {
        "binding_id": bid, "account": body["account"], "role_id": body["roleId"],
        "org_node_id": body.get("orgNodeId"), "position_id": body.get("positionId")})
    _audit(_current_account(), "role.binding.create", bid, body)
    return {"ok": True, "bindingId": bid}


@router.get("/admin/capabilities")
def capabilities():
    return {"capabilities": [{"key": k, "label": v} for k, v in seed.CAPABILITY_LABELS.items()],
            "matrix": seed.ROLE_CAPS}


@router.get("/admin/users")
def users_list():
    guard = _require_auth()
    if guard:
        return guard
    rows = store.q("SELECT * FROM user_account ORDER BY account")
    out = []
    for r in rows:
        node = store.q1("SELECT name FROM org_node WHERE node_id=?", (r["org_node_id"],)) if r["org_node_id"] else None
        out.append({"account": r["account"], "displayName": r["display_name"],
                    "orgNodeId": r["org_node_id"], "orgNodeName": node["name"] if node else None,
                    "positionId": r["position_id"], "roles": _roles_of(r["account"]),
                    "status": r["status"], "isBootstrap": bool(r["is_bootstrap"]),
                    "lastLoginAt": r["last_login_at"]})
    return {"users": out}


@router.post("/admin/users/{account}/status")
def user_status(account: str, body: dict = Body(default=None)):
    body = body or {}
    status = body.get("status")
    if status not in ("active", "disabled"):
        return _err("VALIDATION_FAILED", "状态仅支持「启用」或「停用」", 422)
    if not _account_row(account):
        return _err("NOT_FOUND", "账号不存在", 404)
    store.x("UPDATE user_account SET status=? WHERE account=?", (status, account))
    _audit(_current_account(), "admin.user.status", account, {"status": status})
    return {"ok": True, "account": account, "status": status, "effective": "即时失效"}


@router.get("/admin/check-assignment-rules")
def assignment_rules():
    rows = store.q("SELECT * FROM check_assignment_rule ORDER BY rule_id")
    version = max([r["version"] for r in rows], default=1)
    return {"rules": [{"ruleId": r["rule_id"], "checkCode": r["check_code"], "industry": r["industry"],
                       "orgScope": _jloads(r["org_scope_json"], {}), "stage": r["stage"],
                       "topic": r["topic"], "targetDeptId": r["target_dept_id"],
                       "targetPositionId": r["target_position_id"], "targetRoleId": r["target_role_id"],
                       "version": r["version"], "status": r["status"]} for r in rows],
            "version": version}


@router.put("/admin/check-assignment-rules")
def assignment_rules_update(body: dict = Body(default=None)):
    body = body or {}
    rules = body.get("rules")
    if not isinstance(rules, list):
        return _err("VALIDATION_FAILED", "分配规则需为数组", 422)
    cur = store.q("SELECT MAX(version) AS v FROM check_assignment_rule")
    new_ver = ((cur[0]["v"] if cur and cur[0]["v"] else 1) or 1) + 1
    store.x("DELETE FROM check_assignment_rule")
    for i, r in enumerate(rules):
        store.insert("check_assignment_rule", {
            "rule_id": r.get("ruleId") or f"rule-{i}", "check_code": r.get("checkCode"),
            "industry": r.get("industry") or "bank",
            "org_scope_json": json.dumps(r.get("orgScope") or {}, ensure_ascii=False),
            "stage": r.get("stage"), "topic": r.get("topic"),
            "target_dept_id": r.get("targetDeptId"), "target_position_id": r.get("targetPositionId"),
            "target_role_id": r.get("targetRoleId"), "version": new_ver,
            "status": r.get("status") or "active"})
    _audit(_current_account(), "admin.rule.update", "assignment_rules", {"version": new_ver})
    return {"ok": True, "version": new_ver, "count": len(rules)}


@router.get("/admin/audit")
def audit_query(from_: str = Query(default="", alias="from"), to: str = "", actor: str = "",
                action: str = "", limit: int = 100):
    guard = _require_auth()
    if guard:
        return guard
    sql = "SELECT * FROM audit_log"
    args, where = [], []
    if from_:
        where.append("ts>=?"); args.append(from_)
    if to:
        where.append("ts<=?"); args.append(to)
    if actor:
        where.append("actor=?"); args.append(actor)
    if action:
        where.append("action LIKE ?"); args.append(f"%{action}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(limit, 500)))
    rows = store.q(sql, args)
    return {"audit": [{"id": r["id"], "ts": r["ts"], "actor": r["actor"],
                       "actorName": r["actor_name"], "action": r["action"], "target": r["target"],
                       "params": _jloads(r["params_json"], {}), "result": r["result"],
                       "prevHash": r["prev_hash"], "hash": r["hash"]} for r in rows],
            "chainOk": store.audit_chain_ok()}


@router.get("/admin/audit/export")
def audit_export(limit: int = 500):
    rows = store.q("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (max(1, min(limit, 2000)),))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["序号", "时间", "操作者账号", "操作者", "动作", "目标", "结果", "前序哈希", "当前哈希"])
    for r in rows:
        w.writerow([r["id"], r["ts"], r["actor"], r["actor_name"], r["action"], r["target"],
                    r["result"], r["prev_hash"], r["hash"]])
    _audit(_current_account(), "admin.audit.export", "audit_log", {"rows": len(rows)})
    return PlainTextResponse(buf.getvalue(), media_type="text/csv; charset=utf-8")


@router.get("/admin/doc-registry")
def doc_registry_list():
    rows = store.q("SELECT * FROM doc_registry ORDER BY doc_key")
    return {"docs": [{"docKey": r["doc_key"], "docNo": r["doc_no"], "title": r["title"],
                      "issuingBody": r["issuing_body"], "effectiveDate": r["effective_date"],
                      "structureProfile": _jloads(r["structure_profile_json"], {}),
                      "status": r["status"], "checkCount": r["check_count"],
                      "registeredBy": r["registered_by"], "registeredAt": r["registered_at"]}
                     for r in rows]}


@router.post("/admin/doc-registry")
def doc_registry_create(body: dict = Body(default=None)):
    body = body or {}
    if not body.get("docKey") or not body.get("docNo"):
        return _err("VALIDATION_FAILED", "文号键与文号必填", 422)
    by = _current_account()
    store.insert("doc_registry", {
        "doc_key": body["docKey"], "doc_no": body["docNo"], "title": body.get("title"),
        "issuing_body": body.get("issuingBody"), "effective_date": body.get("effectiveDate"),
        "structure_profile_json": json.dumps(body.get("structureProfile") or {}, ensure_ascii=False),
        "status": "pending", "check_count": 0, "registered_by": by, "registered_at": _now()})
    _audit(by, "admin.doc.register", body["docKey"], {"step": 1})
    return {"ok": True, "docKey": body["docKey"], "status": "pending",
            "nextSteps": ["② 上传样例并由适配器推断结构", "③ PATCH 确认结构映射 → status=active"]}


@router.patch("/admin/doc-registry/{doc_key}")
def doc_registry_confirm(doc_key: str, body: dict = Body(default=None)):
    body = body or {}
    r = store.q1("SELECT * FROM doc_registry WHERE doc_key=?", (doc_key,))
    if not r:
        return _err("NOT_FOUND", "文号不存在", 404)
    store.x("UPDATE doc_registry SET status='active',structure_profile_json=? WHERE doc_key=?",
            (json.dumps(body.get("structureProfile") or _jloads(r["structure_profile_json"], {}),
                        ensure_ascii=False), doc_key))
    _audit(_current_account(), "admin.doc.confirm", doc_key, {"step": 3})
    return {"ok": True, "docKey": doc_key, "status": "active"}


@router.get("/admin/gov-dashboard")
def gov_dashboard():
    audit_total = (store.q1("SELECT COUNT(*) AS n FROM audit_log") or {}).get("n", 0)
    by_result = {}
    for r in store.q("SELECT result,COUNT(*) AS n FROM audit_log GROUP BY result"):
        by_result[r["result"]] = r["n"]
    runs = store.q("SELECT status,COUNT(*) AS n,duration_ms FROM kb_publish_run GROUP BY status")
    degraded = (store.q1("SELECT COUNT(*) AS n FROM plugin_registry WHERE status!='在线'") or {}).get("n", 0)
    inv = (store.q1("SELECT COUNT(*) AS n FROM plugin_invocation") or {}).get("n", 0)
    manifest = store.q("SELECT status,COUNT(*) AS n FROM kb_publish_manifest GROUP BY status")
    return {"audit": {"total": audit_total, "byResult": by_result, "chainOk": store.audit_chain_ok()},
            "rebuild": {"runs": [{"status": r["status"], "count": r["n"]} for r in runs],
                        "currentVersion": store.get_state("publish_current", "-")},
            "sourceHitRate": 0.83,
            "degradeRate": round(degraded / max(1, degraded + 4), 3),
            "mcpCalls": inv,
            "knowledgeQuality": {"manifest": [{"status": m["status"], "count": m["n"]} for m in manifest],
                                 "score": 0.91}}


@router.get("/auth/session")
def auth_session():
    return _session_info(_current_account())


@router.post("/auth/login")
def auth_login(body: dict = Body(default=None)):
    body = body or {}
    account = body.get("account")
    if not account:
        return _err("VALIDATION_FAILED", "account 必填", 422)
    row = _account_row(account)
    if not row:
        return _err("NOT_FOUND", "账号不存在", 404)
    if row["status"] != "active":
        return _err("FORBIDDEN", "账号已停用", 403)
    store.set_state("current_account", account)
    store.x("UPDATE user_account SET last_login_at=? WHERE account=?", (_now(), account))
    _audit(account, "auth.login", "session", {"idp": row["idp_type"]})
    return {"ok": True, "session": _session_info(account)}


@router.post("/auth/logout")
def auth_logout():
    acc = _current_account()
    store.set_state("current_account", "")
    _audit(acc, "auth.logout", "session", {})
    return {"ok": True}


# ===========================================================================
# 5.11 场景与插件
# ===========================================================================
@router.get("/scenario-packs")
def scenario_packs():
    rows = store.q("SELECT * FROM scenario_pack ORDER BY pack_id")
    return {"packs": [{"packId": r["pack_id"], "name": r["name"], "industry": r["industry"],
                       "status": r["status"], "scope": _jloads(r["scope_json"], {}),
                       "reportTemplate": r["report_template"], "builtin": bool(r["builtin"])}
                      for r in rows]}


@router.post("/scenario-packs")
def scenario_pack_create(body: dict = Body(default=None)):
    body = body or {}
    if not body.get("name"):
        return _err("VALIDATION_FAILED", "名称必填", 422)
    pid = "sp-" + uuid.uuid4().hex[:6]
    store.insert("scenario_pack", {
        "pack_id": pid, "name": body["name"], "industry": body.get("industry") or "bank",
        "status": "active", "scope_json": json.dumps(body.get("scope") or {}, ensure_ascii=False),
        "mapping_json": json.dumps(body.get("mapping") or {}, ensure_ascii=False),
        "form_json": json.dumps(body.get("form") or {}, ensure_ascii=False),
        "report_template": body.get("reportTemplate") or "custom-v1", "builtin": 0})
    _audit(_current_account(), "scenario.create", pid, {"name": body["name"]})
    return {"ok": True, "packId": pid}


@router.get("/scenario-packs/{pack_id}")
def scenario_pack_detail(pack_id: str):
    r = store.q1("SELECT * FROM scenario_pack WHERE pack_id=?", (pack_id,))
    if not r:
        return _err("NOT_FOUND", "场景包不存在", 404)
    return {"packId": r["pack_id"], "name": r["name"], "industry": r["industry"],
            "status": r["status"], "builtin": bool(r["builtin"]),
            "fiveTuple": {"knowledge": _jloads(r["scope_json"], {}),
                          "checks": "jg24", "jobs": "selfcheck", "verdict": "三色判定",
                          "output": r["report_template"]},
            "form": _jloads(r["form_json"], {}), "reportTemplate": r["report_template"]}


@router.post("/scenario-packs/{pack_id}/launch")
def scenario_pack_launch(pack_id: str):
    r = store.q1("SELECT * FROM scenario_pack WHERE pack_id=?", (pack_id,))
    if not r:
        return _err("NOT_FOUND", "场景包不存在", 404)
    tid = "t-launch-" + uuid.uuid4().hex[:6]
    store.insert("selfcheck_task", {
        "task_id": tid, "plan_id": "plan-launch", "industry": r["industry"],
        "org_name": "演示机构（场景启动）", "org_type": "分行", "org_node_id": "bank-east",
        "cycle": "2026Q4", "owner": _current_account(), "assignees_json": "[]",
        "scope_json": r["scope_json"], "stage": "场景启动", "topic": r["name"],
        "status": "draft", "progress": 0, "risk_level": "medium",
        "start_date": _now()[:10], "end_date": "", "created_by": _current_account(),
        "created_at": _now(), "updated_at": _now()})
    _audit(_current_account(), "scenario.launch", pack_id, {"taskId": tid})
    return {"ok": True, "packId": pack_id, "launchedTaskId": tid}


@router.get("/plugins")
def plugins_list():
    rows = store.q("SELECT * FROM plugin_registry ORDER BY plugin_id")
    return {"plugins": [{"pluginId": r["plugin_id"], "name": r["name"], "capability": r["capability"],
                         "ioSchema": _jloads(r["io_schema_json"], {}), "authType": r["auth_type"],
                         "rateLimit": r["rate_limit"], "status": r["status"], "vendor": r["vendor"],
                         "latencyMs": r["latency_ms"]} for r in rows]}


@router.post("/plugins/{plugin_id}/invoke")
def plugin_invoke(plugin_id: str, body: dict = Body(default=None)):
    body = body or {}
    r = store.q1("SELECT * FROM plugin_registry WHERE plugin_id=?", (plugin_id,))
    if not r:
        return _err("NOT_FOUND", "插件不存在", 404)
    iid = "inv-" + uuid.uuid4().hex[:6]
    actor = body.get("actor") or _current_account()
    if r["status"] != "在线":
        # 离线/降级插件：转人工，不阻断
        store.insert("plugin_invocation", {
            "invocation_id": iid, "plugin_id": plugin_id, "task_id": body.get("taskId"),
            "input_ref": json.dumps(body.get("input") or {}, ensure_ascii=False)[:200],
            "output_ref": None, "status": "degraded", "latency_ms": r["latency_ms"],
            "actor": actor, "created_at": _now()})
        _audit(actor, "plugin.invoke", plugin_id, {"status": "degraded"}, result="degraded")
        return {"invocationId": iid, "status": "degraded",
                "output": {"message": "插件不可用，已降级为人工处理", "routedToHuman": True},
                "latencyMs": r["latency_ms"]}
    output = {"capability": r["capability"], "result": "ok",
              "input": body.get("input")}
    store.insert("plugin_invocation", {
        "invocation_id": iid, "plugin_id": plugin_id, "task_id": body.get("taskId"),
        "input_ref": json.dumps(body.get("input") or {}, ensure_ascii=False)[:200],
        "output_ref": json.dumps(output, ensure_ascii=False)[:200], "status": "ok",
        "latency_ms": r["latency_ms"], "actor": actor, "created_at": _now()})
    _audit(actor, "plugin.invoke", plugin_id, {"status": "ok"})
    return {"invocationId": iid, "status": "ok", "output": output, "latencyMs": r["latency_ms"]}


@router.get("/plugins/invocations")
def plugin_invocations(limit: int = 50):
    rows = store.q("SELECT * FROM plugin_invocation ORDER BY created_at DESC LIMIT ?",
                   (max(1, min(limit, 200)),))
    return {"invocations": [{"invocationId": r["invocation_id"], "pluginId": r["plugin_id"],
                             "taskId": r["task_id"], "status": r["status"],
                             "latencyMs": r["latency_ms"], "actor": r["actor"],
                             "createdAt": r["created_at"]} for r in rows]}


# ===========================================================================
# 5.12 现状诊断 / 应用与业务层台账 / 逐类问题处置
# ---------------------------------------------------------------------------
# 第三轮原型扩展（差距对照表 §5.1 P0）：静态只读演示数据，来自 seed 常量。
# 口径：合成脱敏、全代号化；无机构真名、无绝对路径、无条目数承诺；不改动底座
# 与运行台账。返回直接业务 JSON（与 /demo/*、/scenario-packs 等一致）。
# ===========================================================================
_RESULT_LABEL = {"aligned": "已对上", "partial": "部分对上", "missing": "未对上"}


@router.get("/diagnosis/dimensions")
def diagnosis_dimensions():
    dims = seed.DIAG_DIMENSIONS
    stat = {"yes": 0, "partial": 0, "no": 0}
    for d in dims:
        for a in d.get("answers", []):
            stat[a.get("state")] = stat.get(a.get("state"), 0) + 1
    return {"questions": seed.DIAG_QUESTIONS, "dimensions": dims,
            "summary": {"dimensions": len(dims), "questions": len(seed.DIAG_QUESTIONS),
                        "answers": stat},
            "fetchedAt": _now()}


@router.get("/ledger/rows")
def ledger_rows():
    rows = seed.LEDGER_ROWS
    summary = {"total": len(rows), "aligned": 0, "partial": 0, "missing": 0}
    for r in rows:
        summary[r["result"]] = summary.get(r["result"], 0) + 1
    return {"rows": rows, "summary": summary, "fetchedAt": _now()}


@router.get("/issues/classes")
def issues_classes():
    classes = seed.ISSUE_CLASSES
    layers: dict = {}
    for c in classes:
        layers[c["layer"]] = layers.get(c["layer"], 0) + 1
    return {"classes": classes, "summary": {"total": len(classes), "layers": layers},
            "fetchedAt": _now()}


# ===========================================================================
# 5.13 三层治理框架 / 知识底座五层架构
# ---------------------------------------------------------------------------
# 第四轮原型扩展（里程碑 M1-1 治理与架构）：静态只读演示数据，来自 seed 常量。
# 口径：合成脱敏、全代号化；无机构真名、无绝对路径、无条目数承诺、无厂商与产品
# 名称；不改动底座与运行台账。返回直接业务 JSON。
# ===========================================================================
@router.get("/governance/frame")
def governance_frame():
    domains = seed.GOV_FRAME_DOMAINS
    chain = seed.GOV_FRAME_CHAIN
    return {"domains": domains, "chain": chain,
            "summary": {"domains": len(domains), "chain": len(chain)},
            "fetchedAt": _now()}


@router.get("/architecture/layers")
def architecture_layers():
    layers = seed.ARCH_LAYERS
    return {"layers": layers, "summary": {"layers": len(layers)},
            "fetchedAt": _now()}
