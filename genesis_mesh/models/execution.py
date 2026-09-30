"""Execution Evidence models: ExecutionEvidence and EvidenceChain.

An ExecutionEvidence record captures what happened after a BoundaryDecision
authorized execution.  Multiple records produced under the same BoundaryDecision
are linked in a hash chain via prev_evidence_digest — each record commits to the
SHA-256 of the prior record's canonical JSON.  Any insertion, deletion, reorder,
or tampering breaks the chain and is detectable.

Signing invariant
-----------------
``ExecutionEvidence.to_canonical_json()`` excludes ``signature`` only.
``prev_evidence_digest`` IS included — the chain integrity depends on it being
signed by the executor.

Resource chains (v0.59)
-----------------------
A record may also name the resource it acted on (``resource_id``, e.g. a
secret) and link to the previous record for that resource across decisions
(``resource_sequence``, ``prev_resource_digest``).  These fields are omitted
from the canonical form when absent, so records created before v0.59 keep
byte-identical canonical forms and signatures.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from .genesis import Signature


ResourceAction = Literal["create", "rotate", "revoke", "update", "delete"]

#: Optional resource-chain fields, omitted from the canonical form when None.
RESOURCE_CHAIN_FIELDS: tuple[str, ...] = (
    "resource_id",
    "resource_action",
    "resource_sequence",
    "prev_resource_digest",
)


class ExecutionEvidence(BaseModel):
    """Signed record of one capability execution event.

    Links to the prior record via ``prev_evidence_digest`` (None if first).
    The executor signs the full canonical form including the prior digest, so
    any reordering or gap is cryptographically detectable.
    """

    evidence_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique evidence identifier",
    )
    sequence_no: int = Field(
        ...,
        ge=1,
        description="Monotonically increasing sequence number (1-based) within this decision",
    )
    decision_id: str = Field(
        ...,
        description="Links to the BoundaryDecision that authorized this execution",
    )
    context_id: str = Field(
        ...,
        description="Links to the ContextRecord for denormalized lookup",
    )
    agreement_id: str = Field(
        ...,
        description="Underlying AgreementRecord, denormalized for fast lookup",
    )
    executor_sovereign_id: str = Field(
        ...,
        description="Sovereign performing the execution",
    )
    executed_capability: str = Field(
        ...,
        description="Capability that was executed",
    )
    execution_parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Final parameters used (may differ from request_parameters)",
    )
    executed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of execution",
    )
    outcome: str = Field(
        ...,
        description='"success", "failure", or "partial"',
    )
    outcome_detail: str | None = Field(
        default=None,
        description="Optional human-readable outcome detail",
    )
    prev_evidence_digest: str | None = Field(
        default=None,
        description="SHA-256 hex of prior record's canonical JSON (None if first)",
    )
    resource_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description="Stable identifier of the resource acted on (never a value), v0.59",
    )
    resource_action: ResourceAction | None = Field(
        default=None,
        description="create, rotate, revoke, update or delete (v0.59)",
    )
    resource_sequence: int | None = Field(
        default=None,
        ge=1,
        description="1-based position in the resource's history across decisions (v0.59)",
    )
    prev_resource_digest: str | None = Field(
        default=None,
        description="digest() of the previous record for the same resource (v0.59)",
    )
    signature: Signature | None = Field(
        default=None,
        description="Ed25519 signature by the executor over canonical evidence body",
    )

    def to_canonical_json(self) -> str:
        """Return deterministic JSON the executor signs.

        Excludes ``signature`` only.  ``prev_evidence_digest`` IS included —
        the chain integrity depends on it being signed.  The v0.59 resource
        fields are omitted when None, so older records keep identical bytes.
        Sorted keys, compact separators.
        """
        exclude = {"signature"} | {f for f in RESOURCE_CHAIN_FIELDS if getattr(self, f) is None}
        data = self.model_dump(exclude=exclude, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        """Return SHA-256 hex of this record's canonical JSON."""
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


# ---------------------------------------------------------------------------
# EvidenceChain
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceChain:
    """A BoundaryDecision followed by an ordered list of ExecutionEvidence records.

    ``records`` must be ordered by sequence_no (1, 2, 3, ...).
    ``decision`` is the BoundaryDecision that authorized the executions.
    """

    decision_id: str
    records: list[ExecutionEvidence] = field(default_factory=list)
