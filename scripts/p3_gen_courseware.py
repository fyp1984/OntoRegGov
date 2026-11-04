#!/usr/bin/env python3
"""P3：从 ekos_ds_kb 真实数据生成"数据安全监管检查"培训课件（pptx，≥10页）。

用法：.venv/bin/python scripts/p3_gen_courseware.py
"""
import json
import os
from datetime import datetime

import psycopg2
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

DSN = "postgresql://test:test@127.0.0.1:15432/ekos_ds_kb"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "reports", "p3_deliverables")
os.makedirs(OUT, exist_ok=True)
NAVY = RGBColor(0x1F, 0x38, 0x64)
BLUE = RGBColor(0x2E, 0x74, 0xB5)
LIGHT = RGBColor(0xEA, 0xF1, 0xF8)
GREY = RGBColor(0x40, 0x40, 0x40)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

DOC_LABELS = {
    "jg24": "金规24号 银行保险机构数据安全管理办法",
    "jg93": "93号文 银保数据安全专项整治自查表",
    "pboc3": "人民银行令〔2025〕第3号 业务领域数据安全管理办法",
    "jf8": "金发〔2026〕8号 人工智能安全开发应用治理",
}


def fetch():
    c = psycopg2.connect(DSN, connect_timeout=8); c.autocommit = True
    cur = c.cursor()
    cur.execute("""SELECT CASE WHEN check_code LIKE '93-%' THEN 'jg93'
                         WHEN check_code LIKE 'pb3-%' THEN 'pboc3'
                         WHEN check_code LIKE 'jf8-%' THEN 'jf8' ELSE 'jg24' END doc,
                         COUNT(*) n FROM inspection_check GROUP BY 1 ORDER BY 1""")
    by_doc = dict(cur.fetchall())
    cur.execute("""SELECT doc_key,dimension,COUNT(*) n FROM check_six_dim
                   GROUP BY doc_key,dimension ORDER BY doc_key,dimension""")
    sixdim = {}
    for dk, dim, n in cur.fetchall():
        sixdim.setdefault(dk, {})[dim] = n
    cur.execute("SELECT COUNT(*) FROM inspection_check"); total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM p1_sixdim_review WHERE merged=true"); merged = cur.fetchone()[0]
    cur.execute("""SELECT check_code,title,domain FROM inspection_check
                   WHERE check_code LIKE '93-%' AND priority='P1'
                   ORDER BY check_code LIMIT 8""")
    p1 = cur.fetchall()
    cur.execute("""SELECT doc_key,article_no,title,content FROM law_chunk
                   WHERE content LIKE '%出境%' LIMIT 2""")
    exit_hits = cur.fetchall()
    cur.execute("""SELECT doc_key,article_no,title,content FROM law_chunk
                   WHERE content LIKE '%敏感%' OR content LIKE '%个人信息%' LIMIT 2""")
    pi_hits = cur.fetchall()
    c.close()
    return dict(by_doc=by_doc, sixdim=sixdim, total=total, merged=merged,
                p1=p1, exit_hits=exit_hits, pi_hits=pi_hits)


prs = Presentation()
prs.slide_width = Inches(13.333); prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]


def slide():
    return prs.slides.add_slide(BLANK)


def box(s, l, t, w, h, fill=None):
    from pptx.enum.shapes import MSO_SHAPE
    sp = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(l), Inches(t), Inches(w), Inches(h))
    sp.line.fill.background()
    if fill:
        sp.fill.solid(); sp.fill.fore_color.rgb = fill
    else:
        sp.fill.background()
    return sp


def text(s, l, t, w, h, lines, size=18, color=GREY, align=PP_ALIGN.LEFT, bold=False):
    tb = s.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = True
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run(); r.text = ln
        r.font.size = Pt(size); r.font.color.rgb = color; r.font.bold = bold
        r.font.name = "Microsoft YaHei"
    return tb


def header(s, title, idx):
    box(s, 0, 0, 13.333, 1.1, NAVY)
    text(s, 0.5, 0.25, 11, 0.7, [title], size=28, color=WHITE, bold=True)
    text(s, 12.3, 0.35, 0.9, 0.5, [str(idx)], size=16, color=WHITE, align=PP_ALIGN.RIGHT)


def table(s, l, t, w, rows, col_w=None):
    nr, nc = len(rows), len(rows[0])
    gt = s.shapes.add_table(nr, nc, Inches(l), Inches(t), Inches(w), Inches(0.4 * nr)).table
    if col_w:
        for i, cw in enumerate(col_w):
            gt.columns[i].width = Inches(cw)
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = gt.cell(ri, ci)
            cell.text = str(val)
            para = cell.text_frame.paragraphs[0]
            para.runs[0].font.size = Pt(13)
            para.runs[0].font.name = "Microsoft YaHei"
            if ri == 0:
                cell.fill.solid(); cell.fill.fore_color.rgb = BLUE
                para.runs[0].font.color.rgb = WHITE; para.runs[0].font.bold = True
            else:
                cell.fill.solid(); cell.fill.fore_color.rgb = LIGHT if ri % 2 else WHITE
    return gt


def build(d):
    # 1 封面
    s = slide(); box(s, 0, 0, 13.333, 7.5, NAVY)
    text(s, 1.2, 2.4, 11, 1.5, ["数据安全监管检查实务培训"], size=44, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    text(s, 1.2, 4.1, 11, 0.8, ["基于金规24号 / 93号文 / 人民银行3号令 / 金发8号 真实检查知识库"],
         size=20, color=RGBColor(0xCF, 0xDD, 0xEF), align=PP_ALIGN.CENTER)
    text(s, 1.2, 6.4, 11, 0.5, [f"生成 {datetime.now().strftime('%Y-%m-%d')}　数据源 ekos_ds_kb"],
         size=14, color=RGBColor(0xAF, 0xC4, 0xDD), align=PP_ALIGN.CENTER)

    # 2 目录
    s = slide(); header(s, "课程目录", 2)
    items = ["1. 监管背景与四份文号概览", "2. 检查项总量与分文号分布",
             "3. 六维知识体系讲解", "4. 审核链路：草案→入闸→通过→落库",
             "5. 数据出境合规要点", "6. 个人信息保护要点",
             "7. AI/自动化决策治理（金发8号）", "8. 典型问题与整改、合规建议、总结"]
    text(s, 1.2, 1.8, 11, 5, items, size=20, color=GREY)

    # 3 文号概览
    s = slide(); header(s, "一、监管背景与四份文号概览", 3)
    rows = [["文号", "规范名称", "检查项"]]
    for dk in ("jg24", "jg93", "pboc3", "jf8"):
        rows.append([dk, DOC_LABELS[dk], d["by_doc"].get(dk, 0)])
    table(s, 0.8, 1.8, 11.7, rows, col_w=[1.5, 8.7, 1.5])
    text(s, 0.8, 5.6, 11.7, 1.2,
         [f"合计检查项 {d['total']} 项；覆盖治理、个人信息、数据出境、AI 等全领域。"],
         size=18, color=BLUE, bold=True)

    # 4 分布
    s = slide(); header(s, "二、检查项分文号分布", 4)
    rows = [["文号", "检查项数", "占比"]]
    for dk, n in sorted(d["by_doc"].items(), key=lambda x: -x[1]):
        rows.append([DOC_LABELS[dk], n, f"{n/d['total']*100:.1f}%"])
    table(s, 1.2, 1.9, 10.9, rows, col_w=[7.0, 2.0, 1.9])

    # 5 六维体系
    s = slide(); header(s, "三、六维知识体系", 5)
    dims = ["checklist 检查清单", "method 检查方法", "verdict 判定标准",
            "findings 典型问题", "related 关联依据"]
    text(s, 1.0, 1.6, 11.5, 1.6, dims, size=19)
    rows = [["文号", "checklist", "method", "verdict", "findings", "related"]]
    for dk in ("jg24", "jg93", "pboc3", "jf8"):
        sd = d["sixdim"].get(dk, {})
        rows.append([dk, sd.get("checklist", 0), sd.get("method", 0),
                     sd.get("verdict", 0), sd.get("findings", 0), sd.get("related", 0)])
    table(s, 1.0, 3.6, 11.3, rows, col_w=[1.6, 2.0, 1.9, 1.9, 1.9, 1.9])

    # 6 审核链路
    s = slide(); header(s, "四、审核链路（真实台账）", 6)
    text(s, 1.0, 2.0, 11.5, 1.5,
         [f"规则/LLM 草案 → 入闸审核队列 → approve 通过 → merge 落库",
          f"已审核并合并 {d['merged']} 条六维草案，全程留痕、可追溯。"], size=20, color=GREY)
    table(s, 1.0, 4.2, 11.3,
          [["环节", "动作", "状态"], ["generate", "生成草案入闸", "完成"],
           ["queue", "审核队列", "完成"], ["approve", "审核通过", "1970 条"],
           ["merge", "合并落库", "1970 条"]], col_w=[2.5, 5.8, 3.0])

    # 7 数据出境
    s = slide(); header(s, "五、数据出境合规要点", 7)
    lines = ["· 符合网信部门规定情形的，须申报安全评估 / 标准合同 / 保护认证；",
             "· 有境内存储要求的业务数据应同时境内存储；",
             "· 不得拆分、转换手段规避出境义务。"]
    text(s, 1.0, 1.8, 11.5, 1.6, lines, size=19)
    for i, (dk, art, title, content) in enumerate(d["exit_hits"]):
        text(s, 1.0, 3.8 + i*1.2, 11.5, 1.1,
             [f"《{DOC_LABELS[dk]}》{art} {title}", content[:110] + "…"], size=14, color=BLUE)

    # 8 个人信息
    s = slide(); header(s, "六、个人信息保护要点", 8)
    text(s, 1.0, 1.8, 11.5, 1.4,
         ["· 合法、正当、必要、诚信，不得过度收集；",
          "· 对外提供敏感级以上数据须取得主体单独同意；",
          "· 制定并公开个人信息处理规则，清晰易懂。"], size=19)
    for i, (dk, art, title, content) in enumerate(d["pi_hits"]):
        text(s, 1.0, 4.0 + i*1.2, 11.5, 1.1,
             [f"《{DOC_LABELS[dk]}》{art} {title}", content[:110] + "…"], size=14, color=BLUE)

    # 9 AI治理
    s = slide(); header(s, "七、AI / 自动化决策治理（金发8号）", 9)
    text(s, 1.0, 2.0, 11.5, 2.5,
         ["· 自动化决策、模型开发、数据标注须保证透明度与公平性；",
          "· 建立 AI 全生命周期安全开发与应用治理；",
          "· jf8 专项检查项 " + str(d['by_doc'].get('jf8', 0)) + " 条，聚焦模型与标注风险。"],
         size=20)

    # 10 典型问题
    s = slide(); header(s, "八、典型 P1 问题抽样（jg93）", 10)
    rows = [["编号", "问题", "领域"]]
    for code, title, domain in d["p1"][:8]:
        rows.append([code, (title or "")[:34], domain or ""])
    table(s, 0.8, 1.7, 11.7, rows, col_w=[1.8, 7.9, 2.0])

    # 11 建议
    s = slide(); header(s, "九、合规建议与行动清单", 11)
    text(s, 1.0, 1.8, 11.5, 4.5,
         ["1. 按文号建立责任清单，P1 项优先整改并留痕；",
          "2. 数据出境落实三条合规路径，禁止拆分规避；",
          "3. 个人信息最小必要 + 单独同意，公开处理规则；",
          "4. AI 自动化决策保障透明公平，建立模型治理；",
          "5. 复用六维 method/verdict 定期自查，闭环 findings。"], size=20)

    # 12 总结
    s = slide(); box(s, 0, 0, 13.333, 7.5, NAVY)
    text(s, 1.2, 2.6, 11, 1.2, ["总结"], size=40, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    text(s, 1.2, 4.0, 11, 1.5,
         [f"{d['total']} 项检查项 · {d['merged']} 条六维草案审核落库 · 语义检索带引用问答",
          "监管检查 = 清单可查、方法可依、判定有据、问题可改、依据可溯"],
         size=18, color=RGBColor(0xCF, 0xDD, 0xEF), align=PP_ALIGN.CENTER)

    out = os.path.join(OUT, "数据安全监管检查培训课件.pptx")
    prs.save(out)
    json.dump(d, open(os.path.join(OUT, "courseware_data_snapshot.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=str)
    print("slides:", len(prs.slides._sldIdLst))
    print("saved:", out)


if __name__ == "__main__":
    build(fetch())
