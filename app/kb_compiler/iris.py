"""统一 base IRI 与命名空间（一处可改，将来换真实域名只动这里）。

大白话：IRI（Internationalized Resource Identifier，国际化资源标识符）就是给每个
类/实例一个"永不重复的网址式编号"，即使本地域名不可公网访问也无所谓——它只当稳定 id 用。
"""
from __future__ import annotations
import os
from rdflib import Namespace

# ★ 唯一事实源：权威知识层 base IRI（拍板占位值 https://schema.cheersai.local/ds/）。
#   将来换真实域名只改这一行 / 环境变量 CANONICAL_BASE_IRI。
CANONICAL_BASE_IRI = os.environ.get(
    "CANONICAL_BASE_IRI", "https://schema.cheersai.local/ds/").strip().rstrip("/") + "/"

# 派生三段命名空间（docs/05 §3.1）：
ONT_IRI = CANONICAL_BASE_IRI + "ontology/"     # TBox：类/对象属性/数据属性/形状
KB_IRI = CANONICAL_BASE_IRI + "kb/"            # ABox 权威知识（10 工程编译产物）
RUN_IRI = CANONICAL_BASE_IRI + "run/"          # ABox 运行态（InspectionRun 等，与权威隔离）

ONT = Namespace(ONT_IRI)
KB = Namespace(KB_IRI)
RUN = Namespace(RUN_IRI)

# 标准词表沿用（不新建）
W3_SKOS = "http://www.w3.org/2004/02/skos/core#"
W3_SH = "http://www.w3.org/ns/shacl#"
W3_OWL = "http://www.w3.org/2002/07/owl#"
W3_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
W3_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
W3_XSD = "http://www.w3.org/2001/XMLSchema#"


def kb_instance_iri(type_key: str, slug: str) -> str:
    """实体实例 URI：<kb>/<type>/<slug>，直接复用 10 工程稳定 slug（id 不变则 URI 不变）。"""
    return KB_IRI + f"{type_key}/{slug}"
