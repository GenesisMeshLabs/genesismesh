"""Policy manifest models."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

from .genesis import Signature


class RoutingConfig(BaseModel):
    """Routing configuration for the mesh network."""
    preferred_transports: List[str] = Field(
        default_factory=lambda: ["quic", "wireguard"],
        description="Preferred transport protocols in order"
    )
    max_hops: int = Field(default=6, description="Maximum routing hops")


class PolicyManifest(BaseModel):
    """
    Policy Manifest - Network-wide policies and configurations.

    Signed by Network Authority and distributed to all nodes.
    """
    policy_id: str = Field(..., description="Unique policy identifier")
    issued_at: datetime = Field(..., description="Policy issue time")
    issued_by: str = Field(..., description="Issuing authority key ID")
    min_client_version: str = Field(..., description="Minimum required client version")
    allowed_ports: List[int] = Field(
        default_factory=lambda: [443, 8443],
        description="Allowed network ports"
    )
    allowed_services: List[str] = Field(
        default_factory=list,
        description="Permitted service identifiers"
    )
    routing: RoutingConfig = Field(
        default_factory=RoutingConfig,
        description="Routing configuration"
    )
    signatures: List[Signature] = Field(
        default_factory=list,
        description="Network Authority signature"
    )

    def to_canonical_json(self) -> str:
        """Convert to canonical JSON for signing/verification."""
        data = self.model_dump(exclude={"signatures"}, mode='json')
        import json
        return json.dumps(data, sort_keys=True, separators=(',', ':'))
