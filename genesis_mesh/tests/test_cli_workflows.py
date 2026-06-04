"""Tests for end-to-end CLI operator workflows."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from genesis_mesh.cli.config import load_config
from genesis_mesh.cli.main import cli

from .cli_ops_helpers import _running_na_from_config


def test_admin_invite_and_join_use_single_configured_workflow(tmp_path):
    """The high-level admin and join commands work against a live local NA."""
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
        token = invite_result.output.strip()
        assert token

        join_result = runner.invoke(
            cli,
            [
                "join",
                "--config",
                str(config_path),
                "--na",
                endpoint,
                "--token",
                token,
                "--role",
                "anchor",
            ],
        )
        assert join_result.exit_code == 0, join_result.output
        assert "Joined USG" in join_result.output

        config = load_config(str(config_path), required=True)
        cert_path = Path(config["paths"]["node_certificate"])
        cert_payload = json.loads(cert_path.read_text(encoding="utf-8"))
        assert cert_payload["roles"] == ["role:anchor"]
        assert Path(config["paths"]["policy"]).exists()

        status_result = runner.invoke(cli, ["status", "--config", str(config_path)])
        assert status_result.exit_code == 0, status_result.output
        assert "/healthz: 200" in status_result.output
        assert "db_path" in status_result.output
        assert "active nodes: 1" in status_result.output
        assert "Node:" in status_result.output

        reuse_result = runner.invoke(
            cli,
            [
                "join",
                "--config",
                str(config_path),
                "--na",
                endpoint,
            ],
        )
        assert reuse_result.exit_code == 0, reuse_result.output
        assert "Using existing certificate" in reuse_result.output
        assert "Joined USG as role:anchor" in reuse_result.output

        reuse_status = runner.invoke(cli, ["status", "--config", str(config_path)])
        assert reuse_status.exit_code == 0, reuse_status.output
        assert "active nodes: 1" in reuse_status.output

def test_sovereign_inspect_reads_public_metadata(tmp_path):
    """The CLI can fetch public operator-safe sovereign metadata."""
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
            "--network-name",
            "USG-NB",
            "--force",
        ],
    )
    assert init_result.exit_code == 0, init_result.output

    with _running_na_from_config(config_path, tmp_path / "na.db") as endpoint:
        result = runner.invoke(cli, ["sovereign", "inspect", "--na", endpoint])

    assert result.exit_code == 0, result.output
    assert "Sovereign: USG-NB" in result.output
    assert "public surfaces:" in result.output
    assert "/sovereign.json" not in result.output


def test_federation_command_is_registered():
    """The root CLI exposes the federation bootstrap command family."""
    runner = CliRunner()
    result = runner.invoke(cli, ["federation", "bootstrap", "--help"])

    assert result.exit_code == 0, result.output
    assert "Review another sovereign" in result.output
