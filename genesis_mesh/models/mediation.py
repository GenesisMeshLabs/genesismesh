"""Process-Level Execution Mediation models (v0.45).

GenesisGuard is a local enforcement sidecar — a non-LLM, deterministic process
that validates authorization artifacts (BoundaryDecision, IBCT) before spawning
any subprocess on behalf of an agent.

See docs/examples/process-level-mediation.md for advisory vs. mandatory mode
distinction and the 5-point mandatory enforcement checklist.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from .genesis import Signature


class ExecutionMediationRequest(BaseModel):
    """Agent's request to GenesisGuard to mediate a capability execution."""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_sovereign_id: str
    requested_capability: str
    decision_id: str
    token_id: str | None = Field(default=None)
    subprocess_command: list[str] = Field(
        ...,
        description="Command + args. No shell expansion occurs.",
    )
    allowed_env_vars: list[str] = Field(
        default_factory=list,
        description="Env var keys the subprocess may inherit. All others stripped.",
    )
    requested_at: datetime
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        d = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class MediatedExecutionReceipt(BaseModel):
    """Cryptographic proof that GenesisGuard mediated a subprocess execution."""

    receipt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str
    agent_sovereign_id: str
    capability: str
    decision_id: str
    subprocess_pid: int
    subprocess_exit_code: int | None = None
    mediated_at: datetime
    completed_at: datetime | None = None
    guard_sovereign_id: str
    signature: Signature | None = None

    def to_canonical_json(self) -> str:
        d = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class MediationRejection(BaseModel):
    """Record of a GenesisGuard rejection with typed reason."""

    rejection_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str
    agent_sovereign_id: str
    rejected_at: datetime
    reason: str
    detail: str | None = None
