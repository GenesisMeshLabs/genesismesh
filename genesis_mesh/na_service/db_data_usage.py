"""Durable data-license policies shared by authority worker processes."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from ..models.data_usage import DataLicensePolicy


class DataUsageStoreMixin:
    """Persist signed policy versions and atomically select the active version."""

    conn: sqlite3.Connection
    _lock: Any

    def save_data_license_policy(self, policy: DataLicensePolicy) -> None:
        """Activate a signed policy in one transaction across all workers."""
        with self._lock, self.conn:
            self.conn.execute("UPDATE data_license_policies SET active = 0 WHERE active = 1")
            self.conn.execute(
                "INSERT OR REPLACE INTO data_license_policies"
                "(policy_id, policy_json, active, created_at) VALUES (?, ?, 1, ?)",
                (policy.policy_id, policy.model_dump_json(), datetime.now(timezone.utc).isoformat()),
            )

    def get_active_data_license_policy(self) -> DataLicensePolicy | None:
        """Read the committed active policy from the shared database."""
        with self._lock:
            row = self.conn.execute(
                "SELECT policy_json FROM data_license_policies WHERE active = 1"
            ).fetchone()
        return DataLicensePolicy.model_validate_json(row["policy_json"]) if row else None
