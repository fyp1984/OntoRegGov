"""kb_knowledge — 从知识库平台的原始 Markdown 装配站点契约 KNOWLEDGE_BASE。

大白话：菜单1（静态知识库站）原本在构建期由 `10_知识库工程/scripts/build.py`
读 `content/**/*.md` 生成 `window.KNOWLEDGE_BASE`。合并为单一「知识库」入口后，
改为在运行期从知识库平台（WeKnora）的原始 Markdown
（`knowledges.metadata->>'content'`）现场解析装配，产出与 build.py **完全同形状**
的数据结构，前端即可零改造直接渲染。

职责边界：本模块只做"Markdown → KNOWLEDGE_BASE 形状"的纯函数装配，不连库、不缓存；
原始 Markdown 由 `weknora_retriever.knowledge_docs()` 提供，
缓存与降级由 `kb_source.fetch_knowledge()` 负责。
"""
from __future__ import annotations

import datetime as _dt
import html as _html
import re

import yaml

KNOWLEDGE_VERSION = "1.0.0"

# frontmatter 通用字段（其余按类型归入 attrs）—— 与 kbcommon.COMMON_KEYS 一致
COMMON_KEYS = {
    "id", "title", "title_en", "type", "level", "aliases", "tags",
    "summary", "status", "updated", "official_url", "sources", "relations",
    "media",
    # control v1.5 结构化字段（顶层），避免被丢进 attrs
    "code", "layer", "lifecycle", "control_type",
    "family", "evidence_examples", "standard_mappings",
}

# 实体 type -> 内容目录（用于还原 md_path 展示）
TYPE_DIR = {
    "term": "terms", "law": "laws", "standard": "standards", "control": "controls",
    "case": "cases", "solution": "solutions", "organization": "organizations",
    "scenario": "scenarios", "topic": "topics", "guide": "paths", "role": "roles",
}

# 关系类型（有向）—— 编译自 10_知识库工程/ontology/ontology.yaml 的 relation_types
REL_TYPES = [
    {"key": "defined_by", "label": "定义/依据于", "inverse": "defines", "range": ["law", "standard"]},
    {"key": "broader", "label": "上位概念", "inverse": "narrower", "range": ["term"]},
    {"key": "synonym", "label": "同义/近义", "inverse": "synonym", "symmetric": True},
    {"key": "antonym", "label": "反义/易混对照", "inverse": "antonym", "symmetric": True},
    {"key": "contrasts_with", "label": "对比辨析", "inverse": "contrasts_with", "symmetric": True},
    {"key": "member_of", "label": "属于/归类于", "inverse": "has_member", "range": ["term"]},
    {"key": "prerequisite", "label": "前置知识", "inverse": "enables", "range": ["term"]},
    {"key": "related_term", "label": "相关概念", "inverse": "related_term", "symmetric": True},
    {"key": "governed_by", "label": "受管于/合规依据", "inverse": "governs", "range": ["law", "standard"]},
    {"key": "mitigates", "label": "缓解风险/对抗威胁", "inverse": "mitigated_by", "range": ["term", "case"]},
    {"key": "implements", "label": "落地/实现", "inverse": "implemented_by", "range": ["standard", "law", "term"]},
    {"key": "deployed_with", "label": "由产品落地", "inverse": "deploys_control", "range": ["solution"]},
    {"key": "deploys_control", "label": "落地该控制", "inverse": "deployed_with", "range": ["control"]},
    {"key": "cites_law", "label": "引用法条", "inverse": "cited_by", "range": ["law"]},
    {"key": "cites_standard", "label": "引用标准", "inverse": "cited_by", "range": ["standard"]},
    {"key": "instance_of", "label": "实例化/是…的案例", "inverse": "has_instance", "range": ["term", "control", "scenario"]},
    {"key": "involves_role", "label": "涉及角色", "inverse": "involved_in", "range": ["role"]},
    {"key": "occurs_in", "label": "发生于行业场景", "inverse": "has_case", "range": ["scenario"]},
    {"key": "published_by", "label": "发布/制定机构", "inverse": "publishes", "range": ["organization"]},
    {"key": "part_of_path", "label": "属于学习路径", "inverse": "includes", "range": ["guide"]},
    {"key": "see_also", "label": "参见/延伸", "inverse": "see_also", "symmetric": True},
]

_WIKILINK_RE = re.compile(r"\[\[\s*([^\]]+?)\s*\]\]")


def _s(v) -> str:
    """安全字符串（date/datetime 转 ISO）。"""
    if v is None:
        return ""
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    return str(v).strip()


def _parse_wikilink(inner: str):
    """从 [[...]] 内部解析出 (id, display)；兼容表格转义 \\|。"""
    norm = inner.replace("\\|", "|")
    parts = norm.split("|", 1)
    tid = parts[0].strip().rstrip("\\").strip()
    disp = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    return tid, disp


# ---------------------------------------------------------------------------
# 关系表：正向键 / 对称键 / 反向名映射 / 中文标签
# ---------------------------------------------------------------------------
_rel_tables_cache = None


def _rel_tables():
    global _rel_tables_cache
    if _rel_tables_cache is not None:
        return _rel_tables_cache
    forward, symmetric, inv_to_fwd, label = set(), set(), {}, {}
    ranges = {rt["key"]: list(rt.get("range") or []) for rt in REL_TYPES}
    for rt in REL_TYPES:
        k = rt["key"]
        forward.add(k)
        label[k] = rt.get("label", k)
        if rt.get("symmetric"):
            symmetric.add(k)
        inv = rt.get("inverse")
        if inv and inv != k:
            cand = (k, (ranges.get(k) or [None])[0])
            if inv in inv_to_fwd and inv_to_fwd[inv] != k:
                old = inv_to_fwd[inv]
                cands = old if isinstance(old, list) else [(old, (ranges.get(old) or [None])[0])]
                cands.append(cand)
                inv_to_fwd[inv] = cands
            else:
                inv_to_fwd[inv] = k
    _rel_tables_cache = (forward, symmetric, inv_to_fwd, label)
    return _rel_tables_cache


def rel_label_map() -> dict:
    return dict(_rel_tables()[3])


def normalize_edge(source: str, rel: str, target: str, node_types: dict | None = None):
    """把 (source, rel, target) 规范化为正向边；rel 非法返回 None。"""
    forward, symmetric, inv_to_fwd, _ = _rel_tables()
    if rel in symmetric or rel in forward:
        return (source, target, rel)
    if rel in inv_to_fwd:
        fwd = inv_to_fwd[rel]
        if isinstance(fwd, list):  # cited_by 等一对多反向名：按 target 类型消歧
            ttype = (node_types or {}).get(target)
            fwd = next((c for c, want in fwd if ttype == want), fwd[0][0])
        return (target, source, fwd)
    return None


# ---------------------------------------------------------------------------
# Markdown 解析 / 渲染
# ---------------------------------------------------------------------------
class FrontmatterError(Exception):
    """frontmatter 缺失或 YAML 解析失败。"""


def split_frontmatter(text: str):
    """把 md 文本切成 (frontmatter_dict, body_str)。"""
    if not text.startswith("---"):
        raise FrontmatterError("缺少以 --- 开头的 YAML frontmatter")
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise FrontmatterError("frontmatter 没有找到结束的 --- 分隔线")
    fm = yaml.safe_load("\n".join(lines[1:end]))
    if fm is None:
        fm = {}
    if not isinstance(fm, dict):
        raise FrontmatterError("frontmatter 顶层必须是映射(dict)")
    return fm, "\n".join(lines[end + 1:])


def extract_wikilinks(body: str):
    """按出现顺序提取正文双链目标 id（去重保序）：[(id, display)]。"""
    seen, seen_ids = [], set()
    for m in _WIKILINK_RE.finditer(body):
        tid, disp = _parse_wikilink(m.group(1))
        if tid and tid not in seen_ids:
            seen_ids.add(tid)
            seen.append((tid, disp))
    return seen


def _inline(text: str) -> str:
    """行内最小渲染（粗体/行内码/链接/转义）。"""
    t = _html.escape(text, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', t)
    return t


def _fallback_md(text: str) -> str:
    """markdown 库缺失时的最小降级渲染（标题/列表/段落），保可用不保完全一致。"""
    out = []
    for block in re.split(r"\n{2,}", text):
        b = block.strip()
        if not b:
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", b)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            continue
        if re.match(r"^([-*+]|\d+\.)\s+", b):
            items = [re.sub(r"^([-*+]|\d+\.)\s+", "", ln) for ln in b.splitlines() if ln.strip()]
            out.append("<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + "</ul>")
            continue
        out.append(f"<p>{_inline(b)}</p>")
    return "\n".join(out)


def render_body(body: str, title_map: dict) -> str:
    """双链 -> <a class="wikilink">，再用 markdown 渲染 HTML。"""
    def repl(m):
        tid, disp = _parse_wikilink(m.group(1))
        if not tid:
            return m.group(0)
        disp = _html.escape((disp or title_map.get(tid, tid) or tid), quote=False)
        return f'<a class="wikilink" href="#/entity/{tid}" data-id="{tid}">{disp}</a>'

    pre = _WIKILINK_RE.sub(repl, body)
    try:
        import markdown as md_lib
        return md_lib.markdown(pre, extensions=["tables", "fenced_code", "sane_lists"])
    except Exception:  # noqa: BLE001 — 依赖缺失时降级，不影响可用性
        return _fallback_md(pre)


# ---------------------------------------------------------------------------
# 字段规范化
# ---------------------------------------------------------------------------
def normalize_media(raw) -> dict:
    """规范 frontmatter.media -> {"images":[...],"videos":[...]}（纯外链）。"""
    out = {"images": [], "videos": []}
    if not isinstance(raw, dict):
        return out
    for it in (raw.get("images") or []):
        if not isinstance(it, dict):
            continue
        url, source = _s(it.get("url")), _s(it.get("source"))
        if not url or not source:
            continue
        item = {"url": url, "source": source}
        for k in ("caption", "source_url", "license"):
            v = _s(it.get(k))
            if v:
                item[k] = v
        out["images"].append(item)
    for it in (raw.get("videos") or []):
        if not isinstance(it, dict):
            continue
        url, title = _s(it.get("url")), _s(it.get("title"))
        if not url or not title:
            continue
        item = {"url": url, "title": title}
        for k in ("platform", "duration", "desc"):
            v = _s(it.get(k))
            if v:
                item[k] = v
        out["videos"].append(item)
    return out


def normalize_control_fields(fm: dict) -> dict:
    """规范 control 结构化字段；非 control 返回空结构。"""
    out = {"code": "", "layer": "", "lifecycle": [], "control_type": "",
           "family": "", "evidence_examples": [], "standard_mappings": []}
    if not isinstance(fm, dict) or fm.get("type") != "control":
        return out
    out["code"] = _s(fm.get("code"))
    out["layer"] = _s(fm.get("layer"))
    out["control_type"] = _s(fm.get("control_type"))
    out["family"] = _s(fm.get("family") or fm.get("control_family"))
    lc = fm.get("lifecycle")
    if isinstance(lc, list):
        out["lifecycle"] = [_s(x) for x in lc if _s(x)]
    ev = fm.get("evidence_examples")
    if isinstance(ev, list):
        out["evidence_examples"] = [_s(x) for x in ev if _s(x)]
    sm = fm.get("standard_mappings")
    if isinstance(sm, list):
        for it in sm:
            if not isinstance(it, dict):
                continue
            fw, rf = _s(it.get("framework")), _s(it.get("ref"))
            if not fw or not rf:
                continue
            item = {"framework": fw, "ref": rf}
            note = _s(it.get("note"))
            if note:
                item["note"] = note
            out["standard_mappings"].append(item)
    return out


# ---------------------------------------------------------------------------
# 装配主函数
# ---------------------------------------------------------------------------
def build(docs) -> dict:
    """把原始 Markdown 列表装配成与 build.py 同形状的 KNOWLEDGE_BASE。

    docs: [{content: <原始 md（含 frontmatter）>, title?: str, updatedAt?: str}]
    返回：{generated_at, version, counts, entities, nodes, edges}
    """
    rel_labels = rel_label_map()

    # ---- Pass 1：解析 frontmatter，按 id 去重 ----
    parsed = []            # [(fm, body)]
    title_map = {}         # id -> title
    node_types = {}        # id -> type（cited_by 等反向键消歧）
    seen_ids = set()
    for d in docs or []:
        content = (d.get("content") or "").strip()
        if not content:
            continue
        try:
            fm, body = split_frontmatter(content)
        except Exception:  # noqa: BLE001 — 单条坏数据不阻断整库
            continue
        eid = fm.get("id")
        if not isinstance(eid, str) or not eid or eid in seen_ids:
            continue
        seen_ids.add(eid)
        parsed.append((fm, body))
        title_map[eid] = _s(fm.get("title")) or eid
        node_types[eid] = fm.get("type")

    # ---- Pass 2：原始边（relations + 正文双链），规范化后去重 ----
    all_raw = []
    for fm, body in parsed:
        eid = fm.get("id", "")
        for r in fm.get("relations") or []:
            if not isinstance(r, dict):
                continue
            rrel, rto = r.get("rel"), r.get("to")
            if not rrel or not rto:
                continue
            norm = normalize_edge(eid, rrel, rto, node_types)
            ns, nt, nrel = norm if norm else (eid, rto, rrel)
            all_raw.append((ns, nt, nrel, r.get("note"), False))
        for tid, _disp in extract_wikilinks(body):
            all_raw.append((eid, tid, "related", None, True))

    seen_edge, deduped = set(), []
    for e in all_raw:
        k = (e[0], e[1], e[2])
        if k in seen_edge:
            continue
        seen_edge.add(k)
        deduped.append(e)

    edges = []
    relations_out_map = {}
    for ns, nt, nrel, note, inline in deduped:
        edges.append({"source": ns, "target": nt, "rel": nrel,
                      "label": rel_labels.get(nrel, nrel), "inline": inline})
        rel_out = {"rel": nrel, "to": nt, "note": note}
        if inline:
            rel_out["inline"] = True
        relations_out_map.setdefault(ns, []).append(rel_out)

    # ---- Pass 3：实体记录 ----
    entities, nodes, type_counts = [], [], {}
    for fm, body in parsed:
        eid = fm.get("id", "")
        etype = fm.get("type", "")
        attrs = {k: v for k, v in fm.items() if k not in COMMON_KEYS}
        record = {
            "id": eid,
            "type": etype,
            "title": _s(fm.get("title")),
            "title_en": _s(fm.get("title_en")),
            "level": _s(fm.get("level")),
            "aliases": fm.get("aliases") or [],
            "tags": fm.get("tags") or [],
            "summary": _s(fm.get("summary")),
            "status": _s(fm.get("status")),
            "updated": _s(fm.get("updated")),
            "official_url": _s(fm.get("official_url")),
            "media": normalize_media(fm.get("media")),
            "attrs": attrs,
            "body_html": render_body(body, title_map),
            "sources": fm.get("sources") or [],
            "relations_out": relations_out_map.get(eid, []),
            "md_path": f"content/{TYPE_DIR.get(etype, 'misc')}/{eid}.md",
        }
        record.update(normalize_control_fields(fm))
        entities.append(record)
        nodes.append({"id": eid, "title": record["title"], "type": etype,
                      "level": record["level"], "tags": record["tags"]})
        type_counts[etype] = type_counts.get(etype, 0) + 1

    return {
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "version": KNOWLEDGE_VERSION,
        "counts": dict(sorted(type_counts.items())),
        "entities": entities,
        "nodes": nodes,
        "edges": edges,
    }
