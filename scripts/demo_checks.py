"""监管检查纵切 demo（端到端，退出码反映断言）。
复用既有 assessment/proposal/review/version/audit；符号引擎聚合，无 LLM。
故事：1.1 党委主体责任 首次 fail（缺审议证据 + 阈值未达）→ 缺口提案 → 专家补全 → 重检 pass。
"""
from __future__ import annotations
import sys, os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import seed  # noqa: E402
from app.ontology import checks_import  # noqa: E402
from app.services import inspection, proposal as proposal_svc, audit  # noqa: E402

PASS = 0


def _assert(cond, msg):
    global PASS
    if cond:
        print(f"  [PASS] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        sys.exit(1)


def run():
    print("=" * 60)
    print("[demo-checks] 金规24号监管检查纵切")
    print("=" * 60)
    seed.seed()
    s = checks_import.import_checks()
    print(f"[setup] 导入检查项 {s['checks']} / 要素 {s['elements']} / 补建法条 {s['clauses_created']}")
    _assert(s["checks"] == 116, "导入 116 项检查")

    # 选 P0：1.1 党委主体责任 / 1.2 责任人 / 15.5 tech 敏感数据操作日志
    r1 = inspection.create_run("演示银行（总行本级）", "合规部·张某", "reviewer")["runId"]
    print(f"[step1] 创建检查运行 {r1}")

    # 1.1 首次：制度有(L1 ok)，但近12月无审议纪要(L4 missing)，阈值 ≥1次/年 实际=0 → fail
    res1 = inspection.record_result(
        r1, "1.1",
        element_inputs=[
            {"code": "1.1.1", "l1_ok": True, "l4_evidence": "missing", "note": "总纲已写主体责任"},
            {"code": "1.1.3", "l1_ok": True, "l4_evidence": "missing", "note": "无近12月会议纪要"},
        ],
        metric_inputs=[
            {"metricId": "m1", "threshold": "≥1 次/年", "actual": 0},
        ],
        actor="reviewer")
    print(f"[step2] 1.1 首次结果 = {res1['result']}，提案 = {res1['proposalId']}")
    _assert(res1["result"] == "fail", "1.1 首次为 fail（缺证据+阈值未达）")
    _assert(res1["proposalId"], "自动生成知识缺口提案（EvidenceRequirement）")
    pid = res1["proposalId"]

    # 1.2 / 15.5 本次直接合格
    inspection.record_result(r1, "1.2",
        [{"code": "1.2.1", "l1_ok": True, "l4_evidence": "provided"}],
        [{"metricId": "m1", "threshold": "≥1", "actual": 1}], "reviewer")
    inspection.record_result(r1, "15.5",
        [{"code": "15.5.1", "l1_ok": True, "l4_evidence": "provided"}],
        [{"metricId": "m1", "threshold": "≥180 天", "actual": 180}], "reviewer")

    # 专家接受提案（复用既有提案表与审核），补一条证据要求模板
    print(f"[step3] 专家接受提案 {pid}，补证据模板")
    acc = proposal_svc.decide(pid, "admin", "accepted", "补会议纪要证据要求")
    _assert(acc["status"] == "accepted", "提案被专家接受")

    # 第二次运行：补齐审议纪要(provided)、阈值实际=2 → 1.1 转 pass
    r2 = inspection.create_run("演示银行（总行本级）", "合规部·张某", "reviewer")["runId"]
    res1b = inspection.record_result(
        r2, "1.1",
        element_inputs=[
            {"code": "1.1.1", "l1_ok": True, "l4_evidence": "provided", "note": "总纲主体责任条款"},
            {"code": "1.1.3", "l1_ok": True, "l4_evidence": "provided", "note": "2026-03 董事会纪要已归档"},
        ],
        metric_inputs=[
            {"metricId": "m1", "threshold": "≥1 次/年", "actual": 2},
        ],
        actor="reviewer")
    inspection.record_result(r2, "1.2",
        [{"code": "1.2.1", "l1_ok": True, "l4_evidence": "provided"}],
        [{"metricId": "m1", "threshold": "≥1", "actual": 1}], "reviewer")
    inspection.record_result(r2, "15.5",
        [{"code": "15.5.1", "l1_ok": True, "l4_evidence": "provided"}],
        [{"metricId": "m1", "threshold": "≥180 天", "actual": 180}], "reviewer")
    print(f"[step4] 1.1 重检结果 = {res1b['result']}")
    _assert(res1b["result"] == "pass", "1.1 补全后转 pass")

    cmp = inspection.compare(r1, r2)
    ch = [c for c in cmp["changes"] if c["checkCode"] == "1.1"][0]
    print(f"[compare] 1.1: {ch['before']} → {ch['after']}；总评 {cmp['overallBefore']} → {cmp['overallAfter']}")
    _assert(ch["before"] == "fail" and ch["after"] == "pass", "闭环：fail → pass 可见")

    print("=" * 60)
    print("[demo-checks] 全部断言通过 ✅")
    print("=" * 60)


if __name__ == "__main__":
    run()
