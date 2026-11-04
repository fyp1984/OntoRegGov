#!/usr/bin/env python3
"""确定性本体编译器入口：把 10 工程编辑源编译成 canonical RDF（幂等、可重复）。

用法：
  python scripts/kb_compile.py            # 编译并写 app/data/canonical.ttl
  python scripts/kb_compile.py --check   # 编译 + 跑编译期 SHACL/断言，违例即非零退出
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.kb_compiler import compiler, shacl  # noqa: E402
from app.config import APP_DATA  # noqa: E402
from rdflib import Graph  # noqa: E402
from rdflib.compare import to_canonical_graph  # noqa: E402
from pyshacl import validate  # noqa: E402

OUT = APP_DATA / "canonical.ttl"


def main():
    g, stats = compiler.compile_canonical()
    # 规范化序列化：消除 BNode 分配差异，保证同输入→同字节输出（幂等可重复）
    ttl = to_canonical_graph(g).serialize(format="turtle")
    OUT.write_text(ttl, encoding="utf-8")
    print(f"[kb_compile] 编译完成 → {OUT}")
    print(f"[kb_compile] 术语={stats['terms']} 控制={stats['controls']} "
          f"方案={stats.get('solutions',0)} 指南={stats.get('guides',0)} 专题={stats.get('topics',0)} "
          f"三元组={stats['triples']}")
    print(f"[kb_compile] 金规116检查: 检查项={stats.get('jg24_checks',0)} "
          f"要素={stats.get('jg24_elements',0)} 法条节点={stats.get('jg24_clauses',0)}")
    print(f"[kb_compile] 93号文: law={stats.get('doc93_law',0)} topic={stats.get('doc93_topic',0)} "
          f"检查项={stats.get('doc93_checks',0)} 要素={stats.get('doc93_elements',0)}")
    print(f"[kb_compile] 分层={shacl.count_by_layer(g)} 带CT码={shacl.count_ct_coded(g)}")

    if "--check" in sys.argv:
        shapes = shacl.build_compile_shapes()
        ok, _, report = validate(
            g, shacl_graph=shapes, format="turtle",
            shacl_graph_format="turtle", inference="none", advanced=True)
        errs = shacl.assert_compile_constraints(g)
        # CSV↔MD 双向对账 + TBox 与 ontology.yaml 一致性（有漂移即失败）
        drift = list(stats.get("code_drift", [])) + list(stats.get("tbox_drift", []))
        print(f"[kb_compile] pySHACL conforms={ok}; 脚本断言违例={len(errs)}; "
              f"CSV/TBox 漂移={len(drift)}")
        if not ok:
            print(report[-2000:])
        for e in errs:
            print("  阻断:", e)
        for d in drift:
            print("  漂移:", d)
        if not ok or errs or drift:
            sys.exit(1)
        print(f"[kb_compile] CSV 对账 0 漂移 / TBox 一致（{stats.get('csv_rows')} 控制登记 / "
              f"{stats.get('entity_types')} 实体类型 / {stats.get('relation_types')} 关系类型）✅")
        print("[kb_compile] 编译期校验全绿 ✅")


if __name__ == "__main__":
    main()
