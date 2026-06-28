"""Context integrity models for context-injection defense (v0.41)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from .genesis import Signature


class ContextTree(BaseModel):
    """Canonical snapshot of agent context at a point in time."""

    system_prompt_hash: str
    turn_count: int
    message_hashes: list[str]
    tool_result_hashes: list[str]
    total_token_estimate: int

    def canonical_hash(self) -> str:
        data = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(data.encode()).hexdigest()


class ContextAppendSegment(BaseModel):
    """A declared, typed unit of post-base context permitted to arrive after commitment."""

    segment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    segment_type: str
    source_id: str
    max_tokens: int
    provenance_digest: str
    actual_tokens: int | None = None
    signature: Signature | None = None


class ContextIntegrityRecord(BaseModel):
    """Pre-execution commitment: base context + declared append segments."""

    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_sovereign_id: str
    decision_id: str
    base_context: ContextTree
    committed_base_context_hash: str = Field(default="")
    declared_append_segments: list[ContextAppendSegment] = Field(default_factory=list)
    max_total_tokens: int
    committed_at: datetime
    expires_at: datetime
    signature: Signature | None = None

    @model_validator(mode="after")
    def _fill_base_hash(self) -> "ContextIntegrityRecord":
        if not self.committed_base_context_hash:
            self.committed_base_context_hash = self.base_context.canonical_hash()
        return self

    def to_canonical_json(self) -> str:
        d = self.model_dump(mode="json")
        d.pop("signature", None)
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class ContextViolationReport(BaseModel):
    """Record of a detected context integrity violation."""

    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    record_id: str
    agent_sovereign_id: str
    detected_at: datetime
    violation_type: str
    committed_value: str
    observed_value: str
    severity: str
