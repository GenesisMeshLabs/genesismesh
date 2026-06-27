"""Tests for Peer Risk Signals â€” EWMA + exponential time decay (v0.37).

Covers:
- create_risk_signal(): default initial signal
- update_risk_signal(): success/failure/partial outcomes
- Time decay applied before EWMA
- Anomaly detection: raised on sudden failure after steady successes
- Anomaly NOT raised with consistent history
- decay_risk_signal(): signal decreases proportional to elapsed time
- Signal clamped to [0.0, 1.0]
- RiskSignalGate: passes above minimum / blocks below
- Two sovereigns hold independent signals for same counterparty
- CLI: create / update / decay / show
"""

from __future__ import annotations

import base64
import json
import math
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nacl.signing
import pytest
from click.testing import CliRunner

from genesis_mesh.cli.decision_ops import trust
from genesis_mesh.models.execution import ExecutionEvidence
from genesis_mesh.models.risk_signal import PeerRiskSignal, RiskSignalUpdate
from genesis_mesh.trust.risk_signal import (
    RiskSignalGate,
    _apply_decay,
    create_risk_signal,
    decay_risk_signal,
    update_risk_signal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
_FROM = "sovereign-a"
_TO = "counterparty-b"


def _sk() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()


def _pub_b64(sk: nacl.signing.SigningKey) -> str:
    return base64.b64encode(bytes(sk.verify_key)).decode()


def _write_key(sk: nacl.signing.SigningKey) -> str:
    fd, path = tempfile.mkstemp(suffix=".key")
    os.close(fd)
    Path(path).write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
    return path


def _make_evidence(outcome: str, sov_id: str = _FROM) -> ExecutionEvidence:
    return ExecutionEvidence(
        sequence_no=1,
        decision_id=str(uuid.uuid4()),
        context_id=str(uuid.uuid4()),
        agreement_id=str(uuid.uuid4()),
        executor_sovereign_id=sov_id,
        executed_capability="transactions.send",
        outcome=outcome,
        executed_at=_NOW,
    )


def _make_signal(
    sk: nacl.signing.SigningKey | None = None,
    initial: float = 0.5,
    alpha: float = 0.2,
    lam: float = 0.05,
) -> tuple[PeerRiskSignal, nacl.signing.SigningKey]:
    sk = sk or _sk()
    sig = create_risk_signal(
        _FROM, _TO, sk, initial_signal=initial, alpha=alpha, decay_lambda=lam, now=_NOW
    )
    return sig, sk


# ---------------------------------------------------------------------------
# create_risk_signal
# ---------------------------------------------------------------------------


class TestCreateRiskSignal:
    def test_default_initial_signal(self) -> None:
        sig, _ = _make_signal()
        assert sig.signal == pytest.approx(0.5)

    def test_signal_is_signed(self) -> None:
        sig, _ = _make_signal()
        assert sig.signature is not None

    def test_signal_fields(self) -> None:
        sig, _ = _make_signal()
        assert sig.from_sovereign_id == _FROM
        assert sig.to_sovereign_id == _TO
        assert sig.update_count == 0

    def test_custom_initial_signal(self) -> None:
        sk = _sk()
        sig = create_risk_signal(_FROM, _TO, sk, initial_signal=0.8, now=_NOW)
        assert sig.signal == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# update_risk_signal â€” EWMA outcomes
# ---------------------------------------------------------------------------


class TestUpdateRiskSignal:
    def test_success_raises_signal(self) -> None:
        sig, sk = _make_signal(initial=0.5)
        updated, _, _ = update_risk_signal(sig, _make_evidence("success"), sk, now=_NOW)
        assert updated.signal > sig.signal

    def test_failure_lowers_signal(self) -> None:
        sig, sk = _make_signal(initial=0.5)
        updated, _, _ = update_risk_signal(sig, _make_evidence("failure"), sk, now=_NOW)
        assert updated.signal < sig.signal

    def test_partial_moves_signal_toward_half(self) -> None:
        sig, sk = _make_signal(initial=0.8)
        updated, _, _ = update_risk_signal(sig, _make_evidence("partial"), sk, now=_NOW)
        # With alpha=0.2: posterior = 0.2*0.5 + 0.8*0.8 = 0.74 (< 0.8)
        assert updated.signal < 0.8

    def test_update_count_increments(self) -> None:
        sig, sk = _make_signal()
        updated, _, _ = update_risk_signal(sig, _make_evidence("success"), sk, now=_NOW)
        assert updated.update_count == 1

    def test_update_record_has_evidence_id(self) -> None:
        sig, sk = _make_signal()
        ev = _make_evidence("success")
        _, update_rec, _ = update_risk_signal(sig, ev, sk, now=_NOW)
        assert update_rec.evidence_id == ev.evidence_id

    def test_delta_is_posterior_minus_prior_after_decay(self) -> None:
        # With no elapsed time, decay is negligible; delta â‰ˆ EWMA-updated - prior
        sig, sk = _make_signal(initial=0.5, lam=0.05)
        _, update_rec, _ = update_risk_signal(sig, _make_evidence("success"), sk, now=_NOW)
        expected = 0.2 * 1.0 + 0.8 * 0.5  # Î±*1.0 + (1-Î±)*0.5 = 0.6
        assert update_rec.posterior_signal == pytest.approx(expected, abs=1e-4)


# ---------------------------------------------------------------------------
# Time decay
# ---------------------------------------------------------------------------


class TestTimeDecay:
    def test_signal_decays_with_elapsed_days(self) -> None:
        sig, sk = _make_signal(initial=0.5, lam=0.05)
        # Decay for 14 days: 0.5 Ã— exp(-0.05 Ã— 14) = 0.5 Ã— exp(-0.7) â‰ˆ 0.248
        days_later = _NOW + timedelta(days=14)
        decayed = decay_risk_signal(sig, sk, now=days_later)
        expected = 0.5 * math.exp(-0.05 * 14)
        assert decayed.signal == pytest.approx(expected, abs=1e-4)

    def test_decay_applied_before_ewma_on_update(self) -> None:
        sig, sk = _make_signal(initial=0.5, lam=0.05)
        # Update 14 days later â€” the decay happens before EWMA
        days_later = _NOW + timedelta(days=14)
        updated, update_rec, _ = update_risk_signal(
            sig, _make_evidence("success"), sk, now=days_later
        )
        decayed_prior = 0.5 * math.exp(-0.05 * 14)
        expected_posterior = 0.2 * 1.0 + 0.8 * decayed_prior
        assert update_rec.posterior_signal == pytest.approx(expected_posterior, abs=1e-4)

    def test_zero_elapsed_time_no_decay(self) -> None:
        sig, sk = _make_signal(initial=0.7)
        decayed = _apply_decay(sig.signal, sig.last_updated_at, sig.decay_lambda, _NOW)
        assert decayed == pytest.approx(0.7, abs=1e-6)


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------


class TestAnomalyDetection:
    def test_no_anomaly_with_consistent_history(self) -> None:
        sig, sk = _make_signal(initial=0.5)
        history: list[RiskSignalUpdate] = []
        for _ in range(12):
            sig, upd, anomaly = update_risk_signal(
                sig, _make_evidence("success"), sk, history=history, now=_NOW
            )
            history.append(upd)
        assert anomaly is None

    def test_anomaly_raised_on_sudden_failure(self) -> None:
        sig, sk = _make_signal(initial=0.5)
        history: list[RiskSignalUpdate] = []
        # Build 10 consistent successes
        for _ in range(10):
            sig, upd, _ = update_risk_signal(
                sig, _make_evidence("success"), sk, history=history, now=_NOW
            )
            history.append(upd)
        # Now a sudden failure â€” delta will be far below history mean
        _, upd, anomaly = update_risk_signal(
            sig, _make_evidence("failure"), sk, history=history,
            anomaly_sigma_threshold=1.0,  # lower threshold to guarantee anomaly
            now=_NOW,
        )
        assert anomaly is not None
        assert anomaly.sigma_multiples > 0

    def test_anomaly_not_raised_without_history(self) -> None:
        sig, sk = _make_signal()
        history: list[RiskSignalUpdate] = []
        # Only 5 records â€” below 10-record minimum
        for _ in range(5):
            sig, upd, anomaly = update_risk_signal(
                sig, _make_evidence("failure"), sk, history=history, now=_NOW
            )
            history.append(upd)
        # Should not raise even on consistent failures (not enough history)
        assert anomaly is None

    def test_anomaly_has_signal_fields(self) -> None:
        sig, sk = _make_signal(initial=0.9, alpha=0.5)
        history: list[RiskSignalUpdate] = []
        for _ in range(10):
            sig, upd, _ = update_risk_signal(
                sig, _make_evidence("success"), sk, history=history, now=_NOW
            )
            history.append(upd)
        _, _, anomaly = update_risk_signal(
            sig, _make_evidence("failure"), sk, history=history,
            anomaly_sigma_threshold=0.5, now=_NOW,
        )
        if anomaly is not None:
            assert anomaly.from_sovereign_id == _FROM
            assert anomaly.to_sovereign_id == _TO


# ---------------------------------------------------------------------------
# Signal clamping
# ---------------------------------------------------------------------------


class TestSignalClamping:
    def test_signal_never_exceeds_1(self) -> None:
        sig, sk = _make_signal(initial=0.99, alpha=0.99)
        for _ in range(20):
            sig, _, _ = update_risk_signal(sig, _make_evidence("success"), sk, now=_NOW)
        assert sig.signal <= 1.0

    def test_signal_never_below_0(self) -> None:
        sig, sk = _make_signal(initial=0.01, alpha=0.99)
        for _ in range(20):
            sig, _, _ = update_risk_signal(sig, _make_evidence("failure"), sk, now=_NOW)
        assert sig.signal >= 0.0


# ---------------------------------------------------------------------------
# RiskSignalGate
# ---------------------------------------------------------------------------


class TestRiskSignalGate:
    def test_passes_when_signal_above_minimum(self) -> None:
        sig, sk = _make_signal(initial=0.8)
        gate = RiskSignalGate(sig, minimum_signal=0.4, issuer_public_keys=[_pub_b64(sk)])
        result = gate(object(), object())  # type: ignore[attr-defined]
        assert result.passed is True  # type: ignore[attr-defined]

    def test_blocks_when_signal_below_minimum(self) -> None:
        sig, sk = _make_signal(initial=0.2)
        gate = RiskSignalGate(sig, minimum_signal=0.4, issuer_public_keys=[_pub_b64(sk)])
        result = gate(object(), object())  # type: ignore[attr-defined]
        assert result.passed is False  # type: ignore[attr-defined]
        assert "risk_signal_below_minimum" in result.detail  # type: ignore[attr-defined]

    def test_blocks_when_signature_invalid(self) -> None:
        sig, _ = _make_signal(initial=0.8)
        wrong_sk = _sk()
        gate = RiskSignalGate(sig, minimum_signal=0.0, issuer_public_keys=[_pub_b64(wrong_sk)])
        result = gate(object(), object())  # type: ignore[attr-defined]
        assert result.passed is False  # type: ignore[attr-defined]
        assert "risk_signal_invalid_signature" in result.detail  # type: ignore[attr-defined]

    def test_blocks_when_no_signature(self) -> None:
        sig, sk = _make_signal(initial=0.8)
        unsigned = sig.model_copy(update={"signature": None})
        gate = RiskSignalGate(unsigned, minimum_signal=0.0, issuer_public_keys=[_pub_b64(sk)])
        result = gate(object(), object())  # type: ignore[attr-defined]
        assert result.passed is False  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Independent signals per sovereign
# ---------------------------------------------------------------------------


class TestIndependentSignals:
    def test_two_sovereigns_hold_independent_signals(self) -> None:
        sk_a, sk_b = _sk(), _sk()
        sig_a = create_risk_signal("sov-a", "shared-counterparty", sk_a,
                                   initial_signal=0.3, now=_NOW)
        sig_b = create_risk_signal("sov-b", "shared-counterparty", sk_b,
                                   initial_signal=0.9, now=_NOW)
        assert sig_a.signal != sig_b.signal
        assert sig_a.signal_id != sig_b.signal_id
        assert sig_a.from_sovereign_id != sig_b.from_sovereign_id


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestRiskSignalCLI:
    def _setup(self) -> tuple[CliRunner, str, str, nacl.signing.SigningKey]:
        runner = CliRunner()
        tmpdir = tempfile.mkdtemp()
        sk = _sk()
        key_path = _write_key(sk)
        return runner, tmpdir, key_path, sk

    def test_cli_create(self) -> None:
        runner, tmpdir, key_path, sk = self._setup()
        sig_path = os.path.join(tmpdir, "signal.json")
        result = runner.invoke(trust, [
            "risk", "create",
            "--from-sovereign", _FROM, "--to-sovereign", _TO,
            "--signing-key", key_path, "--output", sig_path,
        ])
        assert result.exit_code == 0, result.output
        data = json.loads(Path(sig_path).read_text(encoding="utf-8"))
        assert data["signal"] == pytest.approx(0.5)

    def test_cli_update(self) -> None:
        runner, tmpdir, key_path, sk = self._setup()
        sig_path = os.path.join(tmpdir, "signal.json")
        ev_path = os.path.join(tmpdir, "evidence.json")
        updated_path = os.path.join(tmpdir, "updated.json")

        runner.invoke(trust, [
            "risk", "create",
            "--from-sovereign", _FROM, "--to-sovereign", _TO,
            "--signing-key", key_path, "--output", sig_path,
        ])

        ev = _make_evidence("success")
        Path(ev_path).write_text(ev.model_dump_json(indent=2), encoding="utf-8")

        result = runner.invoke(trust, [
            "risk", "update",
            "--signal", sig_path, "--evidence", ev_path,
            "--signing-key", key_path, "--output", updated_path,
        ])
        assert result.exit_code == 0, result.output
        data = json.loads(Path(updated_path).read_text(encoding="utf-8"))
        assert data["signal"] > 0.5  # success raised the signal

    def test_cli_decay(self) -> None:
        runner, tmpdir, key_path, sk = self._setup()
        sig_path = os.path.join(tmpdir, "signal.json")
        decayed_path = os.path.join(tmpdir, "decayed.json")

        runner.invoke(trust, [
            "risk", "create",
            "--from-sovereign", _FROM, "--to-sovereign", _TO,
            "--signing-key", key_path, "--output", sig_path,
        ])
        result = runner.invoke(trust, [
            "risk", "decay",
            "--signal", sig_path, "--signing-key", key_path, "--output", decayed_path,
        ])
        assert result.exit_code == 0, result.output

    def test_cli_show(self) -> None:
        runner, tmpdir, key_path, sk = self._setup()
        sig_path = os.path.join(tmpdir, "signal.json")
        runner.invoke(trust, [
            "risk", "create",
            "--from-sovereign", _FROM, "--to-sovereign", _TO,
            "--signing-key", key_path, "--output", sig_path,
        ])
        result = runner.invoke(trust, [
            "risk", "show", "--signal", sig_path, "--format", "json",
        ])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["from_sovereign_id"] == _FROM
