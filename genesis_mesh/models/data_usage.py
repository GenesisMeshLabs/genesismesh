"""Data Usage Attestation Layer models (v0.47).

Attestation and enforcement for data access.  Provides signed records that
settlement systems can verify.  Payment, royalty calculation, and external
settlement are explicitly out of scope.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from .genesis import Signature


class DataSourceDescriptor(BaseModel):
    """Identifies a data source and its classification."""

    source_id: str
    source_type: str  # "personal" | "proprietary" | "public" | "synthetic"
    owner_sovereign_id: str
    classification_tags: list[str] = Field(default_factory=list)


class DataLicensePolicy(BaseModel):
    """Operator-defined policy: which data sources may be accessed, under what terms."""

    policy_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    licensor_sovereign_id: str
    licensee_sovereign_id: str
    allowed_source_ids: list[str] = Field(
        default_factory=list,
        description="Explicit allowlist. Empty = deny all.",
    )
    allowed_access_types: list[str] = Field(
        default_factory=list,
        description='"read"|"write"|"derive"|"train". Empty = read-only.',
    )
    max_volume_bytes_per_session: int | None = Field(default=None)
    prohibited_classification_tags: list[str] = Field(default_factory=list)
    valid_from: datetime
    valid_until: datetime
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        d = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class DataAccessIntent(BaseModel):
    """Pre-execution declaration of intended data access."""

    intent_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_sovereign_id: str
    decision_id: str
    declared_sources: list[DataSourceDescriptor]
    declared_access_types: list[str]
    estimated_volume_bytes: int | None = None
    declared_at: datetime
    expires_at: datetime
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        d = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class DataAccessRecord(BaseModel):
    """Post-execution record of actual data accessed."""

    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    intent_id: str
    agent_sovereign_id: str
    decision_id: str
    accessed_sources: list[DataSourceDescriptor]
    access_types_used: list[str]
    actual_volume_bytes: int | None = None
    accessed_at: datetime
    completed_at: datetime | None = None
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        d = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class DataUsageViolation(BaseModel):
    """Record of a data policy violation."""

    violation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    intent_id: str | None = None
    record_id: str | None = None
    agent_sovereign_id: str
    violation_type: str
    detail: str
    detected_at: datetime
