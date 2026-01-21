"""Certificate Revocation List (CRL) models."""

import json
from datetime import datetime, timedelta
from typing import List, Optional
from pydantic import BaseModel, Field

from .genesis import Signature


class RevokedCertificate(BaseModel):
    """Information about a revoked certificate."""
    certificate_id: str = Field(..., description="Certificate ID")
    revoked_at: datetime = Field(..., description="Revocation timestamp")
    reason: str = Field(..., description="Revocation reason")
    issuer: str = Field(..., description="Who issued the revocation")


class CertificateRevocationList(BaseModel):
    """
    Certificate Revocation List (CRL).

    Contains list of revoked certificates, signed by Network Authority.
    Distributed via gossip protocol to all nodes.
    """
    crl_id: str = Field(..., description="Unique CRL identifier")
    sequence: int = Field(..., description="Sequence number (monotonic increasing)")
    issued_at: datetime = Field(..., description="Issue timestamp")
    next_update: datetime = Field(..., description="When next CRL will be published")
    issuer: str = Field(..., description="Issuer key ID (typically NA)")
    revoked_certificates: List[RevokedCertificate] = Field(
        default_factory=list,
        description="List of revoked certificates"
    )
    signatures: List[Signature] = Field(
        default_factory=list,
        description="NA signature"
    )

    def to_canonical_json(self) -> str:
        """Convert to canonical JSON for signing/verification."""
        data = self.model_dump(exclude={"signatures"}, mode='json')
        return json.dumps(data, sort_keys=True, separators=(',', ':'))

    def is_cert_revoked(self, cert_id: str) -> bool:
        """Check if a certificate is revoked."""
        return any(
            rc.certificate_id == cert_id
            for rc in self.revoked_certificates
        )

    def is_expired(self) -> bool:
        """Check if CRL should be updated."""
        return datetime.utcnow() > self.next_update

    @staticmethod
    def create_empty(
        issuer: str,
        sequence: int = 1,
        validity_hours: int = 24
    ) -> "CertificateRevocationList":
        """Create an empty CRL."""
        import uuid
        now = datetime.utcnow()
        return CertificateRevocationList(
            crl_id=str(uuid.uuid4()),
            sequence=sequence,
            issued_at=now,
            next_update=now + timedelta(hours=validity_hours),
            issuer=issuer,
            revoked_certificates=[]
        )

    @staticmethod
    def add_revocation(
        crl: "CertificateRevocationList",
        cert_id: str,
        reason: str,
        issuer: str
    ) -> "CertificateRevocationList":
        """Add a revocation to the CRL."""
        import uuid
        revoked = RevokedCertificate(
            certificate_id=cert_id,
            revoked_at=datetime.utcnow(),
            reason=reason,
            issuer=issuer
        )

        # Create new CRL with increased sequence
        new_crl = CertificateRevocationList(
            crl_id=str(uuid.uuid4()),
            sequence=crl.sequence + 1,
            issued_at=datetime.utcnow(),
            next_update=crl.next_update,
            issuer=crl.issuer,
            revoked_certificates=crl.revoked_certificates + [revoked],
            signatures=[]  # Needs to be re-signed
        )

        return new_crl
