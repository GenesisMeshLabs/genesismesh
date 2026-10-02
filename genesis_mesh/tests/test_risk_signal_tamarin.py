"""Tamarin Prover formal verification tests for PeerRiskSignal.

Runs tamarin-prover on ops/tamarin/risk_signal/peer_risk_signal.spthy, a model
of genesis_mesh/trust/risk_signal.py:update_risk_signal, and asserts that every
lemma is verified and the model is wellformed. The proof tests skip when
tamarin-prover is not installed; the Formal verification CI workflow installs
it and runs them.

Lemmas (revised v0.61.1):
  1. signal_bounded                  — a signal only holds a lattice value
  2. anomaly_requires_local_outlier  — an anomaly comes from the owner's own update on an outlier
  3. anomaly_requires_history        — an anomaly requires enough prior updates
  4. detection_is_synchronous        — with enough history an outlier raises the anomaly in the same update
  5. no_single_source_cascade        — anomalies at two sovereigns each come from evidence each processed itself
  6. anomaly_reachable               — sanity: the lemmas above are not vacuous
  7. cold_outlier_reachable_without_anomaly — an outlier with short history raises nothing
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


TAMARIN_SPTHY = (
    Path(__file__).parents[2] / "ops" / "tamarin" / "risk_signal" / "peer_risk_signal.spthy"
)

LEMMAS = (
    "signal_bounded",
    "anomaly_requires_local_outlier",
    "anomaly_requires_history",
    "detection_is_synchronous",
    "no_single_source_cascade",
    "anomaly_reachable",
    "cold_outlier_reachable_without_anomaly",
)

tamarin_available = shutil.which("tamarin-prover") is not None


def test_tamarin_risk_signal_model_file_exists() -> None:
    """The Tamarin theory file must exist regardless of whether tamarin is installed."""
    assert TAMARIN_SPTHY.exists(), f"Missing Tamarin model: {TAMARIN_SPTHY}"


def test_tamarin_risk_signal_model_declares_expected_lemmas() -> None:
    """The model declares exactly the expected lemmas, and no longer claims liveness."""
    content = TAMARIN_SPTHY.read_text(encoding="utf-8")
    assert "theory PeerRiskSignal" in content
    declared = [line.split()[1].rstrip(":") for line in content.splitlines() if line.startswith("lemma ")]
    assert declared == list(LEMMAS)
    assert "anomaly_detection_responsive" not in declared


def test_tamarin_risk_signal_model_has_required_rules() -> None:
    """The model covers creation, normal updates and both outlier cases."""
    content = TAMARIN_SPTHY.read_text(encoding="utf-8")
    for rule in ("InitSignal", "UpdateSignal_Normal", "UpdateSignal_Normal_Warms",
                 "UpdateSignal_Outlier_Cold", "UpdateSignal_Outlier_Warm"):
        assert f"rule {rule}:" in content, rule


@pytest.mark.skipif(not tamarin_available, reason="tamarin-prover not installed")
def test_tamarin_risk_signal_proves_all_lemmas() -> None:
    """Every lemma is verified; none falsified or undecided; the model is wellformed."""
    result = subprocess.run(
        ["tamarin-prover", "--prove", str(TAMARIN_SPTHY)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"tamarin-prover failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    out = result.stdout
    assert "wellformedness check failed" not in out.lower(), out
    assert "falsified" not in out.lower(), out
    assert "analysis incomplete" not in out.lower(), out
    for lemma in LEMMAS:
        assert any(line.strip().startswith(f"{lemma} (") and "verified" in line
                   for line in out.splitlines()), f"{lemma} not verified:\n{out}"
