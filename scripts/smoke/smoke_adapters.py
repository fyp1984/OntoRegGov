"""SPI 适配层装配与切换冒烟（任务线2·工作包A 阶段B1 实测）。

不起 HTTP 服务、不起浏览器；纯进程内脚本。运行：
    ./.venv/bin/python scripts/smoke/smoke_adapters.py
覆盖：
  1) registry 装配：按 config.ADAPTERS 装配，list 全部适配器 + health 全量报告；
  2) RetrieverAdapter 切换：memory ↔ oxigraph 同查询结果一致性（Control=115 / InspectionCheck=344）；
  3) LLMAdapter：无 key 走 rule 降级(degraded=true)；模拟有 key 时 health/capabilities 翻转；
  4) PolicyAdapter / MaskerAdapter：占位返回符合契约。
"""
from __future__ import annotations
import json

from app.config import ADAPTERS
from app.adapters import (build_registry, get_registry, get_retriever,
                          get_policy, get_masker, RetrieverAdapter)

Q_CONTROL = "SELECT (COUNT(?s) AS ?n) WHERE { ?s a <http://dsec.local/base/1.0#control> }"
Q_CHECK = "SELECT (COUNT(?s) AS ?n) WHERE { ?s a <http://dsec.local/ontology/2026/1#InspectionCheck> }"


def hr(t=""):
    print("\n" + "=" * 72)
    if t:
        print(f"【{t}】")
        print("-" * 72)


def main():
    hr("0. ADAPTERS 配置（P3 配置驱动，env 可覆盖）")
    print(json.dumps(ADAPTERS, ensure_ascii=False, indent=2))

    hr("1. registry 装配：list 全部适配器")
    reg = build_registry()
    print(f"已注册 {len(reg)} 个适配器: {reg.names()}")
    for a in reg.list():
        print(f"  - kind={a.kind:9s} name={a.name:14s} v{a.version} caps={a.capabilities()}")

    hr("1b. registry health 全量报告")
    for row in reg.health_report():
        print(f"  {row['name']:14s} status={row['health'].get('status'):15s} | {row['health'].get('note','')}")

    hr("1c. 按 capability 过滤（sparql.select → 应只命中三个 retriever）")
    for a in reg.by_capability("sparql.select"):
        print(f"  - {a.kind}/{a.name}: {a.capabilities()}")

    hr("2. RetrieverAdapter 切换：memory ↔ oxigraph 同查询一致性")
    mem = RetrieverAdapter("memory")
    oxi = RetrieverAdapter("oxigraph")
    print("memory health:", json.dumps(mem.health(), ensure_ascii=False))
    print("oxigraph sync ->", json.dumps(oxi.sync(), ensure_ascii=False))
    print("oxigraph health:", json.dumps(oxi.health(), ensure_ascii=False))
    rows = {}
    for label, adapter in [("memory", mem), ("oxigraph", oxi)]:
        rows[label] = {
            "control": adapter.query(Q_CONTROL)[0]["n"],
            "inspectionCheck": adapter.query(Q_CHECK)[0]["n"],
        }
        print(f"  [{label:9s}] control={rows[label]['control']}  inspectionCheck={rows[label]['inspectionCheck']}")
    assert rows["memory"] == rows["oxigraph"], "memory 与 oxigraph 结果不一致！"
    assert rows["memory"]["control"] == 115, rows["memory"]
    assert rows["memory"]["inspectionCheck"] == 344, rows["memory"]
    print("  ✅ 两后端结果一致（control=115, inspectionCheck=344）")

    # 配置激活的 retriever（默认 memory）
    act = get_retriever()
    print(f"  配置激活 retriever = {act.name}（ADAPTERS['retriever']={ADAPTERS['retriever']}）")

    hr("3. LLMAdapter：无 key / 有 key 两条路径")
    from app.adapters import llm as llm_mod
    sample = ("第一条 为落实数据安全管理义务，处理个人信息应当遵循合法、正当、必要原则。"
              "严禁未经授权向第三方提供个人信息。")
    # 3a 无 key 路径
    llm_mod.LLM_API_KEY = ""
    from app.adapters import LLMAdapter
    la = LLMAdapter(name=ADAPTERS["llm"])
    print("  无 key health:", json.dumps(la.health(), ensure_ascii=False))
    res = la.execute({"text": sample, "documentId": "smoke-doc"})
    print(f"  无 key execute: degraded={res['degraded']} candidates={len(res['candidates'])} reason={res.get('reason')}")
    provs = sorted({c['provenance'] for c in res['candidates']})
    print(f"  candidates provenance={provs}（应含 llm-degraded）")
    assert res["degraded"] is True
    assert set(provs) == {"llm-degraded"}, provs
    # 3b 模拟有 key（仅翻转 health/capabilities，不真实发网络请求）
    llm_mod.LLM_API_KEY = "sk-dummy-not-used"
    print("  有 key health:", json.dumps(la.health(), ensure_ascii=False))
    print("  有 key capabilities:", la.capabilities())
    assert la.health()["status"] == "ok" and "extract.llm" in la.capabilities()
    llm_mod.LLM_API_KEY = ""   # 还原
    print("  ✅ 无 key 走 rule 降级(degraded=true)；有 key 时 health/caps 正确翻转")

    hr("4. PolicyAdapter / MaskerAdapter 占位契约")
    pol = get_policy()
    print("  policy health:", json.dumps(pol.health(), ensure_ascii=False))
    print("  policy check:", json.dumps(pol.check("editor", "law-jg24", "read"), ensure_ascii=False))
    assert pol.check()["allow"] is True
    mask = get_masker()
    print("  masker health:", json.dumps(mask.health(), ensure_ascii=False))
    try:
        mask.execute({"text": "x"})
    except NotImplementedError as e:
        print("  masker execute -> NotImplementedError(符合占位契约):", e)
    print("  ✅ 占位返回符合契约")

    hr("ALL PASS")


if __name__ == "__main__":
    main()
