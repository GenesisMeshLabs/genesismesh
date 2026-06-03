"""Tests for the persona-oriented Genesis Mesh CLI."""

from __future__ import annotations

import json
import sqlite3
import threading
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from click.testing import CliRunner
from werkzeug.serving import make_server

from genesis_mesh.cli.config import load_config
from genesis_mesh.cli.main import cli
from genesis_mesh.crypto import generate_keypair, load_private_key, sign_data
from genesis_mesh.models import GenesisBlock
from genesis_mesh.na_service.auth import load_operator_public_keys
from genesis_mesh.na_service.server import create_app
from genesis_mesh.cli.ops import _run_runtime_forever


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


def test_init_accepts_explicit_operator_paths(tmp_path):
    """Operators can initialize a sovereign using production-style paths."""
    config_path = tmp_path / "config.toml"
    home = tmp_path / "home"
    genesis_path = tmp_path / "etc" / "genesis" / "genesis.signed.json"
    na_key_path = tmp_path / "etc" / "genesis-mesh" / "keys" / "na.key"
    operator_key_path = tmp_path / "etc" / "genesis-mesh" / "keys" / "operator.key"
    operator_pub_path = tmp_path / "etc" / "genesis-mesh" / "operator.pub"
    db_path = tmp_path / "var" / "lib" / "genesis-mesh" / "na.db"

    result = CliRunner().invoke(
        cli,
        [
            "init",
            "--config",
            str(config_path),
            "--home",
            str(home),
            "--network-name",
            "USG-NB",
            "--na-endpoint",
            "http://164.92.250.135:8443",
            "--genesis-file",
            str(genesis_path),
            "--na-private-key-file",
            str(na_key_path),
            "--operator-private-key-file",
            str(operator_key_path),
            "--operator-public-key-file",
            str(operator_pub_path),
            "--db-path",
            str(db_path),
            "--na-host",
            "0.0.0.0",
            "--na-port",
            "8443",
            "--force",
        ],
    )

    assert result.exit_code == 0, result.output
    config = load_config(str(config_path), required=True)
    assert config["network"]["name"] == "USG-NB"
    assert config["network"]["na_endpoint"] == "http://164.92.250.135:8443"
    assert config["paths"]["genesis"] == genesis_path.as_posix()
    assert config["paths"]["na_private_key"] == na_key_path.as_posix()
    assert config["paths"]["operator_private_key"] == operator_key_path.as_posix()
    assert config["paths"]["operator_public_key"] == operator_pub_path.as_posix()
    assert config["paths"]["db"] == db_path.as_posix()
    assert config["na"]["host"] == "0.0.0.0"
    assert config["na"]["port"] == 8443
    assert genesis_path.exists()
    assert na_key_path.exists()
    assert operator_key_path.exists()
    assert operator_pub_path.exists()


def test_init_requires_explicit_network_name_for_operator_paths(tmp_path):
    """Production-style paths should not silently reuse the default sovereign name."""
    result = CliRunner().invoke(
        cli,
        [
            "init",
            "--config",
            str(tmp_path / "config.toml"),
            "--home",
            str(tmp_path / "home"),
            "--genesis-file",
            str(tmp_path / "etc" / "genesis.signed.json"),
            "--force",
        ],
    )

    assert result.exit_code != 0
    assert "requires an explicit --network-name" in result.output
    assert "Traceback" not in result.output


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


def test_proof_cleanup_backs_up_and_removes_only_proof_tables(tmp_path):
    """Proof cleanup uses Python SQLite and keeps non-proof state untouched."""
    db_path = tmp_path / "na.db"
    conn = sqlite3.connect(db_path)
    try:
        for table in [
            "imported_sovereign_revocations",
            "sovereign_revocation_feeds",
            "recognition_treaties",
            "membership_attestations",
            "issued_certs",
        ]:
            conn.execute(f"CREATE TABLE {table}(id TEXT)")
            conn.execute(f"INSERT INTO {table}(id) VALUES ('row')")
        conn.commit()
    finally:
        conn.close()

    result = CliRunner().invoke(
        cli,
        [
            "proof",
            "cleanup",
            "--db-path",
            str(db_path),
            "--backup-dir",
            str(tmp_path / "backups"),
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    conn = sqlite3.connect(db_path)
    try:
        for table in [
            "imported_sovereign_revocations",
            "sovereign_revocation_feeds",
            "recognition_treaties",
            "membership_attestations",
        ]:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM issued_certs").fetchone()[0] == 1
    finally:
        conn.close()
    assert list((tmp_path / "backups").glob("na.db.backup-before-proof-cleanup-*"))


def test_remote_proof_runs_against_two_configured_endpoints(tmp_path):
    """A single CLI command can run the direct cross-sovereign proof."""
    runner = CliRunner()
    acceptor_config = tmp_path / "acceptor.toml"
    issuer_config = tmp_path / "issuer.toml"
    bundle_path = tmp_path / "proof-bundle.json"

    acceptor_init = runner.invoke(
        cli,
        [
            "init",
            "--config",
            str(acceptor_config),
            "--home",
            str(tmp_path / "acceptor"),
            "--network-name",
            "USG",
            "--force",
        ],
    )
    assert acceptor_init.exit_code == 0, acceptor_init.output
    issuer_init = runner.invoke(
        cli,
        [
            "init",
            "--config",
            str(issuer_config),
            "--home",
            str(tmp_path / "issuer"),
            "--network-name",
            "USG-NB",
            "--force",
        ],
    )
    assert issuer_init.exit_code == 0, issuer_init.output

    with _running_na_from_config(acceptor_config, tmp_path / "acceptor.db") as acceptor:
        with _running_na_from_config(issuer_config, tmp_path / "issuer.db") as issuer:
            result = runner.invoke(
                cli,
                [
                    "proof",
                    "remote",
                    "--acceptor",
                    acceptor,
                    "--issuer",
                    issuer,
                    "--acceptor-config",
                    str(acceptor_config),
                    "--issuer-config",
                    str(issuer_config),
                    "--claim",
                    "proof=pytest",
                    "--proof-bundle",
                    str(bundle_path),
                    "--adoption-proof",
                    "--acceptor-operator-label",
                    "Genesis Core",
                    "--acceptor-operator-type",
                    "maintainer",
                    "--issuer-operator-label",
                    "External Operator",
                    "--issuer-operator-type",
                    "external",
                    "--issuer-controls-keys",
                    "--issuer-controls-infrastructure",
                    "--operator-assistance-note",
                    "No protocol changes required.",
                ],
            )

    assert result.exit_code == 0, result.output
    assert "Remote sovereign proof passed" in result.output
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle["acceptor"]["network_name"] == "USG"
    assert bundle["issuer"]["network_name"] == "USG-NB"
    assert bundle["pre_revocation"]["accepted"] is True
    assert bundle["post_revocation"]["accepted"] is False
    assert bundle["post_revocation"]["reason"] == "attestation_locally_revoked"
    assert bundle["operators"]["adoption_proof"] is True
    assert bundle["operators"]["issuer"]["operator_type"] == "external"
    assert bundle["operators"]["issuer"]["controls_keys"] is True
    assert bundle["operators"]["issuer"]["controls_infrastructure"] is True
    assert bundle["operators"]["assistance_notes"] == ["No protocol changes required."]
    assert "operator.key" not in json.dumps(bundle)


def test_remote_adoption_proof_requires_external_operator_confirmation(tmp_path):
    """Adoption-proof mode must not produce weak evidence by accident."""
    result = CliRunner().invoke(
        cli,
        [
            "proof",
            "remote",
            "--acceptor",
            "http://acceptor.example",
            "--issuer",
            "http://issuer.example",
            "--operator-key",
            str(tmp_path / "operator.key"),
            "--adoption-proof",
        ],
    )

    assert result.exit_code != 0
    assert "--issuer-operator-type external" in result.output
    assert "Traceback" not in result.output


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


def test_status_reports_missing_config_without_traceback(tmp_path):
    """The status command reports a missing config without leaking a traceback."""
    missing_config = tmp_path / "missing.toml"

    result = CliRunner().invoke(cli, ["status", "--config", str(missing_config)])

    assert result.exit_code != 0
    assert "No Genesis Mesh config found" in result.output
    assert "Traceback" not in result.output


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


def test_dev_down_removes_runtime_artifacts(tmp_path):
    """The dev-down command removes generated local runtime artifacts."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path(".genesis-mesh").mkdir()
        Path(".genesis-mesh", "na.db").write_text("placeholder", encoding="utf-8")
        Path(".node2").mkdir()
        Path(".node2", "node.json").write_text("placeholder", encoding="utf-8")
        Path("genesis-mesh.toml").write_text("[network]\n", encoding="utf-8")

        result = runner.invoke(cli, ["dev", "down"])

        assert result.exit_code == 0, result.output
        assert "Removed .genesis-mesh" in result.output
        assert "Removed .node2" in result.output
        assert "Removed genesis-mesh.toml" in result.output
        assert not Path(".genesis-mesh").exists()
        assert not Path(".node2").exists()
        assert not Path("genesis-mesh.toml").exists()


def test_dev_down_reports_locked_runtime_artifacts(tmp_path, monkeypatch):
    """Locked runtime artifacts produce a clean remediation message."""
    runner = CliRunner()

    def locked_rmtree(path):
        raise PermissionError("file is locked")

    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path(".genesis-mesh").mkdir()
        monkeypatch.setattr("genesis_mesh.cli.ops.shutil.rmtree", locked_rmtree)

        result = runner.invoke(cli, ["dev", "down"])

        assert result.exit_code != 0
        assert "Some generated files are locked" in result.output
        assert "Stop any running `genesis-mesh na start`" in result.output
        assert "Traceback" not in result.output


def test_runtime_forever_stops_runtime_when_cancelled():
    """Persistent CLI runtime loop stops subsystems when interrupted."""

    class Runtime:
        """Minimal runtime stub for cancellation behavior."""

        def __init__(self):
            self.started = False
            self.stopped = False

        async def start(self):
            self.started = True

        async def stop(self):
            self.stopped = True

    async def run_cancel():
        runtime = Runtime()
        task = asyncio.create_task(_run_runtime_forever(runtime))
        while not runtime.started:
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return runtime

    runtime = asyncio.run(run_cancel())

    assert runtime.started is True
    assert runtime.stopped is True


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
