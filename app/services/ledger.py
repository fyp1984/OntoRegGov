# -*- coding: utf-8 -*-
"""v1.3.0 多人检查台账与周期复查服务。
- 检查计划 InspectionPlan：范围/周期/负责人/覆盖检查项 → 台账与周期复查的挂靠点。
- 多人检查：InspectionRun 挂 planId + assignees（多人分工）。
- 证据归档：inspection_evidence（runId/checkCode/文件元数据）。
- 复核签署：inspection_signoffs（签署人/角色/结论/意见）。
- 台账聚合：get_ledger() 把每次运行沉淀为台账条目（结果汇总/签署/证据/下次复查）。
周期复查：按计划周期与最近运行时间推算 nextRecheck（monthly/quarterly/half-yearly/yearly）。
"""
from __future__ import annotations
import json, uuid, datetime
from ..db import db
from . import audit
from . import run_db

CYCLES = {"monthly": 30, "quarterly": 90, "half-yearly": 180, "yearly": 365}


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _days(cycle: str) -> int:
    return CYCLES.get((cycle or "").strip().lower(), 0)


def create_plan(name: str, scope: str, cycle: str = "quarterly",
                start_date: str = "", end_date: str = "", owner: str = "",
                checks: list = None, actor: str = "reviewer") -> dict:
    pid = f"ipl-{uuid.uuid4().hex[:6]}"
    ts = _now()
    with db() as conn:
        conn.execute(
            "INSERT INTO inspection_plans(id,name,scope,cycle,startDate,endDate,status,owner,checkScopeJSON,createdAt,updatedAt) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (pid, name, scope, cycle, start_date, end_date, "active", owner,
             json.dumps(checks or [], ensure_ascii=False), ts, ts))
    audit.log(actor, "inspection.plan.create", pid, {"name": name, "cycle": cycle, "checks": len(checks or [])})
    run_db.mirror_plan({"plan_id": pid, "name": name, "scope": scope, "cycle": cycle,
                        "owner": owner, "check_scope": checks or [], "status": "active",
                        "start_date": start_date, "end_date": end_date,
                        "created_at": ts, "updated_at": ts})
    return {"planId": pid, "name": name, "scope": scope, "cycle": cycle, "status": "active"}


def list_plans() -> list:
    with db() as conn:
        rows = conn.execute("SELECT * FROM inspection_plans ORDER BY createdAt").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["checkScope"] = json.loads(d.pop("checkScopeJSON") or "[]")
        out.append(d)
    return out


def get_plan(plan_id: str) -> dict | None:
    with db() as conn:
        r = conn.execute("SELECT * FROM inspection_plans WHERE id=?", (plan_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["checkScope"] = json.loads(d.pop("checkScopeJSON") or "[]")
        # 计划下的运行（多人/结果汇总）
        runs = conn.execute("SELECT id,dataJSON FROM entities WHERE type='InspectionRun' AND dataJSON LIKE ?",
                            (f'%"planId": "{plan_id}"%',)).fetchall()
        d["runs"] = []
        for rr in runs:
            rd = json.loads(rr["dataJSON"])
            d["runs"].append(_run_brief(conn, rr["id"], rd))
        return d


def _run_brief(conn, run_id: str, rd: dict) -> dict:
    results = conn.execute("SELECT dataJSON FROM entities WHERE type='CheckResult' AND dataJSON LIKE ?",
                           (f'%"resultRun": "InspectionRun:{run_id}"%',)).fetchall()
    counts = {"pass": 0, "partial": 0, "fail": 0}
    for cr in results:
        cd = json.loads(cr["dataJSON"])
        counts[cd.get("result", "pass")] = counts.get(cd.get("result", "pass"), 0) + 1
    ev = conn.execute("SELECT COUNT(*) n FROM inspection_evidence WHERE runId=?", (run_id,)).fetchone()
    sg = conn.execute("SELECT signer,role,decision,comment,signedAt FROM inspection_signoffs "
                      "WHERE runId=? ORDER BY signedAt DESC", (run_id,)).fetchone()
    return {"runId": run_id, "inspectedTarget": rd.get("inspectedTarget"),
            "inspector": rd.get("inspector"),
            "assignees": (rd.get("assignees") or "").split(",") if rd.get("assignees") else [],
            "ranAt": rd.get("ranAt"), "results": counts,
            "evidenceCount": ev["n"] if ev else 0,
            "signoff": dict(sg) if sg else None}


def attach_evidence(run_id: str, check_code: str, file_name: str, file_path: str,
                    uploaded_by: str, note: str = "") -> dict:
    eid = f"ev-{uuid.uuid4().hex[:8]}"
    ts = _now()
    with db() as conn:
        conn.execute(
            "INSERT INTO inspection_evidence(id,runId,checkCode,fileName,filePath,uploadedBy,note,uploadedAt) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (eid, run_id, check_code, file_name, file_path, uploaded_by, note, ts))
    audit.log(uploaded_by, "inspection.evidence.attach", eid,
              {"run": run_id, "check": check_code, "file": file_name})
    run_db.mirror_evidence({"evidence_id": eid, "run_id": run_id, "check_code": check_code,
                            "file_name": file_name, "file_path": file_path,
                            "uploaded_by": uploaded_by, "note": note, "uploaded_at": ts})
    return {"evidenceId": eid, "runId": run_id, "checkCode": check_code,
            "fileName": file_name, "uploadedBy": uploaded_by, "uploadedAt": ts}


def list_evidence(run_id: str = "") -> list:
    with db() as conn:
        if run_id:
            rows = conn.execute("SELECT * FROM inspection_evidence WHERE runId=? ORDER BY uploadedAt", (run_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM inspection_evidence ORDER BY uploadedAt").fetchall()
    out = [dict(r) for r in rows]
    for x in out:
        x["evidenceId"] = x.pop("id")
    return out


def sign_off(run_id: str, signer: str, role: str, decision: str,
             comment: str = "", actor: str = "reviewer") -> dict:
    """复核签署：decision ∈ approved(复核通过) / returned(退回补证)。"""
    sid = f"sg-{uuid.uuid4().hex[:8]}"
    ts = _now()
    with db() as conn:
        conn.execute(
            "INSERT INTO inspection_signoffs(id,runId,signer,role,decision,comment,signedAt) "
            "VALUES(?,?,?,?,?,?,?)",
            (sid, run_id, signer, role, decision, comment, ts))
    audit.log(actor, "inspection.signoff", run_id, {"signer": signer, "decision": decision})
    run_db.mirror_signoff({"signoff_id": sid, "run_id": run_id, "signer": signer, "role": role,
                           "decision": decision, "comment": comment, "signed_at": ts})
    return {"signoffId": sid, "runId": run_id, "signer": signer, "role": role,
            "decision": decision, "comment": comment, "signedAt": ts}


def _next_from(latest: str, cycle: str) -> str | None:
    days = _days(cycle or "")
    if not days or not latest:
        return None
    try:
        dt = datetime.datetime.fromisoformat(latest)
    except ValueError:
        return None
    return (dt + datetime.timedelta(days=days)).strftime("%Y-%m-%d")


def next_recheck(plan: dict) -> str | None:
    """周期复查测算：计划最近一次运行时间 + 周期天数 → 下次复查日期（YYYY-MM-DD）。"""
    if not plan.get("runs"):
        return None
    latest = max(r["ranAt"] for r in plan["runs"] if r.get("ranAt"))
    return _next_from(latest, plan.get("cycle", ""))


def get_ledger() -> dict:
    """机构检查台账：全部计划 + 全部运行（含未挂计划的运行），附下次复查。"""
    plans = list_plans()
    with db() as conn:
        runs = conn.execute("SELECT id,dataJSON FROM entities WHERE type='InspectionRun' ORDER BY updatedAt").fetchall()
        entries = []
        for r in runs:
            rd = json.loads(r["dataJSON"])
            brief = _run_brief(conn, r["id"], rd)
            brief["planId"] = rd.get("planId")
            entries.append(brief)
    plan_map = {p["id"]: p for p in plans}
    for e in entries:
        pid = e.get("planId")
        if pid and pid in plan_map:
            e["planName"] = plan_map[pid].get("name")
            e["cycle"] = plan_map[pid].get("cycle")
        else:
            e["planName"] = "（未挂计划）"
            e["cycle"] = ""
        e["nextRecheck"] = None
    # 周期复查日期按各计划最近运行推算（台账条目为事实源，不依赖 list_plans 携带 runs）
    for p in plans:
        pruns = [e for e in entries if e.get("planId") == p["id"] and e.get("ranAt")]
        latest = max((e["ranAt"] for e in pruns), default=None)
        p["nextRecheck"] = _next_from(latest, p.get("cycle", ""))
        for e in entries:
            if e.get("planId") == p["id"] and e["ranAt"] == latest:
                e["nextRecheck"] = p["nextRecheck"]
    return {"plans": plans, "entries": entries}


def run_status_summary(entry: dict) -> str:
    c = entry.get("results") or {}
    if c.get("fail"):
        return "fail"
    if c.get("partial"):
        return "partial"
    if c.get("pass"):
        return "pass"
    return "pending"
