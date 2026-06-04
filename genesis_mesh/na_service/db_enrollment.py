"""Enrollment, certificate, invite, and replay persistence."""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import uuid

from ..models import InviteToken, JoinCertificate


class EnrollmentStoreMixin:
    """Persistence methods for node enrollment and certificate state."""

    conn: sqlite3.Connection
    _lock: Any

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
    def get_available_invite_token(self, token_id: str) -> Optional[InviteToken]:
        """Return an unused, unexpired invite token without consuming it."""
        now = datetime.now(timezone.utc)
        row = self.conn.execute(
            "SELECT * FROM invite_tokens WHERE token_id = ?",
            (token_id,),
        ).fetchone()
        if not row:
            return None
        token = self._invite_from_row(row)
        if token.used_at or token.expires_at < now:
            return None
        return token
    def issue_cert(
        self,
        cert: JoinCertificate,
        remote_addr: str,
        renewed_from: Optional[str] = None,
        max_validity_hours: Optional[int] = None,
    ) -> None:
        """Persist an issued certificate and its initial node state."""
        if max_validity_hours is None:
            validity_seconds = (cert.expires_at - cert.issued_at).total_seconds()
            max_validity_hours = max(1, math.ceil(validity_seconds / 3600))

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO issued_certs (
                    cert_id, node_public_key, cert_json, roles_json,
                    issued_at, expires_at, max_validity_hours, remote_addr, status,
                    last_heartbeat, heartbeat_status, renewed_from
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cert.cert_id,
                    cert.node_public_key,
                    cert.model_dump_json(),
                    json.dumps(cert.roles),
                    cert.issued_at.isoformat(),
                    cert.expires_at.isoformat(),
                    max_validity_hours,
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
