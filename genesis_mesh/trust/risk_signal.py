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
from ..models.risk_signal import (
    PeerRiskSignal,
    RiskAnomaly,
    RiskSignalUpdate,
    SeedIsolationReport,
)

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

_SEED_MIN_HISTORY = 20
_DEFAULT_SEED_THRESHOLD = 0.5
_DEFAULT_CFS_WEIGHT = 0.4
_DEFAULT_VDS_WEIGHT = 0.3
_DEFAULT_SFS_WEIGHT = 0.3


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


# ---------------------------------------------------------------------------
# Seed isolation pattern scoring helpers
# ---------------------------------------------------------------------------


def _compute_cfs(deltas: list[float]) -> tuple[float, float, float]:
    """Credit Farming Score. Returns (cfs, early_window_mean, late_window_mean).

    Measures how much better the early history is vs the late history.
    Positive CFS indicates sustained early inflation followed by deterioration.
    """
    n = len(deltas)
    window = max(1, int(n * 0.2))
    early_mean = statistics.mean(deltas[:window])
    late_mean = statistics.mean(deltas[-window:])
    cfs = max(0.0, min(1.0, early_mean - late_mean))
    return cfs, early_mean, late_mean


def _compute_vds(deltas: list[float]) -> tuple[float, int | None]:
    """Volatility Discontinuity Score. Returns (vds, best_midpoint_index).

    Measures whether variance abruptly changed at a specific point in time,
    suggesting a behavioral mode switch.
    """
    n = len(deltas)
    if n < 4:
        return 0.0, None

    best_vds = 0.0
    best_mid: int | None = None
    for mid in range(2, n - 1):
        left = deltas[:mid]
        right = deltas[mid:]
        if len(left) < 2 or len(right) < 2:
            continue
        std_left = statistics.stdev(left)
        std_right = statistics.stdev(right)
        vds_at_mid = abs(std_left - std_right)
        if vds_at_mid > best_vds:
            best_vds = vds_at_mid
            best_mid = mid

    return min(1.0, best_vds), best_mid


def _compute_sfs(deltas: list[float]) -> tuple[float, int]:
    """Streak Fragility Score. Returns (sfs, max_success_streak).

    Measures whether the history contains an implausibly long success streak
    relative to the expected outcome distribution under a benign model.
    """
    n = len(deltas)
    if n == 0:
        return 0.0, 0

    max_streak = 0
    current = 0
    for d in deltas:
        if d > 0:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0

    if max_streak == 0:
        return 0.0, 0

    p_benign = 0.5 ** max_streak
    sfs = max(0.0, min(1.0, (max_streak / n) * (1.0 - p_benign)))
    return sfs, max_streak


# ---------------------------------------------------------------------------
# assess_seed_isolation
# ---------------------------------------------------------------------------


def assess_seed_isolation(
    signal: PeerRiskSignal,
    history: list[RiskSignalUpdate],
    *,
    seed_threshold: float = _DEFAULT_SEED_THRESHOLD,
    cfs_weight: float = _DEFAULT_CFS_WEIGHT,
    vds_weight: float = _DEFAULT_VDS_WEIGHT,
    sfs_weight: float = _DEFAULT_SFS_WEIGHT,
    min_history_for_assessment: int = _SEED_MIN_HISTORY,
    now: datetime | None = None,
) -> SeedIsolationReport:
    """Assess whether a counterparty's update history matches adversarial seed patterns.

    Three pattern scores are computed from the full update history:
    - CFS (Credit Farming Score): early history much better than late history
    - VDS (Volatility Discontinuity Score): abrupt change in variance at some midpoint
    - SFS (Streak Fragility Score): implausibly long success streak

    seed_probability = cfs_weight*CFS + vds_weight*VDS + sfs_weight*SFS

    Returns isolated=False with all scores 0.0 when history < min_history_for_assessment.
    Assessment is local — two sovereigns may reach different conclusions about the same
    counterparty based on their independent histories.
    """
    now = now or datetime.now(timezone.utc)

    if len(history) < min_history_for_assessment:
        return SeedIsolationReport(
            signal_id=signal.signal_id,
            from_sovereign_id=signal.from_sovereign_id,
            to_sovereign_id=signal.to_sovereign_id,
            assessed_at=now,
            history_length=len(history),
            credit_farming_score=0.0,
            volatility_discontinuity_score=0.0,
            streak_fragility_score=0.0,
            seed_probability=0.0,
            isolated=False,
            threshold_used=seed_threshold,
            early_window_mean_delta=0.0,
            late_window_mean_delta=0.0,
            max_success_streak=0,
            discontinuity_midpoint_index=None,
        )

    deltas = [u.delta for u in history]

    cfs, early_mean, late_mean = _compute_cfs(deltas)
    vds, best_mid = _compute_vds(deltas)
    sfs, max_streak = _compute_sfs(deltas)

    seed_probability = min(1.0, cfs_weight * cfs + vds_weight * vds + sfs_weight * sfs)

    return SeedIsolationReport(
        signal_id=signal.signal_id,
        from_sovereign_id=signal.from_sovereign_id,
        to_sovereign_id=signal.to_sovereign_id,
        assessed_at=now,
        history_length=len(history),
        credit_farming_score=cfs,
        volatility_discontinuity_score=vds,
        streak_fragility_score=sfs,
        seed_probability=seed_probability,
        isolated=seed_probability > seed_threshold,
        threshold_used=seed_threshold,
        early_window_mean_delta=early_mean,
        late_window_mean_delta=late_mean,
        max_success_streak=max_streak,
        discontinuity_midpoint_index=best_mid,
    )


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


# ---------------------------------------------------------------------------
# SeedIsolationGate — plugs into BoundaryEngine via add_gate()
# ---------------------------------------------------------------------------


class SeedIsolationGate:
    """Callable gate that blocks execution if seed_probability exceeds threshold.

    Usage (opt-in):

        gate = SeedIsolationGate(
            signal=peer_risk_signal,
            history=update_history,
            seed_threshold=0.5,
        )
        engine.add_gate(gate)
    """

    def __init__(
        self,
        signal: PeerRiskSignal,
        history: list[RiskSignalUpdate],
        seed_threshold: float = 0.5,
    ) -> None:
        self._signal = signal
        self._history = history
        self._threshold = seed_threshold

    def __call__(self, context: object, terms: object) -> object:
        from ..models.context import GateResult

        report = assess_seed_isolation(
            self._signal,
            self._history,
            seed_threshold=self._threshold,
        )
        if report.isolated:
            return GateResult(
                gate_name="seed_isolation",
                passed=False,
                detail=(
                    f"counterparty '{self._signal.to_sovereign_id}' isolated "
                    f"(seed_probability={report.seed_probability:.3f} > {self._threshold})"
                ),
            )
        return GateResult(
            gate_name="seed_isolation",
            passed=True,
            detail=(
                f"counterparty '{self._signal.to_sovereign_id}' passes seed check "
                f"(seed_probability={report.seed_probability:.3f})"
            ),
        )
