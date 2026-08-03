"""F-20 (mesh side): a peer recovers from a superseded certificate on re-announce.

Revoking a renewed node's predecessor only reaches peers through CRL gossip, while
each peer caches that node's certificate by node public key -- which renewal does
not change. These tests pin the resulting window: a peer holding the stale
certificate plus the new CRL treats the node as revoked, and recovers as soon as
the node re-announces with its renewed certificate.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

from genesis_mesh.crypto import generate_keypair, sign_data, sign_model
from genesis_mesh.gossip.crl_gossip import CRLGossip
from genesis_mesh.models import (
    CertificateRevocationList,
    GenesisBlock,
    JoinCertificate,
    NetworkAuthority,
    PolicyManifestRef,
    RevokedCertificate,
)
from genesis_mesh.node.peer_identity import RuntimePeerIdentity
from genesis_mesh.transport.protocol import PeerInfo


class _StubNode:
    """The minimal node surface RuntimePeerIdentity reads."""

    def __init__(self, genesis_block, node_keypair, join_certificate):
        self.genesis_block = genesis_block
        self.node_keypair = node_keypair
        self.join_certificate = join_certificate


def _genesis(na_keypair) -> GenesisBlock:
    now = datetime.now(timezone.utc)
    return GenesisBlock(
        network_name="testnet",
        network_version="v0.1",
        root_public_key=na_keypair.public_key_b64,
        network_authority=NetworkAuthority(
            public_key=na_keypair.public_key_b64,
            valid_from=now - timedelta(hours=1),
            valid_to=now + timedelta(days=90),
        ),
        policy_manifest=PolicyManifestRef(hash="sha256:test"),
        bootstrap_anchors=[],
        signatures=[],
    )


def _cert(node_keypair, genesis, na_keypair) -> JoinCertificate:
    """Mint an NA-signed certificate; each call is a distinct cert_id."""
    now = datetime.now(timezone.utc)
    cert = JoinCertificate(
        cert_id=str(uuid.uuid4()),
        node_public_key=node_keypair.public_key_b64,
        network_name=genesis.network_name,
        roles=["role:client"],
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        issued_by="na-2025-q1",
        signatures=[],
    )
    cert.signatures.append(sign_model(cert, na_keypair.private_key, "na-2025-q1"))
    return cert


def _announcement(cert: JoinCertificate, node_keypair) -> PeerInfo:
    """Build the signed announcement a renewed node gossips about itself."""
    peer_info = PeerInfo(
        node_id=cert.node_public_key,
        endpoint="127.0.0.1:9000",
        roles=cert.roles,
        cert_id=cert.cert_id,
        certificate_b64=RuntimePeerIdentity.certificate_b64(cert),
        announcement_issued_at=time.time(),
        announcement_nonce=str(uuid.uuid4()),
    )
    peer_info.announcement_signature = sign_data(
        peer_info.announcement_canonical_json().encode("utf-8"),
        node_keypair.private_key,
    )
    return peer_info


def _crl_revoking(cert_id: str, na_key_id: str = "na-2025-q1") -> CertificateRevocationList:
    now = datetime.now(timezone.utc)
    crl = CertificateRevocationList.create_empty(issuer=na_key_id, sequence=1)
    crl.revoked_certificates.append(
        RevokedCertificate(
            certificate_id=cert_id,
            revoked_at=now,
            reason="superseded",
            issuer=na_key_id,
        )
    )
    return crl


def _identity(na_keypair, genesis):
    """Build a peer-identity validator for an observing node."""
    local_keypair = generate_keypair()
    local_cert = _cert(local_keypair, genesis, na_keypair)
    node = _StubNode(genesis, local_keypair, local_cert)
    crl_gossip = CRLGossip(
        node_id=local_keypair.public_key_b64,
        get_public_key=lambda key_id: na_keypair.public_key_b64,
        broadcast_func=None,
    )
    return (
        RuntimePeerIdentity(
            node=node,
            node_id=local_keypair.public_key_b64,
            crl_gossip=crl_gossip,
            peer_certs_by_id={},
            peer_certs_by_node_id={},
        ),
        crl_gossip,
    )


def test_stale_cached_certificate_makes_a_renewed_peer_look_revoked():
    """The window the grace period exists to cover, demonstrated end to end."""
    na_keypair = generate_keypair()
    genesis = _genesis(na_keypair)
    identity, crl_gossip = _identity(na_keypair, genesis)

    peer_keypair = generate_keypair()
    old_cert = _cert(peer_keypair, genesis, na_keypair)
    new_cert = _cert(peer_keypair, genesis, na_keypair)
    assert old_cert.cert_id != new_cert.cert_id
    assert old_cert.node_public_key == new_cert.node_public_key

    # The peer is known through its pre-renewal announcement.
    accepted, _ = identity.verify_peer_info(_announcement(old_cert, peer_keypair))
    assert accepted is True
    assert identity.is_peer_revoked(peer_keypair.public_key_b64) is False

    # The CRL carrying the superseded predecessor arrives first.
    crl_gossip.set_crl(_crl_revoking(old_cert.cert_id))
    assert identity.is_peer_revoked(peer_keypair.public_key_b64) is True

    # The renewed node's next announcement clears it.
    accepted, roles = identity.verify_peer_info(_announcement(new_cert, peer_keypair))
    assert accepted is True
    assert roles == ["role:client"]
    assert identity.is_peer_revoked(peer_keypair.public_key_b64) is False


def test_superseded_certificate_is_still_refused_on_its_own():
    """Recovery is not a bypass: the predecessor itself stays rejected."""
    na_keypair = generate_keypair()
    genesis = _genesis(na_keypair)
    identity, crl_gossip = _identity(na_keypair, genesis)

    peer_keypair = generate_keypair()
    old_cert = _cert(peer_keypair, genesis, na_keypair)
    new_cert = _cert(peer_keypair, genesis, na_keypair)

    crl_gossip.set_crl(_crl_revoking(old_cert.cert_id))
    identity.verify_peer_info(_announcement(new_cert, peer_keypair))

    accepted, roles = identity.verify_peer_info(_announcement(old_cert, peer_keypair))
    assert accepted is False
    assert roles == []
