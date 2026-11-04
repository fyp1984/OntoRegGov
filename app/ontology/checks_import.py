"""监管检查知识库导入器（幂等，v1.11 支持多文号）。
只读消费 data/checks/*-checks.json（jg24 金规24号 / jg93 金办发93号 / pboc3 人行令3号 / jf8 金发8号），
物化为平台实体（定义层 TBox 内容）。不重解析源 HTML、不清底座快照、不动义务/控制/资产/Assessment 闭环数据。
"""
from __future__ import annotations
import json, datetime
from pathlib import Path
from ..config import BASE_DIR
from ..db import db

CHECKS_DIR = BASE_DIR / "data" / "checks"
CHECKS_FILES = ["jg24-checks.json", "jg93-checks.json", "pboc3-checks.json", "jf8-checks.json"]
PLACEHOLDERS_JSON = BASE_DIR / "data" / "checks" / "control-placeholders.json"
LAW_ID = "law-jg24"
SEED_CLAUSES = {"cl-16","cl-17","cl-18","cl-19","cl-20","cl-21","cl-22",
                "cl-23","cl-24","cl-25","cl-26","cl-71"}

# jg24 专属：按条号建 Clause 边；其余文号（附件2自查项/法规条款）不建 Clause（不悬空引用）
CLAUSE_DOC = "jg24"

# 底座真实术语 id（已在 base-snapshot.ttl 核对存在），ref 形态 baseTerm:<slug>
BASE_TERM = {
    "data-classification-grading": "数据分类分级",
    "finance-data-grading": "金融数据分级",
    "sensitive-personal-information": "敏感个人信息",
    "finance-outsourcing-security": "外包/供应链安全",
    "cross-border-data-transfer": "数据出境",
    "cross-border-security-assessment": "数据出境安全评估",
    "standard-contract": "个人信息出境标准合同",
}

# 中文数字解析
_CN_DIGIT = {"零":0,"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9}

def cn_to_int(s: str) -> int:
    """第十条/第三十一条 → 10/31。"""
    s = s.replace("第", "").replace("条", "").strip()
    if s.isdigit():
        return int(s)
    total = 0
    if "十" in s:
        left, _, right = s.partition("十")
        tens = (_CN_DIGIT.get(left, 1) if left else 1)
        total += tens * 10
        if right:
            total += _CN_DIGIT.get(right, 0)
        return total
    return _CN_DIGIT.get(s, 0)


def _dots(s: str) -> str:
    return s.replace(".", "-")


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _pub(conn, eid, etype, data, relations=None):
    relations = relations or []
    conn.execute(
        "INSERT OR REPLACE INTO entities(id,type,status,currentVersion,dataJSON,relationsJSON,updatedAt,updatedBy) VALUES(?,?,?,?,?,?,?,?)",
        (eid, etype, "published", 1, json.dumps(data, ensure_ascii=False),
         json.dumps(relations, ensure_ascii=False), _now(), "import-checks"))


def _cleanup(conn):
    """删除本批派生数据（定义层实体 + 导入补建的 Clause），不动底座/种子闭环。"""
    rows = conn.execute("SELECT id,type,dataJSON FROM entities").fetchall()
    for r in rows:
        eid, etype = r["id"], r["type"]
        if etype in ("InspectionCheck", "CheckElement", "Metric", "InspectionMethodStep",
                     "InterviewQuestion", "VerdictRule", "FindingPattern",
                     "InspectionRun", "CheckResult", "ControlPlaceholder"):
            conn.execute("DELETE FROM entities WHERE id=?", (eid,))
            conn.execute("DELETE FROM entity_versions WHERE id=?", (eid,))
        elif etype == "Clause" and eid.startswith("cl-") and eid not in SEED_CLAUSES:
            conn.execute("DELETE FROM entities WHERE id=?", (eid,))
            conn.execute("DELETE FROM entity_versions WHERE id=?", (eid,))


def _maps_to_control(title: str, text: str) -> list[str]:
    t = title + text
    out = []
    if ("分类分级保护制度" in t) or ("数据分类分级规范" in t):
        out.append("ctrl-c1")
    if "差异化" in t:
        out.append("ctrl-c2")
    if ("四类分类" in t) or ("分类标签" in t) or ("数据分类标签" in t):
        out.append("ctrl-c3")
    if ("分级标注" in t) or ("分级目录" in t) or ("重要数据标注" in t):
        out.append("ctrl-c4")
    if ("数据资产登记" in t) or ("资产地图" in t) or ("资产台账" in t):
        out.append("ctrl-c5")
    if ("重要数据目录" in t) and ("报送" in t or "报备" in t):
        out.append("ctrl-c6")
    return list(dict.fromkeys(out))


def _maps_to_term(title: str, text: str) -> list[str]:
    t = title + text
    out = []
    if ("出境" in t) or ("跨境" in t):
        out.append("cross-border-data-transfer")
        if "安全评估" in t:
            out.append("cross-border-security-assessment")
        if ("标准合同" in t) or "SCC" in t:
            out.append("standard-contract")
    if ("外包" in t) or ("供应链" in t) or ("第三方机构" in t) or ("外部机构" in t):
        out.append("finance-outsourcing-security")
    if ("分类分级" in t) or ("分级目录" in t):
        out.append("data-classification-grading")
    if ("敏感个人信息" in t) or ("个人信息敏感" in t):
        out.append("sensitive-personal-information")
    return list(dict.fromkeys(out))


def import_checks() -> dict:
    stats = {"files": 0, "checks": 0, "elements": 0, "metrics": 0, "steps": 0,
             "interviews": 0, "verdicts": 0, "findings": 0,
             "clauses_created": 0, "related_edges": 0,
             "maps_term": 0, "maps_control": 0, "terms_used": set()}

    with db() as conn:
        _cleanup(conn)
        # 已存在 Clause id 集合（按条号 number → id，jg24 复用）
        existing_clauses = {}
        for r in conn.execute("SELECT id,dataJSON FROM entities WHERE type='Clause'").fetchall():
            d = json.loads(r["dataJSON"])
            no = d.get("clauseNo", "")
            digits = "".join(ch for ch in no if ch.isdigit())
            if digits:
                existing_clauses[int(digits)] = r["id"]

        def clause_for(article_no: str, article_text: str, title_hint: str) -> str:
            n = cn_to_int(article_no)
            if n in existing_clauses:
                return existing_clauses[n]
            cid = f"cl-{n}"
            _pub(conn, cid, "Clause",
                 {"clauseNo": f"第{n}条", "title": f"{article_no}（{title_hint[:24]}）",
                  "chapter": "监管检查引用", "articleText": article_text},
                 relations=[{"p": "clauseOf", "o": f"Law:{LAW_ID}"}])
            existing_clauses[n] = cid
            stats["clauses_created"] += 1
            return cid

        for fname in CHECKS_FILES:
            fpath = CHECKS_DIR / fname
            if not fpath.exists():
                continue
            data = json.loads(fpath.read_text(encoding="utf-8"))
            checks = data["checks"]
            doc_key = data.get("doc_key", fname.replace("-checks.json", ""))
            doc_no = data.get("doc_no", "")
            doc_title = data.get("doc_title", "")
            # 文件内索引（relatedCheck 仅同文件内解析）
            by_id = {c["id"]: f"ic-{_dots(c['id'])}" for c in checks}
            stats["files"] += 1

            for c in checks:
                cid = f"ic-{_dots(c['id'])}"
                clause_id = None
                if doc_key == CLAUSE_DOC and (c.get("article_no") or "第十条"):
                    clause_id = clause_for(c.get("article_no") or "第十条",
                                           c.get("article_text", ""), c["title"])
                rels = []
                if clause_id:
                    rels.append({"p": "citesClause", "o": f"Clause:{clause_id}"})
                data_main = {
                    "checkCode": c["id"], "title": c["title"],
                    "domain": c["domain"], "domainLabel": c.get("domain_label", ""),
                    "priority": c["priority"], "regulation": c.get("regulation", ""),
                    "articleNo": c.get("article_no", ""),
                    "chapter": c.get("chapter", c["id"].split(".")[0]),
                    "articleText": c.get("article_text", ""),
                    "tip": (c.get("method") or {}).get("tip") or "",
                    "docKey": doc_key, "docNo": doc_no, "docTitle": doc_title,
                    "sourceNote": data.get("source_note", ""),
                }

                # ---- CheckElement（检查清单要素）----
                el_ids = []
                for el in c.get("checklist", []):
                    eid = f"ic-{_dots(c['id'])}-el-{_dots(el['code'])}"
                    el_rels = [{"p": "elementFocus", "o": f"focus/{lv}"} for lv in el.get("focus_levels", [])]
                    _pub(conn, eid, "CheckElement",
                         {"code": el["code"], "text": el["text"], "criteria": el.get("criteria", ""),
                          "focusLevels": ",".join(el.get("focus_levels", []))},
                         relations=el_rels)
                    el_ids.append(f"CheckElement:{eid}")
                    rels.append({"p": "hasElement", "o": f"CheckElement:{eid}"})
                    stats["elements"] += 1

                # ---- Metric（度量）----
                m_ids = []
                for j, m in enumerate((c.get("method") or {}).get("metrics", []), 1):
                    mid = f"ic-{_dots(c['id'])}-m{j}"
                    _pub(conn, mid, "Metric",
                         {"code": mid, "name": m.get("name", ""),
                          "dataSource": m.get("data_source", ""), "threshold": m.get("threshold", "")})
                    m_ids.append(f"Metric:{mid}")
                    rels.append({"p": "measuredBy", "o": f"Metric:{mid}"})
                    stats["metrics"] += 1

                # ---- InspectionMethodStep（查制度 policy / 查证据 evidence）----
                ms_ids = []
                for j, s in enumerate((c.get("method") or {}).get("policy_steps", []), 1):
                    sid = f"ic-{_dots(c['id'])}-msp{j}"
                    _pub(conn, sid, "InspectionMethodStep",
                         {"code": sid, "stepKind": "policy", "stepNo": s.get("step", str(j)),
                          "action": s.get("action", ""), "focus": s.get("focus", "")})
                    ms_ids.append(f"InspectionMethodStep:{sid}")
                    rels.append({"p": "hasMethodStep", "o": f"InspectionMethodStep:{sid}"})
                    stats["steps"] += 1
                for j, s in enumerate((c.get("method") or {}).get("evidence_steps", []), 1):
                    sid = f"ic-{_dots(c['id'])}-mse{j}"
                    _pub(conn, sid, "InspectionMethodStep",
                         {"code": sid, "stepKind": "evidence", "stepNo": s.get("step", str(j)),
                          "action": s.get("evidence_required", ""), "focus": s.get("criteria", "")})
                    ms_ids.append(f"InspectionMethodStep:{sid}")
                    rels.append({"p": "hasMethodStep", "o": f"InspectionMethodStep:{sid}"})
                    stats["steps"] += 1

                # ---- InterviewQuestion ----
                i_ids = []
                for j, iv in enumerate((c.get("method") or {}).get("interviews", []), 1):
                    iid = f"ic-{_dots(c['id'])}-i{j}"
                    _pub(conn, iid, "InterviewQuestion",
                         {"code": iid, "target": iv.get("target", ""),
                          "question": iv.get("question", ""), "crossCheck": iv.get("cross_check", "")})
                    i_ids.append(f"InterviewQuestion:{iid}")
                    rels.append({"p": "hasInterview", "o": f"InterviewQuestion:{iid}"})
                    stats["interviews"] += 1

                # ---- VerdictRule（三档判定要点，有判定内容才建）----
                v = c.get("verdict") or {}
                if v.get("pass") or v.get("partial") or v.get("fail"):
                    vr_id = f"vr-{_dots(c['id'])}"
                    _pub(conn, vr_id, "VerdictRule",
                         {"code": vr_id,
                          "verdictPass": json.dumps(v.get("pass", []), ensure_ascii=False),
                          "verdictPartial": json.dumps(v.get("partial", []), ensure_ascii=False),
                          "verdictFail": json.dumps(v.get("fail", []), ensure_ascii=False)})
                    rels.append({"p": "verdictRule", "o": f"VerdictRule:{vr_id}"})
                    stats["verdicts"] += 1

                # ---- FindingPattern（常见问题）----
                fp_ids = []
                for j, f in enumerate(c.get("findings", []), 1):
                    fid = f"ic-{_dots(c['id'])}-fp{j}"
                    _pub(conn, fid, "FindingPattern",
                         {"code": fid, "rank": str(f.get("rank", j)),
                          "problem": f.get("problem", ""), "rootCause": f.get("root_cause", ""),
                          "remediation": f.get("remediation", "")})
                    fp_ids.append(f"FindingPattern:{fid}")
                    rels.append({"p": "hasFindingPattern", "o": f"FindingPattern:{fid}"})
                    stats["findings"] += 1

                # ---- relatedCheck（区间式 range 不建边，保留原文；仅同文件内）----
                raw = []
                for r in c.get("related", []):
                    ref = r.get("ref", "")
                    raw.append(f"{ref}|{r.get('relation','')}")
                    if "-" in ref:        # 区间引用（如 1.1-1.2），无独立目标节点
                        continue
                    if re_match := by_id.get(ref):
                        rels.append({"p": "relatedCheck", "o": f"InspectionCheck:{re_match}"})
                        stats["related_edges"] += 1
                if raw:
                    data_main["relatedRaw"] = " ; ".join(raw)

                # ---- mapsToTerm（全部文号）----
                terms = _maps_to_term(c["title"], c.get("article_text", "") + json.dumps(c.get("checklist", []), ensure_ascii=False))
                for slug in terms:
                    rels.append({"p": "mapsToTerm", "o": f"baseTerm:{slug}"})
                    stats["terms_used"].add(slug)
                    stats["maps_term"] += 1

                # ---- mapsToControl（仅 jg24 内部演示控制链）----
                if doc_key == CLAUSE_DOC:
                    ctrls = _maps_to_control(c["title"], c.get("article_text", ""))
                    for slug in ctrls:
                        rels.append({"p": "mapsToControl", "o": f"control:{slug}"})
                        stats["maps_control"] += 1

                # 展开对象属性到 dataJSON（沿用平台物化约定）
                if clause_id:
                    data_main["citesClause"] = f"Clause:{clause_id}"
                if el_ids:
                    data_main["hasElement"] = el_ids
                if m_ids:
                    data_main["measuredBy"] = m_ids
                if ms_ids:
                    data_main["hasMethodStep"] = ms_ids
                if i_ids:
                    data_main["hasInterview"] = i_ids
                if fp_ids:
                    data_main["hasFindingPattern"] = fp_ids
                if terms:
                    data_main["mapsToTerm"] = [f"baseTerm:{x}" for x in terms]

                _pub(conn, cid, "InspectionCheck", data_main, relations=rels)
                stats["checks"] += 1

    stats["terms_used"] = sorted(stats["terms_used"])
    return stats


_LAYER_CODES = {"EP", "NW", "SVC", "PROTO", "MGMT"}
_STATUS_MAP = {"gap": "pending_alignment", "matched_provisional": "provisional",
               "aligned": "aligned"}

def _norm_layer(raw: str) -> str:
    """suggested_layer 带中文后缀（如 'MGMT（建议，最终以 10 工程 v1.5 为准）'）→ 纯层码。"""
    for code in _LAYER_CODES:
        if raw.strip().startswith(code):
            return code
    return "MGMT"


def import_control_placeholders() -> dict:
    """消费 control-placeholders.json → ControlPlaceholder 实体 + suggestsControl 边（幂等）。
    v1.2.0 起：aligned 占位携带权威 CT 码（ctCode/ctLayer）并挂 mapsToFormalControl 边
    指向底座 v1.5 控制；gap 仍为 pending_alignment（待 10 工程补建）。"""
    data = json.loads(PLACEHOLDERS_JSON.read_text(encoding="utf-8"))
    items = data["controls"]
    stats = {"placeholders": 0, "aligned": 0, "pending": 0, "provisional": 0,
             "suggests_edges": 0}
    with db() as conn:
        # 只清占位实体（InspectionCheck 派生 suggestsControl 边随重导重建）
        for r in conn.execute("SELECT id FROM entities WHERE type='ControlPlaceholder'").fetchall():
            conn.execute("DELETE FROM entities WHERE id=?", (r["id"],))
            conn.execute("DELETE FROM entity_versions WHERE id=?", (r["id"],))
        # 先删 InspectionCheck 上旧的 suggestsControl 关系（重导重建）
        for r in conn.execute("SELECT id,relationsJSON FROM entities WHERE type='InspectionCheck'").fetchall():
            rels = [x for x in json.loads(r["relationsJSON"]) if x["p"] != "suggestsControl"]
            conn.execute("UPDATE entities SET relationsJSON=? WHERE id=?",
                         (json.dumps(rels, ensure_ascii=False), r["id"]))

        for c in items:
            hint = c["control_code_hint"]
            pid = f"cp-{hint}"
            align = c.get("alignment", {})
            status = _STATUS_MAP.get(align.get("status", "gap"), "pending_alignment")
            layer = _norm_layer(c.get("suggested_layer", ""))
            rels = []
            data_main = {
                "controlCodeHint": hint, "controlName": c["control_name"],
                "suggestedLayer": layer, "controlTypeHint": c.get("control_type_hint", ""),
                "alignmentStatus": status, "rationale": c.get("rationale", ""),
                "sourceCheckCodes": ",".join(c.get("source_checks", [])),
                "articleRefs": ",".join(c.get("article_refs", [])),
            }
            # v1.2.0 正式对齐：占位 → v1.5 权威控制（CT 码 + mapsToFormalControl 边）
            if status == "aligned" and align.get("ct_code"):
                bid = align["base_control_id"]
                data_main.update({
                    "ctCode": align["ct_code"],
                    "ctLayer": align.get("ct_layer", layer),
                    "baseControlId": bid,
                    "baseControlTitle": align.get("base_control_title", ""),
                })
                rels.append({"p": "mapsToFormalControl", "o": f"baseControl:{bid}"})
                stats["aligned"] += 1
            # provisional（兼容旧数据）：弱关联底座 control，注明待 v1.5 CT 确认
            elif status == "provisional" and align.get("base_control_id"):
                bid = align["base_control_id"]
                rels.append({"p": "provisionalBaseControl", "o": f"baseControl:{bid}"})
                data_main["baseControlTitle"] = align.get("base_control_title", "")
                stats["provisional"] += 1
            else:
                stats["pending"] += 1
            _pub(conn, pid, "ControlPlaceholder", data_main, relations=rels)
            stats["placeholders"] += 1

        # suggestsControl 边：由 source_checks 反查 InspectionCheck（jg24 文件内索引）
        jg24_path = CHECKS_DIR / "jg24-checks.json"
        by_id = {}
        if jg24_path.exists():
            jd = json.loads(jg24_path.read_text(encoding="utf-8"))
            by_id = {c["id"]: f"ic-{_dots(c['id'])}" for c in jd["checks"]}
        for c in items:
            hint = c["control_code_hint"]
            pid = f"cp-{hint}"
            for chk in c.get("source_checks", []):
                if chk in by_id:
                    cid = by_id[chk]
                    row = conn.execute("SELECT relationsJSON FROM entities WHERE id=?", (cid,)).fetchone()
                    if not row:
                        continue
                    rels = json.loads(row["relationsJSON"])
                    rels.append({"p": "suggestsControl", "o": f"ControlPlaceholder:{pid}"})
                    conn.execute("UPDATE entities SET relationsJSON=? WHERE id=?",
                                 (json.dumps(rels, ensure_ascii=False), cid))
                    stats["suggests_edges"] += 1
    return stats


if __name__ == "__main__":
    s = import_checks()
    print("[import-checks] 完成:", json.dumps({k: v for k, v in s.items()}, ensure_ascii=False))
