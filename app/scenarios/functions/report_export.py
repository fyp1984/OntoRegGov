"""函数适配器：自查/检查报告导出。

大白话：把一次（或前后两次）检查运行的"事实"从平台既有服务里捞出来，拼成一份
可直接浏览器打开的 HTML + 一份 Markdown 报告。所有内容来自本体/平台数据：
  - 运行概览 / 逐项判定 / why 溯源 → services.inspection.get_run
  - 复检前后对比                → services.inspection.compare
  - 缺口提案清单               → services.proposal.list_proposals（按 payload.runId 过滤）
  - 整改与证据记录              → services.ledger.list_evidence
不硬编码任何检查项标题与判定——标题/判定一律取 get_run 返回的 why.checkTitle / result。

run(params) 入参：
  runIds: [str]        必需，1 个或 2 个（2 个时第1个=整改前，第2个=整改后，做 compare）
  reportType: str      selfcheck | supervisory（报告标题措辞区分）
  title: str           可选报告标题
  actor: str           可选报告人
返回：{ok, title, runIds, html, markdown, fileNameBase, stats}
"""
from __future__ import annotations

import datetime
import html as _html

from ...services import inspection as inspection_svc
from ...services import proposal as proposal_svc
from ...services import ledger as ledger_svc

_RESULT_LABEL = {"pass": "符合", "partial": "部分符合", "fail": "不符合"}
_RESULT_COLOR = {"pass": "#1a9e5c", "partial": "#b97d10", "fail": "#d23b3b"}


def _esc(s) -> str:
    return _html.escape("" if s is None else str(s))


def _badge_html(result: str) -> str:
    color = _RESULT_COLOR.get(result, "#8a93a6")
    label = _RESULT_LABEL.get(result, result)
    return (f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
            f'font-size:12px;font-weight:600;color:{color};'
            f'background:{color}1a;border:1px solid {color}55">{_esc(label)}</span>')


def _badge_md(result: str) -> str:
    return f"`{_RESULT_LABEL.get(result, result)}`"


def _collect(run_ids: list[str]) -> dict:
    runs = []
    missing = []
    for rid in run_ids:
        r = inspection_svc.get_run(rid)
        if r:
            runs.append(r)
        else:
            missing.append(rid)
    return {"runs": runs, "missing": missing}


def _proposals_for(run_ids: list[str]) -> list[dict]:
    wanted = set(run_ids)
    out = []
    for p in proposal_svc.list_proposals():
        payload = p.get("payload") or {}
        if payload.get("runId") in wanted:
            out.append(p)
    return out


def _evidence_for(run_ids: list[str]) -> list[dict]:
    out = []
    for rid in run_ids:
        for e in ledger_svc.list_evidence(rid):
            out.append(e)
    return out


def _per_item_rows(runs: list[dict]) -> list[dict]:
    """合并多次运行的逐检查项判定，保留 run 维度。"""
    rows = []
    for r in runs:
        for res in r.get("results", []):
            why = res.get("why") or {}
            rows.append({
                "runId": r["runId"],
                "checkCode": res.get("checkCode"),
                "checkTitle": why.get("checkTitle") or res.get("checkCode"),
                "domain": why.get("domain", ""),
                "priority": why.get("priority", ""),
                "result": res.get("result"),
                "elements": why.get("elements", []),
                "metrics": why.get("metrics", []),
            })
    return rows


def run(params: dict | None = None) -> dict:
    params = params or {}
    run_ids = params.get("runIds") or params.get("runIds[]") or []
    if isinstance(run_ids, str):
        run_ids = [x for x in run_ids.split(",") if x.strip()]
    run_ids = [x.strip() for x in run_ids if x and str(x).strip()]
    if not run_ids:
        return {"ok": False, "error": {"code": "no_run", "message": "runIds 不能为空"}}

    report_type = params.get("reportType", "selfcheck")
    title = params.get("title") or (
        "被监管方自查/迎检报告" if report_type == "selfcheck" else "监管检查复盘报告")
    actor = params.get("actor", "reviewer")

    coll = _collect(run_ids)
    runs = coll["runs"]
    missing = coll["missing"]
    if not runs:
        return {"ok": False, "error": {"code": "run_not_found",
                                       "message": f"未找到任何运行: {missing}"}}

    rows = _per_item_rows(runs)
    proposals = _proposals_for(run_ids)
    evidence = _evidence_for(run_ids)

    # 复检对比：提供 2 个运行时
    cmp_info = None
    if len(runs) >= 2:
        cmp_info = inspection_svc.compare(runs[0]["runId"], runs[-1]["runId"])

    # 统计
    counts = {"pass": 0, "partial": 0, "fail": 0}
    for r in rows:
        counts[r["result"]] = counts.get(r["result"], 0) + 1
    overall = inspection_svc._worst([r["result"] for r in rows])

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fileNameBase = f"report-{report_type}-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"

    # ---------------- 生成 HTML ----------------
    html = _render_html(title, actor, now, runs, missing, rows, counts, overall,
                        proposals, evidence, cmp_info, report_type)
    markdown = _render_md(title, actor, now, runs, missing, rows, counts, overall,
                         proposals, evidence, cmp_info)

    return {
        "ok": True, "title": title, "reportType": report_type,
        "runIds": run_ids, "missing": missing,
        "stats": {"itemJudged": len(rows), "pass": counts["pass"],
                  "partial": counts["partial"], "fail": counts["fail"],
                  "overall": overall, "proposals": len(proposals),
                  "evidence": len(evidence), "hasCompare": cmp_info is not None},
        "html": html, "markdown": markdown, "fileNameBase": fileNameBase,
    }


# --------------------------------------------------------------------------- #
def _render_html(title, actor, now, runs, missing, rows, counts, overall,
                 proposals, evidence, cmp_info, report_type) -> str:
    ov_badge = _badge_html(overall)
    runs_html = "".join(
        f"<tr><td>{_esc(r['runId'])}</td><td>{_esc(r.get('inspectedTarget'))}</td>"
        f"<td>{_esc(r.get('inspector'))}</td><td>{_esc(r.get('ranAt'))}</td>"
        f"<td>{len(r.get('results', []))}</td></tr>" for r in runs)

    rows_html = ""
    for r in rows:
        el_why = "；".join(f"{e.get('code')}:{e.get('why')}" for e in r["elements"])
        mt_why = "；".join(f"{m.get('metricId') or m.get('threshold')}:实际={m.get('actual')}"
                          for m in r["metrics"])
        rows_html += (
            f"<tr><td>{_esc(r['runId'])}</td><td>{_esc(r['checkCode'])}</td>"
            f"<td>{_esc(r['checkTitle'])}<br><span class='muted'>域:{_esc(r['domain'])} "
            f">优先级:{_esc(r['priority'])}</span></td>"
            f"<td>{_badge_html(r['result'])}</td>"
            f"<td><div class='why'>{_esc(el_why)}<br>{_esc(mt_why)}</div></td></tr>")

    prop_html = "".join(
        f"<tr><td>{_esc(p['id'])}</td><td>{_esc(p.get('status'))}</td>"
        f"<td>{_esc(p.get('targetKind'))}</td><td>{_esc(p.get('reason'))}</td>"
        f"<td>{_esc(p.get('reviewer',''))}</td></tr>" for p in proposals) or \
        "<tr><td colspan=5>（无缺口提案）</td></tr>"

    ev_html = "".join(
        f"<tr><td>{_esc(e.get('runId'))}</td><td>{_esc(e.get('checkCode'))}</td>"
        f"<td>{_esc(e.get('fileName'))}</td><td>{_esc(e.get('uploadedBy'))}</td>"
        f"<td>{_esc(e.get('uploadedAt'))}</td><td>{_esc(e.get('note',''))}</td></tr>"
        for e in evidence) or "<tr><td colspan=6>（无证据记录）</td></tr>"

    cmp_html = ""
    if cmp_info:
        ch = "".join(
            f"<tr><td>{_esc(c['checkCode'])}</td><td>{_badge_html(c['before'] or '—')}</td>"
            f"<td>→</td><td>{_badge_html(c['after'] or '—')}</td></tr>"
            for c in cmp_info.get("changes", [])) or "<tr><td colspan=4>（两次运行无变化）</td></tr>"
        cmp_html = (f"<h3>复检对比（{_esc(cmp_info['runBefore'])} → {_esc(cmp_info['runAfter'])}）"
                    f"总评 {_badge_html(cmp_info['overallBefore'])} → {_badge_html(cmp_info['overallAfter'])}</h3>"
                    f"<table><tr><th>检查项</th><th>整改前</th><th></th><th>整改后</th></tr>{ch}</table>")

    miss_html = f"<p class='muted'>未取到的运行：{_esc(missing)}</p>" if missing else ""
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<style>
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#F4F7FD;color:#243447;margin:0;padding:28px;line-height:1.65}}
.wrap{{max-width:1080px;margin:0 auto}}
h1{{color:#1E3268;font-size:22px;border-left:6px solid #2055D7;padding-left:12px}}
h3{{color:#1E3268;font-size:16px;margin-top:28px}}
table{{width:100%;border-collapse:collapse;font-size:13px;background:#fff;margin:8px 0}}
th{{background:#1E3268;color:#fff;text-align:left;padding:9px 10px}}
td{{border-bottom:1px solid #E3EBFA;padding:8px 10px;vertical-align:top}}
.muted{{color:#6b7a93;font-size:12px}}
.why{{background:#F6F9FF;border-left:3px solid #2055D7;padding:6px 10px;border-radius:6px;font-size:12px}}
.stat{{display:inline-block;background:#F6F9FF;border:1px solid #E3EBFA;border-radius:12px;padding:12px 18px;margin:4px 10px 4px 0}}
.stat b{{font-size:22px;color:#2055D7;display:block}}
.meta{{color:#6b7a93;font-size:13px;margin-bottom:18px}}
</style></head><body><div class="wrap">
<h1>{_esc(title)}</h1>
<p class="meta">报告类型：{_esc(report_type)}　报告人：{_esc(actor)}　生成时间：{_esc(now)}　结论：{ov_badge}</p>
{miss_html}
<h3>一、运行概览</h3>
<div>
<span class="stat"><b>{len(runs)}</b>次运行</span>
<span class="stat"><b>{counts['pass']}</b>符合</span>
<span class="stat"><b>{counts['partial']}</b>部分</span>
<span class="stat"><b>{counts['fail']}</b>不符合</span>
</div>
<table><tr><th>运行ID</th><th>被查对象</th><th>检查人</th><th>运行时间</th><th>判定项数</th></tr>{runs_html}</table>
<h3>二、逐项判定表（结论来自本体/平台，标题非硬编码）</h3>
<table><tr><th>运行</th><th>检查项</th><th>标题</th><th>判定</th><th>why 溯源</th></tr>{rows_html}</table>
<h3>三、缺口提案清单</h3>
<table><tr><th>提案ID</th><th>状态</th><th>目标</th><th>事由</th><th>处理人</th></tr>{prop_html}</table>
<h3>四、整改与证据记录</h3>
<table><tr><th>运行</th><th>检查项</th><th>证据文件</th><th>上传人</th><th>时间</th><th>备注</th></tr>{ev_html}</table>
{cmp_html}
<h3>五、结论</h3>
<p>本次检查总体结论 {ov_badge}；符合 {counts['pass']} 项、部分符合 {counts['partial']} 项、不符合 {counts['fail']} 项。
缺口提案 {len(proposals)} 条、证据归档 {len(evidence)} 份。不符合项应按 why 溯源整改后复跑，复检对比见上。</p>
<p class="muted">本报告由 OntoRegGov 场景框架 report_export 函数自动生成，全部数据来自本体/平台服务，无人工硬编码判定。</p>
</div></body></html>"""


def _render_md(title, actor, now, runs, missing, rows, counts, overall,
               proposals, evidence, cmp_info) -> str:
    L = [f"# {title}", "",
         f"- 报告人：{actor}　生成时间：{now}",
         f"- 总体结论：{_RESULT_LABEL.get(overall, overall)}",
         f"- 统计：符合 {counts['pass']} / 部分 {counts['partial']} / 不符合 {counts['fail']}", ""]
    if missing:
        L.append(f"> 未取到运行：{missing}")
    L += ["## 一、运行概览", "",
          "| 运行ID | 被查对象 | 检查人 | 运行时间 | 判定项数 |",
          "|---|---|---|---|---|"]
    for r in runs:
        L.append(f"| {r['runId']} | {r.get('inspectedTarget')} | {r.get('inspector')} | "
                 f"{r.get('ranAt')} | {len(r.get('results', []))} |")
    L += ["", "## 二、逐项判定表", "",
          "| 运行 | 检查项 | 标题 | 判定 | why |", "|---|---|---|---|---|"]
    for r in rows:
        el = "；".join(f"{e.get('code')}:{e.get('why')}" for e in r["elements"])
        L.append(f"| {r['runId']} | {r['checkCode']} | {r['checkTitle']} | "
                 f"{_badge_md(r['result'])} | {el} |")
    L += ["", "## 三、缺口提案清单", "",
          "| 提案ID | 状态 | 目标 | 事由 |", "|---|---|---|---|"]
    for p in proposals:
        L.append(f"| {p['id']} | {p.get('status')} | {p.get('targetKind')} | {p.get('reason')} |")
    if not proposals:
        L.append("|（无）| | | |")
    L += ["", "## 四、整改与证据记录", "",
          "| 运行 | 检查项 | 证据文件 | 上传人 | 时间 |", "|---|---|---|---|---|"]
    for e in evidence:
        L.append(f"| {e.get('runId')} | {e.get('checkCode')} | {e.get('fileName')} | "
                 f"{e.get('uploadedBy')} | {e.get('uploadedAt')} |")
    if not evidence:
        L.append("|（无）| | | | |")
    if cmp_info:
        L += ["", f"## 五、复检对比（{cmp_info['runBefore']} → {cmp_info['runAfter']}）", "",
              f"总评 {_RESULT_LABEL.get(cmp_info['overallBefore'])} → {_RESULT_LABEL.get(cmp_info['overallAfter'])}", "",
              "| 检查项 | 整改前 | 整改后 |", "|---|---|---|"]
        for c in cmp_info.get("changes", []):
            L.append(f"| {c['checkCode']} | {c.get('before') or '—'} | {c.get('after') or '—'} |")
    L += ["", "## 结论", "",
          f"本次检查总体结论 {_RESULT_LABEL.get(overall, overall)}。不符合项按 why 溯源整改后复跑复检。",
          "", "---", "*本报告由 OntoRegGov report_export 自动生成，数据来自本体/平台服务。*"]
    return "\n".join(L)
