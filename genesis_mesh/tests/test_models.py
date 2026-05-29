"""Tests for data models."""

import pytest
from datetime import datetime, timedelta, timezone
from genesis_mesh.models import (
    GenesisBlock,
    NetworkAuthority,
    PolicyManifestRef,
    JoinCertificate,
    PolicyManifest
)


def test_genesis_block_creation():
    """Test genesis block model creation."""
    now = datetime.now(timezone.utc)

    genesis = GenesisBlock(
        network_name="USG",
        network_version="v0.1",
        root_public_key="test-root-key",
        network_authority=NetworkAuthority(
            public_key="test-na-key",
            valid_from=now,
            valid_to=now + timedelta(days=90)
        ),
        policy_manifest=PolicyManifestRef(
            hash="sha256:test",
            url="https://example.com/policy.json"
        )
    )

    assert genesis.network_name == "USG"
    assert genesis.network_version == "v0.1"
    assert len(genesis.allowed_crypto_suites) > 0
    assert len(genesis.allowed_transports) > 0


def test_join_certificate_validity():
    """Test join certificate validity checking."""
    now = datetime.now(timezone.utc)

    # Valid certificate
    cert = JoinCertificate(
        cert_id="test-123",
        node_public_key="test-key",
        network_name="USG",
        roles=["role:client"],
        issued_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=23),
        issued_by="na-2025-q1"
    )

    assert cert.is_valid(now)

    # Expired certificate
    expired_cert = JoinCertificate(
        cert_id="test-456",
        node_public_key="test-key",
        network_name="USG",
        roles=["role:client"],
        issued_at=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
        issued_by="na-2025-q1"
    )

    assert not expired_cert.is_valid(now)

    # Not yet valid certificate
    future_cert = JoinCertificate(
        cert_id="test-789",
        node_public_key="test-key",
        network_name="USG",
        roles=["role:client"],
        issued_at=now + timedelta(hours=1),
        expires_at=now + timedelta(days=1),
        issued_by="na-2025-q1"
    )

    assert not future_cert.is_valid(now)


def test_policy_manifest_creation():
    """Test policy manifest model creation."""
    now = datetime.now(timezone.utc)

    policy = PolicyManifest(
        policy_id="policy-usg-v0.1",
        issued_at=now,
        issued_by="na-2025-q1",
        min_client_version="1.0.0",
        allowed_services=["service‑1", "service‑2"]
    )

    assert policy.policy_id == "policy-usg-v0.1"
    assert len(policy.allowed_ports) > 0
    assert "service‑1" in policy.allowed_services
    assert policy.routing.max_hops == 6


def test_canonical_json_excludes_signatures():
    """Test that canonical JSON excludes signatures."""
    now = datetime.now(timezone.utc)

    cert = JoinCertificate(
        cert_id="test-123",
        node_public_key="test-key",
        network_name="USG",
        roles=["role:client"],
        issued_at=now,
        expires_at=now + timedelta(days=1),
        issued_by="na-2025-q1"
    )

    canonical = cert.to_canonical_json()
    assert "signatures" not in canonical
    assert "cert_id" in canonical
    assert "node_public_key" in canonical
