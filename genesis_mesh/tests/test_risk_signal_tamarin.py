"""Tamarin Prover formal verification tests for PeerRiskSignal (v0.48).

Runs tamarin-prover on ops/tamarin/risk_signal/peer_risk_signal.spthy and
asserts all three security lemmas are proved.  Skips gracefully when
tamarin-prover is not installed (consistent with v0.31 pattern).

Lemmas:
  1. signal_bounded           — signal value is always in {low, mid, high}
  2. anomaly_detection_responsive — SuddenDrop is always followed by Anomaly
  3. no_single_source_cascade — cascade requires independent per-sovereign drops
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


TAMARIN_SPTHY = (
    Path(__file__).parents[2] / "ops" / "tamarin" / "risk_signal" / "peer_risk_signal.spthy"
)

tamarin_available = shutil.which("tamarin-prover") is not None


def test_tamarin_risk_signal_model_file_exists() -> None:
    """The Tamarin theory file must exist regardless of whether tamarin is installed."""
    assert TAMARIN_SPTHY.exists(), f"Missing Tamarin model: {TAMARIN_SPTHY}"


def test_tamarin_risk_signal_model_is_readable() -> None:
    """Model file must be non-empty and contain the three expected lemma names."""
    content = TAMARIN_SPTHY.read_text(encoding="utf-8")
    assert "theory PeerRiskSignal" in content
    assert "lemma signal_bounded" in content
    assert "lemma anomaly_detection_responsive" in content
    assert "lemma no_single_source_cascade" in content


def test_tamarin_risk_signal_model_has_three_lemmas() -> None:
    """Model must contain exactly three lemma declarations (lines starting with 'lemma ')."""
    content = TAMARIN_SPTHY.read_text(encoding="utf-8")
    count = sum(1 for line in content.splitlines() if line.startswith("lemma "))
    assert count == 3, f"Expected 3 lemmas, found {count}"


def test_tamarin_risk_signal_model_has_required_rules() -> None:
    """Model must contain the three core protocol rules."""
    content = TAMARIN_SPTHY.read_text(encoding="utf-8")
    assert "rule InitSignal" in content
    assert "rule UpdateSignal_High" in content
    assert "rule EmitAnomaly" in content


@pytest.mark.skipif(not tamarin_available, reason="tamarin-prover not installed")
def test_tamarin_risk_signal_bounded() -> None:
    """Verify Lemma 1 (signal_bounded) via tamarin-prover."""
    result = subprocess.run(
        ["tamarin-prover", "--prove=signal_bounded", str(TAMARIN_SPTHY)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"Lemma signal_bounded failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "verified" in result.stdout.lower()


@pytest.mark.skipif(not tamarin_available, reason="tamarin-prover not installed")
def test_tamarin_anomaly_suppression() -> None:
    """Verify Lemma 2 (anomaly_detection_responsive) via tamarin-prover."""
    result = subprocess.run(
        ["tamarin-prover", "--prove=anomaly_detection_responsive", str(TAMARIN_SPTHY)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"Lemma anomaly_detection_responsive failed.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "verified" in result.stdout.lower()


@pytest.mark.skipif(not tamarin_available, reason="tamarin-prover not installed")
def test_tamarin_cascade_impossibility() -> None:
    """Verify Lemma 3 (no_single_source_cascade) via tamarin-prover."""
    result = subprocess.run(
        ["tamarin-prover", "--prove=no_single_source_cascade", str(TAMARIN_SPTHY)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"Lemma no_single_source_cascade failed.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "verified" in result.stdout.lower()
