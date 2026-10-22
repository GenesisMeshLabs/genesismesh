"""Sovereign trust, treaty, attestation, and revocation-feed persistence."""

from __future__ import annotations

from typing import Any, Callable

import json
from datetime import datetime, timezone

from ..models import (
    MembershipAttestation,
    RecognitionPolicy,
    RecognitionTreaty,
    SovereignRevocationFeed,
)
from ..trust.treaty_lifecycle import is_lifecycle_active, treaty_lifecycle

# The status and lineage columns of an attestation or treaty row (v1.8.0).
_ROW_COLUMNS = "status, revoked_at, revocation_reason, lineage_id, reissued_from, superseded_by"

# How many times a lineage revocation re-checks for a copy that a concurrent
# re-issue committed. A copy can be re-issued only while active, so one more
# pass is enough; the rest is a margin.
LINEAGE_REVOCATION_PASSES = 5


def _row_fields(row: Any) -> dict:
    """The status and lineage fields of an attestation or treaty row."""
    return {
        "status": row["status"],
        "revoked_at": row["revoked_at"],
        "revocation_reason": row["revocation_reason"],
        "lineage_id": row["lineage_id"],
        "reissued_from": row["reissued_from"],
        "superseded_by": row["superseded_by"],
    }


class TrustStoreMixin:
    """Persistence methods for cross-sovereign trust state."""

    conn: Any

    def _insert_membership_attestation(
        self,
        attestation: MembershipAttestation,
        status: str,
        *,
        lineage_id: str | None = None,
        reissued_from: str | None = None,
        upsert: bool = True,
    ) -> None:
        """Write an attestation row inside the caller's transaction.

        A new row starts its own lineage unless it re-issues another. Saving
        an existing ID again replaces its content and keeps its lineage.
        """
        conflict = """
            ON CONFLICT(attestation_id) DO UPDATE SET
                issuer_sovereign_id = excluded.issuer_sovereign_id,
                subject_id = excluded.subject_id,
                subject_public_key = excluded.subject_public_key,
                roles_json = excluded.roles_json,
                status = excluded.status,
                attestation_json = excluded.attestation_json,
                issued_at = excluded.issued_at,
                valid_from = excluded.valid_from,
                expires_at = excluded.expires_at,
                revoked_at = NULL,
                revocation_reason = NULL
        """ if upsert else ""
        self.conn.execute(
            f"""
            INSERT INTO membership_attestations(
                attestation_id, issuer_sovereign_id, subject_id,
                subject_public_key, roles_json, status, attestation_json,
                issued_at, valid_from, expires_at, revoked_at,
                revocation_reason, lineage_id, reissued_from
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
            {conflict}
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
                lineage_id or attestation.attestation_id,
                reissued_from,
            ),
        )
    def save_membership_attestation(
        self,
        attestation: MembershipAttestation,
        status: str = "active",
    ) -> None:
        """Persist a signed membership attestation."""
        with self.conn:
            self._insert_membership_attestation(attestation, status)
    def reissue_membership_attestation(
        self,
        previous_id: str,
        attestation: MembershipAttestation,
    ) -> bool:
        """Store ``attestation`` as the re-issue of ``previous_id`` (v1.8.0).

        One transaction marks the previous copy superseded, if it is still
        active and not yet superseded, and inserts the new copy in its
        lineage. Returns False, storing nothing, when the previous copy was
        revoked, superseded or never stored: a revocation that wins the race
        is never undone by a re-issue under a new ID.
        """
        return self._reissue(
            "membership_attestations", "attestation_id", previous_id, attestation.attestation_id,
            lambda lineage_id: self._insert_membership_attestation(
                attestation, "active", lineage_id=lineage_id, reissued_from=previous_id, upsert=False),
        )
    def get_membership_attestation(self, attestation_id: str) -> dict | None:
        """Return a persisted attestation row and signed model, if present.

        The row is the one stored under this ID, superseded or not: a decision
        binds the ID it was given and is never resolved to a re-issue.
        """
        row = self.conn.execute(
            f"""
            SELECT attestation_json, {_ROW_COLUMNS}
            FROM membership_attestations
            WHERE attestation_id = ?
            """,
            (attestation_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "attestation": MembershipAttestation.model_validate_json(row["attestation_json"]),
            **_row_fields(row),
        }
    def list_membership_attestations(
        self,
        issuer_sovereign_id: str | None = None,
        subject_id: str | None = None,
        status: str | None = None,
        *,
        include_superseded: bool = False,
    ) -> list[dict]:
        """Return persisted attestation rows filtered by issuer, subject, or status.

        Only the newest copy of each lineage is listed unless
        ``include_superseded`` is set.
        """
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
        if not include_superseded:
            clauses.append("superseded_by IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT attestation_json, {_ROW_COLUMNS}
            FROM membership_attestations
            {where}
            ORDER BY issued_at ASC
            """,
            params,
        ).fetchall()
        return [
            {
                "attestation": MembershipAttestation.model_validate_json(row["attestation_json"]),
                **_row_fields(row),
            }
            for row in rows
        ]
    def membership_attestation_lineage(self, attestation_id: str) -> list[str]:
        """The IDs of every copy in an attestation's lineage, oldest first (none if unknown)."""
        return self._lineage_ids("membership_attestations", "attestation_id", attestation_id)
    def revoke_membership_attestation(
        self,
        attestation_id: str,
        reason: str = "unspecified",
    ) -> bool:
        """Mark a persisted attestation revoked without modifying signed JSON.

        Since 1.8.0 every copy in its lineage is revoked with it.
        """
        return bool(self.revoke_membership_attestation_lineage(attestation_id, reason))
    def revoke_membership_attestation_lineage(
        self,
        attestation_id: str,
        reason: str = "unspecified",
    ) -> list[str]:
        """Revoke an attestation and every copy in its lineage; return their IDs (v1.8.0)."""
        return self._revoke_lineage("membership_attestations", "attestation_id", attestation_id, reason)
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
                INSERT INTO recognition_policies(
                    policy_id, policy_json, active, created_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(policy_id) DO UPDATE SET
                    policy_json = excluded.policy_json,
                    active = excluded.active,
                    created_at = excluded.created_at
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
    def _insert_recognition_treaty(
        self,
        treaty: RecognitionTreaty,
        status: str,
        *,
        lineage_id: str | None = None,
        reissued_from: str | None = None,
        upsert: bool = True,
    ) -> None:
        """Write a treaty row inside the caller's transaction (see ``_insert_membership_attestation``)."""
        conflict = """
            ON CONFLICT(treaty_id) DO UPDATE SET
                issuer_sovereign_id = excluded.issuer_sovereign_id,
                subject_sovereign_id = excluded.subject_sovereign_id,
                status = excluded.status,
                treaty_json = excluded.treaty_json,
                issued_at = excluded.issued_at,
                valid_from = excluded.valid_from,
                expires_at = excluded.expires_at,
                revoked_at = NULL,
                revocation_reason = NULL
        """ if upsert else ""
        self.conn.execute(
            f"""
            INSERT INTO recognition_treaties(
                treaty_id, issuer_sovereign_id, subject_sovereign_id,
                status, treaty_json, issued_at, valid_from, expires_at,
                revoked_at, revocation_reason, lineage_id, reissued_from
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
            {conflict}
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
                lineage_id or treaty.treaty_id,
                reissued_from,
            ),
        )
    def save_recognition_treaty(
        self,
        treaty: RecognitionTreaty,
        status: str = "active",
    ) -> None:
        """Persist a signed recognition treaty."""
        with self.conn:
            self._insert_recognition_treaty(treaty, status)
    def reissue_recognition_treaty(
        self,
        previous_id: str,
        treaty: RecognitionTreaty,
    ) -> bool:
        """Store ``treaty`` as the re-issue of ``previous_id`` (v1.8.0; see
        ``reissue_membership_attestation``)."""
        return self._reissue(
            "recognition_treaties", "treaty_id", previous_id, treaty.treaty_id,
            lambda lineage_id: self._insert_recognition_treaty(
                treaty, "active", lineage_id=lineage_id, reissued_from=previous_id, upsert=False),
        )
    def get_recognition_treaty(self, treaty_id: str) -> dict | None:
        """Return a persisted recognition treaty row and signed model, if present.

        As for attestations, this is the row stored under this ID, superseded or not.
        """
        row = self.conn.execute(
            f"""
            SELECT treaty_json, {_ROW_COLUMNS}
            FROM recognition_treaties
            WHERE treaty_id = ?
            """,
            (treaty_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "treaty": RecognitionTreaty.model_validate_json(row["treaty_json"]),
            **_row_fields(row),
        }
    def list_recognition_treaties(
        self,
        issuer_sovereign_id: str | None = None,
        subject_sovereign_id: str | None = None,
        status: str | None = None,
        *,
        include_superseded: bool = False,
    ) -> list[dict]:
        """Return persisted treaty rows filtered by issuer, subject, or status.

        Only the newest copy of each lineage is listed unless
        ``include_superseded`` is set.
        """
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
        if not include_superseded:
            clauses.append("superseded_by IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT treaty_json, {_ROW_COLUMNS}
            FROM recognition_treaties
            {where}
            ORDER BY issued_at ASC
            """,
            params,
        ).fetchall()
        return [
            {
                "treaty": RecognitionTreaty.model_validate_json(row["treaty_json"]),
                **_row_fields(row),
            }
            for row in rows
        ]
    def recognition_treaty_lineage(self, treaty_id: str) -> list[str]:
        """The IDs of every copy in a treaty's lineage, oldest first (none if unknown)."""
        return self._lineage_ids("recognition_treaties", "treaty_id", treaty_id)
    def revoke_recognition_treaty(
        self,
        treaty_id: str,
        reason: str = "unspecified",
    ) -> bool:
        """Mark a persisted recognition treaty revoked without modifying signed JSON.

        Since 1.8.0 every copy in its lineage is revoked with it.
        """
        return bool(self.revoke_recognition_treaty_lineage(treaty_id, reason))
    def revoke_recognition_treaty_lineage(
        self,
        treaty_id: str,
        reason: str = "unspecified",
    ) -> list[str]:
        """Revoke a treaty and every copy in its lineage; return their IDs (v1.8.0)."""
        return self._revoke_lineage("recognition_treaties", "treaty_id", treaty_id, reason)
    # -- re-issue lineage (v1.8.0) -----------------------------------------------

    def _lineage_of(self, table: str, id_column: str, record_id: str) -> str | None:
        row = self.conn.execute(
            f"SELECT lineage_id FROM {table} WHERE {id_column} = ?", (record_id,)
        ).fetchone()
        if row is None:
            return None
        return row["lineage_id"] or record_id
    def _lineage_ids(self, table: str, id_column: str, record_id: str) -> list[str]:
        lineage = self._lineage_of(table, id_column, record_id)
        if lineage is None:
            return []
        rows = self.conn.execute(
            f"""
            SELECT {id_column} FROM {table}
            WHERE lineage_id = ? OR {id_column} = ?
            ORDER BY issued_at ASC, {id_column} ASC
            """,
            (lineage, lineage),
        ).fetchall()
        return [row[id_column] for row in rows]
    def _reissue(
        self,
        table: str,
        id_column: str,
        previous_id: str,
        new_id: str,
        insert: Callable[[str], None],
    ) -> bool:
        with self.conn:
            # The compare-and-set. On PostgreSQL it also locks the previous
            # copy, so a revocation of the lineage waits for this transaction
            # (see _revoke_lineage).
            cursor = self.conn.execute(
                f"""
                UPDATE {table} SET superseded_by = ?
                WHERE {id_column} = ? AND status = 'active' AND superseded_by IS NULL
                """,
                (new_id, previous_id),
            )
            if cursor.rowcount != 1:
                return False
            insert(self._lineage_of(table, id_column, previous_id) or previous_id)
        return True
    def _revoke_lineage(self, table: str, id_column: str, record_id: str, reason: str) -> list[str]:
        """Revoke every copy of a lineage and return their IDs.

        A re-issue racing this revocation either finds the previous copy
        revoked and stores nothing, or commits first. In the second case the
        first UPDATE can miss the new copy (on PostgreSQL its snapshot is
        older than the new row), so the revocation repeats until a pass
        changes nothing.
        """
        lineage = self._lineage_of(table, id_column, record_id)
        if lineage is None:
            return []
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                f"""
                UPDATE {table}
                SET status = 'revoked', revoked_at = ?, revocation_reason = ?
                WHERE lineage_id = ? OR {id_column} = ?
                """,
                (now, reason, lineage, lineage),
            )
        for _ in range(LINEAGE_REVOCATION_PASSES):
            with self.conn:
                cursor = self.conn.execute(
                    f"""
                    UPDATE {table}
                    SET status = 'revoked', revoked_at = ?, revocation_reason = ?
                    WHERE (lineage_id = ? OR {id_column} = ?) AND status != 'revoked'
                    """,
                    (now, reason, lineage, lineage),
                )
            if cursor.rowcount == 0:
                break
        return self._lineage_ids(table, id_column, record_id)
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
                        reason = excluded.reason
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
    def get_imported_sovereign_revocation(self, issuer_sovereign_id: str, attestation_id: str) -> dict | None:
        """One imported revocation, or None (v1.3.1).

        ``imported_at`` is when a feed first listed the attestation: a later
        cumulative feed that lists it again does not move it (since 1.3.1;
        a row written by 1.3.0 may carry the later import, see
        ``first_feed_import``).
        """
        row = self.conn.execute(
            """
            SELECT issuer_sovereign_id, attestation_id, feed_id, sequence, reason, imported_at
            FROM imported_sovereign_revocations
            WHERE issuer_sovereign_id = ? AND attestation_id = ?
            """,
            (issuer_sovereign_id, attestation_id),
        ).fetchone()
        return dict(row) if row else None
    def first_feed_import(self, issuer_sovereign_id: str, attestation_id: str) -> str | None:
        """When the first imported feed of an issuer that lists an attestation was imported (v1.3.1)."""
        rows = self.conn.execute(
            """
            SELECT feed_json, imported_at
            FROM sovereign_revocation_feeds
            WHERE issuer_sovereign_id = ?
            ORDER BY sequence ASC
            """,
            (issuer_sovereign_id,),
        ).fetchall()
        for row in rows:
            feed = SovereignRevocationFeed.model_validate_json(row["feed_json"])
            if attestation_id in feed.revoked_attestation_ids:
                return str(row["imported_at"])
        return None
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
        edges = []
        for treaty_row in treaty_rows:
            lifecycle = treaty_lifecycle(treaty_row)
            edges.append({
                "from": treaty_row["treaty"].issuer_sovereign_id,
                "to": treaty_row["treaty"].subject_sovereign_id,
                "treaty_id": treaty_row["treaty"].treaty_id,
                "status": treaty_row["status"],
                "lifecycle_state": lifecycle["state"],
                "expiry_risk": lifecycle["expiry_risk"],
                "valid_from": treaty_row["treaty"].valid_from.isoformat(),
                "expires_at": treaty_row["treaty"].expires_at.isoformat(),
            })
        active_treaties = [
            treaty_row["treaty"]
            for treaty_row in treaty_rows
            if is_lifecycle_active(treaty_lifecycle(treaty_row))
        ]
        revoked_trust_material = [
            {
                "type": "recognition_treaty",
                "id": treaty_row["treaty"].treaty_id,
                "lifecycle_state": treaty_lifecycle(treaty_row)["state"],
                "reason": treaty_row["revocation_reason"],
                "revoked_at": treaty_row["revoked_at"],
            }
            for treaty_row in treaty_rows
            if treaty_lifecycle(treaty_row)["state"] in {"revoked", "replaced"}
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
