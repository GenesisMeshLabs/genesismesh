"""Regression tests for F-17: env-injected NA secrets must not land at predictable /tmp paths.

Runs the real start.sh (na role) with GENESIS_JSON / NA_PRIVATE_KEY injected via
environment and gunicorn replaced by a stub that records the resolved
GENESIS_FILE / NA_PRIVATE_KEY_FILE paths, then checks where and how the
secrets were materialized.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
START_SH = REPO_ROOT / "start.sh"

GUNICORN_STUB = """#!/bin/bash
printf 'GENESIS_FILE=%s\\n' "$GENESIS_FILE" > "$STUB_OUT"
printf 'NA_PRIVATE_KEY_FILE=%s\\n' "$NA_PRIVATE_KEY_FILE" >> "$STUB_OUT"
exit 0
"""

pytestmark = pytest.mark.skipif(
    sys.platform == "win32"
    or shutil.which("bash") is None
    or shutil.which("mktemp") is None,
    reason="requires a POSIX environment: start.sh is a Linux deployment script, "
    "and the assertions check POSIX file modes that Windows does not implement "
    "(plus bash needs POSIX paths, not C:\\... ones)",
)


def _run_start_sh(tmp_path: Path) -> dict[str, str]:
    """Run start.sh as the NA role with env-injected secrets; return resolved paths."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "gunicorn"
    stub.write_text(GUNICORN_STUB)
    stub.chmod(0o755)
    stub_out = tmp_path / "stub_env.txt"

    env = os.environ.copy()
    env.update(
        {
            "SERVICE_ROLE": "na",
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "STUB_OUT": str(stub_out),
            "GENESIS_JSON": '{"fake": "genesis"}',
            "NA_PRIVATE_KEY": "fake-private-key-material",
            # Point defaults at nonexistent files so both env-injection branches run.
            "GENESIS_FILE": str(tmp_path / "no-such-genesis.json"),
            "NA_PRIVATE_KEY_FILE": str(tmp_path / "no-such-na.key"),
        }
    )
    result = subprocess.run(
        ["bash", str(START_SH)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"start.sh failed: {result.stdout}\n{result.stderr}"
    resolved = dict(
        line.split("=", 1) for line in stub_out.read_text().splitlines() if "=" in line
    )
    return resolved


def test_env_injected_secrets_avoid_predictable_tmp_paths(tmp_path):
    """F-17: the fixed /tmp/na.key and /tmp/genesis.signed.json paths are gone."""
    resolved = _run_start_sh(tmp_path)
    assert resolved["GENESIS_FILE"] != "/tmp/genesis.signed.json"
    assert resolved["NA_PRIVATE_KEY_FILE"] != "/tmp/na.key"


def test_env_injected_secrets_have_owner_only_permissions(tmp_path):
    """F-17: secrets are 0600 inside a 0700 directory, and contents round-trip."""
    resolved = _run_start_sh(tmp_path)
    genesis = Path(resolved["GENESIS_FILE"])
    key = Path(resolved["NA_PRIVATE_KEY_FILE"])

    assert genesis.read_text() == '{"fake": "genesis"}'
    assert key.read_text() == "fake-private-key-material"

    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert stat.S_IMODE(genesis.stat().st_mode) == 0o600
    for parent in {genesis.parent, key.parent}:
        assert stat.S_IMODE(parent.stat().st_mode) == 0o700

    # Both land in the same freshly created secrets dir.
    assert genesis.parent == key.parent


def test_mounted_files_bypass_env_injection(tmp_path):
    """When real files are mounted, start.sh must leave the given paths untouched."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "gunicorn"
    stub.write_text(GUNICORN_STUB)
    stub.chmod(0o755)
    stub_out = tmp_path / "stub_env.txt"

    genesis_file = tmp_path / "genesis.signed.json"
    genesis_file.write_text('{"mounted": true}')
    key_file = tmp_path / "na.key"
    key_file.write_text("mounted-key")

    env = os.environ.copy()
    env.update(
        {
            "SERVICE_ROLE": "na",
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "STUB_OUT": str(stub_out),
            "GENESIS_FILE": str(genesis_file),
            "NA_PRIVATE_KEY_FILE": str(key_file),
            # Env-injected values present but must be ignored: files exist.
            "GENESIS_JSON": '{"fake": "genesis"}',
            "NA_PRIVATE_KEY": "fake-private-key-material",
        }
    )
    result = subprocess.run(
        ["bash", str(START_SH)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"start.sh failed: {result.stdout}\n{result.stderr}"
    resolved = dict(
        line.split("=", 1) for line in stub_out.read_text().splitlines() if "=" in line
    )
    assert resolved["GENESIS_FILE"] == str(genesis_file)
    assert resolved["NA_PRIVATE_KEY_FILE"] == str(key_file)
    assert genesis_file.read_text() == '{"mounted": true}'
    assert key_file.read_text() == "mounted-key"
