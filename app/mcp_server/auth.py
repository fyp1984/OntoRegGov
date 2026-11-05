#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app/mcp_server/auth.py — 远程模式 Bearer API Key 白名单鉴权（与底座知识库工程同一范式）。

设计：
- allowlist 文件 app/mcp_server/config/allowlist.json 为一个 list，条目含
  key/name/email/org/enabled/expires_at/rpm/scope/note。
- 按文件 mtime 缓存，allowlist.json 增删改后无需重启即生效。
- ASGI 中间件包裹 FastMCP 的 streamable_http_app：
    * GET /health -> 200 JSON，免鉴权；
    * POST <mcp_path> -> 校验 Authorization: Bearer <key>；
      未带 / 不存在 / disabled / 已过期 -> 401；超过 rpm -> 429。
- 错误响应不泄露 key 是否存在等任何信息。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

CONFIG_DIR = Path(__file__).resolve().parent / "config"
ALLOWLIST_PATH = CONFIG_DIR / "allowlist.json"


class Allowlist:
    """按 mtime 缓存的白名单读取器。"""

    def __init__(self, path: Path = ALLOWLIST_PATH):
        self.path = path
        self._mtime: float | None = None
        self._by_key: dict[str, dict[str, Any]] = {}

    def _reload_if_changed(self) -> None:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            if self._mtime is not None or self._by_key:
                self._mtime = None
                self._by_key = {}
            return
        if self._mtime == mtime and self._by_key:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            by_key: dict[str, dict[str, Any]] = {}
            for item in data or []:
                k = item.get("key")
                if k:
                    by_key[k] = item
            self._by_key = by_key
            self._mtime = mtime
        except Exception:  # noqa: BLE001
            pass

    def lookup(self, key: str) -> dict[str, Any] | None:
        self._reload_if_changed()
        return self._by_key.get(key)


class RateLimiter:
    def __init__(self, window_sec: int = 60):
        self._window = window_sec
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str, rpm: int) -> bool:
        if rpm <= 0:
            return True
        now = time.time()
        start = now - self._window
        hits = [t for t in self._hits.get(key, []) if t >= start]
        if len(hits) >= rpm:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True


class Unauthorized(Exception):
    pass


class RateLimited(Exception):
    pass


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    return auth[7:].strip() or None


def validate_key(allowlist: Allowlist, limiter: RateLimiter,
                 key: str | None) -> dict[str, Any]:
    if not key:
        raise Unauthorized()
    entry = allowlist.lookup(key)
    if not entry:
        raise Unauthorized()
    if not entry.get("enabled", False):
        raise Unauthorized()
    expires = entry.get("expires_at")
    if expires:
        try:
            from datetime import date
            exp_date = date.fromisoformat(str(expires)[:10])
            if date.today() > exp_date:
                raise Unauthorized()
        except ValueError:
            raise Unauthorized()
    rpm = int(entry.get("rpm", 0) or 0)
    if not limiter.allow(key, rpm):
        raise RateLimited()
    return entry


class AuthMiddleware:
    def __init__(self, app, mcp_path: str = "/mcp", health_path: str = "/health"):
        self.app = app
        self.mcp_path = mcp_path.rstrip("/") or "/"
        self.health_path = health_path
        self.allowlist = Allowlist()
        self.limiter = RateLimiter()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        path = request.url.path.rstrip("/") or "/"

        if path == self.health_path.rstrip("/"):
            resp = JSONResponse({
                "status": "ok",
                "service": "dsec-platform-mcp",
                "time": int(time.time()),
            })
            await resp(scope, receive, send)
            return

        # 根路径：服务信息页（让 http://host:port/ 可直接访问，不再 404）
        if path == "/" and request.method == "GET":
            resp = JSONResponse({
                "service": "dsec-platform-mcp",
                "status": "ok",
                "endpoints": {
                    "mcp": self.mcp_path + "（MCP 规范端点，需 Bearer）",
                    "health": self.health_path + "（免鉴权）",
                },
                "tools": ["dsec_control_gaps", "dsec_control_alignment", "dsec_check_detail",
                          "dsec_create_inspection_run", "dsec_record_check_result",
                          "dsec_graph_backend", "dsec_graph_sparql",
                          "dsec_search", "dsec_checks_by_doc",
                          "dsec_doc93_questionnaire", "dsec_law_qa"],
                "usage": f"Authorization: Bearer <key>（白名单见 config/allowlist.json），调用 MCP 端点 {self.mcp_path}",
                "time": int(time.time()),
            })
            await resp(scope, receive, send)
            return

        if path == self.mcp_path:
            try:
                key = _extract_bearer(request)
                validate_key(self.allowlist, self.limiter, key)
            except Unauthorized:
                resp = JSONResponse(
                    {"error": "unauthorized",
                     "message": "missing or invalid API key"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await resp(scope, receive, send)
                return
            except RateLimited:
                resp = JSONResponse(
                    {"error": "rate_limited",
                     "message": "too many requests, slow down"},
                    status_code=429,
                )
                await resp(scope, receive, send)
                return

        await self.app(scope, receive, send)
