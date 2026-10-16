"""GM_E2E_REQUIRED=1 turns the skips of live tests into failures (quality gate)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from .e2e_support import skip_unless_required

ROOT = Path(__file__).resolve().parents[2]


def test_skips_when_not_required(monkeypatch):
    monkeypatch.delenv("GM_E2E_REQUIRED", raising=False)
    with pytest.raises(pytest.skip.Exception, match="needs nginx"):
        skip_unless_required("needs nginx")


def test_fails_when_required(monkeypatch):
    monkeypatch.setenv("GM_E2E_REQUIRED", "1")
    with pytest.raises(pytest.fail.Exception, match="needs nginx.*GM_E2E_REQUIRED=1"):
        skip_unless_required("needs nginx")


def _postgres_tests(required: bool) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("GENESIS_MESH_TEST_DATABASE_URL", "GM_E2E_REQUIRED")}
    if required:
        env["GM_E2E_REQUIRED"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "genesis_mesh/tests/test_db_migration.py", "-m", "postgres",
         "-q", "-p", "no:cacheprovider", "-rs"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )


def test_postgres_tests_without_a_database_fail_when_required():
    """The CI PostgreSQL job sets GM_E2E_REQUIRED=1: losing the database URL fails it."""
    skipped = _postgres_tests(required=False)
    assert skipped.returncode == 0 and "skipped" in skipped.stdout, skipped.stdout
    failed = _postgres_tests(required=True)
    assert failed.returncode == 1, failed.stdout
    assert "needs GENESIS_MESH_TEST_DATABASE_URL" in failed.stdout and "GM_E2E_REQUIRED=1" in failed.stdout
