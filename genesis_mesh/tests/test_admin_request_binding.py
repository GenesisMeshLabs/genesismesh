"""Admin signatures bind the request they authorise (v1.0.2 security fix).

Version 1 signed only the body, key ID, timestamp and nonce. A revoke signed
for one treaty could therefore be sent to another treaty's path, a signed GET
could be replayed against another admin route or with other query
parameters, and a request for one Network Authority could be replayed at
another that trusts the same operator key. Version 2 signs the method, path,
query and the target NA's public key as well.
"""

from __future__ import annotations

import pytest

from genesis_mesh.crypto.admin_auth import (
    admin_signing_payload,
    legacy_admin_signing_payload,
    sign_admin_request,
)
from genesis_mesh.crypto import sign_data
from genesis_mesh.na_service.settings import load_settings

from .test_na_boundary_policy import _make_service
from .test_na_treaties import _issue_treaty


def _sign(client, *, method: str, path: str, body=None, query=None, audience=None, key_id="operator-test"):
    service = client.application.extensions["genesis_mesh_na"]
    return sign_admin_request(
        client.operator_keypair.private_key,
        key_id,
        method=method,
        path=path,
        audience=audience or service.genesis_block.network_authority.public_key,
        body=body,
        query=query,
    )


def _legacy_headers(client, body, key_id="operator-test"):
    headers = _sign(client, method="POST", path="/unused", body=body, key_id=key_id)
    payload = legacy_admin_signing_payload(
        body=body,
        key_id=key_id,
        timestamp=headers["X-Admin-Timestamp"],
        nonce=headers["X-Admin-Nonce"],
    )
    headers["X-Admin-Signature"] = sign_data(payload, client.operator_keypair.private_key)
    return headers


def _treaty_status(client, treaty_id: str) -> str:
    return client.get(f"/recognition-treaties/{treaty_id}").get_json()["status"]


def _invite_body() -> dict:
    return {"roles": ["role:client"], "max_validity_hours": 24, "token_expiry_hours": 1}


def test_a_revoke_signed_for_one_treaty_cannot_revoke_another(client, na_service):
    first = _issue_treaty(client, na_service).get_json()["treaty_id"]
    second = _issue_treaty(client, na_service).get_json()["treaty_id"]
    body = {"reason": "relationship_ended"}
    headers = _sign(client, method="POST", path=f"/admin/recognition-treaties/{first}/revoke", body=body)

    retargeted = client.post(f"/admin/recognition-treaties/{second}/revoke", json=body, headers=headers)

    assert retargeted.status_code == 401
    assert retargeted.get_json()["error"]["code"] == "admin_auth_failed"
    assert _treaty_status(client, first) == "active"
    assert _treaty_status(client, second) == "active"
    # The genuine request still works once.
    genuine = client.post(f"/admin/recognition-treaties/{first}/revoke", json=body, headers=headers)
    assert genuine.status_code == 200
    assert _treaty_status(client, first) == "revoked"
    assert _treaty_status(client, second) == "active"


def test_a_signed_get_cannot_be_replayed_on_another_admin_route(client):
    headers = _sign(client, method="GET", path="/admin/policy/history")
    assert client.get("/nodes", headers=headers).status_code == 401
    assert client.get("/admin/policy/history", headers=headers).status_code == 200


def test_query_parameters_are_signed(client):
    headers = _sign(client, method="GET", path="/nodes")
    assert client.get("/nodes?limit=1", headers=headers).status_code == 401

    signed_with_query = _sign(client, method="GET", path="/nodes", query={"limit": ["1"]})
    assert client.get("/nodes?limit=2", headers=signed_with_query).status_code == 401
    assert client.get("/nodes?limit=1", headers=signed_with_query).status_code == 200


def test_the_method_is_signed(client):
    body = _invite_body()
    headers = _sign(client, method="PUT", path="/admin/invite", body=body)
    assert client.post("/admin/invite", json=body, headers=headers).status_code == 401


def test_the_body_is_still_signed(client):
    headers = _sign(client, method="POST", path="/admin/invite", body=_invite_body())
    tampered = {**_invite_body(), "roles": ["role:anchor"]}
    assert client.post("/admin/invite", json=tampered, headers=headers).status_code == 401


def test_a_request_for_another_authority_is_refused(client):
    body = _invite_body()
    headers = _sign(client, method="POST", path="/admin/invite", body=body, audience="ANOTHER-SOVEREIGN")
    assert client.post("/admin/invite", json=body, headers=headers).status_code == 401


def test_version_1_signatures_are_refused_by_default(client, na_service):
    body = _invite_body()
    response = client.post("/admin/invite", json=body, headers=_legacy_headers(client, body))
    assert response.status_code == 401
    reasons = [
        e["details"].get("reason")
        for e in na_service.db.list_audit_events()
        if e["event_type"] == "admin_auth_failed"
    ]
    assert "invalid_signature" in reasons


def test_version_1_signatures_are_accepted_and_audited_only_when_opted_in():
    service = _make_service(admin_legacy_signatures="accept")
    service.app.config["TESTING"] = True
    client = service.app.test_client()
    setattr(client, "operator_keypair", service._test_operator_keypair)
    body = _invite_body()

    response = client.post("/admin/invite", json=body, headers=_legacy_headers(client, body))

    assert response.status_code == 201
    legacy = [e for e in service.db.list_audit_events() if e["event_type"] == "admin_legacy_signature_accepted"]
    assert legacy and legacy[-1]["details"] == {
        "key_id": "operator-test", "method": "POST", "path": "/admin/invite",
    }
    # Version 2 keeps working during the migration window and is not audited as legacy.
    assert client.post("/admin/invite", json=body, headers=_sign(
        client, method="POST", path="/admin/invite", body=body,
    )).status_code == 201
    assert len([
        e for e in service.db.list_audit_events() if e["event_type"] == "admin_legacy_signature_accepted"
    ]) == len(legacy)


def test_the_legacy_mode_is_validated_and_read_from_the_environment():
    with pytest.raises(ValueError):
        _make_service(admin_legacy_signatures="maybe")
    assert load_settings({"GENESIS_FILE": "g.json"}).admin_legacy_signatures == "reject"
    assert load_settings({
        "GENESIS_FILE": "g.json", "NA_ADMIN_LEGACY_SIGNATURES": "accept",
    }).admin_legacy_signatures == "accept"


def test_the_payload_refuses_a_relative_path():
    with pytest.raises(ValueError):
        admin_signing_payload(
            method="GET", path="nodes", audience="A", body={},
            key_id="k", timestamp="t", nonce="n",
        )


def test_a_decoded_question_mark_in_a_path_is_signed_not_refused(client):
    """An identifier may contain '?' (sent as %3F); the NA answers, it does not fail."""
    body = {"reason": "test"}
    path = "/admin/attestations/a?b/revoke"
    headers = _sign(client, method="POST", path=path, body=body)
    response = client.post("/admin/attestations/a%3Fb/revoke", json=body, headers=headers)
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "attestation_not_found"


def test_a_request_for_one_na_is_refused_by_another_with_the_same_network_name():
    """The audience is the NA's public key, not its operator-chosen name (v1.0.2).

    Two Network Authorities that share a network name and trust the same
    operator key must still refuse each other's requests.
    """
    from .na_server_helpers import make_client, make_na_service

    first = make_na_service("SHARED-NAME")
    second = make_na_service("SHARED-NAME")
    operator = getattr(first, "_test_operator_keypair")
    second.operator_public_keys["operator-test"] = operator.public_key_b64
    second.operator_key_tiers["operator-test"] = "privileged"

    body = {"roles": ["role:client"], "max_validity_hours": 24, "ttl_hours": 1}
    headers = sign_admin_request(
        operator.private_key, "operator-test", method="POST", path="/admin/invite",
        audience=first.genesis_block.network_authority.public_key, body=body,
    )
    replayed = make_client(second).post("/admin/invite", json=body, headers=headers)
    assert replayed.status_code == 401
    accepted = make_client(first).post("/admin/invite", json=body, headers=headers)
    assert accepted.status_code == 201

