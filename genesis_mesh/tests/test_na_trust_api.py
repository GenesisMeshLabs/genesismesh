"""Tests for the v0.52 Trust API HTTP surface — agreement, boundary, evidence,
disclosure, consensus, and data-usage routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from .na_server_helpers import admin_headers


# ── Shared helpers ────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future_iso(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _post_admin(client, url: str, body: dict):
    return client.post(url, json=body, headers=admin_headers(client, body))


def _issue_treaty_for_sovereign(client, na_service, sovereign_id: str = "sovereign-b"):
    """Issue a recognition treaty so the NA graph recognises the target sovereign."""
    body = {
        "subject_sovereign_id": sovereign_id,
        "subject_public_keys": [na_service.genesis_block.network_authority.public_key],
        "scope": {"allowed_roles": ["role:client"]},
        "validity_hours": 24,
    }
    resp = _post_admin(client, "/admin/recognition-treaties", body)
    assert resp.status_code == 201, f"treaty failed: {resp.get_json()}"


# ── Agreement route helpers ───────────────────────────────────────────────────

def _make_offer(client, na_service, capabilities=None):
    _issue_treaty_for_sovereign(client, na_service)
    body = {
        "responder_sovereign_id": "sovereign-b",
        "capabilities": capabilities or ["read", "write"],
        "scope": {},
        "valid_from": _now_iso(),
        "valid_until": _future_iso(24),
        "expires_at": _future_iso(1),
    }
    return _post_admin(client, "/admin/agreements/offer", body)


# ── Agreement: offer ─────────────────────────────────────────────────────────

def test_agreement_offer_returns_201(client, na_service):
    resp = _make_offer(client, na_service)
    assert resp.status_code == 201


def test_agreement_offer_contains_signatures(client, na_service):
    offer = _make_offer(client, na_service).get_json()
    assert offer["signatures"]
    assert offer["offerer_sovereign_id"] == "TEST"
    assert offer["responder_sovereign_id"] == "sovereign-b"


def test_agreement_offer_capabilities_preserved(client, na_service):
    offer = _make_offer(client, na_service, capabilities=["read"]).get_json()
    assert offer["requested_terms"]["capabilities"] == ["read"]


def test_agreement_offer_rejects_missing_capabilities(client, na_service):
    body = {
        "responder_sovereign_id": "sovereign-b",
        "valid_from": _now_iso(),
        "valid_until": _future_iso(24),
        "expires_at": _future_iso(1),
    }
    resp = _post_admin(client, "/admin/agreements/offer", body)
    assert resp.status_code == 400


def test_agreement_offer_rejects_unauthenticated(client, na_service):
    body = {
        "responder_sovereign_id": "sovereign-b",
        "capabilities": ["read"],
        "valid_from": _now_iso(),
        "valid_until": _future_iso(24),
        "expires_at": _future_iso(1),
    }
    resp = client.post("/admin/agreements/offer", json=body)
    assert resp.status_code == 401


# ── Agreement: counter ───────────────────────────────────────────────────────

def test_agreement_counter_returns_201(client, na_service):
    offer = _make_offer(client, na_service).get_json()
    body = {
        "offer": offer,
        "capabilities": ["read"],
        "scope": {},
        "valid_from": _now_iso(),
        "valid_until": _future_iso(12),
    }
    resp = _post_admin(client, "/admin/agreements/counter", body)
    assert resp.status_code == 201


def test_agreement_counter_contains_signatures(client, na_service):
    offer = _make_offer(client, na_service).get_json()
    body = {
        "offer": offer,
        "capabilities": ["read"],
        "scope": {},
        "valid_from": _now_iso(),
        "valid_until": _future_iso(12),
    }
    counter = _post_admin(client, "/admin/agreements/counter", body).get_json()
    assert counter["signatures"]


def test_agreement_counter_rejects_missing_offer(client, na_service):
    body = {
        "capabilities": ["read"],
        "valid_from": _now_iso(),
        "valid_until": _future_iso(12),
    }
    resp = _post_admin(client, "/admin/agreements/counter", body)
    assert resp.status_code == 400


# ── Agreement: accept ────────────────────────────────────────────────────────

def test_agreement_accept_offer_returns_201(client, na_service):
    offer = _make_offer(client, na_service).get_json()
    body = {"offer": offer}
    resp = _post_admin(client, "/admin/agreements/accept", body)
    assert resp.status_code == 201


def test_agreement_accept_counter_returns_201(client, na_service):
    offer = _make_offer(client, na_service).get_json()
    counter_body = {
        "offer": offer,
        "capabilities": ["read"],
        "scope": {},
        "valid_from": _now_iso(),
        "valid_until": _future_iso(12),
    }
    counter = _post_admin(client, "/admin/agreements/counter", counter_body).get_json()
    accept_body = {"counter": counter, "original_offer": offer}
    resp = _post_admin(client, "/admin/agreements/accept", accept_body)
    assert resp.status_code == 201


def test_agreement_accept_missing_fields_returns_400(client, na_service):
    resp = _post_admin(client, "/admin/agreements/accept", {})
    assert resp.status_code == 400


# ── Agreement: verify ────────────────────────────────────────────────────────

def test_agreement_verify_accepted(client, na_service):
    offer = _make_offer(client, na_service).get_json()
    agreement = _post_admin(client, "/admin/agreements/accept", {"offer": offer}).get_json()
    resp = client.post("/agreements/verify", json={"agreement": agreement})
    assert resp.status_code == 200
    assert resp.get_json()["accepted"] is True


def test_agreement_verify_missing_agreement_returns_400(client, na_service):
    resp = client.post("/agreements/verify", json={})
    assert resp.status_code == 400


# ── Boundary: decide ─────────────────────────────────────────────────────────

def _make_agreement(client, na_service):
    offer = _make_offer(client, na_service).get_json()
    return _post_admin(client, "/admin/agreements/accept", {"offer": offer}).get_json()


def test_boundary_decide_returns_201(client, na_service):
    agreement = _make_agreement(client, na_service)
    body = {
        "agreement": agreement,
        "requested_capability": "read",
    }
    resp = _post_admin(client, "/admin/boundary/decide", body)
    assert resp.status_code == 201


def test_boundary_decide_contains_decision_id(client, na_service):
    agreement = _make_agreement(client, na_service)
    body = {"agreement": agreement, "requested_capability": "read"}
    decision = _post_admin(client, "/admin/boundary/decide", body).get_json()
    assert decision["decision_id"]
    assert decision["signature"]


def test_boundary_decide_rejects_missing_capability(client, na_service):
    agreement = _make_agreement(client, na_service)
    body = {"agreement": agreement}
    resp = _post_admin(client, "/admin/boundary/decide", body)
    assert resp.status_code == 400


def test_boundary_decide_rejects_unauthenticated(client, na_service):
    agreement = _make_agreement(client, na_service)
    resp = client.post(
        "/admin/boundary/decide",
        json={"agreement": agreement, "requested_capability": "read"},
    )
    assert resp.status_code == 401


# ── Boundary: verify ─────────────────────────────────────────────────────────

def test_boundary_verify_accepted(client, na_service):
    agreement = _make_agreement(client, na_service)
    decision = _post_admin(
        client, "/admin/boundary/decide",
        {"agreement": agreement, "requested_capability": "read"},
    ).get_json()
    resp = client.post("/boundary/verify", json={"decision": decision})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["accepted"] is True
    assert "decision_id" in data


def test_boundary_verify_missing_decision_returns_400(client, na_service):
    resp = client.post("/boundary/verify", json={})
    assert resp.status_code == 400


# ── Evidence: build ──────────────────────────────────────────────────────────

def _trust_decision_body() -> dict:
    return {
        "source_sovereign_id": "TEST",
        "target_sovereign_id": "sovereign-b",
        "verdict": "allow",
        "reason": "direct recognition",
        "requested_roles": [],
        "trusted": True,
        "trust_path": [],
        "hop_count": 0,
        "signals": [],
        "evaluated_at": _now_iso(),
    }


def test_evidence_build_returns_201(client, na_service):
    body = {"decision": _trust_decision_body()}
    resp = _post_admin(client, "/admin/trust-evidence", body)
    assert resp.status_code == 201


def test_evidence_build_contains_signatures(client, na_service):
    body = {"decision": _trust_decision_body()}
    evidence = _post_admin(client, "/admin/trust-evidence", body).get_json()
    assert evidence["signatures"]
    assert evidence["issuer_sovereign_id"] == "TEST"
    assert evidence["verdict"] == "allow"


def test_evidence_build_rejects_missing_decision(client, na_service):
    resp = _post_admin(client, "/admin/trust-evidence", {})
    assert resp.status_code == 400


# ── Evidence: verify ─────────────────────────────────────────────────────────

def test_evidence_verify_accepted(client, na_service):
    body = {"decision": _trust_decision_body()}
    evidence = _post_admin(client, "/admin/trust-evidence", body).get_json()
    resp = client.post("/trust-evidence/verify", json={"evidence": evidence})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["accepted"] is True
    assert data["evidence_id"]


def test_evidence_verify_missing_evidence_returns_400(client, na_service):
    resp = client.post("/trust-evidence/verify", json={})
    assert resp.status_code == 400


# ── Disclosure: commit ───────────────────────────────────────────────────────

def test_disclosure_commit_returns_201(client, na_service):
    agreement = _make_agreement(client, na_service)
    body = {"capabilities": ["read", "write"], "agreement": agreement}
    resp = _post_admin(client, "/admin/disclosure/commit", body)
    assert resp.status_code == 201


def test_disclosure_commit_contains_signatures(client, na_service):
    agreement = _make_agreement(client, na_service)
    body = {"capabilities": ["read", "write"], "agreement": agreement}
    commitment = _post_admin(client, "/admin/disclosure/commit", body).get_json()
    assert commitment["signature"]
    assert commitment["commitment_id"]


def test_disclosure_commit_rejects_empty_capabilities(client, na_service):
    agreement = _make_agreement(client, na_service)
    body = {"capabilities": [], "agreement": agreement}
    resp = _post_admin(client, "/admin/disclosure/commit", body)
    assert resp.status_code == 400


# ── Disclosure: prove ────────────────────────────────────────────────────────

def _make_commitment(client, na_service):
    agreement = _make_agreement(client, na_service)
    body = {"capabilities": ["read", "write"], "agreement": agreement}
    return _post_admin(client, "/admin/disclosure/commit", body).get_json()


def test_disclosure_prove_returns_200(client, na_service):
    commitment = _make_commitment(client, na_service)
    body = {
        "capability": "read",
        "capabilities": ["read", "write"],
        "commitment": commitment,
        "prover_sovereign_id": "sovereign-b",
    }
    resp = client.post("/disclosure/prove", json=body)
    assert resp.status_code == 200


def test_disclosure_prove_contains_proof(client, na_service):
    commitment = _make_commitment(client, na_service)
    body = {
        "capability": "read",
        "capabilities": ["read", "write"],
        "commitment": commitment,
        "prover_sovereign_id": "sovereign-b",
    }
    proof = client.post("/disclosure/prove", json=body).get_json()
    assert proof["proof_id"]
    assert proof["revealed_capability"] == "read"


def test_disclosure_prove_missing_fields_returns_400(client, na_service):
    resp = client.post("/disclosure/prove", json={"capability": "read"})
    assert resp.status_code == 400


# ── Disclosure: verify ───────────────────────────────────────────────────────

def _make_proof(client, na_service):
    commitment = _make_commitment(client, na_service)
    body = {
        "capability": "read",
        "capabilities": ["read", "write"],
        "commitment": commitment,
        "prover_sovereign_id": "sovereign-b",
    }
    return client.post("/disclosure/prove", json=body).get_json(), commitment


def test_disclosure_verify_valid(client, na_service):
    proof, commitment = _make_proof(client, na_service)
    resp = client.post(
        "/disclosure/verify",
        json={"proof": proof, "commitment": commitment},
    )
    assert resp.status_code == 200
    assert resp.get_json()["valid"] is True


def test_disclosure_verify_missing_fields_returns_400(client, na_service):
    resp = client.post("/disclosure/verify", json={})
    assert resp.status_code == 400


# ── Disclosure: nullifier ────────────────────────────────────────────────────

def test_disclosure_nullifier_returns_201(client, na_service):
    proof, _ = _make_proof(client, na_service)
    body = {"proof": proof}
    resp = _post_admin(client, "/admin/disclosure/nullifier", body)
    assert resp.status_code == 201


def test_disclosure_nullifier_contains_signatures(client, na_service):
    proof, _ = _make_proof(client, na_service)
    null = _post_admin(client, "/admin/disclosure/nullifier", {"proof": proof}).get_json()
    assert null["signature"]
    assert null["nullifier_id"]


# ── Data usage: policy ───────────────────────────────────────────────────────

def _make_policy(client, na_service):
    body = {
        "licensee_sovereign_id": "sovereign-b",
        "allowed_source_ids": ["src-1"],
        "allowed_access_types": ["read"],
        "valid_from": _now_iso(),
        "valid_until": _future_iso(720),
    }
    return _post_admin(client, "/admin/data-usage/policy", body)


def test_data_usage_policy_create_returns_201(client, na_service):
    resp = _make_policy(client, na_service)
    assert resp.status_code == 201


def test_data_usage_policy_is_signed_by_na(client, na_service):
    policy = _make_policy(client, na_service).get_json()
    assert policy["signature"]
    assert policy["licensor_sovereign_id"] == "TEST"
    assert policy["allowed_source_ids"] == ["src-1"]


def test_data_usage_policy_get_returns_active(client, na_service):
    _make_policy(client, na_service)
    resp = client.get("/data-usage/policy")
    assert resp.status_code == 200
    assert resp.get_json()["licensor_sovereign_id"] == "TEST"


def test_data_usage_policy_get_404_when_none(client, na_service):
    resp = client.get("/data-usage/policy")
    assert resp.status_code == 404


def test_data_usage_policy_create_rejects_missing_fields(client, na_service):
    body = {"licensee_sovereign_id": "sovereign-b"}
    resp = _post_admin(client, "/admin/data-usage/policy", body)
    assert resp.status_code == 400


# ── Data usage: intent ───────────────────────────────────────────────────────

def _make_intent(client, na_service):
    body = {
        "sources": [
            {
                "source_id": "src-1",
                "source_type": "database",
                "owner_sovereign_id": "TEST",
                "classification_tags": [],
            }
        ],
        "access_types": ["read"],
        "decision_id": "dec-001",
    }
    return _post_admin(client, "/admin/data-usage/intent", body)


def test_data_usage_intent_returns_201(client, na_service):
    resp = _make_intent(client, na_service)
    assert resp.status_code == 201


def test_data_usage_intent_is_signed(client, na_service):
    intent = _make_intent(client, na_service).get_json()
    assert intent["signature"]
    assert intent["agent_sovereign_id"] == "TEST"
    assert intent["declared_access_types"] == ["read"]


def test_data_usage_intent_rejects_missing_sources(client, na_service):
    body = {"access_types": ["read"]}
    resp = _post_admin(client, "/admin/data-usage/intent", body)
    assert resp.status_code == 400


# ── Data usage: verify ───────────────────────────────────────────────────────

def test_data_usage_verify_valid(client, na_service):
    policy = _make_policy(client, na_service).get_json()
    intent = _make_intent(client, na_service).get_json()
    resp = client.post(
        "/data-usage/verify",
        json={"intent": intent, "policy": policy},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["valid"] is True
    assert data["violation_count"] == 0


def test_data_usage_verify_missing_fields_returns_400(client, na_service):
    resp = client.post("/data-usage/verify", json={})
    assert resp.status_code == 400


def test_data_usage_verify_reports_violations(client, na_service):
    """An intent with a disallowed access type should fail verification."""
    policy = _make_policy(client, na_service).get_json()
    body = {
        "sources": [
            {
                "source_id": "src-1",
                "source_type": "database",
                "owner_sovereign_id": "TEST",
                "classification_tags": [],
            }
        ],
        "access_types": ["delete"],
    }
    intent = _post_admin(client, "/admin/data-usage/intent", body).get_json()
    resp = client.post(
        "/data-usage/verify",
        json={"intent": intent, "policy": policy},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["valid"] is False
    assert data["violation_count"] > 0
