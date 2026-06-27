"""Peer Risk Signals — EWMA + exponential time decay (v0.37).

Each sovereign maintains local, independent signals for each counterparty.
There is no shared ledger, no global ranking, no cross-sovereign aggregation.

Algorithm:
  Decay: signal = signal × exp(-λ × elapsed_days)
  Update: signal = α × outcome_value + (1 - α) × decayed_signal
  Anomaly: |Δ - μ| > sigma_threshold × σ  over last 10 updates
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.execution import ExecutionEvidence
from ..models.risk_signal import PeerRiskSignal, RiskAnomaly, RiskSignalUpdate

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OUTCOME_VALUES: dict[str, float] = {
    "success": 1.0,
    "partial": 0.5,
    "failure": 0.0,
}

_DEFAULT_INITIAL_SIGNAL = 0.5
_DEFAULT_ALPHA = 0.2
_DEFAULT_LAMBDA = 0.05
_DEFAULT_SIGMA_THRESHOLD = 3.0
_ANOMALY_MIN_HISTORY = 10


# ---------------------------------------------------------------------------
# create_risk_signal
# ---------------------------------------------------------------------------


def create_risk_signal(
    from_sovereign_id: str,
    to_sovereign_id: str,
    signing_key: nacl.signing.SigningKey,
    *,
    initial_signal: float = _DEFAULT_INITIAL_SIGNAL,
    alpha: float = _DEFAULT_ALPHA,
    decay_lambda: float = _DEFAULT_LAMBDA,
    now: datetime | None = None,
) -> PeerRiskSignal:
    """Create and sign a new PeerRiskSignal starting at initial_signal."""
    now = now or datetime.now(timezone.utc)
    sig_obj = PeerRiskSignal(
        from_sovereign_id=from_sovereign_id,
        to_sovereign_id=to_sovereign_id,
        signal=initial_signal,
        update_count=0,
        last_updated_at=now,
        created_at=now,
        alpha=alpha,
        decay_lambda=decay_lambda,
    )
    sig = sign_model(sig_obj, signing_key, from_sovereign_id)
    return sig_obj.model_copy(update={"signature": sig})


# ---------------------------------------------------------------------------
# decay helpers
# ---------------------------------------------------------------------------


def _apply_decay(signal: float, last_updated_at: datetime, decay_lambda: float,
                 now: datetime) -> float:
    """Clamp-safe exponential decay: signal × exp(-λ × elapsed_days)."""
    elapsed_seconds = (now - last_updated_at).total_seconds()
    elapsed_days = max(0.0, elapsed_seconds) / 86400.0
    decayed = signal * math.exp(-decay_lambda * elapsed_days)
    return max(0.0, min(1.0, decayed))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


# ---------------------------------------------------------------------------
# update_risk_signal
# ---------------------------------------------------------------------------


def update_risk_signal(
    signal: PeerRiskSignal,
    evidence: ExecutionEvidence,
    signing_key: nacl.signing.SigningKey,
    *,
    history: list[RiskSignalUpdate] | None = None,
    anomaly_sigma_threshold: float = _DEFAULT_SIGMA_THRESHOLD,
    now: datetime | None = None,
) -> tuple[PeerRiskSignal, RiskSignalUpdate, RiskAnomaly | None]:
    """Update a PeerRiskSignal from an ExecutionEvidence outcome.

    Steps:
    1. Apply time decay since last_updated_at.
    2. Compute outcome_value from evidence.outcome.
    3. Apply EWMA: signal = α × outcome_value + (1 - α) × decayed_signal.
    4. Build signed RiskSignalUpdate.
    5. If history has ≥ 10 records, check for anomaly.
    6. Sign and return updated signal.
    """
    now = now or datetime.now(timezone.utc)

    # 1. Decay
    prior_decayed = _apply_decay(signal.signal, signal.last_updated_at,
                                 signal.decay_lambda, now)

    # 2. Outcome value
    outcome_value = _OUTCOME_VALUES.get(evidence.outcome, 0.5)

    # 3. EWMA
    posterior = _clamp(signal.alpha * outcome_value + (1 - signal.alpha) * prior_decayed)
    delta = posterior - prior_decayed

    # 4. Build update record
    update = RiskSignalUpdate(
        signal_id=signal.signal_id,
        evidence_id=evidence.evidence_id,
        prior_signal=_clamp(signal.signal),
        posterior_signal=posterior,
        delta=delta,
        updated_at=now,
        updated_by_sovereign_id=signal.from_sovereign_id,
    )
    u_sig = sign_model(update, signing_key, signal.from_sovereign_id)
    update = update.model_copy(update={"signature": u_sig})

    # 5. Anomaly detection
    anomaly: RiskAnomaly | None = None
    if history and len(history) >= _ANOMALY_MIN_HISTORY:
        recent_deltas = [u.delta for u in history[-_ANOMALY_MIN_HISTORY:]]
        mu = statistics.mean(recent_deltas)
        sigma = statistics.stdev(recent_deltas) if len(recent_deltas) > 1 else 0.0
        if sigma > 0.0 and abs(delta - mu) > anomaly_sigma_threshold * sigma:
            anomaly = RiskAnomaly(
                signal_id=signal.signal_id,
                from_sovereign_id=signal.from_sovereign_id,
                to_sovereign_id=signal.to_sovereign_id,
                detected_at=now,
                signal_before=_clamp(signal.signal),
                signal_after=posterior,
                delta=delta,
                sigma_multiples=abs(delta - mu) / sigma,
                trigger_update_id=update.update_id,
            )

    # 6. Build new signed signal
    updated_signal = signal.model_copy(update={
        "signal": posterior,
        "update_count": signal.update_count + 1,
        "last_updated_at": now,
        "signature": None,
    })
    s_sig = sign_model(updated_signal, signing_key, signal.from_sovereign_id)
    updated_signal = updated_signal.model_copy(update={"signature": s_sig})

    return updated_signal, update, anomaly


# ---------------------------------------------------------------------------
# decay_risk_signal
# ---------------------------------------------------------------------------


def decay_risk_signal(
    signal: PeerRiskSignal,
    signing_key: nacl.signing.SigningKey,
    *,
    now: datetime | None = None,
) -> PeerRiskSignal:
    """Apply time decay without a new evidence update (e.g. on a schedule)."""
    now = now or datetime.now(timezone.utc)
    decayed = _apply_decay(signal.signal, signal.last_updated_at, signal.decay_lambda, now)
    updated = signal.model_copy(update={
        "signal": decayed,
        "last_updated_at": now,
        "signature": None,
    })
    sig = sign_model(updated, signing_key, signal.from_sovereign_id)
    return updated.model_copy(update={"signature": sig})


# ---------------------------------------------------------------------------
# check_risk_signal_gate
# ---------------------------------------------------------------------------


def check_risk_signal_gate(
    signal: PeerRiskSignal,
    minimum_signal: float,
    issuer_public_keys: list[str],
    *,
    at_time: datetime | None = None,
) -> tuple[bool, str]:
    """Check if a signal passes the minimum threshold gate.

    Returns (passed, reason_string).
    """
    at_time = at_time or datetime.now(timezone.utc)

    if signal.signature is None:
        return False, "risk_signal_invalid_signature"

    if not any(verify_model_signature(signal, signal.signature, pub) for pub in issuer_public_keys):
        return False, "risk_signal_invalid_signature"

    decayed = _apply_decay(signal.signal, signal.last_updated_at, signal.decay_lambda, at_time)
    if decayed < minimum_signal:
        return False, f"risk_signal_below_minimum (current={decayed:.3f}, min={minimum_signal:.3f})"

    return True, "ok"


# ---------------------------------------------------------------------------
# RiskSignalGate — plugs into BoundaryEngine via add_gate()
# ---------------------------------------------------------------------------


class RiskSignalGate:
    """Callable gate that requires the current (decayed) peer risk signal to be
    above a minimum before authorization proceeds.

    Usage (opt-in):

        gate = RiskSignalGate(
            signal=peer_risk_signal,
            minimum_signal=0.4,
            issuer_public_keys=[from_sovereign_pub_b64],
        )
        engine.add_gate(gate)
    """

    def __init__(
        self,
        signal: PeerRiskSignal,
        minimum_signal: float,
        issuer_public_keys: list[str],
    ) -> None:
        self._signal = signal
        self._minimum = minimum_signal
        self._keys = issuer_public_keys

    def __call__(self, context: object, terms: object) -> object:
        from ..models.context import GateResult

        passed, reason = check_risk_signal_gate(
            self._signal, self._minimum, self._keys
        )
        if passed:
            return GateResult(
                gate_name="risk_signal",
                passed=True,
                detail=(
                    f"peer risk signal for '{self._signal.to_sovereign_id}' "
                    f"passes minimum {self._minimum:.3f}"
                ),
            )
        return GateResult(
            gate_name="risk_signal",
            passed=False,
            detail=reason,
        )
