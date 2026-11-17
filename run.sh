#!/usr/bin/env bash
# 一键启动：建/复用 .venv → 装依赖 → 初始化种子 → 起本地服务
# 用法: bash run.sh            # 初始化种子(幂等)并起服务
#        SKIP_SEED=1 bash run.sh # 跳过种子初始化(复用已有 data/app.db)
# 环境变量（均有内置默认）：HOST=127.0.0.1  PORT=8420
# 跨平台：Windows(Git Bash)/macOS/Linux 均可执行；仓库内不含任何机器相关绝对路径。
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8420}"
VENV=.venv

# Python 解释器探测：优先 python3（POSIX），回落 python（Windows 常见）
if command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  PY="${PY:-python}"
fi

# 知识库静态站自动探测：KB10_SITE 未显式设置时，优先用仓库内唯一正本 app/web/static/kb，
# 再依次探测 KB10_ROOT → 仓库同级 10_知识库工程；命中即导出，保证知识库视图不降级；
# 未命中则保持原有降级行为（不阻塞启动）。
# 治理说明：唯一正本随仓库入库（app/web/static/kb/data/knowledge-data.js），
# 不再依赖文档树中的知识工程 site 产物（那份已归档）。
if [ -z "${KB10_SITE:-}" ]; then
  _KB_SITE_FOUND=""
  for _cand in "${ROOT}/app/web/static/kb" "${KB10_ROOT:-}" "${ROOT}/../10_知识库工程"; do
    if [ -z "$_cand" ]; then
      continue
    fi
    if [ -f "${_cand}/site/data/knowledge-data.js" ]; then
      _KB_SITE_FOUND="${_cand}/site"
      break
    fi
    if [ -f "${_cand}/data/knowledge-data.js" ]; then
      _KB_SITE_FOUND="${_cand}"
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

# 4. OpenClaw 网关配置就绪（模板 + 环境变量渲染；密钥不入库；缺失才生成）
if [ -f services/openclaw/openclaw.template.json ]; then
  python scripts/ops/render_openclaw_config.py || true
fi

echo "[run] 启动服务: http://${HOST}:${PORT}  (API 前缀 /api；健康检查 /api/health)"
exec python -m uvicorn app.main:app --host "${HOST}" --port "${PORT}"
