# 变更记录

## v1.11.0（2026-10-19，监管检查库多文号补全：93号/人行令3号/金发8号）

- **新增三份检查数据**（`data/checks/`，均由 `tools/build_checks.py` 从权威原文构建）：
  - `jg93-checks.json`：金办发〔2025〕93号《金融机构数据安全管理能力提升专项行动》自查表，**140 项**
    （标准版 139 + 带监管版多出的 23.1 项，六方面 19+9+48+39+15+9+1）；
  - `pboc3-checks.json`：人行令〔2025〕第3号《中国人民银行业务领域数据安全管理办法》**56 条**，
    逐条含条文原文（国务院公报 gov.cn 第18号，2025-06-30 施行）；
  - `jf8-checks.json`：金发〔2026〕8号《银行业保险业人工智能安全开发应用指导意见》**32 项**
    （总体/七方面/保障监督），2026-06-18 发布。
- **导入引擎多文号化**（`app/ontology/checks_import.py`）：`CHECKS_FILES` 四文号循环导入，
  checkCode 前缀 93-x.y / pb3-N / jf8-N，docKey/docNo/docTitle 写入 dataJSON；
  仅 jg24 建 Clause/VerudictRule 边（其余文号不悬空引用），mapsToTerm 全文号建立；共 344 项
  （jg24 116 + jg93 140 + pboc3 56 + jf8 32），element/metric/step/interview/finding 六维齐备。
- **API**（`app/main.py`）：`/api/checks` 新增 `doc` 参数（匹配 docKey/docNo），返回 `byDoc` 聚合；
  详情接口兼容空 citesClause/verdict（非 jg24 文号正常渲染）。
- **前端**：监管检查库新增「文号」下拉（四文号），列表新增「文号」列，元信息行展示按文号统计；
  标题改「监管检查库（多文号 · 关联检索）」。
- **数据口径说明**（与 PPT 数字核对结论，避免误标）：
  - 平台 jg24 展示 **116 项 = 检查项**（由 jg24-checks.json 派生，准确；领域 gov55/tech37/cross24，P0 33/P1 66/P2 17）；
  - 金规〔2024〕24号正文**条款 81 条**（PPT「80 多」为条款口径，与 116 检查项并行、不可并列相加）；
  - 93号自查表 **139 项（标准版）/ 140 项（带监管版）**（PPT 写 116 有误；厂商「118 条」为归并宣传口径）；
  - 人行令3号 **56 条**；金发8号 **32 项**。
- **修复**：pboc3 单段条款正文（与条头同行）解析丢失问题——条头行内正文并入条文原文，
  页脚「相关稿件」截断；修复后 56 条全部非空（pb3-42 等 22 条补全），GUI 实测
  pb3-42 六维详情条文原文 219 字完整渲染；关键词「勒索」命中 5 项（15.7/15.9/22.3 等）。

## v1.10.3（2026-10-19，知识检索并入总览驾驶舱，搜索引擎式布局）

- 移除导航独立项「知识检索」，搜索功能并入「总览驾驶舱」作为顶部子栏目：居中大搜索框（一体圆角输入框，回车触发检索，
  无搜索按钮），下方为「检索结果」与「实体详情（语义核对）」子卡片。
- 原驾驶舱内容（闭环说明/统计、最近留痕）移至页面底部。
- GUI 实测：驾驶舱搜 IDC → 命中 2 条（OIDC 控制 + IDC Frontier 案例）→ 点击案例 → 详情完整
  （495 家/4 区域/别名/标签/关系链），闭环说明与最近留痕仍正常渲染于底部。

## v1.10.2（2026-10-19，知识检索视图：页面级手工测试新增本体的入口）

- 平台导航新增「知识检索」视图：搜索框调 `/api/search`（canonical 图 + knowledge.json 快照双源合并），
  结果点击调 `/api/entity/{id}` 查看详情（类型/级别/状态/标题/摘要/别名/标签/官方来源/关系链），
  使外部同步新增本体可在页面上直接手工测试"是否可检索、语义是否正确"。
- GUI 实测：搜 Xandr → 命中 1 条 → 详情完整（860 万欧元/RTB/Grindr/敏感数据/官方 Datatilsynet 链接/四条关系链）语义正确。

## v1.10.1（2026-10-19，审核菜单合并 + 按钮状态规则 + 批次切换修复）

- **菜单合并**：「知识入库审核」并入「待审核队列」单一入口。两者逻辑关系：同一审核职能、不同数据源——
  平台知识候选（`/api/review/queue`，手动收集/自动导入产生的实体/提案）+ 知识库入闸候选
  （`/api/ingest/review`，外部同步/本地学习经 ingest 管线的候选）。视图内分两个数据区块，导航仅保留一项。
- **按钮显示规则**：知识库入闸候选按审核状态渲染——pending 显示「批准/拒绝」按钮；approved/rejected
  仅显示状态徽标（已批准/已拒绝），不显示操作按钮；平台知识候选区块保持原状（队列内均为待审项）。
- **批次切换修复**：`loadIngest` 批次选择改为以下拉当前值为准并同步记忆变量，修复切换批次后仍显示旧批次的问题。
- **检索双源合并**：`/api/search` 从"canonical 命中即返回"改为 canonical + knowledge.json 快照双源合并去重，
  避免漏检 json 中的同关键词实体（实测 q=IDC 同时命中 control-oauth-oidc 与 case-2026-idc-frontier-ransomware）。
- GUI 实测（mac 浏览器真实点击）：demo pending 候选显示双按钮 → 点「拒绝」状态变已拒绝且按钮消失 →
  重置后点「批准」状态变已批准且按钮消失 → 主批次 2026-10-19 五条已批准均无按钮、批次统计 5/5 正确；
  验收用 demo 批次已删除。API 往返（reject→approve 恢复、无效候选 400、非法 action 400）均通过。

## v1.10.0（2026-10-19，知识入库审核并入平台 + 外部周同步 5 实体入库）

### 外部周同步（定时任务「数据安全知识库·外部每周同步」批次 2026-10-19）
- 采集 5 条权威候选并经人审全部批准后事务合并（ingest `merge --apply`，validate --strict 0/0）：
  - **案例 ×3**：case-2026-xandr-grindr-norway（挪威 DPA 对 Xandr 860 万欧元罚款，该局史上最高）、
    case-2026-ico-mps-third-party-platform（ICO 对伦敦警察厅训诫+执行通知，第三方平台共享 179 人信息）、
    case-2026-idc-frontier-ransomware（软银云 495 家客户勒索事件，4 区域数据难恢复）；
  - **法规 ×1**：law-police-cyber-supervision-measures（公安部令第176号，10-01 施行，batch V16）；
  - **标准 ×1**：standard-gbt44462-4-industrial-data（GB/T 44462.4-2026，10-01 实施，batch V16）。
- 知识库实体 493→**498**、边 9303；id-registry 登记 batch V16；canonical.ttl 编译/发布/SHACL 全绿。

### 知识入库审核模块并入平台（复用原系统架构与 UI，不再另搭独立工作台）
- 后端新增 `app/services/ingest_review.py`（读 10 工程 `ingest/staging` 的 manifest+草稿+decisions.json，
  批准/拒绝写 decisions.json，与 CLI `approve/reject` 同文件，`merge --apply` 无缝衔接；只写 decisions、绝不直接写 content/）。
- REST 新增三路由：`GET /api/ingest/review/batches`、`GET /api/ingest/review?batch=`、`POST /api/ingest/review/{eid}/decision`。
- 前端 `app/web/static/`：index.html 导航新增「知识入库审核」视图、app.js 新增 loadIngestReview/ingestDecide
  （复用平台 card/badge/button 样式与待审核队列范式）；批次选择 + 候选卡片（类型/置信度/来源/建议双链/证据）+ 批准/拒绝。

### 资产层检索 json 兜底（v1.10，docs/09 §4.3 四态链）
- canonical 只编译 term/control/solution/guide/topic（MVP 范围），case/law/standard/organization 走注册表引用路径不进图；
  现给 `kb_read.get_entity/search` 增加 **knowledge.json 快照兜底**（build 派生产物，含全量类型），
  使审核合并后的新案例/法规/标准可被 `/api/search`、`/api/entity/{id}` 检索。
- 实测：`/api/search?q=Xandr`→case-2026-xandr-grindr-norway；`q=公安部令第176号`→law；`q=44462`→standard；
  `/api/entity/{case|law}` 均返回完整详情；`/api/ingest/review/batches` 2026-10-19 批次 5 候选 5 approved。

### 说明
- PG（ekos_ds_kb）`kb_entity` 由 canonical.ttl 投影，仍不含 case/law/standard（编译范围决策）；是否将全量类型纳入
  canonical 编译（使 PG 投影也覆盖案例/法规/标准）留待任务线2 拍板，可复用 v1.6.0 定向 law 的既有管线扩全量。
- 独立 8450 审核工作台已停止并废弃，审核统一收敛至 8420「知识入库审核」视图。

## v1.8.0（2026-10-12，产品化演进 · 数据库统一管理资产层 + 网关产品化）

### 背景（任务线3 三个并行工作包 A/B/C，代码已落地并实测，本版为文档收口）
- 承 `docs/09-产品化演进-数据库统一管理.md`（366 行已定稿）：把权威知识从"进程内内存图 + SQLite"
  抽出一层**独立数据库资产层**，并给 REST:8420 网关补上认证/限流/审计，不新造轮子、不破坏现有演示。
- 总原则：**复用本机 OrbStack 既有服务、最低成本、端口避让、不新造**（大白话：家里现成的炉子先拿来用，
  不另买一台、也不占别人的灶台）。**本版本变更记录只描述实测结果，不含新代码。**

### 工作包 A · 设计定稿（docs/09）
- `docs/09-产品化演进-数据库统一管理.md` 定稿（366 行）：选型 = 复用本机 OrbStack 既有服务；
  **ER 模型（实体关系模型，大白话：把知识画成一张张表、表与表之间用编号连线的设计图）9 表**
  `kb_entity / kb_relation / control / inspection_check / check_element / law_clause /
  doc93_selfcheck_item / doc93_report_entry / schema_migrations`；
  **迁移（migration，大白话：给数据库结构记版本号、每改一次结构落一笔账、可整笔记回退的施工台账）策略**：
  `schema_migrations` 台账 + 每迁移一个事务（transaction，整批要么全成、要么全撤）+ down 回滚；
  网关契约 `DB_READ_FROM` 三态；待定 Q1–Q5。
- §1.3/§1.4 如实记录实测偏差：15432 实为运行中的 `wren-postgres`（非原计划库）、`ekos-postgres` 未启动。

### 工作包 B · 数据库落地（9 表入库实测）
- 新增 `scripts/db_migrate.py`（结构迁移）：`up / status / rollback <n>` 三命令，**幂等（重跑不出错、
  不重复建表）**；回滚实测 checksum（内容指纹，一串代表文件内容的编码）字节一致 `9316fe95a4b92e70`。
- 新增 `scripts/db_seed_kb.py`（知识灌库）：整批重建、幂等，**三连跑计数一致**。
- `app/config.py` 集中 `KB_PG_DSN=postgresql://test:test@127.0.0.1:15432/ekos_ds_kb`：
  **PostgreSQL（开源关系型数据库，大白话：一张张大表格存数据的标准数据库）** 复用运行中的
  `wren-postgres`（端口 15432），新建独立库 `ekos_ds_kb`，**未动其 test 默认库**
  （借来人家的灶台煮汤，另起一口小锅，不碰人家锅里的东西）。
- **9 表入库实测计数**：kb_entity **1113**（1036 类型化 + 77 引用节点）/ kb_relation **7860** /
  control **104** / inspection_check **129**（金规 116 + 93号文 13）/ check_element **483** /
  law_clause **57** / doc93_selfcheck_item **139** / doc93_report_entry **0**（空表就绪）/
  schema_migrations **1**。
- **pgvector（PostgreSQL 的向量检索扩展，大白话：给数据库装上"按意思相近程度找东西"的能力）未启用**：
  宿主是 plain pg15-alpine，`ekos_ds_kb` 内实测扩展仅 `plpgsql`；按 Q3 维持预留位
  （不 `CREATE EXTENSION vector`、不灌 embedding 向量）。
- 复用栈验证（只读探测）：Fuseki:3030 SPARQL 端点 ds 图 **19,927 三元组**（HTTP 200；
  curl 需加 `--noproxy '*'` 绕过本机代理）；RAGFlow:13080 前端连通（**只读探测，未建库、未写数据**）。

### 工作包 C · 网关产品化（三态读源 + 认证/限流/审计）
- `app/config.py` 新增两个开关：`DB_READ_FROM` **三态**（`json` / `canonical` / `db`，默认 `json`）；
  `GATEWAY_AUTH_ENABLED`（默认 `off`）。
- 新增 `app/services/db_kb.py`：**PG 投影只读服务**（把库里的知识按与内存图一模一样的形状供上层读，
  大白话：给新灶配一个和旧灶一模一样的取菜窗口）。已按真实 schema 修 4 处：title 用 `COALESCE`
  （空值合并）兜底、要素 `criteria` 空值兜底、`citesClause` 补 uri、`search` 追加 `data_json` 的
  ILIKE（不分大小写的模糊匹配）。
- 新增 `app/services/kb_read.py`：**三态回落路由器**（json→不动图；canonical→读内存图；
  db→先读库、库断链自动回落图）；检查详情在 json 态返回 `None`，保住 SQLite 旧链路不被误切。
- `app/main.py` 新增 `gateway_guard` **中间件（middleware，大白话：每个请求进门先过的一道岗亭）**：
  **复用 `app/mcp_server/auth.py` 的 `Allowlist`（白名单，准许进出的钥匙板）/ `RateLimiter`（限流，
  大白话：按每分钟次数限速防刷接口）**，**不新造认证体系**；**审计（audit，大白话：谁、什么时候、
  调了什么的流水账）落 `audit_log`**。`/api/entity/{id}`、`/api/search`、`/api/controls` 切到 kb_read；
  `/api/checks/{code}` 三态回落（db→canonical→SQLite）。
- `app/mcp_server/platform_tools.py` 的 `dsec_check_detail` 先走 kb_read（db→canonical），未命中再落
  SQLite 六维；**顺带修复 v1.7 遗留 latent bug（隐蔽 bug，大白话：平时不发作、一调用才露馅的暗伤）**：
  return 写在 `with`（自动开关的连接块）之外，导致使用时连接已关闭（closed-connection）。
- 新增 `scripts/smoke_v18_gateway.py` 网关冒烟。
- **实测**：db 真读 `/api/controls` total=**104**、`/api/checks/1.1` source=**db**
  （domain=gov / priority=P0 / citesClause=cl-10 / 要素 3 条）、`/api/entity/control-abac`、
  `/api/search?q=ABAC` 命中 3、`q=党委` 在 db 侧 0 命中**自动回落 canonical**（total=3）；
  **断链回落实证**（health=False → 自动走 canonical、仍 HTTP 200 不中断）；认证（无 token / 坏 token
  → 401、白名单内 → 200）、审计落 audit_log、限流件测试通过；MCP `dsec_check_detail` db 态 source=db；
  `demo_e2e / demo_checks`（json 与 db 双模式）exit 0。

### 已知边界（诚实标注，属后续项、非缺陷）
- **pgvector 未启用**：宿主 plain pg15-alpine 无 vector 扩展，向量列仅预留位（Q3）。
- **ekos-postgres 未启动**：容器处于 Created（已建好未开机）态，15432 已被 wren-postgres 占用，
  直接启动会端口冲突。
- **检查短标题 / `law_clause.text` 未投影进库**：db 侧这两处双空即判 miss，自动回落内存图兜底。
- **`DB_READ_FROM` 默认仍是 json**：db 仅作**灰度**（灰度，大白话：先小范围试用、稳了再逐步铺开），
  不破坏现有 8420 演示。
- **13 条控制缺口仍未清零**：align 实测仍 0 自动对齐 / 13 待补，随知识侧补码后 `--apply` 解除，
  **不属本 v1.8 范围**（沿用 v1.7.0 结论）。

## v1.7.0（2026-10-12，EKOS 对齐 · SPI 适配层 + kb-publish 发布流水线 + 全量知识编译 + 控制缺口对齐机制）

### 背景（任务线2 三个并行工作包，代码已落地并实测，本版为文档收口）
- 承 docs/07《EKOS 架构对齐方案》§3–§6 的阶段 B 计划，当日以三个并行工作包把"适配层 SPI 收口（B1）、
  全量知识编译（B2）、消费发布链路（B3 通道）、缺口闭环机制（B4）"一次落地；D1–D6 决策按默认选项
  全部拍板（见 `docs/08-EKOS对齐决策记录.md`）。**本版本变更记录只描述代码/脚本实测结果，不含新代码。**

### 工作包 A · 适配层 SPI 收口（B1，docs/07 §3 设计已实现）
- 新增 `app/adapters/`（统一适配器目录，大白话：按统一插座规格接零件的地方）：
  - `base.py`：SPI 契约四件套 `name / version / health() / capabilities() / execute(...)`（大白话：
    每个零件自报姓名、版本、健康状况、能干什么、怎么干）。
  - `registry.py`：注册中心（开机点名登记所有适配器、按配置选一个上岗）。
  - `retriever.py`：把 `graph_backend` 三后端（memory / oxigraph / fuseki）包成 RetrieverAdapter（检索引擎可插拔）。
  - `llm.py`：LLMAdapter，含 rule-fallback（规则兜底）降级链。
  - `policy.py`：PolicyAdapter 占位，默认实现 `open-dev`（一律放行，单机演示）。
  - `masker.py`：MaskerAdapter 空占位（本期不做，待有 PII 场景再补）。
  - `__init__.py`：按 `config.ADAPTERS` 段配置装配。
- `app/config.py` 新增 `ADAPTERS` 段；环境变量 `ADAPTER_RETRIEVER / ADAPTER_LLM / ADAPTER_POLICY / ADAPTER_MASKER` 可覆盖选型。
- 冒烟实测 `scripts/smoke_adapters.py`：注册 6 个适配器；memory↔oxigraph 真实切换一致
  （pyoxigraph 0.5.11 在 py3.14 `.venv` 可装，Control 91 / InspectionCheck 116 两后端读数一致）；
  LLM 无 key 时 `degraded=true` 走规则兜底；Policy/Masker 占位符合契约；旧调用路径向后兼容。

### 工作包 B · kb-publish 发布流水线（B3 通道，docs/07 §4.3 方案 B 真发布）
- 新增 `scripts/kb_publish.py`：一次编辑触发全链校验 + 失败自动回滚的发布流水线（大白话：
  改一条知识 → 进影子草稿间彩排 → 三道质检门 → 全过才搬到正式站点，任何一道不合格整箱退回）。
- 流程：影子工作区 `.kb-publish/shadow/`（从 10 工程**只读** copytree：content/ontology/sources/site/scripts +
  control-codes.csv）→ 控制对账（reconcile）→ 质量基线门（`validate.py --strict`，默认要求"基线无回归"；
  `--strict-zero` 才是 ERROR 0 / WARN 0 的终态）→ 可选编辑（`--demo-edit` / `--bad-edit`）→ 快照 previous →
  门② `build.py`（前端构建输出重定向到影子 `data/`）→ 门③ `kb_compile.py --check`（`KB10_ROOT` 指向影子，
  要求 conforms=True / 脚本断言 0 / CSV-TBox 漂移 0）→ 提升 `site-preview/`；任一步失败自动回滚。
- 参数：`--demo-edit`（良性编辑演示）、`--bad-edit`（注入非法 level=L9）、`--rollback`、
  `--strict-zero`、`--no-reconcile`。
- 实测：给 `cia-triad.summary` 加联调标记，canonical.ttl / 前端快照 / TestClient API 三处全命中；
  `--bad-edit` 被质量门拦截并自动回滚。**正式消费切源（退役 base-snapshot 手工副本）仍是下一步**，
  `KB_READ_FROM=json|canonical` 双模式开关保留。

### 工作包 C · 全量编译 + 缺口闭环机制（B2/B4）
- 编译器全量扩展（原硬编码只编 term+control+检查 1.1，现推广为全量）：
  - **Solution 33 / Guide 4 / Topic 7**（93号文 topic 自然收录）全部 canonical 化；
  - **金规 116 检查 + 470 检查要素 + 56 法条 Clause** 全部 canonical 化；
  - 三元组 13,881 → **20,425**；两次编译 md5 一致（幂等 `1360810b580220afb4fe138223353e58`）；
    pySHACL conforms=True；CSV/TBox 漂移 0。
- 控制词汇权威源 `data/control-codes.csv` 已被并行团队补码到 **104 行**
  （分层 EP15 / NW17 / SVC30 / PROTO14 / MGMT28）。
- 新增 `scripts/align_controls.py`（控制对齐脚本）：默认 **dry-run（空跑试算不写盘）**，
  `--apply` 才写回 OntoRegGov 占位 JSON；对齐键 = csv 标题逐字匹配，且要求 CT 唯一 / 层匹配 / 有法规依据。
  实测：**0 条自动对齐 / 13 条待补**——其中 2 条 csv 已有语义候选但标题措辞不同需人工对齐
  （机房物理安全防护 → CT-NW-017；同意管理系统功能 → CT-PROTO-014），另 11 条 csv 完全未建。
  报告落 `reports/align-report.json`。
- 已知边界（诚实标注）：
  - **13 缺口未清零**的原因：不是脚本失灵，是知识侧 csv 尚缺 11 条控制、另有 2 条标题措辞需人工对齐；
    待知识侧补码后 `--apply` 即可清零。
  - **116 检查的 richer 细层未入 canonical**：Metric（度量 342）/ InterviewQuestion（访谈 243）/
    InspectionMethodStep（方法步骤 705）/ VerdictRule / FindingPattern 仍只在 SQLite 种子库（jg24-checks.json 导入），
    本期未编入 canonical.ttl。
  - **质量门默认是"基线无回归"而非 0/0**：`--strict-zero` 为终态开关，收紧是下一步。

### 决策记录（D1–D6，2026-10-12 按默认选项推进，用户可随时改）
- 详见 `docs/08-EKOS对齐决策记录.md`：D1 双通道并行（REST+MCP）、D2 Action 本期严格只写运行命名空间、
  D3 脱敏网关本期不做（留 SPI 占位）、D4 维持 memory(RDFLib)+导出 ttl（oxigraph 已实测可插拔、
  fuseki 端点可达但未同步）、D5 93号文 139 项与金规 116 本期不合并同一 schema、
  D6 base IRI 维持 `https://schema.cheersai.local/ds/` 占位。

### 回归
- `demo_e2e` / `demo_checks`（canonical 与 json 双模式）exit 0；`test_thresholds` 49/49；
  SQLite 侧计数不变：InspectionCheck 116 / ControlPlaceholder 48（35 aligned + 13 pending）。

## v1.6.0（2026-10-12，93号文编入 canonical 知识层 + 接入层最小 API + 消费演示页）

### 背景（最小纵切，不做全量切换）
- 把**金办发〔2025〕93号**（金融机构数据安全管理能力提升专项行动）从 10 工程
  `ingest/v17` 同构数据源编入 canonical 权威知识层，并新增接入层最小 API 与一页演示，
  证明"前端 HTML ← 后端本体知识库"链路通。**不切** 10 工程 HTML 主站源、**不全量**
  编译其余 21 法 / 6 专题（留待阶段2）。

### 新增：93号文编译（law + topic + 检查项集合）
- `app/kb_compiler/doc93.py`（新）：只读 `ingest/v17/att1-selfcheck.txt`（附件1 自查要点），
  确定性抽取 13 个带编号自查子项（三5 / 四5 / 六3），按**与金规 116 检查同构**的形状编译：
  - `InspectionCheck`（复用金规语义/形状）：checkCode=`93-<大类>.<序号>`（如 `93-3.1`），
    title=子项名、summary="是否……"问句、domain=六大方面名、priority=P1、articleNo="附件1 自查要点"。
  - `CheckElement`：每条检查 1 个要素（elementCode=`93-x.y.1`），经 `hasElement` 挂接。
  - `Clause`（cl-93-att1，代表附件1）：`citesLaw`→93号文 law，检查经 `citesClause`→该 clause，
    打通 检查→条款→法规 链。
- `parse.py`：定向纳入 2 个 canonical MD（`content/laws/finance-data-security-special-action-2025.md`
  = law、`content/topics/topic-finance-data-security-special-action.md` = topic），走通用实体管线
  （term/control 已支持的 type mapping），不全量扫 laws/topics。
- `compiler.py`：TBox 补 `publishedBy/governs/citedBy`（law/topic 关系）；stats 增 doc93_* 计数。
- 实测：术语 218 / 控制 91 / 三元组 **13526→13881（+355）**；93号文 law 1 / topic 1 /
  InspectionCheck 13 / CheckElement 13 / Clause 1；pySHACL conforms=True、脚本断言 0、CSV/TBox 漂移 0；
  两次编译 md5 一致（幂等 `ec17058d…`）。

### 新增：接入层最小 API（从 canonical RDF 读，进程内 RDFLib）
- `app/services/canonical_kb.py`（新）：懒加载 `app/data/canonical.ttl` 进内存图，提供
  `get_entity / search / list_controls / get_check`。
- `main.py` 新路由：`GET /api/entity/{id}`、`GET /api/search?q=`、`GET /api/controls`（91 条）；
  `GET /api/checks/{code}` 在 `KB_READ_FROM=canonical` 且 SQLite 未命中时**回落本体库**（93号文
  `93-x.y` 由此可查），金规 `1.1` 仍走原 SQLite——**回退语义保留**。
- 验证：`fastapi.testclient.TestClient` 进程内实测（按需确认模式不绑端口），8 条路径全 200。

### 新增：最小消费演示页 `samples/ekos_consumer_demo.html`
- 双模：`file://` 直接打开用**内嵌编译快照**（`window.__KB_SNAPSHOT__`，含 93号文 law/topic/
  抽样3检查项 + 金规1.1 + 控制总数91）；服务模式 `fetch /api/…` 拉实时数据。
- 证据：内嵌快照关键串全部 grep 命中；服务模式接口 TestClient 全 200。**未启动 headless Chrome**
  （权限模式会拦），以 HTML 内嵌断言 + TestClient 替代截图。

### 影子比对增量（`reports/shadow-compare.md` §5）
- 93号文 law/topic 与 knowledge.json 共有 title/summary **0 不一致**（比对 2）；
  13 检查 + 1 Clause + 13 要素 = **27 个新增**知识实体（knowledge.json 本就 0 条 inspectioncheck）；
  关系边：citesClause 13 / citesLaw 1 / hasElement 13 / law·topic 对象关系 18 / mentions 70。

### 回归
- `demo_e2e / demo_checks / demo_ledger`（KB_READ_FROM=canonical）均 exit 0；test_thresholds 49/49；
  门禁负向（候选未复核等）仍拦；`KB_READ_FROM=json` 回退 seed+demo_e2e 正常。
- SQLite 计数不变：InspectionCheck 116 / ControlPlaceholder 48；canonical 控制仍 91。

### 10 工程零写入举证
- 本轮开始 2026-10-12 07:59:21；编译器输入文件（ingest/v17、content/laws|topics、ontology.yaml、
  control-codes.csv、id-registry.yaml）mtime 全部 ≤ 当日 00:10；`find -newermt` 结果为空。

### 未做项（诚实标注）
- 附件2 报送表 139/140 行 = 填报模板（非知识实体）、附件3 统计表 = 空白模板，本切片不编；
  其余 21 法 / 6 专题仍留待阶段2全量；演示页截图未跑（以 HTML 断言 + TestClient 替代）。

## v1.5.1（2026-10-12，P2 收尾修复 + 终验缺陷修复）

### 修复（承 v1.5.0 canonical 编译器）
- **P2（架构对齐硬约束）**：编译器此前"声称读 ontology.yaml/control-codes.csv 但实际枚举硬编码、CT 码仅从 MD 汇聚"。
  本轮真接上两个编辑权威源并做双向对账：
  - 新增 `app/kb_compiler/schema.py`：`load_ontology_schema()` 读 10 工程 `ontology/ontology.yaml`（实测 11 实体类型 / 21 关系类型 / level·status·layer·lifecycle·controlType 枚举），`load_control_codes()` 读 `data/control-codes.csv`（91 行，6 列）。
  - `compiler.py`：control 的 `ctCode/layer/controlType/family` **以 CSV 权威值写入**（MD 仅补 lifecycle/standard_mappings）；新增 `cross_check_codes()`（MD↔CSV 集合差 + 逐条 code/layer/title 漂移比对）与 `assert_tbox_consistency()`（yaml 类型都有 TBox 类）；漂移写入 stats，`kb_compile.py --check` 漂移非空即非零退出。
  - `shacl.py`：编译期枚举**从 ontology.yaml 读取**，删除硬编码。
  - 实测：`--check` 全绿（term 218 / control 91 / 三元组 13526，分层 EP15/NW16/SVC26/PROTO13/MGMT21，pySHACL conforms=True，CSV/TBox 漂移=0）；两次编译 md5 一致（幂等）；负向（坏 CT `XX-BAD-999` / 重复 CT / 缺法规依据 / 非法 level `L9`）全拦；影子比对 309 实体 title/summary 0 不一致，补回 CT91/mappings355/关系边1610/mentions4106。
- **终验缺陷（运行期 SHACL）**：`CheckResultShape`（closed）未声明 `dsec:code`，而 CheckResult 数据自带业务主键 code 字段——DB 中出现检查结论（InspectionRun/CheckResult）后，发布路径的全图 SHACL 校验报 closed 违例，**阻断后续任何实体发布**（此前各轮验收未在含 CheckResult 的库上再发布实体，故未暴露）。修复：`app/ontology/tbox.py` CheckResultShape 补 `sc(s, DSEC.code)`；修复后真实已发布义务 ob-o1 校验放行、全图 `validate_full` conforms=True。

### 回归（KB_READ_FROM=canonical）
- demo_e2e（O6 unknown→conform / partial→compliant）、demo_checks（1.1 fail→缺口→补全→pass）、demo_ledger 均 exit 0；test_thresholds 49/49；三负向（同人自审 / llm 未复核 / 坏来源）仍拦；`KB_READ_FROM=json` 回退 seed+demo_e2e 正常。
- 10 工程（编辑权威源）本轮 07:00 后零写入（find 举证）；OntoRegGov 内全部落盘。

## v1.5.0（2026-10-03，确定性本体编译器 + canonical 知识源纵切 MVP）

### 背景（docs/05 落地）
- 旧底座投影 `base_import` 只读 10 工程 build 副产品 `data/knowledge.json`，仅投影 8 类、
  字段截断为 type/title/summary/official_url→seeAlso，漏 solution/guide/topic 整类 43 条、
  漏 CT 码/分层/生命周期/标准映射/关系边（docs/05 §1 已诊断）。本版新增一条**确定性编译链**：
  直接读 10 工程**编辑权威源**（ontology.yaml + content/*.md + id-registry.yaml + control-codes.csv，全程只读），
  编译成带统一 base IRI 的 canonical RDF/OWL+SHACL 图，并以 feature flag 旁路接入平台。

### 新增：确定性本体编译器 `app/kb_compiler/`
- `iris.py`：集中 base IRI（`https://schema.cheersai.local/ds/`，env `CANONICAL_BASE_IRI` 一处可改），
  派生三段命名空间 ont/kb/run；运行期数据与权威知识层逻辑隔离。
- `parse.py`：自含 YAML frontmatter + Markdown wikilink 解析（不 import 10 工程脚本）；
  `load_registry()` 读 id-registry.yaml 全量 id→type 供跨类型关系解析与零断链校验。
- `compiler.py`：编辑源 → RDF；克制 OWL 子集（subClassOf/datatype/object property/inverseOf/symmetric）；
  slug/CT 码/检查号(1.1) 稳定 URI；layer 英文词→EP/NW/SVC/PROTO/MGMT；幂等（to_canonical_graph 落盘字节一致）。
- `shacl.py`：编译期形状 + 脚本断言（CT 正则 `^CT-(EP|NW|SVC|PROTO|MGMT)-\d{3}$` + 全局唯一、
  control≥1 法规/标准依据、零断链）。
- `adapter.py`：canonical → 平台 dsecb 命名空间富字段快照（加 ctCode/ctLayer/lifecycle/controlType/family）。
- 脚本：`scripts/kb_compile.py [--check]`（编译+校验，违例非零退出）、
  `scripts/kb_shadow_compare.py`（影子比对，**唯一**被允许读 knowledge.json 的地方，仅作对账基准）。

### 接线（feature flag `KB_READ_FROM`）
- `config.py` 新增 `KB_READ_FROM=json|canonical`，默认 `json`（旧行为，可一键回退）。
- `base_import.project()` 在 canonical 分支改走编译器+适配器写 `base-snapshot.ttl`；json 分支原样。
- 切 canonical 后：91 控制分层 EP15/NW16/SVC26/PROTO13/MGMT21、91 带 CT 码、35 已对齐/13 缺口占位不变。

### 验证（全绿）
- 编译：218 term / 91 control / 检查1.1(3要素) / 13526 三元组；pySHACL conforms=True、0 脚本违例；
  负向样例（坏 CT 正则/重复 CT/缺依据/非法 level）conforms=False 被拦。
- 影子比对：309 实体 title/summary 与 knowledge.json **0 不一致**；新编译补回 CT91/ctLayer91/lifecycle176/
  hasMapping355/alias1233/tag977/关系边1610/mentions4106；旧路整类漏投 solution33/guide4/topic6 已显式标注。
- 平台回归（canonical 与 json 两模式）：demo_e2e / demo_checks(fail→pass) / demo_ledger / test_thresholds(49/49) 全 exit 0；
  O6 unknown→conform、partial→compliant；三负向（同人自审/AI候选未复核/坏 SHACL）仍拦；MIME 正确。

### 边界
- MVP 仅编译 term+control+检查1.1；solution/guide/topic（43 条）与全量 116 检查的 canonical 化列入阶段2。
- 静态 HTML 本阶段不切源（仍由 10 工程 build 从 YAML 生成，保 file:// 离线）；HTML 切 RDF 源列下一步。
- 不引 Fuseki/Oxigraph/owlready2/重 reasoner；保留 graph_backend 可插拔接口，默认 memory/rdf 导出。

## v1.4.1（2026-10-03，CheersAI 品牌套件前端改版 + MCP 根路径可达）

### 变更
- **前端整体改版为 CheersAI 品牌套件风格**：按 `/Users/FYP/Documents/WorkSpace/CheersAI/CheersAI - docs/CheersAI品牌套件与企业UI规范.md`
  落地（主色 #2055D7 / 深色 #1847C7 / 深蓝标题 #1E3268 / 浅蓝底 #EEF4FF / 边框 #9AB7FF / 正文 #243447），
  白底+品牌蓝系、企业级克制观感；styles.css 全量重写（卡片/表格/徽章/按钮/表单/折叠/滚动条/响应式），
  页眉嵌入 CheersAI Logo 与 favicon（素材源自 `~/Pictures/CheersAI/logo/`，拷贝至 static 目录，无 CDN 依赖）；
  10 个视图（含检查台账）全部保留，JS/HTML ID 与 onclick 零改动（脚本核对无缺失），node --check 通过。
- **MCP 根路径可达**：`app/mcp_server/auth.py` 对 `GET /` 返回服务信息 JSON（端点/工具清单/调用说明），
  解决浏览器直接访问 http://127.0.0.1:8422/ 时 404 被误判为"服务不可达"；/health 与 /mcp 行为不变。

### 验证
- 浏览器实测 8420 页面：品牌样式生效（Logo 38×38、深蓝表头、浅蓝底、导航胶囊高亮），无 console 错误；
  8422 根路径 200（JSON 信息页）、/health 200、MCP 客户端调用正常。

## v1.4.0（2026-10-03，图存储后端升级 + 远程 MCP 服务）

### 变更：图存储（标准 SPARQL 层，可插拔）
- 新增 `app/ontology/graph_backend.py`：`memory`（默认，进程内 RDFLib）/ `oxigraph`（进程内 pyoxigraph 标准 SPARQL 存储，可落盘）/ `fuseki`（HTTP SPARQL 端点，本地容器或远程）三后端，环境变量切换（`GRAPH_STORE_BACKEND/ENDPOINT/DATASET/USER/PASSWORD/FILE`）。
- `sync()` 全量镜像当前物化图（TBox+底座快照+已发布实体）到所选后端（幂等：CLEAR+装载）；`query()/ask()` 统一标准 SPARQL 入口。
- 判定轨道不变：SHACL 闸门/why 溯源仍走进程内 RDFLib，保证确定性。
- 新 API：`GET /api/graph/backend`（后端与三元组统计）、`POST /api/graph/sync`（镜像）、`POST /api/graph/sparql`（标准 SPARQL 代理）。
- 部署：`deploy/docker-compose.fuseki.yml`（stain/jena-fuseki，tdb2，/ds 数据集，admin/admin 写鉴权）；`deploy/README-fuseki-neo4j.md`（含 Neo4j 适配器 Cypher 映射草案）。
- 新增 `scripts/smoke_graphstore.py`：memory/oxigraph/fuseki 三后端同一组断言全过（22 法规/91 控制/218 术语/116 检查/48 占位/133 边/35 带 CT 码 + 多跳 join + ASK）。

### 变更：远程 MCP 服务
- 新增 `app/mcp_server/`：FastMCP 1.x（mcp>=1.0,<2）工具服务，stdio / streamable-http 双传输。
- 工具：dsec_control_gaps / dsec_control_alignment / dsec_check_detail / dsec_create_inspection_run / dsec_record_check_result / dsec_inspection_ledger / dsec_list_plans / dsec_graph_backend / dsec_graph_sparql（与 HTTP API 共用服务层与 DB）。
- 鉴权：复用底座 10 工程范式——Bearer allowlist（`config/allowlist.json`，mtime 热加载）+ 限流 + `/health` 免鉴权。
- 运行：`MCP_TRANSPORT=streamable-http MCP_PORT=8422 python -m app.mcp_server.server`；已用官方 MCP 客户端经 stdio 与 streamable-http 实测工具调用。

### 验证
- 回归全绿：test_thresholds 49/49、demo_checks、demo_ledger、smoke_graphstore（三后端）。
- Fuseki 容器实测：/ds 建库、全图 19,507 三元组入库、标准 SPARQL 查询/更新/数据装载、Basic 鉴权。

## v1.3.0（2026-10-03，多人检查台账与周期复查）

### 变更
- **检查计划**（新表 `inspection_plans`）：名称/范围/周期(monthly·quarterly·half-yearly·yearly)/起止/负责人/覆盖检查项；API `POST|GET /api/inspection/plans`、`GET /api/inspection/plans/{id}`。
- **多人检查**：`InspectionRun` 支持挂 `planId` + `assignees`（多人分工，主查+协查）；`GET /api/inspection/runs/{id}` 返回二者。
- **证据归档**（新表 `inspection_evidence`）：运行/检查项/文件名/落盘路径/上传人/备注；API `POST /api/inspection/runs/{id}/evidence`（multipart，≤10MB，防目录穿越，`checkCode/uploadedBy` 等以 `Form` 字段绑定）+ `GET` 列表；文件存 `app/data/evidence_uploads/`。
- **复核签署**（新表 `inspection_signoffs`）：签署人/角色(主查·复核·审批)/结论(approved·returned)/意见；API `POST /api/inspection/runs/{id}/signoff`。
- **检查台账**：`GET /api/inspection/ledger` 聚合全部计划+运行条目（结果汇总/证据数/签署状态/**下次复查日期**=最近运行+周期天数）。
- **前端**：新增「检查台账」视图（计划管理、台账表、证据上传/查看、复核签署）。
- 新服务 `app/services/ledger.py`；`reset_db()` 同步清空新表。

### 验证
- `scripts/demo_ledger.py` 端到端全断言通过：计划→首轮多人运行 fail→证据归档→复核退回→复查轮次 pass→审批通过→台账正确+下次复查=最近运行+90天。
- API 冒烟：health/plans/ledger/runs/evidence(multipart)/signoff 全部 200。

## v1.2.1（2026-10-03，阈值自动判定泛化）

### 变更
- **阈值解析器泛化**（`app/services/inspection.py::eval_threshold`，符号引擎、确定性）：
  - 存在性：有即合格/已列入/有即视为合格/存在即合格/有记录即合格；无即不合格/未见即不合格（取反语义）。
  - 分数 `N/M`（4/4、3/3）：actual 支持分数串或百分比数（纯数字按百分比理解）。
  - 抽样比例："抽查 N 项，≥M 项…"：actual 为个数按 ≥M 判定、为百分比按 ≥M/N*100 判定。
  - 全覆盖/100% → =100；零/0 条/件/项 → =0。
  - 中文比较词 + 数字（可嵌句中）：不低于/不少于/至少/达到/以上→≥；超过/高于/大于→>；
    不超过/至多/以下→≤；低于/小于→<；等于→=。
  - 中文频次：至少每季度一次 / 不少于2次 → ≥N。
  - **多目标并存**（如"核心100%，总体≥80%"）与纯定性句（如"抽查人员能说出…"）保持 manual，
    不强行合取/取一；等价目标（3/3 ≡ 全覆盖 ≡ 100%）自动去重。
- **回归测试**：新增 `scripts/test_thresholds.py`（49 用例覆盖全部形态 + 边界 + manual 边界），退出码 0=全绿。
- **覆盖率**：342 条度量阈值形态可解析率（actual=100 粗测）35.4% → **69.3%**；余下为定性/多目标，保持人工。

### 验证
- test_thresholds 49/49 通过；demo_checks 全部断言通过（fail→pass 闭环不受影响）；demo_e2e 复用无回归。

## v1.2.0（2026-10-03，控制清单正式对齐 v1.5 + 底座快照刷新）

### 变更
- **正式对齐**：48 条 ControlPlaceholder 按 `control_name` 认领 10_知识库工程 v1.5 权威控制编码
  `data/control-codes.csv`（92 条 CT 码）—— **35 条正式对齐**（status=aligned），13 条 v1.5 无语义对应，保持缺口并附补建反馈。
  - 对齐表 `ingest/derive_control_placeholders.py::CT_ALIGN`（hint→CT 码），CT 码/id/标题/层码一律从 CSV 回填，脚本启动全量校验（引用了不存在的 CT 码直接失败）。
  - 平台不造 CT 码的架构约束不变；缺口仅反馈，不编造。
- **本体扩展**：`dsec:ctCode`/`dsec:ctLayer`/`dsec:baseControlId` 数据属性；
  对象属性 `dsec:mapsToFormalControl`（ControlPlaceholder→DSEC.Control，等价底座 dsecb:control）；
  ControlPlaceholderShape 允许新增属性（closed shape 同步扩）。
- **导入/API/UI**：`import_control_placeholders()` 对 aligned 写 ctCode/ctLayer/baseControlId +
  mapsToFormalControl 边，gap 仍 pending_alignment；`GET /api/checks/{code}` suggestedControls 携带 ctCode/ctLayer；
  `GET /api/controls/gaps` 返回 aligned/pending/provisional 统计 + 13 条缺口。
- **底座快照刷新**：迁移后 `config.KB_ROOT` 改为 10 工程绝对路径（env `KB10_ROOT` 可覆盖），
  base-snapshot.ttl 按 v1.5 knowledge.json 重投影：**91 control / 218 term / 22 law** 等。
- **文档**：`data/checks/控制缺口清单.md` 重写为"35 对齐 + 13 缺口反馈"；README/ROADMAP 同步。

### 结果
- ControlPlaceholder=48（aligned 35 / pending_alignment 13 / provisional 0）；suggestsControl 边 133。
- 覆盖 116/116；pySHACL（无推理口径）conforms=True。
- 13 条缺口反馈方向见 `data/checks/控制缺口清单.md` 第三节（供 10 工程 v1.6 补建）。

## v1.1.2（2026-10-03，控制词汇单一事实源对齐 + 控制需求占位层）

架构对齐硬约束：**控制措施(control)权威词汇的唯一事实源在 10_知识库工程，其 v1.5 将产出全量控制 + 稳定编码 `CT-<层码>-序号`（EP/NW/SVC/PROTO/MGMT）**。本平台不造 CT 码、不并行权威控制词表。

### 变更
- **纠正伪对齐**：移除 v1.1.0 给 116 检查生成的 9 条 `InspectionCheck → mapsToControl → 内部演示 ctrl-c1/c2/c5`（这些 ctrl-c* 是 O6 义务演示用、非权威控制、无 CT 码，挂上去会误导成"已对齐权威控制"）。
  - **O6 义务闭环原样保留**：义务维度 `Obligation → ctrl-c1..c7` 的种子与 demo_e2e 不动（已声明"演示性"）。
- **新增 `dsec:ControlPlaceholder`（控制需求占位/ControlNeed）**，与权威 `dsec:Control` 严格区分：
  - 数据属性 controlCodeHint(字面 slug)/controlName/suggestedLayer(枚举 EP/NW/SVC/PROTO/MGMT)/controlTypeHint/alignmentStatus(枚举 pending_alignment/provisional/aligned)/rationale/sourceCheckCodes/articleRefs/baseControlTitle。
  - 关系 `dsec:suggestsControl`（InspectionCheck→ControlPlaceholder，多对多）；provisional 3 条加 `dsec:provisionalBaseControl`→底座 dsecb control（弱关联，注明待 v1.5 CT 确认）。
  - **不**物化成 dsec:Control、**不**出现 CT- 码；URI `dsecr:cp-<hint slug>`。closed SHACL（layer/status 走 sh:in 枚举）。
- **导入**：`import_control_placeholders()` 消费 `data/checks/control-placeholders.json`（48 条），幂等；suggested_layer 去中文后缀规范化为纯层码；status gap→pending_alignment、matched_provisional→provisional。接入 seed/run.sh，新增 `python -m app.cli import-control-placeholders`。
- **API/UI**：`GET /api/checks/{code}` 增 `suggestedControls`；新增 `GET /api/controls/gaps`（45 缺口 + 3 暂定）；检查详情"建议控制措施"区用非成功色徽标（待对齐 / 暂定对应·待CT确认），不呈现为已落实。
- **文档**：docs/02 增"控制词汇单一事实源"；控制缺口清单见 `data/checks/控制缺口清单.md`（反馈给 10 工程）。

### 结果
- ControlPlaceholder=48（pending_alignment 45 / provisional 3）；suggestsControl 边 133，覆盖 116/116。
- 检查侧 → ctrl-c* 伪对齐=0；O6 Obligation→ctrl-c* 仍在；全图无 CT- 伪码；pySHACL（无推理口径）conforms=True。
- demo_e2e / demo / demo_checks 均退出 0；三负向仍拦；MIME 正确。

## v1.1.1（2026-10-03，UI 补强：检查运行结果视图）

第三轮验收仅剩 1 个 P2：浏览器端缺 InspectionRun 结果录入/展示页。本轮只补该视图闭环，不改判定引擎/SHACL/本体/导入数据。

### 新增
- 前端新增"**合规自查**"视图（原生 H5，零 CDN，#1B4FE4，与其它视图 data-view 切换一致）：
  - 选被查对象（既有 DataAsset）+ 选 P0 检查项（默认 1.1，可切 1.2 等）。
  - 按 CheckElement 逐条录 L1-L3 制度具备 / L4 证据 provided·missing（对照 method.evidence_steps）；
    每个 Metric 录实际值交后端阈值判定（manual 项如实提示）。
  - 提交即调用既有 `/api/inspection/runs` + `/results`（未新写判定逻辑）；结果页三色 pass/partial/fail、
    why 逐条溯源（element.code/focus/口径、证据齐备、metric 名·阈值·实际值），fail/partial 列自带 findings 的 问题/根因/整改。
  - "一键发起知识缺口提案"复用既有 `/api/proposals` + 待审核队列；同对象+检查"重检"并展示前后对比（fail→pass）。
- 纯前端实现，复用既有 run/result/get/compare/proposals/queue 接口，未新增后端只读聚合接口。

### 验证
- 1.1 缺 L4 证据 + L5 实际 0<阈值≥1次/年 → `fail`，why 与 findings 正确；一键提案后 `/api/review/queue` 可见。
- 补全（证据 provided + 实际=2）重检 → `pass`；compare `fail→pass`。
- demo_e2e / demo / demo_checks 均退出码 0；三负向仍拦；静态 MIME 正确。

## v1.1.0（2026-10-03，金规24号 116 项监管检查知识库全量落地）

### 新增
- **监管检查语义层**：定义层 InspectionCheck/CheckElement/Metric/InspectionMethodStep/
  InterviewQuestion/VerdictRule/FindingPattern/FocusLevel(SKOS L1-L5)；运行层 InspectionRun/CheckResult。
- **首个真实全量种子**：消费独立 ETL 产物 `data/checks/jg24-checks.json`（116 项，gov55/tech37/cross24，
  P0 33/P1 66/P2 17），幂等导入（重导先删本批派生数据，不动底座与既有闭环）。
  导入结果：116 检查项 / 470 要素 / 342 度量 / 705 方法步骤 / 243 访谈 / 116 判定规则 / 285 常见问题；
  补建缺失法条 Clause 45 条（复用 Clause 承担 RegulationArticle，不新建双轨）。
- **法条对齐**：检查项经 dsec:citesClause 挂 Clause→law-jg24；articleText 用 JSON 忠实原文。
- **底座术语对齐**：mapsToTerm 仅挂底座确有术语（分类分级12/外包6/出境5+出境评估3，共26条边）；
  责任体系/三道防线/数据安全责任制/归口管理 4 主题底座暂无词，列入"待底座补词"，未编造 id。
  mapsToControl 9 条关联既有 ctrl-c1/c2/c5。
- **浏览/检索 API**：GET /api/checks（domain/priority/chapter/keyword 筛选+计数）、
  /api/checks/{code}（六维详情）、图谱 root=ic-1-1 双向 BFS。前端新增"监管检查库"视图（零 CDN）。
- **最小真实合规纵切**：InspectionRun→CheckResult 符号引擎聚合（要素 worst-case+证据齐备度+L5阈值），
  why 逐条溯源；缺证据/阈值不可判定→复用既有提案表建 KnowledgeGapProposal，专家补全后重检转档。
  脚本 `scripts/demo_checks.py` / `python -m app.cli demo-checks`：1.1 党委主体责任 fail→补全→pass。
- 新增 CLI：`python -m app.cli import-checks`。

### 约束/口径声明
- 三档判定与阈值解析为依据办法原文的**演示性确定性落地**，落地需合规复核；阈值无法可靠解析的显式标 manual 并作缺口信号。
- requirements.txt 增加 beautifulsoup4（仅 ingest ETL 复跑用；运行导入仅标准库）。

### 验证
- 全新 venv pip install 成功；/api/health ok；/api/checks total=116，三领域/三优先级计数与权威复核一致。
- 全图 pySHACL conforms=True；三负向仍拦；demo_e2e/demo/demo-checks 均退出码 0。

## v1.0.1（2026-10-02，独立验收缺陷修复回合）

> 针对独立第三方验收报告 2 个 P1 + 7 个 P2 的修复；不推翻架构，全部在原代码上改。

### P1
- **P1-1 静态资源 MIME**：main.py 末尾 catch-all 改为 `app.mount("/", StaticFiles(directory=STATIC, html=True))`
  挂在最后（/api 路由在前优先匹配）。styles.css→`text/css`、app.js→`text/javascript`，
  真实存在的静态文件不再被吞成 text/html，未知前端路由仍回退 index.html。
- **P1-2 关系图谱主链空白**：`/api/graph` 游走由单向（主语出边）改为双向 BFS（同时展开 s→o 与 o→s，
  边保留原方向标签）。从 law-jg24 出发 depth=3 由 2 节点/1 边 → 46 节点/97 边，
  走通 Law→Clause→Obligation→Control→证据要求 主链；asset 根图不受影响（仍 37 节点）。

### P2
- **P2-1 自动抽取候选进队列**：`/api/extract` 入库时为每条候选建 `review_task(targetType=candidate)`
  （id=`rt-<cand_id>`）；`review.queue()` 合并手动实体候选+自动候选+提案展示；
  `review.decide()` 新增 candidate 分支——批准时按 payload 物化实体、过 SHACL、生成版本。
  （Obligation closed 形状不接受 title 字段，已仅对非 Obligation 设 title。）
- **P2-2 生效日期**：seed 法规 issued=effective=2024-12-27，summary 注明"自公布之日起施行，
  同时废止银保监办发〔2022〕118号"，不再用 12-30。
- **P2-3 SKOS URI**：docs/02 笔误 `00/02`→`2004/02`；代码本就 `from rdflib.namespace import SKOS`，
  导出 ttl 确认前缀为 `http://www.w3.org/2004/02/skos/core#`。
- **P2-4 版本对比**：新增 `GET /api/entities/{id}/versions/{v1}/diff/{v2}`（复用 versioning.diff）；
  docs/04 收敛为"版本可列表/查看/字段级对比；一键回滚列入路线图"，不夸大。
- **P2-5 why 证据链**：`_evaluate_control` 返回逐条 evidence（每条证据要求对应 provided 记录+locator
  或 missing），`_make_check` 透传；unknown 分支明确"该义务无对应控制项"。不再 evidence:[] 却说满足。
- **P2-6 规则抽取降噪**：extractor_rule 重写，跳过 `#/>/|/-/*` 开头行与"示意/仅供演示"说明句，
  仅对含 应当/必须/不得/严禁 的正文行产 Obligation 候选；候选 19→15，注释行不再被抽成义务。
- **P2-7 裸义务提案去重**：评估建提案前先查同 obligation 是否已有 open/in_review 提案，有则复用原 id；
  连续两次首评仅产生 1 条 open 提案。

### 验证
- curl -I：styles.css=text/css、app.js=text/javascript。
- graph law-jg24 depth=3=46 节点/97 边，含 Clause/Obligation/Control；asset 根图正常。
- 上传+抽取 15 候选全进队列，reviewer 批准自动候选→version=1/entity=obligation-cand-...。
- conform 的 why.evidence 含 requirement/record/status/locator；unknown 文案明确。
- 连续两次首评 open 提案恒为 1 条。
- scripts/demo_e2e.py 与 python -m app.cli demo 均退出码 0（unknown→conform、partial→compliant 不变）。
- 三负向仍被拦：坏 SHACL / llm 未复核 / 同人自审。

## v1.0.0（2026-10-02，冻结基线首版交付）

### 新增
- 全栈 MVP：FastAPI + SQLite + RDFLib + pySHACL + Pydantic v2 + 原生 H5。
- 领域本体：复用底座 8 类（law/standard/term/role/organization/control/case/scenario，只读投影），
  新增 10 类（Clause/Obligation/DataAsset/EvidenceRequirement/EvidenceRecord/
  CheckItem/Finding/Remediation/KnowledgeGapProposal/Assessment）。
- SHACL 1.0 Core：每类一个 closed NodeShape（必填/枚举/基数/类/闭合），pySHACL 双轨闸门。
- 确定性判定引擎：资产→适用义务→控制→证据比对→conform/partial/nonconform/unknown；
  mandatory 无控制自动 `unknown` + 生成 KnowledgeGapProposal；总评 worst-case。
- 自闭环：提案 accepted → 转候选 → SHACL 入库 → 再评估结论变化（unknown→conform，partial→compliant）。
- 规则/LLM 双抽取；LLM 无 key 自动降级 `degraded=true`。
- 版本化发布（不可变版本/前后快照/对比）、全量 audit_log、角色分离、AI 候选未复核拦截。
- 前端 7 视图 + 自写 SVG 力导向图谱。

### 与冻结规格的有据偏差（经组织者授权）
1. SKOS 分级词表按金规24号第十八条精确表达为：核心/重要/一般，一般下位=敏感/其他一般
   （`skos:narrower`），取代规格中"一般/重要/核心 + 个人信息敏感级"的简化写法。
   （见 docs/02，据第十八条校正。）
2. 裸义务缺口点明确落在 **O6（§19 数据安全级别动态调整审批机制）**，
   与"恰好 1 条强制义务初始无控制项"一致。
3. 法规采用**真实全称**《银行保险机构数据安全管理办法》金规〔2024〕24号
   （2024-12-27 印发、公布之日施行；gov.cn 官方 URL 已核实），
   未使用"示意性名称"分支。控制项/判定口径仍为演示性落地改写并已声明。

### 已知边界
- "裸义务检测"在判定引擎内确定性实现（与缺口反哺共用同一结果），未额外建 SPARQL-based SHACL shape。
- 单资产评估的适用义务 = 显式 `governed_by` ∪ 按分级的确定性映射表。
- 不做：多步 what-if、OWL DL 推理、Neo4j/Fuseki/Oxigraph server、GraphRAG、多人审批引擎（见 ROADMAP）。

## [2026-10-12] 控制语义对齐闭环（金规116检查 → 115 权威控制）
- 知识库补建 11 条权威控制（CT-MGMT-029/030/031/032/034/035/036、CT-SVC-034/035/036/037），另 2 条占位标题逐字对齐既有权威控制（CT-NW-017、CT-PROTO-014）；align_controls.py 13 条缺口 13/13 转正。
- SQLite 入库：ControlPlaceholder 48/48 aligned（0 pending/0 provisional），suggestsControl 边 133；检查项重导 116 checks / 470 elements / 705 steps / 243 interviews / 116 verdicts / 285 findings / 45 clauses。
- kb_publish 全量发布：canonical.ttl 三元组 20848、SHACL conforms=True、CSV/TBox 对账 0 漂移；前端预览快照 app/data/site-preview 更新。
- PG 入库（db_seed_kb）：kb_entity 1101 / kb_relation 8011 / control 115 / inspection_check 116 / check_element 470 / law_clause 57 / doc93_selfcheck_item 139。
- 验收：REST /api/controls/gaps 与 MCP dsec_control_gaps 均 total 48 / aligned 48 / gaps []；知识库 validate --strict 0 ERROR/0 WARN、9327 引用 0 断链。

## [2026-10-12] 数据库统一治理（产品化演进收编）
- 本机 PostgreSQL 统一：`wren-postgres`(15432) / `wren-postgres-b`(15433) 已停删，数据迁移至 `ekos-postgres`（pgvector/pgvector:0.8.0-pg16-bookworm，宿主 15432）；备份 `backups/pg-unify-20261012/`。
- 迁移三库（计数全等）：ekos_ds_kb（9 表：kb_entity 1113 / kb_relation 7860 / control 104 / inspection_check 129 / check_element 483 / law_clause 57 / doc93_selfcheck_item 139）、test（6 表）、retail（8 表）。
- **pgvector 0.8.0 正式启用**（EKOS 冻结选型，Q3 由"预留"转"启用"）。
- 关联更新：askoda `connection_info.json`×2 → `host.docker.internal:15432`；askoda compose 两 PG 服务段与 depends_on 注释留痕；wren-mcp/wren-mcp-b 重启后引擎连接实测正常（pg_stat_activity 可见）。
- `KB_PG_DSN` 不变（test:test@15432/ekos_ds_kb）；8420/8422/8430 回归 HTTP 200；controls API 104。
- 保留待后续：askoda-postgres(15434) / bid-postgres(15435)（凭证未知，用户拍板本轮不处理）。
