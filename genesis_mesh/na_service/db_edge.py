"""Edge node persistence (v1.7.0, Stage 6)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def _dict(row: Any) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


class EdgeStoreMixin:
    """Edge nodes: the node key, the executor key it registered at /join, and its agent status."""

    conn: Any
    _lock: Any

    def insert_edge_node(self, values: dict[str, Any]) -> None:
        """Insert an edge node; the database refuses a second row for the node key, the executor
        key, or an active sovereign ID (an integrity error)."""
        with self._lock, self.conn:
            self.conn.execute(
                """INSERT INTO edge_nodes(node_public_key, node_sovereign_id, executor_key_id, resource_prefix,
                       enrolled_cert_id, enrolled_at) VALUES (?, ?, ?, ?, ?, ?)""",
                (values["node_public_key"], values["node_sovereign_id"], values["executor_key_id"],
                 values["resource_prefix"], values["enrolled_cert_id"], values["enrolled_at"]),
            )

    def enrol_edge_node(self, values: dict[str, Any], registered_by: str) -> str:
        """Register an edge node's executor key and record the edge node in one transaction (review
        fixes): neither is written without the other. Returns the key's registration time; an
        integrity error when the key, the node key or an active sovereign ID is taken."""
        registered_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self.conn:
            self.conn.execute(
                """INSERT INTO evidence_executor_keys(key_id, public_key, executor_sovereign_id,
                       registered_at, registered_by, key_role, resource_prefix) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (values["executor_key_id"], values["executor_public_key"], values["node_sovereign_id"],
                 registered_at, registered_by, "executor", values["resource_prefix"]),
            )
            self.conn.execute(
                """INSERT INTO edge_nodes(node_public_key, node_sovereign_id, executor_key_id, resource_prefix,
                       enrolled_cert_id, enrolled_at) VALUES (?, ?, ?, ?, ?, ?)""",
                (values["node_public_key"], values["node_sovereign_id"], values["executor_key_id"],
                 values["resource_prefix"], values["enrolled_cert_id"], values["enrolled_at"]),
            )
        return registered_at

    def get_edge_node_by_executor_key(self, executor_key_id: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM edge_nodes WHERE executor_key_id = ?", (executor_key_id,)).fetchone()
        return _dict(row) if row is not None else None

    def edge_nodes_of(self, node_sovereign_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM edge_nodes WHERE node_sovereign_id = ? ORDER BY enrolled_at", (node_sovereign_id,)
        ).fetchall()
        return [_dict(r) for r in rows]

    def retired_edge_nodes(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM edge_nodes WHERE retired_at IS NOT NULL ORDER BY enrolled_at, node_public_key"
        ).fetchall()
        return [_dict(r) for r in rows]

    def outstanding_edge_invites(self, now: datetime) -> list[dict[str, Any]]:
        """Edge invites neither used nor expired: their sovereign IDs and prefixes."""
        rows = self.conn.execute(
            """SELECT token_id, node_sovereign_id, executor_resource_prefix, expires_at FROM invite_tokens
               WHERE node_sovereign_id IS NOT NULL AND used_at IS NULL""",
        ).fetchall()
        out = []
        for row in rows:
            expires = datetime.fromisoformat(row["expires_at"])
            if (expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)) >= now:
                out.append(_dict(row))
        return out

    def active_executor_key_prefixes(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT resource_prefix FROM evidence_executor_keys WHERE retired_at IS NULL AND resource_prefix IS NOT NULL"
        ).fetchall()
        return [str(r["resource_prefix"]) for r in rows]

    def active_executor_key_sovereign(self, executor_sovereign_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM evidence_executor_keys WHERE executor_sovereign_id = ? AND retired_at IS NULL",
            (executor_sovereign_id,),
        ).fetchone()
        return row is not None

    def attestation_subject_exists(self, issuer_sovereign_id: str, subject_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM membership_attestations WHERE issuer_sovereign_id = ? AND subject_id = ?",
            (issuer_sovereign_id, subject_id),
        ).fetchone()
        return row is not None

    def get_edge_node(self, node_public_key: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM edge_nodes WHERE node_public_key = ?", (node_public_key,)).fetchone()
        return _dict(row) if row is not None else None

    def get_active_edge_node_by_sovereign(self, node_sovereign_id: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM edge_nodes WHERE node_sovereign_id = ? AND retired_at IS NULL", (node_sovereign_id,)
        ).fetchone()
        return _dict(row) if row is not None else None

    def retire_edge_node(self, node_public_key: str, retired_at: str, reason: str, retired_by: str) -> bool:
        """Mark an edge node revoked; False when it already was."""
        with self._lock, self.conn:
            cur = self.conn.execute(
                """UPDATE edge_nodes SET retired_at = ?, retired_reason = ?, retired_by = ?
                   WHERE node_public_key = ? AND retired_at IS NULL""",
                (retired_at, reason, retired_by, node_public_key),
            )
        return bool(cur.rowcount)

    def set_edge_agent_status(self, node_public_key: str, status_json: str, at: str) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE edge_nodes SET agent_status_json = ?, agent_status_at = ? WHERE node_public_key = ?",
                (status_json, at, node_public_key),
            )

    def unretired_edge_nodes(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM edge_nodes WHERE retired_at IS NULL ORDER BY enrolled_at, node_public_key"
        ).fetchall()
        return [_dict(r) for r in rows]

    def edge_nodes_page(
        self, *, retired: Optional[bool], node_sovereign_id: Optional[str],
        after: Optional[tuple[str, str]], limit: int,
    ) -> list[dict[str, Any]]:
        """Edge nodes by ``enrolled_at`` (newest first), then ``node_public_key``. ``retired``: only
        revoked nodes (True), only unrevoked ones (False) or both (None). ``after``: the
        ``(enrolled_at, node_public_key)`` of the last node of the previous page."""
        clauses: list[str] = []
        params: list[Any] = []
        if retired is not None:
            clauses.append("retired_at IS NOT NULL" if retired else "retired_at IS NULL")
        if node_sovereign_id is not None:
            clauses.append("node_sovereign_id = ?")
            params.append(node_sovereign_id)
        if after is not None:
            clauses.append("(enrolled_at < ? OR (enrolled_at = ? AND node_public_key > ?))")
            params.extend([after[0], after[0], after[1]])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM edge_nodes {where} ORDER BY enrolled_at DESC, node_public_key ASC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [_dict(r) for r in rows]

    def break_glass_entries_of(self, executor_sovereign_id: str) -> list[dict[str, Any]]:
        """``recorded_at`` and payload of each break-glass entry an executor sovereign recorded."""
        rows = self.conn.execute(
            """SELECT recorded_at, payload_json FROM evidence_entries
               WHERE executor_sovereign_id = ? AND entry_kind = 'break_glass' ORDER BY store_sequence""",
            (executor_sovereign_id,),
        ).fetchall()
        return [_dict(r) for r in rows]
