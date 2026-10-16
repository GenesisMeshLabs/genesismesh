"""Skipped is not green: live and end-to-end tests fail when CI requires them.

A test that needs an environment (a PostgreSQL database, nginx) skips when it
is missing, so a developer can run the suite anywhere. A CI job that sets up
that environment also sets ``GM_E2E_REQUIRED=1``; a missing piece then fails
the test instead of skipping it, so a broken service container or a renamed
variable cannot turn the job green without running the tests.
"""

from __future__ import annotations

import os
from typing import NoReturn

import pytest

E2E_REQUIRED_ENV = "GM_E2E_REQUIRED"


def e2e_required() -> bool:
    return os.environ.get(E2E_REQUIRED_ENV) == "1"


def skip_unless_required(reason: str) -> NoReturn:
    """Skip with ``reason``, or fail when ``GM_E2E_REQUIRED=1``."""
    if e2e_required():
        pytest.fail(f"{reason} ({E2E_REQUIRED_ENV}=1: this test must run here, not skip)", pytrace=False)
    pytest.skip(reason)
