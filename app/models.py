"""Pydantic v2 DTO：API 入参友好校验（第一轨）。"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional


class EntityCreate(BaseModel):
    type: str
    id: str
    data: dict = Field(default_factory=dict)
    relations: list = Field(default_factory=list)
    actor: str = "editor"


class EntityUpdate(BaseModel):
    data: Optional[dict] = None
    relations: Optional[list] = None
    actor: str = "editor"
    changeNote: str = ""


class ExtractReq(BaseModel):
    documentId: str
    mode: str = "rule"           # rule | llm


class ReviewDecision(BaseModel):
    action: str                  # approved/rejected/needs_changes/merged
    actor: str
    note: str = ""
    edits: Optional[dict] = None


class AssessmentReq(BaseModel):
    assetId: str
    actor: str = "system"


class ProposalCreate(BaseModel):
    reason: str
    targetKind: str = "Control"
    raisedFrom: str = ""
    payload: dict = Field(default_factory=dict)
    actor: str = "system"


class ProposalDecision(BaseModel):
    decision: str                # accepted/rejected/closed
    actor: str
    note: str = ""
