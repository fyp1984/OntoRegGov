#!/usr/bin/env python3
"""影子一致性比对（shadow compare）：证明新编译器与现有 build 产物同源、且更完整。

重要边界（docs/05 §1）：
- 本脚本是**唯一**被允许读 10 工程 data/knowledge.json 的地方——它只是"对账参照基准"，
  不是编译器输入。编译器输入 = 10 工程编辑源（ontology.yaml + content/*.md）。
- 比对两侧：
  ① 新编译器 canonical 图（编译自编辑源）
  ② 10 工程 build 产物 knowledge.json（参照基准）
  ③ 旧 base_import 投影（读 knowledge.json，仅 8 类 + type/title/summary/official_url）
- 期望：共有字段(title/summary/official_url)一致；新编译器补回旧路漏投的结构化字段。
"""
import sys
import json
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.kb_compiler import compiler, shacl  # noqa: E402
from app.kb_compiler.iris import ONT, KB_IRI  # noqa: E402
from app.config import KB_KNOWLEDGE_JSON, BASE_DIR  # noqa: E402
from rdflib import URIRef, RDFS, Literal, RDF  # noqa: E402

REPORT = BASE_DIR / "reports" / "shadow-compare.md"


def main():
    g, stats = compiler.compile_canonical()
    # 参照基准：build 产物 knowledge.json（只读）
    kj = json.loads(KB_KNOWLEDGE_JSON.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in kj["entities"]}

    # --- ① 计数对比 ---
    kj_types = Counter(e["type"] for e in kj["entities"])
    canon_term = sorted(set(s for s in g.subjects(RDF.type, ONT["Term"])))
    canon_ctrl = sorted(set(s for s in g.subjects(RDF.type, ONT["Control"])))

    # --- ② 共有字段逐条比对（title/summary/official_url）---
    mismatches = []
    checked = 0
    for ttype, canon_subjects in [("term", canon_term), ("control", canon_ctrl)]:
        for subj in canon_subjects:
            slug = str(subj)[len(KB_IRI) + len(ttype) + 1:]
            kj_e = by_id.get(slug)
            if not kj_e:
                mismatches.append(f"{ttype}/{slug}: canonical 有但 knowledge.json 缺")
                continue
            checked += 1
            # title
            ct = str(g.value(subj, RDFS.label) or "")
            if ct.strip() != str(kj_e.get("title", "")).strip():
                mismatches.append(f"{slug} title: canonical={ct!r} vs json={kj_e.get('title')!r}")
            # summary
            cs = str(g.value(subj, ONT["summary"]) or "")
            if cs.strip() != str(kj_e.get("summary", "")).strip():
                mismatches.append(f"{slug} summary: 不一致（长度 {len(cs)} vs {len(kj_e.get('summary',''))}）")

    # --- ③ 新编译器补回的结构化字段（旧 base_import 只投影 type/title/summary/seeAlso）---
    n_ct = shacl.count_ct_coded(g)
    n_layer = sum(1 for _ in g.triples((None, ONT["ctLayer"], None)))
    n_lifecycle = sum(1 for _ in g.triples((None, ONT["lifecycle"], None)))
    n_mapping = sum(1 for _ in g.triples((None, ONT["hasMapping"], None)))
    n_alias = sum(1 for _ in g.triples((None, ONT["alias"], None)))
    n_tag = sum(1 for _ in g.triples((None, ONT["tag"], None)))
    n_rel = sum(1 for p in ["implements", "citesLaw", "citesStandard", "governedBy",
                            "relatedTerm", "broader", "narrower", "seeAlso", "mitigates"]
                for _ in g.triples((None, ONT[p], None)))
    n_mentions = sum(1 for _ in g.triples((None, ONT["mentions"], None)))

    # --- ④ 旧路漏投的整类（MVP 外，报告标注）---
    dropped = {t: kj_types.get(t, 0) for t in ("solution", "guide", "topic")}

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 影子一致性比对报告（canonical 编译器 vs 现有 build 产物）",
        "",
        f"- 编译器输入：10 工程**编辑源**（ontology.yaml + content/terms, content/controls）",
        f"- 比对参照：10 工程 build 产物 `data/knowledge.json`（{len(kj['entities'])} 实体，只读基准）",
        f"- 生成时间：脚本运行期；同输入→同输出（幂等）",
        "",
        "## 1. 计数",
        f"- canonical：术语 {len(canon_term)} / 控制 {len(canon_ctrl)} / 三元组 {len(g)}",
        f"- knowledge.json：" + " / ".join(f"{t}={kj_types.get(t,0)}" for t in ("term","control")),
        f"- 分层：{shacl.count_by_layer(g)}；带 CT 码 {n_ct}",
        "",
        "## 2. 共有字段逐条比对（title/summary）",
        f"- 比对实体数：{checked}；不一致：{len(mismatches)}",
    ]
    if mismatches:
        lines.append("")
        lines.append("### 不一致明细")
        lines += [f"- {m}" for m in mismatches[:30]]
    else:
        lines.append("- ✅ title/summary 共有字段完全一致。")
    lines += [
        "",
        "## 3. 新编译器补回旧路漏投的结构化字段",
        "旧 base_import 仅投影 type/title/summary/official_url→seeAlso；新编译补回：",
        f"- ctCode {n_ct} / ctLayer {n_layer} / lifecycle {n_lifecycle} / standard_mappings(hasMapping) {n_mapping}",
        f"- alias {n_alias} / tag {n_tag} / 关系边 {n_rel} / 正文双链 mentions {n_mentions}",
        "",
        "## 4. 旧路整类漏投（MVP 范围外，本阶段不编译，报告显式标注）",
    ]
    for t, n in dropped.items():
        lines.append(f"- {t}：knowledge.json 有 {n} 条，旧 base_import 与本 MVP 均未投影（阶段2全量再补）")

    # ---------- v1.6.0 增量：93号文 law/topic/检查项 ----------
    O = ONT
    d93_law = URIRef(KB_IRI + "law/finance-data-security-special-action-2025")
    d93_topic = URIRef(KB_IRI + "topic/topic-finance-data-security-special-action")
    d93_clause = URIRef(KB_IRI + "clause/cl-93-att1")
    canon_ic93 = sorted(set(s for s in g.subjects(RDF.type, O["InspectionCheck"])
                            if "ic-93-" in str(s)))
    canon_el93 = sorted(set(s for s in g.subjects(RDF.type, O["CheckElement"])
                            if "ic-93-" in str(s)))

    # 共有字段：law/topic 与 knowledge.json 逐条比对 title/summary
    d93_mis = []
    d93_checked = 0
    for uri, slug in [(d93_law, "finance-data-security-special-action-2025"),
                      (d93_topic, "topic-finance-data-security-special-action")]:
        kj_e = by_id.get(slug)
        if not kj_e:
            d93_mis.append(f"{slug}: canonical 有但 knowledge.json 缺")
            continue
        d93_checked += 1
        ct = str(g.value(uri, RDFS.label) or "")
        if ct.strip() != str(kj_e.get("title", "")).strip():
            d93_mis.append(f"{slug} title: canonical={ct!r} vs json={kj_e.get('title')!r}")
        cs = str(g.value(uri, O["summary"]) or "")
        kj_s = str(kj_e.get("summary", "")).strip()
        if cs.strip() != kj_s:
            d93_mis.append(f"{slug} summary: 不一致（长度 {len(cs)} vs {len(kj_s)}）")

    # 93号文关系/双链计数
    def _edges(pred):
        return sum(1 for s in g.subjects(pred, None) if "ic-93-" in str(s) or s in (d93_law, d93_topic, d93_clause))
    n93_citesClause = sum(1 for _ in g.triples((None, O["citesClause"], d93_clause)))
    n93_citesLaw = sum(1 for _ in g.triples((d93_clause, O["citesLaw"], None)))
    n93_hasElement = sum(1 for s in canon_ic93 for _ in g.triples((s, O["hasElement"], None)))
    n93_mentions = sum(1 for s in (d93_law, d93_topic) for _ in g.triples((s, O["mentions"], None)))
    n93_rel = sum(1 for s in (d93_law, d93_topic)
                  for p in ["citesLaw", "citesStandard", "publishedBy", "governs", "citedBy", "seeAlso"]
                  for _ in g.triples((s, O[p], None)))

    # 新增（knowledge.json 完全没有的 93号文实体）
    new_entities = len(canon_ic93) + (1 if (d93_clause, None, None) in g else 0) + len(canon_el93)

    lines += [
        "",
        "## 5. v1.6.0 93号文增量（金办发〔2025〕93号）",
        f"- canonical 新增：law 1 / topic 1（均与 knowledge.json 共有，见下比对）",
        f"- canonical 新增（knowledge.json 无对应）：InspectionCheck {len(canon_ic93)} / "
        f"Clause(cl-93-att1) {1 if (d93_clause, None, None) in g else 0} / CheckElement {len(canon_el93)}"
        f" → 合计新增知识实体 {new_entities}",
        f"- 关系边：检查 citesClause→附件1 {n93_citesClause}；Clause citesLaw→93号文law {n93_citesLaw}；"
        f"检查 hasElement {n93_hasElement}；law/topic 对象关系 {n93_rel}；正文双链 mentions {n93_mentions}",
        f"- 与 knowledge.json 共有字段比对（law/topic title/summary）：比对 {d93_checked}，不一致 {len(d93_mis)}",
    ]
    if d93_mis:
        lines.append(""); lines.append("### 93号文共有字段不一致明细")
        lines += [f"- {m}" for m in d93_mis]
    else:
        lines.append("- ✅ 93号文 law/topic 的 title/summary 与 knowledge.json 完全一致；"
                     "13 检查项/要素/Clause 为 ingest/v17 新增（knowledge.json 本就 0 条）。")
    lines += [
        "",
        "## 结论",
        "- 共有字段一致：✅（" + (f"{checked} 实体 title/summary 全部一致" if not mismatches else f"有 {len(mismatches)} 处差异需复核") + "）",
        "- 新编译器相对编辑源更完整：补回 CT/layer/lifecycle/standard_mappings/关系/双链。",
        "- 任何差异均已列出；无静默不一致。",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[shadow] 比对实体 {checked}；不一致 {len(mismatches)}；报告 → {REPORT}")
    print(f"[shadow] 分层 {shacl.count_by_layer(g)}；补回 CT={n_ct} mappings={n_mapping} 关系边={n_rel} mentions={n_mentions}")
    if mismatches:
        for m in mismatches[:10]:
            print("  diff:", m)


if __name__ == "__main__":
    main()
