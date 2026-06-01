"""Tests for sovereign membership attestation routes."""

from __future__ import annotations

import json

from genesis_mesh.models import RecognitionPolicy, RecognizedIssuer

from .na_server_helpers import admin_headers


def _policy_for_test_issuer(na_service) -> RecognitionPolicy:
    """Build a recognition policy that trusts the test NA as an issuer."""
    return RecognitionPolicy(
        local_sovereign_id="acceptor-test",
        recognized_issuers=[
            RecognizedIssuer(
                sovereign_id=na_service.genesis_block.network_name,
                public_keys=[na_service.genesis_block.network_authority.public_key],
                allowed_roles=["role:anchor", "role:client"],
            )
        ],
    )


def _issue_attestation(client, subject_id: str = "alice"):
    """Issue an operator-authorized membership attestation through the API."""
    body = {
        "subject_id": subject_id,
        "subject_public_key": "subject-public-key",
        "roles": ["role:client"],
        "claims": {"project": "demo"},
        "validity_hours": 24,
    }
    return client.post(
        "/admin/attestations",
        json=body,
        headers=admin_headers(client, body),
    )


def test_admin_can_issue_membership_attestation(client):
    """An operator can issue a signed portable membership attestation."""
    resp = _issue_attestation(client)

    assert resp.status_code == 201
    attestation = resp.get_json()
    assert attestation["issuer_sovereign_id"] == "TEST"
    assert attestation["subject_id"] == "alice"
    assert attestation["roles"] == ["role:client"]
    assert attestation["signatures"]

    stored = client.get(f"/attestations/{attestation['attestation_id']}")
    assert stored.status_code == 200
    payload = stored.get_json()
    assert payload["status"] == "active"
    assert payload["attestation"]["attestation_id"] == attestation["attestation_id"]


def test_attestation_verify_accepts_recognized_issuer(na_service, client):
    """A trusted issuer and valid signature are accepted."""
    attestation = _issue_attestation(client).get_json()
    policy = _policy_for_test_issuer(na_service)

    resp = client.post(
        "/attestations/verify",
        json={
            "attestation": attestation,
            "recognition_policy": json.loads(policy.model_dump_json()),
        },
    )

    assert resp.status_code == 200
    assert resp.get_json() == {
        "accepted": True,
        "reason": "accepted",
        "issuer_sovereign_id": "TEST",
        "attestation_id": attestation["attestation_id"],
    }


def test_attestation_verify_rejects_unknown_issuer(client):
    """An attestation from an unrecognized issuer is rejected safely."""
    attestation = _issue_attestation(client).get_json()
    policy = RecognitionPolicy(local_sovereign_id="acceptor-test")

    resp = client.post(
        "/attestations/verify",
        json={
            "attestation": attestation,
            "recognition_policy": json.loads(policy.model_dump_json()),
        },
    )

    assert resp.status_code == 200
    assert resp.get_json()["accepted"] is False
    assert resp.get_json()["reason"] == "unknown_issuer"


def test_attestation_verify_rejects_disallowed_role(na_service, client):
    """A recognized issuer cannot grant roles outside local recognition policy."""
    attestation = _issue_attestation(client).get_json()
    policy = RecognitionPolicy(
        local_sovereign_id="acceptor-test",
        recognized_issuers=[
            RecognizedIssuer(
                sovereign_id=na_service.genesis_block.network_name,
                public_keys=[na_service.genesis_block.network_authority.public_key],
                allowed_roles=["role:anchor"],
            )
        ],
    )

    resp = client.post(
        "/attestations/verify",
        json={
            "attestation": attestation,
            "recognition_policy": json.loads(policy.model_dump_json()),
        },
    )

    assert resp.status_code == 200
    assert resp.get_json()["accepted"] is False
    assert resp.get_json()["reason"] == "role_not_allowed"


def test_attestation_revocation_changes_verification_result(na_service, client):
    """Issuer-side revocation makes a previously accepted attestation fail."""
    attestation = _issue_attestation(client).get_json()
    policy = _policy_for_test_issuer(na_service)

    revoke_body = {"reason": "membership_removed"}
    revoke = client.post(
        f"/admin/attestations/{attestation['attestation_id']}/revoke",
        json=revoke_body,
        headers=admin_headers(client, revoke_body),
    )
    assert revoke.status_code == 200

    resp = client.post(
        "/attestations/verify",
        json={
            "attestation": attestation,
            "recognition_policy": json.loads(policy.model_dump_json()),
        },
    )

    assert resp.status_code == 200
    assert resp.get_json()["accepted"] is False
    assert resp.get_json()["reason"] == "locally_revoked"

    stored = client.get(f"/attestations/{attestation['attestation_id']}").get_json()
    assert stored["status"] == "revoked"
    assert stored["revocation_reason"] == "membership_removed"


def test_active_recognition_policy_is_used_for_verification(na_service, client):
    """Verification can use a persisted local recognition policy."""
    attestation = _issue_attestation(client).get_json()
    policy = _policy_for_test_issuer(na_service)
    policy_body = {
        "policy_id": "acceptor-policy",
        "recognition_policy": json.loads(policy.model_dump_json()),
    }

    save = client.post(
        "/admin/recognition-policy",
        json=policy_body,
        headers=admin_headers(client, policy_body),
    )
    assert save.status_code == 200

    get_policy = client.get("/recognition-policy")
    assert get_policy.status_code == 200
    assert get_policy.get_json()["local_sovereign_id"] == "acceptor-test"

    resp = client.post("/attestations/verify", json={"attestation": attestation})

    assert resp.status_code == 200
    assert resp.get_json()["accepted"] is True
    assert resp.get_json()["reason"] == "accepted"


def test_attestation_issue_requires_operator_signature(client):
    """Attestation issuance rejects missing operator authentication."""
    resp = client.post(
        "/admin/attestations",
        json={
            "subject_id": "alice",
            "roles": ["role:client"],
        },
    )

    assert resp.status_code == 401
