"""Tests for CLI join and certificate reuse behavior."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from click.testing import CliRunner

from genesis_mesh.cli.config import load_config
from genesis_mesh.cli.main import cli
from genesis_mesh.crypto import generate_keypair, sign_data

from .cli_ops_helpers import _running_na_from_config


def test_join_without_token_or_certificate_fails_cleanly(tmp_path):
    """First enrollment requires an invite token and does not print a traceback."""
    config_path = tmp_path / "genesis-mesh.toml"
    home = tmp_path / ".genesis-mesh"
    runner = CliRunner()

    init_result = runner.invoke(
        cli,
        [
            "init",
            "--config",
            str(config_path),
            "--home",
            str(home),
            "--force",
        ],
    )
    assert init_result.exit_code == 0, init_result.output

    with _running_na_from_config(config_path, tmp_path / "na.db") as endpoint:
        result = runner.invoke(cli, ["join", "--config", str(config_path), "--na", endpoint])

    assert result.exit_code != 0
    assert "No local certificate found" in result.output
    assert "Run with --token for first enrollment" in result.output
    assert "Traceback" not in result.output

def test_join_distinguishes_expired_local_certificate(tmp_path):
    """An expired local certificate gets a specific re-enrollment message."""
    config_path = tmp_path / "genesis-mesh.toml"
    home = tmp_path / ".genesis-mesh"
    runner = CliRunner()

    init_result = runner.invoke(
        cli,
        [
            "init",
            "--config",
            str(config_path),
            "--home",
            str(home),
            "--force",
        ],
    )
    assert init_result.exit_code == 0, init_result.output

    with _running_na_from_config(config_path, tmp_path / "na.db") as endpoint:
        invite_result = runner.invoke(
            cli,
            [
                "admin",
                "invite",
                "--config",
                str(config_path),
                "--na",
                endpoint,
                "--role",
                "anchor",
            ],
        )
        assert invite_result.exit_code == 0, invite_result.output

        join_result = runner.invoke(
            cli,
            [
                "join",
                "--config",
                str(config_path),
                "--na",
                endpoint,
                "--token",
                invite_result.output.strip(),
            ],
        )
        assert join_result.exit_code == 0, join_result.output

        config = load_config(str(config_path), required=True)
        cert_path = Path(config["paths"]["node_certificate"])
        cert_payload = json.loads(cert_path.read_text(encoding="utf-8"))
        cert_payload["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        cert_path.write_text(json.dumps(cert_payload), encoding="utf-8")

        reuse_result = runner.invoke(cli, ["join", "--config", str(config_path), "--na", endpoint])

        assert reuse_result.exit_code != 0
        assert "expired at" in reuse_result.output
        assert "Run with --token to re-enroll" in reuse_result.output
        assert "No local certificate found" not in reuse_result.output
        assert "Traceback" not in reuse_result.output

def test_join_persistent_existing_cert_does_not_consume_new_token(tmp_path, monkeypatch):
    """Persistent reuse must not burn a new invite token supplied by mistake."""
    config_path = tmp_path / "genesis-mesh.toml"
    home = tmp_path / ".genesis-mesh"
    runner = CliRunner()

    init_result = runner.invoke(
        cli,
        [
            "init",
            "--config",
            str(config_path),
            "--home",
            str(home),
            "--force",
        ],
    )
    assert init_result.exit_code == 0, init_result.output

    async def _fake_runtime_forever(runtime):
        return None

    monkeypatch.setattr("genesis_mesh.cli.ops._run_runtime_forever", _fake_runtime_forever)

    with _running_na_from_config(config_path, tmp_path / "na.db") as endpoint:
        first_invite = runner.invoke(
            cli,
            [
                "admin",
                "invite",
                "--config",
                str(config_path),
                "--na",
                endpoint,
                "--role",
                "anchor",
            ],
        )
        assert first_invite.exit_code == 0, first_invite.output

        first_join = runner.invoke(
            cli,
            [
                "join",
                "--config",
                str(config_path),
                "--na",
                endpoint,
                "--token",
                first_invite.output.strip(),
            ],
        )
        assert first_join.exit_code == 0, first_join.output

        second_invite = runner.invoke(
            cli,
            [
                "admin",
                "invite",
                "--config",
                str(config_path),
                "--na",
                endpoint,
                "--role",
                "client",
            ],
        )
        assert second_invite.exit_code == 0, second_invite.output
        spare_token = second_invite.output.strip()

        persistent_reuse = runner.invoke(
            cli,
            [
                "join",
                "--config",
                str(config_path),
                "--na",
                endpoint,
                "--token",
                spare_token,
                "--persistent",
            ],
        )
        assert persistent_reuse.exit_code == 0, persistent_reuse.output
        assert "Using existing certificate" in persistent_reuse.output

        fresh_node = generate_keypair()
        token_check_payload = {
            "node_public_key": fresh_node.public_key_b64,
            "invite_token": spare_token,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "nonce": "token-check",
        }
        canonical = json.dumps(
            token_check_payload,
            sort_keys=True,
            separators=(",", ":"),
        )
        token_check_payload["signature"] = sign_data(
            canonical.encode("utf-8"),
            fresh_node.private_key,
        )
        token_check = requests.post(
            f"{endpoint}/join",
            json=token_check_payload,
            timeout=10,
        )
        assert token_check.status_code == 201

def test_join_with_revoked_local_certificate_fails_cleanly(tmp_path):
    """A revoked local certificate is not silently reused by the join command."""
    config_path = tmp_path / "genesis-mesh.toml"
    home = tmp_path / ".genesis-mesh"
    runner = CliRunner()

    init_result = runner.invoke(
        cli,
        [
            "init",
            "--config",
            str(config_path),
            "--home",
            str(home),
            "--force",
        ],
    )
    assert init_result.exit_code == 0, init_result.output

    with _running_na_from_config(config_path, tmp_path / "na.db") as endpoint:
        invite_result = runner.invoke(
            cli,
            [
                "admin",
                "invite",
                "--config",
                str(config_path),
                "--na",
                endpoint,
                "--role",
                "anchor",
            ],
        )
        assert invite_result.exit_code == 0, invite_result.output

        join_result = runner.invoke(
            cli,
            [
                "join",
                "--config",
                str(config_path),
                "--na",
                endpoint,
                "--token",
                invite_result.output.strip(),
            ],
        )
        assert join_result.exit_code == 0, join_result.output

        config = load_config(str(config_path), required=True)
        cert_payload = json.loads(
            Path(config["paths"]["node_certificate"]).read_text(encoding="utf-8")
        )
        revoke_result = runner.invoke(
            cli,
            [
                "admin",
                "revoke",
                cert_payload["cert_id"],
                "--config",
                str(config_path),
                "--na",
                endpoint,
                "--reason",
                "key_compromise",
            ],
        )
        assert revoke_result.exit_code == 0, revoke_result.output

        reuse_result = runner.invoke(cli, ["join", "--config", str(config_path), "--na", endpoint])

        assert reuse_result.exit_code != 0
        assert "Existing local certificate was rejected by the Network Authority" in reuse_result.output
        assert "Run with --token to re-enroll" in reuse_result.output
        assert "Joined USG" not in reuse_result.output
        assert "Traceback" not in reuse_result.output

def test_join_with_local_cert_missing_from_na_fails_cleanly(tmp_path):
    """A local cert rejected by a wiped NA DB gets an actionable message."""
    config_path = tmp_path / "genesis-mesh.toml"
    home = tmp_path / ".genesis-mesh"
    runner = CliRunner()

    init_result = runner.invoke(
        cli,
        [
            "init",
            "--config",
            str(config_path),
            "--home",
            str(home),
            "--force",
        ],
    )
    assert init_result.exit_code == 0, init_result.output

    first_db = tmp_path / "first-na.db"
    with _running_na_from_config(config_path, first_db) as endpoint:
        invite_result = runner.invoke(
            cli,
            [
                "admin",
                "invite",
                "--config",
                str(config_path),
                "--na",
                endpoint,
                "--role",
                "anchor",
            ],
        )
        assert invite_result.exit_code == 0, invite_result.output
        join_result = runner.invoke(
            cli,
            [
                "join",
                "--config",
                str(config_path),
                "--na",
                endpoint,
                "--token",
                invite_result.output.strip(),
            ],
        )
        assert join_result.exit_code == 0, join_result.output

    with _running_na_from_config(config_path, tmp_path / "fresh-na.db") as endpoint:
        reuse_result = runner.invoke(cli, ["join", "--config", str(config_path), "--na", endpoint])

    assert reuse_result.exit_code != 0
    assert "Existing local certificate was rejected by the Network Authority" in reuse_result.output
    assert "Run with --token to re-enroll" in reuse_result.output
    assert "Traceback" not in reuse_result.output
