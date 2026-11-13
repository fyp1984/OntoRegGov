#!/bin/bash
# 容器入口：统一启动脚本。
# 依赖已随 requirements.txt 在镜像构建期预装（含 neo4j），运行期不再联网安装，
# 保证离线环境可冷启动。
# 环境变量（均有内置默认，可由 compose 覆盖）：HOST=0.0.0.0  PORT=8420
set -euo pipefail
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8420}"
echo "[start] 金融行业数据安全知识库和智能体平台"
echo "[start] 监听 http://${HOST}:${PORT}  (健康检查 /api/health)"
exec python -m uvicorn app.main:app --host "${HOST}" --port "${PORT}"
