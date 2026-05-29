"""Integration tests for multi-node runtime behavior."""

import asyncio
from datetime import datetime, timedelta

import pytest

from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models import GenesisBlock, JoinCertificate, NetworkAuthority, PolicyManifestRef
from genesis_mesh.node.node import MeshNode
from genesis_mesh.node.runtime import MeshNodeRuntime


def _make_signed_genesis(root_keypair, na_keypair) -> GenesisBlock:
    """Create a root-signed genesis block for integration tests."""
    now = datetime.utcnow()
    genesis = GenesisBlock(
        network_name="integration",
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
    genesis.signatures.append(sign_model(genesis, root_keypair.private_key, "root-test"))
    return genesis


def _make_join_certificate(node_keypair, genesis: GenesisBlock, na_keypair) -> JoinCertificate:
    """Create an NA-signed join certificate for a node."""
    now = datetime.utcnow()
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


async def _wait_for(predicate, timeout: float = 5.0) -> None:
    """Wait until a predicate returns true or fail the test."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("Timed out waiting for integration condition")


@pytest.mark.asyncio
async def test_three_node_runtime_routes_data_through_intermediate_peer():
    """Node A routes DATA to node C through node B."""
    root_keypair = generate_keypair()
    na_keypair = generate_keypair()
    genesis = _make_signed_genesis(root_keypair, na_keypair)

    node_a = _make_joined_node(genesis, na_keypair)
    node_b = _make_joined_node(genesis, na_keypair)
    node_c = _make_joined_node(genesis, na_keypair)

    runtime_a = MeshNodeRuntime(node_a, "http://127.0.0.1:9", "127.0.0.1", 0)
    runtime_b = MeshNodeRuntime(node_b, "http://127.0.0.1:9", "127.0.0.1", 0)
    runtime_c = MeshNodeRuntime(node_c, "http://127.0.0.1:9", "127.0.0.1", 0)

    await runtime_a.start()
    await runtime_b.start()
    await runtime_c.start()
    try:
        await runtime_a._connect_endpoint(f"127.0.0.1:{runtime_b.bound_port}")
        await runtime_b._connect_endpoint(f"127.0.0.1:{runtime_c.bound_port}")

        await _wait_for(
            lambda: runtime_b.peer_manager.get_peer(node_a.node_keypair.public_key_b64)
            and runtime_b.peer_manager.get_peer(node_c.node_keypair.public_key_b64)
        )

        await runtime_b.routing_protocol.trigger_update()
        await _wait_for(
            lambda: runtime_a.routing_table.get_route(node_c.node_keypair.public_key_b64)
        )

        delivered = []
        original_route_message = runtime_c.router.route_message

        async def record_delivery(message):
            """Record local delivery on node C."""
            if message.recipient_id == runtime_c.node_id:
                delivered.append(message)
            return await original_route_message(message)

        runtime_c.router.route_message = record_delivery

        assert await runtime_a.router.send_to(node_c.node_keypair.public_key_b64, b"hello")
        await _wait_for(lambda: len(delivered) == 1)
    finally:
        await runtime_a.stop()
        await runtime_b.stop()
        await runtime_c.stop()
