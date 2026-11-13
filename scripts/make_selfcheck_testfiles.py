# -*- coding: utf-8 -*-
"""生成合规自查端到端测试文件集（samples/selfcheck-evidence/）。

覆盖场景（对应金规〔2024〕24号 1.1 党委（党组）、董（理）事会主体责任 等检查项）：
- 合规证据：总纲（含主体责任条款）、董事会会议纪要（审议数据安全议题+具体决策）、
  年度议题清单 xlsx（含数据安全）、任命文件 docx、组织架构说明
- 部分符合：议事规则未提数据安全
- 不合规证据：旧版制度（仅写"公司领导层负责"）
- 干扰项：无关文件（放假通知）、无法解析类型占位（架构图 png、录音 mp3 占位）
- 压缩包证据：zip 内含 txt 纪要
测试数据全部虚构，仅作自查功能验证；后续可替换为用户真实文档集。
"""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "samples" / "selfcheck-evidence"
(ROOT / "制度文件").mkdir(parents=True, exist_ok=True)
(ROOT / "会议纪要").mkdir(parents=True, exist_ok=True)
(ROOT / "签批与议题").mkdir(parents=True, exist_ok=True)
(ROOT / "其他材料").mkdir(parents=True, exist_ok=True)


def w(p: Path, text: str):
    p.write_text(text, encoding="utf-8")
    print("wrote", p)


# ---------- 1. 数据安全管理总纲（docx，合规：明确主体责任） ----------
from docx import Document
from docx.shared import Pt

d = Document()
d.add_heading("数据安全管理总纲", 0)
d.add_paragraph("（虚构测试数据 · XX银行数据安全委员会 2025年3月印发 · 编号 数安〔2025〕1号）")
d.add_heading("第一章 总则", 1)
d.add_paragraph("第一条 为规范全行数据安全管理，依据《银行保险机构数据安全管理办法》"
                "（金规〔2024〕24号）等监管要求，制定本总纲。")
d.add_heading("第二章 组织架构与职责", 1)
d.add_paragraph("第二条 本行建立数据安全责任制，党委（党组）、董事会对本单位数据安全工作负主体责任。"
                "行长为数据安全第一责任人，明确各层级负责人的责任，明确违规情形和责任追究事项，"
                "落实问责处置机制。")
d.add_paragraph("第三条 数据安全管理委员会（下称'数据安全委'）由第一责任人（行长）牵头，"
                "信息科技部、风险管理部、内控合规部、各业务部门负责人参加，"
                "负责数据安全重大事项审议与协调。")
d.add_paragraph("第四条 信息科技部为数据安全归口管理部门，负责技术防护体系建设与日常运营。")
d.add_paragraph("第五条 各业务领域数据安全管理责任由业务部门承担，'谁使用、谁负责'。")
d.add_heading("第三章 数据分类分级", 1)
d.add_paragraph("第六条 本行数据按重要程度分为核心数据、重要数据、一般数据三类，"
                "实施差异化防护。个人金融信息按敏感程度分级管理。")
d.add_heading("第四章 问责", 1)
d.add_paragraph("第七条 对违反本总纲造成数据安全事件的，按照本行问责办法追究相关层级负责人责任。")
for para in d.paragraphs:
    para.style.font.size = Pt(11)
p1 = ROOT / "制度文件" / "数据安全管理总纲.docx"
d.save(str(p1))
print("wrote", p1)

# ---------- 2. 旧版制度（不合规：仅笼统"领导层负责"） ----------
w(ROOT / "制度文件" / "信息科技管理制度（2021旧版·未对标）.md", """# 信息科技管理制度（2021 旧版）

> 虚构测试数据。本文件故意不合规：仅笼统表述"公司领导层负责"，未对标 §10。

## 职责

公司领导层负责信息科技工作的总体管理，信息科技部承担具体执行职责。
数据安全作为技术工作的一部分，由信息科技部负责落实。
""")

# ---------- 3. 董事会会议纪要（合规：审议数据安全+具体决策） ----------
w(ROOT / "会议纪要" / "2025年第3次董事会会议纪要（审议数据安全）.md", """# XX银行第五届董事会2025年第3次会议纪要

（虚构测试数据 · 2025年4月18日 · 会议室A）

## 议题二：审议《数据安全管理总纲》

董事会听取了第一责任人关于数据安全工作体系的汇报，审议《数据安全管理总纲（送审稿）》。

**决议**：
1. 原则通过《数据安全管理总纲》，确认党委（党组）、董事会对本行数据安全工作负主体责任；
2. 批准设立数据安全管理委员会，由第一责任人（行长）牵头；
3. 责成管理层于2025年6月底前完成个人客户信息分级防护专项整改，预算 380 万元。

表决结果：同意 9 票，反对 0 票，弃权 1 票。

签批：董事长（手写签批）：同意，按此落实。——2025.4.18
""")

w(ROOT / "会议纪要" / "2025年第2次党委会会议纪要.md", """# XX银行2025年第2次党委会会议纪要

（虚构测试数据 · 2025年3月7日）

## 议题四：研究本行数据安全工作重大事项

会议听取了信息科技部关于落实金规〔2024〕24号文的汇报。会议要求：
1. 将数据安全纳入党委主体责任清单；
2. 党委每半年听取一次数据安全工作汇报；
3. 同意《数据安全管理总纲》提交董事会审议。

签批记录：党委书记签批"同意，提交董事会审议"。
""")

w(ROOT / "会议纪要" / "2024年第1次董事会会议纪要（无关议题）.md", """# XX银行第五届董事会2024年第1次会议纪要

（虚构测试数据 · 2024年1月20日）

议题一：审议2023年度财务报告。
议题二：审议高管2023年度薪酬方案。
议题三：讨论春节放假安排。

（本纪要不含数据安全相关内容——用于测试"无关文件干扰"场景。）
""")

# ---------- 4. 年度议题清单（xlsx，合规：数据安全已列入） ----------
from openpyxl import Workbook

wb = Workbook()
ws = wb.active
ws.title = "2025年度董事会议题清单"
ws.append(["序号", "议题", "提案部门", "计划时间", "状态"])
ws.append([1, "2024年度报告", "董办", "2025-03", "已审议"])
ws.append([2, "数据安全工作体系与总纲审议", "信息科技部", "2025-04", "已审议"])
ws.append([3, "个人客户信息分级防护专项整改汇报", "信息科技部", "2025-09", "计划中"])
ws.append([4, "信息科技外包风险专题", "风险管理部", "2025-11", "计划中"])
wb.save(str(ROOT / "签批与议题" / "2025年度董事会议题清单.xlsx"))
print("wrote 2025年度董事会议题清单.xlsx")

# ---------- 5. 任命文件（docx） ----------
d2 = Document()
d2.add_heading("关于任命数据安全第一责任人及高管分工调整的通知", 1)
d2.add_paragraph("（虚构测试数据 · 人字〔2025〕12号）")
d2.add_paragraph("各部门：根据《数据安全管理总纲》（数安〔2025〕1号），经党委研究、董事会批准："
                "任命张某某（行长）为本行数据安全第一责任人。"
                "根据高管分工，李某某同志负责信息科技领域日常工作。")
p5 = ROOT / "签批与议题" / "数据安全责任人任命文件.docx"
d2.save(str(p5))

# ---------- 6. 议事规则（部分符合：未提数据安全） ----------
w(ROOT / "制度文件" / "董事会议事规则（未含数据安全条款）.md", """# 董事会议事规则（节选）

（虚构测试数据）

第五条 董事会审议年度经营计划、投资方案、财务预决算、高管聘任等事项。
第六条 董事会设立审计与风险管理委员会。

（本规则未明确列举数据安全议题——用于"部分符合"测试。）
""")

# ---------- 7. 干扰/占位文件 ----------
w(ROOT / "其他材料" / "关于2025年国庆节放假安排的通知.txt", """关于2025年国庆节放假安排的通知（虚构测试数据）
10月1日至7日放假，共7天。各部门做好值班安排。
""")

# ---------- 7b. 真实组织架构示意图（PNG，含可读文字，供智能体视觉识别） ----------
from PIL import Image, ImageDraw, ImageFont

FONT = "C:/Windows/Fonts/msyh.ttc"

def font(sz, bold=False):
    try:
        return ImageFont.truetype(FONT, sz, index=0)
    except Exception:
        return ImageFont.truetype("C:/Windows/Fonts/simhei.ttf", sz)

W, Hh = 1200, 900
img = Image.new("RGB", (W, Hh), "white")
dr = ImageDraw.Draw(img)

def box(x, y, w_, h_, text, f, outline="#333333", fill="#EAF2FA"):
    dr.rounded_rectangle([x, y, x + w_, y + h_], radius=10, fill=fill, outline=outline, width=2)
    lines = text.split("\n")
    th = len(lines) * (f.size + 6)
    ty = y + (h_ - th) // 2
    for ln in lines:
        tw = dr.textlength(ln, font=f)
        dr.text((x + (w_ - tw) // 2, ty), ln, font=f, fill="#111111")
        ty += f.size + 6

def line(x1, y1, x2, y2):
    dr.line([x1, y1, x2, y2], fill="#555555", width=2)

f1, f2, f3 = font(26, True), font(22, True), font(19)
dr.text(((W - dr.textlength("XX银行数据安全组织架构图（虚构示意）", font=f1)) // 2, 18),
        "XX银行数据安全组织架构图（虚构示意）", font=f1, fill="#111111")

# 治理层
box(330, 70, 540, 70, "党委 / 董事会\n（数据安全工作负主体责任）", f2, fill="#FDEBD0")
# 第一责任人
box(400, 180, 400, 56, "第一责任人：张某某（行长）", f2, fill="#D6EAF8")
line(600, 140, 600, 180)
# 数据安全委
box(380, 276, 440, 56, "数据安全管理委员会（牵头：第一责任人·行长）", f3, fill="#D6EAF8")
line(600, 236, 600, 276)
# 归口部门
box(150, 380, 300, 64, "归口管理部门\n信息科技部（陈某某）", f3, fill="#D5F5E3")
line(600, 332, 300, 380)
# 业务与监督部门
row_y = 500
for i, (t, col) in enumerate([("数据安全防护\n运营组", "#E8DAEF"), ("风险条线\n数据安全监督", "#E8DAEF"),
                              ("审计监督\n内审部", "#E8DAEF")]):
    x = 90 + i * 380
    box(x, row_y, 320, 64, t, f3, fill=col)
    line(300, 444, x + 160, row_y)
# 汇报线标注
dr.text((620, 460), "汇报线：信息科技部 → 分管副行长 → 行长", font=f3, fill="#8E44AD")
# 说明
dr.text((90, 620), "说明：本图为虚构测试数据，仅用于合规自查功能验证。", font=font(18), fill="#666666")
dr.text((90, 655), "分管信息科技副行长：李某某；数据安全委办公室设在信息科技部。", font=font(18), fill="#666666")

p_png = ROOT / "其他材料" / "组织架构示意图.png"
img.save(str(p_png))
print("wrote", p_png)


# ---------- 7c. 真实党委会录音（MP3，qwen3-tts-flash 合成，供 ASR 转写核查） ----------
import base64 as _b64
import json as _json
import os as _os
import subprocess as _sp
import urllib.request as _rq

MAAS_BASE = "https://llm-x2b28e85g4rs2bw0.cn-beijing.maas.aliyuncs.com"
MAAS_KEY = "sk-34ed3e6fe9284409b9e484ce58a24c28"

RECORD_SCRIPT = """XX银行2025年第2次党委会会议录音节选，虚构测试数据。
党委书记：今天议题四，研究本行数据安全工作重大事项。请信息科技部汇报落实金规〔2024〕24号文的情况。
信息科技部负责人：已起草数据安全管理总纲，明确党委和董事会负主体责任，行长为第一责任人。总纲已按党委要求纳入主体责任清单，现提请提交董事会审议。
党委书记：同意。要求党委每半年听取一次数据安全工作汇报。另外，信息科技领域日常工作由分管信息科技的李副行长负责。散会。"""

def tts_synth(text, out_mp3):
    payload = {"model": "qwen3-tts-flash", "input": {"text": text, "voice": "Dylan",
                 "language_type": "Chinese"}}
    req = _rq.Request(MAAS_BASE + "/api/v1/services/aigc/multimodal-generation/generation",
                      data=_json.dumps(payload).encode("utf-8"),
                      headers={"Authorization": "Bearer " + MAAS_KEY,
                               "Content-Type": "application/json"})
    with _rq.urlopen(req, timeout=120) as r:
        url = _json.load(r)["output"]["audio"]["url"]
    wav = _rq.urlopen(url, timeout=120).read()
    tmp_wav = out_mp3 + ".tmp.wav"
    open(tmp_wav, "wb").write(wav)
    ff = _os.environ.get("FFMPEG", "ffmpeg")
    _sp.run([ff, "-y", "-i", tmp_wav, "-codec:a", "libmp3lame", "-b:a", "96k", out_mp3],
            check=True, capture_output=True)
    _os.remove(tmp_wav)

p_mp3 = ROOT / "其他材料" / "数据安全专题党委会录音.mp3"
try:
    tts_synth(RECORD_SCRIPT, str(p_mp3))
    print("wrote", p_mp3, p_mp3.stat().st_size, "bytes")
except Exception as e:  # 网络/凭证不可用时保留占位，不阻断整个文件集生成
    p_mp3.write_bytes(b"ID3\x03\x00" + b"\x00" * 300)
    print("WARN tts failed, placeholder kept:", str(e)[:120])
w(ROOT / "其他材料" / "开发文档-客户信息查询接口.md", """# 客户信息查询接口开发文档（虚构）

接口 GET /api/customer/info 返回客户姓名、手机号（明文）。
> 注：未做脱敏——可用于 3.x 技术域检查项的"不符合"测试。
""")

# ---------- 8. zip 压缩包证据 ----------
zpath = ROOT / "其他材料" / "历史会议纪要存档.zip"
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("2023年第5次董事会纪要.txt",
               "审议信息科技三年规划，未涉及数据安全专项议题。（虚构测试数据）")
    z.writestr("2024年第4次党委会纪要.txt",
               "议题：学习数据安全法规，要求建立责任制，纳入下次董事会议题。（虚构测试数据）")
print("wrote", zpath)

print("\n测试文件集生成完毕：", ROOT)
