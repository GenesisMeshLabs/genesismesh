"""Tests for cryptographic operations."""

import pytest
from genesis_mesh.crypto import (
    generate_keypair,
    sign_data,
    verify_signature,
    sign_model,
    verify_model_signature
)
from genesis_mesh.models import GenesisBlock, NetworkAuthority, PolicyManifestRef
from datetime import datetime, timedelta


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
    now = datetime.utcnow()

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
    now = datetime.utcnow()
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
