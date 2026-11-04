# -*- coding: utf-8 -*-
"""platform_tools.py — 平台 MCP 工具（与 HTTP API 共用服务层/DB，口径一致）。"""
from __future__ import annotations
import json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import db  # noqa: E402
from app.services import inspection, ledger, kb_read, db_kb, p1_lawqa, kb_source  # noqa: E402
from app.ontology import graph_backend  # noqa: E402
from app.scenarios.functions import doc93_questionnaire  # noqa: E402


def register(mcp) -> None:
    """向 FastMCP 实例注册全部平台工具。"""

    @mcp.tool()
    def dsec_control_gaps() -> dict:
        """控制需求缺口浏览：35 条已对齐（CT 码）/ 13 条缺口待底座 v1.6 补建。"""
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
                          "rationale": p.get("rationale")})
        gaps = [x for x in all_p if x["status"] != "aligned"]
        return {"total": len(all_p),
                "aligned": sum(1 for x in all_p if x["status"] == "aligned"),
                "pending": sum(1 for x in gaps if x["status"] == "pending_alignment"),
                "gaps": gaps}

    @mcp.tool()
    def dsec_control_alignment() -> dict:
        """全部 48 条控制需求占位及对齐状态（含 CT 码/缺口反馈），供底座工程消费。"""
        with db() as conn:
            rows = conn.execute("SELECT dataJSON FROM entities WHERE type='ControlPlaceholder' "
                                "AND status='published' ORDER BY id").fetchall()
        out = []
        for row in rows:
            p = json.loads(row["dataJSON"])
            out.append({"hint": p.get("controlCodeHint"), "name": p.get("controlName"),
                        "layer": p.get("suggestedLayer"), "type": p.get("controlTypeHint"),
                        "status": p.get("alignmentStatus"), "ctCode": p.get("ctCode"),
                        "ctLayer": p.get("ctLayer"),
                        "baseControlTitle": p.get("baseControlTitle"),
                        "rationale": p.get("rationale")})
        return {"count": len(out), "placeholders": out}

    @mcp.tool()
    def dsec_check_detail(check_code: str) -> dict:
        """监管检查项六维详情（要素/方法/判定/建议控制等）。

        读源纪律（v1.15.1 修复）：六维详情唯一来源=已发布运行台账 SQLite；canonical/db 投影
        仅含标量字段与精简元素，先短路会丢失六维。故 SQLite 命中即返回完整六维，
        仅当 SQLite 未命中（93号文 93-x.y 等仅存本体的检查）才回落 kb_read（db→canonical）。
        """
        # ① SQLite 运行台账（六维详查，唯一完整来源）
        with db() as conn:
            r = conn.execute("SELECT * FROM entities WHERE type='InspectionCheck' AND status='published' "
                             "AND dataJSON LIKE ?", (f'%"checkCode": "{check_code}"%',)).fetchone()
            if r:
                d = json.loads(r["dataJSON"])
                rels = json.loads(r["relationsJSON"])

                def load_ent(eid):
                    er = conn.execute("SELECT dataJSON FROM entities WHERE id=?", (eid,)).fetchone()
                    return json.loads(er["dataJSON"]) if er else None

                sc = []
                for o in rels:
                    if o["p"] == "suggestsControl":
                        p = load_ent(o["o"].split(":", 1)[1])
                        if p:
                            sc.append({"hint": p.get("controlCodeHint"), "name": p.get("controlName"),
                                       "layer": p.get("suggestedLayer"), "status": p.get("alignmentStatus"),
                                       "ctCode": p.get("ctCode"), "ctLayer": p.get("ctLayer")})
                return {"checkCode": d.get("checkCode"), "title": d.get("title"),
                        "domain": d.get("domain"), "priority": d.get("priority"),
                        "regulation": d.get("regulation"), "articleNo": d.get("articleNo"),
                        "citesClause": [o["o"] for o in rels if o["p"] == "citesClause"],
                        "elements": [load_ent(o["o"].split(":", 1)[1]) for o in rels if o["p"] == "hasElement"],
                        "suggestedControls": sc}
        # ② 图/库轨道兜底：仅存于本体的检查（db → canonical 精简形状）
        kb = kb_read.get_check(check_code)
        if kb:
            return {"checkCode": kb.get("checkCode"), "title": kb.get("title"),
                    "domain": kb.get("domain"), "priority": kb.get("priority"),
                    "regulation": kb.get("regulation", ""),
                    "articleNo": kb.get("articleNo", ""),
                    "citesClause": kb.get("citesClause", []),
                    "elements": kb.get("elements", []),
                    "suggestedControls": [],
                    "source": kb.get("source", "canonical")}
        return {"error": f"检查项不存在: {check_code}"}

    @mcp.tool()
    def dsec_create_inspection_run(inspected_target: str, inspector: str,
                                   assignees: str = "") -> dict:
        """创建检查运行（可挂检查计划 planId、多人分工 assignees 逗号分隔）。"""
        return inspection.create_run(inspected_target, inspector, "reviewer",
                                     plan_id="", assignees=[a.strip() for a in assignees.split(",") if a.strip()])

    @mcp.tool()
    def dsec_record_check_result(run_id: str, check_code: str,
                                 elements_json: str = "[]", metrics_json: str = "[]") -> dict:
        """为运行记录某检查项结果（要素 L1/L4 + 度量实际值，阈值由符号引擎判定）。"""
        try:
            elements = json.loads(elements_json)
            metrics = json.loads(metrics_json)
        except json.JSONDecodeError as e:
            return {"error": f"JSON 解析失败: {e}"}
        try:
            return inspection.record_result(run_id, check_code, elements, metrics, "reviewer")
        except ValueError as e:
            return {"error": str(e)}

    @mcp.tool()
    def dsec_inspection_ledger() -> dict:
        """机构检查台账：计划 + 全部运行（结果汇总/证据/签署/下次复查）。"""
        return ledger.get_ledger()

    @mcp.tool()
    def dsec_list_plans() -> dict:
        """检查计划列表（周期/范围/负责人/覆盖检查项）。"""
        return {"plans": ledger.list_plans()}

    @mcp.tool()
    def dsec_graph_backend() -> dict:
        """当前图存储后端与三元组统计（memory/oxigraph/fuseki）。"""
        return {"backend": graph_backend.current_backend(), "stats": graph_backend.stats()}

    @mcp.tool()
    def dsec_graph_sparql(query: str) -> dict:
        """对图存储后端执行标准 SPARQL 只读查询（SELECT/ASK），返回 JSON 行。

        v1.15.0 命名空间 ACL：图存储全只读，非读查询（SPARQL Update）一律拒绝。
        """
        if not query.strip():
            return {"error": "query 必填"}
        try:
            if query.lstrip().upper().startswith("ASK"):
                return {"ask": graph_backend.ask(query)}
            return {"rows": graph_backend.query(query)}
        except ValueError as e:  # 只读 ACL：SPARQL Update 等被拒
            return {"error": str(e)}

    # ---- P1 新增：三路检索 / 四文号检查项 / 93问卷 / 法规带引用问答 ----
    @mcp.tool()
    def dsec_search(query: str, limit: int = 10) -> dict:
        """平台三路融合检索：关键词 ILIKE + 向量(pgvector/TEI) + 图谱(Fuseki/PG) + RAG。
        返回每条命中及其路由来源（keyword/vector/graph/rag）。"""
        if not query.strip():
            return {"error": "query 必填"}
        res = db_kb.fused_search(query, limit=limit)
        return {"query": query, "total": res.get("total"),
                "results": res.get("results", [])}

    @mcp.tool()
    def dsec_checks_by_doc(doc_key: str, limit: int = 50) -> dict:
        """按文号列出检查项：doc_key ∈ jg24/jg93/pboc3/jf8（读 PG inspection_check）。"""
        if doc_key not in ("jg24", "jg93", "pboc3", "jf8"):
            return {"error": "doc_key 仅支持 jg24/jg93/pboc3/jf8"}
        prefix = {"jg93": "93-", "pboc3": "pb3-", "jf8": "jf8-"}.get(doc_key, "")
        items = []
        try:
            import psycopg2
            from app.config import KB_PG_DSN
            conn = psycopg2.connect(KB_PG_DSN, connect_timeout=3)
            cur = conn.cursor()
            if doc_key == "jg24":
                cur.execute(
                    """SELECT check_code,title,domain,priority,article_no FROM inspection_check
                       WHERE check_code NOT LIKE '93-%' AND check_code NOT LIKE 'pb3-%'
                             AND check_code NOT LIKE 'jf8-%' ORDER BY check_code LIMIT %s""",
                    (limit,))
            else:
                cur.execute(
                    """SELECT check_code,title,domain,priority,article_no FROM inspection_check
                       WHERE check_code LIKE %s ORDER BY check_code LIMIT %s""",
                    (prefix + "%", limit))
            for code, title, domain, prio, art in cur.fetchall():
                items.append({"checkCode": code, "title": title, "domain": domain,
                              "priority": prio, "articleNo": art})
            conn.close()
        except Exception as e:  # noqa: BLE001
            return {"error": f"PG 不可达: {e}"}
        return {"docKey": doc_key, "total": len(items), "items": items}

    @mcp.tool()
    def dsec_doc93_questionnaire(supervision_only: bool = False) -> dict:
        """93号文合规自查问卷（139 细项，6大类→22小类），只读 PG 投影。"""
        return doc93_questionnaire.run({"supervisionOnly": supervision_only})

    @mcp.tool()
    def dsec_law_qa(query: str, limit: int = 5) -> dict:
        """法规原文带引用问答（TEI+pgvector）：返回 top-N 条款片段与文号/条号引用。"""
        if not query.strip():
            return {"error": "query 必填"}
        return p1_lawqa.search(query, limit=limit)

    # ---- v1.16.0 统一知识取数（kb_source 适配器：实时知识库优先 + 多源降级）----
    @mcp.tool()
    def dsec_kb_get(check_code: str) -> dict:
        """按检查项编号取实时六维详情（知识库平台覆盖 + 结构化投影/运行台账底座）。

        统一信封：{content, source, fetchedAt}；source 说明本次数据来自哪一级
        （weknora/canonical/db/sqlite 的组合）。六维恒为完整形状，不会出现 undefined/空白。
        """
        env = kb_source.fetch_check(check_code)
        if not env or env.get("content") is None:
            return {"error": f"检查项不存在: {check_code}"}
        return env

    @mcp.tool()
    def dsec_kb_search(query: str, limit: int = 20) -> dict:
        """融合检索（关键词/向量/图谱/RAG + 知识库实时向量路），带来源标注。"""
        if not query.strip():
            return {"error": "query 必填"}
        return kb_source.fetch_search(query, limit=limit)

    @mcp.tool()
    def dsec_kb_wiki(page_id: str = "", limit: int = 200) -> dict:
        """读知识库平台 Wiki：给定 page_id/精确标题读整页正文；留空返回页面目录。

        统一信封：{content, source, fetchedAt, version?}。
        """
        if page_id.strip():
            env = kb_source.fetch_wiki(page_id.strip())
            if not env or env.get("content") is None:
                return {"error": f"知识页面不存在: {page_id}"}
            return env
        return kb_source.fetch_wiki_index(limit)
