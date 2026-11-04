"""端到端闭环演示：种子→抽取→审核→首次评估(裸义务缺口)→提案→补控→再评估→导出。
退出码 0=全绿，1=断言失败。运行: python scripts/demo_e2e.py 或 python -m app.cli demo
"""
import sys, os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import seed  # noqa: E402
from app.db import db  # noqa: E402
from app.services import (extractor_rule, review, assessment, proposal,  # noqa: E402
                           audit)
from app.ontology import graph_store  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name} {extra}")
    if not cond:
        FAILS.append(name)


def run():
    print("=" * 64)
    print("步骤1: 初始化种子")
    seed.seed()

    print("=" * 64)
    print("步骤2: 导入 samples 文档并规则抽取")
    sample = os.path.join(ROOT, "samples", "新规片段-数据分类分级.md")
    text = open(sample, encoding="utf-8").read()
    cands = extractor_rule.extract(text, "doc-demo")
    check("抽取候选非空", len(cands) > 0, f"({len(cands)} 条)")
    check("候选含 provenance", all("provenance" in c for c in cands))
    check("候选含 span 出处片段", all(c.get("span") for c in cands))
    check("候选含 confidence", all("confidence" in c for c in cands))
    ob_cands = [c for c in cands if c["kind"] == "Obligation"]
    check("抽取到义务候选(应当/必须)", len(ob_cands) > 0, f"({len(ob_cands)} 条)")

    print("=" * 64)
    print("步骤3: reviewer 批准一条义务候选并生成版本（演示人工复核→发布）")
    c0 = ob_cands[0]
    # 先落库候选（独立连接）
    import datetime, hashlib
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO candidates(id,documentId,kind,label,mappedClass,confidence,provenance,span,payloadJSON,status,createdBy,createdAt) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (c0["id"], "doc-demo", c0["kind"], c0["label"], c0["mappedClass"], c0["confidence"],
             c0["provenance"], c0["span"], json.dumps(c0.get("payload", {}), ensure_ascii=False),
             "new", "editor", datetime.datetime.now().isoformat(timespec="seconds")))
    # 建复核任务并由 reviewer 批准（各自管理连接，不嵌套）
    from app.services.review import create_entity, decide
    res = create_entity("Obligation", "ob-demo-x",
                        {"code": "ob-demo-x", "text": c0["payload"].get("text", c0["label"]),
                         "force": "mandatory", "clauseOf": "Clause:cl-16"},
                        [], actor="editor", source="candidate")
    tid = res["reviewTaskId"]
    dec = decide(tid, "reviewer", "approved", note="演示复核通过")
    check("审核批准产生新版本", dec.get("version", 0) >= 1, f"(version={dec.get('version')})")

    print("=" * 64)
    print("步骤4: 客户信息库 首次评估（应存在裸义务 O6=§19 无控制 → unknown + 1 提案）")
    a1 = assessment.run_assessment("asset-customer-db", actor="reviewer")
    unknown_items = [i for i in a1["checkItems"] if i["result"] == "unknown"]
    gap_obs = [i["obligationCode"] for i in unknown_items]
    check("存在 unknown 检查项", len(unknown_items) >= 1, f"({gap_obs})")
    check("裸义务为 O6(§19)", "ob-o6" in gap_obs)
    check("自动生成知识缺口提案", len(a1["proposals"]) == 1, f"({len(a1['proposals'])} 个)")
    check("首次总评为 partial", a1["overall"] == "partial", f"(overall={a1['overall']})")
    run_before = a1["runId"]
    prop_id = a1["proposals"][0]["id"]

    print("=" * 64)
    print("步骤5: 接受提案→补控制项 C7+证据要求 E7→为资产补证据→入库")
    payload = {
        "newControl": {
            "id": "ctrl-c7",
            "data": {"code": "ctrl-c7", "title": "数据安全级别动态调整审批机制",
                     "priority": "P0", "controlKind": "preventive",
                     "judgementCriteria": "查记录：级别不适用时是否经审批动态调整",
                     "method": "查系统/查审批流",
                     "implementsObligation": ["Obligation:ob-o6"],
                     "requiresEvidence": ["EvidenceRequirement:er-e7"]},
            "relations": [{"p": "implementsObligation", "o": "Obligation:ob-o6"},
                          {"p": "requiresEvidence", "o": "EvidenceRequirement:er-e7"}],
        },
        "newEvidenceRequirement": {
            "id": "er-e7",
            "data": {"code": "er-e7", "name": "级别动态调整审批记录", "evidenceKind": "system_log"},
            "relations": [],
        },
    }
    # 把完整补控载荷写回自动提案（auto 提案最初仅含 obligation 引用）
    from app.db import db as _db
    with _db() as conn:
        conn.execute("UPDATE proposals SET payloadJSON=? WHERE id=?",
                     (json.dumps(payload, ensure_ascii=False), prop_id))
    paccept = proposal.decide(prop_id, "reviewer", "accepted", note="补控制规则")
    check("提案 accepted", paccept["status"] == "accepted")
    created_tasks = paccept["created"]
    # reviewer 批准这些由 admin 补录的候选（角色分离：createdBy=admin ≠ reviewer）
    from app.db import db as _db
    approved_versions = []
    for ct in created_tasks:
        # 找到该实体的 pending review task
        with _db() as conn:
            row = conn.execute("SELECT id FROM review_tasks WHERE targetId=? AND status='pending_review'",
                               (ct["id"],)).fetchone()
        d = review.decide(row["id"], "reviewer", "approved", note="补控入库")
        approved_versions.append(d.get("version"))
    check("补控实体全部过 SHACL 入库", len(approved_versions) == 2, f"(versions={approved_versions})")

    # 为资产补一条 provided 证据记录（admin 补录 → reviewer 批准）
    from app.services.review import create_entity, decide
    rec_res = create_entity(
        "EvidenceRecord", "rec-a1-e7",
        {"recordId": "rec-a1-e7", "name": "级别动态调整审批记录", "status": "provided",
         "collectedAt": "2026-09-15", "locator": "审批流/rec-a1-e7.pdf",
         "asset": "asset-customer-db",
         "evidencesControl": "Control:ctrl-c7",
         "fulfillsRequirement": "EvidenceRequirement:er-e7"},
        [{"p": "evidencesControl", "o": "Control:ctrl-c7"},
         {"p": "fulfillsRequirement", "o": "EvidenceRequirement:er-e7"}],
        actor="admin", source="manual")
    rec_dec = decide(rec_res["reviewTaskId"], "reviewer", "approved", note="补证据")
    check("补证据记录入库", rec_dec.get("version", 0) >= 1)

    print("=" * 64)
    print("步骤6: 第二次评估（O6 应从 unknown→conform，总评 partial→compliant）")
    a2 = assessment.run_assessment("asset-customer-db", actor="reviewer")
    run_after = a2["runId"]
    after_by_obs = {i["obligationCode"]: i["result"] for i in a2["checkItems"]}
    check("O6 由 unknown 变为 conform", after_by_obs.get("ob-o6") == "conform",
          f"(ob-o6={after_by_obs.get('ob-o6')})")
    check("二次总评为 compliant", a2["overall"] == "compliant", f"(overall={a2['overall']})")
    check("总评改善", a1["overall"] != a2["overall"])

    print("=" * 64)
    print("步骤7: 导出 turtle 并可解析")
    ttl = graph_store.export_turtle()
    from rdflib import Graph
    g = Graph(); g.parse(data=ttl, format="turtle")
    check("turtle 可解析", len(g) > 0, f"({len(g)} 三元组)")
    check("turtle 含 Obligation 类", any("Obligation" in str(t) for t in g[:]))

    print("=" * 64)
    print("闭环前后对比：")
    cmp = assessment.compare(run_before, run_after)
    print(json.dumps(cmp, ensure_ascii=False, indent=2))

    print("=" * 64)
    if FAILS:
        print(f"[demo_e2e] 失败 {len(FAILS)} 项: {FAILS}")
        sys.exit(1)
    print("[demo_e2e] 全部断言通过 ✅")
    sys.exit(0)


if __name__ == "__main__":
    run()
