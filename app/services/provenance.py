"""why 溯源：条款/义务/控制/证据/规则/来源 的可读链。"""
from __future__ import annotations
import json
from ..db import db


def why(check_item_id: str) -> dict:
    with db() as conn:
        r = conn.execute("SELECT * FROM check_items WHERE id=?", (check_item_id,)).fetchone()
        if not r:
            return {}
        why = json.loads(r["whyJSON"])
        # 补来源文档
        why["source"] = "《银行保险机构数据安全管理办法》金规〔2024〕24号"
        return why
