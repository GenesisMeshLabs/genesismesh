"""SQLite to PostgreSQL migration and database verification for the NA (v0.60).

``migrate_sqlite_to_postgres`` copies every table of a v0.60 SQLite database
into an empty PostgreSQL database at the same schema version, preserving
identifiers, sequences and timestamps, then proves nothing was lost or
changed: per-table row counts and content digests must match, and the target
must pass ``verify_database``. The SQLite file is opened read-only and is
never modified, so rollback is "keep using the file".

``verify_database`` checks what the NA relies on, on either backend:

* every boundary policy row parses and matches its stored digest;
* CRL sequences are gap-free and the highest one is the only active one;
* the evidence store is one hash chain (entry and payload digests, previous
  entry links, gap-free sequences after the latest retention checkpoint), and
  with the NA public key, every signature verifies.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..models.evidence_store import EvidenceEvent, EvidenceStoreEntry, payload_digest
from ..models.revocation import CertificateRevocationList
from ..na_service.db import NADatabase, expected_schema_version
from ..trust.evidence_store import (
    EvidenceVerification,
    check_events_against_anchors,
    verify_evidence_events,
    verify_store_anchors,
)

#: Runtime-only tables: recreated empty on the target, never copied.
RUNTIME_TABLES = frozenset({"rate_limit_windows", "job_leases"})
#: Copied rows per INSERT batch.
BATCH = 500


class MigrationError(RuntimeError):
    """The migration was refused or did not verify. The target must not be used."""


@dataclass
class VerificationReport:
    ok: bool = True
    checks: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.ok = False
        self.failures.append(message)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "checks": self.checks, "failures": self.failures}


# ── verification ──────────────────────────────────────────────────────────────


def _verify_boundary_policies(db: NADatabase, report: VerificationReport) -> None:
    rows = db.list_boundary_policy_rows()
    bad = [f"{r['policy_id']}@{r['version']}" for r in rows if db.parse_boundary_policy_row(r) is None]
    report.checks["boundary_policies"] = {"versions": len(rows), "integrity_failures": bad}
    if bad:
        report.fail(f"boundary policies fail their digest check: {', '.join(bad)}")


def _verify_crl(db: NADatabase, report: VerificationReport) -> None:
    rows = db.conn.execute("SELECT sequence, active, crl_json FROM crl_versions ORDER BY sequence").fetchall()
    sequences = [int(r["sequence"]) for r in rows]
    active = [int(r["sequence"]) for r in rows if int(r["active"]) == 1]
    report.checks["crl"] = {"versions": len(rows), "active_sequence": active[0] if len(active) == 1 else active}
    if not rows:
        return
    if sequences != list(range(sequences[0], sequences[0] + len(sequences))):
        report.fail("CRL sequences have gaps")
    if active != [sequences[-1]]:
        report.fail("the active CRL is not exactly the highest sequence")
    for r in rows:
        crl = CertificateRevocationList.model_validate_json(r["crl_json"])
        if crl.sequence != int(r["sequence"]):
            report.fail(f"CRL row {r['sequence']} holds sequence {crl.sequence}")


def _verify_evidence(db: NADatabase, report: VerificationReport, na_public_key: Optional[str]) -> None:
    stored = db.search_evidence({}, limit=10**9)
    checkpoint = db.latest_retention_checkpoint()
    info: dict[str, Any] = {"entries": len(stored), "signatures_checked": na_public_key is not None}
    report.checks["evidence"] = info
    _verify_anchors(db, report, stored, na_public_key)
    if not stored:
        return
    expected_seq = checkpoint.removed_through_sequence + 1 if checkpoint else 1
    prev_digest = checkpoint.last_removed_entry_digest if checkpoint else None
    for s in stored:
        entry: EvidenceStoreEntry = s["entry"]
        if entry.store_sequence != expected_seq:
            report.fail(f"evidence store sequence {entry.store_sequence}, expected {expected_seq}")
            return
        if entry.digest() != s["entry_digest"]:
            report.fail(f"evidence entry {entry.store_sequence} digest mismatch")
        if payload_digest(s["payload"]) != entry.payload_digest:
            report.fail(f"evidence entry {entry.store_sequence} payload digest mismatch")
        if entry.prev_entry_digest != prev_digest:
            report.fail(f"evidence entry {entry.store_sequence} does not link to its predecessor")
        prev_digest = entry.digest()
        expected_seq += 1
    if na_public_key:
        from ..na_service.services.evidence_store import EvidenceStoreService

        # v1.3.0: keys with their role (observer keys sign observations only).
        keys = {r["key_id"]: EvidenceStoreService.key_from_row(r) for r in db.list_executor_keys()}
        events = [EvidenceEvent(entry=s["entry"], entry_digest=s["entry_digest"], payload=s["payload"]) for s in stored]
        result = verify_evidence_events(
            events, na_public_keys=[na_public_key], executor_keys=keys, contiguous=True, checkpoint=checkpoint
        )
        info["signature_failures"] = result.failures
        if not result.verified:
            report.fail(f"evidence store verification failed: {len(result.failures)} failure(s)")


def _verify_anchors(
    db: NADatabase, report: VerificationReport, stored: list[dict[str, Any]], na_public_key: Optional[str]
) -> None:
    """Store anchors (v1.2.0): an unbroken chain naming the stored entries' digests."""
    anchors = db.list_store_anchors(limit=10**9)
    info: dict[str, Any] = {"anchors": len(anchors)}
    report.checks["evidence_anchors"] = info
    if not anchors:
        return
    chain = verify_store_anchors(anchors, na_public_keys=[na_public_key] if na_public_key else None)
    info["chain"] = chain.to_dict()
    if not chain.verified:
        report.fail("store anchors fail verification: "
                    + ", ".join(f"#{f['anchor_sequence']} {f['reason']}" for f in chain.failures[:5]))
    events = [EvidenceEvent(entry=s["entry"], entry_digest=s["entry_digest"], payload=s["payload"]) for s in stored]
    result = EvidenceVerification()
    check_events_against_anchors(events, anchors, result)
    info.update(result.anchors or {})
    if not result.verified:
        report.fail("evidence entries do not match their store anchors: "
                    + ", ".join(f"#{f['store_sequence']} {f['reason']}" for f in result.failures[:5]))


def verify_database(db: NADatabase, na_public_key: Optional[str] = None) -> VerificationReport:
    """Check the invariants the NA relies on (see module docstring)."""
    report = VerificationReport()
    version = db.schema_version()
    report.checks["schema_version"] = version
    if version != expected_schema_version():
        report.fail(f"schema version {version}, expected {expected_schema_version()}")
        return report
    _verify_boundary_policies(db, report)
    _verify_crl(db, report)
    _verify_evidence(db, report, na_public_key)
    report.checks["audit_events"] = int(db.conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
    return report


# ── migration ─────────────────────────────────────────────────────────────────


def _sqlite_readonly(path: str) -> sqlite3.Connection:
    if not Path(path).is_file():
        raise MigrationError(f"source database not found: {path}")
    conn = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(src: sqlite3.Connection, table: str) -> list[str]:
    return [str(r["name"]) for r in src.execute(f'PRAGMA table_info("{table}")')]


def _table_digest(rows: list[tuple[Any, ...]]) -> str:
    canonical = sorted(json.dumps(list(r), default=str, separators=(",", ":")) for r in rows)
    return hashlib.sha256("\n".join(canonical).encode("utf-8")).hexdigest()


def _select_all(conn: Any, table: str, columns: list[str]) -> list[tuple[Any, ...]]:
    cols = ", ".join(f'"{c}"' for c in columns)
    return [tuple(r) for r in conn.execute(f'SELECT {cols} FROM "{table}"').fetchall()]


def migrate_sqlite_to_postgres(
    sqlite_path: str,
    database_url: str,
    *,
    na_public_key: Optional[str] = None,
) -> dict[str, Any]:
    """Copy and verify; returns the migration report. Raises ``MigrationError`` on refusal or mismatch."""
    src = _sqlite_readonly(sqlite_path)
    try:
        src_version = int(src.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0)
        if src_version != expected_schema_version():
            raise MigrationError(
                f"source schema is version {src_version}; start this NA release on it once "
                f"(schema {expected_schema_version()}) before migrating"
            )
        tables = [
            str(r["name"]) for r in src.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        tables = [t for t in tables if t != "schema_version" and t not in RUNTIME_TABLES]

        target = NADatabase(database_url=database_url)
        try:
            if target.backend != "postgres":
                raise MigrationError("the target must be a postgresql:// database URL")
            target.migrate()
            for table in tables:
                if int(target.conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]):
                    raise MigrationError(f"target is not empty: table {table} has rows")

            copied: dict[str, dict[str, Any]] = {}
            with target.conn:
                for table in tables:
                    columns = _columns(src, table)
                    rows = _select_all(src, table, columns)
                    if rows:
                        cols = ", ".join(f'"{c}"' for c in columns)
                        marks = ", ".join("?" for _ in columns)
                        sql = f'INSERT INTO "{table}" ({cols}) VALUES ({marks})'
                        for start in range(0, len(rows), BATCH):
                            target.conn.executemany(sql, rows[start:start + BATCH])
                    copied[table] = {"rows": len(rows), "digest": _table_digest(rows)}

            mismatches = []
            for table in tables:
                columns = _columns(src, table)
                rows = _select_all(target.conn, table, columns)
                if len(rows) != copied[table]["rows"] or _table_digest(rows) != copied[table]["digest"]:
                    mismatches.append(table)
            if mismatches:
                raise MigrationError(f"copied tables do not match the source: {', '.join(mismatches)}")

            verification = verify_database(target, na_public_key)
            if not verification.ok:
                raise MigrationError("target failed verification: " + "; ".join(verification.failures))

            report = {
                "source": str(Path(sqlite_path).resolve()),
                "target": target.db_path,
                "schema_version": src_version,
                "tables": copied,
                "verification": verification.to_dict(),
                "migrated_at": datetime.now(timezone.utc).isoformat(),
            }
            target.add_audit_event("database_migrated", {
                "source": report["source"],
                "target": report["target"],
                "schema_version": src_version,
                "rows": {t: v["rows"] for t, v in copied.items()},
            })
            return report
        finally:
            target.close()
    finally:
        src.close()
