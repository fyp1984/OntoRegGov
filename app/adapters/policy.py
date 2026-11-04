"""PolicyAdapter：权限继承占位（open-dev 实现）。本期不接 SpiceDB / OpenFGA。

对齐 EKOS PolicyAdapter（权限继承，EKOS 护城河）。本期只留接口占位：
- open-dev：单机演示一律放行；
- 将来接 SpiceDB / 飞书权限时，新增一个 PolicyAdapter 子类（如 spicedb/feishu）注册即可，主流程不动。
"""
from __future__ import annotations

from .base import Adapter


class PolicyAdapter(Adapter):
    kind = "policy"

    @property
    def name(self) -> str:
        return "open-dev"

    @property
    def version(self) -> str:
        return "0.1.0-placeholder"

    def health(self) -> dict:
        return {"status": "ok", "mode": "open-dev",
                "note": "开放模式，无策略限制；为权限继承预留（将来接 SpiceDB/飞书权限）"}

    def capabilities(self) -> list[str]:
        return ["policy.check"]   # 占位能力点

    def check(self, subject: str = "anon", resource: str = "*", action: str = "*") -> dict:
        """权限判定占位：一律放行。真实权限模型未来在此落地。"""
        return {"allow": True, "reason": "open-dev：开放模式一律放行（占位实现）",
                "subject": subject, "resource": resource, "action": action}

    def execute(self, payload: dict) -> dict:
        """SPI 统一入口。payload: {"subject","resource","action"}。"""
        return self.check(payload.get("subject", "anon"),
                          payload.get("resource", "*"),
                          payload.get("action", "*"))
