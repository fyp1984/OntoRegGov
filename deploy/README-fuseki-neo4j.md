# 图存储后端接入说明（v1.4.0）

平台语义层保留**双轨**：
- **判定轨道**（不变）：进程内 RDFLib 物化 + pySHACL 闸门 + why 溯源，保证确定性。
- **存储轨道**（新增）：标准 SPARQL 图存储后端，持久化 + 外部可查询，供多进程/BI/底座工程共享。

## 后端切换（环境变量，重启生效）

| 变量 | 取值 | 说明 |
|---|---|---|
| `GRAPH_STORE_BACKEND` | `memory`（默认）/ `oxigraph` / `fuseki` | 存储轨道后端 |
| `GRAPH_STORE_ENDPOINT` | `http://127.0.0.1:3030`（默认） | Fuseki 基址（本地容器或远程均可） |
| `GRAPH_STORE_DATASET` | `ds`（默认） | Fuseki 数据集名 |
| `GRAPH_STORE_USER` / `GRAPH_STORE_PASSWORD` | 空（默认）/ `admin`/`admin` | Fuseki 更新/写入所需 Basic 鉴权 |
| `GRAPH_STORE_FILE` | 空（默认）/ 路径 | oxigraph 落盘文件 |

## 启动 Fuseki（Docker，无需本机 Java）

```bash
docker compose -f deploy/docker-compose.fuseki.yml up -d
curl "http://127.0.0.1:3030/$/ping"        # 期望时间戳 JSON
curl "http://127.0.0.1:3030/$/datasets" -u admin:admin   # 期望包含 /ds（tdb2）
GRAPH_STORE_BACKEND=fuseki GRAPH_STORE_USER=admin GRAPH_STORE_PASSWORD=admin bash run.sh
```

> 镜像入口按 `FUSEKI_DATASET_<NAME>=<数据集名>` 创建数据集（值即数据集名，非路径）；
> 查询端点匿名开放，更新/写入端点需要 Basic 鉴权（admin/admin，生产请改）。

## 验证

```bash
# 全量镜像当前物化图到后端
curl -X POST http://127.0.0.1:8420/api/graph/sync
# 后端健康/三元组数
curl http://127.0.0.1:8420/api/graph/backend
# 标准 SPARQL 代理查询（任意后端统一入口）
curl -X POST http://127.0.0.1:8420/api/graph/sparql -H 'Content-Type: application/json' \
  -d '{"query":"PREFIX dsec:<http://dsec.local/ontology/2026/1#> SELECT (COUNT(?c) AS ?n) WHERE { ?c a dsec:ControlPlaceholder }"}'
# 或直接打 Fuseki 原生端点（外部工具/BI 直连）
curl -X POST http://127.0.0.1:3030/ds/query -H 'Content-Type: application/sparql-query' \
  --data 'SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }'
```

## 冒烟脚本

```bash
python scripts/smoke_graphstore.py            # memory + oxigraph 全断言
GRAPH_STORE_BACKEND=fuseki python scripts/smoke_graphstore.py   # Fuseki（需容器已起）
```

## Neo4j 适配器（属性图，非 SPARQL 原生）

Neo4j 以**适配器**接入存储轨道，只需在 `app/ontology/graph_backend.py` 增加一个分支，
实现与 oxigraph 相同的两个接口即可（Cypher 映射草案）：

```text
sync(ttl):
  → 用 rdflib 解析 TTL，按 (:Node {uri,type,label}) / (:Rel {kind}) 建点边；
    rdf:type → Node.type；DSECR 资源 → Node.uri；DSEC 数据属性 → Node.key
    对象属性（OBJ_KEYS）→ (:Node)-[:REL {pred:DSEC[k]}]->(:Node)
  → 先 MERGE 本体 URI 保证幂等，再删除孤儿边（增量镜像）

query(sparql):
  不支持通用 SPARQL；为受支持的查询形态提供 Cypher 等价（counts / 出边 / 入边 / 路径），
  其余经 HTTP 代理到 Fuseki 或回退 memory。业务接口请固定用平台 /api/graph/sparql。
```

选用建议：需要**标准 SPARQL 端点 + 与底座 TTL 无缝互换**选 Fuseki/oxigraph；
需要**属性图遍历/图算法（社区发现、风险传导多跳）**选 Neo4j。
