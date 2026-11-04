#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阈值解析器回归测试：覆盖 v1.2.1 泛化后的全部形态。
退出码 0 = 全部断言通过。运行：python scripts/test_thresholds.py
"""
from __future__ import annotations
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.services.inspection import eval_threshold  # noqa: E402

CASES = [
    # (threshold, actual, expected_status, 说明)
    # --- 存在性 ---
    ("已列入（有即合格）", "有", "pass", "存在性·有"),
    ("有即合格", "无", "fail", "存在性·无"),
    ("有记录即合格", "有记录", "pass", "存在性·有记录"),
    ("无即不合格", "有", "pass", "存在性·取反-有"),
    ("无即不合格", "无", "fail", "存在性·取反-无"),
    # --- 分数 ---
    ("4/4 层均有运作证据", "4/4", "pass", "分数·4/4"),
    ("4/4 层均有运作证据", "100", "pass", "分数·实际百分比100"),
    ("4/4 层均有运作证据", "75", "fail", "分数·实际百分比75"),
    ("3/3 全覆盖", "3/3", "pass", "分数·3/3"),
    ("3/3 全覆盖", "2/3", "fail", "分数·2/3"),
    # --- 抽样比例 ---
    ("抽查 5 项，≥4 项目录与实际一致", "4", "pass", "抽样·个数命中"),
    ("抽查 5 项，≥4 项目录与实际一致", "3", "fail", "抽样·个数未达"),
    ("抽查 5 项，≥4 项目录与实际一致", "80%", "pass", "抽样·百分比达"),
    ("抽查 5 项，≥4 项目录与实际一致", "50%", "fail", "抽样·百分比未达"),
    # --- 全覆盖 / 100% ---
    ("100%（核心条线全覆盖）", "100", "pass", "全覆盖·100"),
    ("100%（核心条线全覆盖）", "98", "fail", "全覆盖·98"),
    ("核心系统全覆盖", "100", "pass", "全覆盖·字样"),
    # --- 零 ---
    ("高风险项 0 件超期", "0", "pass", "零·0件"),
    ("近12个月零超范围收集事件", "1", "fail", "零·事件1"),
    ("0 条（或已标注\"已下线\"状态）", "0", "pass", "零·0条"),
    # --- 中文比较词 ---
    ("金规24号核心条款覆盖率≥90%", "92", "pass", "嵌句·≥90"),
    ("金规24号核心条款覆盖率≥90%", "88", "fail", "嵌句·≥90未达"),
    ("不低于 80%", "80", "pass", "中文·不低于"),
    ("不低于 80%", "79", "fail", "中文·不低于未达"),
    ("数据服务请求平均响应时间≤2个工作日", "1", "pass", "中文·≤2"),
    ("数据服务请求平均响应时间≤2个工作日", "3", "fail", "中文·≤2未达"),
    ("总体 不少于 12 次", "12", "pass", "中文·不少于"),
    ("总体 不少于 12 次", "11", "fail", "中文·不少于未达"),
    ("达到 95%", "95", "pass", "中文·达到"),
    ("超过 3 次", "3", "fail", "中文·超过(严格大于)"),
    ("超过 3 次", "4", "pass", "中文·超过(严格大于)"),
    # --- 符号比较（保持原能力）---
    ("≥1 次/年", "2", "pass", "符号·≥1"),
    ("≥1 次/年", "0", "fail", "符号·≥1未达"),
    ("≥180 天", "180", "pass", "符号·≥180"),
    ("<5", "4", "pass", "符号·<5"),
    ("<5", "5", "fail", "符号·<5边界"),
    ("=100%", "100", "pass", "符号·=100"),
    # --- 中文频次 ---
    ("至少每季度一次", "1", "pass", "频次·至少每季度一次"),
    ("不少于2次", "2", "pass", "频次·不少于2次"),
    ("不少于2次", "1", "fail", "频次·不少于2次未达"),
    ("每年至少 1 次", "1", "pass", "频次·每年至少1次(阿拉伯)"),
    # --- 多目标 / 定性 → manual ---
    ("核心系统 100%，总体 ≥80%", "85", "manual", "多目标并存→manual"),
    ("敏感级以上数据传输加密率100%，存储加密率≥80%", "90", "manual", "多目标并存→manual"),
    ("抽查人员均能说出自己的数据安全职责要点", "是", "manual", "纯定性→manual"),
    ("有议题且有决议", "有", "manual", "复合定性→manual"),
    ("≥季度", "2", "manual", "裸频次词→manual"),
    ("有预算且有执行（非零支出）", "有", "manual", "复合定性→manual"),
    # --- missing ---
    ("≥1 次/年", "", "missing", "未采集"),
    ("有即合格", None, "missing", "未采集"),
]


def run():
    fails = 0
    for th, actual, expect, note in CASES:
        r = eval_threshold(th, actual)
        ok = r["status"] == expect
        tag = "PASS" if ok else "FAIL"
        if not ok:
            fails += 1
        print(f"  [{tag}] {note:<22} 阈值={th!r:<42} actual={actual!r:<6} → {r['status']} (期望 {expect})")
    print("=" * 70)
    if fails:
        print(f"[FAIL] {fails}/{len(CASES)} 用例未通过")
        sys.exit(1)
    print(f"[PASS] 全部 {len(CASES)} 用例通过 ✅")
    # 覆盖率统计（针对 jg24-checks.json 全量 342 条度量）
    import json
    data = json.load(open(os.path.join(ROOT, "data", "checks", "jg24-checks.json"), encoding="utf-8"))
    ths = []
    for c in data["checks"]:
        for m in (c.get("method") or {}).get("metrics", []):
            if m.get("threshold"):
                ths.append(m["threshold"])
    parsed = sum(1 for t in ths if eval_threshold(t, 100).get("parsed"))
    # 用 actual=100 粗估"可解析形态"占比（真实判定仍需实际值）
    print(f"[STATS] 342 条度量阈值形态：粗解析率(actual=100 时 parsed) = {parsed}/{len(ths)} ({parsed/len(ths)*100:.1f}%)")


if __name__ == "__main__":
    run()
