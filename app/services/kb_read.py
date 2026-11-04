"""资产层读源路由（v1.8.0，docs/09 §4.3 判定顺序的代码化）。

大白话：同一个查询（"这个实体/这个检查长什么样"）有四条供应轨道——
  db（PostgreSQL 投影，新建的复印台账）→ canonical（RDF 图，账本原件）→
  json（knowledge.json 快照，含 case/law/standard 等全量编辑源实体）→ SQLite（运行台账）。
本模块按 DB_READ_FROM 开关决定"先问谁"，任何一轨没货就问下一轨，永远有饭吃。

判定顺序（docs/09 §4.3 表 + v1.10 json 兜底）：
  /api/entity/{id}   db? kb_entity → 未命中/库不可达 → canonical_kb.get_entity
                     → json 快照兜底（case/law/standard 等非编译实体）→ 404
  /api/search        db 关键词 + canonical + json 快照三源合并（v1.15.2 起不提前返回）
                     → 叠加 P0 三路融合（向量/图谱/RAG/WeKnora 语义）路由标注
  /api/controls      db? control JOIN kb_entity → 未命中/库不可达 → canonical_kb.list_controls
  /api/checks/{id}  db? inspection_check+check_element → 未命中(如 93-x.y) → canonical_kb.get_check
                     → SQLite 旧链路（由 main.py /api/checks/{code} 原有逻辑承担）

DB_READ_FROM=json：行为与 v1.7 完全一致（不碰现有回落语义）。
DB_READ_FROM=canonical：检查详情"先图后 SQLite"；entity/search/controls 本就读图，等价。
DB_READ_FROM=db：上述 db 优先链；库 health()=False 时自动降级回 canonical。
json 兜底说明：canonical 只编译 term/control/solution/guide/topic（MVP 范围），
case/law/standard/organization 等实体在 knowledge.json 快照中全量存在；
审核合并（ingest merge）后的新实体经 build 进入快照，即被此处兜底检索覆盖。
"""
from __future__ import annotations

import json

from .. import config
from . import canonical_kb, db_kb


def _db_on() -> bool:
    """DB_READ_FROM=db 且 PG 投影健康，才允许走库分支。"""
    return config.DB_READ_FROM == "db" and db_kb.health()


def _json_entities() -> list[dict]:
    """读 knowledge.json 快照实体（build 派生产物，含全量类型）。"""
    try:
        d = json.loads(config.KB_KNOWLEDGE_JSON.read_text(encoding="utf-8"))
        return d.get("entities", [])
    except Exception:
        return []


def _json_fallback_entity(slug: str) -> dict | None:
    for e in _json_entities():
        if e.get("id") == slug:
            rels = []
            for r in e.get("relations_out", []) or []:
                if isinstance(r, dict) and r.get("to"):
                    rels.append({"p": r.get("rel", ""), "type": "", "slug": r["to"]})
            return {
                "id": slug, "type": e.get("type", ""),
                "label": e.get("title", ""), "title": e.get("title", ""),
                "title_en": e.get("title_en", ""),
                "summary": e.get("summary", ""), "level": e.get("level", ""),
                "status": e.get("status", ""), "aliases": e.get("aliases", []),
                "tags": e.get("tags", []), "official_url": e.get("official_url", ""),
                "checkCode": "", "domain": "", "ctCode": "", "sourcePath": "",
                "md_path": e.get("md_path", ""), "relations": rels,
            }
    return None


def _json_fallback_search(q: str, limit: int) -> dict:
    q = (q or "").strip().lower()
    hits = []
    for e in _json_entities():
        blob = " ".join([
            str(e.get("id", "")), str(e.get("title", "")),
            str(e.get("title_en", "")), str(e.get("summary", "")),
            " ".join(str(a) for a in (e.get("aliases") or [])),
            " ".join(str(t) for t in (e.get("tags") or [])),
        ]).lower()
        if q and q not in blob:
            continue
        hits.append({"id": e.get("id"), "type": e.get("type", ""),
                     "label": e.get("title", ""), "checkCode": ""})
        if len(hits) >= limit:
            break
    return {"query": q, "total": len(hits), "results": hits}


def get_entity(slug: str) -> dict | None:
    if _db_on():
        r = db_kb.get_entity(slug)
        if r:
            return r
    r = canonical_kb.get_entity(slug)
    if r:
        return r
    return _json_fallback_entity(slug)


def search(q: str, limit: int = 20) -> dict:
    # 基线三源同权合并：db 关键词（库健康时）+ canonical（term/control 等编译实体）
    # + json 快照（case/law/standard 等全量），按 id 去重。v1.15.2：db 命中不再提前返回，
    # 否则会跳过下面的三路融合，使 WeKnora 语义检索仅在关键词无命中时才生效。
    baseline: list[dict] = []
    if _db_on():
        baseline = list((db_kb.search(q, limit) or {}).get("results", []) or [])
    r1 = canonical_kb.search(q, limit) or {}
    r2 = _json_fallback_search(q, limit) or {}
    seen: dict[str, dict] = {}
    for it in baseline + list(r1.get("results", [])) + list(r2.get("results", [])):
        iid = it.get("id")
        if iid and iid not in seen:
            seen[iid] = it
    # P0 三路融合（向量/图谱/RAG）+ 关键词 + WeKnora 向量：独立于 DB_READ_FROM 开关，
    # 逐路探测、任一路不可用自动跳过，只增量补充命中并与基线合并路由，不剔除基线（不回归）。
    try:
        fused = db_kb.fused_search(q, limit) or {}
        for it in fused.get("results", []):
            iid = it.get("id")
            if not iid:
                continue
            if iid in seen:
                # 实体已在 canonical+JSON 基线：合并路由来源（图谱/向量/RAG 参与标注），不剔除
                ex = seen[iid]
                ex.setdefault("routes", [ex.get("route", "keyword")])
                for r in it.get("routes", [it.get("route")]):
                    if r and r not in ex["routes"]:
                        ex["routes"].append(r)
                if any(str(r).startswith("graph") for r in it.get("routes", [it.get("route")])):
                    ex["graph"] = True
                    if "graph" not in str(ex.get("route", "")):
                        ex["route"] = f"{ex.get('route', 'keyword')}+graph"
            else:
                seen[iid] = it
    except Exception:  # noqa: BLE001 — 三路融合失败绝不影响既有双源结果
        pass
    merged = list(seen.values())[:limit]
    return {"query": q or "", "total": len(merged), "results": merged}


def list_controls() -> dict:
    if _db_on():
        r = db_kb.list_controls()
        if r.get("total"):
            return r
    return canonical_kb.list_controls()


def get_check(check_code: str) -> dict | None:
    """检查详情的图/库轨道（不含 SQLite 六维）。

    三态纪律（json 模式必须返回 None，让调用方走 SQLite 旧链路，保住 v1.7 行为）：
      json     → None（不碰图，旧链路不变）
      canonical→ canonical_kb.get_check
      db       → db_kb（健康时）→ 未命中回落 canonical_kb
    """
    mode = config.DB_READ_FROM
    if mode == "json":
        return None
    if mode == "db" and _db_on():
        r = db_kb.get_check(check_code)
        if r:
            return r
    return canonical_kb.get_check(check_code)
