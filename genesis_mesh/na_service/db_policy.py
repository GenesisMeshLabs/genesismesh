"""CRL and policy persistence."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import uuid

from ..models import PolicyManifest
from ..models.revocation import CertificateRevocationList, RevokedCertificate


# F-20: how long a revocation entry is kept after its certificate has expired.
# An expired certificate already fails validation everywhere, so the entry adds
# nothing; the margin covers the +/-5 min clock skew JoinCertificate.is_valid
# grants (models/certificates.py:44-45).
CRL_ENTRY_RETENTION = timedelta(hours=1)


class PolicyStoreMixin:
    """Persistence methods for certificate revocation and policy versions."""

    conn: sqlite3.Connection
    _lock: Any

    def get_cert(self, cert_id: str) -> Optional[dict]:
        raise NotImplementedError

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

        now = datetime.now(timezone.utc)
        revoked = RevokedCertificate(
            certificate_id=cert_id,
            revoked_at=now,
            reason=reason,
            issuer=issuer,
        )
        crl = self._next_crl(
            current,
            self._retained_revocations(current.revoked_certificates + [revoked], now),
            now,
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

    def sweep_superseded_certs(
        self,
        issuer: str,
        now: Optional[datetime] = None,
    ) -> Optional[CertificateRevocationList]:
        """Revoke superseded certificates whose grace window has closed (F-20).

        A renewal schedules its predecessor via ``mark_superseded``; this promotes
        every matured schedule into one new unsigned CRL (a single sequence bump).
        Returns None when nothing matured and nothing needed pruning.
        """
        now = now or datetime.now(timezone.utc)
        with self._lock:
            matured = [
                row["cert_id"]
                for row in self.conn.execute(
                    """
                    SELECT cert_id FROM issued_certs
                    WHERE revoke_after IS NOT NULL
                      AND revoke_after <= ?
                      AND status != 'revoked'
                    ORDER BY revoke_after
                    """,
                    (now.isoformat(),),
                ).fetchall()
            ]

            current = self.get_active_crl()
            if current is None:
                current = CertificateRevocationList.create_empty(issuer=issuer, sequence=0)

            known_ids = {rc.certificate_id for rc in current.revoked_certificates}
            additions = [
                RevokedCertificate(
                    certificate_id=cert_id,
                    revoked_at=now,
                    reason="superseded",
                    issuer=issuer,
                )
                for cert_id in matured
                if cert_id not in known_ids
            ]
            revoked_certificates = self._retained_revocations(
                current.revoked_certificates + additions,
                now,
            )
            if not matured and len(revoked_certificates) == len(current.revoked_certificates):
                return None

            if matured:
                with self.conn:
                    self.conn.executemany(
                        """
                        UPDATE issued_certs
                        SET status = 'revoked', revoked_at = ?, revocation_reason = 'superseded'
                        WHERE cert_id = ?
                        """,
                        [(now.isoformat(), cert_id) for cert_id in matured],
                    )

            return self._next_crl(current, revoked_certificates, now)

    def _next_crl(
        self,
        current: CertificateRevocationList,
        revoked_certificates: list[RevokedCertificate],
        now: datetime,
    ) -> CertificateRevocationList:
        """Build the next unsigned CRL version from an existing one."""
        return CertificateRevocationList(
            crl_id=str(uuid.uuid4()),
            sequence=current.sequence + 1,
            issued_at=now,
            next_update=now + timedelta(hours=24),
            issuer=current.issuer,
            revoked_certificates=revoked_certificates,
            signatures=[],
        )

    def _retained_revocations(
        self,
        revoked_certificates: list[RevokedCertificate],
        now: datetime,
    ) -> list[RevokedCertificate]:
        """Drop entries whose certificate expired more than the retention ago (F-20).

        Renewal adds one entry per predecessor, so without this the gossiped CRL
        would grow without bound.
        """
        if not revoked_certificates:
            return []

        cert_ids = [rc.certificate_id for rc in revoked_certificates]
        expiries: dict[str, str] = {}
        # Chunked to stay under SQLite's bound-variable limit on long CRLs.
        for start in range(0, len(cert_ids), 500):
            chunk = cert_ids[start:start + 500]
            placeholders = ",".join("?" for _ in chunk)
            expiries.update(
                {
                    row["cert_id"]: row["expires_at"]
                    for row in self.conn.execute(
                        "SELECT cert_id, expires_at FROM issued_certs "
                        f"WHERE cert_id IN ({placeholders})",
                        chunk,
                    ).fetchall()
                }
            )

        cutoff = now - CRL_ENTRY_RETENTION
        retained = []
        for entry in revoked_certificates:
            expires_at = self._parse_db_datetime(expiries.get(entry.certificate_id))
            if expires_at is not None and expires_at < cutoff:
                continue
            retained.append(entry)
        return retained

    @staticmethod
    def _parse_db_datetime(value: Optional[str]) -> Optional[datetime]:
        """Parse a persisted ISO timestamp as UTC, or None if unusable."""
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
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
