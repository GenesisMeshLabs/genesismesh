"""CRL and policy persistence."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from ..models import PolicyManifest
from ..models.revocation import CertificateRevocationList, RevokedCertificate


class PolicyStoreMixin:
    """Persistence methods for certificate revocation and policy versions."""

    conn: sqlite3.Connection

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
