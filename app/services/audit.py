"""行动层留痕：所有受控写操作全量写 audit_log。"""
from __future__ import annotations
import json
import datetime
from ..db import db


def log(actor: str, action: str, target: str = "", params: dict | None = None) -> None:
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    with db() as conn:
        conn.execute(
            "INSERT INTO audit_log(ts,actor,action,target,paramsJSON) VALUES(?,?,?,?,?)",
            (ts, actor, action, target, json.dumps(params or {}, ensure_ascii=False)),
        )


def recent(limit: int = 50):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
