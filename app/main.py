"""FastAPI 入口：挂静态页与 /api。合规结论只来自 services/inspection。"""
from __future__ import annotations
import json, hashlib, datetime
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from .db import db, init_db
from .ontology import ns, graph_store, graph_backend, shacl_validator, base_import
from .services import (review, proposal, audit,
                       extractor_rule, extractor_llm, confidence, gate, versioning,
                       inspection)
from .models import (EntityCreate, EntityUpdate, ExtractReq, ReviewDecision,
                     ProposalCreate, ProposalDecision, KbIngestReq)
from .services import kb_read        # v1.8.0 三态读源路由：db→canonical→SQLite 回落链
from .services import kb_source      # v1.16.0 取数适配器：实时知识库优先 + 多源降级 + 30s 缓存
from .services import run_db         # v1.16.0 运行态统一库：影子镜像 + 启动回填
from .services import ingest_review   # v1.10.0 知识入库候选审核：staging/decisions.json
from .services import p1_sixdim       # P1 六维审核链路：generate→queue→approve→merge
from .services import p1_lawqa        # P1 法规原文带引用问答（TEI+pgvector）
from . import settings_store          # v1.12.0 平台设置（LLM 配置 UI 持久化）
from .services.extractor_llm import test_connection as settings_test_llm  # noqa: E402
from . import config as _cfg         # v1.8.0 网关开关 / DB_READ_FROM 调用时读取
from .scenarios import loader as scenario_loader  # 任务线3：配置驱动可插拔场景组件层

app = FastAPI(title="数据安全工作平台")
# 全量知识契约（站点 KNOWLEDGE_BASE，约 6MB）经 gzip 后约 1MB，显著改善首屏取数。
app.add_middleware(GZipMiddleware, minimum_size=1024)
STATIC = Path(__file__).parent / "web" / "static"
# P4-4：知识库静态站（8430 site/）挂载到 /kb/，由环境变量 KB10_SITE 指定宿主机路径
import os as _os
KB_SITE = Path(_os.environ.get("KB10_SITE", "/app/kb_site"))


@app.on_event("startup")
def _startup():
    init_db()
    # v1.16.0 运行态库就绪：幂等建表 + 历史回填（静默 best-effort，绝不阻塞启动）
    try:
        if run_db.ensure_schema():
            run_db.backfill_from_sqlite()
    except Exception:  # noqa: BLE001
        pass
    # EKOS 底座连通性自检（启动时静默执行，不阻塞启动；结果可通过 /api/health 查看）
    _ekos_health = {"neo4j": None, "weknora_api": None, "checkedAt": None}
    try:
        from .ontology import neo4j_backend as nb
        _ekos_health["neo4j"] = nb.health()
    except Exception as e:
        _ekos_health["neo4j"] = {"ok": False, "error": str(e)[:200]}
    try:
        import os, urllib.request, json as _json
        token = os.environ.get("WEKNORA_API_TOKEN", "")
        base = os.environ.get("WEKNORA_API_BASE", "http://ekos-weknora:8080")
        if token:
            req = urllib.request.Request(f"{base}/api/v1/knowledge-bases",
                                         headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=3) as r:
                _ekos_health["weknora_api"] = {"ok": True, "status": r.status}
        else:
            _ekos_health["weknora_api"] = {"ok": False, "note": "WEKNORA_API_TOKEN 未配置"}
    except Exception as e:
        _ekos_health["weknora_api"] = {"ok": False, "error": str(e)[:200]}
    import datetime
    _ekos_health["checkedAt"] = datetime.datetime.now().isoformat(timespec="seconds")
    # 存到 app.state 供 /api/health 读取
    app.state.ekos_health = _ekos_health


def _err(code, message, status=400, details=None):
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message, "details": details or {}}})


# ---------------- v1.8.0 产品化网关（docs/09 §4.1：认证/限流/审计复用 MCP 同一把 allowlist） ----------------
# 大白话：MCP:8422 门口已有的"钥匙板 + 每分钟次数限制 + 监控录像"，给 REST:8420 同一套用——
# 不新造认证体系。GATEWAY_AUTH_ENABLED=off（默认）时 /api/* 裸跑兼容单机演示；
# 开关一开：/api/* 强制 Bearer（config/allowlist.json，与 MCP 共用）+ rpm 限流 + 审计落 audit_log。
from fastapi import Request  # noqa: E402
from .mcp_server.auth import (Allowlist, RateLimiter, Unauthorized, RateLimited,  # noqa: E402
                               validate_key, _extract_bearer)

_gw_allowlist = Allowlist()
_gw_limiter = RateLimiter()


@app.middleware("http")
async def gateway_guard(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or path == "/api/health":
        return await call_next(request)
    if not _cfg.GATEWAY_AUTH_ENABLED:
        return await call_next(request)
    try:
        entry = validate_key(_gw_allowlist, _gw_limiter, _extract_bearer(request))
    except Unauthorized:
        return JSONResponse(
            {"error": "unauthorized", "message": "missing or invalid API key"},
            status_code=401, headers={"WWW-Authenticate": "Bearer"})
    except RateLimited:
        return JSONResponse(
            {"error": "rate_limited", "message": "too many requests, slow down"},
            status_code=429)
    audit.log(entry.get("name") or entry.get("key", "?"),
              f"api.{request.method.lower()}", path,
              {"query": dict(request.query_params)})
    return await call_next(request)


# ---------------- 基础 ----------------
@app.get("/api/health")
def health():
    h = {"status": "ok", "service": "dsec-mvp", "version": "1.17.0",
         "baseSnapshot": graph_store.BASE_SNAPSHOT_TTL.exists()}
    if hasattr(app.state, "ekos_health"):
        h["ekos"] = app.state.ekos_health
    return h


# ---------------- LLM 配置（v1.12.0：前端可配置，UI 优先、env 兜底，免重启生效） ----------------
@app.get("/api/settings/llm")
def get_llm_settings():
    cfg = settings_store.get_runtime_llm()
    return {"base_url": cfg["base_url"], "model": cfg["model"],
            "api_key_set": cfg["api_key_set"], "api_key_masked": cfg["api_key_masked"],
            "source": cfg["source"], "ui_configured": cfg["ui_configured"]}


@app.put("/api/settings/llm")
def put_llm_settings(payload: dict):
    """保存 LLM 配置。base_url/model 可更新或清空；api_key 非空才更新（不回显明文）。"""
    cfg = settings_store.save_llm(payload)
    return {"ok": True, "base_url": cfg["base_url"], "model": cfg["model"],
            "api_key_set": cfg["api_key_set"], "api_key_masked": cfg["api_key_masked"],
            "source": cfg["source"], "ui_configured": cfg["ui_configured"]}


@app.post("/api/settings/llm/test")
def test_llm_settings(payload: dict):
    """连通性测试：用（可覆盖的）当前配置打一次最小请求，不落库。"""
    result = settings_test_llm(payload)
    return {"ok": result.get("ok"), "detail": result.get("detail")}


# ---------------- 应用设置：可引用的知识库（多选） ----------------
# 大白话：默认只引用部署环境变量指定的知识库；在这里勾选后，
# 知识库页面与检索只引用所选集合（改完即刷新取数缓存，下一次即生效）。
# 取数纪律（PRD §7.3 契约稳定性）：知识库平台不可达时**不返回空清单**，
# 也不只回单个库，而是降级展示"完整演示目录"并显式标注 source=degraded ——
# 清单可完整呈现、可勾选，页面永不空态、状态可辨。
def _degraded_kb_catalog(effective: list) -> list:
    """平台不可达时的降级清单：完整演示目录 + 标出部署当前生效库。

    必要兜底：若部署配置里的库不在演示目录中，补到最前，保证"当前生效库"一定可选。
    """
    from .demo.seed import DEMO_KB_CATALOG
    eff = [str(x) for x in (effective or [])]
    items = [{"id": kb_id, "name": name, "docCount": doc_count,
              "degraded": True, "effective": kb_id in eff}
             for kb_id, name, doc_count in DEMO_KB_CATALOG]
    known = {it["id"] for it in items}
    for kb_id in eff:
        if kb_id not in known:
            items.insert(0, {"id": kb_id, "name": "数据安全统一知识库（部署默认）",
                             "docCount": None, "degraded": True, "effective": True})
    return items


@app.get("/api/settings/kb")
def get_kb_settings():
    from .services import weknora_retriever as _wr
    effective = _wr.effective_kb_ids()
    detail = ""
    try:
        available = _wr.list_knowledge_bases()
        source = "weknora"
    except Exception as e:  # noqa: BLE001 — 知识库平台不可达：降级展示完整演示目录（不阻断设置页）
        detail = str(e)[:200]
        available = _degraded_kb_catalog(effective)
        source = "degraded"
    return {"available": available,
            "source": source,
            "sourceDetail": detail,
            "selected": settings_store.get_reference_kbs(),
            "effective": effective}


@app.put("/api/settings/kb")
def put_kb_settings(payload: dict):
    """保存可引用知识库集合（仅接受尚未删除的知识库 ID）；保存后主动失效取数缓存。"""
    ids = payload.get("ids")
    if not isinstance(ids, list):
        return _err("bad_request", "ids 需为数组", 400)
    from .services import weknora_retriever as _wr
    try:
        valid = {kb["id"] for kb in _wr.list_knowledge_bases()}
        ids = [str(i) for i in ids if str(i) in valid]
    except Exception:  # noqa: BLE001 — 校验不可用时按原样保存
        ids = [str(i) for i in ids]
    selected = settings_store.save_reference_kbs(ids)
    kb_source.invalidate_env("")
    audit.log("ui-user", "settings.kb", "reference_kbs", {"count": len(selected)})
    return {"ok": True, "selected": selected, "effective": _wr.effective_kb_ids()}


@app.get("/api/ontology/classes")
def classes():
    tree = []
    tree.append({"name": "Law", "label": ns.CLASS_LABELS["Law"], "group": "新增"})
    for c in ns.NEW_CLASSES:
        tree.append({"name": c, "label": ns.CLASS_LABELS.get(c, c), "group": "新增"})
    for c in ns.BASE_PROJECTED_CLASSES:
        tree.append({"name": c, "label": ns.CLASS_LABELS.get(c, c), "group": "底座投影"})
    return {"classes": tree}


@app.get("/api/vocab")
def vocab(scheme: str = ""):
    out = {"dataClassification": [{"slug": s, "label": l, "broader": p}
                                   for s, l, p in ns.DATA_CLASSIFICATION],
           "force": ns.FORCE, "controlKind": ns.CONTROL_KIND, "priority": ns.PRIORITY,
           "evidenceKind": ns.EVIDENCE_KIND, "recordStatus": ns.RECORD_STATUS}
    # 自动补全：底座术语/法规/控制
    with db() as conn:
        laws = [dict(r) for r in conn.execute(
            "SELECT id,dataJSON FROM entities WHERE type='Law' AND status='published'")]
        obs = [dict(r) for r in conn.execute(
            "SELECT id,dataJSON FROM entities WHERE type='Obligation' AND status='published'")]
        ctrls = [dict(r) for r in conn.execute(
            "SELECT id,dataJSON FROM entities WHERE type='Control' AND status='published'")]
    out["laws"] = [{"id": r["id"], "label": json.loads(r["dataJSON"]).get("title")} for r in laws]
    out["obligations"] = [{"id": r["id"], "label": json.loads(r["dataJSON"]).get("code")} for r in obs]
    out["controls"] = [{"id": r["id"], "label": json.loads(r["dataJSON"]).get("title")} for r in ctrls]
    return out


# ---------------- 实体 ----------------
@app.get("/api/entities")
def list_entities(type: str = "", q: str = "", status: str = "published"):
    sql = "SELECT id,type,status,dataJSON,currentVersion,updatedAt,updatedBy FROM entities WHERE status LIKE ?"
    args = [f"%{status}%"]
    if type:
        sql += " AND type=?"; args.append(type)
    with db() as conn:
        rows = conn.execute(sql + " ORDER BY type,id", args).fetchall()
    out = []
    for r in rows:
        d = json.loads(r["dataJSON"])
        if q and q not in json.dumps(d, ensure_ascii=False):
            continue
        out.append({"id": r["id"], "type": r["type"], "status": r["status"],
                    "version": r["currentVersion"],
                    "label": d.get("title") or d.get("name") or d.get("code") or r["id"],
                    "updatedAt": r["updatedAt"], "updatedBy": r["updatedBy"]})
    return {"entities": out}


@app.post("/api/entities", status_code=201)
def create_entity(body: EntityCreate):
    try:
        res = review.create_entity(body.type, body.id, body.data, body.relations,
                                   body.actor, source="manual-form")
        return res
    except gate.GateError as e:
        return _err(e.code, e.message, 400, e.details)


@app.get("/api/entities/{eid}")
def get_entity(eid: str):
    with db() as conn:
        r = conn.execute("SELECT * FROM entities WHERE id=?", (eid,)).fetchone()
    if not r:
        return _err("not_found", "实体不存在", 404)
    d = dict(r); d["data"] = json.loads(d["dataJSON"]); d["relations"] = json.loads(d["relationsJSON"])
    del d["dataJSON"]; del d["relationsJSON"]
    return d


@app.put("/api/entities/{eid}")
def update_entity(eid: str, body: EntityUpdate):
    with db() as conn:
        r = conn.execute("SELECT * FROM entities WHERE id=?", (eid,)).fetchone()
        if not r:
            return _err("not_found", "实体不存在", 404)
        data = json.loads(r["dataJSON"])
        if body.data:
            data.update(body.data)
        relations = json.loads(r["relationsJSON"])
        if body.relations is not None:
            relations = body.relations
        # SHACL 闸门（对已发布实体编辑后重新校验）
        vt = shacl_validator.validate_entity(r["type"], eid, data, relations)
        if not vt["conforms"]:
            return _err("shacl_rejected", "编辑后未通过 SHACL", 400, {"messages": vt["messages"]})
        conn.execute("UPDATE entities SET dataJSON=?,relationsJSON=?,updatedBy=? WHERE id=?",
                     (json.dumps(data, ensure_ascii=False), json.dumps(relations, ensure_ascii=False),
                      body.actor, eid))
    ver = versioning.snapshot(eid, body.actor, body.changeNote or "编辑更新", source="manual")
    audit.log(body.actor, "entity.update", eid, {"version": ver})
    return {"id": eid, "version": ver}


@app.get("/api/entities/{eid}/versions")
def entity_versions(eid: str):
    return {"versions": versioning.versions_of(eid)}


@app.get("/api/entities/{eid}/versions/{v1}/diff/{v2}")
def entity_version_diff(eid: str, v1: int, v2: int):
    return versioning.diff(eid, v1, v2)


# ---------------- 文档上传 + 抽取 ----------------
@app.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...), sourceGrade: str = "B"):
    raw = await file.read()
    name = file.filename
    text = ""
    if name.lower().endswith(".pdf"):
        try:
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(raw))
            text = "\n".join((pg.extract_text() or "") for pg in reader.pages)
        except Exception as e:
            return _err("pdf_parse", "PDF 解析失败", 400, {"err": str(e)})
    else:
        text = raw.decode("utf-8", errors="replace")
    doc_id = "doc-" + hashlib.sha256(raw).hexdigest()[:10]
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO documents(id,sha256,name,sourceGrade,text,uploadedAt) VALUES(?,?,?,?,?,?)",
                     (doc_id, hashlib.sha256(raw).hexdigest(), name, sourceGrade, text, ts))
    audit.log("editor", "document.upload", doc_id, {"name": name})
    return {"documentId": doc_id, "name": name, "chars": len(text)}


@app.post("/api/extract")
def extract(body: ExtractReq):
    with db() as conn:
        r = conn.execute("SELECT text,id FROM documents WHERE id=?", (body.documentId,)).fetchone()
    if not r:
        return _err("not_found", "文档不存在", 404)
    if body.mode == "llm":
        result = extractor_llm.extract(r["text"], r["id"])
    else:
        result = {"candidates": extractor_rule.extract(r["text"], r["id"]), "degraded": False}
    # 落库候选 + 自动补 review_task（人在回路）
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    out_cands = []
    with db() as conn:
        for c in result["candidates"]:
            conn.execute(
                "INSERT OR REPLACE INTO candidates(id,documentId,kind,label,mappedClass,confidence,provenance,span,payloadJSON,status,createdBy,createdAt) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (c["id"], r["id"], c["kind"], c["label"], c["mappedClass"], c["confidence"],
                 c["provenance"], c["span"], json.dumps(c.get("payload", {}), ensure_ascii=False),
                 "new", "editor", ts))
            # 自动候选进入待审核队列（targetType=candidate），专家可在队列批准/修改/拒绝/合并
            conn.execute(
                "INSERT OR IGNORE INTO review_tasks(id,targetType,targetId,status,note,reviewer,createdBy,createdAt) VALUES(?,?,?,?,?,?,?,?)",
                (f"rt-{c['id']}", "candidate", c["id"], "pending_review",
                 "", None, "editor", ts))
            out_cands.append({**c, "badge": confidence.badge(c["confidence"])})
    audit.log("editor", "extract.run", r["id"], {"mode": body.mode, "n": len(out_cands)})
    return {"documentId": r["id"], "degraded": result.get("degraded", False),
            "reason": result.get("reason"), "candidates": out_cands}


# ---------------- 审核 ----------------
@app.get("/api/review/queue")
def review_queue():
    return {"queue": review.queue()}


@app.post("/api/review/{task_id}/decision")
def review_decision(task_id: str, body: ReviewDecision):
    try:
        return review.decide(task_id, body.actor, body.action, body.note, body.edits)
    except gate.GateError as e:
        return _err(e.code, e.message, 403, e.details)
    except ValueError as e:
        return _err("bad_request", str(e), 400)


# ---------------- 知识入库审核（v1.10.0：ingest 候选，复用平台审核范式）----------------
# 与平台"待审核队列"同范式：候选来自 10 工程 ingest/staging（manifest+草稿），
# 批准/拒绝写 decisions.json（与 CLI approve/reject 同文件），merge --apply 才入库。
@app.get("/api/ingest/review/batches")
def ingest_review_batches():
    return {"batches": ingest_review.batches()}


@app.get("/api/ingest/review")
def ingest_review_queue(batch: str = ""):
    return ingest_review.queue(batch or None)


@app.post("/api/ingest/review/{eid}/decision")
def ingest_review_decision(eid: str, batch: str = "", body: dict = None):
    body = body or {}
    try:
        return ingest_review.decide(batch or None, eid, body.get("action", ""))
    except ValueError as e:
        return _err("bad_request", str(e), 400)


# ---------------- P1 六维审核链路（generate→queue→approve→merge，仅 approved 落库）----------------
@app.post("/api/p1/sixdim/generate")
def p1_sixdim_generate(doc_key: str = Query(...), reviewer: str = "p1-bot"):
    if doc_key not in ("jg93", "pboc3", "jf8"):
        return _err("bad_request", "doc_key 仅支持 jg93/pboc3/jf8", 400)
    try:
        return p1_sixdim.generate_drafts(doc_key, reviewer)
    except Exception as e:  # noqa: BLE001
        return _err("p1_generate_failed", str(e), 500)


@app.get("/api/p1/sixdim/queue")
def p1_sixdim_queue(doc_key: str = "", status: str = ""):
    return p1_sixdim.queue(doc_key or None, status or None)


@app.post("/api/p1/sixdim/approve/{draft_id}")
def p1_sixdim_approve(draft_id: str, body: dict = None):
    body = body or {}
    return p1_sixdim.approve(draft_id, body.get("reviewer", "admin"), body.get("note", ""))


@app.post("/api/p1/sixdim/approve_all")
def p1_sixdim_approve_all(doc_key: str = "", reviewer: str = "admin"):
    return p1_sixdim.approve_all(doc_key or None, reviewer)


@app.post("/api/p1/sixdim/merge")
def p1_sixdim_merge():
    try:
        return p1_sixdim.merge_approved()
    except Exception as e:  # noqa: BLE001
        return _err("p1_merge_failed", str(e), 500)


@app.get("/api/p1/sixdim/stats")
def p1_sixdim_stats():
    return p1_sixdim.stats()


@app.get("/api/p1/sixdim/{check_code}")
def p1_sixdim_detail(check_code: str):
    return p1_sixdim.get_check_sixdim(check_code)


# ---------------- P1 法规原文带引用问答（TEI+pgvector，新表 law_chunk）----------------
@app.post("/api/p1/law/index")
def p1_law_index():
    try:
        return p1_lawqa.index()
    except Exception as e:  # noqa: BLE001
        return _err("law_index_failed", str(e), 500)


@app.get("/api/p1/law/qa")
def p1_law_qa(q: str = "", limit: int = 5):
    if not q.strip():
        return _err("bad_request", "q 必填", 400)
    try:
        return p1_lawqa.search(q, limit=limit)
    except Exception as e:  # noqa: BLE001
        return _err("law_qa_failed", str(e), 500)


@app.get("/api/p1/law/stats")
def p1_law_stats():
    return p1_lawqa.stats()


# ---------------- 图谱 ----------------
@app.get("/api/graph")
def graph(root: str = "", depth: int = 2):
    g = graph_store.materialize()
    nodes, edges = set(), []
    start = root or "law-jg24"
    seen = set()

    def _is_resource(uri):
        return str(uri).startswith(str(ns.DSECR))

    def walk(uri, d):
        # 双向 BFS：关系按反向边存（clause clauseOf Law），需沿 s→o 与 o→s 同时展开，
        # 才能从 Law 出发走通 Law→Clause→Obligation→Control 主链；边保留原方向。
        if d > depth or uri in seen:
            return
        seen.add(uri)
        nodes.add(str(uri))
        # 正向出边 s→o
        for _, _, o in g.triples((uri, None, None)):
            if _is_resource(o):
                edges.append({"source": str(uri), "target": str(o)})
                nodes.add(str(o))
                walk(o, d + 1)
        # 反向入边 o→s（主语在另一端）
        for s, _, _ in g.triples((None, None, uri)):
            if _is_resource(s):
                edges.append({"source": str(s), "target": str(uri)})
                nodes.add(str(s))
                walk(s, d + 1)

    start_uri = None
    for cand in [ns.DSECR[f"law/{start}"], ns.DSECR[f"dataasset/{start}"],
                 ns.DSECR[f"inspectioncheck/{start}"]]:
        if (cand, None, None) in g:
            start_uri = cand; break
    if start_uri:
        walk(start_uri, 0)
    else:
        for s, p, o in g:
            if _is_resource(s) and _is_resource(o):
                edges.append({"source": str(s), "target": str(o)})
                nodes.add(str(s)); nodes.add(str(o))
    return {"nodes": [{"id": n} for n in nodes], "edges": edges}


# ---------------- 提案 ----------------
@app.post("/api/proposals")
def create_proposal(body: ProposalCreate):
    p = proposal.create(body.reason, body.targetKind, body.raisedFrom, body.payload, body.actor)
    return p


@app.get("/api/proposals")
def list_proposals():
    return {"proposals": proposal.list_proposals()}


@app.post("/api/proposals/{pid}/decision")
def proposal_decision(pid: str, body: ProposalDecision):
    try:
        return proposal.decide(pid, body.actor, body.decision, body.note)
    except gate.GateError as e:
        return _err(e.code, e.message, 403, e.details)


# ---------------- 监管检查知识库（v1.1.0）----------------
@app.get("/api/checks")
def list_checks(domain: str = "", priority: str = "", chapter: str = "", keyword: str = "", doc: str = ""):
    sql = "SELECT id,dataJSON FROM entities WHERE type='InspectionCheck' AND status='published'"
    args = []
    with db() as conn:
        rows = conn.execute(sql + " ORDER BY id", args).fetchall()
    out = []
    for r in rows:
        d = json.loads(r["dataJSON"])
        if domain and d.get("domain") != domain:
            continue
        if priority and d.get("priority") != priority:
            continue
        if chapter and d.get("chapter") != chapter:
            continue
        if doc and doc not in (d.get("docKey") or "") and doc not in (d.get("docNo") or ""):
            continue
        if keyword and keyword not in json.dumps(d, ensure_ascii=False):
            continue
        out.append({"id": r["id"], "checkCode": d.get("checkCode"), "title": d.get("title"),
                    "domain": d.get("domain"), "domainLabel": d.get("domainLabel"),
                    "priority": d.get("priority"), "regulation": d.get("regulation"),
                    "articleNo": d.get("articleNo"), "chapter": d.get("chapter"),
                    "docKey": d.get("docKey"), "docNo": d.get("docNo"), "docTitle": d.get("docTitle")})
    # 计数
    total_all = len(rows)
    by_domain = {}
    by_priority = {}
    by_doc = {}
    for r in rows:
        d = json.loads(r["dataJSON"])
        by_domain[d.get("domain")] = by_domain.get(d.get("domain"), 0) + 1
        by_priority[d.get("priority")] = by_priority.get(d.get("priority"), 0) + 1
        dk = d.get("docKey") or "jg24"
        by_doc[dk] = by_doc.get(dk, 0) + 1
    return {"total": total_all, "filtered": len(out),
            "byDomain": by_domain, "byPriority": by_priority, "byDoc": by_doc,
            "checks": out}


@app.get("/api/checks/{check_code}")
def get_check(check_code: str):
    # v1.16.0（QA4·P0）：委托统一取数适配器 kb_source.fetch_check —— 内部按
    # "结构化底座（db 规范化子表 + check_six_dim 兜底）→ 运行台账补齐 → 知识库实时覆盖"
    # 合并六维，修复 jf8/jg93/pboc3 此前六维 0% 空白（这些文号只落权威表 check_six_dim；
    # 旧实现仅读运行台账 SQLite，故详情页大面积 undefined/空白）。
    # 适配器内部任何来源不可达都只降级不抛错，故本端点永不 5xx（QA2）。
    env = kb_source.fetch_check(check_code)
    content = (env or {}).get("content")
    if content:
        return content
    return _err("not_found", "检查项不存在", 404)


@app.get("/api/controls/gaps")
def control_gaps():
    """控制需求缺口浏览：返回 status!=aligned 的 ControlPlaceholder（待 10 工程 v1.6 补建反馈）。"""
    with db() as conn:
        rows = conn.execute("SELECT dataJSON FROM entities WHERE type='ControlPlaceholder' "
                            "AND status='published'").fetchall()
        all_p = []
        for row in rows:
            p = json.loads(row["dataJSON"])
            all_p.append({"hint": p.get("controlCodeHint"), "name": p.get("controlName"),
                          "layer": p.get("suggestedLayer"), "type": p.get("controlTypeHint"),
                          "status": p.get("alignmentStatus"),
                          "ctCode": p.get("ctCode"), "ctLayer": p.get("ctLayer"),
                          "sourceChecks": (p.get("sourceCheckCodes") or "").split(","),
                          "articleRefs": (p.get("articleRefs") or "").split(","),
                          "rationale": p.get("rationale"),
                          "baseControlTitle": p.get("baseControlTitle")})
        gaps = [x for x in all_p if x["status"] != "aligned"]
        return {"total": len(all_p),
                "aligned": sum(1 for x in all_p if x["status"] == "aligned"),
                "pending": sum(1 for x in gaps if x["status"] == "pending_alignment"),
                "provisional": sum(1 for x in gaps if x["status"] == "provisional"),
                "gaps": gaps}


# ---------------- 监管检查运行（纵切）----------------
@app.post("/api/inspection/runs")
def inspection_run(body: dict):
    return inspection.create_run(body.get("inspectedTarget", "某银行"),
                                 body.get("inspector", "合规部"), body.get("actor", "reviewer"))


@app.post("/api/inspection/runs/{run_id}/results")
def inspection_result(run_id: str, body: dict):
    try:
        return inspection.record_result(run_id, body["checkCode"],
                                        body.get("elements", []), body.get("metrics", []),
                                        body.get("actor", "reviewer"))
    except ValueError as e:
        return _err("bad_request", str(e), 400)


@app.get("/api/inspection/runs/{run_id}")
def inspection_run_get(run_id: str):
    r = inspection.get_run(run_id)
    if not r:
        return _err("not_found", "运行不存在", 404)
    return r


@app.get("/api/inspection/runs/{run_id}/compare/{other}")
def inspection_compare(run_id: str, other: str):
    c = inspection.compare(run_id, other)
    if not c:
        return _err("not_found", "运行不存在", 404)
    return c


@app.get("/api/inspection/runs/{run_id}/report")
def inspection_report(run_id: str):
    """合规自查报告（PRD M4.5/O5）：逐条佐证完整性 / 内容完备性 / 合规符合性 + 差距 + 整改建议 + 专家意见。"""
    rep = inspection.generate_report(run_id)
    if not rep:
        return _err("not_found", "运行不存在", 404)
    return rep


@app.get("/api/inspection/runs/{run_id}/report.md")
def inspection_report_md(run_id: str):
    """合规自查报告 Markdown 导出（供下载 / 留痕）。"""
    rep = inspection.generate_report(run_id)
    if not rep:
        return _err("not_found", "运行不存在", 404)
    return PlainTextResponse(inspection.report_markdown(rep), media_type="text/markdown; charset=utf-8")


# ---------------- 图存储后端（v1.4.0：标准 SPARQL 层）----------------
@app.get("/api/graph/backend")
def graph_backend_info():
    return {"backend": graph_backend.current_backend(), "stats": graph_backend.stats()}


@app.post("/api/graph/sync")
def graph_backend_sync():
    return graph_backend.sync()


@app.post("/api/graph/sparql")
def graph_backend_query(body: dict):
    """标准 SPARQL 查询代理：对所选后端执行只读查询（SELECT/ASK），返回 JSON 行。

    v1.15.0 命名空间 ACL：图存储全只读，非读查询（SPARQL Update）一律 400 拒绝。
    """
    sparql = (body or {}).get("query", "").strip()
    if not sparql:
        return _err("bad_request", "query 必填")
    try:
        if sparql.lstrip().upper().startswith("ASK"):
            return {"ask": graph_backend.ask(sparql)}
        return {"rows": graph_backend.query(sparql)}
    except ValueError as e:
        return _err("readonly_violation", str(e), 400)


# ---------------- 导出 ----------------
@app.get("/api/export/turtle")
def export_turtle():
    return PlainTextResponse(graph_store.export_turtle(), media_type="text/turtle")


@app.get("/api/export/shapes")
def export_shapes():
    return PlainTextResponse(graph_store.export_shapes(), media_type="text/turtle")


# ---------------- 接入层最小 API（v1.6.0：从 canonical 本体知识库读；v1.8.0：三态读源）----------------
# 证明"前端 HTML ← 后端资产层知识库"链路；进程内读，不绑写库。
# DB_READ_FROM=db 时先走 PostgreSQL 投影，未命中/库不可达自动回落 canonical.ttl（docs/09 §4.3）。
@app.get("/api/entity/{eid}")
def api_entity(eid: str):
    ent = kb_read.get_entity(eid)
    if not ent:
        return _err("not_found", "本体库无此实体", 404)
    return ent


@app.get("/api/search")
def api_search(q: str = ""):
    return kb_read.search(q)


@app.get("/api/controls")
def api_controls():
    return kb_read.list_controls()


# ---------------- 场景组件（任务线3：配置驱动、可插拔）----------------
# 注册表清单 / 单组件配置 / 函数调用；业务逻辑在 app/scenarios/functions/ 适配器，
# 新增场景只改 registry.json（sc02 即纯配置注册实证，零新增 Python 文件）。
@app.get("/api/scenarios")
def scenarios_list():
    try:
        return {"components": scenario_loader.list_components()}
    except scenario_loader.RegistryError as e:
        return _err(e.code, e.message, 500, e.details)


@app.get("/api/scenarios/{sid}")
def scenario_detail(sid: str):
    try:
        return scenario_loader.get_component(sid)
    except scenario_loader.RegistryError as e:
        return _err(e.code, e.message, 404 if e.code == "component_not_found" else 500, e.details)


@app.post("/api/scenarios/{sid}/functions/{fid}")
def scenario_function(sid: str, fid: str, body: dict = None):
    try:
        return scenario_loader.call_function(sid, fid, body or {})
    except scenario_loader.RegistryError as e:
        status = 404 if e.code in ("component_not_found", "function_not_found") else 400
        return _err(e.code, e.message, status, e.details)


# ---------------- 统一知识取数接口（v1.16.0：kb_source 适配器，实时知识库优先 + 多源降级）----------------
# 与 /api/checks 等既有路由并存；本组为"契约化实时接口"，统一返回信封
# {content, source, fetchedAt, version?}，供前端实时取数与 MCP 工具复用。
@app.get("/api/kb/sources")
def kb_sources():
    """各来源（知识库平台/正本图/结构化投影/运行台账）可达性总览（统一信封）。"""
    return kb_source.sources_env()


@app.get("/api/kb/checks")
def kb_checks(doc: str = "", domain: str = "", priority: str = "", keyword: str = ""):
    return kb_source.fetch_checks(doc, domain, priority, keyword)


@app.get("/api/kb/checks/{check_code}")
def kb_check(check_code: str):
    env = kb_source.fetch_check(check_code)
    if not env or env.get("content") is None:
        return _err("not_found", "检查项不存在", 404)
    return env


@app.get("/api/kb/wiki")
def kb_wiki_index(limit: int = 500):
    return kb_source.fetch_wiki_index(limit)


# v1.17.0（M11.1/M11.2）：Wiki 目录树（按业务分类聚合）。
# 必须注册在 /api/kb/wiki/{page_id} 之前，否则 "tree" 会被 {page_id} 吞掉。
@app.get("/api/kb/wiki/tree")
def kb_wiki_tree(limit: int = 500):
    return kb_source.fetch_wiki_tree(limit)


@app.get("/api/kb/wiki/{page_id}")
def kb_wiki_page(page_id: str):
    env = kb_source.fetch_wiki(page_id)
    if not env or env.get("content") is None:
        return _err("not_found", "知识页面不存在", 404)
    return env


@app.get("/api/kb/search")
def kb_search(q: str = "", limit: int = 20):
    return kb_source.fetch_search(q, limit)


# v1.18.0（M11.3）：全量知识契约（站点 KNOWLEDGE_BASE 形状）。
# 运行期从知识库平台原始 Markdown 装配，全量载荷按字节缓存 + ETag（304 命中免重传）。
def _kb_response(payload: tuple[str, bytes], request: Request) -> Response:
    """知识取数统一响应：带 ETag，命中 If-None-Match 直接 304（不重传）。"""
    etag, body = payload
    if etag and request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    headers = {"Cache-Control": "no-cache"}
    if etag:
        headers["ETag"] = etag
    return Response(content=body, media_type="application/json", headers=headers)


@app.get("/api/kb/knowledge")
def kb_knowledge(request: Request):
    return _kb_response(kb_source.knowledge_payload(), request)


# v1.19.0（M11.5）按主题拆分子接口 —— 缩短查询与加载时间（载荷随知识库增长而变重）。
# 全部由同一份装配结果派生，各自独立 ETag；全量 /api/kb/knowledge 保留供 MCP/兜底。
@app.get("/api/kb/knowledge/index")
def kb_knowledge_index(request: Request):
    """轻量索引：列表/筛选/卡片所需字段（无正文、无边），首屏只取这一份。"""
    return _kb_response(kb_source.knowledge_index_payload(), request)


@app.get("/api/kb/knowledge/graph")
def kb_knowledge_graph(request: Request, source: str = "site"):
    """知识图谱主题：nodes + edges（仅图谱视图按需加载）。

    source 切换数据源（v1.20.0）：
      site（默认）本站知识库装配图 / native 底层 WeKnora 抽取图 / ontology 平台本体图。
    Neo4j 来源不可达时自动回落 site，响应信封 source 字段标注实际来源。
    """
    return _kb_response(kb_source.knowledge_graph_payload(source), request)


# 必须注册在 /api/kb/knowledge/index、/graph 等字面量路径之后无冲突；此处为路径参数。
@app.get("/api/kb/knowledge/entity/{entity_id}")
def kb_knowledge_entity(entity_id: str, request: Request):
    """单实体详情：正文/来源/出链 + 入链（点开某条目时才取）。"""
    payload = kb_source.knowledge_entity(entity_id)
    if not payload[0]:
        return _err("not_found", "知识条目不存在", 404)
    return _kb_response(payload, request)


@app.get("/api/kb/knowledge/search")
def kb_knowledge_search(q: str = "", limit: int = 12):
    """服务端全字段检索（含正文），替代前端首屏建全文索引。"""
    return Response(content=kb_source.knowledge_search(q, limit),
                    media_type="application/json",
                    headers={"Cache-Control": "no-cache"})


# v1.17.0（M11.4）：知识加工——投递文档/正文到知识库平台官方 API（仅 /admin 入口使用）。
# 平台不直写知识库库表：处理态由知识库平台承载，本接口只做投递 + 回执。
@app.post("/api/kb/ingest")
def kb_ingest(req: KbIngestReq):
    env = kb_source.submit_ingest(req.title, req.content)
    c = env.get("content") or {}
    if not c.get("ok"):
        return _err("ingest_failed", c.get("detail") or "知识加工投递失败", 400,
                    {"status": c.get("status")})
    try:
        audit.log(req.actor, "kb.ingest", c.get("knowledgeId") or req.title,
                  {"title": req.title, "len": len(req.content)})
    except Exception:  # noqa: BLE001 — 审计失败不阻断投递回执
        pass
    return env


@app.get("/api/kb/ingest/{knowledge_id}")
def kb_ingest_status(knowledge_id: str):
    env = kb_source.fetch_ingest_status(knowledge_id)
    if env.get("content") is None:
        return _err("not_found", "该知识条目不存在或知识库不可达", 404)
    return env


@app.post("/api/kb/cache/invalidate")
def kb_cache_invalidate(prefix: str = ""):
    """主动失效缓存（知识入库后调用，使前端下一次取数即拿最新）。"""
    return kb_source.invalidate_env(prefix)


# v1.17.0（O6）：管理入口（含知识加工）。应用层不鉴权，安全边界交给网络层（PRD §2）。
# 注册在所有 mount 之前，交由 StaticFiles 根挂载兜底前优先命中。
@app.get("/admin")
def admin_page():
    p = STATIC / "admin.html"
    if not p.exists():
        return _err("not_found", "管理入口未就绪", 404)
    return FileResponse(str(p), media_type="text/html")


# ---- 全量功能 Demo（可选模块；导入失败不影响现有功能）----
try:
    from .demo.router import router as _demo_router
    app.include_router(_demo_router)
    from .demo import seed as _demo_seed
    _demo_seed.ensure_seeded()
except Exception as _demo_err:  # noqa: BLE001
    import logging as _logging
    _logging.getLogger(__name__).warning("demo module disabled: %s", _demo_err)


# ---------------- P4-4：挂载 8430 知识库静态站到 /kb/ ----------------
# 知识库站点真源：10_知识库工程/site/（容器内通过 KB10_SITE 环境变量定位）
# 必须挂在 app.mount("/", ...) 之前，否则会被根 mount 吞掉。
if KB_SITE.exists():
    app.mount("/kb", StaticFiles(directory=str(KB_SITE), html=True), name="kb-static")

# ---------------- 静态首页（StaticFiles 按扩展名给正确 MIME；html=True 回退 index.html）----------------
# 必须挂在最后：/api 路由已全部注册在前，优先匹配。真实存在的 .css/.js 由 StaticFiles
# 以正确 Content-Type 返回，不再被吞成 text/html。
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
