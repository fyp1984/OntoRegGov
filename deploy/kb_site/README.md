# 知识库静态站默认挂载点（只读）。
#
# 平台把「知识工程/site」（含 data/knowledge-data.js）挂到容器 /app/kb_site，
# 作为知识阅览 / Wiki / 图谱视图的数据源。
#
# 三种用法：
#   1. 默认：宿主不放任何东西，知识视图走降级链并提示「来源不可用」——不阻塞启动；
#   2. 本地：把知识工程 site 目录内容拷到本目录（或直接在 .env 里设
#      KB10_SITE_HOST=/abs/path/to/10_知识库工程/site）；
#   3. 容器：docker compose -f deploy/docker-compose.ontoreggov.yml --profile demo up -d --build
#
# 注意：本目录内容为运行期挂载数据，不入库。
