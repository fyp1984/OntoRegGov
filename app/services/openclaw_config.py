"""OpenClaw 网关配置渲染（v1.20.0）。

背景：services/openclaw/openclaw.json 原为入库文件，内含机器相关绝对路径与明文密钥，
既无法跨 Windows / macOS / Linux 复用，也违反"密钥不入库"。

做法：
- 入库 `openclaw.template.json`（仅含 `${VAR}` 占位符，无任何密钥与绝对路径）；
- 运行时（本机 run.sh、容器 start.sh、平台启动钩子）由本模块用环境变量渲染出
  `openclaw.json`（已 gitignore）；缺失才生成，已存在则原样保留，不覆盖运行态改动。

安全默认：
- 网关令牌：`OPENCLAW_GATEWAY_TOKEN` > 既有配置内的令牌 > 随机生成一次并落盘
  （避免每次渲染换令牌导致已运行网关失配）。
- 模型密钥：`OPENCLAW_LLM_API_KEY`（未设置则写空串，网关侧报不可用但不崩）。
"""
from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path

TEMPLATE_NAME = "openclaw.template.json"
CONFIG_NAME = "openclaw.json"
_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _existing_token(cfg_path: Path) -> str:
    """读取既有 openclaw.json 中的网关令牌（用于渲染时保持稳定）。"""
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        return ((cfg.get("gateway") or {}).get("auth") or {}).get("token") or ""
    except Exception:  # noqa: BLE001
        return ""


def _build_env(home: Path, cfg_path: Path) -> dict[str, str]:
    state = home / "state"
    env: dict[str, str] = {
        "OPENCLAW_HOME": str(home),
        "OPENCLAW_STATE_DIR": str(state),
        "OPENCLAW_PROVIDER": "qwen",
        "OPENCLAW_LLM_BASE_URL": "",
        "OPENCLAW_LLM_API_KEY": "",
        "OPENCLAW_LLM_MODEL_ID": "qwen3.8-flash",
        "OPENCLAW_LLM_MODEL_NAME": "Qwen3.8 Flash",
        "OPENCLAW_LOG_LEVEL": "info",
    }
    # 环境变量覆盖（同一前缀命名空间，便于容器/CI 注入）
    env.update({k: v for k, v in os.environ.items() if k.startswith("OPENCLAW_")})
    env.setdefault("OPENCLAW_MODEL",
                   f"{env['OPENCLAW_PROVIDER']}/{env['OPENCLAW_LLM_MODEL_ID']}")
    env["OPENCLAW_GATEWAY_TOKEN"] = (env.get("OPENCLAW_GATEWAY_TOKEN", "").strip()
                                     or _existing_token(cfg_path)
                                     or secrets.token_hex(24))
    return env


def render_config(home: Path, *, force: bool = False) -> Path:
    """把 openclaw.template.json 按环境变量渲染为 openclaw.json，返回配置路径。

    force=False（默认）时若 openclaw.json 已存在则原样保留（幂等）。
    模板缺失或渲染结果非合法 JSON 时不写盘，退回既有路径，绝不抛错。
    """
    tpl_path = home / TEMPLATE_NAME
    cfg_path = home / CONFIG_NAME
    if not tpl_path.exists() or (cfg_path.exists() and not force):
        return cfg_path

    text = tpl_path.read_text(encoding="utf-8")
    env = _build_env(home, cfg_path)
    for name in sorted({m for m in _PLACEHOLDER.findall(text) if m not in env}):
        env[name] = ""
    # 用 json.dumps 转义后再填入（字符串内需转义引号与反斜杠，Windows 路径依赖此处理）
    rendered = _PLACEHOLDER.sub(
        lambda m: json.dumps(env.get(m.group(1), ""))[1:-1], text)
    try:
        json.loads(rendered)
    except Exception:  # noqa: BLE001 — 渲染异常不写盘，保持原状
        return cfg_path

    home.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(rendered + "\n", encoding="utf-8")
    try:  # 配置含令牌，尽量收紧权限（Windows 上为 no-op）
        cfg_path.chmod(0o600)
    except Exception:  # noqa: BLE001
        pass
    return cfg_path
