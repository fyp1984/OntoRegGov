"""加载 10 工程的 schema 权威（只读）：
- ontology/ontology.yaml：实体类型 / 关系类型 / 枚举词表（元模型单一事实源）
- data/control-codes.csv：91 控制 CT 编码登记表（CT 码单一事实源）

大白话：以前编译器把类/关系/枚举"手抄"在代码里，CT 码从各 Markdown 汇总；
现在直接读权威登记表，一旦手抄值与登记表漂移就编译失败——消除双源风险。
"""
from __future__ import annotations
import csv
import re
import yaml
from ..config import KB_ROOT

# layer 英文词 → CT 层码（与 docs/05 一致；ontology.yaml 用英文词，CSV 也用英文词）
LAYER_TO_CODE = {"endpoint": "EP", "network": "NW", "service": "SVC",
                 "protocol": "PROTO", "management": "MGMT"}


def load_ontology_schema() -> dict:
    """解析 ontology.yaml → {entity_types:[keys], relation_types:[keys], enums:{...}}。"""
    p = KB_ROOT / "ontology" / "ontology.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    entity_types = [e["key"] for e in data.get("entity_types", [])]
    relation_types = [r["key"] for r in data.get("relation_types", [])]
    levels = [x["id"] for x in data.get("levels", [])]
    # 从 control 字段定义里抽枚举
    ctl = next(e for e in data["entity_types"] if e["key"] == "control")
    fmap = {f["key"]: f for f in ctl.get("fields", [])}
    # lifecycle / layer / control_type 枚举写在 desc，形如 "a|b|c"
    def parse_enum(desc: str) -> list[str]:
        m = re.search(r"((?:[\w-]+\([^)]*\)[,|]?)+)", desc)
        if not m:
            return []
        return re.findall(r"([a-z][\w-]*)\(", m.group(1)) or []
    enums = {
        "level": levels,
        "status": ["draft", "reviewed", "stale"],  # common_fields.status: draft|reviewed|stale
        "layer": parse_enum(fmap["layer"]["desc"]),
        "lifecycle": parse_enum(fmap["lifecycle"]["desc"]),
        "controlType": parse_enum(fmap["control_type"]["desc"]),
    }
    return {
        "entity_types": entity_types,
        "relation_types": relation_types,
        "enums": enums,
        "id_pattern": data.get("meta", {}).get("id_pattern", ""),
    }


def load_control_codes() -> dict[str, dict]:
    """读 control-codes.csv（CT 编码权威登记表）→ {id: {code,title,layer,control_type,family}}。"""
    p = KB_ROOT / "data" / "control-codes.csv"
    out: dict[str, dict] = {}
    with open(p, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rid = row["id"].strip()
            out[rid] = {
                "code": row["code"].strip(),
                "title": row["title"].strip(),
                "layer": row["layer"].strip(),
                "control_type": row["control_type"].strip(),
                "family": row["family"].strip(),
            }
    return out
