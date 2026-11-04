"""不可变版本：每次 publish 生成版本号/时间/责任人/变更说明/来源/前后快照。"""
from __future__ import annotations
import json
import datetime
from ..db import db


def snapshot(entity_id: str, actor: str, change_note: str, source: str) -> int:
    with db() as conn:
        row = conn.execute("SELECT currentVersion,dataJSON,relationsJSON FROM entities WHERE id=?",
                           (entity_id,)).fetchone()
        if not row:
            raise ValueError(f"实体不存在: {entity_id}")
        new_ver = int(row["currentVersion"]) + 1
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO entity_versions(id,version,dataJSON,relationsJSON,actor,changeNote,source,createdAt) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (entity_id, new_ver, row["dataJSON"], row["relationsJSON"] or "[]",
             actor, change_note, source, ts))
        conn.execute("UPDATE entities SET currentVersion=?,updatedAt=?,updatedBy=? WHERE id=?",
                     (new_ver, ts, actor, entity_id))
    return new_ver


def versions_of(entity_id: str):
    with db() as conn:
        rows = conn.execute(
            "SELECT version,actor,changeNote,source,createdAt FROM entity_versions WHERE id=? ORDER BY version",
            (entity_id,)).fetchall()
        return [dict(r) for r in rows]


def diff(entity_id: str, v1: int, v2: int):
    with db() as conn:
        def load(v):
            r = conn.execute("SELECT dataJSON,relationsJSON FROM entity_versions WHERE id=? AND version=?",
                             (entity_id, v)).fetchone()
            return json.loads(r["dataJSON"]) if r else {}
        a, b = load(v1), load(v2)
    keys = sorted(set(a) | set(b))
    changes = []
    for k in keys:
        if a.get(k) != b.get(k):
            changes.append({"field": k, "before": a.get(k), "after": b.get(k)})
    return {"entity": entity_id, "v1": v1, "v2": v2, "changes": changes}
