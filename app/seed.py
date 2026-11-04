"""种子：幂等初始化。法规=金规〔2024〕24号（已权威核实）。
恰好 1 条强制义务 O6(§19 动态调整审批) 初始无 Control，用于缺口反哺演示。
注意：控制项与判定口径为依据办法条文的演示性落地改写（见 docs/02）。
"""
from __future__ import annotations
import json, datetime
from .db import init_db, reset_db, db
from .ontology import base_import
from .services import versioning, audit

LAW_ID = "law-jg24"


def _pub(conn, etype, eid, data, relations=None, actor="admin", note="种子初始化"):
    relations = relations or []
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO entities(id,type,status,currentVersion,dataJSON,relationsJSON,updatedAt,updatedBy) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (eid, etype, "published", 0, json.dumps(data, ensure_ascii=False),
         json.dumps(relations, ensure_ascii=False), ts, actor))
    # 版本 1
    conn.execute(
        "INSERT INTO entity_versions(id,version,dataJSON,relationsJSON,actor,changeNote,source,createdAt) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (eid, 1, json.dumps(data, ensure_ascii=False), json.dumps(relations, ensure_ascii=False),
         actor, note, "seed", ts))
    conn.execute("UPDATE entities SET currentVersion=1 WHERE id=?", (eid,))


def seed():
    init_db()
    reset_db()
    base_import.project()
    from .config import DEMO_ACTORS
    with db() as conn:
        for name, role, label in DEMO_ACTORS:
            conn.execute("INSERT OR REPLACE INTO actors(name,role,label) VALUES(?,?,?)",
                         (name, role, label))

        now = datetime.datetime.now().isoformat(timespec="seconds")

        # ---- 法规（权威核实：金规〔2024〕24号，2024-12-27印发，公布之日起施行）----
        _pub(conn, "Law", LAW_ID, {
            "title": "银行保险机构数据安全管理办法",
            "docNo": "金规〔2024〕24号",
            "authority": "国家金融监督管理总局",
            "issued": "2024-12-27", "effective": "2024-12-27",
            "validity": "effective",
            "summary": "国家金融监督管理总局2024-12-27印发，自公布之日起施行；同时废止《银行保险机构数据安全办法》(银保监办发〔2022〕118号)。数据分类分级与全生命周期监管规章。",
            "official_url": "https://www.gov.cn/zhengce/zhengceku/202412/content_6995081.htm",
        })

        # ---- 条款（§16–19,21,71 等 12 条，聚焦分类分级）----
        clauses = [
            ("cl-16", "第16条", "数据分类分级保护制度"),
            ("cl-17", "第17条", "数据分类（客户/业务/经营管理/系统运行四类）"),
            ("cl-18", "第18条", "数据分级（核心/重要/一般；一般细分敏感/其他一般）"),
            ("cl-19", "第19条", "数据安全级别动态调整与审批"),
            ("cl-20", "第20条", "分类分级结果应用"),
            ("cl-21", "第21条", "企业级数据架构与数据资产登记"),
            ("cl-22", "第22条", "数据收集与预处理"),
            ("cl-23", "第23条", "数据存储与加密"),
            ("cl-24", "第24条", "数据使用与加工"),
            ("cl-25", "第25条", "数据传输与提供"),
            ("cl-26", "第26条", "数据删除与销毁"),
            ("cl-71", "第71条", "重要数据目录报送与报备"),
        ]
        for cid, no, title in clauses:
            _pub(conn, "Clause", cid, {"clauseNo": no, "title": title,
                                        "chapter": "分类分级" if cid != "cl-71" else "监督管理"},
                 relations=[{"p": "clauseOf", "o": f"Law:{LAW_ID}"}])

        # ---- 义务（8 条；O6=§19 裸义务，初始无 Control）----
        obligations = [
            ("ob-o1", "第16条", "应当建立数据分类分级保护制度", "mandatory", "cl-16"),
            ("ob-o2", "第16条", "应当建立数据目录和分类分级规范并动态维护", "mandatory", "cl-16"),
            ("ob-o3", "第16条", "应当根据分类分级结果采取差异化安全保护措施", "mandatory", "cl-16"),
            ("ob-o4", "第17条", "应当按客户/业务/经营管理/系统运行四类实施数据分类", "mandatory", "cl-17"),
            ("ob-o5", "第18条", "应当按核心/重要/一般三级实施数据分级", "mandatory", "cl-18"),
            ("ob-o6", "第19条", "应当建立数据安全级别动态调整审批机制", "mandatory", "cl-19"),
            ("ob-o7", "第21条", "应当登记管理全域数据资产并建立数据资产地图", "mandatory", "cl-21"),
            ("ob-o8", "第71条", "应当按监管要求报送重要数据目录并在重大变化时报备", "mandatory", "cl-71"),
        ]
        for oid, no, text, force, cl in obligations:
            _pub(conn, "Obligation", oid,
                 {"code": oid, "text": text, "force": force, "subject": "银行保险机构",
                  "clauseOf": f"Clause:{cl}"})

        # ---- 证据要求（6 项，类型层）----
        ev_reqs = [
            ("er-e1", "分类分级保护制度文件", "documentary"),
            ("er-e2", "差异化保护措施配置记录", "config_snapshot"),
            ("er-e3", "四类数据分类标签配置", "config_snapshot"),
            ("er-e4", "分级标注记录与分级目录", "system_log"),
            ("er-e5", "数据资产地图/登记台账", "documentary"),
            ("er-e6", "重要数据目录报送回执", "documentary"),
        ]
        for eid, name, kind in ev_reqs:
            _pub(conn, "EvidenceRequirement", eid,
                 {"code": eid, "name": name, "evidenceKind": kind})

        # ---- 控制项（6 个，覆盖 7 条义务；c1 覆盖 O1+O2；O6 无控制）----
        controls = [
            ("ctrl-c1", "数据分类分级保护制度与规范", "P0", "preventive",
             ["ob-o1", "ob-o2"], "查制度：是否发布分类分级保护制度与目录规范", ["er-e1"]),
            ("ctrl-c2", "差异化保护措施配置", "P1", "preventive",
             ["ob-o3"], "查配置：不同级别数据是否落差异化管控策略", ["er-e2"]),
            ("ctrl-c3", "四类数据分类标签落地", "P0", "preventive",
             ["ob-o4"], "查系统：四类标签是否在元数据中落地", ["er-e3"]),
            ("ctrl-c4", "数据分级标注与分级目录", "P0", "preventive",
             ["ob-o5"], "查记录：核心/重要/一般标注与目录是否一致", ["er-e4"]),
            ("ctrl-c5", "企业级数据资产登记与资产地图", "P1", "detective",
             ["ob-o7"], "查台账：是否建立全域资产登记与资产地图", ["er-e5"]),
            ("ctrl-c6", "重要数据目录报送报备", "P1", "corrective",
             ["ob-o8"], "查证据：是否取得报送/报备回执", ["er-e6"]),
        ]
        for cid, title, pri, kind, impls, crit, reqs in controls:
            rels = [{"p": "implementsObligation", "o": f"Obligation:{o}"} for o in impls]
            rels += [{"p": "requiresEvidence", "o": f"EvidenceRequirement:{r}"} for r in reqs]
            _pub(conn, "Control", cid,
                 {"code": cid, "title": title, "priority": pri, "controlKind": kind,
                  "judgementCriteria": crit, "method": "查制度/查配置",
                  "implementsObligation": [f"Obligation:{o}" for o in impls],
                  "requiresEvidence": [f"EvidenceRequirement:{r}" for r in reqs]},
                 relations=rels)

        # ---- 数据资产（2 个）----
        # A1 客户信息库：重要数据；6 条证据全 provided（闭环主角）
        _pub(conn, "DataAsset", "asset-customer-db", {
            "assetId": "asset-customer-db", "name": "客户信息库", "owner": "零售银行部",
            "system": "CRM核心系统", "hasClassification": "cls/important",
            "governed_by": [f"Obligation:{o}" for o in
                            ["ob-o1", "ob-o2", "ob-o3", "ob-o4", "ob-o5", "ob-o6", "ob-o7", "ob-o8"]],
        })
        # A2 交易流水数据集：敏感数据；证据有缺（用于冒烟/展示 partial/nonconform）
        _pub(conn, "DataAsset", "asset-txn-logs", {
            "assetId": "asset-txn-logs", "name": "交易流水数据集", "owner": "信息科技部",
            "system": "交易中台", "hasClassification": "cls/sensitive",
            "governed_by": [f"Obligation:{o}" for o in
                            ["ob-o1", "ob-o2", "ob-o3", "ob-o4", "ob-o5"]],
        })

        # ---- 证据记录（实例层）----
        def rec(rid, name, status, asset, ctrl, req):
            _pub(conn, "EvidenceRecord", rid, {
                "recordId": rid, "name": name, "status": status,
                "collectedAt": "2026-09-01", "locator": f"文档库/{rid}.pdf",
                "asset": asset,
                "evidencesControl": f"Control:{ctrl}",
                "fulfillsRequirement": f"EvidenceRequirement:{req}",
            }, relations=[
                {"p": "evidencesControl", "o": f"Control:{ctrl}"},
                {"p": "fulfillsRequirement", "o": f"EvidenceRequirement:{req}"},
            ])

        # A1：全部 provided
        rec("rec-a1-e1", "《数据分类分级保护制度 v3》", "provided", "asset-customer-db", "ctrl-c1", "er-e1")
        rec("rec-a1-e2", "差异化管控策略配置截图", "provided", "asset-customer-db", "ctrl-c2", "er-e2")
        rec("rec-a1-e3", "四类分类标签元数据配置", "provided", "asset-customer-db", "ctrl-c3", "er-e3")
        rec("rec-a1-e4", "分级标注日志与分级目录", "provided", "asset-customer-db", "ctrl-c4", "er-e4")
        rec("rec-a1-e5", "数据资产地图台账", "provided", "asset-customer-db", "ctrl-c5", "er-e5")
        rec("rec-a1-e6", "重要数据目录报送回执", "provided", "asset-customer-db", "ctrl-c6", "er-e6")
        # A2：provided/missing 混合
        rec("rec-a2-e1", "分类分级制度(共用)", "provided", "asset-txn-logs", "ctrl-c1", "er-e1")
        rec("rec-a2-e2", "差异化配置", "missing", "asset-txn-logs", "ctrl-c2", "er-e2")
        rec("rec-a2-e3", "分类标签配置", "provided", "asset-txn-logs", "ctrl-c3", "er-e3")
        rec("rec-a2-e4", "分级标注记录", "missing", "asset-txn-logs", "ctrl-c4", "er-e4")
        rec("rec-a2-e5", "资产地图(共用)", "provided", "asset-txn-logs", "ctrl-c5", "er-e5")

    audit.log("admin", "seed.reset", LAW_ID, {"ts": now})
    print("[seed] 完成：1 法规 / 12 条款 / 8 义务 / 6 控制 / 6 证据要求 / 2 资产 / 11 证据记录")

    # v1.1.0：金规24号 116 项监管检查知识库（幂等导入，独立可重跑）
    from .ontology import checks_import
    s = checks_import.import_checks()
    print(f"[seed] 监管检查库：{s['checks']} 检查项 / {s['elements']} 要素 / "
          f"补建法条 {s['clauses_created']} 条 / 术语映射 {s['maps_term']}")
    # v1.1.2：48 条控制需求占位（待 10 工程 v1.5 CT 编码对齐，非权威控制）
    cp = checks_import.import_control_placeholders()
    print(f"[seed] 控制需求占位：{cp['placeholders']} 条（缺口 {cp['pending']} / 暂定 {cp['provisional']}）"
          f" / suggestsControl 边 {cp['suggests_edges']}")


if __name__ == "__main__":
    seed()
