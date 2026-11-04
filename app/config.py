"""全局配置：路径、命名空间、来源权重、降级开关。"""
from __future__ import annotations
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # 项目根
APP_DATA = Path(__file__).resolve().parent / "data"
APP_DATA.mkdir(parents=True, exist_ok=True)

DB_PATH = APP_DATA / "app.db"
BASE_SNAPSHOT_TTL = APP_DATA / "base-snapshot.ttl"
EXPORT_DIR = APP_DATA

# 底座只读投影来源（绝不写回；仅一次性读 ontology.yaml + knowledge.json）
# 10_知识库工程 为独立知识工程，未随本工程迁移，此处用绝对路径（可用环境变量覆盖）
KB_ROOT = Path(os.environ.get("KB10_ROOT",
              "/Users/FYP/Documents/@西北人的成长/20-Areas/信息安全/数据安全/10_知识库工程"))
KB_ONTOLOGY_YAML = KB_ROOT / "ontology" / "ontology.yaml"
KB_KNOWLEDGE_JSON = KB_ROOT / "data" / "knowledge.json"

# 命名空间
ONTO_NS = "http://dsec.local/ontology/2026/1#"     # dsec: TBox
RESOURCE_NS = "http://dsec.local/resource/"        # dsecr: ABox
BASE_NS = "http://dsec.local/base/1.0#"            # dsecb: 底座投影

# 来源等级权重（置信度公式）
SOURCE_GRADE_WEIGHT = {"A": 0.90, "B": 0.70, "C": 0.50, "D": 0.35}
LLM_CONFIDENCE_FACTOR = 0.60     # provenance=llm 时 confidence *= 0.6
MAX_CONFIDENCE = 1.0
SINGLE_SOURCE_CAP = 0.60         # 单源 N=1 且 <0.60 只能停留 candidate

# LLM 抽取：OpenAI 兼容；无 key 自动降级为规则抽取（不报错）
LLM_BASE_URL = os.environ.get("OPENAI_BASE_URL", os.environ.get("OPENAI_API_BASE", "")).strip()
LLM_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
LLM_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()

# v1.4.0 图存储后端（memory | oxigraph | fuseki）；端点/数据集/鉴权/落盘可选
# P2 起权威=fuseki（平台命名图 <http://dsec/platform>）；memory 仅作只读降级兜底
GRAPH_STORE_BACKEND = os.environ.get("GRAPH_STORE_BACKEND", "fuseki").strip().lower() or "fuseki"
GRAPH_STORE_ENDPOINT = os.environ.get("GRAPH_STORE_ENDPOINT", "http://127.0.0.1:3030").strip().rstrip("/")
GRAPH_STORE_DATASET = os.environ.get("GRAPH_STORE_DATASET", "ds").strip() or "ds"
GRAPH_STORE_USER = os.environ.get("GRAPH_STORE_USER", "").strip()
GRAPH_STORE_PASSWORD = os.environ.get("GRAPH_STORE_PASSWORD", "").strip()
GRAPH_STORE_FILE = os.environ.get("GRAPH_STORE_FILE", "").strip()

# v1.5.0 知识源开关：json=旧 base_import(读 knowledge.json 副产品，默认，可回退)
#                    canonical=新确定性编译器(读 10 工程编辑源) 产出的更丰富底座快照
KB_READ_FROM = os.environ.get("KB_READ_FROM", "json").strip().lower() or "json"

# v1.8.0 资产层读源开关（docs/09 §4.3，与 KB_READ_FROM 同范式）：
#   json     = 现状行为：旧 SQLite 业务库优先（/api/checks/{id}），entity/search/controls 读 canonical.ttl
#   canonical= canonical 图优先（/api/checks/{id} 先回落图再回落 SQLite 旧链路）
#   db       = PostgreSQL 投影优先（kb_entity/control/inspection_check/check_element），
#              未命中或库不可达 → 自动回落 canonical 图 → 再回落 SQLite，永远不中断 200。
# 默认 json（docs/09 Q4 倾向：最稳、不破坏 8420 演示）。
DB_READ_FROM = os.environ.get("DB_READ_FROM", "json").strip().lower() or "json"

# v1.8.0 PostgreSQL 投影只读连接串（工作包 B：复用 OrbStack 既有 PG，不起新服务）。
# 实测（v1.13.1 校正）：15432 宿主 = ekos-postgres(pgvector/pgvector:0.8.0-pg16-bookworm,
#       用户/口令 test/test, PostgreSQL 16.10)；本平台独立库 = ekos_ds_kb。
#       该宿主自带 pgvector 0.8.0（`vector` 扩展已装），资产层向量表 kb_embedding / law_chunk
#       均已 100% 非空（344/344），语义向量路（db_kb.vector_search）已可用，无需再评估启用。
# 库不可达时 db_kb.health()=False，DB_READ_FROM=db 自动降级回 canonical（docs/09 §4.3）。
KB_PG_DSN = os.environ.get(
    "KB_PG_DSN", "postgresql://test:test@127.0.0.1:15432/ekos_ds_kb").strip()

# v1.8.0 REST:8420 产品化网关开关（docs/09 §4.1）：
#   off（默认）= 单机演示裸跑，/api/* 不强制 Bearer（现状兼容）；
#   on         = 产品化模式：复用 MCP 同一把 allowlist 钥匙板（config/allowlist.json），
#                /api/* 强制 Bearer + 限流 + 审计落 audit_log。不新造认证体系。
GATEWAY_AUTH_ENABLED = os.environ.get(
    "GATEWAY_AUTH_ENABLED", "off").strip().lower() in ("1", "on", "true", "yes")

# v1.5.0 权威知识层 base IRI（集中配置，换域名只改 app/kb_compiler/iris.py 一处）
CANONICAL_BASE_IRI = "https://schema.cheersai.local/ds/"

# ---- SPI 适配层（对齐 EKOS §4.5/§4.6，P2/P3/P4 最小落地）----
# 统一 Adapter 注册中心：改这里（或对应环境变量）即换图后端/LLM/权限实现，主流程零改动。
#   retriever: memory | oxigraph | fuseki  —— 图检索后端可插拔可回滚（P3/P4）
#   llm:      openai+rule                 —— 主 LLM + rule 降级链（薄壳，不引入 LiteLLM）
#   policy:   open-dev                    —— 权限占位：一律放行（将来接 SpiceDB/飞书）
#   masker:   none                        —— 脱敏网关本期不做，留占位（默认决策 D3）
# 注意：retriever 三后端仍注册进注册中心可列出/可切换；此处只决定"默认激活哪一个"。
ADAPTERS = {
    "retriever": os.environ.get("ADAPTER_RETRIEVER", "memory").strip().lower() or "memory",
    "llm":       os.environ.get("ADAPTER_LLM", "openai+rule").strip() or "openai+rule",
    "policy":    os.environ.get("ADAPTER_POLICY", "open-dev").strip() or "open-dev",
    "masker":    os.environ.get("ADAPTER_MASKER", "none").strip() or "none",
}

# 演示 actor
DEMO_ACTORS = [
    ("editor", "editor", "知识编辑"),
    ("reviewer", "reviewer", "合规审核"),
    ("admin", "admin", "平台管理员"),
]
