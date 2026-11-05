#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把知识库静态站点 styles.css 自动作用域化到 .kbsite 容器，输出 app/web/static/kb_site.css。

只做机械变换，不改任何声明值：
  :root / html / body   -> .kbsite
  *                     -> .kbsite *
  其它选择器             -> .kbsite <选择器>
  @media 内的选择器同样加前缀；@media 头保持原样。

用法：
    python3 scripts/kb_site/gen_kb_site_css.py
其中样式源可用环境变量 KB_SITE_SRC 覆盖（默认取历史知识站点构建产物）。
"""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.environ.get(
    "KB_SITE_SRC",
    "/Users/FYP/Documents/@西北人的成长/20-Areas/信息安全/数据安全/"
    "10_知识库工程/site/assets/styles.css",
)
DST = os.path.join(REPO, "app", "web", "static", "kb_site.css")


def strip_comments(s: str) -> str:
    return re.sub(r"/\*.*?\*/", "", s, flags=re.S)


def parse_blocks(s: str):
    """把 CSS 拆成 [(header, body), ...]，header 为 '{' 之前的选择器/at-rule。"""
    blocks = []
    i, n = 0, len(s)
    while i < n:
        b = s.find("{", i)
        if b < 0:
            break
        header = s[i:b].strip()
        depth, j = 1, b + 1
        while j < n and depth > 0:
            c = s[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            j += 1
        body = s[b + 1 : j - 1]
        if header:
            blocks.append((header, body))
        i = j
    return blocks


def prefix(sel: str) -> str:
    outs, seen = [], set()
    for p in sel.split(","):
        p = p.strip()
        if not p:
            continue
        if p in (":root", "html", "body"):
            q = ".kbsite"
        elif p == "*":
            q = ".kbsite *"
        else:
            q = ".kbsite " + p
        if q not in seen:
            seen.add(q)
            outs.append(q)
    return ", ".join(outs)


def render(blocks, indent=0):
    pad = "  " * indent
    out = []
    for header, body in blocks:
        if header.startswith("@"):
            out.append(pad + header + " {\n" + render(parse_blocks(body), indent + 1) + pad + "}")
        else:
            out.append(pad + prefix(header) + " {" + body + "}")
    return "\n".join(out) + "\n"


HEADER = """/* ============================================================
   数据安全知识库（菜单 1 站点）样式 —— 自动作用域化产物，请勿手改。
   来源：10_知识库工程/site/assets/styles.css
   生成：见 scripts/kb_site/gen_kb_site_css.py（机械加 .kbsite 前缀，未改任何声明值）
   用途：合并进平台「知识库」菜单，样式基准以菜单 1 站点为准。
   ============================================================ */

"""

EXTRA = """

/* ============================================================
   平台内嵌适配层（合并后新增，仅作用于 .kbsite 容器内）
   ============================================================ */
.kbsite { background: transparent; }
.kbsite .kb-subnav {
  margin-left: 0; padding: 0 0 10px; margin-bottom: 16px;
  border-bottom: 1px solid var(--border-soft);
}
.kbsite .page { padding: 4px 0 48px; max-width: none; }
.kbsite .kb-foot {
  border-top: 1px solid var(--border-soft); margin-top: 36px; padding: 18px 0 8px;
  text-align: center; font-size: var(--fs-body-sm); color: var(--text-faint); line-height: 1.8;
}
"""

css = strip_comments(open(SRC, encoding="utf-8").read())
out = HEADER + render(parse_blocks(css)) + EXTRA
open(DST, "w", encoding="utf-8").write(out)
print("wrote", DST, len(out), "bytes")
