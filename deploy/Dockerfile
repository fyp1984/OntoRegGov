# 本体驱动数据安全监管与治理合规平台 — 容器镜像（OrbStack 部署用）
# 复用既有容器服务：ekos-postgres(15432)/Fuseki(3030) 通过 host.docker.internal 访问
FROM python:3.13-slim

WORKDIR /app

# 依赖层（利用构建缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码（app/data 由卷挂载持久化，镜像内仅保留 .gitkeep）
COPY app/ app/
COPY data/ data/
COPY ingest/ ingest/
COPY scripts/ scripts/
COPY tools/ tools/
COPY run.sh CHANGELOG.md README.md ROADMAP.md ./

EXPOSE 8420

# 默认运行形态：复用卷内既有数据（SKIP_SEED=1，不重置种子）；
# v1.15.0 工程收敛切源：读源默认 db（PG 投影）+ canonical（权威本体），
# 库不可达自动回落 canonical/SQLite；图后端 memory（如需 Fuseki 可在 compose 环境变量切换）
ENV DB_READ_FROM=db
ENV KB_READ_FROM=canonical
ENV GRAPH_STORE_BACKEND=memory
ENV SKIP_SEED=1
ENV PORT=8420

CMD ["bash", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
