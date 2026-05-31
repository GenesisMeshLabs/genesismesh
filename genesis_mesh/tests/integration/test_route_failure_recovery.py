"""Integration test: A reaches C through B and D; B fails; traffic continues via D."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models import (
    GenesisBlock,
    JoinCertificate,
    NetworkAuthority,
    PolicyManifestRef,
)
from genesis_mesh.node.node import MeshNode
from genesis_mesh.node.runtime import MeshNodeRuntime


def _make_signed_genesis(root_keypair, na_keypair) -> GenesisBlock:
    """Create a root-signed genesis block for integration tests."""
    now = datetime.now(timezone.utc)
    genesis = GenesisBlock(
        network_name="integration-failover",
        network_version="v0.1",
        root_public_key=root_keypair.public_key_b64,
        network_authority=NetworkAuthority(
            public_key=na_keypair.public_key_b64,
            valid_from=now - timedelta(hours=1),
            valid_to=now + timedelta(days=90),
        ),
        policy_manifest=PolicyManifestRef(hash="sha256:test"),
        bootstrap_anchors=[],
        signatures=[],
    )
    genesis.signatures.append(
        sign_model(genesis, root_keypair.private_key, "root-test")
    )
    return genesis


def _make_join_certificate(node_keypair, genesis: GenesisBlock, na_keypair) -> JoinCertificate:
    """Create an NA-signed join certificate for a node."""
    now = datetime.now(timezone.utc)
    cert = JoinCertificate(
        cert_id=f"cert-{node_keypair.public_key_b64[:8]}",
        node_public_key=node_keypair.public_key_b64,
        network_name=genesis.network_name,
        roles=["role:anchor"],
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        issued_by="na-2025-q1",
        signatures=[],
    )
    cert.signatures.append(sign_model(cert, na_keypair.private_key, "na-2025-q1"))
    return cert


def _make_joined_node(genesis: GenesisBlock, na_keypair) -> MeshNode:
    """Create a joined node with a signed certificate."""
    node_keypair = generate_keypair()
    node = MeshNode(
        genesis_block=genesis,
        node_keypair=node_keypair,
        roles=["role:anchor"],
    )
    node.join_certificate = _make_join_certificate(node_keypair, genesis, na_keypair)
    return node


async def _wait_for(predicate, timeout: float = 10.0) -> None:
    """Wait until a predicate returns true or fail the test."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("Timed out waiting for integration condition")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_route_failure_recovery_via_backup_router():
    """When the primary router (B) fails, traffic routes through the backup router (D)."""
    root_keypair = generate_keypair()
    na_keypair = generate_keypair()
    genesis = _make_signed_genesis(root_keypair, na_keypair)

    node_a = _make_joined_node(genesis, na_keypair)
    node_b = _make_joined_node(genesis, na_keypair)
    node_c = _make_joined_node(genesis, na_keypair)
    node_d = _make_joined_node(genesis, na_keypair)

    a_key = node_a.node_keypair.public_key_b64
    b_key = node_b.node_keypair.public_key_b64
    c_key = node_c.node_keypair.public_key_b64
    d_key = node_d.node_keypair.public_key_b64

    runtime_a = MeshNodeRuntime(node_a, "http://127.0.0.1:9", "127.0.0.1", 0)
    runtime_b = MeshNodeRuntime(node_b, "http://127.0.0.1:9", "127.0.0.1", 0)
    runtime_c = MeshNodeRuntime(node_c, "http://127.0.0.1:9", "127.0.0.1", 0)
    runtime_d = MeshNodeRuntime(node_d, "http://127.0.0.1:9", "127.0.0.1", 0)

    await runtime_a.start()
    await runtime_b.start()
    await runtime_c.start()
    await runtime_d.start()
    try:
        # Topology: A connects to both B and D; C connects to both B and D.
        # A and C never connect directly.
        await runtime_a._connect_endpoint(f"127.0.0.1:{runtime_b.bound_port}")
        await runtime_a._connect_endpoint(f"127.0.0.1:{runtime_d.bound_port}")
        await runtime_c._connect_endpoint(f"127.0.0.1:{runtime_b.bound_port}")
        await runtime_c._connect_endpoint(f"127.0.0.1:{runtime_d.bound_port}")

        # Wait for B and D to see both A and C.
        await _wait_for(
            lambda: runtime_b.peer_manager.get_peer(a_key)
            and runtime_b.peer_manager.get_peer(c_key)
        )
        await _wait_for(
            lambda: runtime_d.peer_manager.get_peer(a_key)
            and runtime_d.peer_manager.get_peer(c_key)
        )

        # Trigger route advertisement from both relays.
        await runtime_b.routing_protocol.trigger_update()
        await runtime_d.routing_protocol.trigger_update()

        # A learns a route to C (via B or D — either is fine for the primary send).
        await _wait_for(lambda: runtime_a.routing_table.get_route(c_key) is not None)

        # Record deliveries on C.
        delivered = []
        original_route_message = runtime_c.router.route_message

        async def record_delivery(message):
            """Record local delivery on node C."""
            if message.recipient_id == runtime_c.node_id:
                delivered.append(message)
            return await original_route_message(message)

        runtime_c.router.route_message = record_delivery

        # Send 1 — works through whichever route A learned first.
        assert await runtime_a.router.send_to(c_key, b"hello-1")
        await _wait_for(lambda: len(delivered) == 1)
        assert delivered[0].payload.get("data") is not None

        # === Simulate primary router failure ===
        await runtime_b.stop()

        # A and C should both detect B's disconnect and withdraw B's routes.
        await _wait_for(lambda: runtime_a.peer_manager.get_peer(b_key) is None)
        await _wait_for(lambda: runtime_c.peer_manager.get_peer(b_key) is None)

        # Re-advertise from D so A's route to C is via D (metric=2).
        await runtime_d.routing_protocol.trigger_update()
        await _wait_for(
            lambda: (
                runtime_a.routing_table.get_route(c_key) is not None
                and runtime_a.routing_table.get_route(c_key).next_hop == d_key
            )
        )

        # Send 2 — must succeed via D even though B is gone.
        assert await runtime_a.router.send_to(c_key, b"hello-2")
        await _wait_for(lambda: len(delivered) == 2)
        assert delivered[1].payload.get("data") is not None
    finally:
        await runtime_a.stop()
        try:
            await runtime_b.stop()
        except Exception:
            pass  # Already stopped during the test.
        await runtime_c.stop()
        await runtime_d.stop()
