"""多人检查台账与周期复查 demo（端到端，退出码反映断言）。
故事：年度检查计划（季度周期）→ 首轮检查多人分工（主查+协查）→ 1.1 未达+证据缺失 → fail
→ 归档证据 → 复核退回 → 周期复查轮次补证后 pass → 复核通过 → 台账沉淀下次复查日期。
"""
from __future__ import annotations
import sys, os, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import seed  # noqa: E402
from app.ontology import checks_import  # noqa: E402
from app.services import inspection, ledger  # noqa: E402


def _assert(cond, msg):
    if cond:
        print(f"  [PASS] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        sys.exit(1)


def run():
    print("=" * 60)
    print("[demo-ledger] 多人检查台账与周期复查")
    print("=" * 60)
    seed.seed()
    checks_import.import_checks()

    # 1) 检查计划（季度周期）
    pl = ledger.create_plan("2026年数据安全检查计划", "总行本级+核心系统",
                            cycle="quarterly", start_date="2026-01-01", end_date="2026-12-31",
                            owner="王合规", checks=["1.1", "1.2", "15.5"], actor="reviewer")
    pid = pl["planId"]
    print(f"[step1] 创建检查计划 {pid}（季度周期）")
    _assert(pl["planId"], "计划已创建")

    # 2) 首轮运行：多人分工（主查 张某 + 协查 张三/李四）
    r1 = inspection.create_run("演示银行（总行本级）", "合规部·张某", "reviewer",
                               plan_id=pid, assignees=["张三", "李四"])["runId"]
    print(f"[step2] 首轮运行 {r1}（主查张某+协查张三/李四）")
    res1 = inspection.record_result(
        r1, "1.1",
        element_inputs=[
            {"code": "1.1.1", "l1_ok": True, "l4_evidence": "provided", "note": "总纲已写主体责任"},
            {"code": "1.1.3", "l1_ok": True, "l4_evidence": "missing", "note": "无近12月会议纪要"},
        ],
        metric_inputs=[{"metricId": "m1", "threshold": "≥1 次/年", "actual": 0}],
        actor="reviewer")
    _assert(res1["result"] == "fail", "1.1 首轮 fail（缺证据+阈值未达）")
    rd = inspection.get_run(r1)
    _assert(rd["planId"] == pid and "张三" in rd["assignees"] and "李四" in rd["assignees"],
            "运行已挂计划 + 多人分工可见")

    # 3) 证据归档
    ev_dir = os.path.join(ROOT, "app", "data", "evidence_uploads")
    os.makedirs(ev_dir, exist_ok=True)
    sample = os.path.join(ev_dir, "2026Q1_数据安全委员会会议纪要.md")
    with open(sample, "w", encoding="utf-8") as f:
        f.write("# 2026Q1 数据安全委员会会议纪要\n- 议题：党委数据安全主体责任审议\n- 结论：通过\n")
    ev = ledger.attach_evidence(r1, "1.1", os.path.basename(sample), sample,
                                "张三", "近12月党委会审议纪要（补证）")
    print(f"[step3] 归档证据 {ev['evidenceId']}（{ev['fileName']}）")
    _assert(ledger.list_evidence(r1)[0]["evidenceId"] == ev["evidenceId"], "证据已归档可查")

    # 4) 首轮复核退回（证据口径仍需补 L4 要素）
    sg1 = ledger.sign_off(r1, "李四", "复核", "returned", "会议纪要需在检查要素 1.1.3 标记为已提供", "reviewer")
    _assert(sg1["decision"] == "returned", "复核退回（缺证）")

    # 5) 周期复查轮次：补证后 1.1 转 pass，复核通过
    r2 = inspection.create_run("演示银行（总行本级）", "合规部·张某", "reviewer",
                               plan_id=pid, assignees=["张三", "王合规"])["runId"]
    print(f"[step5] 复查轮次 {r2}")
    res2 = inspection.record_result(
        r2, "1.1",
        element_inputs=[
            {"code": "1.1.1", "l1_ok": True, "l4_evidence": "provided", "note": "总纲主体责任条款"},
            {"code": "1.1.3", "l1_ok": True, "l4_evidence": "provided", "note": "2026-03 董事会纪要已归档"},
        ],
        metric_inputs=[{"metricId": "m1", "threshold": "≥1 次/年", "actual": 2}],
        actor="reviewer")
    _assert(res2["result"] == "pass", "复查轮次 1.1 转 pass")
    ledger.sign_off(r2, "赵审批", "审批", "approved", "证据齐备，复核通过", "reviewer")

    # 6) 台账聚合与周期复查日期
    lg = ledger.get_ledger()
    entries = {e["runId"]: e for e in lg["entries"]}
    _assert(len(entries) >= 2 and all(e["planName"] == "2026年数据安全检查计划" for e in entries.values()),
            "台账含 2 条计划内运行")
    _assert(entries[r1]["results"]["fail"] == 1 and entries[r2]["results"]["pass"] == 1,
            "台账结果汇总正确（r1 fail / r2 pass）")
    _assert(entries[r1]["evidenceCount"] == 1, "台账证据计数正确")
    _assert(entries[r1]["signoff"]["decision"] == "returned" and entries[r2]["signoff"]["decision"] == "approved",
            "台账签署状态正确（退回/通过）")
    plan = next(p for p in lg["plans"] if p["id"] == pid)
    expect = (max(datetime.datetime.fromisoformat(e["ranAt"]) for e in entries.values())
              + datetime.timedelta(days=90)).strftime("%Y-%m-%d")
    print(f"[step6] 下次复查（最近运行 +90 天）= {plan['nextRecheck']}")
    _assert(plan["nextRecheck"] == expect, "周期复查日期 = 最近运行 + 90 天")

    print("=" * 60)
    print("[demo-ledger] 全部断言通过 ✅")
    print("=" * 60)


if __name__ == "__main__":
    run()
