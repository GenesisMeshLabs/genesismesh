"""1.9.2: attestation-basis evaluation is bound to the operator key that asked.

``POST /admin/boundary/evaluate`` with ``attestation_id`` checked the caller's
tier but not that the caller was the attestation's subject, so any operator
key could get decisions under another subject's attestation. The caller's key
must now be the subject: its public key equals ``subject_public_key`` when the
attestation binds one, and its key ID equals ``subject_id`` otherwise. A
mismatch is a signed, stored DENY, for every tier. The numbers in the test
names are the acceptance tests of ``ops/plan-v1.9.2.md``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models import MembershipAttestation
from genesis_mesh.models.canonical_registry import decision_refusal
from genesis_mesh.models.context import AttestationBinding, BoundaryDecision
from genesis_mesh.trust.context import verify_boundary_decision

from .test_attestation_boundary import _store
from .test_na_boundary_policy import _activate, _headers, _iso, _make_service

CAPABILITY = "partner.credential.create"


@pytest.fixture
def na_service():
    service = _make_service(evidence_store="on")
    # Two more standard keys: "psl" is the attestation's subject, "asl" is not.
    for key_id in ("psl", "asl"):
        pair = generate_keypair()
        service.operator_public_keys[key_id] = pair.public_key_b64
        service.operator_key_tiers[key_id] = "standard"
        setattr(service, f"_{key_id}_keypair", pair)
    return service


@pytest.fixture
def client(na_service):
    na_service.app.config["TESTING"] = True
    c = na_service.app.test_client()
    setattr(c, "operator_keypair", na_service._test_operator_keypair)
    setattr(c, "std_keypair", na_service._std_keypair)
    c.keys = {  # type: ignore[attr-defined]
        "operator-test": na_service._test_operator_keypair,
        "operator-std": na_service._std_keypair,
        "psl": na_service._psl_keypair,
        "asl": na_service._asl_keypair,
    }
    return c


def _post(client, url: str, body: dict, key_id: str = "operator-test"):
    headers = _headers(client.keys[key_id], key_id, body, client=client, method="POST", url=url)
    return client.post(url, json=body, headers=headers)


def _issue(client, *, subject: str = "psl", subject_public_key: str | None = "psl") -> dict:
    """Issue the reproduction's attestation; ``subject_public_key`` names a key ID whose key it binds."""
    body: dict = {
        "subject_id": subject,
        "roles": ["role:client"],
        "claims": {"capabilities": [CAPABILITY], "applications": ["app-1"]},
    }
    if subject_public_key is not None:
        body["subject_public_key"] = client.keys[subject_public_key].public_key_b64
    resp = _post(client, "/admin/attestations", body)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def _policy(client) -> None:
    body = {
        "policy_id": "partner-apps",
        "description": "partners may only create credentials for their attested applications",
        "valid_from": _iso(-timedelta(hours=1)),
        "valid_until": _iso(timedelta(days=7)),
        "selector": {"capabilities": ["partner.credential.*"]},
        "gates": [
            {"gate_id": "app-claim", "gate_type": "attestation_claim.v1", "order": 0,
             "config": {"path": "request_parameters.application_object_id", "claim": "applications"}},
        ],
    }
    resp = _post(client, "/admin/boundary-policies", body)
    assert resp.status_code == 201, resp.get_json()
    assert _activate(client, "partner-apps", resp.get_json()["version"]).status_code == 200


def _evaluate(client, attestation_id: str, key_id: str, *, requester: str | None = None):
    context: dict = {"request_parameters": {"application_object_id": "app-1"}}
    if requester is not None:
        context["requester_sovereign_id"] = requester
    body = {"attestation_id": attestation_id, "requested_capability": CAPABILITY, "context": context}
    return _post(client, "/admin/boundary/evaluate", body, key_id)


def _decision(resp) -> BoundaryDecision:
    assert resp.status_code == 201, resp.get_json()
    return BoundaryDecision.model_validate(resp.get_json()["decision"])


def _status_gate(decision: BoundaryDecision):
    return next(g for g in decision.gate_results if g.gate_name == "attestation_status")


def _events(service, event_type: str) -> list[dict]:
    found = []
    for event in service.db.list_audit_events():
        if event["event_type"] != event_type:
            continue
        details = event.get("details")
        found.append(json.loads(details) if isinstance(details, str) else details)
    return found


def _na_keys(service) -> list[str]:
    return service.boundary_policies.policy_public_keys()


def _assert_mismatch(decision: BoundaryDecision, caller: str, subject: str = "psl") -> None:
    assert decision.authorized is False
    assert decision.denial_reason == "attestation_subject_mismatch"
    gate = _status_gate(decision)
    assert gate.passed is False
    assert caller in gate.detail and subject in gate.detail
    # The detail names the keys, never the attestation's claims.
    assert "app-1" not in gate.detail and CAPABILITY not in gate.detail


@pytest.fixture
def setup(client):
    _policy(client)
    return client


def test_1_the_subjects_own_key_is_allowed(setup, na_service):
    att = _issue(setup)
    decision = _decision(_evaluate(setup, att["attestation_id"], "psl"))
    assert decision.authorized is True
    assert _status_gate(decision).passed is True


def test_2_another_standard_key_is_denied_the_reproduction(setup, na_service):
    att = _issue(setup)
    resp = _evaluate(setup, att["attestation_id"], "asl")
    decision = _decision(resp)  # 201: a denial, not an HTTP error
    _assert_mismatch(decision, "asl")
    # Signed, and verifiable offline like any other denial.
    result = verify_boundary_decision(decision, _na_keys(na_service))
    assert result.accepted and result.reason == "unauthorized_attestation_basis"


def test_2_the_denial_is_stored_and_audited(setup, na_service):
    service, client = na_service, setup
    att = _issue(client)

    decision = _decision(_evaluate(client, att["attestation_id"], "asl"))
    _assert_mismatch(decision, "asl")

    stored = [e for e in _events(service, "decision_stored") if e["decision_id"] == decision.decision_id]
    assert stored and stored[-1]["requested_by"] == "asl"
    made = [e for e in _events(service, "boundary_attestation_decision_made")
            if e["decision_id"] == decision.decision_id]
    assert made and made[-1]["authorized"] is False
    assert made[-1]["denial_reason"] == "attestation_subject_mismatch"
    assert "attestation_status" in made[-1]["failed_gates"]


def test_3_a_privileged_key_is_denied_too(setup):
    att = _issue(setup)
    _assert_mismatch(_decision(_evaluate(setup, att["attestation_id"], "operator-test")), "operator-test")


def test_4_without_a_subject_key_the_key_id_must_be_the_subject(setup):
    att = _issue(setup, subject_public_key=None)
    assert _decision(_evaluate(setup, att["attestation_id"], "psl")).authorized is True


def test_5_without_a_subject_key_another_key_id_is_denied(setup):
    att = _issue(setup, subject_public_key=None)
    _assert_mismatch(_decision(_evaluate(setup, att["attestation_id"], "asl")), "asl")


def test_6_a_replaced_key_fails_even_when_its_key_id_matches(setup):
    # Issued to "psl" but binding "asl"'s public key: the key now behind "psl" is not the bound one.
    att = _issue(setup, subject="psl", subject_public_key="asl")
    _assert_mismatch(_decision(_evaluate(setup, att["attestation_id"], "psl")), "psl")


def test_6_the_bound_key_decides_not_the_key_id(setup):
    # The other side of test 6: the key whose public key is bound passes, whatever its ID.
    att = _issue(setup, subject="psl", subject_public_key="asl")
    assert _decision(_evaluate(setup, att["attestation_id"], "asl")).authorized is True


def test_7_naming_the_subject_in_the_body_does_not_help(setup):
    att = _issue(setup)
    _assert_mismatch(_decision(_evaluate(setup, att["attestation_id"], "asl", requester="psl")), "asl")


def test_7_a_body_requester_other_than_the_subject_fails_as_before(setup):
    att = _issue(setup)
    decision = _decision(_evaluate(setup, att["attestation_id"], "psl", requester="someone-else"))
    assert decision.authorized is False and decision.denial_reason == "attestation_subject_mismatch"
    assert _status_gate(decision).detail.endswith("requester is not the attestation subject")


def test_8_revoked_and_expired_fail_as_before_with_the_right_key(setup, na_service):
    att = _issue(setup)
    revoke = _post(setup, f"/admin/attestations/{att['attestation_id']}/revoke", {"reason": "offboarded"})
    assert revoke.status_code == 200
    decision = _decision(_evaluate(setup, att["attestation_id"], "psl"))
    assert decision.authorized is False and decision.denial_reason == "attestation_revoked"

    now = datetime.now(timezone.utc)
    expired = _store(na_service, subject_id="psl", issued_at=now - timedelta(days=3),
                     valid_from=now - timedelta(days=3), expires_at=now - timedelta(days=1),
                     claims={"capabilities": [CAPABILITY], "applications": ["app-1"]})
    decision = _decision(_evaluate(setup, expired.attestation_id, "psl"))
    assert decision.authorized is False and decision.denial_reason == "attestation_expired"


def test_10_the_signed_form_is_unchanged(setup, na_service):
    att = _issue(setup)
    for key_id in ("psl", "asl"):
        raw = _evaluate(setup, att["attestation_id"], key_id).get_json()["decision"]
        # No new field in the binding: a 1.9.1 verifier's strict form check accepts the decision.
        assert set(raw["attestation_binding"]) == set(AttestationBinding.model_fields)
        assert decision_refusal(raw, _na_keys(na_service)) is None
        assert verify_boundary_decision(BoundaryDecision.model_validate(raw), _na_keys(na_service)).accepted


def test_11_the_python_verifier_checks_expected_ids(setup, na_service):
    att = _issue(setup)
    decision = _decision(_evaluate(setup, att["attestation_id"], "psl"))
    keys = _na_keys(na_service)

    def verify(**expected):
        return verify_boundary_decision(decision, keys, **expected)

    assert verify(expected_attestation_id=att["attestation_id"], expected_subject_id="psl").reason == "authorized"
    assert verify(expected_attestation_id="another-attestation").reason == "attestation_binding_mismatch"
    assert verify(expected_subject_id="asl").reason == "attestation_binding_mismatch"
    assert not verify(expected_subject_id="asl").accepted
    # A signed decision without an attestation binding fails when an expectation is given.
    unbound = decision.model_copy(update={"attestation_binding": None, "signature": None})
    unbound.signature = sign_model(unbound, na_service.na_private_key, na_service.key_id)
    assert verify_boundary_decision(unbound, keys).accepted
    assert verify_boundary_decision(unbound, keys, expected_subject_id="psl").reason == "attestation_binding_missing"
    assert verify_boundary_decision(unbound, keys, expected_attestation_id="a").reason == "attestation_binding_missing"


def test_unit_caller_is_subject():
    from genesis_mesh.trust.context.attestation_basis import caller_is_subject

    own, other = generate_keypair(), generate_keypair()
    now = datetime.now(timezone.utc)
    att = MembershipAttestation(
        attestation_id="a", issuer_sovereign_id="TEST", subject_id="psl", subject_public_key=own.public_key_b64,
        roles=[], status="active", issued_at=now, valid_from=now, expires_at=now + timedelta(days=1),
        issued_by="k", claims={},
    )
    assert caller_is_subject(att, "psl", own.public_key_b64)
    assert caller_is_subject(att, "renamed", own.public_key_b64)
    assert not caller_is_subject(att, "psl", other.public_key_b64)
    assert not caller_is_subject(att, "psl", None)
    assert not caller_is_subject(att, "psl", "not base64!")
    unbound = att.model_copy(update={"subject_public_key": None})
    assert caller_is_subject(unbound, "psl", other.public_key_b64)
    assert not caller_is_subject(unbound, "asl", own.public_key_b64)
