"""Tests for Network Authority recognition treaty routes."""

from __future__ import annotations

from .na_server_helpers import admin_headers


def _issue_treaty(client, na_service, allowed_roles=None):
    """Issue an operator-authorized recognition treaty through the API."""
    body = {
        "subject_sovereign_id": "sovereign-b",
        "subject_public_keys": [na_service.genesis_block.network_authority.public_key],
        "scope": {"allowed_roles": allowed_roles or ["role:client"]},
        "validity_hours": 24,
    }
    return client.post(
        "/admin/recognition-treaties",
        json=body,
        headers=admin_headers(client, body),
    )


def _issue_attestation(client, subject_id: str = "alice", roles=None):
    """Issue an operator-authorized membership attestation through the API."""
    body = {
        "issuer_sovereign_id": "sovereign-b",
        "subject_id": subject_id,
        "subject_public_key": "subject-public-key",
        "roles": roles or ["role:client"],
        "validity_hours": 24,
    }
    return client.post(
        "/admin/attestations",
        json=body,
        headers=admin_headers(client, body),
    )


def test_admin_can_issue_recognition_treaty(client, na_service):
    """An operator can issue a signed treaty for another sovereign."""
    resp = _issue_treaty(client, na_service)

    assert resp.status_code == 201
    treaty = resp.get_json()
    assert treaty["issuer_sovereign_id"] == "TEST"
    assert treaty["subject_sovereign_id"] == "sovereign-b"
    assert treaty["scope"]["allowed_roles"] == ["role:client"]
    assert treaty["signatures"]

    stored = client.get(f"/recognition-treaties/{treaty['treaty_id']}")
    assert stored.status_code == 200
    assert stored.get_json()["status"] == "active"


def test_treaty_verification_accepts_signed_treaty(client, na_service):
    """The public verifier accepts a valid signed treaty."""
    treaty = _issue_treaty(client, na_service).get_json()

    resp = client.post("/recognition-treaties/verify", json={"treaty": treaty})

    assert resp.status_code == 200
    assert resp.get_json()["accepted"] is True
    assert resp.get_json()["reason"] == "accepted"


def test_attestation_verify_with_treaty_accepts_scoped_role(client, na_service):
    """A treaty can back acceptance of a subject sovereign's attestation."""
    treaty = _issue_treaty(client, na_service).get_json()
    attestation = _issue_attestation(client).get_json()

    resp = client.post(
        "/attestations/verify-with-treaty",
        json={"attestation": attestation, "treaty": treaty},
    )

    assert resp.status_code == 200
    assert resp.get_json()["accepted"] is True
    assert resp.get_json()["reason"] == "accepted"


def test_attestation_verify_with_treaty_rejects_role_outside_scope(client, na_service):
    """Treaty role scope limits which attestations are accepted."""
    treaty = _issue_treaty(client, na_service, allowed_roles=["role:anchor"]).get_json()
    attestation = _issue_attestation(client, roles=["role:client"]).get_json()

    resp = client.post(
        "/attestations/verify-with-treaty",
        json={"attestation": attestation, "treaty": treaty},
    )

    assert resp.status_code == 200
    assert resp.get_json()["accepted"] is False
    assert resp.get_json()["reason"] == "attestation_role_not_allowed"


def test_revoking_treaty_changes_treaty_backed_verification(client, na_service):
    """A revoked treaty cannot continue backing attestation verification."""
    treaty = _issue_treaty(client, na_service).get_json()
    attestation = _issue_attestation(client).get_json()

    revoke_body = {"reason": "relationship_ended"}
    revoke = client.post(
        f"/admin/recognition-treaties/{treaty['treaty_id']}/revoke",
        json=revoke_body,
        headers=admin_headers(client, revoke_body),
    )
    assert revoke.status_code == 200

    resp = client.post(
        "/attestations/verify-with-treaty",
        json={"attestation": attestation, "treaty": treaty},
    )

    assert resp.status_code == 200
    assert resp.get_json()["accepted"] is False
    assert resp.get_json()["reason"] == "treaty_locally_revoked"


def test_recognition_graph_exports_edges_and_revoked_material(client, na_service):
    """The graph export exposes sovereign nodes, treaty edges, and revocations."""
    treaty = _issue_treaty(client, na_service).get_json()
    revoke_body = {"reason": "relationship_ended"}
    client.post(
        f"/admin/recognition-treaties/{treaty['treaty_id']}/revoke",
        json=revoke_body,
        headers=admin_headers(client, revoke_body),
    )

    resp = client.get("/recognition-graph")

    assert resp.status_code == 200
    graph = resp.get_json()
    assert {"sovereign_id": "TEST"} in graph["sovereigns"]
    assert {"sovereign_id": "sovereign-b"} in graph["sovereigns"]
    assert graph["recognition_edges"][0]["from"] == "TEST"
    assert graph["recognition_edges"][0]["to"] == "sovereign-b"
    assert graph["recognition_edges"][0]["status"] == "revoked"
    assert graph["revoked_trust_material"][0]["id"] == treaty["treaty_id"]


def test_treaty_issue_requires_operator_signature(client, na_service):
    """Treaty issuance rejects missing operator authentication."""
    resp = client.post(
        "/admin/recognition-treaties",
        json={
            "subject_sovereign_id": "sovereign-b",
            "subject_public_keys": [na_service.genesis_block.network_authority.public_key],
        },
    )

    assert resp.status_code == 401
