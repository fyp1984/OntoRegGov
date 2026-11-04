#!/usr/bin/env python3
"""控制缺口一键对齐脚本（任务线2 · 工作包C）。

大白话：金规116检查在落地时推导出 48 条"平台需要的控制"，其中 35 条已认领、
13 条是"知识库侧还没建对应权威控制"的缺口（status=gap）。本脚本读知识库侧最新
登记，把"已经真正建好并登记权威 CT 码"的缺口自动转正为 aligned；其余逐条说清
"为什么还不能补"。组织者补码后重跑本脚本即可自动解除缺口——默认 dry-run 不写盘。

对账纪律（与编译期 cross_check_codes / assert_compile_constraints 同一把尺）：
  1) 单一事实源：候选控制必须已登记在 control-codes.csv；仅 content/controls 起草 MD
     而 csv 未登记的，不算"已存在真实 CT 码"，本脚本不自动转正（只在诊断里提示"待登记"）。
  2) code 全局唯一：该 CT 码在 csv 内只出现一次。
  3) layer 匹配：占位 suggested_layer 提取的层码（EP/NW/SVC/PROTO/MGMT）须与候选
     CT 码层段一致。
  4) 控制须有法规/标准依据：候选 MD frontmatter 的 standard_mappings 非空，或 relations
     含 cites_law / cites_standard / governed_by / implements。
  自动对齐键：占位 control_name（中文标题）与 csv.title 归一化后逐字相等（去空白、去括号注）。

用法：
  python scripts/align_controls.py              # dry-run（默认）：只报告，不写
  python scripts/align_controls.py --apply      # 把可对齐项写回 control-placeholders.json
  python scripts/align_controls.py --json R.json # 另存机器可读报告
"""
from __future__ import annotations
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import KB_ROOT, BASE_DIR  # noqa: E402

PLACEHOLDERS = BASE_DIR / "data" / "checks" / "control-placeholders.json"
CSV_CODES = KB_ROOT / "data" / "control-codes.csv"
CONTROLS_MD_DIR = KB_ROOT / "content" / "controls"

_LAYER_CODES = {"EP", "NW", "SVC", "PROTO", "MGMT"}
_LAYER_EN2CODE = {"endpoint": "EP", "network": "NW", "service": "SVC",
                  "protocol": "PROTO", "management": "MGMT"}
_BASIS_RELS = {"cites_law", "cites_standard", "governed_by", "implements"}


def _norm_title(t: str) -> str:
    """归一化中文标题：去空白、去全/半角括号注释内容，供逐字比对。"""
    t = (t or "").strip()
    t = re.sub(r"[（(][^（）()]*[)）]", "", t)   # 去括号注释
    t = re.sub(r"\s+", "", t)
    return t


def _norm_layer(raw: str) -> str:
    """suggested_layer 带中文后缀（如 'PROTO（建议，待 v1.5 补建）'）→ 纯层码。"""
    for code in _LAYER_CODES:
        if (raw or "").strip().startswith(code):
            return code
    return ""


def load_csv_controls() -> dict:
    """读权威 control-codes.csv → {id: {code,title,layer,control_type,family}}。"""
    out: dict[str, dict] = {}
    with open(CSV_CODES, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rid = row["id"].strip()
            out[rid] = {k: row[k].strip() for k in
                        ("code", "title", "layer", "control_type", "family")}
    return out


def load_md_controls() -> dict:
    """扫 content/controls/*.md frontmatter → {id: {title,code,layer,relations,has_mapping}}。

    只读不写；用于"法规依据"核查与"MD 已起草待登记 csv"诊断。
    """
    import yaml
    out: dict[str, dict] = {}
    if not CONTROLS_MD_DIR.exists():
        return out
    for p in sorted(CONTROLS_MD_DIR.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        parts = text.split("---", 2)
        fm = yaml.safe_load(parts[1]) or {}
        rid = fm.get("id") or p.stem
        rels = fm.get("relations", []) or []
        rel_kinds = {r.get("rel") for r in rels if isinstance(r, dict)}
        out[rid] = {
            "title": fm.get("title", ""),
            "code": fm.get("code", ""),
            "layer": fm.get("layer", ""),
            "rel_kinds": rel_kinds,
            "has_mapping": bool(fm.get("standard_mappings")),
        }
    return out


def has_regulatory_basis(md: dict | None) -> bool:
    """控制须有法规/标准依据：standard_mappings 非空，或 relations 含法规/标准/治理类。"""
    if not md:
        return False
    if md["has_mapping"]:
        return True
    return bool(md["rel_kinds"] & _BASIS_RELS)


def decide(cfg_name: str, gap: dict, csv_controls: dict, md_controls: dict,
           code_seen: dict[str, int]) -> dict:
    """对一条 gap 占位做对齐判定。返回判定 dict（含 action/reason/拟对齐字段）。"""
    suggest_layer = _norm_layer(gap.get("suggested_layer", ""))
    want_title = _norm_title(cfg_name)
    # 1) 在 csv 权威登记表里找逐字标题命中
    hits = [rid for rid, c in csv_controls.items() if _norm_title(c["title"]) == want_title]
    if not hits:
        # 诊断：csv 里是否已有语义相近但标题措辞不同的控制（>=4 字连续子串）。
        #   区分两种不可补原因：①已登记但名称不匹配（需人工对齐/统一标题）；②完全未建。
        sem = []
        for rid2, c2 in csv_controls.items():
            mt = _norm_title(c2["title"])
            if not mt or not want_title:
                continue
            if any(want_title[i:i+4] in mt for i in range(len(want_title) - 3)):
                sem.append("%s『%s』" % (c2["code"], c2["title"]))
        reason = "知识侧 control-codes.csv 无逐字标题『%s』的控制" % cfg_name
        if sem:
            reason += ("；csv 已有语义候选但标题非逐字一致(需人工对齐/统一标题): "
                       + " | ".join(sem))
        else:
            reason += "；csv/MD 均无对应控制，待 10 工程补建"
        return {"action": "keep_gap", "reason": reason}
    if len(hits) > 1:
        return {"action": "keep_gap",
                "reason": "csv 同名命中 %d 个控制（%s），违反 code 唯一，需人工裁定"
                          % (len(hits), ",".join(hits))}
    rid = hits[0]
    cand = csv_controls[rid]
    md = md_controls.get(rid)
    # 2) code 唯一
    if code_seen.get(cand["code"], 0) != 1:
        return {"action": "keep_gap",
                "reason": "CT 码 %s 在 csv 出现 %d 次，不唯一" % (cand["code"], code_seen.get(cand["code"], 0))}
    # 3) layer 匹配
    cand_layer = _LAYER_EN2CODE.get(cand["layer"], "")
    if suggest_layer and cand_layer != suggest_layer:
        return {"action": "keep_gap",
                "reason": "层不匹配: 占位建议 %s vs 候选 %s(%s)" % (suggest_layer, cand["code"], cand_layer)}
    # 4) 法规/标准依据
    if not has_regulatory_basis(md):
        return {"action": "keep_gap",
                "reason": "候选控制 %s 缺法规/标准依据（standard_mappings/relations 均无）" % rid}
    return {"action": "align", "reason": "逐字命中且层/依据/唯一性齐备",
            "ct_code": cand["code"], "ct_layer": cand_layer or suggest_layer,
            "base_control_id": rid, "base_control_title": cand["title"]}


def main() -> int:
    apply = "--apply" in sys.argv
    json_out = None
    if "--json" in sys.argv:
        json_out = sys.argv[sys.argv.index("--json") + 1]

    data = json.loads(PLACEHOLDERS.read_text(encoding="utf-8"))
    csv_controls = load_csv_controls()
    md_controls = load_md_controls()

    # code 唯一性统计（csv 维度）
    code_seen: dict[str, int] = {}
    for c in csv_controls.values():
        code_seen[c["code"]] = code_seen.get(c["code"], 0) + 1

    gaps = [c for c in data["controls"] if c.get("alignment", {}).get("status") == "gap"]
    n_align = n_keep = 0
    report = []
    for gap in gaps:
        name = gap["control_name"]
        d = decide(name, gap, csv_controls, md_controls, code_seen)
        if d["action"] == "align":
            n_align += 1
            if apply:
                gap["alignment"] = {
                    "status": "aligned",
                    "ct_code": d["ct_code"],
                    "ct_layer": d["ct_layer"],
                    "base_control_id": d["base_control_id"],
                    "base_control_title": d["base_control_title"],
                    "note": "由 scripts/align_controls.py 自动对齐（csv 权威登记 + 层/依据/唯一性校验）",
                }
        else:
            n_keep += 1
        report.append({"control_name": name, "hint": gap.get("control_code_hint"),
                       "action": d["action"], "reason": d["reason"]})

    print("=" * 72)
    print("[align] control-placeholders.json 缺口对齐报告（%s）" % ("APPLY 写盘" if apply else "DRY-RUN 只读"))
    print("[align] csv 权威控制=%d 条 / content/controls MD=%d 条 / gap 占位=%d 条"
          % (len(csv_controls), len(md_controls), len(gaps)))
    print("-" * 72)
    for r in report:
        tag = "✅可对齐" if r["action"] == "align" else "⏸ 仍缺口"
        print("%s  %s" % (tag, r["control_name"]))
        print("      ↳ %s" % r["reason"])
    print("-" * 72)
    print("[align] 可自动对齐=%d / 仍待补=%d" % (n_align, n_keep))
    if apply and n_align:
        # 更新顶部计数
        data["stats"]["gap"] = n_keep
        data["stats"]["aligned"] = data["stats"]["controls"] - n_keep
        PLACEHOLDERS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
        print("[align] 已写回 → %s" % PLACEHOLDERS)
    else:
        print("[align] dry-run 未写盘；确认无误后加 --apply 写回；组织者补 csv 后重跑本脚本即自动解除。")
    if json_out:
        Path(json_out).write_text(json.dumps({"summary": {"csv": len(csv_controls),
            "md": len(md_controls), "gaps": len(gaps), "aligned": n_align, "keep": n_keep},
            "details": report}, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[align] 机器可读报告 → %s" % json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
