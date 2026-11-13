"""合规自查报告 PDF 导出（reportlab + STSong-Light 中文 CID 字体，免外部字体文件）。"""
from __future__ import annotations

from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

_FONT = "STSong-Light"
_registered = False

_RESULT_CN = {"pass": "符合", "partial": "部分符合", "fail": "不符合",
              "missing": "证据缺失", "manual": "需人工"}
_RESULT_HEX = {"pass": "1a7f37", "partial": "b45309", "fail": "c62828",
               "missing": "8e44ad", "manual": "5b6b7f"}
_RESULT_COLOR = {k: colors.HexColor("#" + v) for k, v in _RESULT_HEX.items()}
_VERDICT_CN = _RESULT_CN


def _ensure_font() -> str:
    global _registered
    if not _registered:
        pdfmetrics.registerFont(UnicodeCIDFont(_FONT))
        _registered = True
    return _FONT


def _styles() -> dict:
    f = _ensure_font()
    return {
        "title": ParagraphStyle("t", fontName=f, fontSize=17, leading=24,
                                textColor=colors.HexColor("#1E3268"), spaceAfter=2),
        "sub": ParagraphStyle("s", fontName=f, fontSize=9.5, leading=14,
                              textColor=colors.HexColor("#5b6b7f")),
        "h2": ParagraphStyle("h2", fontName=f, fontSize=12.5, leading=18,
                             textColor=colors.HexColor("#1E3268"), spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("b", fontName=f, fontSize=9.5, leading=15, wordWrap="CJK"),
        "small": ParagraphStyle("sm", fontName=f, fontSize=8.5, leading=13,
                                textColor=colors.HexColor("#445066"), wordWrap="CJK"),
        "cell": ParagraphStyle("c", fontName=f, fontSize=9, leading=13.5, wordWrap="CJK"),
        "cellb": ParagraphStyle("cb", fontName=f, fontSize=9, leading=13.5,
                                 textColor=colors.white, wordWrap="CJK"),
    }


def _esc(s: str) -> str:
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_pdf(run: dict, summary: dict) -> bytes:
    """由 SelfCheckRun 数据生成 PDF，返回字节串。"""
    st = _styles()
    buf = __import__("io").BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=16 * mm,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            title="合规自查报告")
    story = []
    brand = colors.HexColor("#1E3268")
    light = colors.HexColor("#EEF4FF")

    story.append(Paragraph("合规自查报告", st["title"]))
    story.append(HRFlowable(width="100%", thickness=2, color=brand, spaceAfter=6))
    meta = (f"依据文件：{_esc(run.get('docNo') or run.get('doc'))}　｜　"
            f"证据目录：{_esc(run.get('dir'))}　｜　"
            f"开始：{_esc((run.get('startedAt') or '').replace('T', ' '))}　"
            f"结束：{_esc((run.get('finishedAt') or '').replace('T', ' '))}<br/>"
            f"检查方式：OpenClaw 智能体（agent: {_esc(run.get('agentId'))}）自动研判　｜　"
            f"文件总数：{run.get('fileCount', 0)}　｜　报告生成：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    story.append(Paragraph(meta, st["sub"]))
    story.append(Spacer(1, 8))

    # 概要统计
    ov = summary.get("overall", "manual")
    stat = Table([[
        Paragraph("总体结论", st["cellb"]), Paragraph("合规率", st["cellb"]),
        Paragraph("符合", st["cellb"]), Paragraph("部分符合", st["cellb"]),
        Paragraph("不符合", st["cellb"]), Paragraph("证据缺失", st["cellb"]),
        Paragraph("需人工", st["cellb"]),
    ], [
        Paragraph(f"<b><font color='#{_RESULT_HEX.get(ov, 'c62828')}'>{_RESULT_CN.get(ov, ov)}</font></b>", st["cell"]),
        Paragraph(f"{summary.get('complianceRate', 0)}%", st["cell"]),
        Paragraph(str(summary.get("pass", 0)), st["cell"]),
        Paragraph(str(summary.get("partial", 0)), st["cell"]),
        Paragraph(str(summary.get("fail", 0)), st["cell"]),
        Paragraph(str(summary.get("missing", 0)), st["cell"]),
        Paragraph(str(summary.get("manual", 0)), st["cell"]),
    ]], colWidths=[34 * mm, 22 * mm, 19 * mm, 22 * mm, 22 * mm, 22 * mm, 19 * mm])
    stat.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), brand),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9d6ee")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, 1), [light]),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(stat)

    if run.get("error"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"运行提示：{_esc(run['error'])}", st["small"]))

    # 逐检查项结果
    story.append(Paragraph("一、逐检查项合规情况", st["h2"]))
    for it in run.get("items") or []:
        r = it.get("result", "manual")
        color = _RESULT_COLOR.get(r, colors.HexColor("#5b6b7f"))
        head = Table([[
            Paragraph(f"<b>{_esc(it.get('checkCode'))}　{_esc(it.get('title'))}</b>", st["cell"]),
            Paragraph(f"<b>{_esc(it.get('priority') or '')}</b>", st["cell"]),
            Paragraph(f"<font color='#{_RESULT_HEX.get(r, '5b6b7f')}'><b>{_RESULT_CN.get(r, r)}</b></font>", st["cell"]),
        ]], colWidths=[118 * mm, 16 * mm, 28 * mm])
        head.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), light),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#c9d6ee")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ]))
        story.append(Spacer(1, 5))
        story.append(head)

        if it.get("summary"):
            story.append(Spacer(1, 2))
            story.append(Paragraph(f"智能体结论：{_esc(it['summary'])}", st["small"]))

        rf = it.get("readFiles") or []
        if rf:
            story.append(Paragraph(
                f"智能体自主取证 {len(rf)} 份文件：{_esc('、'.join(rf))}", st["small"]))

        els = it.get("elements") or []
        if els:
            rows = [[Paragraph("要素", st["cellb"]), Paragraph("判定", st["cellb"]),
                    Paragraph("证据文件", st["cellb"]), Paragraph("理由", st["cellb"])]]
            for e in els:
                v = e.get("verdict", "manual")
                vc = _RESULT_COLOR.get(v, colors.HexColor("#5b6b7f"))
                rows.append([
                    Paragraph(_esc(e.get("code", "")), st["cell"]),
                    Paragraph(f"<font color='#{_RESULT_HEX.get(v, '5b6b7f')}'><b>{_VERDICT_CN.get(v, v)}</b></font>", st["cell"]),
                    Paragraph(_esc("、".join(e.get("evidenceFiles") or []) or "—"), st["cell"]),
                    Paragraph(_esc(e.get("reason", "")), st["cell"]),
                ])
            t = Table(rows, colWidths=[16 * mm, 20 * mm, 44 * mm, 82 * mm], repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), brand),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d5deee")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAFE")]),
                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(Spacer(1, 2))
            story.append(t)

        for label, key in (("差距", "gaps"), ("整改建议", "remediation"), ("缺失证据", "missingEvidence")):
            vals = it.get(key) or []
            if vals:
                story.append(Spacer(1, 2))
                story.append(Paragraph(
                    f"{label}：" + "；".join(_esc(x) for x in vals), st["small"]))

    # 汇总
    story.append(Paragraph("二、汇总说明", st["h2"]))
    story.append(Paragraph(
        "本报告由 OpenClaw 合规自查智能体依据所选监管文件的检查清单、检查方法与三档判定要点生成。"
        "智能体自主完成证据取证与研判：自行判断相关文件、读取文本与图片（视觉识别）、"
        "调用取证工具逐字抽取 office 文档与音频转写（未经加工），再逐检查项给出结论。"
        "判定口径：任一要素不符合→检查项不符合；存在证据缺失→证据缺失；"
        "存在部分符合或需人工→部分符合；全部要素符合→符合。报告结论供内部自查参考，"
        "最终以监管认定与人工复核为准。", st["body"]))
    doc.build(story)
    return buf.getvalue()
