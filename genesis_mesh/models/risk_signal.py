"""Peer Risk Signal models (v0.37).

POSITIONING NOTE: This is NOT a reputation system.
GenesisMesh does not rank sovereigns globally.  There is no shared reputation
ledger, no federation-wide score, and no cross-sovereign ranking.  Each sovereign
computes and stores its own local signals for its own decisions only.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .genesis import Signature


class PeerRiskSignal(BaseModel):
    """Locally-computed EWMA signal that one sovereign maintains about a counterparty.

    Signal is in [0.0, 1.0].  It is time-decayed between updates and updated
    from ExecutionEvidence outcomes.  Two sovereigns observing the same counterparty
    will have independent, unshared signals.
    """

    signal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    from_sovereign_id: str = Field(..., description="Signal owner — local only")
    to_sovereign_id: str = Field(..., description="Counterparty being observed")
    signal: float = Field(..., ge=0.0, le=1.0)
    update_count: int = Field(default=0, ge=0)
    last_updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    alpha: float = Field(default=0.2, gt=0.0, le=1.0,
                         description="EWMA smoothing factor (0 < alpha <= 1)")
    decay_lambda: float = Field(default=0.05, gt=0.0,
                                description="Exponential decay rate (per day)")
    signature: Signature | None = Field(default=None)

    def to_canonical_json(self) -> str:
        data = self.model_dump(exclude={"signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


class RiskSignalUpdate(BaseModel):
    """Record of a single EWMA update to a PeerRiskSignal."""

    update_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    signal_id: str = Field(..., description="Links to PeerRiskSignal")
    evidence_id: str = Field(..., description="ExecutionEvidence that triggered update")
    prior_signal: float = Field(..., ge=0.0, le=1.0)
    posterior_signal: float = Field(..., ge=0.0, le=1.0)
    delta: float = Field(..., description="posterior_signal - prior_signal (after decay)")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_by_sovereign_id: str
    signature: Signature | None = Field(default=None)

    def to_canonical_json(self) -> str:
        data = self.model_dump(exclude={"signature"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))


class RiskAnomaly(BaseModel):
    """Raised when a signal drops faster than historical variance.

    Anomaly detection is applied when history has >= 10 RiskSignalUpdate records.
    |Δ - μ| > sigma_threshold × σ  →  RiskAnomaly
    """

    anomaly_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    signal_id: str
    from_sovereign_id: str
    to_sovereign_id: str
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    signal_before: float = Field(..., ge=0.0, le=1.0)
    signal_after: float = Field(..., ge=0.0, le=1.0)
    delta: float = Field(..., description="posterior - prior (before decay)")
    sigma_multiples: float = Field(..., description="How many σ above threshold")
    trigger_update_id: str = Field(..., description="RiskSignalUpdate that triggered detection")
