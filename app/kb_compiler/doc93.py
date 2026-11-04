"""93号文（金办发〔2025〕93号）自查要点 → canonical RDF 编译器（v1.6.0 新增）。

大白话：把附件1《金融机构数据安全管理自查要点》里带编号的"是否……"逐条自查项，
照着金规116检查同一副"骨架"（InspectionCheck + CheckElement + citesClause）编译进权威知识层。
law/topic 两个实体不在本模块——它们由 parse.py 定向读 content/laws|topics 的 canonical MD 后，
走通用实体管线（同 term/control）编译；本模块只负责"检查项集合"这一块。

只读边界：本模块只读 10 工程 `ingest/v17/att1-selfcheck.txt`（附件1 纯文字提取），绝不回写。
数据纪律：编号子项共 13 个（三5/四5/六3），来自附件1原文；一/二/五为整段式问句、无逐条编号，
不在此建检查项（已由专题 topic 叙事覆盖）。附件2 报送表 139/140 行属"填报模板"，非知识实体，
本切片不编（见 CHANGELOG v1.6.0 未做项）。
"""
from __future__ import annotations
import hashlib
import re
from pathlib import Path

from rdflib import Graph, URIRef, Literal, RDF, RDFS

from ..config import KB_ROOT
from . import iris

# 附件1 纯文字提取（只读）
ATT1 = KB_ROOT / "ingest" / "v17" / "att1-selfcheck.txt"

# 中文大类序号 → 阿拉伯（93号文六方面；本模块只取有逐条编号的三/四/六）
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}

# 法规/专题稳定 slug（与 parse.TARGET_CONTENT 对齐）
LAW_ID = "finance-data-security-special-action-2025"
TOPIC_ID = "topic-finance-data-security-special-action"

# 附件1 自查要点 子项的编号骨架（逐行匹配用）
_CAT_RE = re.compile(r"^([一二三四五六])、(.+?)\s*$")
_ITEM_RE = re.compile(r"^(\d+)\.([^。]+?)。(.*)$")


def _sha(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def parse_att1() -> list[dict]:
    """从 att1-selfcheck.txt 确定性抽取 13 个带编号自查子项。

    返回 [{cat_cn, cat_no(阿拉伯), cat_name, idx, title, question}]，按原文出现顺序。
    """
    if not ATT1.exists():
        return []
    items: list[dict] = []
    cur_cn, cur_name = "", ""
    for line in ATT1.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        mc = _CAT_RE.match(s)
        if mc:
            cur_cn, cur_name = mc.group(1), mc.group(2).strip()
            continue
        mi = _ITEM_RE.match(s)
        if mi and cur_cn in ("三", "四", "六"):   # 仅这三类有逐条编号子项
            items.append({
                "cat_cn": cur_cn,
                "cat_no": _CN_NUM[cur_cn],
                "cat_name": cur_name,
                "idx": int(mi.group(1)),
                "title": mi.group(2).strip(),
                "question": mi.group(3).strip(),
            })
    return items


def compile_doc93(g: Graph, index: dict) -> dict:
    """把 93号文 13 个自查子项编入图。返回计数 dict。

    复用金规检查形状（与 compiler._compile_check_11 同构）：
      InspectionCheck --checkCode/domain/priority/articleNo/summary--> 数据属性
      InspectionCheck --citesClause--> Clause(附件1) --citesLaw--> 93号文 law
      InspectionCheck --hasElement--> CheckElement(elementCode/criteria)
    """
    O = iris.ONT
    items = parse_att1()

    # 93号文 law 实例 URI（优先用通用管线已编译的 URI，否则按稳定 slug 直接构造）
    law_uri = index[LAW_ID][1] if LAW_ID in index else URIRef(iris.kb_instance_iri("law", LAW_ID))

    # 1 个 Clause 节点代表"附件1 自查要点"，并 citesLaw 指向 93号文正文（打通链）
    clause = URIRef(iris.KB_IRI + "clause/cl-93-att1")
    g.add((clause, RDF.type, O["Clause"]))
    g.add((clause, RDFS.label, Literal("附件1 金融机构数据安全管理自查要点", lang="zh")))
    g.add((clause, O["articleNo"], Literal("附件1")))
    g.add((clause, O["title"], Literal("附件1 金融机构数据安全管理自查要点", lang="zh")))
    g.add((clause, O["sourcePath"], Literal("ingest/v17/att1-selfcheck.txt")))
    g.add((clause, O["contentHash"], Literal(_sha("cl-93-att1", "附件1"))))
    g.add((clause, O["citesLaw"], law_uri))

    n_check = n_el = 0
    for it in items:
        code = f"93-{it['cat_no']}.{it['idx']}"           # 如 93-3.1
        slug = "ic-" + code.replace(".", "-")             # ic-93-3-1
        subj = URIRef(iris.KB_IRI + "inspectioncheck/" + slug)
        g.add((subj, RDF.type, O["InspectionCheck"]))
        g.add((subj, RDFS.label, Literal(it["title"], lang="zh")))
        g.add((subj, O["title"], Literal(it["title"], lang="zh")))
        g.add((subj, O["checkCode"], Literal(code)))
        g.add((subj, O["domain"], Literal(it["cat_name"])))
        g.add((subj, O["priority"], Literal("P1")))
        g.add((subj, O["articleNo"], Literal("附件1 自查要点")))
        g.add((subj, O["summary"], Literal(it["question"], lang="zh")))
        g.add((subj, O["sourcePath"], Literal("ingest/v17/att1-selfcheck.txt")))
        g.add((subj, O["contentHash"], Literal(_sha(code, it["title"], it["question"]))))
        g.add((subj, O["citesClause"], clause))
        n_check += 1

        # 1 个 CheckElement（该自查问句本身）
        el = URIRef(iris.KB_IRI + "checkelement/" + slug + "-el-1")
        g.add((el, RDF.type, O["CheckElement"]))
        g.add((el, RDFS.label, Literal(it["question"], lang="zh")))
        g.add((el, O["elementCode"], Literal(f"{code}.1")))
        g.add((el, O["criteria"], Literal("", lang="zh")))
        g.add((el, O["sourcePath"], Literal("ingest/v17/att1-selfcheck.txt")))
        g.add((subj, O["hasElement"], el))
        n_el += 1

    return {"checks": n_check, "elements": n_el, "clauses": 1,
            "law_id": LAW_ID, "topic_id": TOPIC_ID}
