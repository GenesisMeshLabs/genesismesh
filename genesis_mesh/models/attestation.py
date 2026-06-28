"""Verifiable Logic Attestation models (v0.40).

ModelAttestation: signed declaration of exact execution context before a capability runs.
AttestationPolicy: operator-defined allowlist of permitted model configurations.
ToolManifest: ordered tool list with a stable hash (sorted before hashing).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .genesis import Signature


class ToolManifest(BaseModel):
    """Ordered list of tools available to the agent at execution time.

    manifest_hash is computed from sorted(tool_ids) so that tool ordering
    does not affect the hash — two agents with the same tool set produce
    the same hash regardless of declaration order.
    """

    tool_ids: list[str]
    manifest_hash: str = Field(
        default="",
        description="SHA-256 of canonical JSON of sorted tool_ids. "
                    "Computed on construction if empty.",
    )

    def compute_hash(self) -> str:
        data = json.dumps(sorted(self.tool_ids), separators=(",", ":"))
        return hashlib.sha256(data.encode()).hexdigest()

    @model_validator(mode="after")
    def _fill_manifest_hash(self) -> "ToolManifest":
        if not self.manifest_hash:
            self.manifest_hash = self.compute_hash()
        return self


class ModelAttestation(BaseModel):
    """Signed declaration of exact execution context before capability runs.

    An agent signs this immediately before invoking a capability. A
    LogicAttestationGate validates it against the operator's AttestationPolicy.
    Non-repudiable: the agent's key binds the declared context.
    """

    attestation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_sovereign_id: str
    model_id: str = Field(..., description='e.g. "claude-sonnet-4-6"')
    model_version_tag: str = Field(..., description='e.g. "20251001" or SHA prefix')
    system_prompt_hash: str = Field(..., description="SHA-256 of exact system prompt bytes (UTF-8)")
    tool_manifest_hash: str = Field(..., description="SHA-256 of sorted tool_ids canonical JSON")
    token_id: str | None = Field(
        default=None,
        description="Optional IBCT token_id this attestation is bound to",
    )
    attested_at: datetime
    expires_at: datetime
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        data = self.model_dump(exclude={"signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class AttestationPolicy(BaseModel):
    """Operator-defined policy for which model configurations are permitted.

    Empty allowlists mean "any value is permitted" for that dimension.
    All three dimensions (model, prompt, tools) are independently checked.
    """

    policy_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    operator_sovereign_id: str
    allowed_model_ids: list[str] = Field(
        default_factory=list,
        description="Allowlist of model_id values. Empty = any model permitted.",
    )
    allowed_system_prompt_hashes: list[str] = Field(
        default_factory=list,
        description="Allowlist of system_prompt_hash values. Empty = any prompt.",
    )
    allowed_tool_manifest_hashes: list[str] = Field(
        default_factory=list,
        description="Allowlist of tool_manifest_hash values. Empty = any tools.",
    )
    require_bound_token: bool = Field(
        default=False,
        description="If True, attestation.token_id must be set.",
    )
    valid_from: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    valid_until: datetime
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        data = self.model_dump(exclude={"signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))
