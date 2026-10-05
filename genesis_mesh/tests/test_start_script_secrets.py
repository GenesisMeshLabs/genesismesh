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


NODE_STUB = """#!/bin/bash
printf '%s\\n' "$@" > "$STUB_OUT"
exit 0
"""


def test_node_invite_token_reaches_the_node_in_a_private_file(tmp_path):
    """v1.1: the token is not on the node's command line, where ps shows it."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "python"
    stub.write_text(NODE_STUB)
    stub.chmod(0o755)
    stub_out = tmp_path / "node_args.txt"
    genesis_file = tmp_path / "genesis.signed.json"
    genesis_file.write_text("{}")

    env = os.environ.copy()
    env.update(
        {
            "SERVICE_ROLE": "node",
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "STUB_OUT": str(stub_out),
            "GENESIS_FILE": str(genesis_file),
            "INVITE_TOKEN": "tok-secret-123",
        }
    )
    result = subprocess.run(
        ["bash", str(START_SH)], env=env, cwd=tmp_path, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"start.sh failed: {result.stdout}\n{result.stderr}"
    args = stub_out.read_text().splitlines()
    assert "tok-secret-123" not in args
    assert "--invite-token" not in args
    token_file = Path(args[args.index("--invite-token-file") + 1])
    try:
        assert token_file.read_text() == "tok-secret-123"
        assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(token_file.parent.stat().st_mode) == 0o700
    finally:
        shutil.rmtree(token_file.parent, ignore_errors=True)


def test_files_the_na_creates_are_group_writable(tmp_path):
    """v1.1: umask 0002, so another user ID in group 0 can take over the volume."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "gunicorn"
    stub.write_text("#!/bin/bash\ntouch \"$PROBE\"\nexit 0\n")
    stub.chmod(0o755)
    genesis_file = tmp_path / "genesis.signed.json"
    genesis_file.write_text("{}")
    key_file = tmp_path / "na.key"
    key_file.write_text("key")
    probe = tmp_path / "created-by-the-na"

    env = os.environ.copy()
    env.update(
        {
            "SERVICE_ROLE": "na",
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "GENESIS_FILE": str(genesis_file),
            "NA_PRIVATE_KEY_FILE": str(key_file),
            "DB_PATH": str(tmp_path / "na.db"),
            "PROBE": str(probe),
        }
    )
    result = subprocess.run(
        ["bash", str(START_SH)], env=env, cwd=tmp_path, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"start.sh failed: {result.stdout}\n{result.stderr}"
    assert stat.S_IMODE(probe.stat().st_mode) == 0o664
    # SQLite would create the database 0644; start.sh creates it first.
    assert stat.S_IMODE((tmp_path / "na.db").stat().st_mode) == 0o664
