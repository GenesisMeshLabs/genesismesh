"""Integration tests for the NA /agents discovery routes."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest

from genesis_mesh.crypto import generate_keypair, sign_data, sign_model
from genesis_mesh.models import AgentDescriptor, AgentEndpoint

from .na_server_helpers import admin_headers, create_invite, revoke_cert, sign_payload


def _enroll(client, node_keypair):
    """Enroll a node and return the join certificate response payload."""
    invite_resp = create_invite(client, roles=["role:anchor"])
    assert invite_resp.status_code == 201, invite_resp.get_json()
    token_id = invite_resp.get_json()["token_id"]
    join_body = sign_payload(
        {
            "node_public_key": node_keypair.public_key_b64,
            "invite_token": token_id,
            "validity_hours": 24,
        },
        node_keypair.private_key,
    )
    resp = client.post("/join", json=join_body)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def _build_signed_descriptor(
    node_keypair,
    *,
    network_name,
    capabilities,
    ttl_seconds=600,
    agent_id="llm-1",
):
    now = datetime.now(timezone.utc)
    descriptor = AgentDescriptor(
        agent_id=agent_id,
        node_public_key=node_keypair.public_key_b64,
        network_name=network_name,
        capabilities=list(capabilities),
        endpoint=AgentEndpoint(host="127.0.0.1", port=7448),
        registered_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
        metadata={"model": "gpt-4o-mini"},
    )
    descriptor.signatures.append(
        sign_model(descriptor, node_keypair.private_key, key_id=node_keypair.public_key_b64)
    )
    return descriptor


def test_post_agents_registers_signed_descriptor(client, na_service):
    """Happy path: enrolled node POSTs a signed descriptor, gets 200."""
    node_keypair = generate_keypair()
    _enroll(client, node_keypair)
    descriptor = _build_signed_descriptor(
        node_keypair,
        network_name=na_service.genesis_block.network_name,
        capabilities=["llm:chat", "llm:openai/gpt-4o-mini"],
    )
    resp = client.post("/agents", json=descriptor.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "registered"


def test_post_agents_rejects_unenrolled_node(client, na_service):
    """A node without a valid join certificate cannot register an agent."""
    node_keypair = generate_keypair()  # never enrolled
    descriptor = _build_signed_descriptor(
        node_keypair,
        network_name=na_service.genesis_block.network_name,
        capabilities=["llm:chat"],
    )
    resp = client.post("/agents", json=descriptor.model_dump(mode="json"))
    assert resp.status_code == 403


def test_post_agents_rejects_wrong_signature(client, na_service):
    """A descriptor signed by the wrong key must be refused."""
    node_keypair = generate_keypair()
    impostor = generate_keypair()
    _enroll(client, node_keypair)
    descriptor = _build_signed_descriptor(
        node_keypair,
        network_name=na_service.genesis_block.network_name,
        capabilities=["llm:chat"],
    )
    # Replace the signature with one made by the impostor key.
    descriptor.signatures[0] = sign_model(
        descriptor, impostor.private_key, key_id=node_keypair.public_key_b64
    )
    resp = client.post("/agents", json=descriptor.model_dump(mode="json"))
    assert resp.status_code == 401


def test_post_agents_rejects_wrong_network_name(client, na_service):
    """Descriptors for a different network must be rejected."""
    node_keypair = generate_keypair()
    _enroll(client, node_keypair)
    descriptor = _build_signed_descriptor(
        node_keypair,
        network_name="OTHER",
        capabilities=["llm:chat"],
    )
    resp = client.post("/agents", json=descriptor.model_dump(mode="json"))
    assert resp.status_code == 400


def test_get_agents_filters_by_capability(client, na_service):
    """GET /agents?capability=foo returns only matching registrations."""
    keypair_a = generate_keypair()
    keypair_b = generate_keypair()
    _enroll(client, keypair_a)
    _enroll(client, keypair_b)

    desc_a = _build_signed_descriptor(
        keypair_a,
        network_name=na_service.genesis_block.network_name,
        capabilities=["llm:chat", "llm:openai/gpt-4o-mini"],
    )
    desc_b = _build_signed_descriptor(
        keypair_b,
        network_name=na_service.genesis_block.network_name,
        capabilities=["kb:security"],
    )
    client.post("/agents", json=desc_a.model_dump(mode="json"))
    client.post("/agents", json=desc_b.model_dump(mode="json"))

    matching = client.get("/agents?capability=llm:chat").get_json()
    assert matching["count"] == 1
    assert matching["agents"][0]["node_public_key"] == keypair_a.public_key_b64

    matching_kb = client.get("/agents?capability=kb:security").get_json()
    assert matching_kb["count"] == 1
    assert matching_kb["agents"][0]["node_public_key"] == keypair_b.public_key_b64

    all_agents = client.get("/agents").get_json()
    assert all_agents["count"] == 2


def test_revoke_evicts_agent_registration_for_capability_discovery(client, na_service):
    """Revoked providers are removed from capability discovery results."""
    keypair_a = generate_keypair()
    keypair_b = generate_keypair()
    cert_a = _enroll(client, keypair_a)
    _enroll(client, keypair_b)

    desc_a = _build_signed_descriptor(
        keypair_a,
        network_name=na_service.genesis_block.network_name,
        capabilities=["repo.summary"],
        agent_id="repo-agent-a",
    )
    desc_b = _build_signed_descriptor(
        keypair_b,
        network_name=na_service.genesis_block.network_name,
        capabilities=["repo.summary"],
        agent_id="repo-agent-b",
    )
    client.post("/agents", json=desc_a.model_dump(mode="json"))
    client.post("/agents", json=desc_b.model_dump(mode="json"))

    before = client.get("/agents?capability=repo.summary").get_json()
    assert before["count"] == 2

    revoke_resp = revoke_cert(client, cert_a["cert_id"], reason="key_compromise")
    assert revoke_resp.status_code == 200

    after = client.get("/agents?capability=repo.summary").get_json()
    assert after["count"] == 1
    assert after["agents"][0]["agent_id"] == "repo-agent-b"


def test_delete_agents_requires_valid_signature(client, na_service):
    """DELETE /agents/{key} must be signed by the node key."""
    keypair = generate_keypair()
    _enroll(client, keypair)
    descriptor = _build_signed_descriptor(
        keypair,
        network_name=na_service.genesis_block.network_name,
        capabilities=["llm:chat"],
    )
    client.post("/agents", json=descriptor.model_dump(mode="json"))

    signed_at = datetime.now(timezone.utc).isoformat()
    envelope = f"delete-agent|v1|{keypair.public_key_b64}|{signed_at}".encode("utf-8")
    signature = sign_data(envelope, keypair.private_key)
    encoded_node_key = quote(keypair.public_key_b64, safe="")

    resp = client.delete(
        f"/agents/{encoded_node_key}",
        json={"version": "v1", "signed_at": signed_at, "signature": signature},
    )
    assert resp.status_code == 200

    # Second delete is now a 404.
    resp2 = client.delete(
        f"/agents/{encoded_node_key}",
        json={"version": "v1", "signed_at": signed_at, "signature": signature},
    )
    assert resp2.status_code in (401, 404)
