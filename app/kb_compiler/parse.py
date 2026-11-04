"""自含的 Markdown 条目解析器（不 import 10 工程脚本）。

只做确定性解析：YAML frontmatter + Markdown 正文 + 正文 [[wikilink]] 抽取。
输入 = 10 工程编辑源文件路径；输出 = dict（frontmatter 字段 + body + 正文双链）。
"""
from __future__ import annotations
import hashlib
import re
from pathlib import Path

import yaml

from ..config import KB_ROOT

# MVP 纵切只编译两类：术语 term + 控制 control（+ 金规检查由平台 JSON 单独纳入）
MVP_DIRS = {"terms": "term", "controls": "control"}

# v1.7.0（阶段 B2 全量编译推进）：在 term/control 之外，全量纳入三类——
#   solutions（解决方案 33）/ paths（学习路径，类型=guide，4）/ topics（专题 7，含 93号文专题）。
#   复用 term/control 同一套通用实体管线（_entity_common + _resolve_relations），不新增 TBox 类
#   （Solution/Guide/Topic 类已在 ontology.yaml 与编译器 _add_tbox 声明）。
#   目录名 paths 与实体类型 guide 不一致，故显式定型 rec["type"]=guide（双保险）。
B2_DIRS = {"solutions": "solution", "paths": "guide", "topics": "topic"}

# v1.6.0 定向纳入：93号文 law（仅此 1 部法，不全量扫 23 部 laws）。
#   93号文纵深专题改由 B2_DIRS["topics"] 全量收录，此处不再单列（避免重复解析）。
#   v1.8.0（261025）：TARGET_CONTENT 保留兜底；B3_DIRS 全量扫后按 id 去重，此条不会重复入图。
TARGET_CONTENT = [
    ("laws", "law", "finance-data-security-special-action-2025"),       # 金办发〔2025〕93号
]

# v1.8.0（阶段 B3 全量编译）：法规 law / 标准 standard / 机构 organization 全量编入图谱。
#   复用 term/control 同一套通用实体管线（_entity_common + _resolve_relations +
#   law/standard/org 专属富字段投影），TBox 类 Law/Standard/Organization 已声明。
B3_DIRS = {"laws": "law", "standards": "standard", "organizations": "organization"}

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]")
_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")


def split_frontmatter(text: str) -> tuple[dict, str]:
    """--- 之间为 YAML frontmatter，其余为正文。缺 frontmatter 返回 ({}, text)。"""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return fm, body


def extract_wikilinks(body: str) -> list[dict]:
    """抽取正文 [[id]] / [[id|显示文本]]，去重保序。返回 [{id, label}]。"""
    seen = {}
    for m in _WIKILINK_RE.finditer(body):
        tid = m.group(1).strip()
        label = (m.group(2) or "").strip()
        if tid and tid not in seen:
            seen[tid] = label
    return [{"id": k, "label": v} for k, v in seen.items()]


def content_hash(fm_raw: str, body: str) -> str:
    """内容哈希：frontmatter 原文 + 正文 sha256，用于幂等判定与溯源标注。"""
    return hashlib.sha256((fm_raw + "\n" + body).encode("utf-8")).hexdigest()


def parse_md(path: Path) -> dict:
    """解析一个 content/<type>/<id>.md 条目。"""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        fm_raw = parts[1] if len(parts) >= 3 else ""
        fm = yaml.safe_load(fm_raw) or {}
        body = parts[2].lstrip("\n") if len(parts) >= 3 else ""
    else:
        fm, body = {}, text
    eid = fm.get("id") or path.stem
    return {
        "id": eid,
        "type": fm.get("type"),
        "fm": fm,
        "body": body,
        "wikilinks": extract_wikilinks(body),
        "sourcePath": str(path.relative_to(KB_ROOT)),
        "contentHash": content_hash(fm_raw if text.startswith("---") else "", body),
    }


def scan_mvp() -> list[dict]:
    """扫描编译范围：terms + controls（MVP），+ B2 全量 solutions/paths(guide)/topics，
    + v1.6.0 定向纳入的 93号文 law。"""
    out = []
    for sub, ttype in MVP_DIRS.items():
        d = KB_ROOT / "content" / sub
        if not d.exists():
            continue
        for p in sorted(d.glob("*.md")):
            out.append(parse_md(p))
    # v1.7.0 B2：solution / guide(paths) / topic 全量纳入（目录名→类型显式定型）
    for sub, ttype in B2_DIRS.items():
        d = KB_ROOT / "content" / sub
        if not d.exists():
            continue
        for p in sorted(d.glob("*.md")):
            rec = parse_md(p)
            rec["type"] = ttype
            out.append(rec)
    # v1.6.0 定向：93号文 law（单文件，按 id 定位；缺文件则跳过，不阻断）
    for sub, ttype, eid in TARGET_CONTENT:
        p = KB_ROOT / "content" / sub / f"{eid}.md"
        if p.exists():
            rec = parse_md(p)
            rec["type"] = ttype  # 显式定型（frontmatter 已一致，双保险）
            out.append(rec)
    # v1.8.0 B3：law/standard/organization 全量扫入；按 id 去重（防与 TARGET_CONTENT 重复）
    seen_ids = {r["id"] for r in out}
    for sub, ttype in B3_DIRS.items():
        d = KB_ROOT / "content" / sub
        if not d.exists():
            continue
        for p in sorted(d.glob("*.md")):
            if p.stem in seen_ids:
                continue
            rec = parse_md(p)
            rec["type"] = ttype  # 显式定型（frontmatter 已一致，双保险）
            out.append(rec)
            seen_ids.add(rec["id"])
    return out


# registry 分节名 → 实体类型（paths=学习路径=guide）
_SECTION_TO_TYPE = {
    "terms": "term", "laws": "law", "standards": "standard",
    "organizations": "organization", "cases": "case", "paths": "guide",
    "topics": "topic", "scenarios": "scenario", "roles": "role",
    "controls": "control", "solutions": "solution",
}


def load_registry() -> dict[str, str]:
    """读 sources/id-registry.yaml → {id: type}。用于跨类型关系目标解析与零断链校验。"""
    reg = KB_ROOT / "sources" / "id-registry.yaml"
    out: dict[str, str] = {}
    if not reg.exists():
        return out
    data = yaml.safe_load(reg.read_text(encoding="utf-8")) or {}
    for sec, items in data.items():
        if not isinstance(items, list):
            continue
        ttype = _SECTION_TO_TYPE.get(sec)
        if not ttype:
            continue
        for it in items:
            if isinstance(it, dict) and it.get("id"):
                out[it["id"]] = ttype
    return out
