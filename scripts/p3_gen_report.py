#!/usr/bin/env python3
"""P3：从 ekos_ds_kb 真实数据生成监管检查/数据安全合规分析报告（docx）。

所有数字/清单均实时查库，不写死；产物落 reports/p3_deliverables/。
用法：.venv/bin/python scripts/p3_gen_report.py
"""
import json
import os
from datetime import datetime

import psycopg2
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

DSN = "postgresql://test:test@127.0.0.1:15432/ekos_ds_kb"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "reports", "p3_deliverables")
os.makedirs(OUT, exist_ok=True)

DOC_LABELS = {
    "jg24": "金规24号 银行保险机构数据安全管理办法",
    "jg93": "93号文 银保数据安全专项整治自查表",
    "pboc3": "人民银行令〔2025〕第3号 业务领域数据安全管理办法",
    "jf8": "金发〔2026〕8号 人工智能安全开发应用治理",
}
DOC_PREFIX = {"jg93": "93-", "pboc3": "pb3-", "jf8": "jf8-"}


def conn():
    c = psycopg2.connect(DSN, connect_timeout=8)
    c.autocommit = True
    return c


def fetch():
    db = conn()
    cur = db.cursor()
    # 分文号检查项
    cur.execute("""SELECT CASE WHEN check_code LIKE '93-%' THEN 'jg93'
                         WHEN check_code LIKE 'pb3-%' THEN 'pboc3'
                         WHEN check_code LIKE 'jf8-%' THEN 'jf8' ELSE 'jg24' END doc,
                         COUNT(*) n FROM inspection_check GROUP BY 1 ORDER BY 1""")
    by_doc = {r[0]: r[1] for r in cur.fetchall()}
    # 六维
    cur.execute("""SELECT doc_key,dimension,COUNT(*) n FROM check_six_dim
                   GROUP BY doc_key,dimension ORDER BY doc_key,dimension""")
    sixdim = {}
    for dk, dim, n in cur.fetchall():
        sixdim.setdefault(dk, {})[dim] = n
    # 审核台账
    cur.execute("SELECT status,COUNT(*),BOOL_AND(merged) FROM p1_sixdim_review GROUP BY status")
    review = cur.fetchall()
    # 优先级分布
    cur.execute("""SELECT CASE WHEN check_code LIKE '93-%' THEN 'jg93'
                          WHEN check_code LIKE 'pb3-%' THEN 'pboc3'
                          WHEN check_code LIKE 'jf8-%' THEN 'jf8' ELSE 'jg24' END doc,
                          priority,COUNT(*) n FROM inspection_check
                   GROUP BY 1,2 ORDER BY 1,2""")
    priority = cur.fetchall()
    # P1 重点问题抽样（jg93 自查问题，真实标题）
    cur.execute("""SELECT check_code,title,domain,article_no FROM inspection_check
                   WHERE check_code LIKE '93-%' AND priority='P1'
                   ORDER BY check_code LIMIT 12""")
    p1_items = cur.fetchall()
    # 检索要点：数据出境/个人信息/自动化决策（law_chunk top1，无 TEI 直接取引用行）
    cur.execute("""SELECT doc_key,article_no,title,content FROM law_chunk
                   WHERE content LIKE '%出境%' ORDER BY chunk_id LIMIT 3""")
    exit_hits = cur.fetchall()
    cur.execute("""SELECT doc_key,article_no,title,content FROM law_chunk
                   WHERE content LIKE '%敏感%' OR content LIKE '%个人信息%'
                   ORDER BY chunk_id LIMIT 3""")
    pi_hits = cur.fetchall()
    # 总量
    cur.execute("SELECT COUNT(*) FROM inspection_check"); total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM kb_embedding"); emb = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM law_chunk"); lc = cur.fetchone()[0]
    db.close()
    return dict(by_doc=by_doc, sixdim=sixdim, review=review, priority=priority,
                p1_items=p1_items, exit_hits=exit_hits, pi_hits=pi_hits,
                total=total, emb=emb, lc=lc)


def build(data):
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Microsoft YaHei"
    style.font.size = Pt(10.5)

    h = doc.add_heading("银行保险机构数据安全监管检查合规分析报告", level=0)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　"
                          "数据来源：ekos_ds_kb 真实库（inspection_check/check_six_dim/"
                          "p1_sixdim_review/law_chunk）")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_heading("一、执行摘要", level=1)
    doc.add_paragraph(
        f"本次纳入监管检查项共 {data['total']} 项，覆盖金规24号、93号文专项整治、"
        f"人民银行3号令、金发8号AI治理四份文号；六维知识经审核链路全部落库，"
        f"审核台账 {data['review'][0][1]} 条草案已 {data['review'][0][0]} 并合并；"
        f"检查项向量化 {data['emb']} 条、法规原文片段 {data['lc']} 条，"
        "支持语义检索与带引用问答。")

    doc.add_heading("二、检查项分文号统计", level=1)
    t = doc.add_table(rows=1, cols=3); t.style = "Light Grid Accent 1"
    t.rows[0].cells[0].text, t.rows[0].cells[1].text, t.rows[0].cells[2].text = "文号", "名称", "检查项数"
    for dk, n in sorted(data["by_doc"].items(), key=lambda x: -x[1]):
        row = t.add_row().cells
        row[0].text, row[1].text, row[2].text = dk, DOC_LABELS[dk], str(n)

    doc.add_heading("三、六维知识覆盖分析", level=1)
    t = doc.add_table(rows=1, cols=6); t.style = "Light Grid Accent 1"
    hdr = ["文号", "checklist", "method", "verdict", "findings", "related"]
    for i, x in enumerate(hdr):
        t.rows[0].cells[i].text = x
    for dk in ("jg24", "jg93", "pboc3", "jf8"):
        sd = data["sixdim"].get(dk, {})
        row = t.add_row().cells
        row[0].text = dk
        for i, dim in enumerate(hdr[1:], start=1):
            row[i].text = str(sd.get(dim, 0))

    doc.add_heading("四、审核台账概况", level=1)
    for status, n, merged in data["review"]:
        doc.add_paragraph(f"· 状态 {status}：{n} 条，全部已合并落库={bool(merged)}",
                          style="List Bullet")

    doc.add_heading("五、重点领域合规要点（带法规引用）", level=1)
    doc.add_heading("5.1 数据出境", level=2)
    for dk, art, title, content in data["exit_hits"]:
        doc.add_paragraph(f"《{DOC_LABELS[dk]}》{art} {title}：{content[:120]}…",
                          style="List Bullet")
    doc.add_heading("5.2 个人信息保护", level=2)
    for dk, art, title, content in data["pi_hits"]:
        doc.add_paragraph(f"《{DOC_LABELS[dk]}》{art} {title}：{content[:120]}…",
                          style="List Bullet")

    doc.add_heading("六、重点问题清单（jg93 P1 抽样）", level=1)
    t = doc.add_table(rows=1, cols=4); t.style = "Light Grid Accent 1"
    for i, x in enumerate(["编号", "问题", "领域", "条号"]):
        t.rows[0].cells[i].text = x
    for code, title, domain, art in data["p1_items"]:
        row = t.add_row().cells
        row[0].text, row[1].text, row[2].text, row[3].text = code, title or "", domain or "", art or ""

    doc.add_heading("七、合规建议", level=1)
    for rec in [
        "按四份文号建立分领域责任清单，P1 项优先整改并留痕；",
        "数据出境场景落实安全评估/标准合同/保护认证路径，禁止拆分规避；",
        "个人信息处理遵循最小必要、告知同意，敏感信息单独同意；",
        "自动化决策保证透明度与公平性，建立模型与标注治理；",
        "定期复用六维 method/verdict 开展自查，闭环 findings 整改。",
    ]:
        doc.add_paragraph(rec, style="List Number")

    out = os.path.join(OUT, "数据安全监管检查合规分析报告.docx")
    doc.save(out)
    # 数据快照证据
    snap = os.path.join(OUT, "report_data_snapshot.json")
    json.dump(data, open(snap, "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
    print("saved:", out)
    print("snapshot:", snap)


if __name__ == "__main__":
    build(fetch())
