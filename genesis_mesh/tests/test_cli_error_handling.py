"""CLI error handling tests for operator-facing workflows."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from genesis_mesh.cli.main import cli

from .cli_ops_helpers import _running_na_from_config


def _write_admin_config(path: Path, key_path: Path | None = None) -> None:
    """Write the minimum config needed by signed admin commands."""
    operator_key = (key_path or path.parent / "missing.key").as_posix()
    path.write_text(
        "\n".join(
            [
                "[network]",
                'na_endpoint = "https://na.example.test"',
                "",
                "[paths]",
                f'operator_private_key = "{operator_key}"',
                "",
                "[operator]",
                'key_id = "operator-local"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_admin_invite_rejects_invalid_role_before_http(tmp_path):
    """A mistyped role should not become a server traceback."""
    config_path = tmp_path / "admin.toml"
    _write_admin_config(config_path)

    result = CliRunner().invoke(
        cli,
        [
            "admin",
            "invite",
            "--config",
            str(config_path),
            "--role",
            "node",
        ],
    )

    assert result.exit_code != 0
    assert "Invalid role: role:node" in result.output
    assert "Allowed roles" in result.output
    assert "Traceback" not in result.output


def test_admin_invite_rejects_non_positive_windows(tmp_path):
    """Invalid validity windows should fail before signing or HTTP."""
    config_path = tmp_path / "admin.toml"
    _write_admin_config(config_path)

    result = CliRunner().invoke(
        cli,
        [
            "admin",
            "invite",
            "--config",
            str(config_path),
            "--validity-hours",
            "0",
        ],
    )

    assert result.exit_code != 0
    assert "--validity-hours must be greater than zero" in result.output
    assert "Traceback" not in result.output


def test_admin_invite_reports_missing_operator_key(tmp_path):
    """Missing signing keys should produce an actionable operator message."""
    config_path = tmp_path / "admin.toml"
    key_path = tmp_path / "missing-operator.key"
    _write_admin_config(config_path, key_path)

    result = CliRunner().invoke(
        cli,
        ["admin", "invite", "--config", str(config_path), "--role", "client"],
    )

    assert result.exit_code != 0
    assert f"Operator private key not found: {key_path}" in result.output
    assert "Traceback" not in result.output


def test_admin_invite_prints_server_validation_body(tmp_path, monkeypatch):
    """Server-side 400 JSON errors should be shown without a Python traceback."""
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

    class Response:
        status_code = 400
        text = '{"error":"Invalid role: role:node"}'

        def json(self):
            return {"error": "Invalid role: role:node"}

    def fake_request(*args, **kwargs):
        return Response()

    monkeypatch.setattr("requests.sessions.Session.request", fake_request)

    result = runner.invoke(
        cli,
        ["admin", "invite", "--config", str(config_path), "--role", "client"],
    )

    assert result.exit_code != 0
    assert "invite creation failed: 400 Invalid role: role:node" in result.output
    assert "HTTPError" not in result.output
    assert "Traceback" not in result.output


def test_federation_bootstrap_rejects_invalid_role(tmp_path):
    """Federation role validation should fail locally before remote calls."""
    result = CliRunner().invoke(
        cli,
        [
            "federation",
            "bootstrap",
            "--acceptor",
            "https://acceptor.example.test",
            "--issuer",
            "https://issuer.example.test",
            "--role",
            "node",
            "--dry-run",
        ],
    )

    assert result.exit_code != 0
    assert "Invalid role: role:node" in result.output
    assert "Traceback" not in result.output


def test_treaty_replace_rejects_invalid_role():
    """Treaty lifecycle role replacement uses the same validation surface."""
    result = CliRunner().invoke(
        cli,
        [
            "treaty",
            "replace",
            "--na",
            "https://na.example.test",
            "treaty-1",
            "--role",
            "node",
            "--yes",
        ],
    )

    assert result.exit_code != 0
    assert "Invalid role: role:node" in result.output
    assert "Traceback" not in result.output


def test_join_with_mismatched_config_fails_cleanly(tmp_path):
    """Joining one sovereign with another sovereign's genesis should be clear."""
    runner = CliRunner()
    a_config = tmp_path / "a.toml"
    b_config = tmp_path / "b.toml"
    for config_path, home, name in (
        (a_config, tmp_path / "a-home", "USG-A"),
        (b_config, tmp_path / "b-home", "USG-B"),
    ):
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

    with _running_na_from_config(a_config, tmp_path / "a.db") as endpoint:
        invite = runner.invoke(
            cli,
            ["admin", "invite", "--config", str(a_config), "--na", endpoint],
        )
        assert invite.exit_code == 0, invite.output

        result = runner.invoke(
            cli,
            [
                "join",
                "--config",
                str(b_config),
                "--na",
                endpoint,
                "--token",
                invite.output.strip(),
            ],
        )

    assert result.exit_code != 0
    assert "Join enrollment failed" in result.output
    assert "same sovereign as --na" in result.output
    assert "Traceback" not in result.output
