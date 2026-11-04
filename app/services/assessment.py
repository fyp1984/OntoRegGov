"""确定性判定引擎：合规结论唯一来源。
asset -> 适用义务 -> control -> 证据比对 -> conform/partial/nonconform/unknown + why。
mandatory 无 control -> unknown 且自动生成 KnowledgeGapProposal。
"""
from __future__ import annotations
import json, datetime, uuid
from ..db import db
from . import audit

# 分类分级 -> 应适用义务的确定性映射表（MVP：按资产分级补充适用集）
CLASSIFICATION_OBLIGATIONS = {
    "important": ["ob-o8-baogaojilu"],   # 重要数据额外适用 §71 目录报备
    "core": ["ob-o8-baogaojilu"],
}


def _entity(conn, eid):
    r = conn.execute("SELECT * FROM entities WHERE id=?", (eid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["data"] = json.loads(d["dataJSON"])
    d["relations"] = json.loads(d["relationsJSON"])
    return d


def _obligations_of_asset(conn, asset):
    data = asset["data"]
    obs = list(data.get("governed_by", []))
    # 按分级映射补充
    cls = data.get("hasClassification", "")
    if isinstance(cls, str):
        slug = cls.replace("cls/", "")
        obs += CLASSIFICATION_OBLIGATIONS.get(slug, [])
    # 去重
    seen, uniq = set(), []
    for o in obs:
        if o not in seen:
            seen.add(o); uniq.append(o)
    return uniq


def _controls_for_obligation(conn, obs_code):
    rows = conn.execute(
        "SELECT id FROM entities WHERE type='Control' AND status='published'").fetchall()
    out = []
    for r in rows:
        c = _entity(conn, r["id"])
        impl = c["data"].get("implementsObligation", [])
        if isinstance(impl, str):
            impl = [impl]
        # implementsObligation 存的是 'Obligation:ob-xx'
        if any(x.endswith(obs_code) or x == obs_code for x in impl):
            out.append(c)
    return out


def run_assessment(asset_id: str, actor: str = "system") -> dict:
    conn_cm = db()
    conn = conn_cm.__enter__()
    try:
        asset = _entity(conn, asset_id)
        if not asset or asset["type"] != "DataAsset":
            raise ValueError(f"数据资产不存在: {asset_id}")
        run_id = f"asm-{uuid.uuid4().hex[:8]}"
        ran_at = datetime.datetime.now().isoformat(timespec="seconds")
        check_items, findings, remediations, proposals = [], [], [], []

        obs_codes = _obligations_of_asset(conn, asset)
        for obs_ref in obs_codes:
            obs_code = obs_ref.split(":")[-1]
            obs = None
            for r in conn.execute("SELECT id FROM entities WHERE type='Obligation' AND status='published'").fetchall():
                if r["id"] == obs_code:
                    obs = _entity(conn, r["id"]); break
            if not obs:
                continue
            obs_text = obs["data"].get("text", "")
            force = obs["data"].get("force", "mandatory")
            controls = _controls_for_obligation(conn, obs_code)

            if not controls:
                # 裸义务：mandatory -> unknown + 自动提案；recommended -> unknown 不提案
                ci = _make_check(conn, run_id, asset, obs, None, "unknown",
                                 rule="R-GAP", detail="该义务无对应控制项（裸义务），无法判定，已生成知识缺口提案",
                                 evidence=[{"requirement": None, "requirementName": None,
                                            "record": None, "status": "n/a",
                                            "note": "无控制项，故无证据要求可对照"}])
                check_items.append(ci)
                if force == "mandatory":
                    # 去重：同一 obligation 已存在 open/in_review 提案则复用，不重复新建
                    existing = conn.execute(
                        "SELECT id FROM proposals WHERE status IN ('open','in_review') "
                        "AND payloadJSON LIKE ?", (f'%"obligation": "{obs_code}"%',)).fetchone()
                    if existing:
                        prop_id = existing["id"]
                    else:
                        prop_id = f"prop-{uuid.uuid4().hex[:8]}"
                        proposals.append({
                            "id": prop_id, "reason": f"强制义务 {obs_code}（{obs_text[:30]}）无任何控制项，需补控制规则",
                            "status": "open", "targetKind": "Control",
                            "raisedFrom": ci["id"], "payload": {"obligation": obs_code}})
                    check_items[-1]["proposalId"] = prop_id
                continue

            for ctrl in controls:
                result, why_detail = _evaluate_control(conn, asset, obs, ctrl)
                ci = _make_check(conn, run_id, asset, obs, ctrl, result,
                                 rule="R-EVIDENCE", detail=why_detail["detail"],
                                 evidence=why_detail["evidence"])
                check_items.append(ci)
                if result == "nonconform":
                    f = {
                        "id": f"find-{uuid.uuid4().hex[:8]}", "checkItemId": ci["id"],
                        "severity": "high", "gapKind": "missing_evidence",
                        "detail": why_detail["detail"], "status": "open"}
                    findings.append(f)
                    remediations.append({
                        "id": f"rem-{uuid.uuid4().hex[:8]}", "findingId": f["id"],
                        "action": f"补充证据: {why_detail['detail']}",
                        "dueDate": "", "status": "open"})

        overall = _overall(check_items)
        summary = {"asset": asset["data"].get("name"),
                   "counts": _counts(check_items)}
        conn.execute(
            "INSERT INTO assessments(runId,assetId,ranAt,overall,summaryJSON) VALUES(?,?,?,?,?)",
            (run_id, asset_id, ran_at, overall, json.dumps(summary, ensure_ascii=False)))
        for ci in check_items:
            conn.execute(
                "INSERT INTO check_items(id,runId,assetId,obligationCode,controlCode,result,whyJSON) VALUES(?,?,?,?,?,?,?)",
                (ci["id"], run_id, asset_id, ci["obligationCode"], ci["controlCode"],
                 ci["result"], json.dumps(ci["why"], ensure_ascii=False)))
        for f in findings:
            conn.execute("INSERT INTO findings VALUES(?,?,?,?,?,?)",
                         (f["id"], f["checkItemId"], f["severity"], f["gapKind"], f["detail"], f["status"]))
        for rm in remediations:
            conn.execute("INSERT INTO remediations VALUES(?,?,?,?,?)",
                         (rm["id"], rm["findingId"], rm["action"], rm["dueDate"], rm["status"]))
        for p in proposals:
            conn.execute("INSERT INTO proposals(id,reason,status,targetKind,raisedFrom,payloadJSON,reviewer,decidedAt,createdAt) VALUES(?,?,?,?,?,?,?,?,?)",
                         (p["id"], p["reason"], p["status"], p["targetKind"], p["raisedFrom"],
                          json.dumps(p["payload"], ensure_ascii=False), None, None,
                          datetime.datetime.now().isoformat(timespec="seconds")))
        result = {"runId": run_id, "assetId": asset_id, "overall": overall,
                  "ranAt": ran_at, "checkItems": check_items, "findings": findings,
                  "proposals": proposals, "summary": summary}
    finally:
        conn_cm.__exit__(None, None, None)
    audit.log(actor, "assessment.run", asset_id, {"runId": run_id, "overall": overall})
    return result


def _make_check(conn, run_id, asset, obs, ctrl, result, rule, detail, evidence=None):
    obs_code = obs["id"]
    ctrl_code = ctrl["id"] if ctrl else None
    clause_ref = obs["data"].get("clauseOf", "")
    why = {
        "ruleId": rule,
        "law": "金规〔2024〕24号",
        "clauseNo": clause_ref,
        "obligation": obs_code,
        "obligationText": obs["data"].get("text", ""),
        "control": ctrl_code,
        "controlTitle": ctrl["data"].get("title") if ctrl else None,
        "asset": asset["id"],
        "assetName": asset["data"].get("name"),
        "evidence": evidence if evidence is not None else [],
        "detail": detail,
    }
    return {"id": f"ci-{uuid.uuid4().hex[:8]}", "runId": run_id,
            "assetId": asset["id"], "obligationCode": obs_code,
            "controlCode": ctrl_code, "result": result, "why": why}


def _evaluate_control(conn, asset, obs, ctrl):
    reqs = ctrl["data"].get("requiresEvidence", [])
    if isinstance(reqs, str):
        reqs = [reqs]
    req_codes = [r.split(":")[-1] for r in reqs]
    # 资产证据记录
    records = []
    for r in conn.execute("SELECT id,dataJSON FROM entities WHERE type='EvidenceRecord' AND status='published'").fetchall():
        d = json.loads(r["dataJSON"])
        if d.get("asset") == asset["id"] or asset["id"] in (d.get("assets") or []):
            records.append((r["id"], d))
    evidence = []
    satisfied = 0
    for rc in req_codes:
        req_name = ""
        rr = conn.execute("SELECT dataJSON FROM entities WHERE id=? AND type='EvidenceRequirement'",
                          (rc,)).fetchone()
        if rr:
            req_name = json.loads(rr["dataJSON"]).get("name", "")
        hit = [rid for rid, d in records
               if d.get("fulfillsRequirement", "").endswith(rc)
               and d.get("status") == "provided"]
        if hit:
            satisfied += 1
            for rid in hit:
                rd = dict(records)[rid] if False else next(d for x, d in records if x == rid)
                evidence.append({"requirement": rc, "requirementName": req_name,
                                 "record": rid, "recordName": rd.get("name"),
                                 "status": "provided", "locator": rd.get("locator")})
        else:
            evidence.append({"requirement": rc, "requirementName": req_name,
                             "record": None, "recordName": None,
                             "status": "missing", "locator": None})
    missing = [e["requirement"] for e in evidence if e["status"] == "missing"]
    detail = f"证据要求 {len(req_codes)} 项，满足 {satisfied} 项"
    if missing:
        detail += f"；缺: {', '.join(missing)}"
    else:
        detail += "；全部证据 provided"
    if satisfied == len(req_codes) and req_codes:
        return "conform", {"detail": detail, "evidence": evidence}
    if satisfied > 0:
        return "partial", {"detail": detail, "evidence": evidence}
    return "nonconform", {"detail": detail, "evidence": evidence}


def _overall(items):
    if any(i["result"] == "nonconform" for i in items):
        return "noncompliant"
    if any(i["result"] in ("partial", "unknown") for i in items):
        return "partial"
    if items:
        return "compliant"
    return "noncompliant"


def _counts(items):
    c = {"conform": 0, "partial": 0, "nonconform": 0, "unknown": 0}
    for i in items:
        c[i["result"]] = c.get(i["result"], 0) + 1
    return c


def get_assessment(run_id: str):
    with db() as conn:
        a = conn.execute("SELECT * FROM assessments WHERE runId=?", (run_id,)).fetchone()
        if not a:
            return None
        items = conn.execute("SELECT * FROM check_items WHERE runId=?", (run_id,)).fetchall()
        out = dict(a)
        out["summary"] = json.loads(out["summaryJSON"])
        out["checkItems"] = []
        for it in items:
            d = dict(it); d["why"] = json.loads(d["whyJSON"]); out["checkItems"].append(d)
        return out


def compare(run1: str, run2: str):
    a, b = get_assessment(run1), get_assessment(run2)
    if not a or not b:
        return None
    by_obs1 = {i["obligationCode"]: i["result"] for i in a["checkItems"]}
    by_obs2 = {i["obligationCode"]: i["result"] for i in b["checkItems"]}
    rows = []
    for obs in sorted(set(by_obs1) | set(by_obs2)):
        rows.append({"obligation": obs, "before": by_obs1.get(obs, "—"),
                     "after": by_obs2.get(obs, "—")})
    return {"beforeRun": run1, "afterRun": run2,
            "beforeOverall": a["overall"], "afterOverall": b["overall"],
            "changed": rows}
