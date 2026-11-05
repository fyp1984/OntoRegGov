"""审核：候选/实体 批准→发布(SHACL闸门+版本)、修改、拒绝、合并。"""
from __future__ import annotations
import json, uuid, datetime
from ..db import db
from ..ontology import shacl_validator
from . import gate, versioning, audit, run_db


def create_entity(etype: str, eid: str, data: dict, relations: list,
                  actor: str, source: str = "manual") -> dict:
    """创建待审核实体（candidate），并生成 review_task。"""
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    with db() as conn:
        conn.execute(
            "INSERT INTO entities(id,type,status,currentVersion,dataJSON,relationsJSON,updatedAt,updatedBy) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (eid, etype, "candidate", 0, json.dumps(data, ensure_ascii=False),
             json.dumps(relations, ensure_ascii=False), ts, actor))
        tid = f"rt-{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO review_tasks(id,targetType,targetId,status,note,reviewer,createdBy,createdAt) VALUES(?,?,?,?,?,?,?,?)",
            ("entity", "entity", eid, "pending_review", "", None, actor, ts)
            if False else
            (tid, "entity", eid, "pending_review", "", None, actor, ts))
    audit.log(actor, "entity.create_candidate", eid, {"type": etype, "source": source})
    run_db.mirror_review_task({"task_id": tid, "target_type": "entity", "target_id": eid,
                               "status": "pending_review", "reviewer": None, "note": "",
                               "created_by": actor, "created_at": ts, "decided_at": ""})
    return {"id": eid, "status": "candidate", "reviewTaskId": tid}


def queue():
    with db() as conn:
        tasks = conn.execute(
            "SELECT * FROM review_tasks WHERE status='pending_review' ORDER BY createdAt").fetchall()
        out = []
        for t in tasks:
            d = dict(t)
            ent = conn.execute("SELECT type,dataJSON,status FROM entities WHERE id=?",
                               (d["targetId"],)).fetchone()
            if ent:
                d["entityType"] = ent["type"]
                d["title"] = (json.loads(ent["dataJSON"]).get("title")
                              or json.loads(ent["dataJSON"]).get("code")
                              or d["targetId"])
            else:
                # 自动抽取候选（targetType=candidate）：显示候选标签与出处
                cand = conn.execute("SELECT kind,label,confidence,provenance,span FROM candidates WHERE id=?",
                                    (d["targetId"],)).fetchone()
                d["entityType"] = cand["kind"] if cand else d["targetType"]
                d["title"] = (cand["label"] + ("〔自动候选·" + cand["provenance"] + "〕")) if cand else d["targetId"]
            out.append(d)
        # 合并提案视图
        props = conn.execute("SELECT * FROM proposals WHERE status='open' OR status='in_review'").fetchall()
        for p in props:
            d = dict(p); d["kind"] = "proposal"
            out.append(d)
        return out


def decide(task_id: str, actor: str, action: str, note: str = "", edits: dict | None = None) -> dict:
    """action: approved / rejected / needs_changes / merged。"""
    audit_action, audit_params, shacl_block = None, None, None
    approved_new_entity = None
    with db() as conn:
        t = conn.execute("SELECT * FROM review_tasks WHERE id=?", (task_id,)).fetchone()
        if not t:
            raise ValueError(f"审核任务不存在: {task_id}")
        gate.check_review_separation(actor, t["createdBy"])
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        target_type, target_id = t["targetType"], t["targetId"]

        if action == "rejected":
            conn.execute("UPDATE review_tasks SET status='rejected',note=?,reviewer=?,decidedAt=? WHERE id=?",
                         (note, actor, ts, task_id))
            conn.execute("UPDATE entities SET status='rejected' WHERE id=?", (target_id,))
            audit_action, audit_params = "review.reject", {"task": task_id}

        elif action in ("needs_changes", "merged"):
            conn.execute("UPDATE review_tasks SET status=?,note=?,reviewer=?,decidedAt=? WHERE id=?",
                         (action, note, actor, ts, task_id))
            audit_action, audit_params = f"review.{action}", {"task": task_id}

        elif target_type == "candidate":
            # 自动抽取候选：批准 → 按 payload 物化实体并过 SHACL 闸门
            cand = conn.execute("SELECT * FROM candidates WHERE id=?", (target_id,)).fetchone()
            if not cand:
                raise ValueError(f"候选不存在: {target_id}")
            gate.check_candidate_reviewed(cand["provenance"], True, cand["confidence"])
            etype = cand["mappedClass"] or cand["kind"]
            payload = json.loads(cand["payloadJSON"] or "{}")
            data = dict(payload)
            data.setdefault("code", target_id)
            if etype != "Obligation":
                data.setdefault("title", cand["label"])
            relations = []
            if etype == "Obligation":
                data.setdefault("text", cand["span"])
                data.setdefault("force", "mandatory")
                data.setdefault("clauseOf", "Clause:cl-16")
                relations = [{"p": "clauseOf", "o": data["clauseOf"]}]
            new_id = f"{etype.lower()}-{target_id}"
            result = shacl_validator.validate_entity(etype, new_id, data, relations)
            if not result["conforms"]:
                conn.execute("UPDATE review_tasks SET status='rejected',note=?,reviewer=?,decidedAt=? WHERE id=?",
                             ("SHACL未通过(需补全字段): " + "; ".join(result["messages"]), actor, ts, task_id))
                conn.execute("UPDATE candidates SET status='rejected' WHERE id=?", (target_id,))
                audit_action = "review.blocked_shacl"; audit_params = {"messages": result["messages"]}
                shacl_block = result["messages"]
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO entities(id,type,status,currentVersion,dataJSON,relationsJSON,updatedAt,updatedBy) VALUES(?,?,?,?,?,?,?,?)",
                    (new_id, etype, "published", 0, json.dumps(data, ensure_ascii=False),
                     json.dumps(relations, ensure_ascii=False), ts, actor))
                conn.execute("UPDATE candidates SET status='approved' WHERE id=?", (target_id,))
                conn.execute("UPDATE review_tasks SET status='approved',note=?,reviewer=?,decidedAt=? WHERE id=?",
                             (note, actor, ts, task_id))
                audit_action = "candidate.publish"; audit_params = {"entity": new_id, "candidate": target_id}
                approved_new_entity = new_id

        else:  # approved -> SHACL 闸门 -> published + 版本
            ent = conn.execute("SELECT * FROM entities WHERE id=?", (target_id,)).fetchone()
            if not ent:
                raise ValueError(f"目标不存在: {target_id}")
            data = json.loads(ent["dataJSON"])
            relations = json.loads(ent["relationsJSON"])
            result = shacl_validator.validate_entity(ent["type"], target_id, data, relations)
            if not result["conforms"]:
                conn.execute("UPDATE review_tasks SET status='rejected',note=?,reviewer=?,decidedAt=? WHERE id=?",
                             ("SHACL校验未通过: " + "; ".join(result["messages"]), actor, ts, task_id))
                audit_action = "review.blocked_shacl"
                audit_params = {"messages": result["messages"]}
                shacl_block = result["messages"]
            else:
                conn.execute("UPDATE entities SET status='published' WHERE id=?", (target_id,))
                conn.execute("UPDATE review_tasks SET status='approved',note=?,reviewer=?,decidedAt=? WHERE id=?",
                             (note, actor, ts, task_id))
                audit_action = "review.approve"
                audit_params = {"task": task_id}
    # audit 在事务块外写，避免嵌套写连接
    if audit_action:
        audit.log(actor, audit_action, target_id, audit_params)
    # 影子镜像审核任务终态（best-effort，PG 运行库；失败不影响主流程）
    try:
        with db() as conn:
            tr = conn.execute("SELECT * FROM review_tasks WHERE id=?", (task_id,)).fetchone()
        if tr:
            td = dict(tr)
            run_db.mirror_review_task({"task_id": td["id"], "target_type": td.get("targetType"),
                                       "target_id": td.get("targetId"), "status": td.get("status"),
                                       "reviewer": td.get("reviewer"), "note": td.get("note"),
                                       "created_by": td.get("createdBy"),
                                       "created_at": td.get("createdAt") or "",
                                       "decided_at": td.get("decidedAt") or ""})
    except Exception:  # noqa: BLE001
        pass
    if shacl_block:
        raise gate.GateError("SHACL 校验未通过，拒绝发布", {"messages": shacl_block})
    if action == "rejected":
        return {"ok": True, "status": "rejected"}
    if action in ("needs_changes", "merged"):
        return {"ok": True, "status": action}
    snap_target = approved_new_entity or target_id
    ver = versioning.snapshot(snap_target, actor, note or "审核通过发布", source="review")
    audit.log(actor, "review.approve", snap_target, {"task": task_id, "version": ver})
    return {"ok": True, "status": "approved", "version": ver, "entity": snap_target}


def approve_candidate_as_entity(cand_id: str, reviewer: str,
                                mapped_data: dict, relations: list,
                                etype: str, eid: str) -> dict:
    """自动候选经人工复核后物化发布（AI 候选未复核拦截在此强制）。"""
    with db() as conn:
        c = conn.execute("SELECT * FROM candidates WHERE id=?", (cand_id,)).fetchone()
        if not c:
            raise ValueError(f"候选不存在: {cand_id}")
        # 门禁：自动候选必须有复核决策
        has_decision = conn.execute(
            "SELECT 1 FROM review_tasks WHERE targetId=? AND status='approved'",
            (cand_id,)).fetchone() is not None
        gate.check_candidate_reviewed(c["provenance"], has_decision, c["confidence"])
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO entities(id,type,status,currentVersion,dataJSON,relationsJSON,updatedAt,updatedBy) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (eid, etype, "published", 0, json.dumps(mapped_data, ensure_ascii=False),
             json.dumps(relations, ensure_ascii=False), ts, reviewer))
        conn.execute("UPDATE candidates SET status='approved' WHERE id=?", (cand_id,))
    ver = versioning.snapshot(eid, reviewer, "候选复核通过发布", source=f"candidate:{cand_id}")
    audit.log(reviewer, "candidate.publish_reviewed", eid, {"candidate": cand_id, "version": ver})
    return {"id": eid, "status": "published", "version": ver}
