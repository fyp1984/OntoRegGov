#!/usr/bin/env bash
# 一键启动：建/复用 .venv → 装依赖 → 初始化种子 → 起本地服务
# 用法: bash run.sh            # 初始化种子(幂等)并起服务
#        SKIP_SEED=1 bash run.sh # 跳过种子初始化(复用已有 data/app.db)
# 环境变量（均有内置默认）：HOST=127.0.0.1  PORT=8420
set -euo pipefail
cd "$(dirname "$0")"

PY=python3
VENV=.venv
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8420}"

# 1. 虚拟环境
if [ ! -d "$VENV" ]; then
  echo "[run] 创建虚拟环境 $VENV ..."
  "$PY" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

# 2. 依赖（已装则 pip 快速跳过）
echo "[run] 安装依赖 ..."
pip install -q -r requirements.txt

# 3. 初始化种子（幂等；SKIP_SEED=1 可跳过）
if [ "${SKIP_SEED:-0}" != "1" ]; then
  echo "[run] 初始化/重置种子数据 ..."
  python -m app.cli seed
else
  echo "[run] SKIP_SEED=1，跳过种子初始化"
fi

echo "[run] 启动服务: http://${HOST}:${PORT}  (API 前缀 /api；健康检查 /api/health)"
exec python -m uvicorn app.main:app --host "${HOST}" --port "${PORT}"
