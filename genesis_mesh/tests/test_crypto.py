"""Tests for cryptographic operations."""

import pytest
from genesis_mesh.crypto import (
    generate_keypair,
    sign_data,
    verify_signature,
    sign_model,
    verify_model_signature
)
from genesis_mesh.models import GenesisBlock, NetworkAuthority, PolicyManifest, PolicyManifestRef
from genesis_mesh.node.node import MeshNode
from datetime import datetime, timedelta, timezone


def test_keypair_generation():
    """Test Ed25519 keypair generation."""
    keypair = generate_keypair()
    assert keypair.private_key is not None
    assert keypair.public_key is not None
    assert len(keypair.public_key_b64) > 0
    assert len(keypair.private_key_b64) > 0


def test_sign_and_verify():
    """Test signing and verification of raw data."""
    keypair = generate_keypair()
    data = b"Hello, Genesis Mesh!"

    # Sign data
    signature = sign_data(data, keypair.private_key)
    assert len(signature) > 0

    # Verify with correct key
    assert verify_signature(data, signature, keypair.public_key)

    # Verify fails with wrong key
    wrong_keypair = generate_keypair()
    assert not verify_signature(data, signature, wrong_keypair.public_key)

    # Verify fails with tampered data
    assert not verify_signature(b"Tampered data", signature, keypair.public_key)


def test_model_signing():
    """Test signing and verification of Pydantic models."""
    keypair = generate_keypair()
    now = datetime.now(timezone.utc)

    # Create a genesis block
    genesis = GenesisBlock(
        network_name="TEST",
        network_version="v0.1",
        root_public_key=keypair.public_key_b64,
        network_authority=NetworkAuthority(
            public_key=keypair.public_key_b64,
            valid_from=now,
            valid_to=now + timedelta(days=90)
        ),
        policy_manifest=PolicyManifestRef(
            hash="sha256:test",
            url=None
        )
    )

    # Sign the model
    signature = sign_model(genesis, keypair.private_key, "test-key")
    assert signature.key_id == "test-key"
    assert len(signature.sig) > 0

    # Verify signature
    assert verify_model_signature(genesis, signature, keypair.public_key)

    # Verify fails with wrong key
    wrong_keypair = generate_keypair()
    assert not verify_model_signature(genesis, signature, wrong_keypair.public_key)


def test_canonical_json():
    """Test canonical JSON generation for consistent signing."""
    now = datetime.now(timezone.utc)
    keypair = generate_keypair()

    genesis1 = GenesisBlock(
        network_name="TEST",
        network_version="v0.1",
        root_public_key=keypair.public_key_b64,
        network_authority=NetworkAuthority(
            public_key=keypair.public_key_b64,
            valid_from=now,
            valid_to=now + timedelta(days=90)
        ),
        policy_manifest=PolicyManifestRef(
            hash="sha256:test",
            url=None
        )
    )

    genesis2 = GenesisBlock(
        network_name="TEST",
        network_version="v0.1",
        root_public_key=keypair.public_key_b64,
        network_authority=NetworkAuthority(
            public_key=keypair.public_key_b64,
            valid_from=now,
            valid_to=now + timedelta(days=90)
        ),
        policy_manifest=PolicyManifestRef(
            hash="sha256:test",
            url=None
        )
    )

    # Same data should produce same canonical JSON
    assert genesis1.to_canonical_json() == genesis2.to_canonical_json()

    # Sign both
    sig1 = sign_model(genesis1, keypair.private_key, "key1")
    sig2 = sign_model(genesis2, keypair.private_key, "key1")

    # Signatures should be identical for identical data
    assert sig1.sig == sig2.sig


def test_node_rejects_policy_signed_by_wrong_key():
    """Client-side policy verification rejects policies not signed by the NA key."""
    root_keypair = generate_keypair()
    na_keypair = generate_keypair()
    wrong_keypair = generate_keypair()
    node_keypair = generate_keypair()
    now = datetime.now(timezone.utc)
    genesis = GenesisBlock(
        network_name="TEST",
        network_version="v0.1",
        root_public_key=root_keypair.public_key_b64,
        network_authority=NetworkAuthority(
            public_key=na_keypair.public_key_b64,
            valid_from=now,
            valid_to=now + timedelta(days=90),
        ),
        policy_manifest=PolicyManifestRef(hash="sha256:test", url=None),
    )
    genesis.signatures.append(sign_model(genesis, root_keypair.private_key, "root-test"))
    policy = PolicyManifest(
        policy_id="policy-test",
        issued_at=now,
        issued_by="wrong-key",
        min_client_version="0.1.0",
        allowed_ports=[443],
        allowed_services=["svc"],
    )
    policy.signatures.append(sign_model(policy, wrong_keypair.private_key, "wrong-key"))
    node = MeshNode(genesis, node_keypair)

    assert node._verify_policy_manifest(policy) is False
