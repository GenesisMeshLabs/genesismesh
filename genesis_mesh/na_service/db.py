"""SQLite persistence for the Network Authority service."""

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import uuid

from ..models import InviteToken, JoinCertificate, PolicyManifest
from ..models.revocation import CertificateRevocationList, RevokedCertificate


MIGRATIONS_DIR = Path(__file__).with_name("migrations")
logger = logging.getLogger(__name__)


class NADatabase:
    """Small SQLite repository for NA state."""

    def __init__(self, db_path: str):
        """Open the SQLite database and configure connection-level pragmas."""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        try:
            self.conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError as exc:
            logger.warning("Could not enable SQLite WAL mode: %s", exc)

    def migrate(self) -> None:
        """Apply numbered SQL migrations transactionally."""
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {
            row["version"]
            for row in self.conn.execute("SELECT version FROM schema_version")
        }

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = int(path.stem.split("_", 1)[0])
            if version in applied:
                continue

            sql = path.read_text(encoding="utf-8")
            with self.conn:
                self.conn.executescript(sql)
                self.conn.execute(
                    "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (?, ?)",
                    (version, datetime.now(timezone.utc).isoformat()),
                )

    def create_invite_token(
        self,
        assigned_roles: list[str],
        max_validity_hours: int,
        token_expiry_hours: int,
    ) -> InviteToken:
        """Create and persist a single-use invite token."""
        now = datetime.now(timezone.utc)
        token = InviteToken(
            token_id=str(uuid.uuid4()),
            assigned_roles=assigned_roles,
            max_validity_hours=max_validity_hours,
            created_at=now,
            expires_at=now + timedelta(hours=token_expiry_hours),
        )
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO invite_tokens (
                    token_id, assigned_roles_json, max_validity_hours,
                    created_at, expires_at, used_at, used_by_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token.token_id,
                    json.dumps(token.assigned_roles),
                    token.max_validity_hours,
                    token.created_at.isoformat(),
                    token.expires_at.isoformat(),
                    None,
                    None,
                ),
            )
        return token

    def use_invite_token(self, token_id: str, node_key: str) -> Optional[InviteToken]:
        """Atomically mark an unused, unexpired token as used."""
        now = datetime.now(timezone.utc)
        with self._lock:
            with self.conn:
                row = self.conn.execute(
                    "SELECT * FROM invite_tokens WHERE token_id = ?",
                    (token_id,),
                ).fetchone()
                if not row:
                    return None

                token = self._invite_from_row(row)
                if token.used_at or token.expires_at < now:
                    return None

                updated = self.conn.execute(
                    """
                    UPDATE invite_tokens
                    SET used_at = ?, used_by_key = ?
                    WHERE token_id = ? AND used_at IS NULL
                    """,
                    (now.isoformat(), node_key, token_id),
                ).rowcount
                if updated != 1:
                    return None

        return token.model_copy(update={"used_at": now, "used_by_key": node_key})

    def issue_cert(
        self,
        cert: JoinCertificate,
        remote_addr: str,
        renewed_from: Optional[str] = None,
    ) -> None:
        """Persist an issued certificate and its initial node state."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO issued_certs (
                    cert_id, node_public_key, cert_json, roles_json,
                    issued_at, expires_at, remote_addr, status, last_heartbeat,
                    heartbeat_status, renewed_from
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cert.cert_id,
                    cert.node_public_key,
                    cert.model_dump_json(),
                    json.dumps(cert.roles),
                    cert.issued_at.isoformat(),
                    cert.expires_at.isoformat(),
                    remote_addr,
                    "issued",
                    datetime.now(timezone.utc).isoformat(),
                    "joined",
                    renewed_from,
                ),
            )

    def get_cert(self, cert_id: str) -> Optional[dict]:
        """Return a persisted certificate row by certificate ID."""
        row = self.conn.execute(
            "SELECT * FROM issued_certs WHERE cert_id = ?",
            (cert_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_certs_by_node_key(self, node_public_key: str) -> list[dict]:
        """Return all persisted certificate rows for a node public key."""
        rows = self.conn.execute(
            "SELECT * FROM issued_certs WHERE node_public_key = ?",
            (node_public_key,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_issued_certs(self) -> list[dict]:
        """Return all persisted certificate rows ordered by latest activity."""
        rows = self.conn.execute(
            """
            SELECT * FROM issued_certs
            ORDER BY COALESCE(last_heartbeat, issued_at) DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_heartbeat(self, cert_id: str, status: str, remote_addr: str) -> None:
        """Record the latest heartbeat details for an issued certificate."""
        with self.conn:
            self.conn.execute(
                """
                UPDATE issued_certs
                SET last_heartbeat = ?, heartbeat_status = ?, remote_addr = ?
                WHERE cert_id = ?
                """,
                (datetime.now(timezone.utc).isoformat(), status, remote_addr, cert_id),
            )

    def add_nonce(self, scope: str, nonce: str, created_at: datetime) -> None:
        """Persist a nonce inside a scoped replay-protection namespace."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO nonces(scope, nonce, created_at) VALUES (?, ?, ?)",
                (scope, nonce, created_at.isoformat()),
            )

    def has_nonce(self, scope: str, nonce: str) -> bool:
        """Return whether a nonce has already been used in a scope."""
        row = self.conn.execute(
            "SELECT 1 FROM nonces WHERE scope = ? AND nonce = ?",
            (scope, nonce),
        ).fetchone()
        return row is not None

    def cleanup_expired_nonces(self, max_age_secs: int) -> None:
        """Delete nonce records older than the configured replay window."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_secs)
        with self.conn:
            self.conn.execute(
                "DELETE FROM nonces WHERE created_at < ?",
                (cutoff.isoformat(),),
            )

    def save_crl(self, crl: CertificateRevocationList, active: bool = True) -> None:
        """Persist a CRL version and optionally make it the active CRL."""
        with self.conn:
            if active:
                self.conn.execute("UPDATE crl_versions SET active = 0")
            self.conn.execute(
                """
                INSERT OR REPLACE INTO crl_versions(sequence, crl_json, active, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    crl.sequence,
                    crl.model_dump_json(),
                    1 if active else 0,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get_active_crl(self) -> Optional[CertificateRevocationList]:
        """Return the currently active CRL, if one exists."""
        row = self.conn.execute(
            "SELECT crl_json FROM crl_versions WHERE active = 1 ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        return CertificateRevocationList.model_validate_json(row["crl_json"]) if row else None

    def revoke_cert(
        self,
        cert_id: str,
        reason: str,
        issuer: str,
    ) -> CertificateRevocationList:
        """Mark a certificate as revoked and return the next unsigned CRL."""
        cert = self.get_cert(cert_id)
        if not cert:
            raise KeyError(f"Unknown certificate: {cert_id}")

        current = self.get_active_crl()
        if current is None:
            current = CertificateRevocationList.create_empty(issuer=issuer, sequence=0)

        revoked_ids = {rc.certificate_id for rc in current.revoked_certificates}
        if cert_id in revoked_ids:
            return current

        revoked = RevokedCertificate(
            certificate_id=cert_id,
            revoked_at=datetime.now(timezone.utc),
            reason=reason,
            issuer=issuer,
        )
        crl = CertificateRevocationList(
            crl_id=str(uuid.uuid4()),
            sequence=current.sequence + 1,
            issued_at=datetime.now(timezone.utc),
            next_update=datetime.now(timezone.utc) + timedelta(hours=24),
            issuer=current.issuer,
            revoked_certificates=current.revoked_certificates + [revoked],
            signatures=[],
        )

        with self.conn:
            self.conn.execute(
                """
                UPDATE issued_certs
                SET status = 'revoked', revoked_at = ?, revocation_reason = ?
                WHERE cert_id = ?
                """,
                (revoked.revoked_at.isoformat(), reason, cert_id),
            )
        return crl

    def save_policy(self, policy: PolicyManifest, active: bool = True) -> None:
        """Persist a policy version and optionally make it active."""
        with self.conn:
            if active:
                self.conn.execute("UPDATE policy_versions SET active = 0")
            self.conn.execute(
                """
                INSERT OR REPLACE INTO policy_versions(policy_id, policy_json, active, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    policy.policy_id,
                    policy.model_dump_json(),
                    1 if active else 0,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get_active_policy(self) -> Optional[PolicyManifest]:
        """Return the currently active policy, if one exists."""
        row = self.conn.execute(
            "SELECT policy_json FROM policy_versions WHERE active = 1 LIMIT 1"
        ).fetchone()
        return PolicyManifest.model_validate_json(row["policy_json"]) if row else None

    def list_policy_versions(self) -> list[dict]:
        """Return all persisted policy versions with active flags."""
        rows = self.conn.execute(
            """
            SELECT policy_id, policy_json, active, created_at
            FROM policy_versions
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def activate_policy(self, policy_id: str) -> bool:
        """Make an existing policy version active."""
        with self.conn:
            exists = self.conn.execute(
                "SELECT 1 FROM policy_versions WHERE policy_id = ?",
                (policy_id,),
            ).fetchone()
            if not exists:
                return False
            self.conn.execute("UPDATE policy_versions SET active = 0")
            self.conn.execute(
                "UPDATE policy_versions SET active = 1 WHERE policy_id = ?",
                (policy_id,),
            )
        return True

    def backup(self, dest_path: str) -> None:
        """Copy the live SQLite database to a destination path."""
        dest = sqlite3.connect(dest_path)
        try:
            self.conn.backup(dest)
        finally:
            dest.close()

    def add_audit_event(self, event_type: str, details: dict) -> str:
        """Persist a lightweight Network Authority audit event."""
        event_id = str(uuid.uuid4())
        payload = {
            "event_id": event_id,
            "event_type": event_type,
            "details": details,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO audit_events(event_id, event_json, created_at)
                VALUES (?, ?, ?)
                """,
                (event_id, json.dumps(payload, sort_keys=True), payload["created_at"]),
            )
        return event_id

    def list_audit_events(self) -> list[dict]:
        """Return persisted Network Authority audit events in insertion order."""
        rows = self.conn.execute(
            "SELECT event_json FROM audit_events ORDER BY created_at ASC"
        ).fetchall()
        return [json.loads(row["event_json"]) for row in rows]

    def _invite_from_row(self, row: sqlite3.Row) -> InviteToken:
        """Convert an `invite_tokens` row into an `InviteToken` model."""
        return InviteToken(
            token_id=row["token_id"],
            assigned_roles=json.loads(row["assigned_roles_json"]),
            max_validity_hours=row["max_validity_hours"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            used_at=datetime.fromisoformat(row["used_at"]) if row["used_at"] else None,
            used_by_key=row["used_by_key"],
        )
