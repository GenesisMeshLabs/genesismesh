"""Genesis Block data models."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class Signature(BaseModel):
    """Cryptographic signature with key identifier."""
    key_id: str = Field(..., description="Identifier of the signing key")
    sig: str = Field(..., description="Base64-encoded signature")


class NetworkAuthority(BaseModel):
    """Network Authority configuration."""
    public_key: str = Field(..., description="Base64-encoded public key")
    valid_from: datetime = Field(..., description="Validity start time")
    valid_to: datetime = Field(..., description="Validity end time")


class PolicyManifestRef(BaseModel):
    """Reference to policy manifest with content hash."""
    hash: str = Field(..., description="Content hash (e.g., sha256:...)")
    url: Optional[str] = Field(None, description="Optional URL for policy retrieval")


class BootstrapAnchor(BaseModel):
    """Bootstrap anchor node information."""
    id: str = Field(..., description="Unique anchor identifier")
    endpoint: str = Field(..., description="Network endpoint (host:port)")


class GenesisBlock(BaseModel):
    """
    Genesis Block - The network constitution.

    This is the root of trust for the entire mesh network.
    All nodes embed or import this once at initialization.
    """
    network_name: str = Field(..., description="Unique network identifier")
    network_version: str = Field(..., description="Network protocol version")
    root_public_key: str = Field(..., description="Root Sovereign public key (base64)")
    network_authority: NetworkAuthority = Field(..., description="Current Network Authority")
    allowed_crypto_suites: List[str] = Field(
        default_factory=lambda: ["ed25519", "x25519"],
        description="Permitted cryptographic algorithms"
    )
    allowed_transports: List[str] = Field(
        default_factory=lambda: ["quic", "wireguard"],
        description="Permitted transport protocols"
    )
    policy_manifest: PolicyManifestRef = Field(..., description="Reference to policy manifest")
    bootstrap_anchors: List[BootstrapAnchor] = Field(
        default_factory=list,
        description="Initial anchor nodes for network entry"
    )
    signatures: List[Signature] = Field(
        default_factory=list,
        description="Root Sovereign signatures"
    )

    def to_canonical_json(self) -> str:
        """
        Convert to canonical JSON for signing/verification.
        Excludes signatures field.
        """
        data = self.model_dump(exclude={"signatures"}, mode='json')
        import json
        return json.dumps(data, sort_keys=True, separators=(',', ':'))
