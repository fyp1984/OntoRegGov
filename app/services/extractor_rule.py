"""确定性规则抽取器：从 PDF/MD/TXT 文本抽取 实体+关系候选。
降噪：跳过 Markdown 引用块(>)、标题、空行与"示意/仅供演示"说明句；
仅对含义务触发词(应当/必须/不得/严禁/应/需要)的正文行产 Obligation 候选。
"""
from __future__ import annotations
import re
import hashlib

OBLIGATION_TRIGGER = re.compile(r"(应当|必须|不得|严禁)")
CLAUSE_PAT = re.compile(r"^第[一二三四五六七八九十百零\d]+条[^\n]*")
NOISE_HINTS = ("示意", "仅供演示", "样例", "说明", "注意：", "注：", "非逐字", "整理自")


def _cand_id(text: str) -> str:
    return "cand-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def _clean_lines(text: str):
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("#", ">", "|", "-", "*")):   # 标题/引用块/表格/列表符号
            continue
        if any(h in line for h in NOISE_HINTS) and not OBLIGATION_TRIGGER.search(line):
            continue
        out.append(line)
    return out


def extract(text: str, document_id: str = "doc") -> list[dict]:
    cands = []
    for line in _clean_lines(text):
        # 条款候选：行首是"第X条"
        m = CLAUSE_PAT.match(line)
        if m:
            span = line
            cands.append({
                "id": _cand_id(span + "cl"), "kind": "Clause",
                "label": span[:40], "mappedClass": "Clause",
                "confidence": 0.60, "provenance": "rule", "span": span,
                "payload": {"clauseNo": re.match(r"(第[一二三四五六七八九十百零\d]+条)", line).group(1),
                            "title": span[:40]},
            })
        # 义务候选：仅当行内含义务触发词
        if OBLIGATION_TRIGGER.search(line):
            force = "mandatory" if ("应当" in line or "必须" in line) else "recommended"
            cands.append({
                "id": _cand_id(line), "kind": "Obligation",
                "label": line[:40], "mappedClass": "Obligation",
                "confidence": 0.60, "provenance": "rule", "span": line,
                "payload": {"text": line, "force": force},
            })
    # 去重
    seen, out = set(), []
    for c in cands:
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        out.append(c)
    return out
