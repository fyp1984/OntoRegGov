#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染 services/openclaw/openclaw.json（模板 + 环境变量），密钥不入库。

用法：
  python scripts/ops/render_openclaw_config.py           # 缺失才生成（幂等）
  python scripts/ops/render_openclaw_config.py --force   # 按当前环境变量强制重渲染

相关环境变量（缺省见 app/services/openclaw_config.py）：
  OPENCLAW_GATEWAY_TOKEN / OPENCLAW_LLM_API_KEY / OPENCLAW_LLM_BASE_URL
  OPENCLAW_PROVIDER / OPENCLAW_LLM_MODEL_ID / OPENCLAW_LLM_MODEL_NAME / OPENCLAW_LOG_LEVEL
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.services.openclaw_config import render_config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="渲染 OpenClaw 网关配置")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的 openclaw.json")
    args = ap.parse_args()
    path = render_config(ROOT / "services" / "openclaw", force=args.force)
    print(f"[openclaw] 配置就绪：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
