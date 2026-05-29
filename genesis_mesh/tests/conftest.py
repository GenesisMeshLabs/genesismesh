"""Shared pytest fixtures for Genesis Mesh tests."""

from __future__ import annotations

from datetime import datetime, timedelta

import nacl.encoding
import nacl.signing
import pytest

from genesis_mesh.crypto import generate_keypair
from genesis_mesh.models import GenesisBlock, NetworkAuthority, PolicyManifestRef
from genesis_mesh.na_service.server import NetworkAuthorityService


@pytest.fixture
def na_service():
    """Create a NetworkAuthorityService with test NA and operator keys."""
    signing_key = nacl.signing.SigningKey.generate()
    operator_keypair = generate_keypair()
    pub_b64 = signing_key.verify_key.encode(
        encoder=nacl.encoding.Base64Encoder,
    ).decode("utf-8")

    now = datetime.utcnow()
    genesis = GenesisBlock(
        network_name="TEST",
        network_version="v0.1",
        root_public_key=pub_b64,
        network_authority=NetworkAuthority(
            public_key=pub_b64,
            valid_from=now,
            valid_to=now + timedelta(days=90),
        ),
        policy_manifest=PolicyManifestRef(hash="sha256:test", url=None),
    )

    service = NetworkAuthorityService(
        genesis_block=genesis,
        na_private_key=signing_key,
        key_id="test-key",
        operator_public_keys={"operator-test": operator_keypair.public_key_b64},
    )
    setattr(service, "_test_operator_keypair", operator_keypair)
    return service


@pytest.fixture
def client(na_service):
    """Create a Flask test client for the Network Authority."""
    na_service.app.config["TESTING"] = True
    test_client = na_service.app.test_client()
    setattr(test_client, "operator_keypair", getattr(na_service, "_test_operator_keypair"))
    return test_client


@pytest.fixture
def node_keypair():
    """Generate a fresh Ed25519 keypair for a test node."""
    return generate_keypair()
