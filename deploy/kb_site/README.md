# 知识库静态站挂载点（只读）。

# 【治理后口径 2026-11-17】前端静态知识的唯一正本已迁到仓库内
# app/web/static/kb/data/knowledge-data.js（随仓库入库、可发布 GitHub）。
# compose 默认挂载源已改为 ../app/web/static/kb（相对 deploy/ 基准），
# 不再使用本目录作为默认；本目录仅作历史兼容/临时覆盖位保留。

# 平台把含 data/knowledge-data.js 的目录挂到容器 /app/kb_site，
# 作为知识阅览 / Wiki / 图谱视图的数据源；kb_source 以 KB10_SITE 定位。

# 三种用法：
#   1. 默认（推荐）：无需配置，compose 挂载 ../app/web/static/kb，
#      直接读取仓库内唯一正本；
#   2. 覆盖：在 .env 里设 KB10_SITE_HOST=/abs/path/to/任意含 data/knowledge-data.js 的目录；
#   3. 本地直跑（非容器）：run.sh 自动探测 app/web/static/kb 并导出 KB10_SITE。

# 生成：python3 scripts/kb/kb_publish.py（KB10_ROOT 指向文档树知识工程），
#       产物提升写入 app/web/static/kb/data/。

# 注意：本目录历史遗留，内容不入库；新部署不要往这里放知识文件。
