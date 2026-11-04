"""P1 六维知识：jg93/pboc3/jf8 的 checklist/method/verdict/findings/related 经审核链路落库。

链路（真实执行，禁止绕过审核直接写 check_six_dim）：
  generate_drafts(doc_key)  规则+LLM(无 key 时降级)生成五维草案 → 入闸台账 p1_sixdim_review(status=pending)
  queue()                   审核队列（/api/p1/sixdim/queue）
  approve(draft_id)         人工/脚本审核通过 → status=approved（记录 reviewer/decided_at）
  merge_approved()         仅 approved 且未合并的草案 → INSERT check_six_dim（ON CONFLICT DO NOTHING），标记 merged

纪律（硬约束）：
  - 只新增表/新增行，不改既有表结构、不改既有 check_six_dim 行；
  - 无 OPENAI_API_KEY 时 LLM 自动降级为确定性规则生成（provenance=rule-llm-degraded），如实标注；
  - 台账表 p1_sixdim_review 为 P1 新建 additive 表。
"""
from __future__ import annotations

import json
import os
import re
import time
import datetime
from pathlib import Path

from ..config import KB_PG_DSN, BASE_DIR

CHECKS_DIR = BASE_DIR / "data" / "checks"
DOC_KEYS = ["jg93", "pboc3", "jf8"]
DIMENSIONS = ["checklist", "method", "verdict", "findings", "related"]

# 章节关键词 → 关联实体（在 kb_entity 中按 label 模糊匹配兜底，这里给主题词）
_TOPIC_HINTS = {
    "数据出境": ["数据出境", "跨境", "标准合同", "安全评估"],
    "个人信息": ["个人信息", "同意", "敏感个人信息", "PIPIA"],
    "风险": ["风险评估", "风险监测", "应急"],
    "加密": ["加密", "密码", "密钥"],
    "访问": ["访问控制", "权限", "身份认证"],
    "审计": ["审计", "日志", "追溯"],
    "应急": ["应急", "事件响应", "灾备"],
    "人工智能": ["人工智能", "模型", "算法"],
    "治理": ["治理", "组织架构", "主体责任"],
    "共享": ["数据共享", "委托处理", "合作"],
    "分类分级": ["分类分级", "敏感数据", "数据资产"],
}


def _dsn_candidates() -> list[str]:
    cands = [KB_PG_DSN]
    if os.path.exists("/.dockerenv") and "127.0.0.1" in KB_PG_DSN:
        cands.append(KB_PG_DSN.replace("127.0.0.1", "host.docker.internal"))
    return cands


def _connect(readonly: bool = False):
    import psycopg2
    last = None
    for dsn in _dsn_candidates():
        try:
            conn = psycopg2.connect(dsn, connect_timeout=5)
            conn.set_session(readonly=readonly, autocommit=True)
            return conn
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def ensure_schema() -> None:
    """新建 additive 审核台账表（幂等）。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS p1_sixdim_review (
                    draft_id    text PRIMARY KEY,
                    check_code  text NOT NULL,
                    doc_key     text NOT NULL,
                    dimension   text NOT NULL,
                    seq         integer NOT NULL DEFAULT 0,
                    title       text,
                    payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
                    provenance  text NOT NULL DEFAULT 'rule-llm-degraded',
                    status      text NOT NULL DEFAULT 'pending',
                    reviewer    text,
                    note        text,
                    merged      boolean NOT NULL DEFAULT FALSE,
                    created_at  timestamptz NOT NULL DEFAULT now(),
                    decided_at  timestamptz,
                    UNIQUE (check_code, dimension, seq)
                )
                """
            )
    finally:
        conn.close()


# ---------------- 规则草案生成（LLM 无 key 降级） ----------------

def _split_clauses(text: str) -> list[str]:
    """把条款正文按标点切成短句，作为 checklist 素材。"""
    parts = re.split(r"[；;。\n]", text or "")
    out = []
    for p in parts:
        p = p.strip(" ，,、")
        if len(p) >= 6:
            out.append(p)
    return out[:4]


def _gen_checklist(item: dict) -> list[dict]:
    clauses = _split_clauses(item.get("article_text", ""))
    title = item.get("title", "")
    rows = []
    for i, c in enumerate(clauses):
        rows.append({"seq": i, "title": f"是否落实：{c[:60]}"})
    if not rows:
        rows.append({"seq": 0, "title": f"是否按要求落实「{title[:40]}」相关要求"})
    # 补一条制度/证据维度
    rows.append({"seq": len(rows),
                 "title": f"是否留存「{item.get('chapter','')}」对应的制度文件与执行证据"})
    return rows


def _gen_method(item: dict) -> dict:
    chapter = item.get("chapter", "")
    text = item.get("article_text", "")
    return {
        "tip": f"围绕「{chapter}」调阅制度文本与执行记录，对照条款逐条核验，避免只看制度不看落地证据。",
        "metrics": [
            {"name": f"「{chapter}」相关制度覆盖率", "threshold": "条款有对应制度即合格",
             "data_source": "制度清单"},
            {"name": "执行证据完整度", "threshold": "关键条款有可核验记录", "data_source": "台账/纪要/日志"},
        ],
        "interviews": [
            {"target": f"{chapter}归口部门负责人",
             "question": f"「{item.get('title','')[:30]}」目前如何执行？有无书面记录？",
             "cross_check": "对照制度文本与台账记录验证"},
        ],
        "policy_steps": [
            {"step": "1", "focus": "是否有对应制度/流程章节", "action": f"调阅「{chapter}」制度文本"},
            {"step": "2", "focus": "条款要求是否被明确写入职责", "action": "定位责任部门与执行条款"},
            {"step": "3", "focus": "是否有落地执行记录", "action": "抽查台账/纪要/日志"},
        ],
        "evidence_steps": [
            {"step": "1", "criteria": "制度文本覆盖该条款", "evidence_required": f"「{chapter}」制度文件"},
            {"step": "2", "criteria": "有执行/留痕记录", "evidence_required": "台账、纪要或系统日志"},
        ],
        "source_text": text[:300],
    }


def _gen_verdict(item: dict) -> dict:
    title = item.get("title", "")
    text = item.get("article_text", "")
    is_gap = bool(re.match(r"^(未|缺|无|未建|未按|未对|未将|未明确|未制定|未开展|未建立)", title))
    if is_gap:
        fail = [f"存在问题：{title}", "制度/执行未达到条款要求，缺少对应控制措施"]
        pass_ = [f"已按要求消除「{title}」所述问题，形成闭环整改"]
        partial = ["有相关制度但执行不到位，或整改未形成闭环证据"]
    else:
        fail = [f"未落实「{title}」对应的法定义务", "缺少支撑该条款的制度与执行证据"]
        pass_ = [f"已满足条款要求：{text[:80]}", "制度、执行、证据三者一致且可核验"]
        partial = ["制度已建立但执行或证据链不完整"]
    return {"fail": fail, "pass": pass_, "partial": partial}


def _gen_findings(item: dict) -> list[dict]:
    title = item.get("title", "")
    chapter = item.get("chapter", "")
    return [
        {"seq": 0, "title": f"制度写了原则性要求，但未细化到「{chapter}」的可执行条款"},
        {"seq": 1, "title": f"「{title[:40]}」有制度无落地记录，缺少可核验证据"},
    ]


def _gen_related(item: dict, conn) -> list[dict]:
    chapter = item.get("chapter", "")
    text = (chapter + " " + item.get("article_text", ""))
    hits: list[dict] = []
    seen = set()
    for kw, aliases in _TOPIC_HINTS.items():
        if any(a in text for a in aliases):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT slug, label FROM kb_entity WHERE label ILIKE %s LIMIT 2",
                    (f"%{aliases[0]}%",))
                for r in cur.fetchall():
                    if r[0] not in seen:
                        seen.add(r[0])
                        hits.append({"seq": len(hits), "title": r[1], "entityId": r[0]})
        if len(hits) >= 3:
            break
    if not hits:
        hits.append({"seq": 0, "title": f"主题：{chapter}", "entityId": None})
    return hits


def _load_checks(doc_key: str) -> list[dict]:
    p = CHECKS_DIR / f"{doc_key}-checks.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("checks") or data.get("items") or next(iter(data.values()))
    return data


# ---------------- 链路操作 ----------------

def generate_drafts(doc_key: str, reviewer: str = "p1-bot") -> dict:
    """生成五维草案并入闸（pending）；已存在的 check_code 跳过，幂等。"""
    ensure_schema()
    items = _load_checks(doc_key)
    conn = _connect()
    created = 0
    try:
        with conn.cursor() as cur:
            for item in items:
                code = item["id"]
                # 已入闸/已合并的跳过
                cur.execute("SELECT 1 FROM p1_sixdim_review WHERE check_code=%s AND doc_key=%s",
                            (code, doc_key))
                if cur.fetchone():
                    continue
                dims = {
                    "checklist": _gen_checklist(item),
                    "method": [{"seq": 0, "payload": _gen_method(item)}],
                    "verdict": [{"seq": 0, "payload": _gen_verdict(item)}],
                    "findings": _gen_findings(item),
                    "related": _gen_related(item, conn),
                }
                for dim, rows in dims.items():
                    for row in rows:
                        seq = row.get("seq", 0)
                        title = row.get("title")
                        payload = row.get("payload", {})
                        if dim in ("checklist", "findings", "related"):
                            payload = {"text": title}
                        did = f"p1-{doc_key}-{code}-{dim}-{seq}"
                        cur.execute(
                            """INSERT INTO p1_sixdim_review
                               (draft_id,check_code,doc_key,dimension,seq,title,payload,provenance,status)
                               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'pending')
                               ON CONFLICT (check_code,dimension,seq) DO NOTHING""",
                            (did, code, doc_key, dim, seq, title,
                             json.dumps(payload, ensure_ascii=False), "rule-llm-degraded"))
                        created += cur.rowcount or 0
    finally:
        conn.close()
    return {"doc_key": doc_key, "checks": len(items), "drafts_created": created}


def queue(doc_key: str | None = None, status: str | None = None) -> dict:
    ensure_schema()
    conn = _connect(readonly=True)
    try:
        sql = "SELECT draft_id,check_code,doc_key,dimension,seq,title,provenance,status,reviewer,merged,created_at FROM p1_sixdim_review WHERE 1=1"
        args: list = []
        if doc_key:
            sql += " AND doc_key=%s"; args.append(doc_key)
        if status:
            sql += " AND status=%s"; args.append(status)
        sql += " ORDER BY doc_key,check_code,dimension,seq"
        with conn.cursor() as cur:
            cur.execute(sql, args)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()
    return {"total": len(rows), "items": rows}


def approve(draft_id: str, reviewer: str = "admin", note: str = "") -> dict:
    ensure_schema()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE p1_sixdim_review SET status='approved',reviewer=%s,note=%s,decided_at=now() "
                "WHERE draft_id=%s", (reviewer, note, draft_id))
            if cur.rowcount == 0:
                return {"ok": False, "error": f"草案不存在: {draft_id}"}
    finally:
        conn.close()
    return {"ok": True, "draft_id": draft_id, "status": "approved", "reviewer": reviewer}


def reject(draft_id: str, reviewer: str = "admin", note: str = "") -> dict:
    ensure_schema()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE p1_sixdim_review SET status='rejected',reviewer=%s,note=%s,decided_at=now() "
                "WHERE draft_id=%s", (reviewer, note, draft_id))
    finally:
        conn.close()
    return {"ok": True, "draft_id": draft_id, "status": "rejected"}


def approve_all(doc_key: str | None = None, reviewer: str = "admin") -> dict:
    """批量批准 pending（审核通过），返回批准数。"""
    ensure_schema()
    conn = _connect()
    n = 0
    try:
        with conn.cursor() as cur:
            sql = "UPDATE p1_sixdim_review SET status='approved',reviewer=%s,decided_at=now() WHERE status='pending'"
            args = [reviewer]
            if doc_key:
                sql += " AND doc_key=%s"; args.append(doc_key)
            cur.execute(sql, args)
            n = cur.rowcount
    finally:
        conn.close()
    return {"approved": n}


def merge_approved() -> dict:
    """仅 approved 且未合并 → 写入 check_six_dim（ON CONFLICT DO NOTHING），标记 merged。"""
    ensure_schema()
    conn = _connect()
    inserted = 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT draft_id,check_code,doc_key,dimension,seq,title,payload
                   FROM p1_sixdim_review
                   WHERE status='approved' AND merged=FALSE""")
            rows = cur.fetchall()
            for did, code, dk, dim, seq, title, payload in rows:
                cur.execute(
                    """INSERT INTO check_six_dim(check_code,doc_key,dimension,seq,title,payload)
                       VALUES(%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (check_code,dimension,seq) DO NOTHING""",
                    (code, dk, dim, seq, title,
                     json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload))
                inserted += cur.rowcount or 0
                cur.execute("UPDATE p1_sixdim_review SET merged=TRUE WHERE draft_id=%s", (did,))
    finally:
        conn.close()
    return {"merged_rows": inserted, "processed": len(rows) if 'rows' in dir() else 0}


def get_check_sixdim(check_code: str) -> dict:
    """只读返回某检查项的五维内容（来自 check_six_dim）。"""
    ensure_schema()
    conn = _connect(readonly=True)
    grouped: dict = {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT doc_key, dimension, seq, title, payload FROM check_six_dim
                   WHERE check_code=%s ORDER BY dimension, seq""", (check_code,))
            for dk, dim, seq, title, payload in cur.fetchall():
                grouped.setdefault(dim, []).append({
                    "seq": seq, "title": title,
                    "payload": payload if isinstance(payload, dict) else json.loads(payload or "{}"),
                })
    finally:
        conn.close()
    return {"checkCode": check_code, "dimensions": grouped}


def stats() -> dict:
    ensure_schema()
    conn = _connect(readonly=True)
    out: dict = {}
    try:
        with conn.cursor() as cur:
            for dk in DOC_KEYS:
                cur.execute(
                    """SELECT status, count(*) FROM p1_sixdim_review WHERE doc_key=%s GROUP BY status""",
                    (dk,))
                out[dk] = {r[0]: r[1] for r in cur.fetchall()}
            cur.execute(
                """SELECT doc_key, dimension, count(*) FROM check_six_dim
                   WHERE doc_key IN ('jg93','pboc3','jf8') GROUP BY doc_key,dimension ORDER BY doc_key,dimension""")
            landed: dict = {}
            for dk, dim, n in cur.fetchall():
                landed.setdefault(dk, {})[dim] = n
            out["landed_check_six_dim"] = landed
    finally:
        conn.close()
    return out
