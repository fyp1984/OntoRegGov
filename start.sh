#!/bin/bash
# 启动脚本：先确保 neo4j 依赖已安装，再启动 uvicorn
pip install --no-cache-dir neo4j==5.27.0 > /tmp/pip.log 2>&1
exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8420}
