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

# 知识库静态站自动探测（加性改动）：KB10_SITE 未显式设置时，按 KB10_ROOT → 内置默认
# 本地知识工程路径探测 site/；命中即导出，保证一键启动时知识库视图不降级；
# 未命中则保持原有降级行为（不阻塞启动）。
if [ -z "${KB10_SITE:-}" ]; then
  _KB_SITE_FOUND=""
  for _cand in "${KB10_ROOT:-}" "/Users/FYP/Documents/@西北人的成长/20-Areas/信息安全/数据安全/10_知识库工程"; do
    if [ -n "$_cand" ] && [ -f "${_cand}/site/data/knowledge-data.js" ]; then
      _KB_SITE_FOUND="${_cand}/site"
      break
    fi
  done
  if [ -n "$_KB_SITE_FOUND" ]; then
    export KB10_SITE="$_KB_SITE_FOUND"
    echo "[run] 自动探测知识库站点：KB10_SITE=$KB10_SITE"
  else
    echo "[run] 未探测到本地知识库站点，知识库视图将降级（可显式 KB10_SITE=/path/to/site）"
  fi
fi

# 1. 虚拟环境
if [ ! -d "$VENV" ]; then
  echo "[run] 创建虚拟环境 $VENV ..."
  "$PY" -m venv "$VENV"
fi
# 兼容 Windows（Git Bash 下 venv 为 Scripts/ 布局）与 POSIX（bin/ 布局）
if [ -f "$VENV/Scripts/activate" ]; then
  # shellcheck disable=SC1091
  source "$VENV/Scripts/activate"
else
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
fi

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
