"""知识缺口提案：accepted 时把提议内容转候选并走同一审核/入库/SHACL 流程。"""
from __future__ import annotations
import json, uuid, datetime
from ..db import db
from . import review, audit, gate, run_db


def create(reason: str, target_kind: str, raised_from: str, payload: dict, actor: str = "system") -> dict:
    pid = f"prop-{uuid.uuid4().hex[:8]}"
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    with db() as conn:
        conn.execute(
            "INSERT INTO proposals(id,reason,status,targetKind,raisedFrom,payloadJSON,createdAt) VALUES(?,?,?,?,?,?,?)",
            (pid, reason, "open", target_kind, raised_from, json.dumps(payload, ensure_ascii=False), ts))
    audit.log(actor, "proposal.create", pid, {"reason": reason})
    run_db.mirror_proposal({"proposal_id": pid, "reason": reason, "target_kind": target_kind,
                            "raised_from": raised_from, "status": "open", "payload": payload,
                            "reviewer": None, "decided_at": "", "created_at": ts})
    return {"id": pid, "status": "open"}


def list_proposals():
    with db() as conn:
        rows = conn.execute("SELECT * FROM proposals ORDER BY createdAt DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r); d["payload"] = json.loads(d["payloadJSON"] or "{}"); out.append(d)
        return out


def decide(prop_id: str, actor: str, decision: str, note: str = "") -> dict:
    """decision: accepted/rejected/closed。accepted -> 转候选实体入库。"""
    payload = None
    with db() as conn:
        p = conn.execute("SELECT * FROM proposals WHERE id=?", (prop_id,)).fetchone()
        if not p:
            raise ValueError(f"提案不存在: {prop_id}")
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        if decision == "accepted":
            conn.execute("UPDATE proposals SET status='accepted',reviewer=?,decidedAt=? WHERE id=?",
                         (actor, ts, prop_id))
            payload = json.loads(p["payloadJSON"] or "{}")
            run_db.mirror_proposal({"proposal_id": prop_id, "reason": p["reason"],
                                    "target_kind": p["targetKind"], "raised_from": p["raisedFrom"],
                                    "status": "accepted", "payload": payload,
                                    "reviewer": actor, "decided_at": ts,
                                    "created_at": p["createdAt"] or ""})
        else:
            conn.execute("UPDATE proposals SET status=?,reviewer=?,decidedAt=? WHERE id=?",
                         (decision, actor, ts, prop_id))
            run_db.mirror_proposal({"proposal_id": prop_id, "reason": p["reason"],
                                    "target_kind": p["targetKind"], "raised_from": p["raisedFrom"],
                                    "status": decision, "payload": p["payloadJSON"] or "{}",
                                    "reviewer": actor, "decided_at": ts,
                                    "created_at": p["createdAt"] or ""})
            audit.log(actor, f"proposal.{decision}", prop_id)
            return {"ok": True, "status": decision}
    # 块外创建实体，避免嵌套写连接
    created = []
    if payload.get("newControl"):
        c = payload["newControl"]
        created.append(review.create_entity(
            "Control", c["id"], c["data"], c.get("relations", []),
            actor="admin", source=f"proposal:{prop_id}"))
    if payload.get("newEvidenceRequirement"):
        e = payload["newEvidenceRequirement"]
        created.append(review.create_entity(
            "EvidenceRequirement", e["id"], e["data"], e.get("relations", []),
            actor="admin", source=f"proposal:{prop_id}"))
    audit.log(actor, "proposal.accept", prop_id, {"created": created})
    return {"ok": True, "status": "accepted", "created": created}
