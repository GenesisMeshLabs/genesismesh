"""Tests for managed sovereign operational commands."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from click.testing import CliRunner
import nacl.encoding
import nacl.signing

from genesis_mesh.cli.main import cli
from genesis_mesh.crypto import sign_model
from genesis_mesh.models import (
    GenesisBlock,
    NetworkAuthority,
    PolicyManifestRef,
    RecognitionTreaty,
    RecognitionTreatyScope,
)
from genesis_mesh.na_service.db import NADatabase
from genesis_mesh.na_service.server import NetworkAuthorityService


def test_managed_backup_and_restore_drill_restores_database_state(tmp_path):
    """A non-production backup/restore drill restores previous NA state."""
    db_path = tmp_path / "na.db"
    backup_path = tmp_path / "backups" / "na-backup.db"
    pre_restore_path = tmp_path / "backups" / "pre-restore.db"
    db = NADatabase(str(db_path))
    try:
        db.migrate()
        db.add_audit_event("drill_started", {"status": "before_backup"})
    finally:
        db.conn.close()

    backup = CliRunner().invoke(
        cli,
        ["managed", "backup", "--db-path", str(db_path), "--output", str(backup_path)],
    )

    assert backup.exit_code == 0, backup.output
    assert backup_path.exists()

    db = NADatabase(str(db_path))
    try:
        db.add_audit_event("drill_mutated", {"status": "after_backup"})
        assert len(db.list_audit_events()) == 2
    finally:
        db.conn.close()

    restore = CliRunner().invoke(
        cli,
        [
            "managed",
            "restore",
            "--db-path",
            str(db_path),
            "--backup",
            str(backup_path),
            "--pre-restore-backup",
            str(pre_restore_path),
            "--yes",
        ],
    )

    assert restore.exit_code == 0, restore.output
    assert pre_restore_path.exists()
    restored = NADatabase(str(db_path))
    try:
        events = restored.list_audit_events()
    finally:
        restored.conn.close()
    assert [event["event_type"] for event in events] == ["drill_started"]


def test_managed_restore_drill_restores_live_na_health_and_connectome(tmp_path):
    """A restored DB can be reopened by the NA and exposes restored trust state."""
    db_path = tmp_path / "na.db"
    backup_path = tmp_path / "na-backup.db"

    service = _new_service(db_path)
    try:
        service.db.save_recognition_treaty(_treaty("restored-treaty"))
        service.db.add_audit_event("restore_drill_seeded", {"treaty_id": "restored-treaty"})
    finally:
        service.db.conn.close()

    backup = CliRunner().invoke(
        cli,
        ["managed", "backup", "--db-path", str(db_path), "--output", str(backup_path)],
    )
    assert backup.exit_code == 0, backup.output

    service = _new_service(db_path)
    try:
        service.db.save_recognition_treaty(_treaty("mutated-after-backup"))
    finally:
        service.db.conn.close()

    restore = CliRunner().invoke(
        cli,
        ["managed", "restore", "--db-path", str(db_path), "--backup", str(backup_path), "--yes"],
    )
    assert restore.exit_code == 0, restore.output

    restored_service = _new_service(db_path)
    try:
        client = restored_service.app.test_client()
        healthz = client.get("/healthz")
        readyz = client.get("/readyz")
        connectome = client.get("/connectome.json")
    finally:
        restored_service.db.conn.close()

    assert healthz.status_code == 200
    assert healthz.get_json()["status"] == "ok"
    assert readyz.status_code == 200
    assert readyz.get_json()["status"] == "ready"
    assert connectome.status_code == 200
    data = connectome.get_json()
    assert data["summary"]["recognition_edge_count"] == 1
    assert data["recognition_edges"][0]["treaty_id"] == "restored-treaty"


def test_managed_restore_requires_confirmation(tmp_path):
    """Restore refuses to replace DB state without explicit confirmation."""
    db_path = tmp_path / "na.db"
    backup_path = tmp_path / "backup.db"
    db = NADatabase(str(db_path))
    try:
        db.migrate()
        db.backup(str(backup_path))
    finally:
        db.conn.close()

    result = CliRunner().invoke(
        cli,
        ["managed", "restore", "--db-path", str(db_path), "--backup", str(backup_path)],
    )

    assert result.exit_code != 0
    assert "Refusing to restore without --yes" in result.output
    assert "Traceback" not in result.output


def test_managed_audit_export_redacts_sensitive_fields(tmp_path):
    """Audit export is suitable for sharing with support and SIEM pipelines."""
    db_path = tmp_path / "na.db"
    export_path = tmp_path / "audit.jsonl"
    db = NADatabase(str(db_path))
    try:
        db.migrate()
        db.add_audit_event(
            "admin_request_rejected",
            {
                "operator_key_id": "operator-local",
                "admin_signature": "secret-signature",
                "invite_token": "secret-token",
                "request_body": {"private_key": "secret-key", "cert_id": "cert-1"},
                "result": "denied",
            },
        )
    finally:
        db.conn.close()

    result = CliRunner().invoke(
        cli,
        [
            "managed",
            "audit-export",
            "--db-path",
            str(db_path),
            "--output",
            str(export_path),
        ],
    )

    assert result.exit_code == 0, result.output
    lines = export_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["details"]["admin_signature"] == "<redacted>"
    assert event["details"]["invite_token"] == "<redacted>"
    assert event["details"]["request_body"] == "<redacted>"
    assert "secret" not in export_path.read_text(encoding="utf-8")


def test_managed_audit_export_supports_json_and_event_type_filter(tmp_path):
    """Operators can export one event class as a JSON array."""
    db_path = tmp_path / "na.db"
    export_path = tmp_path / "audit.json"
    db = NADatabase(str(db_path))
    try:
        db.migrate()
        db.add_audit_event("ignored", {"result": "ok"})
        db.add_audit_event("recognition_treaty_issued", {"treaty_id": "treaty-1"})
    finally:
        db.conn.close()

    result = CliRunner().invoke(
        cli,
        [
            "managed",
            "audit-export",
            "--db-path",
            str(db_path),
            "--output",
            str(export_path),
            "--format",
            "json",
            "--event-type",
            "recognition_treaty_issued",
        ],
    )

    assert result.exit_code == 0, result.output
    events = json.loads(export_path.read_text(encoding="utf-8"))
    assert len(events) == 1
    assert events[0]["event_type"] == "recognition_treaty_issued"


def test_managed_restore_rejects_non_na_sqlite_file(tmp_path):
    """Restore validates the backup shape before replacing the target DB."""
    db_path = tmp_path / "na.db"
    backup_path = tmp_path / "not-na.db"
    conn = sqlite3.connect(backup_path)
    try:
        conn.execute("CREATE TABLE something_else(id TEXT)")
        conn.commit()
    finally:
        conn.close()

    result = CliRunner().invoke(
        cli,
        [
            "managed",
            "restore",
            "--db-path",
            str(db_path),
            "--backup",
            str(backup_path),
            "--yes",
        ],
    )

    assert result.exit_code != 0
    assert "does not look like a Genesis Mesh NA database" in result.output


def _new_service(db_path):
    na_key = nacl.signing.SigningKey(bytes([7]) * 32)
    na_public = na_key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode("utf-8")
    now = datetime.now(timezone.utc)
    genesis = GenesisBlock(
        network_name="managed-test",
        network_version="v0.16-test",
        root_public_key=na_public,
        network_authority=NetworkAuthority(
            public_key=na_public,
            valid_from=now - timedelta(minutes=1),
            valid_to=now + timedelta(days=90),
        ),
        policy_manifest=PolicyManifestRef(hash="sha256:test", url=None),
    )
    return NetworkAuthorityService(
        genesis_block=genesis,
        na_private_key=na_key,
        key_id="managed-test-na",
        db_path=str(db_path),
        operator_public_keys={},
    )


def _treaty(treaty_id: str) -> RecognitionTreaty:
    signer = nacl.signing.SigningKey(bytes([8]) * 32)
    public_key = signer.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode("utf-8")
    now = datetime.now(timezone.utc)
    treaty = RecognitionTreaty(
        treaty_id=treaty_id,
        issuer_sovereign_id="managed-test",
        subject_sovereign_id="customer-sovereign",
        subject_public_keys=[public_key],
        scope=RecognitionTreatyScope(allowed_roles=["role:service:maintainer"]),
        status="active",
        issued_at=now,
        valid_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        issued_by="managed-test-na",
    )
    treaty.signatures.append(sign_model(treaty, signer, "managed-test-na"))
    return treaty
