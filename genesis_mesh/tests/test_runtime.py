"""Runtime-level tests for authenticated peer connection setup."""

import asyncio
import logging
from datetime import datetime, timedelta

import pytest
import websockets

from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models import (
    BootstrapAnchor,
    CertificateRevocationList,
    GenesisBlock,
    JoinCertificate,
    NetworkAuthority,
    PolicyManifestRef,
    RevokedCertificate,
)
from genesis_mesh.node.node import MeshNode
from genesis_mesh.node.runtime import MeshNodeRuntime
from genesis_mesh.node.runtime import _ExpectedWebSocketProbeFilter


def _make_signed_genesis(root_keypair, na_keypair) -> GenesisBlock:
    """Create a root-signed genesis block for runtime tests."""
    now = datetime.utcnow()
    genesis = GenesisBlock(
        network_name="testnet",
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
    """Create an NA-signed join certificate for a test node."""
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


def _make_join_certificate_with_issuer(
    node_keypair,
    genesis: GenesisBlock,
    na_keypair,
    issuer: str,
) -> JoinCertificate:
    """Create an NA-signed join certificate with a custom issuer key ID."""
    cert = _make_join_certificate(node_keypair, genesis, na_keypair)
    cert.issued_by = issuer
    cert.signatures = [sign_model(cert, na_keypair.private_key, issuer)]
    return cert


def _make_joined_node(genesis: GenesisBlock, na_keypair) -> MeshNode:
    """Create a `MeshNode` with a pre-issued join certificate."""
    node_keypair = generate_keypair()
    node = MeshNode(
        genesis_block=genesis,
        node_keypair=node_keypair,
        roles=["role:anchor"],
    )
    node.join_certificate = _make_join_certificate(node_keypair, genesis, na_keypair)
    return node


@pytest.mark.asyncio
async def test_runtime_connects_peer_with_noise_and_verified_certificate():
    """Two runtimes complete Noise auth and register direct peer routes."""
    root_keypair = generate_keypair()
    na_keypair = generate_keypair()
    genesis = _make_signed_genesis(root_keypair, na_keypair)

    node_a = _make_joined_node(genesis, na_keypair)
    node_b = _make_joined_node(genesis, na_keypair)

    runtime_a = MeshNodeRuntime(
        node_a,
        na_endpoint="http://127.0.0.1:9",
        listen_host="127.0.0.1",
        listen_port=0,
    )
    runtime_b = MeshNodeRuntime(
        node_b,
        na_endpoint="http://127.0.0.1:9",
        listen_host="127.0.0.1",
        listen_port=0,
    )

    await runtime_a.start()
    await runtime_b.start()
    try:
        assert runtime_b.bound_port is not None
        await runtime_a._connect_endpoint(f"127.0.0.1:{runtime_b.bound_port}")

        # Give the inbound accept path time to register the peer.
        for _ in range(20):
            if runtime_b.peer_manager.get_peer(node_a.node_keypair.public_key_b64):
                break
            await asyncio.sleep(0.05)

        assert runtime_a.peer_manager.get_peer(node_b.node_keypair.public_key_b64)
        assert runtime_b.peer_manager.get_peer(node_a.node_keypair.public_key_b64)
        assert runtime_a.routing_table.get_route(node_b.node_keypair.public_key_b64)
        assert runtime_b.routing_table.get_route(node_a.node_keypair.public_key_b64)
    finally:
        await runtime_a.stop()
        await runtime_b.stop()


@pytest.mark.asyncio
async def test_runtime_rejects_revoked_peer_certificate():
    """A runtime does not register an inbound peer with a revoked certificate."""
    root_keypair = generate_keypair()
    na_keypair = generate_keypair()
    genesis = _make_signed_genesis(root_keypair, na_keypair)

    node_a = _make_joined_node(genesis, na_keypair)
    node_b = _make_joined_node(genesis, na_keypair)

    runtime_a = MeshNodeRuntime(
        node_a,
        na_endpoint="http://127.0.0.1:9",
        listen_host="127.0.0.1",
        listen_port=0,
    )
    runtime_b = MeshNodeRuntime(
        node_b,
        na_endpoint="http://127.0.0.1:9",
        listen_host="127.0.0.1",
        listen_port=0,
    )

    now = datetime.utcnow()
    crl = CertificateRevocationList(
        crl_id="crl-revoked-a",
        sequence=1,
        issued_at=now,
        next_update=now + timedelta(hours=1),
        issuer="na-2025-q1",
        revoked_certificates=[
            RevokedCertificate(
                certificate_id=node_a.join_certificate.cert_id,
                revoked_at=now,
                reason="key_compromise",
                issuer="na-2025-q1",
            )
        ],
        signatures=[],
    )
    crl.signatures.append(sign_model(crl, na_keypair.private_key, "na-2025-q1"))

    await runtime_a.start()
    await runtime_b.start()
    runtime_b.crl_gossip.set_crl(crl)
    try:
        assert runtime_b.bound_port is not None
        await runtime_a._connect_endpoint(f"127.0.0.1:{runtime_b.bound_port}")
        await asyncio.sleep(0.2)

        assert runtime_b.peer_manager.get_peer(node_a.node_keypair.public_key_b64) is None
    finally:
        await runtime_a.stop()
        await runtime_b.stop()


def test_runtime_bootstraps_crl_signed_by_local_na_key_id():
    """Runtime CRL bootstrap accepts the NA key ID from the local certificate."""
    root_keypair = generate_keypair()
    na_keypair = generate_keypair()
    genesis = _make_signed_genesis(root_keypair, na_keypair)

    node = _make_joined_node(genesis, na_keypair)
    node.join_certificate = _make_join_certificate_with_issuer(
        node.node_keypair,
        genesis,
        na_keypair,
        "na-local",
    )

    runtime = MeshNodeRuntime(
        node,
        na_endpoint="http://127.0.0.1:9",
        listen_host="127.0.0.1",
        listen_port=0,
    )

    assert runtime._get_public_key("na-local") == genesis.network_authority.public_key


def test_runtime_skips_bootstrap_anchor_matching_na_endpoint():
    """Runtime treats the NA HTTP API as control plane, not a peer anchor."""
    root_keypair = generate_keypair()
    na_keypair = generate_keypair()
    genesis = _make_signed_genesis(root_keypair, na_keypair)
    genesis.bootstrap_anchors = [BootstrapAnchor(id="na-http", endpoint="127.0.0.1:8443")]
    genesis.signatures = [sign_model(genesis, root_keypair.private_key, "root-test")]

    node = _make_joined_node(genesis, na_keypair)
    runtime = MeshNodeRuntime(
        node,
        na_endpoint="http://127.0.0.1:8443",
        listen_host="127.0.0.1",
        listen_port=0,
    )

    assert runtime._is_na_endpoint("127.0.0.1:8443")
    assert not runtime._is_na_endpoint("127.0.0.1:9443")


def test_expected_websocket_probe_filter_suppresses_browser_http_probe():
    """Browser HTTP probes of the peer WebSocket port should not log tracebacks."""
    log_filter = _ExpectedWebSocketProbeFilter()
    record = logging.LogRecord(
        name="genesis_mesh.peer_websocket",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="opening handshake failed",
        args=(),
        exc_info=(websockets.exceptions.InvalidUpgrade, None, None),
    )

    assert not log_filter.filter(record)
