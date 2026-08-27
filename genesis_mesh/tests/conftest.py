"""Shared pytest fixtures for Genesis Mesh tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import nacl.encoding
import nacl.signing
import pytest

from genesis_mesh.audit import logger as audit_logger_module
from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models import GenesisBlock, NetworkAuthority, PolicyManifestRef
from genesis_mesh.na_service.server import NetworkAuthorityService


@pytest.fixture(autouse=True)
def _audit_logs_to_tmp(tmp_path, monkeypatch):
    """Keep default-on audit logs (F-03) out of the real ~/.genesis-mesh."""
    monkeypatch.setattr(
        audit_logger_module, "DEFAULT_AUDIT_DIR", tmp_path / "audit"
    )


@pytest.fixture
def na_service():
    """Create a NetworkAuthorityService with test NA and operator keys."""
    signing_key = nacl.signing.SigningKey.generate()
    operator_keypair = generate_keypair()
    pub_b64 = signing_key.verify_key.encode(
        encoder=nacl.encoding.Base64Encoder,
    ).decode("utf-8")

    now = datetime.now(timezone.utc)
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
    # F-11: the NA now verifies genesis signatures at boot; the fixture's
    # root key is the NA key, so sign with it.
    genesis.signatures.append(sign_model(genesis, signing_key, "root"))

    service = NetworkAuthorityService(
        genesis_block=genesis,
        na_private_key=signing_key,
        key_id="test-key",
        operator_public_keys={"operator-test": operator_keypair.public_key_b64},
        # F-21: every operator key must declare a tier. Fixtures use
        # privileged so existing tests keep the access they had.
        operator_key_tiers={"operator-test": "privileged"},
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
