"""Tests for managed sovereign operational commands."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from click.testing import CliRunner
import pytest
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

# SQLite backup/restore tooling; PostgreSQL relies on the managed service's backups.
pytestmark = pytest.mark.sqlite_only


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


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="POSIX permissions; root ignores them")
def test_managed_restore_reads_a_backup_on_read_only_media(tmp_path):
    """Validating a backup never writes to it, so a read-only backup directory
    works (as a backup volume mounted read-only into a container) (v1.0.2)."""
    db_path = tmp_path / "na.db"
    backup_dir = tmp_path / "backups"
    backup_path = backup_dir / "na-backup.db"
    _seed_and_back_up(db_path, backup_path)
    before = backup_path.read_bytes()
    backup_dir.chmod(0o555)  # no -wal or -shm can be created next to the backup
    try:
        result = CliRunner().invoke(
            cli,
            ["managed", "restore", "--db-path", str(db_path), "--backup", str(backup_path), "--yes"],
        )
    finally:
        backup_dir.chmod(0o755)
    assert result.exit_code == 0, result.output
    assert backup_path.read_bytes() == before
    assert sorted(p.name for p in backup_dir.iterdir()) == ["na-backup.db"]


def test_managed_restore_discards_the_replaced_databases_wal(tmp_path):
    """After an unclean stop, writes that exist only in the replaced database's
    WAL never reach the restored database (v1.0.2)."""
    db_path = tmp_path / "na.db"
    backup_path = tmp_path / "na-backup.db"
    _seed_and_back_up(db_path, backup_path)
    _crash_after_wal_write(db_path, "after_backup")
    assert (tmp_path / "na.db-wal").stat().st_size > 0

    result = CliRunner().invoke(
        cli,
        ["managed", "restore", "--db-path", str(db_path), "--backup", str(backup_path), "--yes"],
    )

    assert result.exit_code == 0, result.output
    assert _event_types(db_path) == ["in_backup"]


def test_managed_pre_restore_backup_keeps_writes_still_in_the_wal(tmp_path):
    """The pre-restore copy includes writes not yet checkpointed into the
    database file, which a plain file copy would lose (v1.0.2)."""
    db_path = tmp_path / "na.db"
    backup_path = tmp_path / "na-backup.db"
    pre_restore_path = tmp_path / "pre-restore.db"
    _seed_and_back_up(db_path, backup_path)
    _crash_after_wal_write(db_path, "after_backup")

    result = CliRunner().invoke(
        cli,
        [
            "managed", "restore", "--db-path", str(db_path), "--backup", str(backup_path),
            "--pre-restore-backup", str(pre_restore_path), "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert _event_types(pre_restore_path) == ["in_backup", "after_backup"]
    assert _event_types(db_path) == ["in_backup"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_managed_restore_keeps_the_database_mode(tmp_path):
    """A restore replaces the contents only: a group-writable database stays
    group-writable even from a 0444 backup (v1.0.2)."""
    db_path = tmp_path / "na.db"
    backup_path = tmp_path / "backups" / "na-backup.db"
    _seed_and_back_up(db_path, backup_path)
    db_path.chmod(0o664)
    backup_path.chmod(0o444)
    try:
        result = CliRunner().invoke(
            cli,
            ["managed", "restore", "--db-path", str(db_path), "--backup", str(backup_path), "--yes"],
        )
    finally:
        backup_path.chmod(0o644)
    assert result.exit_code == 0, result.output
    assert stat.S_IMODE(db_path.stat().st_mode) == 0o664
    assert _event_types(db_path) == ["in_backup"]


def _seed_and_back_up(db_path, backup_path):
    db = NADatabase(str(db_path))
    try:
        db.migrate()
        db.add_audit_event("in_backup", {})
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        db.backup(str(backup_path))
    finally:
        db.conn.close()


def _crash_after_wal_write(db_path, event_type):
    """Commit one audit event in WAL mode and exit without closing, as a crash
    would: the write is in na.db-wal only, never checkpointed."""
    event = json.dumps({"event_id": event_type, "event_type": event_type, "details": {},
                        "created_at": "2999-01-01T00:00:00+00:00"})
    code = (
        "import os, sqlite3, sys\n"
        "conn = sqlite3.connect(sys.argv[1])\n"
        "conn.execute('PRAGMA journal_mode = WAL')\n"
        "conn.execute('PRAGMA wal_autocheckpoint = 0')\n"
        "conn.execute('INSERT INTO audit_events (event_id, event_json, created_at) VALUES (?, ?, ?)',\n"
        "             (sys.argv[2], sys.argv[3], '2999-01-01T00:00:00+00:00'))\n"
        "conn.commit()\n"
        "os._exit(0)\n"
    )
    subprocess.run([sys.executable, "-c", code, str(db_path), event_type, event], check=True)


def _event_types(db_path):
    db = NADatabase(str(db_path))
    try:
        return [event["event_type"] for event in db.list_audit_events()]
    finally:
        db.conn.close()


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
    genesis.signatures.append(sign_model(genesis, na_key, "managed-test-root"))
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
