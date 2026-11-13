#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图存储后端冒烟：对 memory / oxigraph / fuseki 后端同步全量物化图并跑 SPARQL 断言。
默认跑 memory + oxigraph；GRAPH_STORE_BACKEND=fuseki 时对 Fuseki 跑同一组断言。
退出码 0 = 全部通过。运行：python scripts/smoke/smoke_graphstore.py
"""
from __future__ import annotations
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app import seed  # noqa: E402
from app.ontology import graph_backend  # noqa: E402

P = """
PREFIX dsec:  <http://dsec.local/ontology/2026/1#>
PREFIX dsecr: <http://dsec.local/resource/>
PREFIX dsecb: <http://dsec.local/base/1.0#>
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
"""


def _assert(cond, msg):
    if cond:
        print(f"  [PASS] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        sys.exit(1)


def _n(sparql) -> int:
    rows = graph_backend.query(P + sparql)
    return int(rows[0]["n"]) if rows else -1


def run():
    print("=" * 60)
    print(f"[smoke-graphstore] backend = {graph_backend.current_backend()}")
    print("=" * 60)
    seed.seed()   # 内含 checks_import + 占位导入；勿重复调用 import_checks（会清派生类型）

    sync = graph_backend.sync()
    print(f"[sync] 镜像完成：{sync}")
    st = graph_backend.stats()
    print(f"[stats] {st}")

    # 底座快照（dsecb: 投影命名空间）+ 平台实体 + 检查定义 + 占位
    n_law = _n("SELECT (COUNT(?c) AS ?n) WHERE { ?c a dsecb:law }")
    n_ctl = _n("SELECT (COUNT(?c) AS ?n) WHERE { ?c a dsecb:control }")
    n_term = _n("SELECT (COUNT(?c) AS ?n) WHERE { ?c a dsecb:term }")
    n_check = _n("SELECT (COUNT(?c) AS ?n) WHERE { ?c a dsec:InspectionCheck }")
    n_ph = _n("SELECT (COUNT(?c) AS ?n) WHERE { ?c a dsec:ControlPlaceholder }")
    n_edge = _n("SELECT (COUNT(?c) AS ?n) WHERE { ?c dsec:suggestsControl ?o }")
    n_asset = _n("SELECT (COUNT(?c) AS ?n) WHERE { ?c a dsec:DataAsset }")

    print(f"  法条 {n_law} / 控制 {n_ctl} / 术语 {n_term} / 检查 {n_check} / 占位 {n_ph} / 边 {n_edge} / 资产 {n_asset}")
    _assert(n_law == 22, "底座 22 部法规")
    _assert(n_ctl == 91, "底座 91 条权威控制（v1.5）")
    _assert(n_term == 218, "底座 218 个术语")
    _assert(n_check == 116, "监管检查 116 项")
    _assert(n_ph == 48, "控制需求占位 48 条")
    _assert(n_edge == 133, "suggestsControl 边 133")
    _assert(n_asset == 2, "演示资产 2 个")

    # 对齐链路：占位→CT 码（35 aligned 应有 ctCode 数据属性）
    n_aligned = _n("SELECT (COUNT(?c) AS ?n) WHERE { ?c a dsec:ControlPlaceholder ; dsec:ctCode ?code }")
    print(f"  已对齐（带 CT 码）占位 = {n_aligned}")
    _assert(n_aligned == 35, "35 条占位已带 CT 码（v1.5 正式对齐）")

    # 主链可达：检查 1.1 → 条款 → 法规；检查 → 建议控制（check URI=inspectioncheck/ic-1-1，law URI=law/law-jg24）
    reach = _n(P + """
        SELECT (COUNT(DISTINCT ?cp) AS ?n) WHERE {
          ?check  dsec:checkCode "1.1" .
          ?check  dsec:citesClause ?clause .
          ?clause dsec:clauseOf <http://dsec.local/resource/law/law-jg24> .
          ?check  dsec:suggestsControl ?cp .
          ?cp     a dsec:ControlPlaceholder }""")
    print(f"  金规24号 检查1.1→条款→法规→建议控制 可达占位 = {reach}")
    _assert(reach >= 1, "SPARQL 多跳 join 查询可用（法规→…→占位可达）")

    # ASK 布尔
    ok = graph_backend.ask(P + "ASK { <http://dsec.local/resource/law/law-jg24> a dsec:Law }")
    _assert(ok, "ASK 查询可用")

    print("=" * 60)
    print("[smoke-graphstore] 全部断言通过 ✅")
    print("=" * 60)


if __name__ == "__main__":
    run()
