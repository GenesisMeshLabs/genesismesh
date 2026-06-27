"""Tamarin Prover formal verification tests.

Runs tamarin-prover on ops/tamarin/gm_protocol.spthy and asserts all
lemmas are proved.  Skips gracefully when tamarin-prover is not installed.

The model captures five core security properties of the GenesisMesh protocol:
1. authorization_requires_agreement
2. execution_requires_authorization
3. agreement_has_two_signers
4. delegation_requires_agreement
5. execution_traceability
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


TAMARIN_SPTHY = Path(__file__).parents[2] / "ops" / "tamarin" / "gm_protocol.spthy"

tamarin_available = shutil.which("tamarin-prover") is not None


@pytest.mark.skipif(not tamarin_available, reason="tamarin-prover not installed")
def test_tamarin_model_proves_all_lemmas() -> None:
    """Run tamarin-prover --prove and assert exit code 0 (all lemmas verified)."""
    result = subprocess.run(
        ["tamarin-prover", "--prove", str(TAMARIN_SPTHY)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, (
        f"tamarin-prover failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "verified" in result.stdout.lower(), (
        f"Expected 'verified' in tamarin output.\nstdout:\n{result.stdout}"
    )


def test_tamarin_model_file_exists() -> None:
    """The Tamarin model file must exist (even without tamarin-prover installed)."""
    assert TAMARIN_SPTHY.exists(), f"Missing Tamarin model: {TAMARIN_SPTHY}"


def test_tamarin_model_is_readable() -> None:
    """The model file must be non-empty and contain expected lemma names."""
    content = TAMARIN_SPTHY.read_text(encoding="utf-8")
    assert "theory GenesisMesh" in content
    assert "lemma authorization_requires_agreement" in content
    assert "lemma execution_requires_authorization" in content
    assert "lemma agreement_has_two_signers" in content
    assert "lemma delegation_requires_agreement" in content
    assert "lemma execution_traceability" in content


def test_tamarin_model_has_five_lemmas() -> None:
    """The model must contain exactly five lemmas."""
    content = TAMARIN_SPTHY.read_text(encoding="utf-8")
    lemma_count = content.count("lemma ")
    assert lemma_count == 5, f"Expected 5 lemmas, found {lemma_count}"
