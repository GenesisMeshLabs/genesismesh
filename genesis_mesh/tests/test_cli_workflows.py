"""Tests for end-to-end CLI operator workflows."""

from __future__ import annotations

import json
import logging
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


def test_admin_invite_accepts_direct_operator_key_flags(tmp_path):
    """Operators can sign admin commands without creating a temporary TOML file."""
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
    config = load_config(str(config_path), required=True)

    with _running_na_from_config(config_path, tmp_path / "na.db") as endpoint:
        invite_result = runner.invoke(
            cli,
            [
                "admin",
                "invite",
                "--na",
                endpoint,
                "--operator-key",
                config["paths"]["operator_private_key"],
                "--operator-key-id",
                config["operator"]["key_id"],
                "--role",
                "client",
            ],
        )

    assert invite_result.exit_code == 0, invite_result.output
    assert invite_result.output.strip()


def test_na_start_uses_logger_and_werkzeug_runner(tmp_path, monkeypatch, caplog):
    """The local NA dev server avoids Flask's direct stderr banner path."""
    config_path = tmp_path / "genesis-mesh.toml"
    home = tmp_path / ".genesis-mesh"
    runner = CliRunner()
    called: dict[str, object] = {}

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

    def fake_run_simple(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr("genesis_mesh.cli.ops.run_simple", fake_run_simple)
    caplog.set_level(logging.INFO)

    result = runner.invoke(cli, ["na", "start", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    assert called["hostname"] == "127.0.0.1"
    assert called["port"] == 8443
    assert called["use_reloader"] is False
    assert called["use_debugger"] is False
    assert "Starting Flask development server" not in result.output
    assert any(
        record.name == "genesis_mesh.cli.ops"
        and record.getMessage() == "Starting Network Authority"
        and getattr(record, "endpoint") == "http://127.0.0.1:8443"
        for record in caplog.records
    )


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


def test_sovereign_inspect_accepts_endpoint_alias(tmp_path):
    """The public sovereign inspector accepts --endpoint as a --na alias."""
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
        result = runner.invoke(cli, ["sovereign", "inspect", "--endpoint", endpoint])

    assert result.exit_code == 0, result.output
    assert "Sovereign: USG-NB" in result.output


def test_federation_command_is_registered():
    """The root CLI exposes the federation bootstrap command family."""
    runner = CliRunner()
    result = runner.invoke(cli, ["federation", "bootstrap", "--help"])

    assert result.exit_code == 0, result.output
    assert "Review another sovereign" in result.output


def _valid_proof_bundle() -> dict[str, object]:
    return {
        "proof": "remote-sovereign-recognition-revocation",
        "acceptor": {"network_name": "BOS-NA"},
        "issuer": {"network_name": "SAS-NA"},
        "attestation_id": "att-1",
        "treaty_id": "treaty-1",
        "feed_id": "feed-1",
        "feed_sequence": 1,
        "pre_revocation": {"accepted": True, "reason": "accepted"},
        "post_revocation": {
            "accepted": False,
            "reason": "attestation_locally_revoked",
        },
        "trust_path": {
            "from": "BOS-NA",
            "to": "SAS-NA",
            "trusted": True,
            "hop_count": 1,
            "reason": "active_treaty_path",
        },
        "connectome_summary": {
            "sovereign_count": 2,
            "active_edge_count": 1,
            "imported_revocation_count": 1,
            "revoked_trust_material_count": 1,
        },
    }


def test_proof_inspect_validates_redacted_bundle(tmp_path):
    """Operators can validate committed proof bundles without live NA services."""
    bundle_path = tmp_path / "proof-bundle.json"
    bundle_path.write_text(json.dumps(_valid_proof_bundle()), encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(cli, ["proof", "inspect", "--proof-bundle", str(bundle_path)])

    assert result.exit_code == 0, result.output
    assert "Proof bundle: valid" in result.output
    assert "acceptor:    BOS-NA" in result.output
    assert "after:       attestation_locally_revoked" in result.output


def test_proof_inspect_cross_checks_connectome_artifact(tmp_path):
    """Proof inspection can validate the bundle against a committed Connectome artifact."""
    bundle_path = tmp_path / "proof-bundle.json"
    bundle_path.write_text(json.dumps(_valid_proof_bundle()), encoding="utf-8")
    connectome_path = tmp_path / "connectome.json"
    connectome_path.write_text(
        json.dumps(
            {
                "summary": {
                    "sovereign_count": 2,
                    "active_edge_count": 1,
                    "imported_revocation_count": 1,
                    "revoked_trust_material_count": 1,
                },
                "recognition_edges": [
                    {"from": "BOS-NA", "to": "SAS-NA", "treaty_id": "treaty-1"}
                ],
                "revoked_trust_material": [{"id": "att-1", "feed_id": "feed-1"}],
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["proof", "inspect", "--proof-bundle", str(bundle_path), "--connectome", str(connectome_path)],
    )

    assert result.exit_code == 0, result.output
    assert "connectome artifact: matched" in result.output


def test_proof_inspect_rejects_connectome_mismatch(tmp_path):
    """Stale Connectome artifacts fail proof inspection instead of looking verified."""
    bundle_path = tmp_path / "proof-bundle.json"
    bundle_path.write_text(json.dumps(_valid_proof_bundle()), encoding="utf-8")
    connectome_path = tmp_path / "connectome.json"
    connectome_path.write_text(
        json.dumps(
            {
                "summary": {"sovereign_count": 2, "active_edge_count": 0},
                "recognition_edges": [],
                "revoked_trust_material": [],
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["proof", "inspect", "--proof-bundle", str(bundle_path), "--connectome", str(connectome_path)],
    )

    assert result.exit_code != 0, result.output
    assert "connectome artifact: mismatch" in result.output
    assert "connectome active_edge_count mismatch" in result.output


def test_proof_inspect_rejects_invalid_bundle(tmp_path):
    """Invalid proof bundles fail loudly so demos do not ship stale artifacts."""
    bundle_path = tmp_path / "proof-bundle.json"
    bundle_path.write_text(json.dumps({"proof": "wrong"}), encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(cli, ["proof", "inspect", "--proof-bundle", str(bundle_path)])

    assert result.exit_code != 0, result.output
    assert "Proof bundle: invalid" in result.output
    assert "unexpected proof type" in result.output
