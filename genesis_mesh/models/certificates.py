"""Certificate models for node and service identities."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

from .genesis import Signature


class JoinCertificate(BaseModel):
    """
    Join Certificate - Permits a node to join the network.

    Short-lived certificates issued by Network Authority.
    - Servers: 7 days validity
    - Mobile devices: 24-72 hours validity
    """
    cert_id: str = Field(..., description="Unique certificate identifier")
    node_public_key: str = Field(..., description="Node's public key (base64)")
    network_name: str = Field(..., description="Target network identifier")
    roles: List[str] = Field(
        default_factory=list,
        description="Assigned roles (e.g., role:anchor, role:client)"
    )
    issued_at: datetime = Field(..., description="Certificate issue time")
    expires_at: datetime = Field(..., description="Certificate expiration time")
    issued_by: str = Field(..., description="Issuing authority key ID")
    signatures: List[Signature] = Field(
        default_factory=list,
        description="Network Authority signature"
    )

    def to_canonical_json(self) -> str:
        """Convert to canonical JSON for signing/verification."""
        data = self.model_dump(exclude={"signatures"}, mode='json')
        import json
        return json.dumps(data, sort_keys=True, separators=(',', ':'))

    def is_valid(self, current_time: Optional[datetime] = None) -> bool:
        """Check if certificate is currently valid."""
        if current_time is None:
            current_time = datetime.utcnow()
        return self.issued_at <= current_time <= self.expires_at


class ServiceManifest(BaseModel):
    """
    Service Manifest - Authenticates a service identity and its endpoints.

    Used for service-to-service authentication within the mesh.
    """
    service_name: str = Field(..., description="Unique service identifier")
    service_key: str = Field(..., description="Service public key (base64)")
    endpoints: List[str] = Field(..., description="Service endpoints (URLs)")
    issued_at: datetime = Field(..., description="Manifest issue time")
    valid_to: datetime = Field(..., description="Manifest expiration time")
    issued_by: str = Field(..., description="Issuing authority key ID")
    signatures: List[Signature] = Field(
        default_factory=list,
        description="Network Authority signature"
    )

    def to_canonical_json(self) -> str:
        """Convert to canonical JSON for signing/verification."""
        data = self.model_dump(exclude={"signatures"}, mode='json')
        import json
        return json.dumps(data, sort_keys=True, separators=(',', ':'))

    def is_valid(self, current_time: Optional[datetime] = None) -> bool:
        """Check if manifest is currently valid."""
        if current_time is None:
            current_time = datetime.utcnow()
        return self.issued_at <= current_time <= self.valid_to
