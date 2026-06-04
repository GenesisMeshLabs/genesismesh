"""Agent discovery and service-registry persistence."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from ..models import AgentDescriptor


class AgentStoreMixin:
    """Persistence methods for authenticated agent registrations."""

    conn: sqlite3.Connection

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
