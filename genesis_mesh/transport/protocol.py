"""Mesh network protocol definitions."""

import json
import time
import uuid
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """Types of messages in the mesh network."""
    # Connection management
    HANDSHAKE = "handshake"
    HANDSHAKE_ACK = "handshake_ack"
    PING = "ping"
    PONG = "pong"
    DISCONNECT = "disconnect"

    # Peer discovery
    PEER_ANNOUNCE = "peer_announce"
    PEER_REQUEST = "peer_request"
    PEER_RESPONSE = "peer_response"

    # Routing
    ROUTE_ANNOUNCE = "route_announce"
    ROUTE_UPDATE = "route_update"
    ROUTE_WITHDRAW = "route_withdraw"

    # Data forwarding
    DATA = "data"
    DATA_ACK = "data_ack"

    # Control plane
    CONTROL_MESSAGE = "control_message"
    POLICY_UPDATE = "policy_update"
    REVOCATION = "revocation"

    # Service mesh
    SERVICE_ANNOUNCE = "service_announce"
    SERVICE_REQUEST = "service_request"
    SERVICE_RESPONSE = "service_response"


class MeshMessage(BaseModel):
    """
    Base message format for all mesh communications.

    All messages are JSON-encoded and optionally signed/encrypted.
    """
    message_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique message identifier"
    )
    message_type: MessageType = Field(..., description="Message type")
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix timestamp when message was created"
    )
    sender_id: str = Field(..., description="Sender node ID")
    recipient_id: Optional[str] = Field(
        None,
        description="Recipient node ID (None for broadcast)"
    )
    ttl: int = Field(default=10, description="Time-to-live (max hops)")
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Message payload"
    )
    signature: Optional[str] = Field(
        None,
        description="Ed25519 signature (for control messages)"
    )

    def to_json(self) -> str:
        """Serialize to JSON."""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, data: str) -> "MeshMessage":
        """Deserialize from JSON."""
        return cls.model_validate_json(data)

    def to_bytes(self) -> bytes:
        """Serialize to bytes for transport."""
        return self.to_json().encode('utf-8')

    @classmethod
    def from_bytes(cls, data: bytes) -> "MeshMessage":
        """Deserialize from bytes."""
        return cls.from_json(data.decode('utf-8'))

    def decrement_ttl(self) -> bool:
        """
        Decrement TTL for forwarding.

        Returns:
            True if message should be forwarded, False if TTL expired
        """
        self.ttl -= 1
        return self.ttl > 0


class HandshakePayload(BaseModel):
    """Payload for handshake messages."""
    protocol_version: str = Field(default="1.0", description="Protocol version")
    node_id: str = Field(..., description="Node identity")
    certificate: str = Field(..., description="Join certificate (base64)")
    capabilities: list[str] = Field(
        default_factory=list,
        description="Node capabilities"
    )
    roles: list[str] = Field(..., description="Node roles")


class PeerInfo(BaseModel):
    """Information about a peer node."""
    node_id: str = Field(..., description="Node identifier")
    endpoint: str = Field(..., description="Connection endpoint (host:port)")
    roles: list[str] = Field(..., description="Node roles")
    last_seen: float = Field(
        default_factory=time.time,
        description="Last contact timestamp"
    )
    reputation: float = Field(default=1.0, description="Peer reputation score")
    latency_ms: Optional[float] = Field(None, description="RTT latency")


class RouteInfo(BaseModel):
    """Routing information."""
    destination: str = Field(..., description="Destination node ID")
    next_hop: str = Field(..., description="Next hop node ID")
    metric: int = Field(..., description="Route metric (hop count or cost)")
    sequence: int = Field(..., description="Route sequence number")
    timestamp: float = Field(
        default_factory=time.time,
        description="Route announcement time"
    )


class ControlMessage(BaseModel):
    """Control-plane message."""
    command: str = Field(..., description="Control command")
    scope: str = Field(..., description="Command scope")
    issuer: str = Field(..., description="Issuer key ID")
    issued_at: float = Field(
        default_factory=time.time,
        description="Issue timestamp"
    )
    expires_at: Optional[float] = Field(None, description="Expiration timestamp")
    data: Dict[str, Any] = Field(default_factory=dict, description="Command data")
    signature: str = Field(..., description="Ed25519 signature")


def create_handshake(
    node_id: str,
    certificate: str,
    roles: list[str]
) -> MeshMessage:
    """Create a handshake message."""
    payload = HandshakePayload(
        node_id=node_id,
        certificate=certificate,
        roles=roles
    )
    return MeshMessage(
        message_type=MessageType.HANDSHAKE,
        sender_id=node_id,
        payload=payload.model_dump()
    )


def create_ping(node_id: str, recipient_id: str) -> MeshMessage:
    """Create a ping message."""
    return MeshMessage(
        message_type=MessageType.PING,
        sender_id=node_id,
        recipient_id=recipient_id,
        payload={"timestamp": time.time()}
    )


def create_pong(node_id: str, recipient_id: str, ping_timestamp: float) -> MeshMessage:
    """Create a pong response."""
    return MeshMessage(
        message_type=MessageType.PONG,
        sender_id=node_id,
        recipient_id=recipient_id,
        payload={
            "ping_timestamp": ping_timestamp,
            "pong_timestamp": time.time()
        }
    )


def create_peer_announce(node_id: str, peers: list[PeerInfo]) -> MeshMessage:
    """Create a peer announcement message."""
    return MeshMessage(
        message_type=MessageType.PEER_ANNOUNCE,
        sender_id=node_id,
        payload={"peers": [p.model_dump() for p in peers]}
    )


def create_route_announce(
    node_id: str,
    routes: list[RouteInfo]
) -> MeshMessage:
    """Create a route announcement message."""
    return MeshMessage(
        message_type=MessageType.ROUTE_ANNOUNCE,
        sender_id=node_id,
        payload={"routes": [r.model_dump() for r in routes]}
    )


def create_data_message(
    sender_id: str,
    recipient_id: str,
    data: bytes,
    ttl: int = 10
) -> MeshMessage:
    """Create a data message for forwarding."""
    import base64
    return MeshMessage(
        message_type=MessageType.DATA,
        sender_id=sender_id,
        recipient_id=recipient_id,
        ttl=ttl,
        payload={"data": base64.b64encode(data).decode('utf-8')}
    )
