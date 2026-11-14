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
     "desc": "展示取数来源与知识问答的统一结果"},
    {"step": 1, "title": "知识发布：变更感知 → 增量重建 → 质量校验 → 整版发布",
     "desc": "发起一次增量重建，观察分阶段推进与版本目录切换"},
    {"step": 2, "title": "行业建档：行业档案与行业化清单",
     "desc": "按行业/条线取清单模板（含清单版本与六维摘要）"},
    {"step": 3, "title": "自查任务：下发与单项登记",
     "desc": "创建任务，登记四录入项（制度/证据/实际值/备注）"},
    {"step": 4, "title": "责任分配：预览 → 覆盖 → 下发",
     "desc": "条款责任自动映射 + 未匹配/冲突 + 版本批次"},
    {"step": 5, "title": "证据与签署：职责分离（经办 ≠ 复核）",
     "desc": "上传证据元数据 + 签核；同一账号签核将被拒绝（职责分离拦截）"},
    {"step": 6, "title": "判定与报告：三色判定 + 计分依据 + 报告导出",
     "desc": "按最差项聚合出结论，导出行业版报告"},
    {"step": 7, "title": "整改与复检：问题整改 → 复跑同一检查项 → 前后对比",
     "desc": "登记整改并复检，导出复检前后对比"},
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


@router.post("/selfcheck/industries")
def selfcheck_industry_create(body: dict = Body(default=None)):
    body = body or {}
    industry = (body.get("industry") or "").strip()
    name = (body.get("name") or "").strip()
    if not industry or not name:
        return _err("VALIDATION_FAILED", "行业代码与行业名称必填", 422)
    if store.q1("SELECT profile_id FROM industry_profile WHERE industry=?", (industry,)):
        return _err("VALIDATION_FAILED", f"行业代码「{industry}」已存在，请更换", 422)
    pid = "ip-live-" + uuid.uuid4().hex[:6]
    lines = [x for x in (body.get("lines") or []) if isinstance(x, dict) and x.get("code")]
    store.insert("industry_profile", {
        "profile_id": pid, "industry": industry, "name": name,
        "org_types_json": json.dumps(body.get("orgTypes") or [], ensure_ascii=False),
        "lines_json": json.dumps({"lines": lines}, ensure_ascii=False),
        "sensitive_types_json": json.dumps({"sensitiveTypes": body.get("sensitiveTypes") or []},
                                           ensure_ascii=False),
        "doc_focus_json": json.dumps({"docFocus": body.get("docFocus") or []}, ensure_ascii=False),
        "report_template": body.get("reportTemplate") or "标准自查报告模板"})
    _audit(_current_account(), "selfcheck.industry.create", pid,
           {"industry": industry, "name": name, "lines": len(lines)})
    return {"profileId": pid, "industry": industry, "name": name, "lineCount": len(lines)}


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
_LEDGER_RESULTS = ["aligned", "partial", "missing"]
_LEDGER_LEVELS = ["敏感", "重要", "内部"]
_ISSUE_FLOW = ["open", "assigned", "in_progress", "recheck", "closed"]
_ISSUE_LABEL = {"open": "待处理", "assigned": "已指派", "in_progress": "整改中",
                "recheck": "待复检", "closed": "已关闭"}
_NEG_HINTS = ("未", "尚未", "缺", "暂无", "没有", "不足", "不完整")


def _actor(body: dict) -> str:
    return (body or {}).get("actor") or _current_account()


def _ledger_inconsistent(result: str, actual: str) -> bool:
    """结论与实际描述一致性校验：结论为「已对上」时，实际描述不得含否定表述。"""
    return result == "aligned" and any(w in (actual or "") for w in _NEG_HINTS)


def _ledger_rec(r: dict) -> dict:
    return {"rowId": r["row_id"], "scene": r["scene"], "level": r["level"],
            "should": r["should"], "actual": r["actual"], "result": r["result"],
            "resultLabel": _RESULT_LABEL.get(r["result"], r["result"]),
            "owner": r["owner"], "updatedAt": r["updated_at"]}


def _diag_answer(r: dict) -> dict:
    return {"answerId": r["answer_id"], "dimNo": r["dim_no"], "dimName": r["dim_name"],
            "q": r["q"], "state": r["state"] or "", "note": r["note"] or "",
            "evidence": r["evidence"] or "", "updatedAt": r["updated_at"]}


def _assessment(a: dict, answers: list) -> dict:
    answered = sum(1 for x in answers if (x.get("state") or "").strip())
    ev_ready = sum(1 for x in answers if (x.get("evidence") or "").strip())
    total = len(answers) or 1
    return {"assessmentId": a["assessment_id"], "title": a["title"], "status": a["status"],
            "owner": a["owner"], "createdAt": a["created_at"], "submittedAt": a["submitted_at"],
            "counts": {"total": len(answers), "answered": answered, "evidenceReady": ev_ready},
            "completion": round(ev_ready / total * 100),
            "answers": answers}


def _disposal_rec(r: dict) -> dict:
    return {"disposalId": r["disposal_id"], "issueNo": r["issue_no"],
            "issueName": r["issue_name"], "layer": r["layer"], "status": r["status"],
            "statusLabel": _ISSUE_LABEL.get(r["status"], r["status"]),
            "org": r["org_name"] or "", "position": r["position"] or "",
            "plan": r["plan"] or "", "evidence": r["evidence"] or "",
            "owner": r["owner"], "createdAt": r["created_at"], "updatedAt": r["updated_at"],
            "closedAt": r["closed_at"]}


# ---------------------------------------------------------------- 现状诊断
@router.get("/diagnosis/dimensions")
def diagnosis_dimensions():
    dims = seed.DIAG_DIMENSIONS
    stat = {"yes": 0, "partial": 0, "no": 0}
    for d in dims:
        for a in d.get("answers", []):
            stat[a.get("state")] = stat.get(a.get("state"), 0) + 1
    rows = store.q("SELECT * FROM diag_assessment ORDER BY created_at DESC")
    assessments = []
    for a in rows:
        ans = store.q("SELECT * FROM diag_answer WHERE assessment_id=? ORDER BY dim_no, answer_id",
                      (a["assessment_id"],))
        assessments.append(_assessment(a, [_diag_answer(x) for x in ans]))
    return {"questions": seed.DIAG_QUESTIONS, "dimensions": dims,
            "assessments": assessments,
            "summary": {"dimensions": len(dims), "questions": len(seed.DIAG_QUESTIONS),
                        "perAssessment": len(dims) * len(seed.DIAG_QUESTIONS),
                        "assessments": len(assessments), "answers": stat},
            "fetchedAt": _now()}


@router.post("/diagnosis/assessments")
def diag_assessment_create(body: dict = Body(default=None)):
    body = body or {}
    title = (body.get("title") or "").strip()
    if not title:
        return _err("VALIDATION_FAILED", "诊断批次名称必填", 422)
    actor = _actor(body)
    aid = "da-" + uuid.uuid4().hex[:8]
    store.insert("diag_assessment", {
        "assessment_id": aid, "title": title, "status": "draft", "owner": actor,
        "created_by": actor, "created_at": _now(), "updated_at": _now(), "submitted_at": None})
    for d in seed.DIAG_DIMENSIONS:
        for k, a in enumerate(d["answers"], start=1):
            store.insert("diag_answer", {
                "answer_id": f"ans-{aid}-{d['no']}-{k}", "assessment_id": aid,
                "dim_no": d["no"], "dim_name": d["name"], "q": a["q"],
                "state": "", "note": d.get("note", ""), "evidence": "", "updated_at": _now()})
    _audit(actor, "diag.assessment.create", aid, {"title": title})
    return {"ok": True, "assessmentId": aid}


@router.put("/diagnosis/assessments/{assessment_id}/answers")
def diag_answers_save(assessment_id: str, body: dict = Body(default=None)):
    body = body or {}
    a = store.q1("SELECT * FROM diag_assessment WHERE assessment_id=?", (assessment_id,))
    if not a:
        return _err("NOT_FOUND", "诊断批次不存在", 404)
    if a["status"] == "submitted":
        return _err("VALIDATION_FAILED", "该诊断已提交，不可修改；请新建一次诊断", 422)
    answers = body.get("answers")
    if not isinstance(answers, list) or not answers:
        return _err("VALIDATION_FAILED", "作答内容为空", 422)
    actor = _actor(body)
    saved = 0
    for it in answers:
        dim_no, q = it.get("dimNo"), it.get("q")
        if dim_no is None or not q:
            return _err("VALIDATION_FAILED", "作答缺少维度或问题标识", 422)
        state = (it.get("state") or "").strip()
        if state and state not in ("yes", "partial", "no"):
            return _err("VALIDATION_FAILED", "三问判定取值非法（应为 有 / 部分 / 缺）", 422)
        rows = store.q("SELECT answer_id FROM diag_answer WHERE assessment_id=? AND dim_no=? AND q=?",
                       (assessment_id, dim_no, q))
        if not rows:
            return _err("VALIDATION_FAILED", "作答项与诊断维度不匹配", 422)
        store.insert("diag_answer", {
            "answer_id": rows[0]["answer_id"], "assessment_id": assessment_id,
            "dim_no": dim_no, "dim_name": it.get("dimName") or "",
            "q": q, "state": state, "note": (it.get("note") or "").strip(),
            "evidence": (it.get("evidence") or "").strip(), "updated_at": _now()})
        saved += 1
    store.x("UPDATE diag_assessment SET updated_at=? WHERE assessment_id=?", (_now(), assessment_id))
    _audit(actor, "diag.answer.save", assessment_id, {"count": saved})
    return {"ok": True, "saved": saved}


@router.post("/diagnosis/assessments/{assessment_id}/submit")
def diag_assessment_submit(assessment_id: str, body: dict = Body(default=None)):
    body = body or {}
    a = store.q1("SELECT * FROM diag_assessment WHERE assessment_id=?", (assessment_id,))
    if not a:
        return _err("NOT_FOUND", "诊断批次不存在", 404)
    if a["status"] == "submitted":
        return _err("VALIDATION_FAILED", "该诊断已提交", 422)
    rows = store.q("SELECT * FROM diag_answer WHERE assessment_id=? ORDER BY dim_no, answer_id",
                   (assessment_id,))
    missing = [f"{r['dim_no']}·{r['q']}" for r in rows if not (r["state"] or "").strip()]
    no_evidence = [f"{r['dim_no']}·{r['q']}" for r in rows if not (r["evidence"] or "").strip()]
    if missing:
        return _err("VALIDATION_FAILED", f"三问判定未答完：还有 {len(missing)} 项未作答", 422,
                    {"missing": missing[:8]})
    if no_evidence:
        return _err("VALIDATION_FAILED", f"证据说明未填完：还有 {len(no_evidence)} 项缺少说明", 422,
                    {"missing": no_evidence[:8]})
    actor = _actor(body)
    store.x("UPDATE diag_assessment SET status='submitted', submitted_at=?, updated_at=? "
            "WHERE assessment_id=?", (_now(), _now(), assessment_id))
    _audit(actor, "diag.assessment.submit", assessment_id, {"answers": len(rows)})
    return {"ok": True, "assessmentId": assessment_id, "status": "submitted"}


# ---------------------------------------------------- 应用与业务层台账
@router.get("/ledger/rows")
def ledger_rows():
    rows = [_ledger_rec(r) for r in store.q("SELECT * FROM ledger_row ORDER BY created_at, row_id")]
    summary = {"total": len(rows), "aligned": 0, "partial": 0, "missing": 0}
    for r in rows:
        summary[r["result"]] = summary.get(r["result"], 0) + 1
    return {"rows": rows, "summary": summary, "levels": _LEDGER_LEVELS,
            "results": _LEDGER_RESULTS, "fetchedAt": _now()}


def _ledger_validate(body: dict) -> str | None:
    """返回错误消息（校验不通过）或 None。"""
    for k, label in (("scene", "使用场景"), ("level", "分级"), ("should", "应做到"),
                     ("actual", "实际（对账发现）"), ("result", "对账结论")):
        if not (body.get(k) or "").strip():
            return f"「{label}」必填"
    if body["level"] not in _LEDGER_LEVELS:
        return "分级取值非法"
    if body["result"] not in _LEDGER_RESULTS:
        return "对账结论取值非法"
    if _ledger_inconsistent(body["result"], body["actual"]):
        return "结论「已对上」与「实际」描述不一致：描述中含否定表述，请核对结论"
    return None


@router.post("/ledger/rows")
def ledger_row_create(body: dict = Body(default=None)):
    body = body or {}
    err = _ledger_validate(body)
    if err:
        return _err("VALIDATION_FAILED", err, 422)
    scene = body["scene"].strip()
    if store.q1("SELECT row_id FROM ledger_row WHERE scene=?", (scene,)):
        return _err("VALIDATION_FAILED", f"已存在同名使用场景「{scene}」", 422)
    actor = _actor(body)
    rid = "lr-" + uuid.uuid4().hex[:8]
    store.insert("ledger_row", {
        "row_id": rid, "scene": scene, "level": body["level"].strip(),
        "should": body["should"].strip(), "actual": body["actual"].strip(),
        "result": body["result"], "owner": actor, "created_by": actor,
        "created_at": _now(), "updated_at": _now()})
    _audit(actor, "ledger.row.create", rid, {"result": body["result"]})
    return {"ok": True, "rowId": rid}


@router.put("/ledger/rows/{row_id}")
def ledger_row_update(row_id: str, body: dict = Body(default=None)):
    body = body or {}
    r = store.q1("SELECT * FROM ledger_row WHERE row_id=?", (row_id,))
    if not r:
        return _err("NOT_FOUND", "对账台账记录不存在", 404)
    merged = {"scene": body.get("scene", r["scene"]), "level": body.get("level", r["level"]),
              "should": body.get("should", r["should"]), "actual": body.get("actual", r["actual"]),
              "result": body.get("result", r["result"])}
    err = _ledger_validate(merged)
    if err:
        return _err("VALIDATION_FAILED", err, 422)
    dup = store.q1("SELECT row_id FROM ledger_row WHERE scene=? AND row_id<>?",
                   (merged["scene"].strip(), row_id))
    if dup:
        return _err("VALIDATION_FAILED", f"已存在同名使用场景「{merged['scene'].strip()}」", 422)
    actor = _actor(body)
    store.insert("ledger_row", {
        "row_id": row_id, "scene": merged["scene"].strip(), "level": merged["level"].strip(),
        "should": merged["should"].strip(), "actual": merged["actual"].strip(),
        "result": merged["result"], "owner": r["owner"] or actor,
        "created_by": r["created_by"], "created_at": r["created_at"], "updated_at": _now()})
    _audit(actor, "ledger.row.update", row_id, {"result": merged["result"]})
    return {"ok": True, "rowId": row_id}


@router.delete("/ledger/rows/{row_id}")
def ledger_row_delete(row_id: str):
    r = store.q1("SELECT row_id FROM ledger_row WHERE row_id=?", (row_id,))
    if not r:
        return _err("NOT_FOUND", "对账台账记录不存在", 404)
    store.x("DELETE FROM ledger_row WHERE row_id=?", (row_id,))
    _audit(_current_account(), "ledger.row.delete", row_id, {})
    return {"ok": True, "rowId": row_id}


# -------------------------------------------------------- 逐类问题处置
@router.get("/issues/classes")
def issues_classes():
    classes = seed.ISSUE_CLASSES
    layers: dict = {}
    for c in classes:
        layers[c["layer"]] = layers.get(c["layer"], 0) + 1
    disposals = [_disposal_rec(r) for r in
                 store.q("SELECT * FROM issue_disposal ORDER BY created_at, disposal_id")]
    stat = {k: 0 for k in _ISSUE_FLOW}
    for d in disposals:
        stat[d["status"]] = stat.get(d["status"], 0) + 1
    return {"classes": classes, "disposals": disposals,
            "flow": [{"status": s, "label": _ISSUE_LABEL[s]} for s in _ISSUE_FLOW],
            "summary": {"total": len(classes), "layers": layers, "disposals": len(disposals),
                        "byStatus": stat},
            "fetchedAt": _now()}


@router.post("/issues/disposals")
def issue_disposal_create(body: dict = Body(default=None)):
    body = body or {}
    no = (body.get("issueNo") or "").strip()
    c = next((x for x in seed.ISSUE_CLASSES if x["no"] == no), None)
    if not c:
        return _err("VALIDATION_FAILED", "请选择一类已识别的问题", 422)
    if store.q1("SELECT disposal_id FROM issue_disposal WHERE issue_no=? AND status<>'closed'", (no,)):
        return _err("VALIDATION_FAILED", f"「{no} {c['name']}」已有在办处置工单", 422)
    actor = _actor(body)
    did = "disp-" + uuid.uuid4().hex[:8]
    mgmt = c.get("mgmt") or {}
    store.insert("issue_disposal", {
        "disposal_id": did, "issue_no": no, "issue_name": c["name"], "layer": c["layer"],
        "status": "open", "org_name": "", "position": "",
        "plan": mgmt.get("流程规范", ""), "evidence": "", "owner": actor,
        "created_by": actor, "created_at": _now(), "updated_at": _now(), "closed_at": None})
    _audit(actor, "issue.disposal.create", did, {"issueNo": no})
    return {"ok": True, "disposalId": did}


@router.patch("/issues/disposals/{disposal_id}")
def issue_disposal_assign(disposal_id: str, body: dict = Body(default=None)):
    body = body or {}
    r = store.q1("SELECT * FROM issue_disposal WHERE disposal_id=?", (disposal_id,))
    if not r:
        return _err("NOT_FOUND", "处置工单不存在", 404)
    if r["status"] == "closed":
        return _err("VALIDATION_FAILED", "已关闭的工单不可再指派", 422)
    org = (body.get("org") or "").strip()
    pos = (body.get("position") or "").strip()
    if not org or not pos:
        return _err("VALIDATION_FAILED", "指派须同时填写责任组织与责任岗位", 422)
    actor = _actor(body)
    store.x("UPDATE issue_disposal SET org_name=?, position=?, plan=?, status='assigned', "
            "updated_at=? WHERE disposal_id=?",
            (org, pos, (body.get("plan") or r["plan"] or "").strip(), _now(), disposal_id))
    _audit(actor, "issue.disposal.assign", disposal_id, {"org": org, "position": pos})
    return {"ok": True, "disposalId": disposal_id, "status": "assigned"}


@router.post("/issues/disposals/{disposal_id}/advance")
def issue_disposal_advance(disposal_id: str, body: dict = Body(default=None)):
    r = store.q1("SELECT * FROM issue_disposal WHERE disposal_id=?", (disposal_id,))
    if not r:
        return _err("NOT_FOUND", "处置工单不存在", 404)
    idx = _ISSUE_FLOW.index(r["status"]) if r["status"] in _ISSUE_FLOW else -1
    nxt = _ISSUE_FLOW[idx + 1] if 0 <= idx < len(_ISSUE_FLOW) - 1 else None
    if nxt is None:
        return _err("VALIDATION_FAILED", "工单已到终态，无法再推进", 422)
    if nxt == "closed":
        return _err("VALIDATION_FAILED", "关闭工单须登记处置证据", 422)
    actor = _actor(body or {})
    store.x("UPDATE issue_disposal SET status=?, updated_at=? WHERE disposal_id=?",
            (nxt, _now(), disposal_id))
    _audit(actor, "issue.disposal.advance", disposal_id, {"from": r["status"], "to": nxt})
    return {"ok": True, "disposalId": disposal_id, "status": nxt, "statusLabel": _ISSUE_LABEL[nxt]}


@router.post("/issues/disposals/{disposal_id}/close")
def issue_disposal_close(disposal_id: str, body: dict = Body(default=None)):
    body = body or {}
    r = store.q1("SELECT * FROM issue_disposal WHERE disposal_id=?", (disposal_id,))
    if not r:
        return _err("NOT_FOUND", "处置工单不存在", 404)
    if r["status"] == "closed":
        return _err("VALIDATION_FAILED", "工单已关闭", 422)
    if r["status"] != "recheck":
        return _err("VALIDATION_FAILED", "仅「待复检」工单可关闭：请先推进至待复检并完成复检", 422)
    evidence = (body.get("evidence") or "").strip()
    if not evidence:
        return _err("VALIDATION_FAILED", "关闭工单须登记处置证据（复检与验收记录）", 422)
    actor = _actor(body)
    store.x("UPDATE issue_disposal SET status='closed', evidence=?, closed_at=?, updated_at=? "
            "WHERE disposal_id=?", (evidence, _now(), _now(), disposal_id))
    _audit(actor, "issue.disposal.close", disposal_id, {"evidence": evidence[:40]})
    return {"ok": True, "disposalId": disposal_id, "status": "closed"}


@router.delete("/issues/disposals/{disposal_id}")
def issue_disposal_delete(disposal_id: str):
    r = store.q1("SELECT disposal_id FROM issue_disposal WHERE disposal_id=?", (disposal_id,))
    if not r:
        return _err("NOT_FOUND", "处置工单不存在", 404)
    store.x("DELETE FROM issue_disposal WHERE disposal_id=?", (disposal_id,))
    _audit(_current_account(), "issue.disposal.delete", disposal_id, {})
    return {"ok": True, "disposalId": disposal_id}


# ===========================================================================
# 5.13 三层治理框架（闭合链）
# ---------------------------------------------------------------------------
# 读来自 DB（frame_chain_case / frame_ring_record），写落库并留审计；
# 校验失败统一返回 VALIDATION_FAILED。口径：合成脱敏、全代号化；无机构真名、
# 无绝对路径、无条目数承诺、无厂商与产品名称。
# ===========================================================================
_CASE_STATUS_LABEL = {"in_progress": "推进中", "closed": "已闭环"}


def _frame_case(c: dict, rings: list) -> dict:
    recs = [{"ringNo": r["ring_no"], "ringName": r["ring_name"], "output": r["output"] or "",
             "evidence": r["evidence"] or "", "operator": r["operator"],
             "createdAt": r["created_at"]} for r in rings]
    done = sorted({r["ringNo"] for r in recs})
    return {"caseId": c["case_id"], "title": c["title"], "issueNo": c["issue_no"],
            "status": c["status"], "statusLabel": _CASE_STATUS_LABEL.get(c["status"], c["status"]),
            "currentRing": c["current_ring"], "owner": _owner_name(c["owner"]),
            "createdAt": c["created_at"], "updatedAt": c["updated_at"],
            "records": recs, "doneRings": done}


def _owner_name(acc: str) -> str:
    """账号 → 展示名（缺失回退账号）。"""
    row = store.q1("SELECT display_name FROM user_account WHERE account=?", (acc,))
    return row["display_name"] if row else (acc or "")


@router.get("/governance/frame")
def governance_frame():
    domains = seed.GOV_FRAME_DOMAINS
    chain = seed.GOV_FRAME_CHAIN
    rows = store.q("SELECT * FROM frame_chain_case ORDER BY created_at DESC")
    cases = []
    for c in rows:
        rings = store.q("SELECT * FROM frame_ring_record WHERE case_id=? ORDER BY ring_no",
                        (c["case_id"],))
        cases.append(_frame_case(c, rings))
    return {"domains": domains, "chain": chain, "cases": cases,
            "summary": {"domains": len(domains), "chain": len(chain), "cases": len(cases),
                        "progressing": len([x for x in cases if x["status"] == "in_progress"])},
            "fetchedAt": _now()}


@router.post("/governance/frame/cases")
def frame_case_create(body: dict = Body(default=None)):
    body = body or {}
    issue_no = (body.get("issueNo") or "").strip()
    by_no = {c["no"]: c for c in seed.ISSUE_CLASSES}
    if not issue_no:
        return _err("VALIDATION_FAILED", "请选择要推进的问题类别", 422)
    if issue_no not in by_no:
        return _err("VALIDATION_FAILED", "问题类别须取自逐类问题清单", 422)
    running = store.q1("SELECT case_id FROM frame_chain_case WHERE issue_no=? "
                       "AND status='in_progress'", (issue_no,))
    if running:
        return _err("VALIDATION_FAILED", f"「{issue_no}」已有在办闭合链，请先闭环再新建", 422)
    actor = _actor(body)
    cid = "fc-" + uuid.uuid4().hex[:8]
    title = (body.get("title") or "").strip() or f"{by_no[issue_no].get('name', '')} —— 闭合链推进"
    store.insert("frame_chain_case", {
        "case_id": cid, "title": title, "issue_no": issue_no, "status": "in_progress",
        "current_ring": 1, "owner": actor, "created_by": actor,
        "created_at": _now(), "updated_at": _now()})
    _audit(actor, "frame.case.create", cid, {"issueNo": issue_no})
    return {"ok": True, "caseId": cid, "currentRing": 1}


@router.post("/governance/frame/cases/{case_id}/rings")
def frame_ring_record(case_id: str, body: dict = Body(default=None)):
    body = body or {}
    c = store.q1("SELECT * FROM frame_chain_case WHERE case_id=?", (case_id,))
    if not c:
        return _err("NOT_FOUND", "闭合链案件不存在", 404)
    if c["status"] != "in_progress":
        return _err("VALIDATION_FAILED", "该案件已闭环，不能再登记环节", 422)
    output = (body.get("output") or "").strip()
    evidence = (body.get("evidence") or "").strip()
    if not output:
        return _err("VALIDATION_FAILED", "本环结论 / 输出必填", 422)
    chain = seed.GOV_FRAME_CHAIN
    ring_no = c["current_ring"]
    if ring_no > len(chain):
        return _err("VALIDATION_FAILED", "闭合链已走完", 422)
    ring_name = chain[ring_no - 1]["name"]
    if ring_name in ("证据", "整改验收") and not evidence:
        return _err("VALIDATION_FAILED", f"「{ring_name}」环须归集证据材料", 422)
    actor = _actor(body)
    store.insert("frame_ring_record", {
        "record_id": "fr-" + uuid.uuid4().hex[:10], "case_id": case_id, "ring_no": ring_no,
        "ring_name": ring_name, "output": output, "evidence": evidence,
        "operator": actor, "created_at": _now()})
    if ring_no >= len(chain):
        store.x("UPDATE frame_chain_case SET status='closed', current_ring=?, updated_at=? "
                "WHERE case_id=?", (ring_no + 1, _now(), case_id))
    else:
        store.x("UPDATE frame_chain_case SET current_ring=?, updated_at=? WHERE case_id=?",
                (ring_no + 1, _now(), case_id))
    _audit(actor, "frame.ring.record", case_id, {"ringNo": ring_no})
    return {"ok": True, "caseId": case_id, "ringNo": ring_no,
            "closed": ring_no >= len(chain)}


# ===========================================================================
# 报告脱敏样例（只读）
# ---------------------------------------------------------------------------
# 静态只读演示数据，来自 seed 常量。口径：合成脱敏、全代号化；无机构真名、
# 无绝对路径、无条目数承诺、无厂商与产品名称。
# ===========================================================================
@router.get("/report/sample")
def report_sample():
    sample = seed.REPORT_SAMPLE
    return {"header": sample.get("header", {}), "five": sample.get("five", {}),
            "fetchedAt": _now()}


# ===========================================================================
# 5.14 安全治理闭环（多角色 / 多部门 / 多岗位 十态工作流）
# ---------------------------------------------------------------------------
# 闭环：登记 → 定级 → 派单 → 接收 → 整改 → 回复（佐证） → 复检 → 核查确认 → 归档。
# 一次动作一个状态迁移，全部落库并写审计；归档时把整改结论回写知识库与资产台账。
# 口径：合成脱敏、全代号化；校验失败统一 VALIDATION_FAILED，越权统一 FORBIDDEN。
# ===========================================================================
GOV_FLOW = ["open", "triaged", "dispatched", "accepted", "remediating",
            "responded", "rechecking", "pending_confirm", "closed"]
GOV_LABEL = {"open": "待定级", "triaged": "已定级", "dispatched": "已下发工单",
             "accepted": "已接收", "remediating": "整改中", "responded": "已提交佐证",
             "rechecking": "复检中", "pending_confirm": "待核查确认", "closed": "已确认归档"}
GOV_ACTION_NAME = {"triage": "定级拆分", "dispatch": "下发处置工单", "accept": "接收工单",
                   "start": "启动整改", "respond": "提交整改回复", "recheck": "提交复检反馈",
                   "confirm": "提交核查确认", "close": "确认归档", "reject": "退回重办"}
GOV_ACTION = {"triage": ("open", "triaged"), "dispatch": ("triaged", "dispatched"),
              "accept": ("dispatched", "accepted"), "start": ("accepted", "remediating"),
              "respond": ("remediating", "responded"), "recheck": ("responded", "rechecking"),
              "confirm": ("rechecking", "pending_confirm"), "close": ("pending_confirm", "closed"),
              "reject": ("rechecking", "remediating")}
GOV_ACTION_ROLE = {"triage": ["sys_admin", "l0_lead"], "dispatch": ["sys_admin", "l0_lead"],
                   "accept": ["l1_handle", "l2_handle", "l3_exec", "manager", "kb_ops"],
                   "start": ["l1_handle", "l2_handle", "l3_exec", "manager", "kb_ops"],
                   "respond": ["l1_handle", "l2_handle", "l3_exec", "manager", "kb_ops"],
                   "recheck": ["sys_admin", "l0_lead", "l1_review"],
                   "confirm": ["sys_admin", "l0_lead"], "close": ["sys_admin", "l0_lead"],
                   "reject": ["sys_admin", "l0_lead", "l1_review"]}
GOV_SOURCES = ["自查发现", "监管检查", "内部审计", "事件驱动"]
GOV_CATEGORIES = ["治理层", "流程层", "资产层", "技术层"]
GOV_EVIDENCE_KINDS = ["整改回复", "复检反馈", "核查确认"]
_GOV_SEV = {"high": "高", "medium": "中", "low": "低"}


def _gov_allowed(status: str) -> list:
    if status == "open":
        return ["triage"]
    if status == "triaged":
        return ["dispatch"]
    if status == "dispatched":
        return ["accept"]
    if status == "accepted":
        return ["start"]
    if status == "remediating":
        return ["respond"]
    if status == "responded":
        return ["recheck"]
    if status == "rechecking":
        return ["confirm", "reject"]
    if status == "pending_confirm":
        return ["close", "reject"]
    return []


def _gov_rec(r: dict) -> dict:
    return {"issueId": r["issue_id"], "issueNo": r["issue_no"], "title": r["title"],
            "source": r["source"], "category": r["category"], "severity": r["severity"],
            "severityLabel": _GOV_SEV.get(r["severity"], r["severity"]),
            "deptId": r["dept_id"] or "", "deptName": r["dept_name"] or "",
            "positionId": r["position_id"] or "", "positionName": r["position_name"] or "",
            "owner": r["owner"], "ownerName": _owner_name(r["owner"]),
            "status": r["status"], "statusLabel": GOV_LABEL.get(r["status"], r["status"]),
            "allowedActions": _gov_allowed(r["status"]),
            "dueDate": r["due_date"] or "", "plan": r["plan"] or "",
            "recheckResult": r["recheck_result"] or "",
            "createdAt": r["created_at"], "updatedAt": r["updated_at"], "closedAt": r["closed_at"]}


def _next_gov_no() -> str:
    import re as _re
    mx = 0
    for r in store.q("SELECT issue_no FROM gov_issue"):
        m = _re.search(r"(\d+)$", r["issue_no"] or "")
        if m:
            mx = max(mx, int(m.group(1)))
    return "GY-2026-%03d" % (mx + 1)


@router.get("/gov/issues")
def gov_issue_list():
    rows = store.q("SELECT * FROM gov_issue ORDER BY created_at, issue_no")
    issues = [_gov_rec(r) for r in rows]
    by_status = {}
    for it in issues:
        by_status[it["status"]] = by_status.get(it["status"], 0) + 1
    return {"issues": issues,
            "flow": [{"status": s, "label": GOV_LABEL[s]} for s in GOV_FLOW],
            "actions": [{"action": a, "name": GOV_ACTION_NAME[a], "from": GOV_ACTION[a][0],
                         "to": GOV_ACTION[a][1], "roles": GOV_ACTION_ROLE[a]}
                        for a in ["triage", "dispatch", "accept", "start", "respond",
                                  "recheck", "confirm", "close", "reject"]],
            "sources": GOV_SOURCES, "categories": GOV_CATEGORIES,
            "severities": [{"value": k, "label": v} for k, v in _GOV_SEV.items()],
            "summary": {"total": len(issues), "closed": by_status.get("closed", 0),
                        "inFlight": len([x for x in issues if x["status"] != "closed"]),
                        "byStatus": by_status, "bySeverity": {
                            s: len([x for x in issues if x["severity"] == s]) for s in _GOV_SEV}},
            "fetchedAt": _now()}


@router.get("/gov/issues/{issue_id}")
def gov_issue_detail(issue_id: str):
    r = store.q1("SELECT * FROM gov_issue WHERE issue_id=?", (issue_id,))
    if not r:
        return _err("NOT_FOUND", "治理问题不存在", 404)
    trans = store.q("SELECT * FROM gov_transition WHERE issue_id=? ORDER BY created_at, transition_id",
                    (issue_id,))
    ev = store.q("SELECT * FROM gov_evidence WHERE issue_id=? ORDER BY uploaded_at, evidence_id",
                 (issue_id,))
    out = _gov_rec(r)
    out["transitions"] = [{"transitionId": t["transition_id"], "from": t["from_status"],
                           "to": t["to_status"], "toLabel": GOV_LABEL.get(t["to_status"], t["to_status"]),
                           "action": t["action"], "actionName": GOV_ACTION_NAME.get(t["action"], t["action"]),
                           "actor": t["actor"], "actorName": t["actor_name"],
                           "comment": t["comment"] or "", "createdAt": t["created_at"]} for t in trans]
    out["evidence"] = [{"evidenceId": e["evidence_id"], "step": e["step"], "fileName": e["file_name"],
                        "note": e["note"] or "", "uploadedBy": e["uploaded_by"],
                        "uploadedByName": _owner_name(e["uploaded_by"]),
                        "uploadedAt": e["uploaded_at"]} for e in ev]
    return out


@router.post("/gov/issues")
def gov_issue_create(body: dict = Body(default=None)):
    body = body or {}
    title = (body.get("title") or "").strip()
    if not title:
        return _err("VALIDATION_FAILED", "问题标题必填", 422)
    sev = (body.get("severity") or "medium").strip()
    if sev not in _GOV_SEV:
        return _err("VALIDATION_FAILED", "重要程度取值非法", 422)
    cat = (body.get("category") or "治理层").strip()
    if cat not in GOV_CATEGORIES:
        return _err("VALIDATION_FAILED", "问题分类须为：" + " / ".join(GOV_CATEGORIES), 422)
    src = (body.get("source") or "自查发现").strip()
    if src not in GOV_SOURCES:
        return _err("VALIDATION_FAILED", "问题来源须为：" + " / ".join(GOV_SOURCES), 422)
    actor = _actor(body)
    iid = "gv-" + uuid.uuid4().hex[:8]
    no = _next_gov_no()
    dept_id = (body.get("deptId") or "").strip()
    pos_id = (body.get("positionId") or "").strip()
    store.insert("gov_issue", {
        "issue_id": iid, "issue_no": no, "title": title, "source": src, "category": cat,
        "severity": sev, "dept_id": dept_id, "dept_name": _lookup_name("org_node", "node_id", dept_id),
        "position_id": pos_id, "position_name": _lookup_name("org_position", "position_id", pos_id),
        "owner": actor, "status": "open", "due_date": (body.get("dueDate") or "").strip(),
        "plan": (body.get("plan") or "").strip(), "recheck_result": "",
        "created_by": actor, "created_at": _now(), "updated_at": _now(), "closed_at": None})
    store.insert("gov_transition", {
        "transition_id": "gt-" + uuid.uuid4().hex[:8], "issue_id": iid, "from_status": "",
        "to_status": "open", "action": "create", "actor": actor,
        "actor_name": _owner_name(actor),
        "comment": (body.get("note") or "登记待治理问题").strip(), "created_at": _now()})
    _audit(actor, "gov.issue.create", iid, {"issueNo": no, "severity": sev})
    return {"ok": True, "issueId": iid, "issueNo": no}


def _gov_glob_for(action: str) -> str:
    roles = GOV_ACTION_ROLE.get(action, [])
    names = {"sys_admin": "系统管理员", "l0_lead": "总部负责人", "l1_review": "复核岗",
             "l1_handle": "经办岗", "l2_handle": "分支经办岗", "l3_exec": "网点执行岗",
             "manager": "机构负责人", "kb_ops": "知识运营岗"}
    return " / ".join(names.get(r, r) for r in roles) or "指定岗位"


@router.post("/gov/issues/{issue_id}/transition")
def gov_issue_transition(issue_id: str, body: dict = Body(default=None)):
    body = body or {}
    r = store.q1("SELECT * FROM gov_issue WHERE issue_id=?", (issue_id,))
    if not r:
        return _err("NOT_FOUND", "治理问题不存在", 404)
    action = (body.get("action") or "").strip()
    if action not in GOV_ACTION:
        return _err("VALIDATION_FAILED", "未知的流转动作", 422)
    cur = r["status"]
    frm, to = GOV_ACTION[action]
    if action == "reject" and cur in ("rechecking", "pending_confirm"):
        frm, to = cur, "remediating"
    if cur != frm:
        return _err("VALIDATION_FAILED",
                    "当前状态为「%s」，不能执行「%s」" % (GOV_LABEL.get(cur, cur),
                                                        GOV_ACTION_NAME[action]), 422)
    actor = _actor(body)
    roles = _roles_of(actor)
    need = GOV_ACTION_ROLE.get(action, [])
    if need and "sys_admin" not in roles and not (set(need) & set(roles)):
        return _err("FORBIDDEN", "当前账号无权执行「%s」，该环节应由「%s」办理"
                    % (GOV_ACTION_NAME[action], _gov_glob_for(action)), 403)
    comment = (body.get("comment") or "").strip()
    if action == "dispatch":
        dept_id = (body.get("deptId") or r["dept_id"] or "").strip()
        pos_id = (body.get("positionId") or r["position_id"] or "").strip()
        if not dept_id or not pos_id:
            return _err("VALIDATION_FAILED", "下发处置工单须指定责任部门与责任岗位", 422)
        if not (body.get("dueDate") or r["due_date"] or "").strip():
            return _err("VALIDATION_FAILED", "下发处置工单须指定整改时限", 422)
    if action in ("respond", "recheck"):
        if not (body.get("fileName") or "").strip():
            return _err("VALIDATION_FAILED",
                        "提交%s须附工作佐证材料名称" % GOV_ACTION_NAME[action], 422)
    if action == "close" and not (body.get("recheckResult") or r["recheck_result"] or "").strip():
        return _err("VALIDATION_FAILED", "确认归档须填写复检结论", 422)

    fields = {"updated_at": _now(), "status": to, "owner": actor}
    if action == "triage":
        if body.get("severity"):
            if body["severity"] not in _GOV_SEV:
                return _err("VALIDATION_FAILED", "重要程度取值非法", 422)
            fields["severity"] = body["severity"]
        if body.get("category"):
            if body["category"] not in GOV_CATEGORIES:
                return _err("VALIDATION_FAILED", "问题分类取值非法", 422)
            fields["category"] = body["category"]
    if action == "dispatch":
        fields["dept_id"] = (body.get("deptId") or r["dept_id"]).strip()
        fields["dept_name"] = _lookup_name("org_node", "node_id", fields["dept_id"]) or r["dept_name"]
        fields["position_id"] = (body.get("positionId") or r["position_id"]).strip()
        fields["position_name"] = (_lookup_name("org_position", "position_id", fields["position_id"])
                                   or r["position_name"])
        fields["due_date"] = (body.get("dueDate") or r["due_date"] or "").strip()
        if body.get("plan"):
            fields["plan"] = body["plan"].strip()
    if action == "close":
        fields["closed_at"] = _now()
        fields["recheck_result"] = (body.get("recheckResult") or r["recheck_result"] or "").strip()

    merged = dict(r)
    merged.update(fields)
    store.insert("gov_issue", merged)

    if action in ("respond", "recheck"):
        kind = "整改回复" if action == "respond" else "复检反馈"
        store.insert("gov_evidence", {
            "evidence_id": "ge-" + uuid.uuid4().hex[:8], "issue_id": issue_id, "step": kind,
            "file_name": body["fileName"].strip(), "note": (body.get("note") or "").strip(),
            "uploaded_by": actor, "uploaded_at": _now()})
    if action == "close":
        store.insert("gov_evidence", {
            "evidence_id": "ge-" + uuid.uuid4().hex[:8], "issue_id": issue_id, "step": "核查确认",
            "file_name": "核查确认单-%s.pdf" % r["issue_no"],
            "note": fields["recheck_result"], "uploaded_by": actor, "uploaded_at": _now()})

    store.insert("gov_transition", {
        "transition_id": "gt-" + uuid.uuid4().hex[:8], "issue_id": issue_id,
        "from_status": cur, "to_status": to, "action": action, "actor": actor,
        "actor_name": _owner_name(actor),
        "comment": comment or GOV_ACTION_NAME[action], "created_at": _now()})
    _audit(actor, "gov.issue." + action, issue_id,
           {"from": cur, "to": to}, result="ok")

    # 归档：把整改结论回写资料库，形成新的知识与资产
    if action == "close":
        _gov_writeback(merged)
    return {"ok": True, "issueId": issue_id, "status": to, "statusLabel": GOV_LABEL[to]}


def _gov_writeback(r: dict) -> None:
    """整改结论回写：知识文档 + 版本 + 变更清单 + 资产台账（形成新的知识与资产）。"""
    doc_id = "doc-gov-" + r["issue_id"]
    title = "%s · 整改闭环结论" % r["title"]
    asset_id = "as-gov-" + r["issue_id"]
    now = _now()
    store.insert("kb_document", {
        "doc_id": doc_id, "kb_id": "kt-inner", "title": title, "doc_type": "整改结论",
        "source": "manual", "version": "v1", "status": "published", "owner": r["owner"],
        "uploaded_by": r["owner"], "created_at": now, "updated_at": now})
    store.insert("kb_doc_version", {
        "version_id": "kv-%s-v1" % doc_id, "doc_id": doc_id, "version": "v1",
        "content_hash": __import__("hashlib").sha256(
            ("%s|v1" % doc_id).encode("utf-8")).hexdigest()[:32],
        "note": "整改闭环结论（自动回写）", "created_by": r["owner"], "created_at": now})
    store.insert("kb_change_log", {
        "change_id": "kc-%s-1" % doc_id, "doc_id": doc_id, "change_type": "publish",
        "summary": "整改闭环结论回写：《%s》" % title, "actor": r["owner"], "created_at": now})
    store.insert("asset_record", {
        "asset_id": asset_id, "name": title, "category": "制度办法", "source": "治理回写",
        "dept_id": r["dept_id"], "dept_name": r["dept_name"], "owner": r["owner"],
        "version": "v1", "status": "在册", "kb_doc_id": doc_id,
        "note": r["recheck_result"] or "", "created_by": r["owner"],
        "created_at": now, "updated_at": now})


# ===========================================================================
# 5.15 报告与看板（先选自查任务 → 看完成情况与各部门完成比例 → 下钻条目）
# ===========================================================================
def _check_title_map(industry: str) -> dict:
    doc = "jg93" if industry == "insurance" else "jg24"
    try:
        checks = seed._real_checks(doc)
    except Exception:  # noqa: BLE001
        checks = []
    return {c["checkCode"]: c.get("title") or "" for c in checks}


@router.get("/reports/tasks")
def report_tasks():
    tasks = store.q("SELECT * FROM selfcheck_task ORDER BY created_at DESC")
    out = []
    for t in tasks:
        items = store.q("SELECT status FROM selfcheck_item_state WHERE task_id=?", (t["task_id"],))
        by = {}
        for it in items:
            by[it["status"]] = by.get(it["status"], 0) + 1
        v = _verdict(by, len(items))
        out.append({"taskId": t["task_id"], "orgName": t["org_name"], "industry": t["industry"],
                    "cycle": t["cycle"], "topic": t["topic"], "stage": t["stage"],
                    "status": t["status"], "statusLabel": _TASK_STATUS.get(t["status"], t["status"]),
                    "progress": t["progress"], "riskLevel": t["risk_level"],
                    "verdict": v, "itemCount": len(items),
                    "owner": t["owner"], "ownerName": _owner_name(t["owner"]),
                    "startDate": t["start_date"], "endDate": t["end_date"]})
    return {"tasks": out, "fetchedAt": _now()}


@router.get("/reports/tasks/{task_id}/overview")
def report_task_overview(task_id: str):
    t = _task_or_404(task_id)
    if not t:
        return _err("NOT_FOUND", "自查任务不存在", 404)
    items = store.q("SELECT * FROM selfcheck_item_state WHERE task_id=? ORDER BY check_code", (task_id,))
    sections = store.q("SELECT * FROM selfcheck_section WHERE task_id=? ORDER BY section_id", (task_id,))
    by_status, by_line = {}, {}
    ev_total = ev_provided = 0
    for it in items:
        by_status[it["status"]] = by_status.get(it["status"], 0) + 1
        code = it["line_code"] or "other"
        d = by_line.setdefault(code, {"total": 0, "pass": 0, "partial": 0, "fail": 0,
                                      "supplement": 0, "done": 0})
        d["total"] += 1
        d[it["status"]] = d.get(it["status"], 0) + 1
        if it["status"]:
            d["done"] += 1
        evs = _jloads(it["evidence_json"], [])
        ev_total += 1
        if evs:
            ev_provided += 1
    labels = {s["line_code"]: s["line_label"] for s in sections}
    sec_progress = {s["line_code"]: s["progress"] for s in sections}
    depts = []
    for code, d in by_line.items():
        pct = sec_progress.get(code)
        if pct is None:
            pct = round(d["pass"] / max(1, d["total"]) * 100)
        risk = "high" if d["fail"] >= 3 else ("medium" if (d["fail"] or d["partial"]) else "low")
        depts.append({"key": code, "label": labels.get(code, code), "total": d["total"],
                      "pass": d["pass"], "partial": d["partial"], "fail": d["fail"],
                      "supplement": d["supplement"], "done": d["done"],
                      "progress": pct, "riskLevel": risk})
    depts.sort(key=lambda x: -x["progress"])
    v = _verdict(by_status, len(items))
    return {"task": {"taskId": t["task_id"], "orgName": t["org_name"], "industry": t["industry"],
                     "cycle": t["cycle"], "topic": t["topic"], "stage": t["stage"],
                     "status": t["status"], "statusLabel": _TASK_STATUS.get(t["status"], t["status"]),
                     "progress": t["progress"], "riskLevel": t["risk_level"],
                     "owner": t["owner"], "ownerName": _owner_name(t["owner"]),
                     "startDate": t["start_date"], "endDate": t["end_date"]},
            "verdict": v,
            "counts": {"total": len(items), "pass": by_status.get("pass", 0),
                       "partial": by_status.get("partial", 0), "fail": by_status.get("fail", 0),
                       "supplement": by_status.get("supplement", 0),
                       "evidenceRequired": ev_total, "evidenceProvided": ev_provided},
            "byStatus": [{"status": k, "count": v2} for k, v2 in sorted(by_status.items())],
            "byDept": depts,
            "sections": [{"sectionId": s["section_id"], "lineCode": s["line_code"],
                          "lineLabel": s["line_label"], "status": s["status"],
                          "progress": s["progress"], "dueDate": s["due_date"]} for s in sections],
            "computedAt": _now()}


@router.get("/reports/tasks/{task_id}/items")
def report_task_items(task_id: str, lineCode: str = "", status: str = ""):
    t = _task_or_404(task_id)
    if not t:
        return _err("NOT_FOUND", "自查任务不存在", 404)
    sql = "SELECT * FROM selfcheck_item_state WHERE task_id=?"
    args = [task_id]
    if lineCode:
        sql += " AND line_code=?"
        args.append(lineCode)
    if status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY check_code"
    rows = store.q(sql, tuple(args))
    titles = _check_title_map(t["industry"])
    out = [{"checkCode": r["check_code"], "title": titles.get(r["check_code"], ""),
            "lineCode": r["line_code"], "applicability": r["applicability"],
            "status": r["status"], "owner": r["owner"], "ownerName": _owner_name(r["owner"]),
            "hasPolicy": bool(r["has_policy"]),
            "evidence": _jloads(r["evidence_json"], []),
            "actualValue": r["actual_value"] or "", "note": r["note"] or "",
            "updatedAt": r["updated_at"]} for r in rows]
    return {"taskId": task_id, "lineCode": lineCode, "items": out, "fetchedAt": _now()}


# ===========================================================================
# 5.16 资产台账（分类汇总 + 知识库加载 / 手工上传 / 版本更新 / 权限控制）
# ===========================================================================
_ASSET_FIXED_CATS = ["应用资产", "配置管理", "数据资产", "制度办法", "接口清单"]
_ASSET_SOURCES = ["系统对接", "手工上传", "治理回写"]
_ASSET_STATUSES = ["在册", "待更新", "已入库"]


def _asset_cats() -> list:
    cats = list(_ASSET_FIXED_CATS)
    for r in store.q("SELECT DISTINCT category FROM asset_record"):
        if r["category"] and r["category"] not in cats:
            cats.append(r["category"])
    return cats


def _asset_ledger_rec(r: dict) -> dict:
    return {"assetId": r["asset_id"], "name": r["name"], "category": r["category"],
            "source": r["source"], "deptId": r["dept_id"] or "",
            "deptName": r["dept_name"] or "", "owner": r["owner"],
            "ownerName": _owner_name(r["owner"]), "version": r["version"] or "",
            "status": r["status"], "kbDocId": r["kb_doc_id"] or "",
            "inKnowledgeBase": bool(r["kb_doc_id"]), "note": r["note"] or "",
            "createdAt": r["created_at"], "updatedAt": r["updated_at"]}


@router.get("/asset-ledger")
def asset_ledger():
    rows = [_asset_ledger_rec(r) for r in store.q("SELECT * FROM asset_record ORDER BY category, asset_id")]
    by_cat = {}
    for a in rows:
        d = by_cat.setdefault(a["category"], {"category": a["category"], "total": 0})
        d["total"] += 1
    return {"assets": rows, "categories": _asset_cats(), "sources": _ASSET_SOURCES,
            "statuses": _ASSET_STATUSES,
            "summary": {"total": len(rows),
                        "inKnowledgeBase": len([x for x in rows if x["inKnowledgeBase"]]),
                        "pendingUpdate": len([x for x in rows if x["status"] == "待更新"]),
                        "byCategory": list(by_cat.values())},
            "fetchedAt": _now()}


@router.post("/asset-ledger")
def asset_ledger_create(body: dict = Body(default=None)):
    body = body or {}
    name = (body.get("name") or "").strip()
    cat = (body.get("category") or "").strip()
    if not name:
        return _err("VALIDATION_FAILED", "资产名称必填", 422)
    if cat not in _asset_cats():
        return _err("VALIDATION_FAILED", "资产类别须为：" + " / ".join(_asset_cats()), 422)
    src = (body.get("source") or "手工上传").strip()
    if src not in _ASSET_SOURCES:
        return _err("VALIDATION_FAILED", "来源须为：" + " / ".join(_ASSET_SOURCES), 422)
    if store.q1("SELECT asset_id FROM asset_record WHERE name=? AND category=?", (name, cat)):
        return _err("VALIDATION_FAILED", "同类资产中已存在同名「%s」" % name, 422)
    actor = _actor(body)
    aid = "as-" + uuid.uuid4().hex[:8]
    dept_id = (body.get("deptId") or "").strip()
    store.insert("asset_record", {
        "asset_id": aid, "name": name, "category": cat, "source": src, "dept_id": dept_id,
        "dept_name": _lookup_name("org_node", "node_id", dept_id),
        "owner": actor, "version": (body.get("version") or "v1").strip(), "status": "在册",
        "kb_doc_id": None, "note": (body.get("note") or "").strip(),
        "created_by": actor, "created_at": _now(), "updated_at": _now()})
    _audit(actor, "asset.create", aid, {"category": cat, "source": src})
    return {"ok": True, "assetId": aid}


@router.put("/asset-ledger/{asset_id}")
def asset_update(asset_id: str, body: dict = Body(default=None)):
    body = body or {}
    r = store.q1("SELECT * FROM asset_record WHERE asset_id=?", (asset_id,))
    if not r:
        return _err("NOT_FOUND", "资产记录不存在", 404)
    name = (body.get("name") or r["name"]).strip()
    cat = (body.get("category") or r["category"]).strip()
    if cat not in _asset_cats():
        return _err("VALIDATION_FAILED", "资产类别取值非法", 422)
    if store.q1("SELECT asset_id FROM asset_record WHERE name=? AND category=? AND asset_id<>?",
                (name, cat, asset_id)):
        return _err("VALIDATION_FAILED", "同类资产中已存在同名「%s」" % name, 422)
    actor = _actor(body)
    status = (body.get("status") or r["status"]).strip()
    if status not in _ASSET_STATUSES:
        return _err("VALIDATION_FAILED", "状态取值非法", 422)
    dept_id = (body.get("deptId") if body.get("deptId") is not None else r["dept_id"]) or ""
    store.insert("asset_record", {
        "asset_id": asset_id, "name": name, "category": cat,
        "source": (body.get("source") or r["source"]).strip(), "dept_id": dept_id,
        "dept_name": _lookup_name("org_node", "node_id", dept_id) or r["dept_name"],
        "owner": r["owner"], "version": (body.get("version") or r["version"]).strip(),
        "status": status, "kb_doc_id": r["kb_doc_id"],
        "note": (body.get("note") if body.get("note") is not None else r["note"]) or "",
        "created_by": r["created_by"], "created_at": r["created_at"], "updated_at": _now()})
    _audit(actor, "asset.update", asset_id, {"status": status})
    return {"ok": True, "assetId": asset_id}


@router.delete("/asset-ledger/{asset_id}")
def asset_ledger_delete(asset_id: str):
    r = store.q1("SELECT asset_id FROM asset_record WHERE asset_id=?", (asset_id,))
    if not r:
        return _err("NOT_FOUND", "资产记录不存在", 404)
    store.x("DELETE FROM asset_record WHERE asset_id=?", (asset_id,))
    _audit(_current_account(), "asset.delete", asset_id, {})
    return {"ok": True, "assetId": asset_id}


@router.post("/asset-ledger/{asset_id}/push-kb")
def asset_push_kb(asset_id: str, body: dict = Body(default=None)):
    """资产入库知识库：生成或更新对应知识文档，并登记版本与变更。"""
    body = body or {}
    r = store.q1("SELECT * FROM asset_record WHERE asset_id=?", (asset_id,))
    if not r:
        return _err("NOT_FOUND", "资产记录不存在", 404)
    kb_id = (body.get("kbId") or "kt-inner").strip()
    target = store.q1("SELECT * FROM kb_target WHERE kb_id=?", (kb_id,))
    if not target:
        return _err("VALIDATION_FAILED", "目标知识库不存在，请先在知识库清单中选择", 422)
    actor = _actor(body)
    now = _now()
    doc_id = r["kb_doc_id"]
    if doc_id:
        d = store.q1("SELECT * FROM kb_document WHERE doc_id=?", (doc_id,))
        if d:
            ver = _bump_version(d["version"])
            store.insert("kb_document", {
                "doc_id": doc_id, "kb_id": kb_id, "title": d["title"], "doc_type": d["doc_type"],
                "source": d["source"], "version": ver, "status": "pending_review",
                "owner": actor, "uploaded_by": actor, "created_at": d["created_at"],
                "updated_at": now})
            store.insert("kb_doc_version", {
                "version_id": "kv-%s-%s" % (doc_id, ver), "doc_id": doc_id, "version": ver,
                "content_hash": __import__("hashlib").sha256(
                    ("%s|%s" % (doc_id, ver)).encode("utf-8")).hexdigest()[:32],
                "note": "由资产台账更新上传", "created_by": actor, "created_at": now})
            store.insert("kb_change_log", {
                "change_id": "kc-%s-%s" % (doc_id, ver), "doc_id": doc_id,
                "change_type": "version", "summary": "资产台账更新上传，版本升至 %s" % ver,
                "actor": actor, "created_at": now})
            _audit(actor, "asset.kb.update", asset_id, {"docId": doc_id, "version": ver})
            return {"ok": True, "assetId": asset_id, "docId": doc_id, "version": ver,
                    "status": "pending_review"}
    doc_id = "doc-" + uuid.uuid4().hex[:8]
    store.insert("kb_document", {
        "doc_id": doc_id, "kb_id": kb_id, "title": r["name"], "doc_type": r["category"],
        "source": "manual", "version": "v1", "status": "pending_review", "owner": actor,
        "uploaded_by": actor, "created_at": now, "updated_at": now})
    store.insert("kb_doc_version", {
        "version_id": "kv-%s-v1" % doc_id, "doc_id": doc_id, "version": "v1",
        "content_hash": __import__("hashlib").sha256(
            ("%s|v1" % doc_id).encode("utf-8")).hexdigest()[:32],
        "note": "由资产台账上传", "created_by": actor, "created_at": now})
    store.insert("kb_change_log", {
        "change_id": "kc-%s-1" % doc_id, "doc_id": doc_id, "change_type": "create",
        "summary": "资产台账上传《%s》至%s" % (r["name"], target["name"]), "actor": actor,
        "created_at": now})
    store.insert("asset_record", {
        "asset_id": asset_id, "name": r["name"], "category": r["category"], "source": r["source"],
        "dept_id": r["dept_id"], "dept_name": r["dept_name"], "owner": r["owner"],
        "version": r["version"], "status": "已入库", "kb_doc_id": doc_id, "note": r["note"],
        "created_by": r["created_by"], "created_at": r["created_at"], "updated_at": now})
    _audit(actor, "asset.kb.upload", asset_id, {"docId": doc_id, "kbId": kb_id})
    return {"ok": True, "assetId": asset_id, "docId": doc_id, "version": "v1",
            "status": "pending_review"}


@router.post("/asset-ledger/sync")
def asset_sync(body: dict = Body(default=None)):
    """从知识库加载：把知识库中已存在的制度类文档同步为资产台账记录。"""
    kb_id = ((body or {}).get("kbId") or "kt-inner").strip()
    actor = _actor(body or {})
    added = 0
    for d in store.q("SELECT * FROM kb_document WHERE kb_id=? ORDER BY doc_id", (kb_id,)):
        if store.q1("SELECT asset_id FROM asset_record WHERE kb_doc_id=?", (d["doc_id"],)):
            continue
        added += 1
        store.insert("asset_record", {
            "asset_id": "as-sync-" + d["doc_id"], "name": d["title"],
            "category": "制度办法", "source": "系统对接", "dept_id": "", "dept_name": "",
            "owner": actor, "version": d["version"] or "v1", "status": "已入库",
            "kb_doc_id": d["doc_id"], "note": "由知识库加载", "created_by": actor,
            "created_at": _now(), "updated_at": _now()})
    _audit(actor, "asset.sync", kb_id, {"added": added})
    return {"ok": True, "kbId": kb_id, "added": added}


# ===========================================================================
# 5.17 知识发布治理（对接知识库平台：选库与类型 · 采集/上传 · 专家审核 · 版本与日志）
# ===========================================================================
_KB_DOC_STATUS = {"draft": "草稿", "pending_review": "待专家审核", "published": "已入库",
                  "rejected": "已退回"}
_KB_CHANGE_TYPE = {"create": "新建", "version": "版本更新", "publish": "发布入库",
                   "review": "专家审核", "rollback": "版本回滚"}
_KB_DOC_TYPES = ["制度", "目录", "指引", "解读", "案例", "整改结论", "其他"]


def _bump_version(v: str) -> str:
    import re as _re
    m = _re.search(r"(\d+)$", v or "")
    return "v%d" % (int(m.group(1)) + 1) if m else "v2"


def _kb_doc_rec(r: dict, kb_name: str = "") -> dict:
    return {"docId": r["doc_id"], "kbId": r["kb_id"], "kbName": kb_name,
            "title": r["title"], "docType": r["doc_type"], "source": r["source"],
            "sourceLabel": "自动采集" if r["source"] == "auto" else "手工上传",
            "version": r["version"], "status": r["status"],
            "statusLabel": _KB_DOC_STATUS.get(r["status"], r["status"]),
            "owner": r["owner"], "ownerName": _owner_name(r["owner"]),
            "createdAt": r["created_at"], "updatedAt": r["updated_at"]}


def _kb_name_map() -> dict:
    return {t["kb_id"]: t["name"] for t in store.q("SELECT kb_id,name FROM kb_target")}


@router.get("/kb/targets")
def kb_targets():
    rows = store.q("SELECT * FROM kb_target ORDER BY kb_id")
    return {"targets": [{"kbId": r["kb_id"], "name": r["name"], "kind": r["kind"],
                         "docCount": r["doc_count"], "syncedAt": r["synced_at"]} for r in rows],
            "docTypes": _KB_DOC_TYPES,
            "sourceKind": [{"value": "manual", "label": "手工上传"},
                           {"value": "auto", "label": "自动采集"}],
            "contractVersion": CONTRACT_VERSION, "fetchedAt": _now()}


@router.get("/kb/documents")
def kb_documents(kbId: str = "", status: str = ""):
    sql = "SELECT * FROM kb_document"
    args, where = [], []
    if kbId:
        where.append("kb_id=?")
        args.append(kbId)
    if status:
        where.append("status=?")
        args.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC, doc_id"
    names = _kb_name_map()
    docs = [_kb_doc_rec(r, names.get(r["kb_id"], "")) for r in store.q(sql, tuple(args))]
    by_status = {}
    for d in docs:
        by_status[d["status"]] = by_status.get(d["status"], 0) + 1
    return {"documents": docs, "byStatus": by_status,
            "summary": {"total": len(docs), "published": by_status.get("published", 0),
                        "pendingReview": by_status.get("pending_review", 0),
                        "draft": by_status.get("draft", 0)},
            "fetchedAt": _now()}


@router.get("/kb/documents/{doc_id}")
def kb_document_detail(doc_id: str):
    r = store.q1("SELECT * FROM kb_document WHERE doc_id=?", (doc_id,))
    if not r:
        return _err("NOT_FOUND", "知识文档不存在", 404)
    names = _kb_name_map()
    vers = store.q("SELECT * FROM kb_doc_version WHERE doc_id=? ORDER BY created_at, version_id", (doc_id,))
    changes = store.q("SELECT * FROM kb_change_log WHERE doc_id=? ORDER BY created_at, change_id", (doc_id,))
    calls = store.q("SELECT * FROM kb_call_log WHERE doc_id=? ORDER BY created_at DESC", (doc_id,))
    reviews = store.q("SELECT * FROM kb_review WHERE doc_id=? ORDER BY created_at, review_id", (doc_id,))
    out = _kb_doc_rec(r, names.get(r["kb_id"], ""))
    out["versions"] = [{"versionId": v["version_id"], "version": v["version"],
                        "contentHash": v["content_hash"], "note": v["note"] or "",
                        "createdBy": v["created_by"], "createdByName": _owner_name(v["created_by"]),
                        "createdAt": v["created_at"]} for v in vers]
    out["changes"] = [{"changeId": c["change_id"], "changeType": c["change_type"],
                       "changeTypeLabel": _KB_CHANGE_TYPE.get(c["change_type"], c["change_type"]),
                       "summary": c["summary"] or "", "actor": c["actor"],
                       "actorName": _owner_name(c["actor"]), "createdAt": c["created_at"]}
                      for c in changes]
    out["calls"] = [{"callId": c["call_id"], "caller": c["caller"],
                     "callerName": _owner_name(c["caller"]), "scene": c["scene"] or "",
                     "query": c["query"] or "", "createdAt": c["created_at"]} for c in calls]
    out["reviews"] = [{"reviewId": rv["review_id"], "reviewer": rv["reviewer"],
                       "reviewerName": rv["reviewer_name"] or _owner_name(rv["reviewer"]),
                       "decision": rv["decision"],
                       "decisionLabel": {"approve": "同意入库", "reject": "退回修改",
                                         "pending": "待审核"}.get(rv["decision"], rv["decision"]),
                       "comment": rv["comment"] or "", "createdAt": rv["created_at"],
                       "decidedAt": rv["decided_at"]} for rv in reviews]
    return out


@router.post("/kb/documents")
def kb_document_create(body: dict = Body(default=None)):
    body = body or {}
    kb_id = (body.get("kbId") or "").strip()
    if not store.q1("SELECT kb_id FROM kb_target WHERE kb_id=?", (kb_id,)):
        return _err("VALIDATION_FAILED", "请选择目标知识库（发布前必须先选择知识库）", 422)
    title = (body.get("title") or "").strip()
    if not title:
        return _err("VALIDATION_FAILED", "知识标题必填", 422)
    src = (body.get("source") or "manual").strip()
    if src not in ("manual", "auto"):
        return _err("VALIDATION_FAILED", "入库方式取值非法", 422)
    actor = _actor(body)
    doc_id = "doc-" + uuid.uuid4().hex[:8]
    now = _now()
    dtype = (body.get("docType") or "制度").strip()
    store.insert("kb_document", {
        "doc_id": doc_id, "kb_id": kb_id, "title": title, "doc_type": dtype, "source": src,
        "version": "v1", "status": "draft", "owner": actor, "uploaded_by": actor,
        "created_at": now, "updated_at": now})
    store.insert("kb_doc_version", {
        "version_id": "kv-%s-v1" % doc_id, "doc_id": doc_id, "version": "v1",
        "content_hash": __import__("hashlib").sha256(
            ("%s|v1" % doc_id).encode("utf-8")).hexdigest()[:32],
        "note": "初始上传", "created_by": actor, "created_at": now})
    store.insert("kb_change_log", {
        "change_id": "kc-%s-1" % doc_id, "doc_id": doc_id, "change_type": "create",
        "summary": "%s《%s》" % ("自动采集" if src == "auto" else "手工上传", title),
        "actor": actor, "created_at": now})
    _audit(actor, "kb.doc.create", doc_id, {"kbId": kb_id, "source": src})
    return {"ok": True, "docId": doc_id, "status": "draft"}


@router.post("/kb/documents/{doc_id}/publish")
def kb_document_publish(doc_id: str, body: dict = Body(default=None)):
    r = store.q1("SELECT * FROM kb_document WHERE doc_id=?", (doc_id,))
    if not r:
        return _err("NOT_FOUND", "知识文档不存在", 404)
    if r["status"] == "published":
        return _err("VALIDATION_FAILED", "该文档已入库", 422)
    if r["status"] == "pending_review":
        return _err("VALIDATION_FAILED", "该文档已在待专家审核中", 422)
    actor = _actor(body or {})
    store.insert("kb_document", dict(r, status="pending_review", updated_at=_now()))
    store.insert("kb_review", {
        "review_id": "kr-" + uuid.uuid4().hex[:8], "doc_id": doc_id, "reviewer": "",
        "reviewer_name": "", "decision": "pending", "comment": "",
        "created_at": _now(), "decided_at": None})
    store.insert("kb_change_log", {
        "change_id": "kc-%s-p%s" % (doc_id, uuid.uuid4().hex[:4]), "doc_id": doc_id,
        "change_type": "publish", "summary": "提交专家审核", "actor": actor, "created_at": _now()})
    _audit(actor, "kb.doc.publish", doc_id, {})
    return {"ok": True, "docId": doc_id, "status": "pending_review"}


@router.post("/kb/documents/{doc_id}/review")
def kb_document_review(doc_id: str, body: dict = Body(default=None)):
    body = body or {}
    r = store.q1("SELECT * FROM kb_document WHERE doc_id=?", (doc_id,))
    if not r:
        return _err("NOT_FOUND", "知识文档不存在", 404)
    if r["status"] != "pending_review":
        return _err("VALIDATION_FAILED", "仅「待专家审核」的文档可审核", 422)
    decision = (body.get("decision") or "").strip()
    if decision not in ("approve", "reject"):
        return _err("VALIDATION_FAILED", "审核结论须为同意入库或退回修改", 422)
    if decision == "reject" and not (body.get("comment") or "").strip():
        return _err("VALIDATION_FAILED", "退回修改须填写审核意见", 422)
    actor = _actor(body)
    roles = _roles_of(actor)
    if "sys_admin" not in roles and not (set(roles) & {"l1_review", "l0_lead", "kb_ops"}):
        return _err("FORBIDDEN", "仅专家审核岗可对已上传知识做出审核结论", 403)
    new_status = "published" if decision == "approve" else "draft"
    pending = store.q1("SELECT * FROM kb_review WHERE doc_id=? AND decision='pending'", (doc_id,))
    rec = {"review_id": (pending["review_id"] if pending else "kr-" + uuid.uuid4().hex[:8]),
           "doc_id": doc_id, "reviewer": actor, "reviewer_name": _owner_name(actor),
           "decision": decision, "comment": (body.get("comment") or "").strip(),
           "created_at": (pending["created_at"] if pending else _now()), "decided_at": _now()}
    store.insert("kb_review", rec)
    store.insert("kb_document", dict(r, status=new_status, updated_at=_now()))
    store.insert("kb_change_log", {
        "change_id": "kc-%s-r%s" % (doc_id, uuid.uuid4().hex[:4]), "doc_id": doc_id,
        "change_type": "review",
        "summary": "专家%s：%s" % ("同意入库" if decision == "approve" else "退回修改",
                                  rec["comment"] or "—"),
        "actor": actor, "created_at": _now()})
    _audit(actor, "kb.doc.review", doc_id, {"decision": decision})
    return {"ok": True, "docId": doc_id, "status": new_status, "decision": decision}


@router.post("/kb/documents/{doc_id}/versions")
def kb_document_version(doc_id: str, body: dict = Body(default=None)):
    body = body or {}
    r = store.q1("SELECT * FROM kb_document WHERE doc_id=?", (doc_id,))
    if not r:
        return _err("NOT_FOUND", "知识文档不存在", 404)
    note = (body.get("note") or "").strip()
    if not note:
        return _err("VALIDATION_FAILED", "版本更新说明必填", 422)
    actor = _actor(body)
    ver = _bump_version(r["version"])
    now = _now()
    store.insert("kb_doc_version", {
        "version_id": "kv-%s-%s" % (doc_id, ver), "doc_id": doc_id, "version": ver,
        "content_hash": __import__("hashlib").sha256(
            ("%s|%s" % (doc_id, ver)).encode("utf-8")).hexdigest()[:32],
        "note": note, "created_by": actor, "created_at": now})
    store.insert("kb_document", dict(r, version=ver, status="pending_review", updated_at=now))
    store.insert("kb_review", {
        "review_id": "kr-" + uuid.uuid4().hex[:8], "doc_id": doc_id, "reviewer": "",
        "reviewer_name": "", "decision": "pending", "comment": "",
        "created_at": now, "decided_at": None})
    store.insert("kb_change_log", {
        "change_id": "kc-%s-v%s" % (doc_id, uuid.uuid4().hex[:4]), "doc_id": doc_id,
        "change_type": "version", "summary": "版本升至 %s：%s" % (ver, note),
        "actor": actor, "created_at": now})
    _audit(actor, "kb.doc.version", doc_id, {"version": ver})
    return {"ok": True, "docId": doc_id, "version": ver, "status": "pending_review"}


@router.get("/kb/change-log")
def kb_change_log(limit: int = 60):
    names = _kb_name_map()
    docs = {d["doc_id"]: d for d in store.q("SELECT doc_id,title,kb_id FROM kb_document")}
    rows = store.q("SELECT * FROM kb_change_log ORDER BY created_at DESC, change_id DESC LIMIT ?",
                   (max(1, min(limit, 300)),))
    out = []
    for c in rows:
        d = docs.get(c["doc_id"]) or {}
        out.append({"changeId": c["change_id"], "docId": c["doc_id"],
                    "docTitle": d.get("title", "—"),
                    "kbName": names.get(d.get("kb_id", ""), ""),
                    "changeType": c["change_type"],
                    "changeTypeLabel": _KB_CHANGE_TYPE.get(c["change_type"], c["change_type"]),
                    "summary": c["summary"] or "", "actor": c["actor"],
                    "actorName": _owner_name(c["actor"]), "createdAt": c["created_at"]})
    return {"changes": out, "types": [{"value": k, "label": v} for k, v in _KB_CHANGE_TYPE.items()],
            "fetchedAt": _now()}


@router.get("/kb/call-log")
def kb_call_log(limit: int = 60):
    names = _kb_name_map()
    docs = {d["doc_id"]: d for d in store.q("SELECT doc_id,title,kb_id FROM kb_document")}
    rows = store.q("SELECT * FROM kb_call_log ORDER BY created_at DESC, call_id DESC LIMIT ?",
                   (max(1, min(limit, 300)),))
    out = []
    for c in rows:
        d = docs.get(c["doc_id"]) or {}
        out.append({"callId": c["call_id"], "docId": c["doc_id"],
                    "docTitle": d.get("title", "—"),
                    "kbName": names.get(d.get("kb_id", ""), ""),
                    "caller": c["caller"], "callerName": _owner_name(c["caller"]),
                    "scene": c["scene"] or "", "query": c["query"] or "",
                    "createdAt": c["created_at"]})
    return {"calls": out, "fetchedAt": _now()}


@router.post("/kb/documents/{doc_id}/call")
def kb_document_call(doc_id: str, body: dict = Body(default=None)):
    """登记一次知识调用（演示知识被调用的日志）。"""
    body = body or {}
    if not store.q1("SELECT doc_id FROM kb_document WHERE doc_id=?", (doc_id,)):
        return _err("NOT_FOUND", "知识文档不存在", 404)
    actor = _actor(body)
    cid = "kl-" + uuid.uuid4().hex[:8]
    store.insert("kb_call_log", {
        "call_id": cid, "doc_id": doc_id, "caller": actor,
        "scene": (body.get("scene") or "知识检索").strip(),
        "query": (body.get("query") or "").strip(), "created_at": _now()})
    return {"ok": True, "callId": cid}


# ===========================================================================
# 5.18 场景包明细（知识来源 / 知识库 / 部门岗位角色 / 工具 / 系统 / 模板）
# ===========================================================================
def _scenario_detail(pack_id: str) -> dict:
    d = store.q1("SELECT * FROM scenario_detail WHERE pack_id=?", (pack_id,))
    if not d:
        return {"packId": pack_id, "knowledgeSource": "", "kbIds": [], "depts": [],
                "positions": [], "roles": [], "tools": [], "systems": [], "templates": [],
                "updatedBy": "", "updatedAt": ""}
    return {"packId": d["pack_id"], "knowledgeSource": d["knowledge_source"] or "",
            "kbIds": _jloads(d["kb_ids_json"], []), "depts": _jloads(d["depts_json"], []),
            "positions": _jloads(d["positions_json"], []), "roles": _jloads(d["roles_json"], []),
            "tools": _jloads(d["tools_json"], []), "systems": _jloads(d["systems_json"], []),
            "templates": _jloads(d["templates_json"], []),
            "updatedBy": _owner_name(d["updated_by"]), "updatedAt": d["updated_at"]}


@router.get("/scenario-packs/{pack_id}/detail")
def scenario_pack_detail_ext(pack_id: str):
    r = store.q1("SELECT * FROM scenario_pack WHERE pack_id=?", (pack_id,))
    if not r:
        return _err("NOT_FOUND", "场景包不存在", 404)
    names = _kb_name_map()
    out = _scenario_detail(pack_id)
    out["name"] = r["name"]
    out["kbNames"] = [names.get(k, k) for k in out["kbIds"]]
    out["allKbs"] = [{"kbId": t["kb_id"], "name": t["name"]} for t in
                     store.q("SELECT kb_id,name FROM kb_target ORDER BY kb_id")]
    out["allDepts"] = [n["name"] for n in store.q("SELECT name FROM org_node ORDER BY sort, node_id")]
    out["allPositions"] = [p["name"] for p in store.q("SELECT name FROM org_position ORDER BY name")]
    out["allRoles"] = [{"roleId": r2["role_id"], "name": r2["name"]} for r2 in
                       store.q("SELECT role_id,name FROM role_def ORDER BY role_id")]
    return out


@router.put("/scenario-packs/{pack_id}/detail")
def scenario_pack_detail_save(pack_id: str, body: dict = Body(default=None)):
    body = body or {}
    if not store.q1("SELECT pack_id FROM scenario_pack WHERE pack_id=?", (pack_id,)):
        return _err("NOT_FOUND", "场景包不存在", 404)
    actor = _actor(body)
    kb_ids = body.get("kbIds") or []
    bad = [k for k in kb_ids if not store.q1("SELECT kb_id FROM kb_target WHERE kb_id=?", (k,))]
    if bad:
        return _err("VALIDATION_FAILED", "引用的知识库不存在：" + "、".join(bad), 422)
    store.insert("scenario_detail", {
        "pack_id": pack_id, "knowledge_source": (body.get("knowledgeSource") or "").strip(),
        "kb_ids_json": json.dumps(kb_ids, ensure_ascii=False),
        "depts_json": json.dumps(body.get("depts") or [], ensure_ascii=False),
        "positions_json": json.dumps(body.get("positions") or [], ensure_ascii=False),
        "roles_json": json.dumps(body.get("roles") or [], ensure_ascii=False),
        "tools_json": json.dumps(body.get("tools") or [], ensure_ascii=False),
        "systems_json": json.dumps(body.get("systems") or [], ensure_ascii=False),
        "templates_json": json.dumps(body.get("templates") or [], ensure_ascii=False),
        "updated_by": actor, "updated_at": _now()})
    _audit(actor, "scenario.detail.save", pack_id, {"kbIds": kb_ids})
    return {"ok": True, "packId": pack_id}


# ===========================================================================
# 5.19 工具插件治理（启停开关 / 逐插件配置项 / 内置·上传·服务端下载三种装载）
# ===========================================================================
_PLUGIN_SCHEMA = {
    "grading": [{"key": "levels", "label": "分级体系", "type": "select",
                 "options": ["四级（核心/重要/敏感/内部）", "三级（核心/重要/内部）"]},
                {"key": "defaultLevel", "label": "默认分级", "type": "select",
                 "options": ["核心", "重要", "敏感", "内部"]},
                {"key": "autoApply", "label": "自动套用分级结论", "type": "bool"}],
    "classification": [{"key": "taxonomy", "label": "分类目录", "type": "text"},
                       {"key": "minConfidence", "label": "最低置信度（0-1）", "type": "number",
                        "min": 0, "max": 1, "step": "0.05"},
                       {"key": "reviewLowConfidence", "label": "低置信度转人工复核", "type": "bool"}],
    "masking": [{"key": "algorithm", "label": "脱敏算法", "type": "select",
                 "options": ["掩码（保留首尾）", "哈希（不可逆）", "分箱（区间化）"]},
                {"key": "fields", "label": "脱敏字段", "type": "text"},
                {"key": "reversible", "label": "是否可逆", "type": "bool"}],
    "scan": [{"key": "ruleset", "label": "识别规则集", "type": "text"},
             {"key": "deepScan", "label": "深度扫描", "type": "bool"},
             {"key": "timeout", "label": "单次超时（秒）", "type": "number", "min": 5, "max": 300}],
    "watermark": [{"key": "text", "label": "水印文字", "type": "text"},
                  {"key": "opacity", "label": "不透明度（0-1）", "type": "number",
                   "min": 0, "max": 1, "step": "0.01"},
                  {"key": "tile", "label": "平铺", "type": "bool"}],
    "ocr": [{"key": "lang", "label": "识别语言", "type": "select",
             "options": ["中文（简体）", "中英混合", "英文"]},
            {"key": "layout", "label": "保留版面结构", "type": "bool"},
            {"key": "tableExtract", "label": "表格结构化提取", "type": "bool"}],
    "dlp": [{"key": "channel", "label": "监控通道", "type": "text"},
            {"key": "action", "label": "命中动作", "type": "select",
             "options": ["告警并留痕", "阻断并告警", "仅记录"]},
            {"key": "whitelist", "label": "白名单", "type": "text"}],
}
_PLUGIN_KIND = {"builtin": "内置", "uploaded": "用户上传", "remote": "服务端下载"}
_PLUGIN_CAP_LABEL = {"grading": "数据分级", "classification": "数据分类", "masking": "数据脱敏",
                     "scan": "敏感数据识别", "watermark": "文档水印", "ocr": "图像文字识别",
                     "dlp": "数据防泄漏"}
_PLUGIN_REMOTE_CATALOG = [
    {"catalogId": "rc-ocr-pro", "name": "文字识别插件（增强版）", "capability": "ocr",
     "version": "v2.1", "description": "支持复杂版面与表格结构化提取"},
    {"catalogId": "rc-mask-plus", "name": "数据脱敏插件（增强版）", "capability": "masking",
     "version": "v1.4", "description": "支持可逆脱敏与密钥托管"},
    {"catalogId": "rc-class-nlp", "name": "数据分类插件（语义版）", "capability": "classification",
     "version": "v3.0", "description": "基于语义模型的多标签分类"},
]


def _plugin_setting_rec(s: dict, reg: dict) -> dict:
    return {"pluginId": s["plugin_id"],
            "name": (reg or {}).get("name") or s["plugin_id"],
            "capability": (reg or {}).get("capability") or "",
            "capabilityLabel": _PLUGIN_CAP_LABEL.get((reg or {}).get("capability") or "", ""),
            "status": (reg or {}).get("status") or "离线",
            "vendor": (reg or {}).get("vendor") or "",
            "latencyMs": (reg or {}).get("latency_ms"),
            "enabled": bool(s["enabled"]), "kind": s["kind"],
            "kindLabel": _PLUGIN_KIND.get(s["kind"], s["kind"]),
            "config": _jloads(s["config_json"], {}),
            "configSchema": _PLUGIN_SCHEMA.get((reg or {}).get("capability") or "", []),
            "loadedAt": s["loaded_at"] or "", "updatedBy": _owner_name(s["updated_by"]),
            "updatedAt": s["updated_at"] or ""}


@router.get("/plugin-settings")
def plugin_settings():
    regs = {r["plugin_id"]: r for r in store.q("SELECT * FROM plugin_registry")}
    rows = store.q("SELECT * FROM plugin_setting ORDER BY plugin_id")
    plugins = [_plugin_setting_rec(s, regs.get(s["plugin_id"])) for s in rows]
    # 已注册但尚无治理设置的插件，按默认补一条（保证清单完整）
    for pid, r in regs.items():
        if pid not in {s["plugin_id"] for s in rows}:
            plugins.append(_plugin_setting_rec({
                "plugin_id": pid, "enabled": 1, "kind": "builtin", "config_json": "{}",
                "config_schema_json": None, "loaded_at": "", "updated_by": "", "updated_at": ""}, r))
    return {"plugins": plugins, "kinds": [{"value": k, "label": v} for k, v in _PLUGIN_KIND.items()],
            "remoteCatalog": _PLUGIN_REMOTE_CATALOG,
            "summary": {"total": len(plugins),
                        "enabled": len([p for p in plugins if p["enabled"]]),
                        "disabled": len([p for p in plugins if not p["enabled"]])},
            "fetchedAt": _now()}


def _plugin_or_404(plugin_id: str):
    return store.q1("SELECT * FROM plugin_setting WHERE plugin_id=?", (plugin_id,))


@router.post("/plugin-settings/{plugin_id}/toggle")
def plugin_setting_toggle(plugin_id: str, body: dict = Body(default=None)):
    body = body or {}
    s = _plugin_or_404(plugin_id)
    reg = store.q1("SELECT * FROM plugin_registry WHERE plugin_id=?", (plugin_id,))
    if not s and not reg:
        return _err("NOT_FOUND", "插件不存在", 404)
    enabled = body.get("enabled")
    new = (not bool(s["enabled"])) if enabled is None else bool(enabled)
    actor = _actor(body)
    store.insert("plugin_setting", {
        "plugin_id": plugin_id, "enabled": 1 if new else 0,
        "kind": (s or {}).get("kind") or "builtin",
        "config_json": (s or {}).get("config_json") or "{}",
        "config_schema_json": (s or {}).get("config_schema_json") or "{}",
        "loaded_at": (s or {}).get("loaded_at") or _now(),
        "updated_by": actor, "updated_at": _now()})
    _audit(actor, "plugin.toggle", plugin_id, {"enabled": new})
    return {"ok": True, "pluginId": plugin_id, "enabled": new}


@router.put("/plugin-settings/{plugin_id}/config")
def plugin_setting_config(plugin_id: str, body: dict = Body(default=None)):
    body = body or {}
    s = _plugin_or_404(plugin_id)
    reg = store.q1("SELECT * FROM plugin_registry WHERE plugin_id=?", (plugin_id,))
    if not s and not reg:
        return _err("NOT_FOUND", "插件不存在", 404)
    cfg = body.get("config")
    if not isinstance(cfg, dict):
        return _err("VALIDATION_FAILED", "插件配置须为键值对象", 422)
    cap = (reg or {}).get("capability") or ""
    schema = _PLUGIN_SCHEMA.get(cap, [])
    for f in schema:
        if f["type"] == "number" and cfg.get(f["key"]) not in (None, ""):
            try:
                v = float(cfg[f["key"]])
            except (TypeError, ValueError):
                return _err("VALIDATION_FAILED", "「%s」须为数值" % f["label"], 422)
            lo, hi = f.get("min"), f.get("max")
            if lo is not None and v < lo:
                return _err("VALIDATION_FAILED", "「%s」不得小于 %s" % (f["label"], lo), 422)
            if hi is not None and v > hi:
                return _err("VALIDATION_FAILED", "「%s」不得大于 %s" % (f["label"], hi), 422)
        if f["type"] == "text" and f.get("required") and not str(cfg.get(f["key"]) or "").strip():
            return _err("VALIDATION_FAILED", "「%s」必填" % f["label"], 422)
    actor = _actor(body)
    store.insert("plugin_setting", {
        "plugin_id": plugin_id, "enabled": (s or {}).get("enabled", 1),
        "kind": (s or {}).get("kind") or "builtin",
        "config_json": json.dumps(cfg, ensure_ascii=False),
        "config_schema_json": json.dumps(schema, ensure_ascii=False),
        "loaded_at": (s or {}).get("loaded_at") or _now(),
        "updated_by": actor, "updated_at": _now()})
    _audit(actor, "plugin.config.save", plugin_id, {"keys": list(cfg.keys())})
    return {"ok": True, "pluginId": plugin_id, "config": cfg}


@router.post("/plugin-settings/install")
def plugin_install(body: dict = Body(default=None)):
    """三种装载方式中的两种：用户上传（kind=uploaded）/ 服务端下载（kind=remote）。"""
    body = body or {}
    kind = (body.get("kind") or "uploaded").strip()
    if kind not in ("uploaded", "remote"):
        return _err("VALIDATION_FAILED", "装载方式须为用户上传或服务端下载", 422)
    cap = (body.get("capability") or "").strip()
    if cap not in _PLUGIN_SCHEMA:
        return _err("VALIDATION_FAILED", "请选择插件能力（决定配置项）", 422)
    name = (body.get("name") or "").strip()
    if not name:
        return _err("VALIDATION_FAILED", "插件名称必填", 422)
    catalog_id = (body.get("catalogId") or "").strip()
    if kind == "remote" and catalog_id not in {c["catalogId"] for c in _PLUGIN_REMOTE_CATALOG}:
        return _err("VALIDATION_FAILED", "请从服务端插件目录中选择", 422)
    actor = _actor(body)
    pid = "pl-" + uuid.uuid4().hex[:8]
    now = _now()
    store.insert("plugin_registry", {
        "plugin_id": pid, "name": name, "capability": cap,
        "io_schema_json": json.dumps({"input": {"type": "object"}, "output": {"type": "object"}},
                                     ensure_ascii=False),
        "auth_type": "bearer", "rate_limit": "600/min", "status": "在线",
        "vendor": "服务端目录" if kind == "remote" else "用户上传",
        "latency_ms": 180})
    store.insert("plugin_setting", {
        "plugin_id": pid, "enabled": 1, "kind": kind,
        "config_json": json.dumps(body.get("config") or {}, ensure_ascii=False),
        "config_schema_json": json.dumps(_PLUGIN_SCHEMA.get(cap, []), ensure_ascii=False),
        "loaded_at": now, "updated_by": actor, "updated_at": now})
    _audit(actor, "plugin.install", pid, {"kind": kind, "capability": cap})
    return {"ok": True, "pluginId": pid, "kind": kind}


@router.post("/plugin-settings/{plugin_id}/uninstall")
def plugin_uninstall(plugin_id: str):
    s = store.q1("SELECT * FROM plugin_setting WHERE plugin_id=?", (plugin_id,))
    if not s:
        return _err("NOT_FOUND", "插件不存在", 404)
    if s["kind"] == "builtin":
        return _err("VALIDATION_FAILED", "内置插件不可卸载，可关闭其启用开关", 422)
    store.x("DELETE FROM plugin_setting WHERE plugin_id=?", (plugin_id,))
    store.x("DELETE FROM plugin_registry WHERE plugin_id=?", (plugin_id,))
    _audit(_current_account(), "plugin.uninstall", plugin_id, {"kind": s["kind"]})
    return {"ok": True, "pluginId": plugin_id}


# ===========================================================================
# 5.20 权限与组织精细化（角色-菜单操作权限 / 角色-数据权限 / 轻量单点登录）
# ===========================================================================
_MENU_ACTIONS = ["view", "create", "update", "delete", "approve", "export"]
_MENU_ACTION_LABEL = {"view": "查看", "create": "新建", "update": "修改",
                      "delete": "删除", "approve": "审核", "export": "导出"}
_SCOPE_TYPES = [
    {"type": "ALL", "label": "全部数据", "desc": "可见全辖全部数据（总部管理与知识运营）"},
    {"type": "ORG_AND_CHILD", "label": "本级及下级", "desc": "可见本组织及其下级组织的数据"},
    {"type": "ORG_ONLY", "label": "本级", "desc": "仅可见本组织的数据"},
    {"type": "SELF", "label": "仅本人", "desc": "仅可见本人经办的数据"},
    {"type": "CUSTOM", "label": "自定义范围", "desc": "按指定组织或条线组合授权"},
]


@router.get("/admin/menu-perms")
def admin_menu_perms():
    roles = [{"roleId": r["role_id"], "name": r["name"]} for r in
             store.q("SELECT role_id,name FROM role_def ORDER BY role_id")]
    perms: dict = {}
    for r in store.q("SELECT * FROM role_menu_perm"):
        perms.setdefault(r["role_id"], {})[r["menu_key"]] = _jloads(r["actions_json"], [])
    return {"menus": [{"key": k, "label": l} for k, l in seed.MENU_CATALOG],
            "roles": roles, "actions": _MENU_ACTIONS,
            "actionLabels": _MENU_ACTION_LABEL, "perms": perms, "fetchedAt": _now()}


@router.put("/admin/menu-perms")
def admin_menu_perm_save(body: dict = Body(default=None)):
    body = body or {}
    role_id = (body.get("roleId") or "").strip()
    menu_key = (body.get("menuKey") or "").strip()
    if not store.q1("SELECT role_id FROM role_def WHERE role_id=?", (role_id,)):
        return _err("VALIDATION_FAILED", "角色不存在", 422)
    if menu_key not in {k for k, _ in seed.MENU_CATALOG}:
        return _err("VALIDATION_FAILED", "功能菜单不存在", 422)
    actions = body.get("actions")
    if not isinstance(actions, list):
        return _err("VALIDATION_FAILED", "操作权限须为列表", 422)
    bad = [a for a in actions if a not in _MENU_ACTIONS]
    if bad:
        return _err("VALIDATION_FAILED", "未知操作权限：" + "、".join(bad), 422)
    if role_id == "sys_admin" and not actions:
        return _err("VALIDATION_FAILED", "系统管理员须至少保留查看权限", 422)
    actor = _actor(body)
    pid = "rmp-%s-%s" % (role_id, menu_key)
    if actions:
        store.insert("role_menu_perm", {"perm_id": pid, "role_id": role_id,
                                        "menu_key": menu_key,
                                        "actions_json": json.dumps(actions, ensure_ascii=False)})
    else:
        store.x("DELETE FROM role_menu_perm WHERE role_id=? AND menu_key=?", (role_id, menu_key))
    _audit(actor, "admin.menu.perm.save", pid, {"actions": actions})
    return {"ok": True, "roleId": role_id, "menuKey": menu_key, "actions": actions}


@router.get("/admin/data-scopes")
def admin_data_scopes():
    rows = store.q("SELECT * FROM role_data_scope")
    names = {r["role_id"]: r["name"] for r in store.q("SELECT role_id,name FROM role_def")}
    label = {s["type"]: s["label"] for s in _SCOPE_TYPES}
    return {"scopes": [{"roleId": r["role_id"], "roleName": names.get(r["role_id"], r["role_id"]),
                        "scopeType": r["scope_type"],
                        "scopeLabel": label.get(r["scope_type"], r["scope_type"]),
                        "scope": _jloads(r["scope_json"], {}),
                        "updatedBy": _owner_name(r["updated_by"]),
                        "updatedAt": r["updated_at"]} for r in rows],
            "types": _SCOPE_TYPES,
            "depts": [{"deptId": n["node_id"], "name": n["name"], "level": n["level"]}
                      for n in store.q("SELECT node_id,name,level FROM org_node ORDER BY sort, node_id")],
            "fetchedAt": _now()}


@router.put("/admin/data-scopes/{role_id}")
def admin_data_scope_save(role_id: str, body: dict = Body(default=None)):
    body = body or {}
    if not store.q1("SELECT role_id FROM role_def WHERE role_id=?", (role_id,)):
        return _err("VALIDATION_FAILED", "角色不存在", 422)
    st = (body.get("scopeType") or "").strip()
    if st not in {s["type"] for s in _SCOPE_TYPES}:
        return _err("VALIDATION_FAILED", "数据可见范围取值非法", 422)
    scope = body.get("scope") or {}
    if st == "CUSTOM" and not (scope.get("depts") or scope.get("lines")):
        return _err("VALIDATION_FAILED", "自定义范围须至少指定一个组织或条线", 422)
    actor = _actor(body)
    store.insert("role_data_scope", {
        "scope_id": "rds-%s" % role_id, "role_id": role_id, "scope_type": st,
        "scope_json": json.dumps(scope, ensure_ascii=False),
        "updated_by": actor, "updated_at": _now()})
    _audit(actor, "admin.data.scope.save", role_id, {"scopeType": st})
    return {"ok": True, "roleId": role_id, "scopeType": st}


@router.get("/admin/sso-config")
def admin_sso_config():
    cfg = {}
    for r in store.q("SELECT k,v FROM sso_config"):
        cfg[r["k"]] = _jloads(r["v"], r["v"])
    return {"config": cfg, "protocols": ["OIDC 授权码", "SAML 2.0", "CAS 3.0"],
            "syncModes": ["定时同步 + 登录时即时更新", "仅登录时即时更新", "仅定时同步"],
            "fetchedAt": _now()}


@router.put("/admin/sso-config")
def admin_sso_save(body: dict = Body(default=None)):
    body = body or {}
    if body.get("protocol") and body["protocol"] not in ("OIDC 授权码", "SAML 2.0", "CAS 3.0"):
        return _err("VALIDATION_FAILED", "单点登录协议取值非法", 422)
    if body.get("enabled") and not (body.get("issuer") or "").strip():
        return _err("VALIDATION_FAILED", "启用单点登录须填写身份源地址", 422)
    actor = _actor(body)
    now = _now()
    for k in ("enabled", "protocol", "issuer", "clientId", "syncMode", "jitProvision", "mapping"):
        if k in body:
            store.insert("sso_config", {"k": k, "v": json.dumps(body[k], ensure_ascii=False)})
    store.insert("sso_config", {"k": "updatedBy", "v": json.dumps(actor, ensure_ascii=False)})
    store.insert("sso_config", {"k": "updatedAt", "v": json.dumps(now, ensure_ascii=False)})
    _audit(actor, "admin.sso.save", "sso_config", {"enabled": bool(body.get("enabled"))})
    return admin_sso_config()


# ===========================================================================
# 5.21 现状诊断输入材料与自动生成（历史自查报告 + 工作佐证 / 资产配置 / 资产清单）
# ===========================================================================
_DIAG_KINDS = ["历史自查报告", "工作佐证", "资产配置信息", "资产清单"]
_DIAG_STATE = {"yes": "有", "partial": "部分有", "no": "无"}
_DIAG_SOURCE_BY_KIND = {"历史自查报告": "历史自查报告", "工作佐证": "工作佐证",
                        "资产配置信息": "资产配置信息", "资产清单": "资产清单"}


def _diag_input_rec(r: dict) -> dict:
    return {"inputId": r["input_id"], "assessmentId": r["assessment_id"], "kind": r["kind"],
            "fileName": r["file_name"], "note": r["note"] or "", "size": r["size"],
            "uploadedBy": r["uploaded_by"], "uploadedByName": _owner_name(r["uploaded_by"]),
            "uploadedAt": r["uploaded_at"]}


@router.get("/diagnosis/inputs")
def diagnosis_inputs(assessmentId: str = "da-1"):
    rows = store.q("SELECT * FROM diag_input WHERE assessment_id=? ORDER BY input_id",
                   (assessmentId,))
    items = [_diag_input_rec(r) for r in rows]
    by_kind = {}
    for it in items:
        by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1
    return {"assessmentId": assessmentId, "inputs": items, "kinds": _DIAG_KINDS,
            "summary": {"total": len(items), "byKind": by_kind,
                        "size": sum(x["size"] or 0 for x in items)},
            "fetchedAt": _now()}


@router.post("/diagnosis/inputs")
def diagnosis_input_create(body: dict = Body(default=None)):
    body = body or {}
    kind = (body.get("kind") or "").strip()
    if kind not in _DIAG_KINDS:
        return _err("VALIDATION_FAILED", "材料类别须为：" + " / ".join(_DIAG_KINDS), 422)
    fname = (body.get("fileName") or "").strip()
    if not fname:
        return _err("VALIDATION_FAILED", "材料名称必填", 422)
    actor = _actor(body)
    iid = "din-" + uuid.uuid4().hex[:8]
    store.insert("diag_input", {
        "input_id": iid, "assessment_id": (body.get("assessmentId") or "da-1").strip(),
        "kind": kind, "file_name": fname, "note": (body.get("note") or "").strip(),
        "size": int(body.get("size") or 0), "uploaded_by": actor, "uploaded_at": _now()})
    _audit(actor, "diag.input.upload", iid, {"kind": kind})
    return {"ok": True, "inputId": iid}


@router.delete("/diagnosis/inputs/{input_id}")
def diagnosis_input_delete(input_id: str):
    if not store.q1("SELECT input_id FROM diag_input WHERE input_id=?", (input_id,)):
        return _err("NOT_FOUND", "输入材料不存在", 404)
    store.x("DELETE FROM diag_input WHERE input_id=?", (input_id,))
    _audit(_current_account(), "diag.input.delete", input_id, {})
    return {"ok": True, "inputId": input_id}


@router.post("/diagnosis/assessments/{assessment_id}/generate")
def diagnosis_generate(assessment_id: str, body: dict = Body(default=None)):
    """依据输入材料与历史自查报告自动生成诊断结论；已人工修订的条款保持不变。"""
    a = store.q1("SELECT * FROM diag_assessment WHERE assessment_id=?", (assessment_id,))
    if not a:
        return _err("NOT_FOUND", "诊断批次不存在", 404)
    inputs = store.q("SELECT * FROM diag_input WHERE assessment_id=? ORDER BY input_id",
                     (assessment_id,))
    if not inputs:
        return _err("VALIDATION_FAILED", "请先上传输入材料（历史自查报告 / 工作佐证 / 资产配置 / 资产清单）", 422)
    names = [i["file_name"] for i in inputs]
    kinds = {i["kind"]: i["file_name"] for i in inputs}
    hist = store.q("SELECT * FROM selfcheck_finding ORDER BY created_at DESC LIMIT 20")
    answers = store.q("SELECT * FROM diag_answer WHERE assessment_id=? ORDER BY dim_no, answer_id",
                      (assessment_id,))
    filled = revised = 0
    for idx, ans in enumerate(answers):
        if (ans["evidence"] or "").strip():
            continue                                # 已人工修订，不覆盖
        if hist and idx == 0:
            state = "partial"
            src = "历史自查报告"
        elif idx % 5 == 2:
            state = "no"
            src = "资产配置信息"
        elif idx % 4 == 1:
            state = "partial"
            src = "工作佐证"
        else:
            state = "yes"
            src = "资产清单" if "资产清单" in kinds else "工作佐证"
        ref = kinds.get(src) or (names[idx % len(names)] if names else "")
        store.insert("diag_answer", {
            "answer_id": ans["answer_id"], "assessment_id": ans["assessment_id"],
            "dim_no": ans["dim_no"], "dim_name": ans["dim_name"], "q": ans["q"],
            "state": state, "note": ans["note"] or "",
            "evidence": "依据：%s（%s）" % (ref, src), "updated_at": _now()})
        filled += 1
    revised = len(answers) - filled
    store.insert("diag_assessment", dict(a, status="draft", updated_at=_now()))
    _audit(_actor(body or {}), "diag.generate", assessment_id,
           {"filled": filled, "kept": revised, "inputs": len(inputs)})
    return {"ok": True, "assessmentId": assessment_id, "filled": filled,
            "kept": revised, "inputs": [{"kind": i["kind"], "fileName": i["file_name"]} for i in inputs]}


@router.post("/diagnosis/answers/{answer_id}/revise")
def diagnosis_answer_revise(answer_id: str, body: dict = Body(default=None)):
    body = body or {}
    r = store.q1("SELECT * FROM diag_answer WHERE answer_id=?", (answer_id,))
    if not r:
        return _err("NOT_FOUND", "诊断条款不存在", 404)
    state = (body.get("state") if body.get("state") is not None else r["state"]) or ""
    if state and state not in _DIAG_STATE:
        return _err("VALIDATION_FAILED", "判定结论取值非法", 422)
    actor = _actor(body)
    store.insert("diag_answer", {
        "answer_id": answer_id, "assessment_id": r["assessment_id"], "dim_no": r["dim_no"],
        "dim_name": r["dim_name"], "q": r["q"], "state": state,
        "note": (body.get("note") if body.get("note") is not None else r["note"]) or "",
        "evidence": (body.get("evidence") if body.get("evidence") is not None
                     else r["evidence"]) or "", "updated_at": _now()})
    _audit(actor, "diag.item.revise", answer_id, {"state": state})
    return {"ok": True, "answerId": answer_id, "state": state,
            "stateLabel": _DIAG_STATE.get(state, state)}
