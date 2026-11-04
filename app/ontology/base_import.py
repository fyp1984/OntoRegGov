"""底座只读投影（v1.15.0 工程收敛切源）：统一走 canonical 编译器产出 dsecb 富字段底座快照。

大白话：旧版把 10 工程 build 产物 knowledge.json 手工"抄"成一份精简副本（仅 8 类、只投
type/title/summary/seeAlso）——该**手工副本路径已退役**；现一律由确定性编译器把编辑源编成
canonical RDF，再投影为平台 dsecb 命名空间快照：单一正本、同输入同输出、绝不回写底座。
"""
from __future__ import annotations
from rdflib import Graph, RDF, OWL
from .ns import DSECB
from ..config import BASE_SNAPSHOT_TTL, KB_ROOT


def project() -> str:
    # 编辑源可达（研发态）：确定性编译器 + 适配器，产富字段底座快照（唯一正本链路）
    if KB_ROOT.exists():
        from ..kb_compiler.adapter import write_snapshot
        return write_snapshot()
    # 编辑源不可达（打包运行态）：保留既有快照，绝不覆盖为空
    if BASE_SNAPSHOT_TTL.exists():
        return BASE_SNAPSHOT_TTL.read_text(encoding="utf-8")
    # 两无：生成最小空快照，保证零依赖可跑
    g = Graph()
    g.bind("dsecb", DSECB)
    g.add((DSECB["Note"], RDF.type, OWL.Class))
    out = g.serialize(format="turtle")
    BASE_SNAPSHOT_TTL.write_text(out, encoding="utf-8")
    return out


if __name__ == "__main__":
    project()
    print(f"base snapshot -> {BASE_SNAPSHOT_TTL}")
