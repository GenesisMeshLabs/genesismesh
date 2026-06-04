"""Sovereign trust, treaty, attestation, and revocation-feed persistence."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from ..models import (
    MembershipAttestation,
    RecognitionPolicy,
    RecognitionTreaty,
    SovereignRevocationFeed,
)


class TrustStoreMixin:
    """Persistence methods for cross-sovereign trust state."""

    conn: sqlite3.Connection

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
    def get_latest_sovereign_revocation_sequence(
        self,
        issuer_sovereign_id: str,
    ) -> int | None:
        """Return the latest imported revocation feed sequence for an issuer."""
        row = self.conn.execute(
            """
            SELECT MAX(sequence) AS latest_sequence
            FROM sovereign_revocation_feeds
            WHERE issuer_sovereign_id = ?
            """,
            (issuer_sovereign_id,),
        ).fetchone()
        if not row or row["latest_sequence"] is None:
            return None
        return int(row["latest_sequence"])
    def save_sovereign_revocation_feed(self, feed: SovereignRevocationFeed) -> None:
        """Persist an imported sovereign revocation feed and its revoked IDs."""
        latest = self.get_latest_sovereign_revocation_sequence(feed.issuer_sovereign_id)
        if latest is not None and feed.sequence <= latest:
            raise ValueError("stale_sequence")

        imported_at = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO sovereign_revocation_feeds(
                    feed_id, issuer_sovereign_id, sequence, feed_json, imported_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    feed.feed_id,
                    feed.issuer_sovereign_id,
                    feed.sequence,
                    feed.model_dump_json(),
                    imported_at,
                ),
            )
            for attestation_id in feed.revoked_attestation_ids:
                self.conn.execute(
                    """
                    INSERT INTO imported_sovereign_revocations(
                        issuer_sovereign_id, attestation_id, feed_id,
                        sequence, reason, imported_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(issuer_sovereign_id, attestation_id) DO UPDATE SET
                        feed_id = excluded.feed_id,
                        sequence = excluded.sequence,
                        reason = excluded.reason,
                        imported_at = excluded.imported_at
                    """,
                    (
                        feed.issuer_sovereign_id,
                        attestation_id,
                        feed.feed_id,
                        feed.sequence,
                        feed.revocation_reasons.get(attestation_id),
                        imported_at,
                    ),
                )
    def list_sovereign_revocation_feeds(
        self,
        issuer_sovereign_id: str | None = None,
    ) -> list[dict]:
        """Return imported sovereign revocation feeds."""
        clauses: list[str] = []
        params: list[str] = []
        if issuer_sovereign_id:
            clauses.append("issuer_sovereign_id = ?")
            params.append(issuer_sovereign_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT feed_json, imported_at
            FROM sovereign_revocation_feeds
            {where}
            ORDER BY issuer_sovereign_id ASC, sequence ASC
            """,
            params,
        ).fetchall()
        return [
            {
                "feed": SovereignRevocationFeed.model_validate_json(row["feed_json"]),
                "imported_at": row["imported_at"],
            }
            for row in rows
        ]
    def get_imported_revoked_attestation_ids(self, issuer_sovereign_id: str) -> set[str]:
        """Return attestation IDs revoked by imported feeds for an issuer."""
        rows = self.conn.execute(
            """
            SELECT attestation_id
            FROM imported_sovereign_revocations
            WHERE issuer_sovereign_id = ?
            """,
            (issuer_sovereign_id,),
        ).fetchall()
        return {row["attestation_id"] for row in rows}
    def list_imported_sovereign_revocations(self) -> list[dict]:
        """Return imported revoked attestation IDs for graph export and diagnostics."""
        rows = self.conn.execute(
            """
            SELECT issuer_sovereign_id, attestation_id, feed_id,
                   sequence, reason, imported_at
            FROM imported_sovereign_revocations
            ORDER BY issuer_sovereign_id ASC, attestation_id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]
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
        revoked_trust_material.extend(
            {
                "type": "membership_attestation",
                "id": row["attestation_id"],
                "issuer_sovereign_id": row["issuer_sovereign_id"],
                "feed_id": row["feed_id"],
                "sequence": row["sequence"],
                "reason": row["reason"],
                "revoked_at": row["imported_at"],
            }
            for row in self.list_imported_sovereign_revocations()
        )
        return {
            "sovereigns": sovereigns,
            "recognition_edges": edges,
            "active_treaties": [
                json.loads(treaty.model_dump_json()) for treaty in active_treaties
            ],
            "revoked_trust_material": revoked_trust_material,
        }
