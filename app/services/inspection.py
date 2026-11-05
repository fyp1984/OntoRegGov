"""监管检查运行层：InspectionRun / CheckResult 的确定性聚合（符号引擎，无 LLM）。
复用既有 proposals / review / versioning / audit。判定口径为依据原文的演示性确定性落地。
"""
from __future__ import annotations
import json, re, uuid, datetime
from ..db import db
from . import proposal as proposal_svc
from . import audit, versioning
from . import run_db


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _pub(conn, eid, etype, data, relations=None):
    relations = relations or []
    conn.execute(
        "INSERT OR REPLACE INTO entities(id,type,status,currentVersion,dataJSON,relationsJSON,updatedAt,updatedBy) VALUES(?,?,?,?,?,?,?,?)",
        (eid, etype, "published", 1, json.dumps(data, ensure_ascii=False),
         json.dumps(relations, ensure_ascii=False), _now(), "inspection"))


# ---------------- 阈值解析器（确定性符号解析；解析不了 → manual 缺口信号，不假装能算）----------------
# v1.2.1 泛化支持形态（判定口径均可在 test_thresholds.py 复现）：
#   1) 存在性：有即合格/已列入/有即视为合格/存在即合格/有记录即合格；无即不合格/未见即不合格（取反语义）
#   2) 分数 N/M：4/4、3/3 → 需求比例 N/M（actual 可为分数串或百分比数）
#   3) 抽样比例："抽查 5 项，≥4 项…" → 需求 ≥4/5（actual 为个数按 ≥M，为百分比按 ≥M/N*100）
#   4) 全覆盖 / 100% → =100
#   5) 零 / 0 条/件/项 → =0
#   6) 中文/符号比较词 + 数字[+单位]（可嵌句中）：不低于/不少于/至少/达到/以上/≥/>= → >=；
#      超过/高于/大于/> → >；不超过/至多/以下/≤/<= → <=；低于/小于/< → <；等于/= → =
#   7) 中文频次：至少每季度一次 / 不少于2次 → ≥N
#   多目标并存（如"核心100%，总体≥80%"）或纯定性句（如"抽查人员能说出…"）→ manual，不强行判定。

_CN_NUM = {"一":1,"二":2,"两":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10}
_HAS_MARK = re.compile(r"有即合格|已列入|有即视为合格|存在即合格|有记录即合格|已建立且有记录")
_NO_MARK = re.compile(r"无即不合格|未见即不合格|未列入即不合格")
_OP_WORDS = r"不低于|不少于|至少|达到|超过|高于|大于|不超过|至多|低于|小于|等于|以上|以下"
_CMP_RE = re.compile(rf"({_OP_WORDS}|>=|≥|<=|≤|>|<|=)\s*([0-9]+(?:\.[0-9]+)?)")
_CN_FREQ_RE = re.compile(r"(至少|不低于|不少于|≥|>=)\s*(?:每(?:季度|年|月|周|日))?\s*([一两二三四五六七八九十]+)\s*次")
_FRAC_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_SAMPLE_RE = re.compile(r"(\d+)\s*[项条件个]\D{0,8}(?:≥|>=|不少于|至少)\s*(\d+)\s*[项条件个]")
_ZERO_RE = re.compile(r"零|0\s*(?:条|件|项|个)")
# 全覆盖目标：全覆盖/全部…字样，或 "100%"（前面不是比较符，避免与 =100%/≥100% 重复计数）
_FULL_RE = re.compile(r"全覆盖|全部(?:纳入|覆盖|具备)|(?:^|[^0-9<>=≤≥])100\s*%")

_OP_MAP = {"不低于": ">=", "不少于": ">=", "至少": ">=", "达到": ">=", "以上": ">=", ">=": ">=", "≥": ">=",
           "超过": ">", "高于": ">", "大于": ">", ">": ">",
           "不超过": "<=", "至多": "<=", "以下": "<=", "<=": "<=", "≤": "<=",
           "低于": "<", "小于": "<", "<": "<",
           "等于": "=", "=": "="}


def _norm_threshold(t: str) -> str:
    t = (t or "").replace("％", "%")
    t = t.replace("：", ":").replace("，", ",").replace("。", ".")
    return re.sub(r"\s+", " ", t).strip()


def _as_float(a: str):
    try:
        return float(a)
    except (ValueError, TypeError):
        return None


def _as_ratio(a: str) -> float | None:
    """actual 转比例：'4/4'→1.0；'80%'→0.8；纯数字按百分比（分数阈值语境，如 4/4 需 ≥100）。"""
    s = a.strip().rstrip("%")
    m = re.match(r"^(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)$", s)
    if m:
        den = float(m.group(2))
        return float(m.group(1)) / den if den else None
    v = _as_float(s)
    return v / 100.0 if v is not None else None


def _scan_targets(t: str) -> list:
    """识别文本中的量化目标并去重等价目标（3/3 ≡ 全覆盖 ≡ 100%）。
    返回 ≥2 个不同目标 → 多目标并存（判 manual，不强行合取）。"""
    targets = []
    fm = _FRAC_RE.search(t)
    frac_ratio = None
    if fm:
        den = float(fm.group(2))
        frac_ratio = float(fm.group(1)) / den if den else None
        targets.append(("frac", frac_ratio))
    if _FULL_RE.search(t):
        targets.append(("full", None))
    if _ZERO_RE.search(t):
        targets.append(("zero", None))
    for m in _CMP_RE.finditer(t):
        targets.append(("cmp", m.group(1), float(m.group(2))))
    cm = _CN_FREQ_RE.search(t)
    if cm:
        targets.append(("freq", sum(_CN_NUM.get(ch, 0) for ch in cm.group(2))))
    # 等价去重：frac=1.0 与 full 同义（"3/3 全覆盖"算一个目标）
    if frac_ratio is not None and abs(frac_ratio - 1.0) < 1e-9 and any(x[0] == "full" for x in targets):
        targets = [x for x in targets if x[0] != "frac"]
    return targets


def eval_threshold(threshold: str, actual) -> dict:
    t = _norm_threshold(threshold or "")
    if actual is None or str(actual).strip() == "":
        return {"status": "missing", "parsed": False, "reason": "未采集实际值"}
    a = str(actual).strip()

    # 1) 存在性判定
    if _HAS_MARK.search(t) or _NO_MARK.search(t):
        ok = a not in ("无", "否", "0", "missing", "未", "没有", "无记录", "不存在", "未提供", "不合格")
        return {"status": "pass" if ok else "fail", "parsed": True, "kind": "presence"}

    # 1.5) 多目标并存 → manual（如 "核心100%，总体≥80%" 是两个独立目标，不做合取/取一）
    if len(_scan_targets(t)) >= 2:
        return {"status": "manual", "parsed": False,
                "reason": f"多目标并存，需人工拆分: {t[:60]}"}

    # 2) 分数 N/M
    fm = _FRAC_RE.search(t)
    if fm:
        num, den = float(fm.group(1)), float(fm.group(2))
        if den <= 0:
            return {"status": "manual", "parsed": False, "reason": "分数分母非法"}
        need_ratio = num / den
        av = _as_ratio(a)
        if av is None:
            return {"status": "manual", "parsed": False,
                    "reason": f"分数阈值 {fm.group(0)} 需 actual 为分数或百分比"}
        ok = av >= need_ratio - 1e-9
        return {"status": "pass" if ok else "fail", "parsed": True, "kind": "fraction",
                "op": ">=", "need": round(need_ratio * 100, 2), "unit": "%", "actual": a}

    # 3) 抽样比例："抽查 N 项，≥M 项"
    sm = _SAMPLE_RE.search(t)
    if sm:
        n, m = float(sm.group(1)), float(sm.group(2))
        if n <= 0 or m > n:
            return {"status": "manual", "parsed": False, "reason": "抽样比例形态异常"}
        av = _as_float(a)
        if av is not None:
            # 纯数字按"命中个数 ≥ M"判定
            ok = av >= m - 1e-9
            return {"status": "pass" if ok else "fail", "parsed": True, "kind": "sample-count",
                    "op": ">=", "need": m, "unit": "项", "actual": a}
        av2 = _as_ratio(a)
        if av2 is not None:
            ok = av2 >= (m / n) - 1e-9
            return {"status": "pass" if ok else "fail", "parsed": True, "kind": "sample-ratio",
                    "op": ">=", "need": round(m / n * 100, 2), "unit": "%", "actual": a}
        return {"status": "manual", "parsed": False,
                "reason": f"抽样阈值 {sm.group(0)} 需 actual 为命中个数或百分比"}

    # 4) 全覆盖 / 100%
    if _FULL_RE.search(t):
        av = _as_float(a.rstrip("%"))
        if av is None:
            return {"status": "manual", "parsed": False, "reason": "全覆盖阈值需数值实际值"}
        ok = av >= 100 - 1e-9
        return {"status": "pass" if ok else "fail", "parsed": True, "kind": "full-coverage",
                "op": "=", "need": 100, "unit": "%", "actual": a}

    # 5) 零 / 0 条
    if _ZERO_RE.search(t):
        av = _as_float(a)
        if av is None:
            return {"status": "manual", "parsed": False, "reason": "零目标阈值需数值实际值"}
        ok = av <= 0 + 1e-9
        return {"status": "pass" if ok else "fail", "parsed": True, "kind": "zero",
                "op": "=", "need": 0, "unit": "条", "actual": a}

    # 6) 中文频次（如 至少每季度一次 / 不少于2次）
    cm = _CN_FREQ_RE.search(t)
    if cm:
        need = sum(_CN_NUM.get(ch, 0) for ch in cm.group(2))
        av = _as_float(a)
        if av is None:
            return {"status": "manual", "parsed": False, "reason": "频次阈值需数值实际值"}
        ok = av >= need - 1e-9
        return {"status": "pass" if ok else "fail", "parsed": True, "kind": "frequency",
                "op": ">=", "need": need, "unit": "次", "actual": a}

    # 7) 数值比较（可嵌句中；多目标并存 → manual）
    m = _CMP_RE.search(t)
    if m:
        word, num = m.group(1), float(m.group(2))
        rest = t[m.end():]
        if _CMP_RE.search(rest):
            return {"status": "manual", "parsed": False, "reason": f"多目标并存，需人工拆分: {t[:60]}"}
        av = _as_float(a)
        if av is None:
            return {"status": "manual", "parsed": False,
                    "reason": f"比较阈值 {m.group(0)} 需数值实际值（实际={a}）"}
        op = _OP_MAP[word]
        ok = {">=": av >= num, "<=": av <= num, ">": av > num, "<": av < num,
              "=": abs(av - num) < 1e-9}[op]
        return {"status": "pass" if ok else "fail", "parsed": True, "kind": "numeric",
                "op": op, "need": num, "actual": av}

    return {"status": "manual", "parsed": False, "reason": "定性/未识别阈值形态"}


def create_run(inspected_target: str, inspector: str, actor: str = "reviewer") -> dict:
    """创建检查运行。"""
    run_id = f"ir-{uuid.uuid4().hex[:8]}"
    data = {"code": run_id, "inspectedTarget": inspected_target,
            "inspector": inspector, "ranAt": _now()}
    with db() as conn:
        _pub(conn, run_id, "InspectionRun", data)
    audit.log(actor, "inspection.run.create", run_id, {"target": inspected_target})
    run_db.mirror_run({"run_id": run_id, "inspected_target": inspected_target,
                       "inspector": inspector, "ran_at": data.get("ranAt"),
                       "data": data, "updated_at": data.get("ranAt") or ""})
    return {"runId": run_id, "inspectedTarget": inspected_target, "inspector": inspector}


def _get_check(conn, check_code: str):
    r = conn.execute("SELECT * FROM entities WHERE type='InspectionCheck' AND status='published' "
                     "AND dataJSON LIKE ?", (f'%"checkCode": "{check_code}"%',)).fetchone()
    return r


def record_result(run_id: str, check_code: str,
                  element_inputs: list[dict], metric_inputs: list[dict],
                  actor: str = "reviewer") -> dict:
    """element_inputs: [{code, l1_ok(bool), l4_evidence: provided|missing, note}]
       metric_inputs: [{metricId, actual}]
       聚合：要素 worst-case + 证据齐备度 + L5 阈值 → pass/partial/fail。"""
    with db() as conn:
        run = conn.execute("SELECT id FROM entities WHERE id=? AND type='InspectionRun'", (run_id,)).fetchone()
        if not run:
            raise ValueError(f"检查运行不存在: {run_id}")
        cr = _get_check(conn, check_code)
        if not cr:
            raise ValueError(f"检查项不存在: {check_code}")
        check_id = cr["id"]
        cdata = json.loads(cr["dataJSON"])

        # ---- 逐要素判定 ----
        elem_verdicts = []
        has_gap = False
        for e in element_inputs:
            v = {"code": e["code"], "note": e.get("note", "")}
            if not e.get("l1_ok", False):
                v["result"] = "fail"
                v["why"] = "L1制度层：未见对应制度条款"
            elif e.get("l4_evidence") == "missing":
                v["result"] = "partial"
                v["why"] = "L4证据层：制度存在但缺运行证据"
                has_gap = True
            else:
                v["result"] = "pass"
                v["why"] = "L1制度存在且L4证据provided"
            elem_verdicts.append(v)

        # ---- L5 度量阈值 ----
        metric_results = []
        gap_target_kind = None
        for mi in metric_inputs:
            th = mi.get("threshold", "")
            ev = eval_threshold(th, mi.get("actual"))
            metric_results.append({"metricId": mi.get("metricId"), "threshold": th,
                                   "actual": mi.get("actual"), **ev})
            if ev["status"] == "manual":
                has_gap = True
                gap_target_kind = "Metric"
            elif ev["status"] == "fail":
                elem_verdicts.append({"code": "L5-metric", "result": "fail",
                                      "why": f"L5效果层：阈值 {th} 未达（实际 {mi.get('actual')}）"})
            elif ev["status"] == "missing":
                elem_verdicts.append({"code": "L5-metric", "result": "partial",
                                      "why": f"L5效果层：未采集度量值（阈值 {th}）"})

        # ---- 聚合 worst-case ----
        if any(v["result"] == "fail" for v in elem_verdicts):
            overall = "fail"
        elif any(v["result"] == "partial" for v in elem_verdicts):
            overall = "partial"
        else:
            overall = "pass"

        why = {
            "checkCode": check_code, "checkTitle": cdata.get("title"),
            "domain": cdata.get("domain"), "priority": cdata.get("priority"),
            "elements": elem_verdicts, "metrics": metric_results,
            "verdictRule": cdata.get("verdictRule"),
        }
        result_id = f"cr-{uuid.uuid4().hex[:8]}"
        _pub(conn, result_id, "CheckResult",
             {"code": result_id, "result": overall,
              "checkResultOfCheck": f"InspectionCheck:{check_id}",
              "resultRun": f"InspectionRun:{run_id}",
              "elementVerdict": json.dumps(elem_verdicts, ensure_ascii=False),
              "metricActual": json.dumps(metric_results, ensure_ascii=False),
              "why": json.dumps(why, ensure_ascii=False)},
             relations=[
                 {"p": "checkResultOfCheck", "o": f"InspectionCheck:{check_id}"},
                 {"p": "resultRun", "o": f"InspectionRun:{run_id}"},
             ])
        gap_target_kind = gap_target_kind or "EvidenceRequirement"
    # 块外建提案，避免嵌套写连接锁库
    proposal_id = None
    if has_gap and overall in ("partial", "fail"):
        proposal_id = proposal_svc.create(
            reason=f"检查项 {check_code}（{cdata.get('title')}）运行存在知识缺口："
                   f"缺证据模板或阈值不可自动判定，需专家补全{gap_target_kind}",
            target_kind=gap_target_kind, raised_from=result_id,
            payload={"checkCode": check_code, "runId": run_id,
                     "need": gap_target_kind}, actor=actor)["id"]
    audit.log(actor, "inspection.result", result_id,
              {"check": check_code, "result": overall, "proposal": proposal_id})
    run_db.mirror_result({"result_id": result_id, "run_id": run_id, "check_code": check_code,
                          "elements_json": elem_verdicts, "metrics_json": metric_results,
                          "result": overall, "why_json": why, "created_at": _now()})
    return {"resultId": result_id, "checkCode": check_code, "result": overall,
            "why": why, "proposalId": proposal_id}


def get_run(run_id: str) -> dict:
    with db() as conn:
        r = conn.execute("SELECT * FROM entities WHERE id=? AND type='InspectionRun'", (run_id,)).fetchone()
        if not r:
            return None
        rd = json.loads(r["dataJSON"])
        results = []
        for cr in conn.execute("SELECT * FROM entities WHERE type='CheckResult' "
                               "AND dataJSON LIKE ?", (f'%"resultRun": "InspectionRun:{run_id}"%',)).fetchall():
            cd = json.loads(cr["dataJSON"])
            results.append({"id": cr["id"], "checkCode": json.loads(cd["why"]).get("checkCode"),
                            "result": cd["result"], "why": json.loads(cd["why"])})
        return {"runId": run_id, "inspectedTarget": rd.get("inspectedTarget"),
                "inspector": rd.get("inspector"), "ranAt": rd.get("ranAt"),
                "results": results}


def compare(run1: str, run2: str) -> dict:
    a, b = get_run(run1), get_run(run2)
    if not a or not b:
        return None
    ba = {r["checkCode"]: r["result"] for r in a["results"]}
    bb = {r["checkCode"]: r["result"] for r in b["results"]}
    changes = []
    for code in sorted(set(ba) | set(bb)):
        if ba.get(code) != bb.get(code):
            changes.append({"checkCode": code, "before": ba.get(code), "after": bb.get(code)})
    return {"runBefore": run1, "runAfter": run2, "changes": changes,
            "overallBefore": _worst(ba.values()), "overallAfter": _worst(bb.values())}


def _worst(results) -> str:
    rs = list(results)
    if "fail" in rs:
        return "fail"
    if "partial" in rs:
        return "partial"
    if rs:
        return "pass"
    return "unknown"


# ---------------- 合规自查报告（PRD M4.5 / O5）----------------
# 纯派生、无副作用：报告随时可由「运行 + 检查项六维」复算，同输入同输出（M4 验收要点）。
# 逐条产出：佐证是否完整 / 内容是否完备 / 是否符合监管合规要求 → 差距 → 整改建议 → 专家意见。
# 整改建议与专家意见一律由检查项自身数据（findings / methodSteps / verdict / suggestedControls）
# 派生，不臆造监管要求。
_L5 = "L5-metric"
_VERDICT_WORD = {"pass": "符合", "partial": "部分符合", "fail": "不符合"}
_GAP_KW = {
    "制度缺失": ("制度", "条款", "总纲", "办法", "细则", "规范"),
    "证据缺失": ("证据", "记录", "纪要", "台账", "报告", "留痕", "清单"),
    "阈值未达": ("度量", "阈值", "指标", "比例", "覆盖"),
    "度量未采集": ("度量", "阈值", "指标", "采集", "统计"),
}


def _pct(n: int, d: int) -> float:
    return round(n * 100.0 / d, 1) if d else 0.0


def _check_detail(check_code: str) -> dict:
    """取检查项六维详情（含 findings/verdict/suggestedControls）；任何异常降级为空字典。"""
    try:
        from . import kb_source
        return ((kb_source.fetch_check(check_code) or {}).get("content")) or {}
    except Exception:
        return {}


def _remediation_for(gap: dict, det: dict) -> list[dict]:
    """按缺口类型从检查项自身 findings / 证据步骤 / 建议控制派生整改建议。"""
    kws = _GAP_KW.get(gap.get("type"), ())
    out = []
    for f in det.get("findings") or []:
        blob = f"{f.get('problem', '')}{f.get('rootCause', '')}"
        if not kws or any(k in blob for k in kws):
            out.append({"action": f.get("remediation") or "", "basis": f.get("problem") or "",
                        "rootCause": f.get("rootCause") or ""})
    if not out and gap.get("type") in ("证据缺失", "度量未采集"):
        for s in det.get("methodSteps") or []:
            if s.get("stepKind") == "evidence":
                out.append({"action": f"按检查方法补齐证据：{s.get('action') or s.get('focus') or ''}",
                            "basis": f"检查方法·证据步骤 {s.get('stepNo', '')}", "rootCause": ""})
    if not out:
        for s in det.get("suggestedControls") or []:
            out.append({"action": f"对齐控制措施「{s.get('name')}」并补齐落地证据",
                        "basis": f"建议控制措施（{s.get('ctCode') or s.get('layer') or '占位'}）",
                        "rootCause": ""})
    return [x for x in out if x.get("action")][:3]


def _expert_opinion(item: dict, det: dict) -> str:
    """专家意见：由依据条款 / 差距 / 核查要点 / 建议控制确定性合成。"""
    reg, art = det.get("regulation") or "", det.get("articleNo") or ""
    basis = (f"《{reg}》{art}" if reg else str(art)).strip()
    parts = []
    parts.append(f"依据 {basis} 判定为「{_VERDICT_WORD.get(item['result'], item['result'])}」"
                 if basis else f"判定为「{_VERDICT_WORD.get(item['result'], item['result'])}」")
    if item["gaps"]:
        parts.append("主要差距：" + "、".join(f"{g['type']}（{g['code'] or '—'}）" for g in item["gaps"][:3]))
    tip = det.get("tip")
    if tip:
        parts.append(f"核查要点：{tip}")
    sc = det.get("suggestedControls") or []
    if sc:
        parts.append(f"建议优先对齐控制「{sc[0].get('name')}」")
    if item["result"] != "pass":
        parts.append("补齐上述佐证后建议 30 日内复检")
    return "；".join(parts) + "。"


def generate_report(run_id: str) -> dict | None:
    """合规自查报告（PRD M4）：逐条佐证完整性 / 内容完备性 / 合规符合性 + 差距 + 整改建议 + 专家意见。"""
    run = get_run(run_id)
    if not run:
        return None
    items = []
    for r in run.get("results", []):
        why = r.get("why") or {}
        code = why.get("checkCode") or r.get("checkCode") or ""
        det = _check_detail(code)
        elems = why.get("elements") or []
        metrics = why.get("metrics") or []
        real_elems = [e for e in elems if e.get("code") != _L5]

        l1_missing = [e for e in real_elems if e.get("result") == "fail"]
        l4_missing = [e for e in real_elems if e.get("result") == "partial"]
        l5_fail = [e for e in elems if e.get("code") == _L5 and e.get("result") == "fail"]
        l5_noactual = [e for e in elems if e.get("code") == _L5 and e.get("result") == "partial"]

        gaps = []
        gaps += [{"type": "制度缺失", "code": e.get("code", ""), "detail": e.get("why", "")} for e in l1_missing]
        gaps += [{"type": "证据缺失", "code": e.get("code", ""), "detail": e.get("why", "")} for e in l4_missing]
        gaps += [{"type": "阈值未达", "code": _L5, "detail": e.get("why", "")} for e in l5_fail]
        gaps += [{"type": "度量未采集", "code": _L5, "detail": e.get("why", "")} for e in l5_noactual]
        for m in metrics:
            if m.get("status") == "manual":
                gaps.append({"type": "度量未采集", "code": m.get("metricId") or "",
                             "detail": m.get("reason") or f"阈值 {m.get('threshold')} 需人工判定"})

        remediation = []
        for g in gaps:
            for rmd in _remediation_for(g, det):
                rmd = dict(rmd)
                rmd["forGap"] = f"{g['type']}·{g['code'] or '—'}"
                if rmd not in remediation:
                    remediation.append(rmd)

        total_el = len(real_elems)
        item = {
            "checkCode": code,
            "title": why.get("checkTitle") or det.get("title") or "",
            "priority": why.get("priority") or det.get("priority") or "",
            "domain": det.get("domainLabel") or why.get("domain") or "",
            "regulation": det.get("regulation") or "",
            "articleNo": det.get("articleNo") or "",
            "result": r.get("result"),
            "evidence": {"provided": max(total_el - len(l1_missing) - len(l4_missing), 0),
                         "missing": len(l4_missing), "absent": len(l1_missing), "total": total_el},
            "evidenceComplete": not (l1_missing or l4_missing or l5_noactual)
                                and not any(m.get("status") in ("missing", "manual") for m in metrics),
            "contentAdequate": not l1_missing,
            "compliant": r.get("result") == "pass",
            "gaps": gaps,
            "remediation": remediation,
        }
        item["expertOpinion"] = _expert_opinion(item, det)
        items.append(item)

    n = len(items)
    el_total = sum(i["evidence"]["total"] for i in items)
    el_provided = sum(i["evidence"]["provided"] for i in items)
    summary = {
        "total": n,
        "pass": sum(1 for i in items if i["result"] == "pass"),
        "partial": sum(1 for i in items if i["result"] == "partial"),
        "fail": sum(1 for i in items if i["result"] == "fail"),
        "overall": _worst([i["result"] for i in items]),
        "complianceRate": _pct(sum(1 for i in items if i["compliant"]), n),
        "evidenceCompleteness": _pct(el_provided, el_total),
        "contentAdequacy": _pct(sum(1 for i in items if i["contentAdequate"]), n),
        "evidenceComplete": sum(1 for i in items if i["evidenceComplete"]),
    }
    p_order = {"P0": 0, "P1": 1, "P2": 2}
    gap_summary = [{"checkCode": i["checkCode"], "title": i["title"], **g}
                   for i in items for g in i["gaps"]]
    expert = [{"checkCode": i["checkCode"], "priority": i["priority"], "opinion": i["expertOpinion"]}
              for i in sorted(items, key=lambda x: (p_order.get(x["priority"], 9), x["checkCode"]))
              if i["result"] != "pass"]
    audit.log("system", "inspection.report", run_id,
              {"items": n, "overall": summary["overall"], "gaps": len(gap_summary)})
    return {"runId": run_id, "inspectedTarget": run.get("inspectedTarget"),
            "inspector": run.get("inspector"), "ranAt": run.get("ranAt"),
            "generatedAt": _now(), "summary": summary, "items": items,
            "gapSummary": gap_summary, "expertOpinions": expert}


def report_markdown(rep: dict) -> str:
    """合规自查报告 Markdown 导出（供下载/留痕）。"""
    s = rep.get("summary") or {}
    L = ["# 合规自查报告", "",
         f"- 被查对象：{rep.get('inspectedTarget') or '—'}",
         f"- 检查人：{rep.get('inspector') or '—'}",
         f"- 运行ID：{rep.get('runId')}",
         f"- 运行时间：{rep.get('ranAt') or '—'}",
         f"- 生成时间：{rep.get('generatedAt') or '—'}", "",
         "## 一、总体结论", "",
         f"- 检查项合计：{s.get('total', 0)}",
         f"- 结论分布：符合 {s.get('pass', 0)} / 部分符合 {s.get('partial', 0)} / 不符合 {s.get('fail', 0)}",
         f"- 合规率：{s.get('complianceRate', 0)}%",
         f"- 佐证完整性：{s.get('evidenceCompleteness', 0)}%（{s.get('evidenceComplete', 0)}/{s.get('total', 0)} 条佐证齐备）",
         f"- 内容完备性：{s.get('contentAdequacy', 0)}%",
         f"- 总体判定：{_VERDICT_WORD.get(s.get('overall'), s.get('overall'))}", "",
         "## 二、逐条自查结论与差距", ""]
    for i in rep.get("items", []):
        L += [f"### {i['checkCode']} {i['title']}", "",
              f"- 依据：{i.get('regulation') or '—'} {i.get('articleNo') or ''}".rstrip(),
              f"- 判定：{_VERDICT_WORD.get(i['result'], i['result'])}"
              f"（佐证{'完整' if i['evidenceComplete'] else '不完整'} / 内容{'完备' if i['contentAdequate'] else '不完备'}）",
              f"- 佐证：已提供 {i['evidence']['provided']} / 缺失 {i['evidence']['missing']} / 无制度 {i['evidence']['absent']}"]
        if i["gaps"]:
            L.append("- 差距：")
            L += [f"  - [{g['type']}] {g['code'] or '—'}：{g['detail']}" for g in i["gaps"]]
        if i["remediation"]:
            L.append("- 整改建议：")
            L += [f"  - {r['action']}（依据：{r['basis']}）" for r in i["remediation"]]
        L += [f"- 专家意见：{i['expertOpinion']}", ""]
    gp = rep.get("gapSummary") or []
    L += ["## 三、差距汇总", ""]
    L += [f"- {g['checkCode']} [{g['type']}] {g['code'] or '—'}：{g['detail']}" for g in gp] or ["- 无"]
    L += ["", "## 四、专家意见汇总", ""]
    L += [f"- [{e['priority'] or '—'}] {e['checkCode']}：{e['opinion']}" for e in rep.get("expertOpinions") or []] or ["- 无"]
    return "\n".join(L) + "\n"
