"""Tests for Adversarial Seed Isolation (v0.39).

Covers:
- assess_seed_isolation(): insufficient history returns isolated=False with scores=0.0
- CFS (Credit Farming Score): early-better-than-late history
- VDS (Volatility Discontinuity Score): abrupt variance change
- SFS (Streak Fragility Score): implausibly long success streak
- seed_probability weighted sum of component scores
- isolation threshold: strictly greater than (not >=)
- Configurable weights and threshold
- SeedIsolationGate: blocks when isolated, passes when clean, passes on insufficient history
- Two sovereigns hold independent assessments for same counterparty
- CLI: assess-seed exits 0 / 1, JSON format
"""

from __future__ import annotations

import json
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from genesis_mesh.cli.decision_ops import trust
from genesis_mesh.models.risk_signal import PeerRiskSignal, RiskSignalUpdate
from genesis_mesh.trust.risk_signal import (
    SeedIsolationGate,
    _compute_cfs,
    _compute_sfs,
    _compute_vds,
    assess_seed_isolation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
_FROM = "sovereign-a"
_TO = "counterparty-b"


def _signal(from_sov: str = _FROM, to_sov: str = _TO) -> PeerRiskSignal:
    return PeerRiskSignal(
        from_sovereign_id=from_sov,
        to_sovereign_id=to_sov,
        signal=0.5,
    )


def _update(signal_id: str, delta: float) -> RiskSignalUpdate:
    return RiskSignalUpdate(
        signal_id=signal_id,
        evidence_id=str(uuid.uuid4()),
        prior_signal=0.5,
        posterior_signal=max(0.0, min(1.0, 0.5 + delta)),
        delta=delta,
        updated_by_sovereign_id=_FROM,
        updated_at=_NOW,
    )


def _history(signal_id: str, deltas: list[float]) -> list[RiskSignalUpdate]:
    return [_update(signal_id, d) for d in deltas]


def _farming_history(signal_id: str, n: int = 100) -> list[RiskSignalUpdate]:
    """Classic credit-farming attack: uniform positive early, erratic/negative late."""
    first = [+0.5] * int(n * 0.6)
    # late section: alternating +0.5, -0.5 (zero mean, high variance)
    tail_len = n - len(first)
    last = [+0.5 if i % 2 == 0 else -0.5 for i in range(tail_len)]
    return _history(signal_id, first + last)


def _clean_history(signal_id: str, n: int = 100) -> list[RiskSignalUpdate]:
    """Normal behavior: alternating small +/- deltas, uniform variance."""
    deltas = [+0.1 if i % 2 == 0 else -0.05 for i in range(n)]
    return _history(signal_id, deltas)


# ---------------------------------------------------------------------------
# Insufficient history
# ---------------------------------------------------------------------------


def test_insufficient_history_not_isolated() -> None:
    sig = _signal()
    hist = _history(sig.signal_id, [+0.1] * 19)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.isolated is False


def test_insufficient_history_scores_zero() -> None:
    sig = _signal()
    hist = _history(sig.signal_id, [+0.1] * 10)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.credit_farming_score == 0.0
    assert report.volatility_discontinuity_score == 0.0
    assert report.streak_fragility_score == 0.0


def test_insufficient_history_seed_probability_zero() -> None:
    sig = _signal()
    hist = _history(sig.signal_id, [+0.1] * 5)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.seed_probability == 0.0


def test_empty_history_not_isolated() -> None:
    sig = _signal()
    report = assess_seed_isolation(sig, [], now=_NOW)
    assert report.isolated is False
    assert report.history_length == 0


def test_custom_min_history_respected() -> None:
    sig = _signal()
    hist = _history(sig.signal_id, [+0.5] * 6)
    report = assess_seed_isolation(sig, hist, min_history_for_assessment=5, now=_NOW)
    # 6 >= 5, so assessment should run (scores may be non-zero)
    assert report.history_length == 6


# ---------------------------------------------------------------------------
# Report structure
# ---------------------------------------------------------------------------


def test_report_signal_id_matches() -> None:
    sig = _signal()
    hist = _farming_history(sig.signal_id)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.signal_id == sig.signal_id


def test_report_from_to_sovereign() -> None:
    sig = _signal("sov-x", "sov-y")
    hist = _history(sig.signal_id, [+0.1] * 20)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.from_sovereign_id == "sov-x"
    assert report.to_sovereign_id == "sov-y"


def test_report_history_length() -> None:
    sig = _signal()
    hist = _farming_history(sig.signal_id, n=80)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.history_length == 80


def test_report_threshold_used() -> None:
    sig = _signal()
    hist = _farming_history(sig.signal_id)
    report = assess_seed_isolation(sig, hist, seed_threshold=0.3, now=_NOW)
    assert report.threshold_used == 0.3


def test_report_assessed_at_set() -> None:
    sig = _signal()
    hist = _farming_history(sig.signal_id)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.assessed_at == _NOW


# ---------------------------------------------------------------------------
# CFS computation
# ---------------------------------------------------------------------------


def test_cfs_positive_when_early_better() -> None:
    # Early all +0.3, late all -0.3 → CFS should be > 0
    sig = _signal()
    deltas = [+0.3] * 40 + [0.0] * 40 + [-0.3] * 20
    hist = _history(sig.signal_id, deltas)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.credit_farming_score > 0.0


def test_cfs_zero_when_late_better() -> None:
    # Late is better than early → CFS is clamped to 0
    sig = _signal()
    deltas = [-0.1] * 20 + [0.0] * 60 + [+0.1] * 20
    hist = _history(sig.signal_id, deltas)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.credit_farming_score == 0.0


def test_cfs_early_late_means_recorded() -> None:
    sig = _signal()
    deltas = [+0.4] * 20 + [0.0] * 60 + [-0.4] * 20
    hist = _history(sig.signal_id, deltas)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    # early window = first 20 (20% of 100) → mean = +0.4
    # late window = last 20 → mean = -0.4
    assert abs(report.early_window_mean_delta - 0.4) < 1e-9
    assert abs(report.late_window_mean_delta - (-0.4)) < 1e-9


def test_cfs_max_one() -> None:
    cfs, _, _ = _compute_cfs([+1.0] * 10 + [-1.0] * 10)
    assert cfs <= 1.0


# ---------------------------------------------------------------------------
# VDS computation
# ---------------------------------------------------------------------------


def test_vds_nonzero_on_variance_switch() -> None:
    # First 50: all +0.5 (zero variance) → second 50: alternating (high variance)
    sig = _signal()
    deltas = [+0.5] * 50 + [+0.5 if i % 2 == 0 else -0.5 for i in range(50)]
    hist = _history(sig.signal_id, deltas)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.volatility_discontinuity_score > 0.1


def test_vds_low_on_uniform_variance() -> None:
    # Alternating consistently throughout → uniform variance, VDS near zero
    sig = _signal()
    deltas = [+0.2 if i % 2 == 0 else -0.2 for i in range(100)]
    hist = _history(sig.signal_id, deltas)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.volatility_discontinuity_score < 0.1


def test_vds_midpoint_index_recorded() -> None:
    sig = _signal()
    hist = _farming_history(sig.signal_id)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    # Farming history has a variance switch at the midpoint
    assert report.discontinuity_midpoint_index is not None
    assert 0 < report.discontinuity_midpoint_index < len(hist)


def test_vds_midpoint_none_on_insufficient() -> None:
    sig = _signal()
    hist = _history(sig.signal_id, [+0.1] * 5)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.discontinuity_midpoint_index is None


def test_vds_clamped_to_one() -> None:
    # Extreme alternating variance in second half — VDS must not exceed 1.0
    raw_vds, _ = _compute_vds([0.0] * 50 + [2.0, -2.0] * 25)
    assert raw_vds <= 1.0


# ---------------------------------------------------------------------------
# SFS computation
# ---------------------------------------------------------------------------


def test_sfs_high_on_long_streak() -> None:
    sig = _signal()
    # 80 consecutive positives then some negatives
    deltas = [+0.3] * 80 + [-0.3] * 20
    hist = _history(sig.signal_id, deltas)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.streak_fragility_score > 0.3


def test_sfs_low_on_alternating() -> None:
    sig = _signal()
    # Alternating: max streak = 1
    deltas = [+0.1 if i % 2 == 0 else -0.1 for i in range(100)]
    hist = _history(sig.signal_id, deltas)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.streak_fragility_score < 0.05


def test_sfs_zero_when_all_negative() -> None:
    sig = _signal()
    deltas = [-0.1] * 100
    hist = _history(sig.signal_id, deltas)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.streak_fragility_score == 0.0
    assert report.max_success_streak == 0


def test_max_success_streak_recorded() -> None:
    sig = _signal()
    deltas = [+0.2] * 60 + [-0.1] * 40
    hist = _history(sig.signal_id, deltas)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.max_success_streak == 60


# ---------------------------------------------------------------------------
# Seed probability formula
# ---------------------------------------------------------------------------


def test_seed_probability_is_weighted_sum() -> None:
    sig = _signal()
    hist = _farming_history(sig.signal_id)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    expected = (
        0.4 * report.credit_farming_score
        + 0.3 * report.volatility_discontinuity_score
        + 0.3 * report.streak_fragility_score
    )
    assert abs(report.seed_probability - min(1.0, expected)) < 1e-9


def test_custom_weights_shift_result() -> None:
    sig = _signal()
    hist = _farming_history(sig.signal_id)
    report_default = assess_seed_isolation(sig, hist, now=_NOW)
    # Increase SFS weight, lower CFS weight
    report_custom = assess_seed_isolation(
        sig, hist, cfs_weight=0.1, vds_weight=0.3, sfs_weight=0.6, now=_NOW
    )
    assert report_default.seed_probability != report_custom.seed_probability


# ---------------------------------------------------------------------------
# Isolation threshold
# ---------------------------------------------------------------------------


def test_isolated_true_above_threshold() -> None:
    sig = _signal()
    hist = _farming_history(sig.signal_id)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    # Farming history should produce seed_probability > 0.5
    assert report.isolated is True
    assert report.seed_probability > 0.5


def test_isolated_false_below_threshold() -> None:
    sig = _signal()
    hist = _clean_history(sig.signal_id)
    report = assess_seed_isolation(sig, hist, seed_threshold=0.5, now=_NOW)
    assert report.isolated is False


def test_isolated_strict_greater_than() -> None:
    # Construct history with known exact seed_probability, check strictly >
    sig = _signal()
    hist = _farming_history(sig.signal_id)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    # At exactly seed_probability threshold: not isolated
    report_at = assess_seed_isolation(
        sig, hist, seed_threshold=report.seed_probability, now=_NOW
    )
    assert report_at.isolated is False


def test_configurable_threshold_low() -> None:
    sig = _signal()
    hist = _clean_history(sig.signal_id)
    # With threshold=0.01, even a clean history may be isolated if any score > 0
    report = assess_seed_isolation(sig, hist, seed_threshold=0.0, now=_NOW)
    # seed_probability > 0.0 (clean history has small positive scores)
    # so isolated=True with threshold=0.0
    assert report.isolated is True


def test_configurable_threshold_high() -> None:
    sig = _signal()
    hist = _farming_history(sig.signal_id)
    report = assess_seed_isolation(sig, hist, seed_threshold=0.99, now=_NOW)
    assert report.isolated is False


# ---------------------------------------------------------------------------
# Full adversarial scenario
# ---------------------------------------------------------------------------


def test_credit_farming_attack_isolated() -> None:
    sig = _signal()
    hist = _farming_history(sig.signal_id, n=100)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.isolated is True
    assert report.credit_farming_score > 0.0
    assert report.streak_fragility_score > 0.0


def test_clean_history_not_isolated() -> None:
    sig = _signal()
    hist = _clean_history(sig.signal_id, n=100)
    report = assess_seed_isolation(sig, hist, now=_NOW)
    assert report.isolated is False


def test_two_sovereigns_independent() -> None:
    # Both observe counterparty-b, but with different histories
    sig_a = _signal("sovereign-a", "counterparty-b")
    sig_b = _signal("sovereign-c", "counterparty-b")

    # Sovereign A has seen farming behavior
    hist_a = _farming_history(sig_a.signal_id, n=100)
    # Sovereign C has seen only clean behavior
    hist_b = _clean_history(sig_b.signal_id, n=100)

    report_a = assess_seed_isolation(sig_a, hist_a, now=_NOW)
    report_b = assess_seed_isolation(sig_b, hist_b, now=_NOW)

    assert report_a.isolated is True
    assert report_b.isolated is False


# ---------------------------------------------------------------------------
# SeedIsolationGate
# ---------------------------------------------------------------------------


def test_gate_blocks_when_isolated() -> None:
    sig = _signal()
    hist = _farming_history(sig.signal_id)
    gate = SeedIsolationGate(sig, hist, seed_threshold=0.5)
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is False  # type: ignore[attr-defined]
    assert result.gate_name == "seed_isolation"  # type: ignore[attr-defined]


def test_gate_passes_when_clean() -> None:
    sig = _signal()
    hist = _clean_history(sig.signal_id)
    gate = SeedIsolationGate(sig, hist, seed_threshold=0.5)
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is True  # type: ignore[attr-defined]


def test_gate_passes_on_insufficient_history() -> None:
    sig = _signal()
    hist = _history(sig.signal_id, [+0.1] * 10)
    gate = SeedIsolationGate(sig, hist, seed_threshold=0.5)
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is True  # type: ignore[attr-defined]


def test_gate_name_is_seed_isolation() -> None:
    sig = _signal()
    hist = _farming_history(sig.signal_id)
    gate = SeedIsolationGate(sig, hist)
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.gate_name == "seed_isolation"  # type: ignore[attr-defined]


def test_gate_detail_contains_counterparty() -> None:
    sig = _signal()
    hist = _clean_history(sig.signal_id)
    gate = SeedIsolationGate(sig, hist)
    result = gate(None, None)  # type: ignore[attr-defined]
    assert _TO in result.detail  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# CLI: trust risk assess-seed
# ---------------------------------------------------------------------------


def _write_json(path: Path, obj: object) -> None:
    if hasattr(obj, "model_dump_json"):
        path.write_text(obj.model_dump_json(indent=2), encoding="utf-8")
    else:
        path.write_text(json.dumps(obj), encoding="utf-8")


def test_cli_assess_seed_exit_0_clean() -> None:
    sig = _signal()
    hist = _clean_history(sig.signal_id)
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        sig_path = p / "signal.json"
        _write_json(sig_path, sig)
        hist_paths = []
        for i, upd in enumerate(hist):
            hp = p / f"update_{i:04d}.json"
            _write_json(hp, upd)
            hist_paths.append(str(hp))

        runner = CliRunner()
        args = ["risk", "assess-seed", "--signal", str(sig_path)]
        for h in hist_paths:
            args += ["--history", h]

        result = runner.invoke(trust, args)
        assert result.exit_code == 0
        assert "[OK]" in result.output


def test_cli_assess_seed_exit_1_isolated() -> None:
    sig = _signal()
    hist = _farming_history(sig.signal_id)
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        sig_path = p / "signal.json"
        _write_json(sig_path, sig)
        hist_paths = []
        for i, upd in enumerate(hist):
            hp = p / f"update_{i:04d}.json"
            _write_json(hp, upd)
            hist_paths.append(str(hp))

        runner = CliRunner()
        args = ["risk", "assess-seed", "--signal", str(sig_path)]
        for h in hist_paths:
            args += ["--history", h]

        result = runner.invoke(trust, args)
        assert result.exit_code == 1
        assert "[ISOLATED]" in result.output


def test_cli_assess_seed_json_format() -> None:
    sig = _signal()
    hist = _farming_history(sig.signal_id)
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        sig_path = p / "signal.json"
        _write_json(sig_path, sig)
        hist_paths = []
        for i, upd in enumerate(hist):
            hp = p / f"update_{i:04d}.json"
            _write_json(hp, upd)
            hist_paths.append(str(hp))

        runner = CliRunner()
        args = ["risk", "assess-seed", "--signal", str(sig_path), "--format", "json"]
        for h in hist_paths:
            args += ["--history", h]

        result = runner.invoke(trust, args)
        parsed = json.loads(result.output)
        assert "seed_probability" in parsed
        assert "isolated" in parsed
        assert parsed["isolated"] is True
