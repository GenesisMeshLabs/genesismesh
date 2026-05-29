"""Tests for signed peer discovery announcements."""

import time
import uuid

import pytest

from genesis_mesh.crypto import generate_keypair, sign_data, verify_signature
from genesis_mesh.node.discovery import PeerDiscovery
from genesis_mesh.node.peer_manager import PeerManager
from genesis_mesh.transport.protocol import MeshMessage, MessageType, PeerInfo


def _signed_peer(node_id: str, endpoint: str = "127.0.0.1:9000") -> tuple[PeerInfo, list[str]]:
    """Create a signed PeerInfo and return it with trusted roles."""
    keypair = generate_keypair()
    trusted_roles = ["role:client"]
    peer = PeerInfo(
        node_id=keypair.public_key_b64 if node_id == "from-key" else node_id,
        endpoint=endpoint,
        roles=["role:untrusted"],
        cert_id=f"cert-{uuid.uuid4()}",
        announcement_issued_at=time.time(),
        announcement_nonce=str(uuid.uuid4()),
    )
    peer.announcement_signature = sign_data(
        peer.announcement_canonical_json().encode("utf-8"),
        keypair.private_key,
    )
    peer.node_id = keypair.public_key_b64
    return peer, trusted_roles


def _verifier(expected_roles: list[str]):
    """Build a verifier that checks the announcement signature."""
    def verify(peer_info: PeerInfo) -> tuple[bool, list[str]]:
        """Verify one peer announcement."""
        if not peer_info.announcement_signature:
            return False, []
        return (
            verify_signature(
                peer_info.announcement_canonical_json().encode("utf-8"),
                peer_info.announcement_signature,
                peer_info.node_id,
            ),
            expected_roles,
        )

    return verify


@pytest.mark.asyncio
async def test_unsigned_peer_announcement_is_ignored():
    """Discovery rejects peer announcements without a signature."""
    peer_manager = PeerManager("local")
    discovery = PeerDiscovery(
        "local",
        peer_manager,
        [],
        verify_peer_info=_verifier(["role:client"]),
    )
    peer = PeerInfo(
        node_id="peer",
        endpoint="127.0.0.1:9000",
        roles=["role:client"],
        cert_id="cert-1",
        announcement_issued_at=time.time(),
        announcement_nonce=str(uuid.uuid4()),
    )
    message = MeshMessage(
        message_type=MessageType.PEER_RESPONSE,
        sender_id="sender",
        payload={"peers": [peer.model_dump()]},
    )

    await discovery.handle_peer_response(message)

    assert peer_manager.get_peer("peer") is None


@pytest.mark.asyncio
async def test_peer_announcement_roles_are_derived_from_verifier():
    """Discovery ignores gossip roles and uses verifier-provided roles."""
    peer, trusted_roles = _signed_peer("from-key")
    peer_manager = PeerManager("local")
    discovery = PeerDiscovery(
        "local",
        peer_manager,
        [],
        verify_peer_info=_verifier(trusted_roles),
    )
    message = MeshMessage(
        message_type=MessageType.PEER_RESPONSE,
        sender_id="sender",
        payload={"peers": [peer.model_dump()]},
    )

    await discovery.handle_peer_response(message)

    state = peer_manager.get_peer(peer.node_id)
    assert state is not None
    assert state.info.roles == trusted_roles


@pytest.mark.asyncio
async def test_stale_peer_announcement_is_ignored():
    """Discovery rejects signed announcements outside the freshness window."""
    peer, trusted_roles = _signed_peer("from-key")
    peer.announcement_issued_at = time.time() - 3600
    peer.announcement_signature = sign_data(
        peer.announcement_canonical_json().encode("utf-8"),
        generate_keypair().private_key,
    )
    peer_manager = PeerManager("local")
    discovery = PeerDiscovery(
        "local",
        peer_manager,
        [],
        verify_peer_info=_verifier(trusted_roles),
    )
    message = MeshMessage(
        message_type=MessageType.PEER_RESPONSE,
        sender_id="sender",
        payload={"peers": [peer.model_dump()]},
    )

    await discovery.handle_peer_response(message)

    assert peer_manager.get_peer(peer.node_id) is None


@pytest.mark.asyncio
async def test_replayed_peer_announcement_nonce_is_ignored():
    """Discovery accepts a signed announcement once and rejects nonce replay."""
    peer, trusted_roles = _signed_peer("from-key")
    peer_manager = PeerManager("local")
    discovery = PeerDiscovery(
        "local",
        peer_manager,
        [],
        verify_peer_info=_verifier(trusted_roles),
    )
    message = MeshMessage(
        message_type=MessageType.PEER_RESPONSE,
        sender_id="sender",
        payload={"peers": [peer.model_dump()]},
    )

    await discovery.handle_peer_response(message)
    first_seen = peer_manager.get_peer(peer.node_id).info.last_seen
    await discovery.handle_peer_response(message)

    assert peer_manager.get_peer(peer.node_id).info.last_seen == first_seen


@pytest.mark.asyncio
async def test_peer_response_is_capped_to_twenty_announcements():
    """Discovery processes at most 20 peer announcements from one message."""
    peers = [_signed_peer("from-key", f"127.0.0.1:{9000 + i}")[0] for i in range(25)]
    peer_manager = PeerManager("local", max_peers=30)
    discovery = PeerDiscovery(
        "local",
        peer_manager,
        [],
        verify_peer_info=_verifier(["role:client"]),
    )
    message = MeshMessage(
        message_type=MessageType.PEER_RESPONSE,
        sender_id="sender",
        payload={"peers": [peer.model_dump() for peer in peers]},
    )

    await discovery.handle_peer_response(message)

    assert len(peer_manager.peers) == 20
