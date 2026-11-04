"""app/services/ingest_review.py — 知识库 ingest 候选人工审核（复用平台轻量服务风格）。

读 10_知识库工程 ingest/staging/<batch>/ 的 manifest.json + 草稿 md + decisions.json；
批准/拒绝写 decisions.json（与 CLI `approve <id>`/`reject <id>` 同一文件，`merge --apply` 无缝衔接）。
铁律：只写 decisions.json，绝不直接写 content/（人审通过后由 merge 事务化入库）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from ..config import KB_ROOT

INGEST = KB_ROOT / "ingest"
STAGING = INGEST / "staging"

_CASE_KEYS = ("event_date", "case_type", "org_involved", "penalty_amount",
              "affected_scale", "root_causes")


def _decisions(d: Path) -> dict:
    p = d / "decisions.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def batches() -> list[dict]:
    """按时间倒序列出 staging 批次及审核进度。"""
    out = []
    for d in sorted(STAGING.glob("*"), reverse=True):
        if not d.is_dir():
            continue
        man_p = d / "manifest.json"
        if not man_p.exists():
            continue
        try:
            items = json.loads(man_p.read_text(encoding="utf-8"))
        except Exception:
            items = []
        decisions = _decisions(d)
        n_ok = sum(1 for i in items if decisions.get(i.get("proposed_id")) == "approved")
        n_no = sum(1 for i in items if decisions.get(i.get("proposed_id")) == "rejected")
        out.append({
            "batch": d.name,
            "candidates": len(items),
            "approved": n_ok,
            "rejected": n_no,
            "pending": len(items) - n_ok - n_no,
        })
    return out


def _latest_batch() -> str:
    bs = batches()
    return bs[0]["batch"] if bs else ""


def queue(batch: str | None = None) -> dict:
    """返回一个批次的候选列表（manifest + 草稿 frontmatter 富字段 + 审核状态）。"""
    batch = batch or _latest_batch()
    if not batch:
        return {"batch": "", "items": []}
    d = STAGING / batch
    man_p = d / "manifest.json"
    if not man_p.exists():
        return {"batch": batch, "items": []}
    man = json.loads(man_p.read_text(encoding="utf-8"))
    decisions = _decisions(d)
    items = []
    for m in man:
        eid = m.get("proposed_id", "")
        extra: dict = {}
        draft = d / f"{eid}.md"
        if draft.exists():
            txt = draft.read_text(encoding="utf-8")
            fm = re.match(r"^---\n(.*?)\n---", txt, re.S)
            if fm:
                try:
                    extra = yaml.safe_load(fm.group(1)) or {}
                except Exception:
                    extra = {}
        items.append({
            "id": eid,
            "type": m.get("type", ""),
            "title": m.get("title", ""),
            "title_en": extra.get("title_en", ""),
            "level": extra.get("level", "L2"),
            "tags": extra.get("tags", []),
            "aliases": extra.get("aliases", []),
            "summary": extra.get("summary", ""),
            "official_url": m.get("official_url", ""),
            "confidence": m.get("confidence", "medium"),
            "source_kind": m.get("source_kind", "external"),
            "sources": m.get("sources", []),
            "relations": m.get("proposed_relations", []),
            "evidence_quotes": m.get("evidence_quotes", []),
            "case_fields": {k: extra.get(k, "") for k in _CASE_KEYS if extra.get(k)},
            "status": decisions.get(eid, "pending"),
        })
    return {"batch": batch, "items": items}


def decide(batch: str | None, eid: str, action: str) -> dict:
    """批准/拒绝候选，写 decisions.json（与 CLI 同文件）。"""
    if action not in ("approve", "reject"):
        raise ValueError("action 必须为 approve 或 reject")
    batch = batch or _latest_batch()
    if not batch:
        raise ValueError("staging 下无批次")
    d = STAGING / batch
    if not (d / f"{eid}.md").exists():
        raise ValueError(f"候选不存在: {eid}")
    decisions = _decisions(d)
    decisions[eid] = "approved" if action == "approve" else "rejected"
    (d / "decisions.json").write_text(
        json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"batch": batch, "id": eid, "status": decisions[eid]}
