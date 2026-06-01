"""Agent discovery models for the Network Authority service registry.

Agents announce themselves and their capabilities to the Network Authority so
peers can find them by capability rather than by node public key. Each
registration is signed by the registering agent's join-certificate key; the
NA verifies that signature against the public key embedded in the descriptor.

The registry is intentionally simple in v0.7:

- TTL-based — entries expire if the agent does not refresh.
- One descriptor per ``node_public_key`` (each enrolled node can advertise at
  most one agent role).
- Operator-side revocation (CRL) automatically evicts registrations belonging
  to revoked node keys.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from .genesis import Signature


class AgentEndpoint(BaseModel):
    """Where an agent listens for peer connections."""

    host: str = Field(..., description="Reachable hostname or IP")
    port: int = Field(..., ge=1, le=65535, description="Peer WebSocket port")
    scheme: str = Field("ws", description="Peer transport scheme: ws or wss")

    def to_uri(self) -> str:
        """Return the WebSocket URI for this endpoint."""
        return f"{self.scheme}://{self.host}:{self.port}"


class AgentDescriptor(BaseModel):
    """Signed announcement of an agent identity and its capabilities."""

    agent_id: str = Field(..., description="Logical agent identifier (e.g. 'llm-1')")
    node_public_key: str = Field(
        ...,
        description="Base64-encoded Ed25519 public key of the enrolled mesh node",
    )
    network_name: str = Field(..., description="Network the agent belongs to")
    capabilities: List[str] = Field(
        default_factory=list,
        description="Capability tags peers query against (e.g. 'llm:chat', 'kb:security')",
    )
    endpoint: AgentEndpoint = Field(..., description="Reachable peer endpoint")
    registered_at: datetime = Field(..., description="UTC timestamp of this announcement")
    expires_at: datetime = Field(..., description="UTC timestamp when this registration is stale")
    metadata: dict = Field(
        default_factory=dict,
        description="Optional free-form descriptor (e.g. {'model': 'gpt-4o-mini'})",
    )
    signatures: List[Signature] = Field(
        default_factory=list,
        description="Signed by the agent's join-certificate key",
    )

    @model_validator(mode="after")
    def _check_window(self) -> "AgentDescriptor":
        """Reject obviously bogus expiry windows."""
        if self.expires_at <= self.registered_at:
            raise ValueError("expires_at must be strictly greater than registered_at")
        return self

    def to_canonical_json(self) -> str:
        """Canonical JSON for signing/verification (excludes signatures)."""
        data = self.model_dump(exclude={"signatures"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def is_active(self, current_time: Optional[datetime] = None) -> bool:
        """Return whether the registration is still within its TTL."""
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        # Tolerate ~5 minutes of clock skew on the lower bound.
        return (
            (self.registered_at - timedelta(minutes=5)) <= current_time <= self.expires_at
        )
