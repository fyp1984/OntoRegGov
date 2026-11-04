"""场景框架端到端 demo（任务线3，退出码反映断言）。

与 scripts/demo_checks.py 同风格（无 LLM、退出码断言），但全程走 8420 HTTP，
把"配置驱动场景框架"的新 API 一并跑通：
  1) GET /api/scenarios → 两个组件（sc01 + sc02 纯配置注册实证）
  2) 金规 P0 选 1.1（党委主体责任）首次 L4 证据缺失 + L5 阈值未达 → fail + 自动缺口提案
  3) 整改（提案决策 accepted）→ 复检 → pass，compare 可见 fail→pass
  4) POST /api/scenarios/sc01/functions/doc93_questionnaire → 139 项分组统计
  5) POST /api/scenarios/sc01/functions/report_export → 生成 HTML+MD 报告
数据来自本体/平台，不写死检查项标题（标题从 why.checkTitle 取）。

前置：8420 已用新代码重启（/api/scenarios 已挂）。
"""
from __future__ import annotations
import sys, json, urllib.request, urllib.error

BASE = "http://127.0.0.1:8420"
SC01 = "sc01-selfcheck-reception"
PASS = 0


def _req(method: str, path: str, body=None):
    url = BASE + path
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _assert(cond, msg):
    global PASS
    if cond:
        print(f"  [PASS] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        sys.exit(1)


def run():
    print("=" * 64)
    print("[demo-scenario] 配置驱动场景框架 · 首场景闭环 e2e")
    print("=" * 64)

    # 0) 健康 + 注册表
    st, h = _req("GET", "/api/health")
    _assert(st == 200 and h.get("status") == "ok", "8420 health 200")
    st, reg = _req("GET", "/api/scenarios")
    ids = [c["id"] for c in reg.get("components", [])]
    print(f"[setup] 注册表组件: {ids}")
    _assert(st == 200 and "sc01-selfcheck-reception" in ids and "sc02-supervisory-inspection" in ids,
            "注册表含 sc01 + sc02 两组件")
    st, sc02 = _req("GET", "/api/scenarios/sc02-supervisory-inspection")
    _assert(st == 200 and sc02.get("functions", [{}])[0].get("id") == "report_export",
            "sc02 纯配置注册（仅复用 report_export，无新增函数）")

    # 1) 金规 1.1 首次运行：L4 证据缺失 + L5 阈值(≥1次/年)实际=0 → fail + 自动提案
    st, r1 = _req("POST", "/api/inspection/runs",
                  {"inspectedTarget": "演示银行（总行本级）", "inspector": "合规部·张某", "actor": "reviewer"})
    rid1 = r1["runId"]
    print(f"[step1] 创建整改前运行 {rid1}")
    st, res1 = _req("POST", f"/api/inspection/runs/{rid1}/results", {
        "checkCode": "1.1",
        "elements": [
            {"code": "1.1.1", "l1_ok": True, "l4_evidence": "missing", "note": "总纲已写主体责任"},
            {"code": "1.1.3", "l1_ok": True, "l4_evidence": "missing", "note": "无近12月会议纪要"},
        ],
        "metrics": [{"metricId": "审议次数", "threshold": "≥1 次/年", "actual": 0}],
        "actor": "reviewer"})
    title1 = (res1.get("why") or {}).get("checkTitle")
    print(f"[step2] 1.1 首次结果={res1['result']} 提案={res1.get('proposalId')} 标题=「{title1}」")
    _assert(res1["result"] == "fail", "1.1 首次为 fail（缺证据+阈值未达）")
    _assert(res1.get("proposalId"), "fail 自动生成知识缺口提案")
    _assert(title1 and "党委" in title1, "检查项标题来自本体 why.checkTitle（非硬编码）")
    pid = res1["proposalId"]

    # 2) 整改：提案决策 accepted（专家补全证据要求）
    st, dec = _req("POST", f"/api/proposals/{pid}/decision",
                   {"actor": "admin", "decision": "accepted", "note": "补会议纪要证据要求"})
    print(f"[step3] 提案 {pid} 决策 → {dec.get('status')}")
    _assert(dec.get("status") == "accepted", "缺口提案被专家接受")

    # 3) 复检：补证据(provided)+阈值实际=2 → pass
    st, r2 = _req("POST", "/api/inspection/runs",
                  {"inspectedTarget": "演示银行（总行本级）", "inspector": "合规部·张某", "actor": "reviewer"})
    rid2 = r2["runId"]
    st, res2 = _req("POST", f"/api/inspection/runs/{rid2}/results", {
        "checkCode": "1.1",
        "elements": [
            {"code": "1.1.1", "l1_ok": True, "l4_evidence": "provided", "note": "总纲主体责任条款"},
            {"code": "1.1.3", "l1_ok": True, "l4_evidence": "provided", "note": "2026-03 董事会纪要已归档"},
        ],
        "metrics": [{"metricId": "审议次数", "threshold": "≥1 次/年", "actual": 2}],
        "actor": "reviewer"})
    print(f"[step4] 1.1 复检结果={res2['result']}")
    _assert(res2["result"] == "pass", "1.1 补全后转 pass")

    # 4) compare：fail→pass 可见
    st, cmp = _req("GET", f"/api/inspection/runs/{rid1}/compare/{rid2}")
    ch = [c for c in cmp.get("changes", []) if c["checkCode"] == "1.1"]
    print(f"[step5] compare 总评 {cmp.get('overallBefore')} → {cmp.get('overallAfter')}；1.1 变化={ch}")
    _assert(ch and ch[0]["before"] == "fail" and ch[0]["after"] == "pass", "闭环：1.1 fail→pass 可见")

    # 5) 93号文问卷装载（场景函数）
    st, qz = _req("POST", f"/api/scenarios/{SC01}/functions/doc93_questionnaire", {})
    print(f"[step6] doc93_questionnaire ok={qz.get('ok')} total={qz.get('total')} "
          f"大类={qz.get('categoryCount')} 小类={qz.get('problemTypeCount')}")
    _assert(qz.get("ok") is True and qz.get("total") == 139, "93号文问卷装载 139 项")
    _assert(qz.get("categoryCount") == 6 and qz.get("problemTypeCount") == 22,
            "93号文 6 大类 / 22 小类分组统计")

    # 6) 报告导出（场景函数）：HTML+MD
    st, rep = _req("POST", f"/api/scenarios/{SC01}/functions/report_export", {
        "runIds": [rid1, rid2], "reportType": "selfcheck",
        "title": "首场景闭环演示报告", "actor": "reviewer"})
    print(f"[step7] report_export ok={rep.get('ok')} stats={rep.get('stats')}")
    _assert(rep.get("ok") is True, "report_export 成功")
    _assert(rep.get("html") and "<html" in rep["html"][:200].lower(), "产出 HTML 报告")
    _assert(rep.get("markdown") and "# 首场景闭环演示报告" in rep["markdown"], "产出 Markdown 报告")
    _assert(rep.get("stats", {}).get("hasCompare") is True, "报告含复检对比（fail→pass）")
    _assert(rep.get("stats", {}).get("fail", 0) >= 1, "报告含整改前不符合项")

    print("=" * 64)
    print("[demo-scenario] 全部断言通过 ✅")
    print("=" * 64)


if __name__ == "__main__":
    run()
