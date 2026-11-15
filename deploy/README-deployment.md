# 金融行业数据安全知识库和智能体平台 · 系统技术方案（架构 / 部署 / 运维）

> 版本：v1.20.0（容器化 + 跨平台参数化改造）
> 适用范围：Windows / macOS / Linux；开发机与服务器**同一套编排、同一套命令**
> 关联文件：[Dockerfile](file:///d:/workspace/CheersAI/OntoRegGov/deploy/Dockerfile)、
> [docker-compose.ontoreggov.yml](file:///d:/workspace/CheersAI/OntoRegGov/deploy/docker-compose.ontoreggov.yml)、
> [docker-compose.fuseki.yml](file:///d:/workspace/CheersAI/OntoRegGov/deploy/docker-compose.fuseki.yml)、
> [.env.example](file:///d:/workspace/CheersAI/OntoRegGov/.env.example)、
> [run.sh](file:///d:/workspace/CheersAI/OntoRegGov/run.sh)、
> [start.sh](file:///d:/workspace/CheersAI/OntoRegGov/start.sh)

---

## 0. 目标与设计约束

| 约束 | 含义 | 落地手段 |
|---|---|---|
| 跨平台同构 | Windows / macOS / Linux 拉下代码后**同一命令**可起服务 | 单文件编排 + profile；行尾归一（`.gitattributes` + 构建期 `sed`）；路径一律推导或经环境变量注入 |
| 零密钥可启动 | 无任何密钥也能完整跑通主链路，不 5xx | 所有外部依赖缺失即**降级**：LLM→规则抽取、图存储→进程内 memory、底座库→本地种子 |
| 密钥不入库 | 仓库内不出现口令 / Token / API Key | 一律 `${VAR}` 注入；`.env`、`openclaw.json` 已 gitignore；模板 `openclaw.template.json` 只含占位符 |
| 无绝对路径 | 仓库内不含任何机器相关绝对路径 | 代码内 `Path(__file__)` 推导；宿主目录只允许出现在 `.env`（`KB10_SITE_HOST` / `KB10_ROOT`） |
| 形态可叠加 | 演示 / 完整 / 智能体 / 图存储按需组合 | Docker Compose profiles + 两文件共用 `COMPOSE_PROJECT_NAME` |

---

## 1. 系统架构

### 1.1 逻辑分层（五层）

![技术架构](../assets/architecture.svg)

```
┌─ L5 接入层 ────────────────────────────────────────────────────────────────┐
│  H5 业务台(/)      REST 网关(/api, :8420)     智能体网关(MCP, :8422, 可选)   │
│  鉴权中间件（GATEWAY_AUTH_ENABLED=on 时 /api/* 强制 Bearer + 限流 + 审计）    │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
┌─ L4 编排层 ────▼───────────────────────────────────────────────────────────┐
│  知识编译流水线 → 发布质量门（影子彩排 + 失败回滚）                            │
│  检查闭环编排（判定 → 缺口提案 → 补控 → 复检） · 场景加载器（配置驱动）         │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
┌─ L3 内核层 ────▼───────────────────────────────────────────────────────────┐
│  本体引擎（对象 / 关系 / 动作 / 能力） · 形状闸门（pyshacl 校验）              │
│  确定性判定引擎（pass / partial / fail + 逐条 why 溯源） · 角色分离三重拦截     │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
┌─ L2 适配层 ────▼───────────────────────────────────────────────────────────┐
│  kb_source 取数适配器（统一信封 + 降级链 weknora→canonical→db→sqlite）        │
│  kb_knowledge 知识契约装配 · kb_read 三态读源路由 · SPI 适配器注册中心        │
│  （retriever / llm / policy / masker 按 ADAPTER_* 环境变量插拔）             │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
┌─ L1 底座层 ────▼───────────────────────────────────────────────────────────┐
│  RDF 正本(canonical) · SQLite 运行态 · PostgreSQL 只读投影 · 图存储           │
│  (Fuseki / Oxigraph / Neo4j / memory) · 向量索引(TEI/RAGFlow) · 知识库平台    │
└───────────────────────────────────────────────────────────────────────────┘
```

### 1.2 容器部署视图

```
宿主（Windows Docker Desktop / macOS OrbStack·Docker Desktop / Linux dockerd）
└─ compose 项目：${COMPOSE_PROJECT_NAME:-ontoreggov}      网络：ontoreggov_default
   │
   ├─ ontoreggov-demo        [profile: demo]   端口 ${APP_PORT:-8420}→8420
   ├─ ontoreggov-app         [profile: full]   端口 ${APP_PORT:-8420}→8420
   │    ├─ 卷 ../app                → /app/app           (代码热挂载)
   │    ├─ 卷 ../app/data           → /app/app/data      (运行态持久化)
   │    ├─ 卷 ${KB10_SITE_HOST}     → /app/kb_site:ro    (知识静态站，只读)
   │    └─ 网络 ekos-net(外部)      → compose_weknora-net  (仅 full)
   │
   ├─ ontoreggov-openclaw    [profile: openclaw] 端口 ${OPENCLAW_GATEWAY_PORT:-18789}→18789
   │    └─ 卷 ../services/openclaw → /srv/openclaw      (构建产物 + 渲染配置 + state)
   │
   └─ ontoreggov-fuseki      [docker-compose.fuseki.yml] 端口 ${FUSEKI_PORT:-3030}→3030
        └─ 卷 fuseki-data       → /fuseki                (TDB2 数据)

外部底座（既有，非本编排创建；full 形态经 ekos-net 接入）
   PostgreSQL:15432(只读投影 ekos_ds_kb) · WeKnora:8080 + Neo4j:7687 · RAGFlow:19380 · TEI:18002
```

> 两份编排文件共用 `name: ${COMPOSE_PROJECT_NAME:-ontoreggov}`，因此默认网络一致，
> 容器内可用服务名互访：`GRAPH_STORE_ENDPOINT=http://fuseki:3030`。

### 1.3 数据来源与降级链

| 能力 | 主源 | 降级顺序 | 触发条件 | 表现 |
|---|---|---|---|---|
| 检查项 / 实体 / 控制 | `DB_READ_FROM`（demo=sqlite，full=db） | db → canonical → sqlite | PG 不可达或无命中 | `source` 字段体现实际来源，仍 200 |
| 知识契约 / Wiki / 图谱 | `KB_READ_FROM=canonical` | weknora → canonical → db → sqlite | 上游不可达 | 页面提示「来源不可用」，其余模块不受影响 |
| 图存储 | `GRAPH_STORE_BACKEND`（默认 fuseki） | fuseki → oxigraph → memory | 端点不可达 / `GRAPH_FORCE_MEMORY=1` | 进程内物化，只读可用 |
| LLM 抽取 | `OPENAI_*` | openai → rule（确定性） | `OPENAI_API_KEY` 为空 | 响应标注 `degraded=true` |
| 合规自查 | OpenClaw 网关 :18789 | 无 → 该功能不可用 | 无构建产物 / 网关未起 | 仅自查功能降级，主链路不受影响 |
| 智能体网关 MCP | `app.mcp_server.server` :8422 | 无 → 不启动 | 未安装可选依赖 `mcp` | 仅外部智能体接入能力缺失 |

### 1.4 端口与网络规划

| 端口 | 归属 | 默认 | 环境变量 | 是否需对外 |
|---|---|---|---|---|
| 8420 | REST + H5 业务台 | 8420 | `APP_PORT`（宿主侧） | 是（经反向代理） |
| 8422 | 智能体网关 MCP | 8422 | `MCP_PORT` | 按需（建议仅内网） |
| 18789 | OpenClaw 网关 | 18789 | `OPENCLAW_GATEWAY_PORT` | 否（内网/loopback） |
| 3030 | Fuseki 图存储 | 3030 | `FUSEKI_PORT` | 否 |
| 15432 | PostgreSQL 投影库 | — | `KB_PG_DSN` 内 | 否（既有底座） |
| 7687 / 8080 | Neo4j / WeKnora API | — | `WEKNORA_NEO4J_*` / `WEKNORA_API_*` | 否（既有底座） |

---

## 2. 部署方案

### 2.1 前置条件

| 项 | 要求 | 说明 |
|---|---|---|
| 容器运行时 | Docker Engine ≥ 24（含 Docker Desktop / OrbStack / Colima） | Windows 建议 WSL2 后端 |
| 编排 | Docker Compose v2 ≥ 2.20（`docker compose` 子命令） | 需支持 top-level `name:` 与 `profiles` |
| 磁盘 | ≥ 6 GB 可用 | 镜像 + 依赖；启用 openclaw 需另加 ~3 GB |
| CPU / 内存 | ≥ 2 vCPU / 4 GB | 单实例基线；接底座时按底座另计 |
| 端口 | 8420 空闲 | 冲突时改 `APP_PORT` |

### 2.2 三步起服务（Windows / macOS / Linux 完全一致）

```bash
git clone https://github.com/fyp1984/OntoRegGov.git
cd OntoRegGov
cp .env.example .env                                   # ① 复制环境变量模板（可先用默认值）
docker compose -f deploy/docker-compose.ontoreggov.yml --profile demo up -d --build
```

打开 `http://127.0.0.1:8420/`（健康检查 `/api/health`）。

> `.env` 放在**仓库根目录**（compose 会自动读取根目录与编排文件目录两份 `.env`）。
> 留空即零密钥启动：智能抽取自动降级为规则抽取，图存储走进程内 memory。

### 2.3 运行形态矩阵

| profile | 服务 | 外部依赖 | 适用场景 |
|---|---|---|---|
| `demo` | `ontoreggov-demo` | 无（SQLite + 进程内图） | 演示、验收、无底座环境 |
| `full` | `ontoreggov-app` | 既有 PG / WeKnora / Neo4j（经 `EKOS_NETWORK`） | 生产、接真实底座 |
| `openclaw` | `ontoreggov-openclaw` | 无（需已有构建产物） | 启用合规自查智能体 |
| （独立文件） | `ontoreggov-fuseki` | 无 | 需要真实图存储 |

```bash
# 常用组合
docker compose -f deploy/docker-compose.ontoreggov.yml --profile demo up -d --build        # 演示
docker compose -f deploy/docker-compose.ontoreggov.yml --profile full up -d --build        # 完整
docker compose -f deploy/docker-compose.fuseki.yml up -d                                   # + Fuseki
docker compose -f deploy/docker-compose.ontoreggov.yml --profile demo --profile openclaw up -d  # + 自查智能体
```

### 2.4 环境变量清单

完整模板见 [.env.example](file:///d:/workspace/CheersAI/OntoRegGov/.env.example)。分组要点：

| 分组 | 关键变量 | 说明 |
|---|---|---|
| 应用与镜像 | `TZ` `APP_PORT` `APP_IMAGE` `PYTHON_VERSION` `MCP_PORT` | 镜像基础版本经构建参数注入，不烘焙进镜像 |
| 宿主目录 | `KB10_SITE_HOST` `KB10_ROOT` | **唯一允许出现绝对路径的地方**；相对路径以 `deploy/` 为基准 |
| 读源开关 | `DB_READ_FROM` `KB_READ_FROM` `SKIP_SEED` `GRAPH_FORCE_MEMORY` | 未设置时由 profile 给默认值 |
| 图存储 | `GRAPH_STORE_BACKEND` `GRAPH_STORE_ENDPOINT` `GRAPH_STORE_DATASET` `GRAPH_STORE_USER` `GRAPH_STORE_PASSWORD` `FUSEKI_PORT` | 留空即降级 memory |
| 投影库 | `KB_PG_DSN` | `postgresql://user:pass@host:port/db`，留空即降级 |
| LLM | `OPENAI_BASE_URL` `OPENAI_API_KEY` `OPENAI_MODEL` | Key 留空 → 规则抽取 |
| 知识底座 | `WEKNORA_*`（API / PG / Neo4j） | full 形态使用 |
| 向量检索 | `RAGFLOW_*` `TEI_EMBED_URL` | 可选 |
| OpenClaw | `OPENCLAW_GATEWAY_URL` `OPENCLAW_GATEWAY_TOKEN` `OPENCLAW_LLM_*` `OPENCLAW_NODE_BIN` | 令牌留空则渲染时随机生成并落盘（不入库） |
| 网关鉴权 | `GATEWAY_AUTH_ENABLED` `MCP_ALLOWLIST_PATH` | `on` = `/api/*` 强制 Bearer + 限流 + 审计 |
| 网络 | `EKOS_NETWORK` `COMPOSE_PROJECT_NAME` | 外部网络名 / compose 项目名 |

### 2.5 跨平台一致性保障机制

| 风险 | 机制 | 位置 |
|---|---|---|
| Windows 检出为 CRLF → 容器内 `bash` 报 `set -euo pipefail\r: invalid option` | `.gitattributes` 强制 `*.sh text eol=lf`；构建期再 `sed -i 's/\r$//' run.sh start.sh` 双保险 | [.gitattributes](file:///d:/workspace/CheersAI/OntoRegGov/.gitattributes)、[Dockerfile](file:///d:/workspace/CheersAI/OntoRegGov/deploy/Dockerfile#L30-L31) |
| 机器绝对路径 | 代码内 `Path(__file__).resolve().parents[N]` 推导；宿主路径仅由 `.env` 注入 | `app/config.py`、`scripts/**` |
| 密钥泄漏 | 模板 + 环境变量渲染，`openclaw.json` / `.env` gitignore | `app/services/openclaw_config.py` |
| 网络名漂移 | 两份编排共用 `COMPOSE_PROJECT_NAME` | `deploy/*.yml` 的 `name:` 段 |
| 路径分隔符 | 统一由 `pathlib` / Compose 处理，脚本内不拼 `/` 以外的分隔符 | `run.sh`、`start.sh` |
| 运行期联网 | 依赖在构建期装齐，容器内零联网可冷启动 | `deploy/Dockerfile` |

### 2.6 不同终端 / 服务器落地清单

| 环境 | 差异点 | 处理 |
|---|---|---|
| Windows + Docker Desktop | 卷挂载需在 WSL2 文件系统或对路径做共享授权 | 建议仓库与 `KB10_SITE_HOST` 均置于 `\\wsl$` 或已共享盘符；或直接不放知识站点（走降级） |
| macOS + OrbStack / Docker Desktop | `host.docker.internal` 指向宿主 | 已用于访问宿主侧 Ollama / PG |
| Linux 服务器 | 无 `host.docker.internal` | 若需访问宿主服务，改用宿主实际 IP 或让服务加入同一 docker 网络 |
| 无外网服务器 | 无法 `pip install` / 拉基础镜像 | 先在可联网机器 `docker compose build`，`docker save` 导出镜像后 `docker load` |

### 2.7 可选组件接入

**Fuseki（真实图存储）**

```bash
# .env 中设置 GRAPH_STORE_PASSWORD（生产必须）、FUSEKI_PORT、GRAPH_STORE_DATASET
docker compose -f deploy/docker-compose.fuseki.yml up -d
# 平台侧（同一 .env，容器内用服务名）
GRAPH_STORE_BACKEND=fuseki
GRAPH_STORE_ENDPOINT=http://fuseki:3030
GRAPH_STORE_USER=admin
GRAPH_STORE_PASSWORD=<与 ADMIN_PASSWORD 一致>
```

**WeKnora / PostgreSQL 底座（full 形态）** — 在 `.env` 填 `WEKNORA_*`、`KB_PG_DSN`、`EKOS_NETWORK`（默认 `compose_weknora-net`）；网络须已存在，否则 `--profile full up` 会报 external network not found。

**OpenClaw 合规自查智能体**

```bash
# 前置：构建产物就位（services/openclaw/openclaw.mjs + node_modules，~3GB，不入库）
python scripts/ops/render_openclaw_config.py     # 按 .env 渲染 openclaw.json（密钥不入库）
docker compose -f deploy/docker-compose.ontoreggov.yml --profile demo --profile openclaw up -d
# .env：OPENCLAW_GATEWAY_URL=http://openclaw-gateway:18789  OPENCLAW_GATEWAY_TOKEN=<令牌>
```

**智能体网关 MCP（:8422）** — 可选依赖，未装 `mcp` 则镜像内无该模块，属预期行为：

```bash
pip install "mcp>=1.0,<2"
MCP_TRANSPORT=streamable-http MCP_PORT=8422 python -m app.mcp_server.server
```

### 2.8 非容器本地开发

```bash
bash run.sh                 # Windows(Git Bash)/macOS/Linux：建/复用 .venv → 装依赖 → 种子 → 起服务
# Windows 亦可：start.bat（平台）/ start-all.bat（平台 + OpenClaw）
# 跳过种子：SKIP_SEED=1 bash run.sh
```

---

## 3. 运维方案

### 3.1 生命周期命令

```bash
docker compose -f deploy/docker-compose.ontoreggov.yml --profile demo ps
docker compose -f deploy/docker-compose.ontoreggov.yml --profile demo logs -f --tail=200
docker compose -f deploy/docker-compose.ontoreggov.yml --profile demo restart
docker compose -f deploy/docker-compose.ontoreggov.yml --profile demo down            # 停并删容器（保留卷）
docker compose -f deploy/docker-compose.ontoreggov.yml --profile demo down -v         # 连带删除卷（数据不可恢复）
```

改前端静态资源即时生效（需 bump `index.html` 内 `?v=` 缓存参数）；改后端 Python 需 `restart`。

### 3.2 健康检查与可观测

| 项 | 命令 / 端点 | 期望 |
|---|---|---|
| 容器健康 | `docker inspect --format '{{.State.Health.Status}}' ontoreggov-demo` | `healthy` |
| 应用健康 | `GET http://127.0.0.1:8420/api/health` | 200（该端点豁免网关鉴权） |
| 底座连通 | `/api/health` 返回体中的 `ekos_health`（neo4j / weknora_api / checkedAt） | 未配置时为 `ok:false` + `note`，属预期降级 |
| 编排健康检查 | compose 内置 `healthcheck`：`interval 30s / timeout 5s / retries 3 / start_period 20s` | 连续失败自动标记 unhealthy（未触发自重启） |

### 3.3 日志

| 日志 | 位置 |
|---|---|
| 应用标准输出 | `docker compose logs`（容器内 `PYTHONUNBUFFERED=1`） |
| OpenClaw 网关 | `services/openclaw/state/gateway.log` |
| Fuseki | `docker compose -f deploy/docker-compose.fuseki.yml logs` |

### 3.4 数据持久化与备份恢复

| 数据 | 位置 | 备份 | 恢复 |
|---|---|---|---|
| 运行态 SQLite / 上传 / 快照 | 宿主 `app/data/` | 停容器后打包 `app/data/` | 解包回原位后 `up -d` |
| 图存储 TDB2 | 命名卷 `ontoreggov_fuseki-data` | `docker run --rm -v ontoreggov_fuseki-data:/d -v ${PWD}:/b alpine tar czf /b/fuseki.tgz -C /d .` | 反向解包 |
| 环境变量与密钥 | 宿主 `.env`（不入库） | 安全渠道另存 | 还原 `.env` |
| 知识静态站 | 宿主 `KB10_SITE_HOST` 目录 | 随知识工程备份 | 还原目录 |

> `SKIP_SEED=1`（compose 默认）表示**复用卷内既有数据、不重置种子**；置 `0` 才会重新初始化。

### 3.5 版本升级与回滚

```bash
git pull                                  # 或切到目标 tag
docker compose -f deploy/docker-compose.ontoreggov.yml --profile demo up -d --build
```

回滚：镜像按 `APP_IMAGE` 打版本标签保留上一版（如 `ontoreggov-app:1.19.0`），`APP_IMAGE=<上一版> up -d` 即可；代码回滚 `git checkout <上一版 tag>`。升级前先备份 `app/data/` 与 `.env`。

### 3.6 密钥与凭据管理

```bash
# 生成强口令 / 令牌（无需联网）
python -c "import secrets;print(secrets.token_hex(24))"
```

| 凭据 | 变量 | 轮换步骤 |
|---|---|---|
| LLM API Key | `OPENAI_API_KEY` / `OPENCLAW_LLM_API_KEY` | 改 `.env` → `up -d`（openclaw 需 `render_openclaw_config.py --force` 后重启该容器） |
| OpenClaw 网关令牌 | `OPENCLAW_GATEWAY_TOKEN` | 同上；平台侧优先读 `openclaw.json`，缺失时回落该环境变量 |
| Fuseki 管理口令 | `GRAPH_STORE_PASSWORD` / `ADMIN_PASSWORD` | 改 `.env` → 重建 fuseki 容器 |
| PG 连接串 | `KB_PG_DSN` | 改 `.env` → `up -d` |
| 网关钥匙板 | `MCP_ALLOWLIST_PATH` | 指向外部钥匙板文件，避免用内置演示钥匙板 |
| RAGFlow 令牌 | `RAGFLOW_API_TOKEN` | 改 `.env` → `up -d` |

原则：**任何密钥只存在于运行环境 `.env` / 渲染后的 `openclaw.json`，仓库内仅有占位符**。

### 3.7 安全基线

- 对外暴露前设 `GATEWAY_AUTH_ENABLED=on`（`/api/*` 强制 Bearer + 限流 + 审计），并把 `MCP_ALLOWLIST_PATH` 指向真实钥匙板。
- 知识静态站以 `:ro` 只读挂载；平台对上游知识仅做只读投影，绝不回写。
- 8422 / 18789 不直接暴露公网；如需外网访问，前置反向代理（TLS + 认证）。
- 容器以官方 slim / node-alpine 基础镜像构建，不在镜像内烘焙任何凭据。
- `openclaw.json` 渲染后权限收紧至 `0600`（Windows 上为 no-op）。

### 3.8 故障排查速查表

| 现象 | 定位 | 处置 |
|---|---|---|
| `bash: set -euo pipefail\r: invalid option` | 脚本为 CRLF 检出 | `git rm --cached -r . && git reset --hard` 后按 `.gitattributes` 重新检出；确认 `.gitattributes` 已入库 |
| `external network compose_weknora-net not found` | `--profile full` 但底座网络不存在 | 先起底座，或改 `EKOS_NETWORK`，或改用 `--profile demo` |
| 容器 unhealthy | 应用未就绪 | `logs` 看异常；确认 8420 未被占用、`/api/health` 可访问 |
| 8420 被占用 | 宿主端口冲突 | 改 `.env` 的 `APP_PORT` |
| 知识视图「来源不可用」 | `KB10_SITE_HOST` 未指向含 `data/knowledge-data.js` 的目录 | 修正挂载路径，或接受降级 |
| 智能抽取结果简单、`degraded=true` | 未配置 `OPENAI_API_KEY` | 配置 Key 后重启；或接受规则抽取 |
| 合规自查不可用 | OpenClaw 构建产物缺失 / 网关未起 | 见 §2.7；缺失属预期，主链路不受影响 |
| Linux 上连不上宿主服务 | 无 `host.docker.internal` | 改用宿主 IP 或共用 docker 网络 |

### 3.9 部署验收清单

1. `docker compose ps` 中目标服务为 `running` 且 `healthy`。
2. `GET /api/health` → 200。
3. 打开 `http://127.0.0.1:8420/`：业务台可加载，本体浏览 / 监管检查库 / 合规评估可交互。
4. `GET /api/checks` 返回检查项（`source` 字段体现实际读取来源）。
5. 抽查 `docker inspect` 挂载：`kb_site` 为只读、`app/data` 指向宿主目录。
6. 仓库自检：`git grep -nI "sk-\|admin:admin\|test:test@"` 无明文密钥命中。

---

## 4. 本次改造变更清单

| 类别 | 关键变更 |
|---|---|
| 密钥参数化 | 移除 LLM Key、RAGFlow Token、Neo4j 口令、PG 口令、Fuseki `admin:admin`、OpenClaw 令牌等全部明文默认值，改为环境变量注入 |
| 绝对路径去除 | `app/config.py`（`KB10_ROOT`）、`app/services/openclaw_svc.py`（node 可执行文件）、`scripts/**`（10 个脚本）改为推导 + 环境变量 |
| 配置模板化 | 新增 `services/openclaw/openclaw.template.json` + `app/services/openclaw_config.py` + `scripts/ops/render_openclaw_config.py`；删除含明文密钥的 `openclaw.json` |
| 容器化 | `deploy/Dockerfile` 参数化基础版本、构建期行尾归一、内置 `HEALTHCHECK`；`deploy/docker-compose.ontoreggov.yml` 单文件 profile 化；`.dockerignore` 排除密钥与 3GB 构建产物 |
| 跨平台 | 新增 `.gitattributes`；`run.sh` 跨平台重写；`services/openclaw/start-gateway.bat` 去机器路径 |
| 网络一致性 | 两份编排共用 `COMPOSE_PROJECT_NAME`，Fuseki 与平台同网络可互访 |
| 交付物 | 新增 `.env.example`、`deploy/kb_site/README.md`、本文件 |
