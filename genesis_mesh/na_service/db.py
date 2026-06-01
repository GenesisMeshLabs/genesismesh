"""SQLite persistence for the Network Authority service."""

import json
import logging
import math
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import uuid

from ..models import (
    AgentDescriptor,
    AgentEndpoint,
    InviteToken,
    JoinCertificate,
    MembershipAttestation,
    PolicyManifest,
    RecognitionPolicy,
    RecognitionTreaty,
)
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

    # -- Sovereign trust / attestations --------------------------------------

    def save_membership_attestation(
        self,
        attestation: MembershipAttestation,
        status: str = "active",
    ) -> None:
        """Persist a signed membership attestation."""
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO membership_attestations(
                    attestation_id, issuer_sovereign_id, subject_id,
                    subject_public_key, roles_json, status, attestation_json,
                    issued_at, valid_from, expires_at, revoked_at,
                    revocation_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    attestation.attestation_id,
                    attestation.issuer_sovereign_id,
                    attestation.subject_id,
                    attestation.subject_public_key,
                    json.dumps(attestation.roles, sort_keys=True),
                    status,
                    attestation.model_dump_json(),
                    attestation.issued_at.isoformat(),
                    attestation.valid_from.isoformat(),
                    attestation.expires_at.isoformat(),
                ),
            )

    def get_membership_attestation(self, attestation_id: str) -> dict | None:
        """Return a persisted attestation row and signed model, if present."""
        row = self.conn.execute(
            """
            SELECT attestation_json, status, revoked_at, revocation_reason
            FROM membership_attestations
            WHERE attestation_id = ?
            """,
            (attestation_id,),
        ).fetchone()
        if not row:
            return None
        attestation = MembershipAttestation.model_validate_json(row["attestation_json"])
        return {
            "attestation": attestation,
            "status": row["status"],
            "revoked_at": row["revoked_at"],
            "revocation_reason": row["revocation_reason"],
        }

    def list_membership_attestations(
        self,
        issuer_sovereign_id: str | None = None,
        subject_id: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        """Return persisted attestation rows filtered by issuer, subject, or status."""
        clauses: list[str] = []
        params: list[str] = []
        if issuer_sovereign_id:
            clauses.append("issuer_sovereign_id = ?")
            params.append(issuer_sovereign_id)
        if subject_id:
            clauses.append("subject_id = ?")
            params.append(subject_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT attestation_json, status, revoked_at, revocation_reason
            FROM membership_attestations
            {where}
            ORDER BY issued_at ASC
            """,
            params,
        ).fetchall()
        return [
            {
                "attestation": MembershipAttestation.model_validate_json(row["attestation_json"]),
                "status": row["status"],
                "revoked_at": row["revoked_at"],
                "revocation_reason": row["revocation_reason"],
            }
            for row in rows
        ]

    def revoke_membership_attestation(
        self,
        attestation_id: str,
        reason: str = "unspecified",
    ) -> bool:
        """Mark a persisted attestation revoked without modifying signed JSON."""
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE membership_attestations
                SET status = 'revoked', revoked_at = ?, revocation_reason = ?
                WHERE attestation_id = ?
                """,
                (now, reason, attestation_id),
            )
        return cursor.rowcount > 0

    def save_recognition_policy(
        self,
        policy_id: str,
        policy: RecognitionPolicy,
        active: bool = True,
    ) -> None:
        """Persist a local recognition policy and optionally activate it."""
        with self.conn:
            if active:
                self.conn.execute("UPDATE recognition_policies SET active = 0")
            self.conn.execute(
                """
                INSERT OR REPLACE INTO recognition_policies(
                    policy_id, policy_json, active, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    policy_id,
                    policy.model_dump_json(),
                    1 if active else 0,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get_active_recognition_policy(self) -> RecognitionPolicy | None:
        """Return the active recognition policy, if one is configured."""
        row = self.conn.execute(
            "SELECT policy_json FROM recognition_policies WHERE active = 1 LIMIT 1"
        ).fetchone()
        return RecognitionPolicy.model_validate_json(row["policy_json"]) if row else None

    def save_recognition_treaty(
        self,
        treaty: RecognitionTreaty,
        status: str = "active",
    ) -> None:
        """Persist a signed recognition treaty."""
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO recognition_treaties(
                    treaty_id, issuer_sovereign_id, subject_sovereign_id,
                    status, treaty_json, issued_at, valid_from, expires_at,
                    revoked_at, revocation_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    treaty.treaty_id,
                    treaty.issuer_sovereign_id,
                    treaty.subject_sovereign_id,
                    status,
                    treaty.model_dump_json(),
                    treaty.issued_at.isoformat(),
                    treaty.valid_from.isoformat(),
                    treaty.expires_at.isoformat(),
                ),
            )

    def get_recognition_treaty(self, treaty_id: str) -> dict | None:
        """Return a persisted recognition treaty row and signed model, if present."""
        row = self.conn.execute(
            """
            SELECT treaty_json, status, revoked_at, revocation_reason
            FROM recognition_treaties
            WHERE treaty_id = ?
            """,
            (treaty_id,),
        ).fetchone()
        if not row:
            return None
        treaty = RecognitionTreaty.model_validate_json(row["treaty_json"])
        return {
            "treaty": treaty,
            "status": row["status"],
            "revoked_at": row["revoked_at"],
            "revocation_reason": row["revocation_reason"],
        }

    def list_recognition_treaties(
        self,
        issuer_sovereign_id: str | None = None,
        subject_sovereign_id: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        """Return persisted treaty rows filtered by issuer, subject, or status."""
        clauses: list[str] = []
        params: list[str] = []
        if issuer_sovereign_id:
            clauses.append("issuer_sovereign_id = ?")
            params.append(issuer_sovereign_id)
        if subject_sovereign_id:
            clauses.append("subject_sovereign_id = ?")
            params.append(subject_sovereign_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT treaty_json, status, revoked_at, revocation_reason
            FROM recognition_treaties
            {where}
            ORDER BY issued_at ASC
            """,
            params,
        ).fetchall()
        return [
            {
                "treaty": RecognitionTreaty.model_validate_json(row["treaty_json"]),
                "status": row["status"],
                "revoked_at": row["revoked_at"],
                "revocation_reason": row["revocation_reason"],
            }
            for row in rows
        ]

    def revoke_recognition_treaty(
        self,
        treaty_id: str,
        reason: str = "unspecified",
    ) -> bool:
        """Mark a persisted recognition treaty revoked without modifying signed JSON."""
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE recognition_treaties
                SET status = 'revoked', revoked_at = ?, revocation_reason = ?
                WHERE treaty_id = ?
                """,
                (now, reason, treaty_id),
            )
        return cursor.rowcount > 0

    def export_recognition_graph(self) -> dict:
        """Return a minimal recognition graph for external viewers."""
        treaty_rows = self.list_recognition_treaties()
        sovereign_ids = {
            treaty_row["treaty"].issuer_sovereign_id
            for treaty_row in treaty_rows
        } | {
            treaty_row["treaty"].subject_sovereign_id
            for treaty_row in treaty_rows
        }
        sovereigns = [
            {"sovereign_id": sovereign_id}
            for sovereign_id in sorted(sovereign_ids)
        ]
        edges = [
            {
                "from": treaty_row["treaty"].issuer_sovereign_id,
                "to": treaty_row["treaty"].subject_sovereign_id,
                "treaty_id": treaty_row["treaty"].treaty_id,
                "status": treaty_row["status"],
                "valid_from": treaty_row["treaty"].valid_from.isoformat(),
                "expires_at": treaty_row["treaty"].expires_at.isoformat(),
            }
            for treaty_row in treaty_rows
        ]
        active_treaties = [
            treaty_row["treaty"]
            for treaty_row in treaty_rows
            if treaty_row["status"] == "active"
        ]
        revoked_trust_material = [
            {
                "type": "recognition_treaty",
                "id": treaty_row["treaty"].treaty_id,
                "reason": treaty_row["revocation_reason"],
                "revoked_at": treaty_row["revoked_at"],
            }
            for treaty_row in treaty_rows
            if treaty_row["status"] == "revoked"
        ]
        return {
            "sovereigns": sovereigns,
            "recognition_edges": edges,
            "active_treaties": [
                json.loads(treaty.model_dump_json()) for treaty in active_treaties
            ],
            "revoked_trust_material": revoked_trust_material,
        }

    # -- Agent discovery / service registry ---------------------------------

    def upsert_agent_registration(self, descriptor: AgentDescriptor) -> None:
        """Persist a signed agent descriptor; existing row for the same node key is replaced."""
        capabilities_csv = ",".join(sorted(set(descriptor.capabilities)))
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO agent_registrations(
                    node_public_key, agent_id, network_name, capabilities_csv,
                    endpoint_host, endpoint_port, endpoint_scheme,
                    descriptor_json, registered_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(node_public_key) DO UPDATE SET
                    agent_id         = excluded.agent_id,
                    network_name     = excluded.network_name,
                    capabilities_csv = excluded.capabilities_csv,
                    endpoint_host    = excluded.endpoint_host,
                    endpoint_port    = excluded.endpoint_port,
                    endpoint_scheme  = excluded.endpoint_scheme,
                    descriptor_json  = excluded.descriptor_json,
                    registered_at    = excluded.registered_at,
                    expires_at       = excluded.expires_at
                """,
                (
                    descriptor.node_public_key,
                    descriptor.agent_id,
                    descriptor.network_name,
                    capabilities_csv,
                    descriptor.endpoint.host,
                    descriptor.endpoint.port,
                    descriptor.endpoint.scheme,
                    descriptor.model_dump_json(),
                    descriptor.registered_at.isoformat(),
                    descriptor.expires_at.isoformat(),
                ),
            )

    def delete_agent_registration(self, node_public_key: str) -> bool:
        """Remove a registration. Returns True iff a row was deleted."""
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM agent_registrations WHERE node_public_key = ?",
                (node_public_key,),
            )
            return cur.rowcount > 0

    def cleanup_expired_agent_registrations(
        self,
        current_time: Optional[datetime] = None,
    ) -> int:
        """Drop registrations whose TTL has passed. Returns the row count removed."""
        now = (current_time or datetime.now(timezone.utc)).isoformat()
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM agent_registrations WHERE expires_at <= ?",
                (now,),
            )
            return cur.rowcount

    def evict_agent_registrations_for_revoked_keys(self, revoked_keys: list[str]) -> int:
        """Remove any registrations belonging to revoked node keys."""
        if not revoked_keys:
            return 0
        placeholders = ",".join("?" for _ in revoked_keys)
        with self.conn:
            cur = self.conn.execute(
                f"DELETE FROM agent_registrations WHERE node_public_key IN ({placeholders})",
                revoked_keys,
            )
            return cur.rowcount

    def get_agent_registration(self, node_public_key: str) -> Optional[AgentDescriptor]:
        """Return one registration, or None if missing or expired."""
        self.cleanup_expired_agent_registrations()
        row = self.conn.execute(
            "SELECT descriptor_json FROM agent_registrations WHERE node_public_key = ?",
            (node_public_key,),
        ).fetchone()
        if row is None:
            return None
        return AgentDescriptor.model_validate_json(row["descriptor_json"])

    def list_agent_registrations(
        self,
        capability: Optional[str] = None,
    ) -> list[AgentDescriptor]:
        """Return all live registrations, optionally filtered by capability tag."""
        self.cleanup_expired_agent_registrations()
        if capability:
            rows = self.conn.execute(
                "SELECT descriptor_json FROM agent_registrations "
                "WHERE ',' || capabilities_csv || ',' LIKE ? "
                "ORDER BY registered_at DESC",
                (f"%,{capability},%",),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT descriptor_json FROM agent_registrations ORDER BY registered_at DESC"
            ).fetchall()
        return [AgentDescriptor.model_validate_json(r["descriptor_json"]) for r in rows]

    # -----------------------------------------------------------------------

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
