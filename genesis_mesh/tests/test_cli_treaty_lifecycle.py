"""Tests for treaty lifecycle CLI and derived state."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from click.testing import CliRunner

from genesis_mesh.cli.config import load_config
from genesis_mesh.cli.main import cli
from genesis_mesh.cli.support import _signed_admin_headers
from genesis_mesh.models import RecognitionTreaty, RecognitionTreatyScope
from genesis_mesh.trust.treaty_lifecycle import treaty_lifecycle

from .cli_ops_helpers import _running_na_from_config


def _init_sovereign(runner: CliRunner, tmp_path: Path, name: str) -> Path:
    config_path = tmp_path / f"{name.lower()}.toml"
    result = runner.invoke(
        cli,
        [
            "init",
            "--config",
            str(config_path),
            "--home",
            str(tmp_path / name.lower()),
            "--network-name",
            name,
            "--force",
        ],
    )
    assert result.exit_code == 0, result.output
    return config_path


def _issue_treaty(endpoint: str, config_path: Path, subject: str = "USG-NB") -> dict:
    """Issue a treaty directly through the existing signed admin endpoint."""
    config = load_config(str(config_path), required=True)
    key_id = config["operator"]["key_id"]
    key_path = Path(config["paths"]["operator_private_key"])
    body: dict[str, Any] = {
        "subject_sovereign_id": subject,
        "subject_public_keys": ["subject-public-key"],
        "scope": {
            "allowed_roles": ["role:service:maintainer"],
            "accepted_statuses": ["active"],
            "claims": {"proof": "lifecycle"},
        },
        "validity_hours": 24,
        "metadata": {"subject_endpoint": "https://issuer.example"},
    }
    response = requests.post(
        f"{endpoint}/admin/recognition-treaties",
        json=body,
        headers=_signed_admin_headers(key_id, key_path, body),
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def test_treaty_lifecycle_classifies_expiring_and_expired():
    """Lifecycle labels are derived without database schema changes."""
    now = datetime(2026, 6, 5, tzinfo=timezone.utc)
    expiring = _row(now, now + timedelta(hours=2), "active")
    expired = _row(now - timedelta(days=2), now - timedelta(hours=1), "active")

    assert treaty_lifecycle(expiring, now=now)["state"] == "expiring_soon"
    assert treaty_lifecycle(expiring, now=now)["expiry_risk"] == "high"
    assert treaty_lifecycle(expired, now=now)["state"] == "expired"
    assert treaty_lifecycle(expired, now=now)["expiry_risk"] == "expired"


def test_treaty_list_inspect_revoke_and_connectome(tmp_path):
    """Operators can list, inspect, revoke, and see Connectome consistency."""
    runner = CliRunner()
    config_path = _init_sovereign(runner, tmp_path, "USG")

    with _running_na_from_config(config_path, tmp_path / "na.db") as endpoint:
        treaty = _issue_treaty(endpoint, config_path)
        treaty_id = treaty["treaty_id"]

        listed = runner.invoke(cli, ["treaty", "list", "--na", endpoint])
        assert listed.exit_code == 0, listed.output
        assert treaty_id in listed.output
        assert "active" in listed.output

        inspected = runner.invoke(cli, ["treaty", "inspect", "--na", endpoint, treaty_id])
        assert inspected.exit_code == 0, inspected.output
        assert "role:service:maintainer" in inspected.output
        assert "claims:" in inspected.output

        connectome = requests.get(f"{endpoint}/connectome.json", timeout=10).json()
        assert connectome["summary"]["active_edge_count"] == 1

        revoked = runner.invoke(
            cli,
            [
                "treaty",
                "revoke",
                "--na",
                endpoint,
                treaty_id,
                "--config",
                str(config_path),
                "--reason",
                "relationship_ended",
                "--yes",
            ],
        )
        assert revoked.exit_code == 0, revoked.output

        inspected_after = runner.invoke(
            cli,
            ["treaty", "inspect", "--na", endpoint, treaty_id],
        )
        assert inspected_after.exit_code == 0, inspected_after.output
        assert "revoked" in inspected_after.output
        assert "relationship_ended" in inspected_after.output

        connectome_after = requests.get(f"{endpoint}/connectome.json", timeout=10).json()
        assert connectome_after["summary"]["active_edge_count"] == 0
        assert connectome_after["summary"]["revoked_edge_count"] == 1


def test_treaty_renew_and_replace_retire_old_treaties(tmp_path):
    """Renew and replace helpers create successors and mark old treaties replaced."""
    runner = CliRunner()
    config_path = _init_sovereign(runner, tmp_path, "USG")

    with _running_na_from_config(config_path, tmp_path / "na.db") as endpoint:
        renew_source = _issue_treaty(endpoint, config_path, "USG-NB")
        renew_result = runner.invoke(
            cli,
            [
                "treaty",
                "renew",
                "--na",
                endpoint,
                renew_source["treaty_id"],
                "--config",
                str(config_path),
                "--validity-hours",
                "48",
                "--yes",
            ],
        )
        assert renew_result.exit_code == 0, renew_result.output
        assert "Recognition treaty renewed" in renew_result.output

        replace_source = _issue_treaty(endpoint, config_path, "USG-NC")
        replace_result = runner.invoke(
            cli,
            [
                "treaty",
                "replace",
                "--na",
                endpoint,
                replace_source["treaty_id"],
                "--config",
                str(config_path),
                "--role",
                "service:observer",
                "--claim",
                "proof=replaced",
                "--yes",
            ],
        )
        assert replace_result.exit_code == 0, replace_result.output
        assert "Recognition treaty replaced" in replace_result.output

        rows = runner.invoke(
            cli,
            ["treaty", "list", "--na", endpoint, "--format", "json"],
        )
        assert rows.exit_code == 0, rows.output
        data = json.loads(rows.output)
        old_rows = {
            row["treaty"]["treaty_id"]: row
            for row in data["recognition_treaties"]
            if row["treaty"]["treaty_id"] in {
                renew_source["treaty_id"],
                replace_source["treaty_id"],
            }
        }
        assert old_rows[renew_source["treaty_id"]]["lifecycle"]["state"] == "replaced"
        assert old_rows[replace_source["treaty_id"]]["lifecycle"]["state"] == "replaced"

        active_rows = [
            row for row in data["recognition_treaties"]
            if row["lifecycle"]["state"] in {"active", "expiring_soon"}
        ]
        assert len(active_rows) == 2
        assert any(
            row["treaty"]["scope"]["claims"] == {"proof": "replaced"}
            and row["treaty"]["scope"]["allowed_roles"] == ["role:service:observer"]
            for row in active_rows
        )


def test_treaty_inspect_unknown_id_fails(tmp_path):
    """Unknown treaty IDs fail cleanly."""
    runner = CliRunner()
    config_path = _init_sovereign(runner, tmp_path, "USG")
    with _running_na_from_config(config_path, tmp_path / "na.db") as endpoint:
        result = runner.invoke(cli, ["treaty", "inspect", "--na", endpoint, "missing"])

    assert result.exit_code != 0
    assert "treaty inspect failed: 404" in result.output


def _row(valid_from: datetime, expires_at: datetime, status: str) -> dict:
    treaty = RecognitionTreaty(
        treaty_id="treaty-test",
        issuer_sovereign_id="USG",
        subject_sovereign_id="USG-NB",
        subject_public_keys=["subject-public-key"],
        scope=RecognitionTreatyScope(allowed_roles=["role:service:maintainer"]),
        status="active",
        issued_at=valid_from,
        valid_from=valid_from,
        expires_at=expires_at,
        issued_by="na-test",
        signatures=[],
    )
    return {
        "treaty": treaty,
        "status": status,
        "revoked_at": None,
        "revocation_reason": None,
    }
