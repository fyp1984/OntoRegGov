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

import json
import time
import datetime

from .. import config
from ..config import DB_PATH, APP_DATA
from . import canonical_kb, db_kb, weknora_retriever
from ..db import db

SOURCES = ("weknora", "canonical", "db", "sqlite")

# ---------------- 统一形状 + 缓存（30s TTL + 主动失效） ----------------
_CACHE_TTL_SEC = 30.0
_cache: dict[str, tuple[float, dict]] = {}


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
        return n
    keys = [k for k in _cache if k.startswith(prefix)]
    for k in keys:
        _cache.pop(k, None)
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
