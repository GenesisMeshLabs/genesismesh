"""Tests for the v0.52 Trust API HTTP surface — agreement, boundary, evidence,
disclosure, consensus, and data-usage routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from genesis_mesh.crypto import generate_keypair

from .na_server_helpers import admin_headers


# ── Shared helpers ────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future_iso(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _post_admin(client, url: str, body: dict):
    return client.post(url, json=body, headers=admin_headers(client, body))


def _issue_treaty_for_sovereign(client, na_service, sovereign_id: str = "sovereign-b"):
    """Issue a recognition treaty so the NA graph recognises the target sovereign.

    The treaty names the sovereign's own key, never the NA's: agreements the NA
    offers and accepts itself are trusted as NA-issued (v1.1.1).
    """
    body = {
        "subject_sovereign_id": sovereign_id,
        "subject_public_keys": [generate_keypair().public_key_b64],
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


# ── F-06: /consensus/verify must not default validator keys to the NA's own ──


def _minimal_consensus_proof_payload() -> dict:
    """A syntactically valid ConsensusProof with no validator signatures.

    This is the shape the Phase-1 PoC submitted: the route used to default the
    validator key map to the NA's own key, so every genuine validator was an
    unrecognised key, every vote was skipped, and the proof verified as valid.
    """
    now = datetime.now(timezone.utc)
    return {
        "consensus_id": "con-1",
        "proof_id": "jp-1",
        "decision_id": "dec-1",
        "required_threshold": 2,
        "validator_sovereign_ids": ["validator-1", "validator-2"],
        "votes": [
            {
                "vote_id": f"vote-{i}",
                "proof_id": "jp-1",
                "decision_id": "dec-1",
                "validator_sovereign_id": f"validator-{i}",
                "vote": True,
                "voted_at": now.isoformat(),
                "context_digest": f"digest-{i}",
                "signature": None,
            }
            for i in (1, 2)
        ],
        "reached_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "signature": None,
    }


def test_consensus_verify_requires_validator_public_keys(client):
    """F-06: the caller must supply validator keys; no silent NA-key default."""
    resp = client.post("/consensus/verify", json={"proof": _minimal_consensus_proof_payload()})

    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"]["code"] == "missing_validator_public_keys"


def test_consensus_verify_rejects_empty_validator_public_keys(client):
    """An empty map is not a licence to skip the check either."""
    resp = client.post(
        "/consensus/verify",
        json={"proof": _minimal_consensus_proof_payload(), "validator_public_keys": {}},
    )

    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "missing_validator_public_keys"


def test_consensus_verify_does_not_accept_unsigned_votes(client):
    """The Phase-1 attack: zero validator signatures must not verify as valid."""
    resp = client.post(
        "/consensus/verify",
        json={
            "proof": _minimal_consensus_proof_payload(),
            "validator_public_keys": {"validator-1": "AAAA", "validator-2": "BBBB"},
        },
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["valid"] is False


def test_data_usage_policy_visible_to_other_connection_and_after_restart(client, na_service, tmp_path):
    from genesis_mesh.na_service.db import NADatabase
    original = na_service.db
    na_service.db = NADatabase(str(tmp_path / "authority.db"))
    na_service.db.migrate()
    created = _make_policy(client, na_service).get_json()
    # A second connection to the same database (the file, or the PostgreSQL URL).
    same_database = getattr(na_service.db.conn, "url", None)
    observer = NADatabase(na_service.db.db_path, database_url=same_database)
    try:
        observer.migrate()
        assert observer.get_active_data_license_policy().policy_id == created["policy_id"]
        replacement = _make_policy(client, na_service).get_json()
        assert observer.get_active_data_license_policy().policy_id == replacement["policy_id"]
    finally:
        observer.conn.close()
    reopened = NADatabase(na_service.db.db_path, database_url=same_database)
    try:
        assert reopened.get_active_data_license_policy().policy_id == replacement["policy_id"]
        assert reopened.conn.execute("SELECT count(*) FROM data_license_policies WHERE active = 1").fetchone()[0] == 1
    finally:
        reopened.conn.close()
        na_service.db.conn.close()
        na_service.db = original


# ── v1.0.2: request timestamps keep their instant ──────────────────────────────


def test_offer_with_utc_offset_keeps_the_instant(client, na_service):
    """A window given in +02:00 is converted to UTC, not relabelled as UTC."""
    _issue_treaty_for_sovereign(client, na_service)
    start = datetime.now(timezone.utc).replace(microsecond=0)
    plus_two = timezone(timedelta(hours=2))
    body = {
        "responder_sovereign_id": "sovereign-b",
        "capabilities": ["read"],
        "valid_from": start.astimezone(plus_two).isoformat(),
        "valid_until": (start + timedelta(hours=24)).astimezone(plus_two).isoformat(),
        "expires_at": (start + timedelta(hours=1)).astimezone(plus_two).isoformat(),
    }
    offer = _post_admin(client, "/admin/agreements/offer", body).get_json()
    terms = offer["requested_terms"]
    assert datetime.fromisoformat(terms["valid_from"]) == start
    assert datetime.fromisoformat(terms["valid_until"]) == start + timedelta(hours=24)
    assert datetime.fromisoformat(offer["expires_at"]) == start + timedelta(hours=1)


def test_data_usage_policy_with_utc_offset_keeps_the_instant(client, na_service):
    start = datetime.now(timezone.utc).replace(microsecond=0)
    minus_five = timezone(timedelta(hours=-5))
    body = {
        "licensee_sovereign_id": "sovereign-b",
        "allowed_source_ids": ["src-1"],
        "allowed_access_types": ["read"],
        "valid_from": start.astimezone(minus_five).isoformat(),
        "valid_until": (start + timedelta(hours=1)).astimezone(minus_five).isoformat(),
    }
    policy = _post_admin(client, "/admin/data-usage/policy", body).get_json()
    assert datetime.fromisoformat(policy["valid_from"]) == start
    assert datetime.fromisoformat(policy["valid_until"]) == start + timedelta(hours=1)


def test_timestamp_without_offset_is_utc(client, na_service):
    _issue_treaty_for_sovereign(client, na_service)
    start = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    body = {
        "responder_sovereign_id": "sovereign-b",
        "capabilities": ["read"],
        "valid_from": start.isoformat(),
        "valid_until": (start + timedelta(hours=24)).isoformat(),
        "expires_at": (start + timedelta(hours=1)).isoformat(),
    }
    offer = _post_admin(client, "/admin/agreements/offer", body).get_json()
    assert datetime.fromisoformat(offer["requested_terms"]["valid_from"]) == start.replace(tzinfo=timezone.utc)


def test_non_string_timestamp_is_a_bad_request(client, na_service):
    body = {
        "responder_sovereign_id": "sovereign-b",
        "capabilities": ["read"],
        "valid_from": 1700000000,
        "valid_until": _future_iso(24),
        "expires_at": _future_iso(1),
    }
    resp = _post_admin(client, "/admin/agreements/offer", body)
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "invalid_timestamps"


# ── v1.0.2: consensus vote and proof over HTTP ─────────────────────────────────


def _justification_proof(na_service) -> dict:
    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models.justification import GateTrace, GateTraceEntry, JustificationProof

    now = datetime.now(timezone.utc)
    trace = GateTrace(
        trace_id="tr-http-1", decision_id="dec-http-1", agreement_id="agr-http-1",
        operator_sovereign_id=na_service.genesis_block.network_name, traced_at=now,
        entries=[GateTraceEntry(gate_name="capability_check", gate_type="CapabilityGate", evaluated_at=now,
                                inputs={"requested_capability": "read"}, result=True, reason="ok")],
        final_authorized=True,
    )
    proof = JustificationProof(proof_id="jp-http-1", decision_id="dec-http-1", trace=trace,
                               proof_issued_at=now, issuer_sovereign_id=na_service.genesis_block.network_name)
    proof.signature = sign_model(proof, na_service.signer, na_service.key_id)
    return proof.model_dump(mode="json")


def test_consensus_vote_proof_and_verify_over_http(client, na_service):
    proof = _justification_proof(na_service)
    vote = _post_admin(client, "/admin/consensus/vote", {"justification_proof": proof, "vote": True})
    assert vote.status_code == 201, vote.get_json()
    vote_body = vote.get_json()
    assert vote_body["vote"] is True
    assert vote_body["validator_sovereign_id"] == na_service.genesis_block.network_name

    assembled = _post_admin(client, "/admin/consensus/proof", {
        "justification_proof": proof, "votes": [vote_body], "required_threshold": 1,
        "validator_sovereign_ids": [na_service.genesis_block.network_name],
    })
    assert assembled.status_code == 201, assembled.get_json()
    consensus = assembled.get_json()
    assert consensus["required_threshold"] == 1

    verified = client.post("/consensus/verify", json={
        "proof": consensus,
        "validator_public_keys": {na_service.genesis_block.network_name: na_service.genesis_block.network_authority.public_key},
    })
    assert verified.status_code == 200
    assert verified.get_json()["valid"] is True


def test_consensus_refuses_proofs_this_na_did_not_sign(client, na_service):
    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models.justification import JustificationProof

    forged = JustificationProof.model_validate(_justification_proof(na_service))
    forged.signature = sign_model(forged, generate_keypair().private_key, "someone")
    body = forged.model_dump(mode="json")
    vote = _post_admin(client, "/admin/consensus/vote", {"justification_proof": body, "vote": True})
    assert vote.status_code == 422 and vote.get_json()["error"]["code"] == "justification_untrusted"
    assembled = _post_admin(client, "/admin/consensus/proof", {
        "justification_proof": body, "votes": [], "required_threshold": 1,
        "validator_sovereign_ids": [na_service.genesis_block.network_name],
    })
    assert assembled.status_code == 422 and assembled.get_json()["error"]["code"] == "justification_untrusted"


@pytest.mark.parametrize("threshold", [0, -1, 2, "1", True, 1.5])
def test_consensus_threshold_must_be_between_one_and_the_validator_count(client, na_service, threshold):
    resp = _post_admin(client, "/admin/consensus/proof", {
        "justification_proof": _justification_proof(na_service), "votes": [], "required_threshold": threshold,
        "validator_sovereign_ids": [na_service.genesis_block.network_name],
    })
    assert resp.status_code == 400 and resp.get_json()["error"]["code"] == "invalid_threshold"


def test_consensus_vote_rejects_bad_input(client, na_service):
    proof = _justification_proof(na_service)
    assert _post_admin(client, "/admin/consensus/vote", {"justification_proof": proof}).status_code == 400
    assert _post_admin(client, "/admin/consensus/vote",
                       {"justification_proof": proof, "vote": "yes"}).status_code == 400
    assert _post_admin(client, "/admin/consensus/vote",
                       {"justification_proof": {"not": "a proof"}, "vote": True}).status_code == 400
    assert client.post("/admin/consensus/vote", json={"justification_proof": proof, "vote": True}).status_code == 401


def test_consensus_proof_needs_enough_votes(client, na_service):
    proof = _justification_proof(na_service)
    resp = _post_admin(client, "/admin/consensus/proof", {
        "justification_proof": proof, "votes": [], "required_threshold": 1,
        "validator_sovereign_ids": [na_service.genesis_block.network_name],
    })
    assert resp.status_code in (400, 422)
