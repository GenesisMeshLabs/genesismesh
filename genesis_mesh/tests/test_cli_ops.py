"""Tests for the persona-oriented Genesis Mesh CLI."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from pathlib import Path

from click.testing import CliRunner
from werkzeug.serving import make_server

from genesis_mesh.cli.config import load_config
from genesis_mesh.cli.main import cli
from genesis_mesh.crypto import load_private_key
from genesis_mesh.models import GenesisBlock
from genesis_mesh.na_service.auth import load_operator_public_keys
from genesis_mesh.na_service.server import create_app


def test_init_creates_config_and_local_artifacts(tmp_path):
    """The init command creates keys, genesis artifacts, and a project config."""
    config_path = tmp_path / "genesis-mesh.toml"
    home = tmp_path / ".genesis-mesh"

    result = CliRunner().invoke(
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

    assert result.exit_code == 0, result.output
    config = load_config(str(config_path), required=True)
    assert config["network"]["na_endpoint"] == "http://127.0.0.1:8443"
    genesis = GenesisBlock.model_validate_json(
        Path(config["paths"]["genesis"]).read_text(encoding="utf-8")
    )
    assert genesis.bootstrap_anchors == []
    assert Path(config["paths"]["genesis"]).exists()
    assert Path(config["paths"]["na_private_key"]).exists()
    assert Path(config["paths"]["operator_private_key"]).exists()


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


def test_na_start_reports_missing_config_without_traceback(tmp_path):
    """Missing config is reported as a Click error instead of a traceback."""
    missing_config = tmp_path / "missing.toml"

    result = CliRunner().invoke(
        cli,
        ["na", "start", "--config", str(missing_config)],
    )

    assert result.exit_code != 0
    assert "No Genesis Mesh config found" in result.output
    assert "Traceback" not in result.output


@contextmanager
def _running_na_from_config(config_path: Path, db_path: Path):
    """Run a configured Network Authority on an ephemeral localhost port."""
    config = load_config(str(config_path), required=True)
    with open(config["paths"]["genesis"], "r", encoding="utf-8") as f:
        genesis = GenesisBlock(**json.load(f))

    app = create_app(
        genesis_block=genesis,
        na_private_key=load_private_key(config["paths"]["na_private_key"]),
        key_id=config["na"]["key_id"],
        db_path=str(db_path),
        operator_public_keys=load_operator_public_keys(
            [f"{config['operator']['key_id']}={config['paths']['operator_public_key']}"]
        ),
    )
    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
