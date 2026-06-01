"""Unit tests for the AgentDescriptor model."""

from datetime import datetime, timedelta, timezone

import pytest

from genesis_mesh.crypto import generate_keypair, sign_model, verify_model_signature
from genesis_mesh.models import AgentDescriptor, AgentEndpoint


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_descriptor(node_public_key: str) -> AgentDescriptor:
    return AgentDescriptor(
        agent_id="llm-1",
        node_public_key=node_public_key,
        network_name="USG",
        capabilities=["llm:chat", "llm:openai/gpt-4o-mini"],
        endpoint=AgentEndpoint(host="127.0.0.1", port=7448),
        registered_at=_now(),
        expires_at=_now() + timedelta(minutes=10),
        metadata={"model": "gpt-4o-mini"},
    )


def test_descriptor_round_trips_through_json():
    """to_canonical_json + model_validate_json should round-trip."""
    keypair = generate_keypair()
    descriptor = _make_descriptor(keypair.public_key_b64)
    descriptor.signatures.append(
        sign_model(descriptor, keypair.private_key, key_id=keypair.public_key_b64)
    )

    raw = descriptor.model_dump_json()
    parsed = AgentDescriptor.model_validate_json(raw)

    assert parsed.agent_id == "llm-1"
    assert parsed.capabilities == ["llm:chat", "llm:openai/gpt-4o-mini"]
    assert parsed.endpoint.host == "127.0.0.1"
    assert parsed.endpoint.port == 7448
    assert parsed.endpoint.to_uri() == "ws://127.0.0.1:7448"


def test_descriptor_signature_validates_against_node_key():
    """The signature verifies against the node_public_key embedded in the descriptor."""
    keypair = generate_keypair()
    descriptor = _make_descriptor(keypair.public_key_b64)
    descriptor.signatures.append(
        sign_model(descriptor, keypair.private_key, key_id=keypair.public_key_b64)
    )

    assert verify_model_signature(
        descriptor, descriptor.signatures[0], keypair.public_key_b64
    )


def test_descriptor_signature_rejects_a_different_key():
    """A signature by one key must not verify under another key."""
    keypair_a = generate_keypair()
    keypair_b = generate_keypair()
    descriptor = _make_descriptor(keypair_a.public_key_b64)
    descriptor.signatures.append(
        sign_model(descriptor, keypair_a.private_key, key_id=keypair_a.public_key_b64)
    )

    assert not verify_model_signature(
        descriptor, descriptor.signatures[0], keypair_b.public_key_b64
    )


def test_descriptor_rejects_inverted_expiry_window():
    """expires_at <= registered_at must raise at construction time."""
    now = _now()
    with pytest.raises(ValueError):
        AgentDescriptor(
            agent_id="llm-1",
            node_public_key="x" * 44,
            network_name="USG",
            capabilities=[],
            endpoint=AgentEndpoint(host="127.0.0.1", port=7448),
            registered_at=now,
            expires_at=now - timedelta(seconds=1),
        )


def test_is_active_returns_false_after_expiry():
    """is_active should switch to False once expires_at has passed."""
    keypair = generate_keypair()
    descriptor = _make_descriptor(keypair.public_key_b64)
    # Force a past expiry by bypassing validation through direct mutation.
    descriptor.expires_at = _now() - timedelta(seconds=1)
    assert not descriptor.is_active()
