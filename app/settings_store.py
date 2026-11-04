"""平台设置存储：SQLite 键值持久化（UI 可配置项）。

设计（对齐 EKOS 配置分层思想）：
- 环境变量 = 部署期默认（不可被本模块覆盖为空白，仅作为兜底来源）；
- 本库（app.db.llm_settings）= 运行时用户配置（前端保存后立即生效，无需重启）；
- 读取优先级：UI 已保存且值非空 → UI 值；否则 → env 兜底。
安全：GET 不返回明文 api_key，仅返回是否已设置与掩码；api_key 存本地 SQLite
（与本机 .env 同级信任），不随任何日志/响应输出。
"""
from __future__ import annotations
import os
import sqlite3
from contextlib import contextmanager
from .config import DB_PATH


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS llm_settings(key TEXT PRIMARY KEY, value TEXT, updatedAt TEXT)")
    return c


@contextmanager
def _cursor():
    c = _conn()
    try:
        yield c.cursor()
        c.commit()
    finally:
        c.close()


def _db_get(key: str) -> str | None:
    with _cursor() as cur:
        cur.execute("SELECT value FROM llm_settings WHERE key=?", (key,))
        row = cur.fetchone()
        return (row[0] if row else None) or ""


def _db_set(key: str, value: str) -> None:
    from datetime import datetime, timezone
    with _cursor() as cur:
        cur.execute(
            "INSERT OR REPLACE INTO llm_settings(key,value,updatedAt) VALUES(?,?,?)",
            (key, value.strip(), datetime.now(timezone.utc).isoformat(timespec="seconds")))


def get_runtime_llm() -> dict:
    """运行时 LLM 配置：UI 优先（值非空），env 兜底。返回 dict（含掩码 key）。"""
    ui_base = _db_get("llm_base_url")
    ui_key = _db_get("llm_api_key")
    ui_model = _db_get("llm_model")
    env_base = os.environ.get("OPENAI_BASE_URL", os.environ.get("OPENAI_API_BASE", "")).strip()
    env_key = os.environ.get("OPENAI_API_KEY", "").strip()
    env_model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()

    base_url = ui_base or env_base
    api_key = ui_key or env_key
    model = ui_model or env_model
    source = "db" if (ui_base or ui_key or ui_model) else "env"

    def mask(k: str) -> str:
        if not k:
            return ""
        return k[:4] + "****" + k[-4:] if len(k) > 8 else "****"

    return {
        "base_url": base_url,
        "api_key": api_key,
        "api_key_set": bool(api_key),
        "api_key_masked": mask(api_key),
        "model": model,
        "source": source,
        "ui_configured": bool(ui_base or ui_key or ui_model),
    }


def save_llm(payload: dict) -> dict:
    """保存 UI 配置；api_key 为空/未传则不更新（保留旧值）。"""
    base = (payload.get("base_url") or "").strip()
    key = (payload.get("api_key") or "").strip()
    model = (payload.get("model") or "").strip()
    if base:
        _db_set("llm_base_url", base)
    if key:
        _db_set("llm_api_key", key)
    if model:
        _db_set("llm_model", model)
    # 支持显式清空 base_url/model（api_key 不允许通过此接口清空，保护既有密钥）
    if "base_url" in payload and not base:
        _db_set("llm_base_url", "")
    if "model" in payload and not model:
        _db_set("llm_model", "")
    return get_runtime_llm()
