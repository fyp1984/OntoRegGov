"""确定性本体编译器（deterministic knowledge compiler）。

把 10_知识库工程的"编辑权威源"（人写的 ontology.yaml + content/*.md + id-registry.yaml +
control-codes.csv）按固定规则单向编译成带统一 base IRI 的 RDF/OWL + SKOS 图。
单向、确定性、幂等：同一份输入，任何机器任何时刻编译出的三元组集合完全相同。

关键边界（docs/05 §1 / 本任务写入约束）：
- 本编译器**只读** 10 工程编辑源；**绝不读** build 产物 data/knowledge.json（那是比对参照，不是输入）。
- 编译器自身**不 import** 10 工程任何脚本，自含解析，避免耦合其运行态。
"""
