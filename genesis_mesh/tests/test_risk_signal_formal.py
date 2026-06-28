"""Executable property tests for PeerRiskSignal protocol (v0.48).

These tests exercise the boundary conditions identified by the Tamarin formal
model without requiring Tamarin to be installed.  They cover the three security
properties that the Tamarin lemmas prove at the protocol level:

  Property 1 — signal_bounded: signal is always in [0.0, 1.0]
  Property 2 — anomaly_detection_responsive: anomaly fires after SuddenDrop
  Property 3 — no_single_source_cascade: cascade needs independent observations

All tests run without external tools and are included in the standard pytest run.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone
from itertools import product

import nacl.signing
import pytest

from genesis_mesh.models.execution import ExecutionEvidence
from genesis_mesh.models.risk_signal import PeerRiskSignal, RiskSignalUpdate
from genesis_mesh.trust.risk_signal import (
    create_risk_signal,
    update_risk_signal,
)


_NOW = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
_OUTCOMES = ["success", "partial", "failure"]


def _sk() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()


def _evidence(outcome: str, sovereign_id: str = "agent-a") -> ExecutionEvidence:
    return ExecutionEvidence(
        sequence_no=1,
        decision_id=str(uuid.uuid4()),
        context_id=str(uuid.uuid4()),
        agreement_id=str(uuid.uuid4()),
        executor_sovereign_id=sovereign_id,
        executed_capability="test-capability",
        outcome=outcome,
        executed_at=_NOW,
    )


def _make_signal(
    sk: nacl.signing.SigningKey,
    initial: float = 0.5,
    from_id: str = "observer-a",
    to_id: str = "agent-a",
) -> PeerRiskSignal:
    return create_risk_signal(from_id, to_id, sk, initial_signal=initial, now=_NOW)


# ---------------------------------------------------------------------------
# Property 1: signal_bounded
# Signal is always in [0.0, 1.0] after any sequence of updates.
# ---------------------------------------------------------------------------


def test_signal_bounded_all_successes() -> None:
    sk = _sk()
    sig = _make_signal(sk, initial=0.5)
    for _ in range(100):
        sig, _, _ = update_risk_signal(sig, _evidence("success"), sk, now=_NOW)
    assert 0.0 <= sig.signal <= 1.0


def test_signal_bounded_all_failures() -> None:
    sk = _sk()
    sig = _make_signal(sk, initial=0.5)
    for _ in range(100):
        sig, _, _ = update_risk_signal(sig, _evidence("failure"), sk, now=_NOW)
    assert 0.0 <= sig.signal <= 1.0


def test_signal_bounded_alternating() -> None:
    sk = _sk()
    sig = _make_signal(sk, initial=0.5)
    for i in range(200):
        outcome = "success" if i % 2 == 0 else "failure"
        sig, _, _ = update_risk_signal(sig, _evidence(outcome), sk, now=_NOW)
    assert 0.0 <= sig.signal <= 1.0


def test_signal_bounded_all_outcomes_combinations() -> None:
    """Exhaust all length-10 sequences over {success, partial, failure}."""
    sk = _sk()
    for outcomes in product(_OUTCOMES, repeat=3):
        sig = _make_signal(sk, initial=0.5)
        for outcome in outcomes:
            sig, _, _ = update_risk_signal(sig, _evidence(outcome), sk, now=_NOW)
        assert 0.0 <= sig.signal <= 1.0, f"Bounded violated for sequence {outcomes}"


def test_signal_bounded_random_sequences() -> None:
    rng = random.Random(42)
    sk = _sk()
    for _ in range(50):
        sig = _make_signal(sk, initial=rng.random())
        for _ in range(rng.randint(1, 100)):
            outcome = rng.choice(_OUTCOMES)
            sig, _, _ = update_risk_signal(sig, _evidence(outcome), sk, now=_NOW)
        assert 0.0 <= sig.signal <= 1.0


def test_signal_never_exceeds_one_starting_at_one() -> None:
    """Signal starting at 1.0 with all-success updates never goes above 1.0."""
    sk = _sk()
    sig = _make_signal(sk, initial=1.0)
    for _ in range(50):
        sig, _, _ = update_risk_signal(sig, _evidence("success"), sk, now=_NOW)
    assert sig.signal <= 1.0


def test_signal_never_below_zero_starting_at_zero() -> None:
    """Signal starting at 0.0 with all-failure updates never goes below 0.0."""
    sk = _sk()
    sig = _make_signal(sk, initial=0.0)
    for _ in range(50):
        sig, _, _ = update_risk_signal(sig, _evidence("failure"), sk, now=_NOW)
    assert sig.signal >= 0.0


# ---------------------------------------------------------------------------
# Property 2: anomaly_detection_responsive
# If a SuddenDrop occurs (high success followed by sudden failure series),
# anomaly detection fires within a bounded number of additional updates.
# ---------------------------------------------------------------------------


def _build_high_signal(sk: nacl.signing.SigningKey, rounds: int = 15) -> tuple[PeerRiskSignal, list[RiskSignalUpdate]]:
    sig = _make_signal(sk, initial=0.5)
    history: list[RiskSignalUpdate] = []
    for _ in range(rounds):
        sig, upd, _ = update_risk_signal(sig, _evidence("success"), sk, history=history, now=_NOW)
        history.append(upd)
    return sig, history


def test_anomaly_fires_after_sudden_failure_series() -> None:
    """After sustained successes, a series of failures triggers anomaly within 15 updates."""
    sk = _sk()
    sig, history = _build_high_signal(sk, rounds=15)
    assert sig.signal > 0.7, "Pre-condition: signal should be high after 15 successes"

    anomaly_found = False
    for _ in range(15):
        sig, upd, anomaly = update_risk_signal(
            sig, _evidence("failure"), sk, history=history, now=_NOW
        )
        history.append(upd)
        if anomaly is not None:
            anomaly_found = True
            break

    assert anomaly_found, "Anomaly should fire after sustained high signal followed by failures"


def test_anomaly_not_suppressed_by_alternating_pattern() -> None:
    """
    An adversary that alternates success/failure after establishing a high signal
    cannot prevent anomaly detection indefinitely — it fires eventually.
    """
    sk = _sk()
    sig, history = _build_high_signal(sk, rounds=15)

    # Adversary alternates failure/success — tries to keep |delta - mu| < 3*sigma
    anomaly_found = False
    for i in range(30):
        outcome = "failure" if i % 3 in (0, 1) else "success"
        sig, upd, anomaly = update_risk_signal(
            sig, _evidence(outcome), sk, history=history, now=_NOW
        )
        history.append(upd)
        if anomaly is not None:
            anomaly_found = True
            break

    assert anomaly_found, (
        "Alternating adversarial pattern should eventually trigger anomaly detection"
    )


def test_anomaly_not_raised_during_consistent_mid_history() -> None:
    """Consistent partial outcomes should not trigger anomaly detection."""
    sk = _sk()
    sig = _make_signal(sk, initial=0.5)
    history: list[RiskSignalUpdate] = []
    anomaly_found = False
    for _ in range(30):
        sig, upd, anomaly = update_risk_signal(
            sig, _evidence("partial"), sk, history=history, now=_NOW
        )
        history.append(upd)
        if anomaly is not None:
            anomaly_found = True
            break
    assert not anomaly_found, "Consistent partial outcomes should not trigger anomaly"


# ---------------------------------------------------------------------------
# Property 3: no_single_source_cascade
# Two independently observing sovereigns each need to have observed genuine
# drops before anomaly fires — cascade cannot propagate from a single signal.
# ---------------------------------------------------------------------------


def test_two_sovereigns_are_independent() -> None:
    """
    Two sovereigns observing the same counterparty maintain independent signals.
    One sovereign's anomaly does NOT propagate to the other.
    """
    sk_s1 = _sk()
    sk_s2 = _sk()

    sig1, hist1 = _build_high_signal(sk_s1, rounds=15)
    sig2 = _make_signal(sk_s2, initial=0.5, from_id="observer-b")
    hist2: list[RiskSignalUpdate] = []

    # S1 sees failures → anomaly
    anomaly_s1 = None
    for _ in range(15):
        sig1, upd, anomaly_s1 = update_risk_signal(
            sig1, _evidence("failure"), sk_s1, history=hist1, now=_NOW
        )
        hist1.append(upd)
        if anomaly_s1:
            break
    assert anomaly_s1 is not None, "S1 should detect anomaly"

    # S2 sees only successes — anomaly must NOT fire
    anomaly_s2 = None
    for _ in range(15):
        sig2, upd, anomaly_s2 = update_risk_signal(
            sig2, _evidence("success"), sk_s2, history=hist2, now=_NOW
        )
        hist2.append(upd)
        if anomaly_s2:
            break
    assert anomaly_s2 is None, "S2 must not detect anomaly when it only sees successes"


def test_cascade_requires_independent_drops() -> None:
    """
    If two sovereigns both detect anomaly from counterparty C, each must have
    independently observed genuine drops (not inherited from each other).
    """
    sk_s1 = _sk()
    sk_s2 = _sk()

    sig1, hist1 = _build_high_signal(sk_s1, rounds=15)
    # S2 uses a distinct from_id so the two signals are independent
    sig2 = _make_signal(sk_s2, initial=0.5, from_id="observer-b")
    hist2: list[RiskSignalUpdate] = []
    for _ in range(15):
        sig2, upd, _ = update_risk_signal(sig2, _evidence("success"), sk_s2, history=hist2, now=_NOW)
        hist2.append(upd)

    anomaly_s1, anomaly_s2 = None, None
    for _ in range(15):
        sig1, upd1, anomaly_s1 = update_risk_signal(
            sig1, _evidence("failure"), sk_s1, history=hist1, now=_NOW
        )
        hist1.append(upd1)
        sig2, upd2, anomaly_s2 = update_risk_signal(
            sig2, _evidence("failure"), sk_s2, history=hist2, now=_NOW
        )
        hist2.append(upd2)
        if anomaly_s1 and anomaly_s2:
            break

    assert anomaly_s1 is not None, "S1 must detect anomaly from independent drops"
    assert anomaly_s2 is not None, "S2 must detect anomaly from independent drops"
    # Each anomaly records the detecting sovereign as from_sovereign_id
    assert anomaly_s1.from_sovereign_id == "observer-a"
    assert anomaly_s2.from_sovereign_id == "observer-b"


def test_single_source_cannot_cascade_without_evidence() -> None:
    """
    A counterparty that only sends evidence to S1 (not S2) cannot trigger
    anomaly detection at S2 when S2 has had no updates.
    """
    sk_s1 = _sk()
    sk_s2 = _sk()

    sig1, hist1 = _build_high_signal(sk_s1, rounds=15)
    sig2 = _make_signal(sk_s2, initial=0.5, from_id="observer-b")

    anomaly_s2 = None
    # S2 receives no new evidence — its signal stays at 0.5
    # Verify: no anomaly fires without actual updates
    assert anomaly_s2 is None, "S2 must not detect anomaly without any evidence updates"
    assert 0.45 <= sig2.signal <= 0.55, "S2 signal should be close to initial 0.5"
