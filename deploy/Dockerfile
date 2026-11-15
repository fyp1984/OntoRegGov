# 金融行业数据安全知识库和智能体平台 — 容器镜像（跨平台：Windows / macOS / Linux 宿主一致）
#
# 设计要点：
#   1. 零环境硬编码：镜像内不烘焙任何连接串 / 口令 / 令牌 / 宿主绝对路径，
#      全部由 compose 或运行环境经环境变量注入；
#   2. 行尾归一：Windows 宿主检出为 CRLF 时，容器内 bash 无法执行 shell 脚本
#      （`set -euo pipefail\r: invalid option`），构建期统一转 LF；
#   3. 运行期零联网：依赖在构建期预装，离线环境可冷启动；
#   4. 运行态数据全部卷挂载（app/data），镜像内只保留只读种子数据。
ARG PYTHON_VERSION=3.13
FROM python:${PYTHON_VERSION}-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 依赖层（利用构建缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码（app/data 由卷挂载持久化，镜像内仅保留 .gitkeep）
COPY app/ app/
COPY data/ data/
COPY scripts/ scripts/
COPY run.sh start.sh CHANGELOG.md README.md ROADMAP.md ./

# 行尾归一：Windows 宿主检出可能为 CRLF，容器内 bash 必须拿到 LF
RUN sed -i 's/\r$//' run.sh start.sh

EXPOSE 8420

# 只保留与运行环境无关的默认值；读源 / 图后端 / 底座连接一律由 compose 决定
ENV PORT=8420 \
    TZ=Asia/Shanghai

# 就绪判据：/api/health 返回 200（该端点已豁免网关鉴权）
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8420/api/health',timeout=3).status==200 else 1)"

CMD ["bash", "start.sh"]
