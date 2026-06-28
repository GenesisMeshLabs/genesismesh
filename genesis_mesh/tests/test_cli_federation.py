"""Tests for federation bootstrap CLI workflows."""

from __future__ import annotations

import json
from pathlib import Path

import requests
from click.testing import CliRunner

from genesis_mesh.crypto import generate_keypair, save_keypair
from genesis_mesh.workflows.federation import (
    FederationBootstrapVerificationError,
    run_federation_bootstrap,
)
from genesis_mesh.cli.main import cli

from .cli_ops_helpers import _running_na_from_config


def _init_sovereign(runner: CliRunner, tmp_path: Path, name: str) -> Path:
    """Create a local sovereign config for CLI workflow tests."""
    config_path = tmp_path / f"{name.lower()}.toml"
    home = tmp_path / name.lower()
    result = runner.invoke(
        cli,
        [
            "init",
            "--config",
            str(config_path),
            "--home",
            str(home),
            "--network-name",
            name,
            "--force",
        ],
    )
    assert result.exit_code == 0, result.output
    return config_path


def test_federation_bootstrap_issues_treaty_and_evidence(tmp_path):
    """The bootstrap command reviews, issues, and verifies a direct treaty."""
    runner = CliRunner()
    acceptor_config = _init_sovereign(runner, tmp_path, "USG-A")
    issuer_config = _init_sovereign(runner, tmp_path, "USG-B")
    evidence_path = tmp_path / "federation-bootstrap-evidence.json"

    with _running_na_from_config(acceptor_config, tmp_path / "acceptor.db") as acceptor:
        with _running_na_from_config(issuer_config, tmp_path / "issuer.db") as issuer:
            result = runner.invoke(
                cli,
                [
                    "federation",
                    "bootstrap",
                    "--acceptor",
                    acceptor,
                    "--issuer",
                    issuer,
                    "--acceptor-config",
                    str(acceptor_config),
                    "--role",
                    "service:maintainer",
                    "--claim",
                    "proof=federation-bootstrap",
                    "--validity-hours",
                    "12",
                    "--evidence",
                    str(evidence_path),
                    "--yes",
                ],
            )
            assert result.exit_code == 0, result.output
            assert "Federation bootstrap completed" in result.output
            assert "trust_path: active_treaty_path" in result.output

            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            assert evidence["workflow"] == "federation-bootstrap"
            assert evidence["dry_run"] is False
            assert evidence["acceptor"]["sovereign_id"] == "USG-A"
            assert evidence["issuer"]["sovereign_id"] == "USG-B"
            assert evidence["treaty_id"]
            assert evidence["trust_path"]["trusted"] is True
            assert evidence["treaty_preview"]["scope"]["allowed_roles"] == [
                "role:service:maintainer"
            ]
            serialized = json.dumps(evidence)
            assert "operator_private_key" not in serialized
            assert "na_private_key" not in serialized
            assert "db_path" not in serialized
            assert ".key" not in serialized


def test_federation_bootstrap_dry_run_does_not_issue_treaty(tmp_path):
    """Dry-run mode performs review and preview only."""
    runner = CliRunner()
    acceptor_config = _init_sovereign(runner, tmp_path, "USG-A")
    issuer_config = _init_sovereign(runner, tmp_path, "USG-B")

    with _running_na_from_config(acceptor_config, tmp_path / "acceptor.db") as acceptor:
        with _running_na_from_config(issuer_config, tmp_path / "issuer.db") as issuer:
            result = runner.invoke(
                cli,
                [
                    "federation",
                    "bootstrap",
                    "--acceptor",
                    acceptor,
                    "--issuer",
                    issuer,
                    "--dry-run",
                    "--format",
                    "json",
                ],
            )
            assert result.exit_code == 0, result.output
            evidence = json.loads(result.output)
            assert evidence["dry_run"] is True
            assert "treaty_id" not in evidence

            connectome = requests.get(f"{acceptor}/connectome.json", timeout=10)
            connectome.raise_for_status()
            assert connectome.json()["summary"]["recognition_edge_count"] == 0


def test_federation_bootstrap_requires_confirmation_before_issue(tmp_path):
    """The command must not issue a treaty when confirmation is declined."""
    runner = CliRunner()
    acceptor_config = _init_sovereign(runner, tmp_path, "USG-A")
    issuer_config = _init_sovereign(runner, tmp_path, "USG-B")

    with _running_na_from_config(acceptor_config, tmp_path / "acceptor.db") as acceptor:
        with _running_na_from_config(issuer_config, tmp_path / "issuer.db") as issuer:
            result = runner.invoke(
                cli,
                [
                    "federation",
                    "bootstrap",
                    "--acceptor",
                    acceptor,
                    "--issuer",
                    issuer,
                    "--acceptor-config",
                    str(acceptor_config),
                ],
                input="n\n",
            )
            assert result.exit_code != 0
            assert "Issue direct-recognition treaty from USG-A to USG-B?" in result.output

            connectome = requests.get(f"{acceptor}/connectome.json", timeout=10)
            connectome.raise_for_status()
            assert connectome.json()["summary"]["recognition_edge_count"] == 0


def test_federation_bootstrap_fails_on_unavailable_issuer(tmp_path):
    """Failed public preflight checks stop before treaty issue."""
    runner = CliRunner()
    acceptor_config = _init_sovereign(runner, tmp_path, "USG-A")

    with _running_na_from_config(acceptor_config, tmp_path / "acceptor.db") as acceptor:
        result = runner.invoke(
            cli,
            [
                "federation",
                "bootstrap",
                "--acceptor",
                acceptor,
                "--issuer",
                "http://127.0.0.1:9",
                "--dry-run",
            ],
        )
        assert result.exit_code != 0
        assert "issuer healthz failed" in result.output


def test_federation_bootstrap_reports_persisted_treaty_on_failed_verification(
    tmp_path,
    monkeypatch,
):
    """A post-issue trust-path failure should clearly report persisted state."""
    keypair = generate_keypair()
    key_path, _ = save_keypair(keypair, str(tmp_path / "operator"), "operator-local")

    def fake_request_json(session, method, url, *, label, **kwargs):
        if label.endswith("healthz"):
            return {"status": "ok"}
        if label.endswith("readyz"):
            return {"status": "ready"}
        if label.endswith("genesis"):
            network_name = "USG-A" if "acceptor" in label else "USG-B"
            public_key = "acceptor-key" if "acceptor" in label else "issuer-key"
            return {
                "network_name": network_name,
                "network_version": "v0.1",
                "network_authority": {"public_key": public_key},
            }
        if label.endswith("sovereign metadata"):
            sovereign_id = "USG-A" if "acceptor" in label else "USG-B"
            public_key = "acceptor-key" if "acceptor" in label else "issuer-key"
            return {
                "sovereign_id": sovereign_id,
                "network_version": "v0.1",
                "network_authority": {"public_key": public_key},
            }
        if label.endswith("Connectome"):
            return {"summary": {}}
        if label == "acceptor treaty issue":
            return {"treaty_id": "treaty-persisted", "status": "active"}
        if label == "trust path verification":
            return {"trusted": False, "reason": "no_active_treaty_path"}
        raise AssertionError(f"unexpected request: {method} {url} {label}")

    monkeypatch.setattr("genesis_mesh.workflows.federation._request_json", fake_request_json)

    try:
        run_federation_bootstrap(
            acceptor_endpoint="https://acceptor.example.test",
            issuer_endpoint="https://issuer.example.test",
            issuer_bundle_path=None,
            acceptor_signer=("operator-local", key_path),
            roles=["role:service:maintainer"],
            accepted_statuses=["active"],
            claims={},
            validity_hours=24,
            issue_treaty=True,
            confirmed=True,
        )
    except FederationBootstrapVerificationError as exc:
        assert "Treaty was persisted" in exc.message
        assert "treaty-persisted" in exc.message
        assert exc.result["treaty_id"] == "treaty-persisted"
        assert exc.result["verification"]["status"] == "failed"
        assert "genesis-mesh treaty revoke" in exc.result["verification"]["cleanup_hint"]
    else:
        raise AssertionError("expected failed post-issue trust-path verification")
