#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app/mcp_server/server.py — 平台 MCP 服务（FastMCP 1.x）。

工具逻辑在 platform_tools.py（stdio / http 共用）。本文件按环境变量选择传输：

  MCP_TRANSPORT = stdio（默认）           本地命令行
                  streamable-http         远程 HTTP（供底座知识库工程 / 外部 MCP 客户端调用）

  MCP_HOST = 127.0.0.1（默认）
  MCP_PORT = 8422（默认）
  MCP_PATH = /mcp（默认）
  /health 健康检查（免鉴权）

远程模式对 /mcp 要求 Authorization: Bearer <key>，白名单 app/mcp_server/config/allowlist.json。
运行：python -m app.mcp_server.server
"""
from __future__ import annotations

import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from app.mcp_server.platform_tools import register as register_tools  # noqa: E402
from app.mcp_server.auth import AuthMiddleware  # noqa: E402

SERVICE_NAME = "dsec-platform"


def make_server() -> FastMCP:
    mcp = FastMCP(SERVICE_NAME)
    register_tools(mcp)
    return mcp


def run_stdio(mcp: FastMCP) -> None:
    mcp.run(transport="stdio")


def run_http(mcp: FastMCP) -> None:
    import uvicorn

    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8422"))
    path = os.environ.get("MCP_PATH", "/mcp") or "/mcp"

    mcp.settings.host = host
    mcp.settings.port = port
    mcp.settings.streamable_http_path = path

    inner = mcp.streamable_http_app()
    app = AuthMiddleware(inner, mcp_path=path, health_path="/health")
    uvicorn.run(app, host=host, port=port, log_level="info")


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio").strip().lower()
    mcp = make_server()
    if transport in ("stdio", "standardio", ""):
        run_stdio(mcp)
    elif transport in ("streamable-http", "streamable_http", "http"):
        run_http(mcp)
    else:
        raise SystemExit(f"未知 MCP_TRANSPORT={transport!r}，仅支持 stdio | streamable-http")


if __name__ == "__main__":
    main()
