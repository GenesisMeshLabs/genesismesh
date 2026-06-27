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
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from .genesis import Signature


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
    signature: Signature | None = Field(
        default=None,
        description="Ed25519 signature by the executor over canonical evidence body",
    )

    def to_canonical_json(self) -> str:
        """Return deterministic JSON the executor signs.

        Excludes ``signature`` only.  ``prev_evidence_digest`` IS included —
        the chain integrity depends on it being signed.  Sorted keys, compact
        separators.
        """
        data = self.model_dump(exclude={"signature"}, mode="json")
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
