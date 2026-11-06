"""kb_source 取数适配器（v1.16.0，PRD M6.1 / M6.4 / M3.3）。

大白话：这是"取数总台"。不管底层换了几套知识库（实时知识库平台 / RDF 正本 /
PostgreSQL 投影 / 运行台账），上层只管调用这里的 fetch_*，拿到的一定是同一形状的
JSON，并附带"这次数据从哪来、什么时候取的"。

统一形状（PRD §7.3）：
    {"content": <业务内容>, "source": "weknora|canonical|db|sqlite", "fetchedAt": <ISO>, "version"?: <str>}

降级链（按业务键择优，任一级不可达自动跳到下一级，永不中断）：
    weknora（实时知识库平台） → canonical（RDF 正本图） → db（PG 结构化投影） → sqlite（运行台账）

纪律：
- 每个来源独立实现、彼此隔离；任何异常都不抛给调用方，只记录并降级。
- 前端对 source 仅做展示，不做分支渲染 —— 知识库重建不触发前端改造。
- 30s TTL 缓存 + 主动失效（PRD D2）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import datetime
from pathlib import Path

from .. import config
from ..config import DB_PATH, APP_DATA
from . import canonical_kb, db_kb, kb_knowledge, weknora_graph, weknora_retriever
from ..db import db

SOURCES = ("weknora", "canonical", "db", "sqlite")

# ---------------- 统一形状 + 缓存（30s TTL + 主动失效） ----------------
_CACHE_TTL_SEC = 30.0
_cache: dict[str, tuple[float, dict]] = {}
# 全量知识契约（站点 KNOWLEDGE_BASE）缓存：
#   {at, data, src, topics:{name:{etag,body}}, etag?, body?}（v1.19.0 起按主题共享）
_KB_CACHE: dict = {}
# Neo4j 图谱（native/ontology）最近一次读取错误；供状态页排障，成功即清除。
_GRAPH_ERR: dict[str, str] = {}


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _env(content, source: str, version: str = "") -> dict:
    """统一信封：无论来源，返回结构一致。"""
    env = {"content": content, "source": source, "fetchedAt": _now_iso()}
    if version:
        env["version"] = version
    return env


def invalidate(prefix: str = "") -> int:
    """主动失效缓存（prefix 为空清全部）；返回清掉的条数。"""
    global _cache
    if not prefix:
        n = len(_cache)
        _cache = {}
        _KB_CACHE.clear()
        return n
    keys = [k for k in _cache if k.startswith(prefix)]
    for k in keys:
        _cache.pop(k, None)
    # 知识契约与各主题派生载荷同源：knowledge/kb/wiki 任一失效都一并清掉
    if prefix.startswith(("knowledge", "kb", "wiki")):
        _KB_CACHE.clear()
    return len(keys)


def _cached(key: str, producer) -> dict:
    """缓存包装：30s 内命中直接返回（深拷贝避免调用方误改）。"""
    now = time.time()
    hit = _cache.get(key)
    if hit and (now - hit[0]) < _CACHE_TTL_SEC:
        return json.loads(json.dumps(hit[1]))
    val = producer()
    if isinstance(val, dict) and val.get("content") is not None:
        _cache[key] = (now, val)
    return val


# ---------------- 来源健康总览（PRD /api/kb/sources） ----------------
def sources() -> dict:
    """各来源可达性总览；供 /api/kb/sources 与降级可视使用。"""
    wk = {}
    try:
        wk = weknora_retriever.health()
    except Exception as e:  # noqa: BLE001
        wk = {"ok": False, "error": str(e)[:200]}
    canon = canonical_kb.CANONICAL_TTL.exists()
    dbo = False
    try:
        dbo = db_kb.health()
    except Exception:  # noqa: BLE001
        dbo = False
    sqlite_ok = DB_PATH.exists()
    return {
        "sources": [
            {"name": "weknora", "label": "知识库平台（实时）", "ok": bool(wk.get("ok")), "detail": wk},
            {"name": "canonical", "label": "RDF 正本图", "ok": bool(canon),
             "detail": {"path": str(canonical_kb.CANONICAL_TTL)}},
            {"name": "db", "label": "PostgreSQL 结构化投影", "ok": bool(dbo), "detail": {"dsn": config.KB_PG_DSN}},
            {"name": "sqlite", "label": "运行台账", "ok": bool(sqlite_ok), "detail": {"path": str(DB_PATH)}},
        ],
        "precedence": list(SOURCES),
        "cacheTtlSec": _CACHE_TTL_SEC,
        "checkedAt": _now_iso(),
    }


def _preferred_source() -> str:
    """按优先级 weknora > canonical > db > sqlite 取首个可达来源；全不可达取末位。"""
    try:
        ok = [x["name"] for x in sources()["sources"] if x.get("ok")]
    except Exception:  # noqa: BLE001
        ok = []
    return next((n for n in SOURCES if n in ok), SOURCES[-1])


def _norm_source(contributors) -> str:
    """把多次级来源归一为单值枚举（PRD §7.3）：取优先级最高者；无有效值则探测可达源。"""
    cset = [c for c in dict.fromkeys(contributors) if c in SOURCES]
    return next((n for n in SOURCES if n in cset), None) or _preferred_source()


def sources_env() -> dict:
    """来源健康总览的统一信封版（/api/kb/sources）。"""
    s = sources()
    ok = [x["name"] for x in s["sources"] if x.get("ok")]
    src = next((n for n in SOURCES if n in ok), SOURCES[-1])
    return _env(s, src)


def invalidate_env(prefix: str = "") -> dict:
    """主动失效缓存的统一信封版（/api/kb/cache/invalidate）。"""
    return _env({"invalidated": invalidate(prefix), "prefix": prefix}, _preferred_source())


# ===========================================================================
# 检查项：六维详情（M3.2）
# 关键：六维唯一完整来源是"结构化投影/运行台账"，实时知识库平台只提供
# 标题/条文/释义的实时覆盖。故做"结构化底座 + 实时覆盖"的合并，避免出现
# undefined/空白（PRD M3 验收要点 + 历史回归）。
# ===========================================================================

_SIX_KEYS = ("elements", "methodSteps", "metrics", "interviews",
             "verdict", "findings", "related", "suggestedControls")
_SCALAR_KEYS = ("title", "domain", "domainLabel", "priority", "regulation",
                "articleNo", "articleText", "tip", "relatedRaw", "citesClause")


def _sqlite_full(code: str) -> dict | None:
    """运行台账（SQLite）完整六维 —— 与 /api/checks/{code} 既有形状严格一致。"""
    with db() as conn:
        r = conn.execute("SELECT * FROM entities WHERE type='InspectionCheck' AND status='published' "
                         "AND dataJSON LIKE ?", (f'%"checkCode": "{code}"%',)).fetchone()
        if not r:
            return None
        d = json.loads(r["dataJSON"])
        rels = json.loads(r["relationsJSON"])

        def load_ent(eid):
            er = conn.execute("SELECT dataJSON FROM entities WHERE id=?", (eid,)).fetchone()
            return json.loads(er["dataJSON"]) if er else None

        elements = [load_ent(o["o"].split(":", 1)[1]) for o in rels if o["p"] == "hasElement"]
        steps = [load_ent(o["o"].split(":", 1)[1]) for o in rels if o["p"] == "hasMethodStep"]
        metrics = [load_ent(o["o"].split(":", 1)[1]) for o in rels if o["p"] == "measuredBy"]
        interviews = [load_ent(o["o"].split(":", 1)[1]) for o in rels if o["p"] == "hasInterview"]
        findings = [load_ent(o["o"].split(":", 1)[1]) for o in rels if o["p"] == "hasFindingPattern"]
        vr = [load_ent(o["o"].split(":", 1)[1]) for o in rels if o["p"] == "verdictRule"]
        related = [{"ref": o["o"], "relType": "edge"} for o in rels if o["p"] == "relatedCheck"]
        clauses = [o["o"] for o in rels if o["p"] == "citesClause"]
        sc = []
        for o in rels:
            if o["p"] == "suggestsControl":
                p = load_ent(o["o"].split(":", 1)[1])
                if p:
                    sc.append({"hint": p.get("controlCodeHint"), "name": p.get("controlName"),
                               "layer": p.get("suggestedLayer"), "type": p.get("controlTypeHint"),
                               "status": p.get("alignmentStatus"),
                               "ctCode": p.get("ctCode"), "ctLayer": p.get("ctLayer"),
                               "baseControlTitle": p.get("baseControlTitle")})
        return {
            "id": r["id"], "checkCode": d.get("checkCode"), "title": d.get("title"),
            "domain": d.get("domain"), "priority": d.get("priority"),
            "regulation": d.get("regulation"), "articleNo": d.get("articleNo"),
            "articleText": d.get("articleText"), "tip": d.get("tip"),
            "citesClause": clauses,
            "elements": [e for e in elements if e], "methodSteps": [s for s in steps if s],
            "metrics": [m for m in metrics if m], "interviews": [i for i in interviews if i],
            "verdict": vr[0] if vr else {}, "findings": [f for f in findings if f],
            "related": related, "relatedRaw": d.get("relatedRaw", ""),
            "suggestedControls": sc,
        }


def _is_empty(v) -> bool:
    return v in (None, "", [], {})


def _merge_missing(base: dict, fill: dict) -> dict:
    """用 fill 补齐 base 中为空的字段（不覆盖 base 既有非空值）。"""
    if not fill:
        return base
    for k, v in fill.items():
        if k not in base or _is_empty(base.get(k)):
            if not _is_empty(v):
                base[k] = v
    return base


def _weknora_check_overlay(code: str, title_hint: str = "") -> dict | None:
    """实时知识库覆盖：找标题含检查项编号/标题的页面，取标题+正文。

    当前条件：页面标题形如 "[check] 1.1 ..." 或以检查编号开头。未命中返回 None。
    """
    try:
        pages = weknora_retriever.wiki_find(f"[check] {code}") or []
        if not pages and title_hint:
            pages = [p for p in (weknora_retriever.wiki_find(code) or []) if p.get("pageId")]
        if not pages:
            return None
        page = weknora_retriever.wiki_get(pages[0]["pageId"])
        if not page:
            return None
        overlay = {}
        if page.get("content"):
            overlay["articleText"] = page["content"]
        return overlay or None
    except Exception:  # noqa: BLE001
        return None


def fetch_check(code: str) -> dict | None:
    """实时取检查项六维（结构化底座 + 实时覆盖）。

    合并顺序：以 PG 结构化（db）为底座，缺项用 SQLite 补齐（保证六维完整），
    再用知识库平台（weknora）的页面正文实时覆盖标题/条文。
    """
    def _produce() -> dict:
        sql = None
        try:
            sql = _sqlite_full(code)
        except Exception:  # noqa: BLE001
            sql = None
        dbf = None
        try:
            dbf = db_kb.get_check_full(code)
        except Exception:  # noqa: BLE001
            dbf = None

        base = None
        contributors = []
        if dbf and not _is_empty(dbf.get("elements")):
            base = dbf
            contributors.append("db")
        if sql:
            if base is None:
                base = sql
            else:
                _merge_missing(base, sql)     # 用台账补齐（含 suggestedControls/tip/relatedRaw）
            contributors.append("sqlite")
        if base is None:
            # 无结构化六维：退到 canonical 精简形状（至少不 404）。
            # v1.16.0（QA-C）：终结兜底同样加 try/except，canonical 读源异常时不得冒泡，
            # 保持"永不 5xx"红线与其余来源同等纪律。
            ck = None
            try:
                ck = canonical_kb.get_check(code)
            except Exception:  # noqa: BLE001
                ck = None
            if not ck:
                return {"content": None, "source": "none", "fetchedAt": _now_iso()}
            base = {"checkCode": ck.get("checkCode"), "title": ck.get("title"),
                    "domain": ck.get("domain"), "priority": ck.get("priority"),
                    "regulation": ck.get("regulation", ""), "articleNo": ck.get("articleNo", ""),
                    "articleText": ck.get("summary", ""), "citesClause": ck.get("citesClause", []),
                    "elements": ck.get("elements", []), "methodSteps": [], "metrics": [],
                    "interviews": [], "verdict": {}, "findings": [], "related": [],
                    "relatedRaw": "", "suggestedControls": []}
            contributors.append("canonical")

        # 实时覆盖
        ov = _weknora_check_overlay(code, base.get("title") or "")
        if ov:
            base.update(ov)
            contributors.insert(0, "weknora")
        base["checkCode"] = base.get("checkCode") or code
        for k in _SIX_KEYS:
            base.setdefault(k, [] if k != "verdict" else {})
        src = _norm_source(contributors)
        return _env(base, src)

    return _cached(f"check:{code}", _produce)


# ===========================================================================
# 检查项：列表（M3.1）
# ===========================================================================
def _checks_from_db(doc: str, domain: str, priority: str, keyword: str) -> dict | None:
    """PG inspection_check 列表（含计数）。库不可达返回 None。"""
    try:
        if not db_kb.health():
            return None
        where = ["1=1"]
        args: list = []
        unknown_doc = False
        if doc:
            if doc == "jg24":
                where.append("check_code NOT LIKE %s AND check_code NOT LIKE %s AND check_code NOT LIKE %s")
                args.extend(["93-%", "pb3-%", "jf8-%"])
            elif doc in ("jg93", "pboc3", "jf8"):
                prefix = {"jg93": "93-", "pboc3": "pb3-", "jf8": "jf8-"}[doc]
                where.append("check_code LIKE %s")
                args.append(prefix + "%")
            else:
                # 未知文号：显式空集，避免 LIKE '%' 静默匹配全量（QA1 D1）
                unknown_doc = True
        if domain:
            where.append("domain = %s")
            args.append(domain)
        if priority:
            where.append("priority = %s")
            args.append(priority)
        if keyword:
            where.append("(title ILIKE %s OR article_text ILIKE %s OR check_code ILIKE %s)")
            args.extend([f"%{keyword}%"] * 3)
        sql_w = " AND ".join(where)
        rows = [] if unknown_doc else db_kb._q(  # noqa: SLF001 — 同包内复用只读连接
            f"""SELECT check_code, title, domain, domain_label, priority, regulation,
                       article_no, article_text
                FROM inspection_check WHERE {sql_w} ORDER BY check_code""", tuple(args))
        # 全量计数（按文号）
        allrows = db_kb._q(
            """SELECT check_code, domain, priority FROM inspection_check""")
        by_domain, by_priority, by_doc = {}, {}, {}
        for r in allrows:
            code = r["check_code"] or ""
            by_domain[r["domain"]] = by_domain.get(r["domain"], 0) + 1
            by_priority[r["priority"]] = by_priority.get(r["priority"], 0) + 1
            dk = ("jg93" if code.startswith("93-") else "pboc3" if code.startswith("pb3-")
                  else "jf8" if code.startswith("jf8-") else "jg24")
            by_doc[dk] = by_doc.get(dk, 0) + 1
        checks = []
        for r in rows:
            code = r["check_code"] or ""
            dk = ("jg93" if code.startswith("93-") else "pboc3" if code.startswith("pb3-")
                  else "jf8" if code.startswith("jf8-") else "jg24")
            checks.append({"id": code, "checkCode": code, "title": r["title"],
                           "domain": r["domain"], "domainLabel": r["domain_label"],
                           "priority": r["priority"], "regulation": r["regulation"],
                           "articleNo": r["article_no"], "docKey": dk})
        return {"total": len(allrows), "filtered": len(checks),
                "byDomain": by_domain, "byPriority": by_priority, "byDoc": by_doc,
                "checks": checks}
    except Exception:  # noqa: BLE001
        return None


def _checks_from_sqlite(doc: str, domain: str, priority: str, keyword: str) -> dict:
    """运行台账列表兜底（与 /api/checks 既有逻辑一致）。"""
    with db() as conn:
        rows = conn.execute("SELECT id,dataJSON FROM entities WHERE type='InspectionCheck' "
                            "AND status='published' ORDER BY id").fetchall()
    out, by_domain, by_priority, by_doc = [], {}, {}, {}
    for r in rows:
        d = json.loads(r["dataJSON"])
        by_domain[d.get("domain")] = by_domain.get(d.get("domain"), 0) + 1
        by_priority[d.get("priority")] = by_priority.get(d.get("priority"), 0) + 1
        dk = d.get("docKey") or "jg24"
        by_doc[dk] = by_doc.get(dk, 0) + 1
        if doc and doc not in (d.get("docKey") or "") and doc not in (d.get("docNo") or ""):
            continue
        if domain and d.get("domain") != domain:
            continue
        if priority and d.get("priority") != priority:
            continue
        if keyword and keyword not in json.dumps(d, ensure_ascii=False):
            continue
        out.append({"id": r["id"], "checkCode": d.get("checkCode"), "title": d.get("title"),
                    "domain": d.get("domain"), "domainLabel": d.get("domainLabel"),
                    "priority": d.get("priority"), "regulation": d.get("regulation"),
                    "articleNo": d.get("articleNo"), "docKey": d.get("docKey")})
    return {"total": len(rows), "filtered": len(out), "byDomain": by_domain,
            "byPriority": by_priority, "byDoc": by_doc, "checks": out}


def fetch_checks(doc: str = "", domain: str = "", priority: str = "", keyword: str = "") -> dict:
    """实时取检查项列表。结构化登记表（db→sqlite），可被知识库页面覆盖。"""
    key = f"checks:{doc}:{domain}:{priority}:{keyword}"

    def _produce() -> dict:
        data = _checks_from_db(doc, domain, priority, keyword)
        src = "db"
        if data is None:
            data = _checks_from_sqlite(doc, domain, priority, keyword)
            src = "sqlite"
        if not data.get("checks"):
            data = _checks_from_sqlite(doc, domain, priority, keyword)
            src = "sqlite"
        return _env(data, src)

    return _cached(key, _produce)


# ===========================================================================
# 实体 / 检索 / 控制 / Wiki（M6.2）
# ===========================================================================
def fetch_entity(eid: str) -> dict | None:
    def _produce() -> dict:
        from . import kb_read
        ent = kb_read.get_entity(eid)
        if ent:
            # 标注来源（kb_read 内部已按 db→canonical→json 走）
            return _env(ent, ent.get("source", "db"))
        return {"content": None, "source": "none", "fetchedAt": _now_iso()}

    return _cached(f"entity:{eid}", _produce)


def fetch_search(q: str, limit: int = 20) -> dict:
    """融合检索：关键词/向量/图谱/RAG + 知识库实时向量路（含来源标注）。"""
    def _produce() -> dict:
        from . import kb_read
        res = kb_read.search(q, limit) or {}
        return _env(res, _preferred_source())

    return _cached(f"search:{q}:{limit}", _produce)


def fetch_controls() -> dict:
    def _produce() -> dict:
        from . import kb_read
        res = kb_read.list_controls()
        src = "db" if (db_kb.health() and res.get("total")) else "canonical"
        return _env(res, src)

    return _cached("controls", _produce)


def fetch_wiki(page_id: str) -> dict | None:
    """实时读取知识库平台 Wiki 页面（id 或精确标题）。"""
    def _produce() -> dict:
        try:
            page = weknora_retriever.wiki_get(page_id)
        except Exception:  # noqa: BLE001
            page = None
        if page:
            return _env(page, "weknora", version=page.get("updatedAt") or "")
        # 退到正本实体
        ent = canonical_kb.get_entity(page_id)
        if ent:
            return _env(ent, "canonical")
        return {"content": None, "source": "none", "fetchedAt": _now_iso()}

    return _cached(f"wiki:{page_id}", _produce)


def fetch_wiki_index(limit: int = 500) -> dict:
    """知识库 Wiki 目录（页面清单）。"""
    def _produce() -> dict:
        try:
            pages = weknora_retriever.wiki_list(limit)
        except Exception:  # noqa: BLE001
            pages = []
        if pages:
            # 按 type 聚合目录
            tree: dict[str, list] = {}
            for p in pages:
                tree.setdefault(p.get("type") or "其他", []).append(p)
            return _env({"total": len(pages), "tree": tree, "pages": pages}, "weknora")
        return {"content": None, "source": "none", "fetchedAt": _now_iso()}

    return _cached("wiki:index", _produce)


# ===========================================================================
# v1.17.0 知识库能力开放（PRD M11）
# 大白话：Wiki 目录按"业务分类"聚合（映射表在 app/data/kb_taxonomy.json，改分类只改它）；
# 知识加工走知识库平台官方 API（投递 + 查进度），平台不落库处理态（D5）。
# ===========================================================================

_TAXONOMY_CACHE: dict | None = None


def _taxonomy() -> dict:
    """加载业务分类映射（进程内缓存；文件缺失用内置兜底，不阻断）。"""
    global _TAXONOMY_CACHE
    if _TAXONOMY_CACHE is not None:
        return _TAXONOMY_CACHE
    tx = {"fallback": "其他", "order": [], "map": {}}
    try:
        raw = json.loads((APP_DATA / "kb_taxonomy.json").read_text(encoding="utf-8"))
        tx["fallback"] = raw.get("fallback") or "其他"
        tx["order"] = [str(x) for x in (raw.get("order") or []) if x]
        tx["map"] = {str(k).strip().lower(): v for k, v in (raw.get("map") or {}).items() if v}
    except Exception:  # noqa: BLE001
        pass
    _TAXONOMY_CACHE = tx
    return tx


def _category(type_prefix: str) -> str:
    """type 前缀 → 业务分类：精确命中 → 包含命中 → fallback。"""
    tx = _taxonomy()
    key = (type_prefix or "").strip().lower()
    m = tx["map"]
    if key and key in m:
        return m[key]
    if key:
        for k, v in m.items():  # 包含匹配（如 type="法规条文" 命中 "法规"）
            if k and (k in key or key in k):
                return v
    return tx["fallback"]


def fetch_wiki_tree(limit: int = 500) -> dict:
    """Wiki 目录树：把页面按业务分类聚合成 [{category, count, pages}]。"""
    def _produce() -> dict:
        try:
            pages = weknora_retriever.wiki_list(limit)
        except Exception:  # noqa: BLE001
            pages = []
        if not pages:
            return {"content": None, "source": "none", "fetchedAt": _now_iso()}
        groups: dict[str, list] = {}
        for p in pages:
            cat = _category(p.get("type") or "")
            groups.setdefault(cat, []).append({
                "pageId": p.get("pageId"), "title": p.get("title"),
                "name": p.get("name") or p.get("title"), "type": p.get("type") or "",
                "updatedAt": p.get("updatedAt") or "",
            })
        order = [c for c in _taxonomy()["order"] if c in groups]
        rest = sorted(c for c in groups if c not in order)
        tree = [{"category": c, "count": len(groups[c]), "pages": groups[c]}
                for c in order + rest]
        return _env({"total": len(pages), "categories": [t["category"] for t in tree],
                     "tree": tree}, "weknora")

    return _cached(f"wiki:tree:{limit}", _produce)


def submit_ingest(title: str, content: str) -> dict:
    """知识加工投递（仅 /admin）：走知识库平台官方 API，平台不落库处理态。"""
    res = weknora_retriever.submit_manual(title, content)
    if res.get("ok"):
        invalidate("wiki:")   # 投递成功即失效目录缓存，查阅/检索尽快可见
    return _env(res, "weknora" if res.get("ok") else "none")


def fetch_ingest_status(knowledge_id: str) -> dict:
    """加工进度：读知识库平台该条知识的分块/向量化状态。"""
    try:
        st = weknora_retriever.knowledge_status(knowledge_id)
    except Exception:  # noqa: BLE001
        st = None
    if st:
        return _env(st, "weknora")
    return {"content": None, "source": "none", "fetchedAt": _now_iso()}


# ===========================================================================
# v1.18.0 全量知识契约（M11.3）：站点 KNOWLEDGE_BASE 形状
# 大白话：菜单1静态站原本靠构建期生成的 knowledge-data.js 驱动；合并为单一
# 「知识库」入口后，改为运行期从知识库平台的原始 Markdown 现场装配同一形状，
# 前端零改造渲染。全量载荷按字节缓存 + ETag，避免每次请求重复序列化/压缩。
#
# v1.19.0（M11.5）按主题拆分子接口：全量契约约 5MB（body_html 46% / edges 21% /
# relations_out 13%），随知识库增长会持续变重。故按"页面实际需要"切成四个主题：
#   /api/kb/knowledge/index      轻量索引（列表/筛选/检索候选；无正文、无边）
#   /api/kb/knowledge/graph      图谱（nodes + edges，仅图谱视图加载）
#   /api/kb/knowledge/entity/{id} 单实体详情（正文/来源/出链 + 入链）
#   /api/kb/knowledge/search     服务端全字段检索（含正文，替代前端全量建索引）
# 全部由同一份装配结果派生（同一 30s TTL 缓存），各自独立 ETag/304；全量
# /api/kb/knowledge 保留，供 MCP 与兜底使用。
# ===========================================================================

def _static_knowledge() -> dict | None:
    """兜底快照：知识库站点内挂载的构建产物 data/knowledge-data.js。

    知识库平台不可达时，退回上一份构建快照（内容同源、可能略旧），保证页面
    不空窗、不 5xx。
    """
    site = Path(os.environ.get("KB10_SITE", "/app/kb_site"))
    p = site / "data" / "knowledge-data.js"
    if not p.exists():
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
        i, j = text.find("{"), text.rfind("}")
        if i < 0 or j <= i:
            return None
        snap = json.loads(text[i:j + 1])
        return snap if snap.get("entities") else None
    except Exception:  # noqa: BLE001
        return None


def _json_default(o):
    """frontmatter 中的 YYYY-MM-DD 会被 PyYAML 解析为 date/datetime，统一转 ISO 字符串。"""
    if isinstance(o, datetime.date):  # datetime 是 date 的子类
        return o.isoformat()
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")


def _strip_ts(obj):
    """剔除装配时间戳，使 ETag 对同一份知识恒定（浏览器可稳定命中 304）。"""
    if not isinstance(obj, dict):
        return obj
    return {k: v for k, v in obj.items() if k not in ("generated_at", "fetchedAt")}


def _etag_of(content) -> str:
    """内容 ETag（不含装配时间戳）。注：不加 sort_keys —— attrs 可能含 YAML 数字键。"""
    raw = json.dumps(_strip_ts(content), ensure_ascii=False,
                     default=_json_default).encode("utf-8")
    return '"' + hashlib.sha256(raw).hexdigest()[:32] + '"'


def _load_knowledge(force: bool = False) -> dict:
    """装配（或复用）全量知识契约；返回 _KB_CACHE 本身。30s TTL。

    缓存键：data（装配结果）/ src（来源）/ at（装配时刻）/ topics（各主题派生载荷）/
    etag + body（全量契约序列化结果，按需惰性生成）。
    """
    now = time.time()
    if (not force and _KB_CACHE.get("data") is not None
            and (now - _KB_CACHE.get("at", 0.0)) < _CACHE_TTL_SEC):
        return _KB_CACHE
    docs = []
    try:
        docs = weknora_retriever.knowledge_docs()
    except Exception:  # noqa: BLE001
        docs = []
    data, src = None, "none"
    if docs:
        try:
            data = kb_knowledge.build(docs)
            src = "weknora"
        except Exception:  # noqa: BLE001 — 装配失败同样降级到快照
            data = None
    if not data or not data.get("entities"):
        data, src = _static_knowledge(), "canonical"
    if not data or not data.get("entities"):
        data, src = None, "none"
    _KB_CACHE.clear()
    _KB_CACHE.update({"at": now, "data": data, "src": src, "topics": {}})
    return _KB_CACHE


def _kb_bytes(content, src: str) -> bytes:
    return json.dumps(_env(content, src), ensure_ascii=False,
                      default=_json_default).encode("utf-8")


def _kb_topic(topic: str, producer) -> tuple[str, bytes]:
    """按主题生成 (etag, json_bytes)；与全量契约共享 30s TTL 与主动失效。"""
    st = _load_knowledge()
    bucket = st.setdefault("topics", {})
    hit = bucket.get(topic)
    if hit:
        return hit["etag"], hit["body"]
    data, src = st.get("data"), st.get("src") or "none"
    content = producer(data) if data else None
    etag = _etag_of(content) if content is not None else ""
    body = _kb_bytes(content, src)
    bucket[topic] = {"etag": etag, "body": body}
    return etag, body


# ---- 主题派生：索引 / 图谱 / 实体 / 检索 ----
# 索引投影：仅保留列表、筛选、卡片与关系指向所需的字段（正文/来源/出链不进索引）
_INDEX_FIELDS = (
    "id", "type", "title", "title_en", "level", "aliases", "tags", "summary",
    "status", "updated", "official_url", "md_path", "attrs",
    "code", "layer", "lifecycle", "control_type", "family", "standard_mappings",
)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    return _TAG_RE.sub("", html or "").strip()


def _snippet(e: dict, q: str) -> str:
    """与前端一致的摘要：正文命中处截 110 字，未命中回退 summary。"""
    full = _strip_html(e.get("body_html") or "")
    idx = full.lower().find((q or "").strip().lower())
    if idx < 0:
        return e.get("summary") or ""
    s = max(0, idx - 30)
    return ("…" if s > 0 else "") + full[s:s + 110] + "…"


def _project_index(data: dict) -> dict:
    ents = data.get("entities") or []
    return {
        "generated_at": data.get("generated_at"),
        "version": data.get("version"),
        "counts": data.get("counts") or {},
        "entityCount": len(ents),
        "edgeCount": len(data.get("edges") or []),
        "entities": [{k: e.get(k) for k in _INDEX_FIELDS if k in e} for e in ents],
    }


def knowledge_index_payload() -> tuple[str, bytes]:
    """轻量索引（首页/列表/筛选/卡片）：无正文、无来源、无关系明细、无边。"""
    return _kb_topic("index", _project_index)


def knowledge_graph_payload(source: str = "site") -> tuple[str, bytes]:
    """图谱主题：nodes + edges（仅知识图谱视图加载）。

    source 切换图谱数据源（v1.20.0，用户「双源可切换」诉求）：
      - ``site``（默认）：本站知识库装配图（Markdown -> nodes/edges，见 kb_knowledge）。
      - ``native``      ：底层 WeKnora 抽取图（Neo4j ``:ENTITY*``），直连只读。
      - ``ontology``    ：平台本体镜像图（Neo4j ``:Entity`` @ dsec.local）。

    Neo4j 来源失败一律回落到 site 图（永不中断），并在信封 source 中标注实际来源。
    """
    src = (source or "site").strip().lower()
    if src in ("native", "ontology"):
        env = _neo_graph_payload(src)
        if env is not None:
            return env[0], env[1]
        # 回落：Neo4j 不可达时退回站点图，保证图谱视图始终有内容
    def _produce(data):
        return {
            "generated_at": data.get("generated_at"),
            "version": data.get("version"),
            "graphSource": "site",
            "counts": data.get("counts") or {},
            "nodes": data.get("nodes") or [],
            "edges": data.get("edges") or [],
        }
    return _kb_topic("graph", _produce)


def _neo_graph_payload(src: str) -> tuple[str, bytes] | None:
    """Neo4j 图谱（native/ontology）载荷，独立 30s TTL 缓存；异常返回 None 供回落。"""
    now = time.time()
    key = f"graph:{src}"
    hit = _cache.get(key)
    if hit and (now - hit[0]) < _CACHE_TTL_SEC:
        body = hit[1]["body"]
        return hit[1]["etag"], body
    try:
        content = weknora_graph.read_graph(src)
    except Exception as e:  # noqa: BLE001 — 任何 Neo4j 异常都回落到站点图
        _GRAPH_ERR[key] = str(e)[:200]
        return None
    if not content or not content.get("nodes"):
        _GRAPH_ERR[key] = "empty graph"
        return None
    _GRAPH_ERR.pop(key, None)
    env = _env(content, f"weknora-neo4j:{src}")
    env["graphSource"] = src
    body = json.dumps(env, ensure_ascii=False, default=_json_default).encode("utf-8")
    etag = _etag_of(content)
    _cache[key] = (now, {"etag": etag, "body": body})
    return etag, body


def knowledge_entity(eid: str) -> tuple[str, bytes]:
    """单实体详情：完整记录（正文/来源/出链）+ 入链（自 edges 反查）。

    未命中返回 ("", body)，由路由转 404（知识库不可达时同样返回未命中）。
    """
    def _produce(data):
        rec = next((e for e in (data.get("entities") or [])
                    if e.get("id") == eid), None)
        if not rec:
            return None
        rel_in, seen = [], set()
        for x in (data.get("edges") or []):
            if x.get("target") != eid:
                continue
            key = (x.get("source"), x.get("rel"))
            if key in seen:
                continue
            seen.add(key)
            rel_in.append({"rel": x.get("rel"), "source": x.get("source"),
                           "label": x.get("label"), "inline": bool(x.get("inline"))})
        return {"entity": rec, "relations_in": rel_in}

    return _kb_topic("entity:" + eid, _produce)


def knowledge_search(q: str, limit: int = 12) -> bytes:
    """服务端全字段检索（含正文）：与前端原打分口径一致，避免首屏传全量正文。

    不缓存：查询串无限、缓存无界；526 条量级下纯内存打分耗时可忽略。
    """
    qn = (q or "").strip()
    try:
        limit = max(1, min(int(limit or 12), 50))
    except Exception:  # noqa: BLE001
        limit = 12
    st = _load_knowledge()
    data, src = st.get("data"), st.get("src") or "none"
    if not data or not qn:
        return _kb_bytes({"q": qn, "total": 0, "results": []}, src)
    ql = qn.lower()
    toks = [t for t in ql.split() if t]
    scored = []
    for e in (data.get("entities") or []):
        title = (e.get("title") or "").lower()
        aliases = [a for a in (e.get("aliases") or []) if isinstance(a, str)]
        tags = [t for t in (e.get("tags") or []) if isinstance(t, str)]
        summary = (e.get("summary") or "").lower()
        body = _strip_html(e.get("body_html") or "").lower()
        hay = " ".join([title, " ".join(aliases), " ".join(tags), summary, body])
        if not all(t in hay for t in toks):
            continue
        score = 0
        if ql in title:
            score += 100
        score += 60 * sum(1 for a in aliases if ql in a.lower())
        score += 40 * sum(1 for t in tags if ql in t.lower())
        if ql in summary:
            score += 25
        if ql in body:
            score += 10
        if score == 0:
            score = 5
        scored.append((score, e))
    scored.sort(key=lambda x: -x[0])
    results = [{
        "id": e.get("id"), "title": e.get("title"), "type": e.get("type"),
        "level": e.get("level"), "aliases": e.get("aliases") or [],
        "tags": e.get("tags") or [], "summary": e.get("summary") or "",
        "snippet": _snippet(e, qn), "score": score,
    } for score, e in scored[:limit]]
    return _kb_bytes({"q": qn, "total": len(scored), "results": results}, src)


def knowledge_payload(force: bool = False) -> tuple[str, bytes]:
    """全量知识契约 HTTP 快路径（兼容 / MCP）：返回 (etag, json_bytes)。

    v1.19.0 起前端改为按主题取数，本接口保留以兼容既有调用方与兜底。
    """
    st = _load_knowledge(force)
    if not force and st.get("body") is not None:
        return st.get("etag", ""), st["body"]
    data, src = st.get("data"), st.get("src") or "none"
    if not data:
        body = _kb_bytes(None, "none")
        st.update({"etag": "", "body": body})
        return "", body
    etag = _etag_of(data)
    body = _kb_bytes(data, src)
    st.update({"etag": etag, "body": body})
    return etag, body


def fetch_knowledge() -> dict:
    """全量知识契约（统一信封版，供 MCP / 内部调用）。"""
    _, body = knowledge_payload()
    try:
        return json.loads(body)
    except Exception:  # noqa: BLE001
        return {"content": None, "source": "none", "fetchedAt": _now_iso()}
