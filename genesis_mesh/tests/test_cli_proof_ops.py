"""Tests for CLI proof and cleanup operations."""

from __future__ import annotations

import json
import sqlite3

from click.testing import CliRunner

from genesis_mesh.cli.main import cli

from .cli_ops_helpers import _running_na_from_config


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
