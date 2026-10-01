"""SQLite to PostgreSQL migration and database verification (v0.60)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from genesis_mesh.cli.main import cli
from genesis_mesh.models import JoinCertificate
from genesis_mesh.na_service.db import NADatabase
from genesis_mesh.na_service.server import NetworkAuthorityService
from genesis_mesh.crypto import generate_keypair
from genesis_mesh.workflows.db_migration import MigrationError, migrate_sqlite_to_postgres, verify_database

from .pg_support import fresh_postgres_url
from .test_evidence_store import Controller, _client, _decide, _submit
from .test_na_boundary_policy import _activate, _make_service, _publish


def _populate(service: NetworkAuthorityService) -> None:
    """Policies, attestations, decisions, evidence chains and a CRL revocation."""
    client = _client(service)
    policy = _publish(client)
    assert _activate(client, policy["policy_id"], policy["version"]).status_code == 200
    controller = Controller(client)
    first = controller.record(_decide(client), action="create")
    assert _submit(client, first).status_code == 201
    second = controller.record(_decide(client), action="rotate", prior_resource=first)
    assert _submit(client, second).status_code == 201
    service._get_or_create_active_crl()
    now = datetime.now(timezone.utc)
    cert = JoinCertificate(
        cert_id=str(uuid.uuid4()), node_public_key=generate_keypair().public_key_b64, network_name="TEST",
        roles=["role:client"], issued_at=now, expires_at=now + timedelta(hours=1),
        issued_by=service.key_id, signatures=[],
    )
    service.db.issue_cert(cert, "127.0.0.1")
    service.publish_crl(lambda: service.db.revoke_cert(cert.cert_id, "key_compromise", service.key_id))


@pytest.fixture
def source(tmp_path) -> tuple[Path, str]:
    """A populated v0.60 SQLite database file and its NA public key."""
    path = tmp_path / "na.db"
    service = _make_service(evidence_store="on", database_url=f"sqlite:///{path}")
    _populate(service)
    na_key = service.signer.public_key_b64
    service.db.close()
    return path, na_key


@pytest.mark.sqlite_only
def test_verify_db_passes_on_a_healthy_sqlite_database(source):
    path, na_key = source
    report = verify_database(NADatabase(str(path)), na_key)
    assert report.ok, report.failures
    assert report.checks["evidence"]["entries"] >= 4
    assert report.checks["crl"]["versions"] == 2


@pytest.mark.sqlite_only
def test_verify_db_cli_reports_a_tampered_policy(source, tmp_path):
    path, _ = source
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE boundary_policy_versions SET policy_json = replace(policy_json, 'read', 'rEad')")
    result = CliRunner().invoke(cli, ["na", "verify-db", "--db-path", str(path)])
    assert result.exit_code == 1
    assert "boundary policies fail their digest check" in result.output


@pytest.mark.postgres
def test_migrates_everything_and_the_target_verifies_and_serves(request, source):
    path, na_key = source
    target_url = fresh_postgres_url(request)
    report = migrate_sqlite_to_postgres(str(path), target_url, na_public_key=na_key)
    assert report["verification"]["ok"]
    assert report["tables"]["evidence_entries"]["rows"] >= 4
    assert report["tables"]["crl_versions"]["rows"] == 2
    assert report["tables"]["boundary_policy_versions"]["rows"] == 1

    target = NADatabase(database_url=target_url)
    try:
        assert verify_database(target, na_key).ok
        events = [e["event_type"] for e in target.list_audit_events()]
        assert events[-1] == "database_migrated"
    finally:
        target.close()


@pytest.mark.postgres
def test_refuses_a_non_empty_target(request, source):
    path, na_key = source
    target_url = fresh_postgres_url(request)
    migrate_sqlite_to_postgres(str(path), target_url)
    with pytest.raises(MigrationError, match="not empty"):
        migrate_sqlite_to_postgres(str(path), target_url)


@pytest.mark.postgres
def test_refuses_a_source_at_an_older_schema(request, source, tmp_path):
    path, _ = source
    old = tmp_path / "old.db"
    old.write_bytes(path.read_bytes())
    with sqlite3.connect(old) as conn:
        conn.execute("DELETE FROM schema_version WHERE version = (SELECT MAX(version) FROM schema_version)")
    with pytest.raises(MigrationError, match="source schema"):
        migrate_sqlite_to_postgres(str(old), fresh_postgres_url(request))


@pytest.mark.postgres
def test_verification_detects_tampering_on_postgres(request, source):
    path, na_key = source
    target_url = fresh_postgres_url(request)
    migrate_sqlite_to_postgres(str(path), target_url)
    target = NADatabase(database_url=target_url)
    try:
        with target.conn:
            target.conn.execute("DROP TRIGGER evidence_entries_no_update ON evidence_entries")
            row = target.conn.execute(
                "SELECT store_sequence, payload_json FROM evidence_entries WHERE entry_kind = 'execution' "
                "ORDER BY store_sequence LIMIT 1"
            ).fetchone()
            payload = json.loads(row["payload_json"])
            payload["outcome"] = "failure"
            target.conn.execute(
                "UPDATE evidence_entries SET payload_json = ? WHERE store_sequence = ?",
                (json.dumps(payload), row["store_sequence"]),
            )
            target.conn.execute(
                "UPDATE boundary_policy_versions SET policy_digest = 'tampered'"
            )
        report = verify_database(target, na_key)
        assert not report.ok
        joined = " ".join(report.failures)
        assert "payload digest mismatch" in joined and "boundary policies" in joined
    finally:
        target.close()


@pytest.mark.postgres
def test_migrate_db_cli_writes_a_report(request, source, tmp_path):
    path, _ = source
    report_path = tmp_path / "report.json"
    result = CliRunner().invoke(
        cli, ["na", "migrate-db", "--from", f"sqlite:///{path}", "--to", fresh_postgres_url(request),
              "--report", str(report_path)],
    )
    assert result.exit_code == 0, result.output
    assert "verification passed" in result.output
    assert json.loads(report_path.read_text())["verification"]["ok"]


def test_migrate_db_cli_refuses_a_non_postgres_target(tmp_path):
    result = CliRunner().invoke(cli, ["na", "migrate-db", "--from", str(tmp_path / "x.db"), "--to", "sqlite:///y.db"])
    assert result.exit_code != 0 and "postgresql://" in result.output
