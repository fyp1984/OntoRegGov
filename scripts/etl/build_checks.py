#!/usr/bin/env python3
"""监管检查库扩展数据构建：金办发93号(139项) / 人行令3号(56条) / 金发8号(32项)。

输入（权威源材料）：
  /tmp/jg93-index.txt  知识库专题 md「检查项索引」段（源自附件2实测）
  /tmp/pboc3.html      gov.cn 官方公报页面（人行令〔2025〕第3号 全文）
  /tmp/jf8-norm.txt    金发〔2026〕8号 全文（NFKC 规范化）

输出：data/checks/{jg93,pboc3,jf8}-checks.json，结构与 jg24-checks.json 对齐
（id/title/priority/domain/domain_label/regulation/article_no/article_text/checklist…），
另带 doc_key/doc_no/doc_title 与 source_note（数据来源与口径说明）。

优先级为工程标注（映射自条款重要性，非官方字段），如实写入 source_note。
"""
from __future__ import annotations
import json, re, unicodedata
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent.parent / "data" / "checks"
OUT.mkdir(parents=True, exist_ok=True)

_CN = {"零":0,"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9}
def cn_to_int(s: str) -> int:
    s = s.replace("第", "").replace("条", "").replace("项", "").strip()
    if s.isdigit():
        return int(s)
    total = 0
    if "十" in s:
        left, _, right = s.partition("十")
        tens = (_CN.get(left, 1) if left else 1)
        total += tens * 10
        if right:
            total += _CN.get(right, 0)
        return total
    return _CN.get(s, 0)

def clean_wikilink(s: str) -> str:
    """去掉 [[pipia|PIPIA]] → PIPIA、[[gbt43697]] → gbt43697。"""
    return re.sub(r"\[\[[^\]|]*(?:\|([^\]|]*))?\]\]", lambda m: m.group(1) or m.group(0)[2:-2], s)

def build_jg93() -> list:
    txt = Path("/tmp/jg93-index.txt").read_text(encoding="utf-8")
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    checks = []
    # 章头：**一、数据安全治理（19）**
    chapter = None
    chap_map = {"一":"gov","二":"gov","三":"cross","四":"tech","五":"cross","六":"cross","七":"gov"}
    chap_title = {}
    cur_domain = "gov"
    for line in lines:
        m = re.match(r"^\*\*([一二三四五六七])、([^（]+)（(\d+)）\*\*$", line)
        if m:
            cn, name, cnt = m.groups()
            chapter = name
            cur_domain = chap_map.get(cn, "gov")
            chap_title[cn] = name
            continue
        if line.startswith("- "):
            body = line[2:]
            # N.子类名：子项；子项…
            mm = re.match(r"^(\d+)\.([^：]+)：(.+)$", body)
            if not mm:
                continue
            sub_no, sub_name, items = mm.groups()
            for it in re.split(r"；", items):
                it = it.strip().rstrip("。")
                im = re.match(r"^(\d+\.\d+)(.*)$", it)
                if not im:
                    continue
                code, title = im.groups()
                title = clean_wikilink(title).strip()
                priority = "P2" if title.endswith("其他") else ("P0" if sub_no in ("9","12","17") else "P1")
                checks.append({
                    "id": f"93-{code}",
                    "title": title,
                    "priority": priority,
                    "domain": cur_domain,
                    "domain_label": {"gov":"治理域","tech":"科技域","cross":"跨域"}[cur_domain],
                    "regulation": "附件2 自查整改情况表",
                    "article_no": code,
                    "article_text": f"{chapter}·{sub_no}.{sub_name}：{title}",
                    "chapter": chapter,
                    "doc_key": "jg93",
                })
    # 去重与校验：标准版139项 + 带监管版"七、监督管理/23.报告/23.1"1项 = 140
    seen = {}
    for c in checks:
        if c["id"] not in seen:
            seen[c["id"]] = c
    checks = list(seen.values())
    assert len(checks) == 140, f"jg93 期望140项（标准版139+带监管版23.1），实际{len(checks)}"
    return checks

def build_pboc3() -> list:
    raw = Path("/tmp/pboc3.html").read_bytes()
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError:
        html = raw.decode("gb18030")
    # 去标签但保留段落文本
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"</p>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unicodedata.normalize("NFKC", text)
    # 行首匹配条头（避免正文中"第四十五条予以处罚"等引用被误判）
    items: dict[int, tuple] = {}
    cur = None
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^第([一二三四五六七八九十百]+)条(?:\s*|　)(.*)$", line)
        if m:
            n = cn_to_int(m.group(1))
            if 1 <= n <= 56 and n not in items:
                cur = n
                # 条头行内的正文作为首段（单段条款正文与条头同行）
                items[n] = [f"第{m.group(1)}条", [m.group(2).strip()] if m.group(2).strip() else []]
            else:
                cur = None  # 重复/越界条头（页面尾部重复全文）不再收集
            continue
        if "相关稿件" in line:
            cur = None  # 页脚起始，停止条款正文收集
            continue
        if cur is not None and line:
            items[cur][1].append(line)
    checks_pre = []
    for n in sorted(items):
        no, body_lines = items[n]
        body = " ".join(body_lines).strip()
        first = re.split(r"[。；]", body)[0].strip()[:36]
        checks_pre.append((n, no, body, first))
    assert len(checks_pre) == 56, f"pboc3 期望56条，实际{len(checks_pre)}"
    # 章-域
    def domain_of(n):
        if n <= 5: return "gov", "第一章 总则"
        if n <= 13: return "gov", "第二章 业务数据分类分级与总体要求"
        if n <= 28: return "cross", "第三章 全流程业务数据安全管理要求"
        if n <= 38: return "tech", "第四章 全流程业务数据安全技术要求"
        if n <= 46: return "cross", "第五章 业务数据安全风险与事件管理"
        if n <= 53: return "gov", "第六章 法律责任"
        return "gov", "第七章 附则"
    P0 = {9,15,17,21,22,24,30,32,35,42,43,44,45}
    checks = []
    for n, no, body, first in checks_pre:
        dom, chap = domain_of(n)
        priority = "P0" if n in P0 else ("P2" if n >= 54 else "P1")
        checks.append({
            "id": f"pb3-{n}",
            "title": f"{no}：{first}",
            "priority": priority,
            "domain": dom,
            "domain_label": {"gov":"治理域","tech":"科技域","cross":"跨域"}[dom],
            "regulation": "中国人民银行令〔2025〕第3号",
            "article_no": no,
            "article_text": body.strip(),
            "chapter": chap,
            "doc_key": "pboc3",
        })
    return checks

def build_jf8() -> list:
    txt = Path("/tmp/jf8-norm.txt").read_text(encoding="utf-8")
    # 章节头：## 二、完善人工智能治理架构 / - (一)标题。正文（NFKC 后括号为半角）
    chap_dom = {
        "总体要求": "gov", "完善人工智能治理架构": "gov",
        "推进高水平人工智能开发应用": "tech", "提升数据治理能力": "cross",
        "加强智能算力建设": "tech", "完善人工智能风险治理框架": "cross",
        "提升人工智能安全开发应用能力": "tech", "保障与监督": "gov",
    }
    cur_dom = "gov"
    cur_chap = "总体要求"
    items = []
    pending = None  # (n, head, body_list, dom, chap)
    for raw in txt.splitlines():
        line = raw.strip()
        m = re.match(r"^## ([一二三四五六七八]、.+)", line)
        if m:
            name = m.group(1).split("、", 1)[1]
            cur_dom = chap_dom.get(name, "gov")
            cur_chap = name
            continue
        m2 = re.match(r"^[-–—]?\s*[（(]([一二三四五六七八九十]+)[）)]([^。]+)。(.*)$", line)
        if m2:
            cn, head, body = m2.groups()
            n = cn_to_int(cn)
            if 1 <= n <= 32:
                if pending:
                    pending[2].append(pending[3])
                pending = [n, head.strip(), [body.strip()], cur_dom, cur_chap]
                items.append(pending)
            continue
        # 续行（- 开头无编号 / 普通续行）追加到当前项正文
        if pending and line:
            cont = re.sub(r"^[-–—]\s*", "", line).strip()
            if cont:
                pending[2].append(cont)
    items.sort(key=lambda x: x[0])
    assert len(items) == 32, f"jf8 期望32项，实际{len(items)}"
    P0 = {16, 24, 25}
    P2 = {27, 28, 30, 31, 32}
    checks = []
    for n, head, body_parts, dom, chap in items:
        body = "".join(body_parts).strip()
        priority = "P0" if n in P0 else ("P2" if n in P2 else "P1")
        checks.append({
            "id": f"jf8-{n}",
            "title": f"（{cn_word(n)}）{head}",
            "priority": priority,
            "domain": dom,
            "domain_label": {"gov":"治理域","tech":"科技域","cross":"跨域"}[dom],
            "regulation": "金发〔2026〕8号",
            "article_no": f"第{n}项",
            "article_text": f"{head}。{body}".strip(),
            "chapter": chap,
            "doc_key": "jf8",
        })
    return checks

_CNW = ["零","一","二","三","四","五","六","七","八","九"]
def cn_word(n: int) -> str:
    if n < 10:
        return _CNW[n]
    if n < 20:
        return "十" + (_CNW[n - 10] if n > 10 else "")
    tens, ones = divmod(n, 10)
    return _CNW[tens] + "十" + (_CNW[ones] if ones else "")

DOC_META = {
    "jg93": {
        "doc_key": "jg93", "doc_no": "金办发〔2025〕93号",
        "doc_title": "金融机构数据安全管理能力提升专项行动通知（附件2 自查整改情况表）",
        "source_note": "检查项编号与标题源自附件2自查整改表实测（标准版139条 + 带监管检查方式版多'23.报告/23.1'1条 = 清单140条，见知识库专题索引；厂商'118条'为归并宣传口径）。领域为工程按六方面标注（一治理/二分类分级→治理域，三安全管理→跨域，四技术保护→科技域，五/六→跨域，七→治理域）；优先级为工程标注（P2=含'其他'项，P0=数据加工使用传输/转移提供公开/人工智能运用），非官方字段。",
    },
    "pboc3": {
        "doc_key": "pboc3", "doc_no": "人行令〔2025〕第3号",
        "doc_title": "中国人民银行业务领域数据安全管理办法",
        "source_note": "条文全文取自中国政府网 2025年第18号国务院公报（gov.cn/gongbao/2025/issue_12126/202506/content_7029666.html）。标题为条款首句概括；领域为工程按章标注（总则/分类分级/法律责任→治理域，全流程管理/风险事件→跨域，技术要求→科技域）；优先级为工程标注（P0=分类分级/收集/使用/提供/风险评估/出境/日志/存储/传输/年度评估/事件分级处置/合规审计等核心条款），非官方字段。",
    },
    "jf8": {
        "doc_key": "jf8", "doc_no": "金发〔2026〕8号",
        "doc_title": "国家金融监督管理总局关于银行业保险业人工智能安全开发应用的指导意见",
        "source_note": "32项指导意见全文取自本地保存的官方文本（2026-06-18 发布，NFKC 规范化）。领域为工程按八方面标注（总体/治理架构/保障与监督→治理域，开发应用/算力/能力提升→科技域，数据治理/风险治理→跨域）；优先级为工程标注（P0=高风险应用准入/数据安全与个保/网络防御），非官方字段。",
    },
}

if __name__ == "__main__":
    builders = {"jg93": build_jg93, "pboc3": build_pboc3, "jf8": build_jf8}
    for key, fn in builders.items():
        checks = fn()
        meta = DOC_META[key]
        out = {**meta, "generated_at": "2026-10-19", "counts": {
            "total": len(checks),
            "by_domain": {d: sum(1 for c in checks if c["domain"] == d)
                          for d in ("gov", "tech", "cross")},
            "by_priority": {p: sum(1 for c in checks if c["priority"] == p)
                            for p in ("P0", "P1", "P2")},
        }, "checks": checks}
        fp = OUT / f"{key}-checks.json"
        fp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[build] {fp.name}: {len(checks)} 项, domain={out['counts']['by_domain']}, priority={out['counts']['by_priority']}")
    print("完成。")
