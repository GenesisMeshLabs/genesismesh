"""Conformance suite integration: loads reference vectors and validates them."""

from __future__ import annotations

import pytest

from conformance.runner import SUITE_RUNNERS, run_suite


@pytest.mark.parametrize("suite_name", list(SUITE_RUNNERS.keys()))
def test_conformance_suite(suite_name: str) -> None:
    passed, total, failures = run_suite(suite_name)
    assert total > 0, f"suite '{suite_name}' has no vectors"
    assert not failures, "\n".join(failures)
    assert passed == total
