"""Tests for attestation-backed boundary evaluation (v0.58.1).

A request is evaluated under a MembershipAttestation the Network Authority
issued instead of an AgreementRecord.  Revoking the attestation -- locally or
through an imported revocation feed -- blocks every later decision, and the
signed decision binds the exact attestation it relied on.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from genesis_mesh.cli.boundary_policy_ops import boundary_policy
from genesis_mesh.cli.context_ops import context as context_group
from genesis_mesh.crypto import sign_model
from genesis_mesh.models import ContextRecord, MembershipAttestation, SovereignRevocationFeed
from genesis_mesh.models.context import BoundaryDecision, GateResult
from genesis_mesh.models.justification import JustificationProof
from genesis_mesh.trust.context import (
    GateRegistry,
    assess_attestation_basis,
    fact_path_error,
    resolve_fact,
    validate_boundary_policy,
    verify_boundary_decision,
)
from genesis_mesh.trust.context.registry import MISSING, AttestationClaimGate, AttestationClaimConfig
from genesis_mesh.trust.justification import verify_justification_proof

from .test_na_boundary_policy import _activate, _iso, _make_service, _post
from .test_na_trust_api import _make_agreement

SUBJECT = "vendor-acme"


@pytest.fixture
def na_service():
    return _make_service()


@pytest.fixture
def client(na_service):
    na_service.app.config["TESTING"] = True
    c = na_service.app.test_client()
    setattr(c, "operator_keypair", na_service._test_operator_keypair)
    setattr(c, "std_keypair", na_service._std_keypair)
    return c


def _na_keys(na_service) -> list[str]:
    return na_service.boundary_policies.policy_public_keys()


def _issue(client, *, apps=("billing",), capabilities=("app.invoke",), subject=SUBJECT) -> dict:
    body = {
        "subject_id": subject,
        "roles": ["role:client"],
        "claims": {"capabilities": list(capabilities), "apps": list(apps)},
    }
    resp = _post(client, "/admin/attestations", body)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def _apps_policy(client) -> None:
    body = {
        "policy_id": "vendor-apps",
        "description": "vendors may only use their attested apps",
        "valid_from": _iso(-timedelta(hours=1)),
        "valid_until": _iso(timedelta(days=7)),
        "selector": {"parent_kinds": ["attestation"]},
        "gates": [
            {"gate_id": "app-claim", "gate_type": "attestation_claim.v1", "order": 0,
             "config": {"path": "request_parameters.app_id", "claim": "apps"}},
        ],
    }
    resp = _post(client, "/admin/boundary-policies", body)
    assert resp.status_code == 201, resp.get_json()
    assert _activate(client, "vendor-apps", resp.get_json()["version"]).status_code == 200


def _evaluate(client, attestation_id, *, app="billing", capability="app.invoke", requester=None, **extra):
    context: dict = {"request_parameters": {"app_id": app}}
    if requester is not None:
        context["requester_sovereign_id"] = requester
    body = {"attestation_id": attestation_id, "requested_capability": capability, "context": context, **extra}
    return _post(client, "/admin/boundary/evaluate", body)


def _decision(resp) -> BoundaryDecision:
    assert resp.status_code == 201, resp.get_json()
    return BoundaryDecision.model_validate(resp.get_json()["decision"])


def _store(na_service, **overrides) -> MembershipAttestation:
    """Sign and store an attestation directly (for windows the route cannot issue)."""
    now = datetime.now(timezone.utc)
    fields = dict(
        attestation_id=str(uuid.uuid4()),
        issuer_sovereign_id=na_service.genesis_block.network_name,
        subject_id=SUBJECT,
        roles=["role:client"],
        status="active",
        issued_at=now - timedelta(days=2),
        valid_from=now - timedelta(days=2),
        expires_at=now + timedelta(days=2),
        issued_by=na_service.key_id,
        claims={"capabilities": ["app.invoke"], "apps": ["billing"]},
    )
    fields.update(overrides)
    att = MembershipAttestation(**fields)
    att.signatures.append(sign_model(att, na_service.na_private_key, na_service.key_id))
    na_service.db.save_membership_attestation(att)
    return att


# ---------------------------------------------------------------------------
# NA route: allow / deny
# ---------------------------------------------------------------------------


def test_allows_valid_attestation_with_app_in_claims(client, na_service):
    _apps_policy(client)
    att = _issue(client)
    resp = _evaluate(client, att["attestation_id"])
    decision = _decision(resp)

    assert decision.authorized is True
    assert [g.gate_name for g in decision.gate_results][:4] == [
        "attestation_status", "attestation_validity", "capability_check", "freshness_check",
    ]
    assert decision.gate_results[-1].gate_name == "vendor-apps/app-claim"
    binding = decision.attestation_binding
    assert binding is not None and binding.subject_id == SUBJECT
    assert binding.attestation_digest == MembershipAttestation.model_validate(att).digest()
    assert decision.policy_binding is not None
    assert [p.policy_id for p in decision.policy_binding.policies] == ["vendor-apps"]

    result = verify_boundary_decision(
        decision, _na_keys(na_service), expected_attestation=MembershipAttestation.model_validate(att)
    )
    assert result.accepted and result.reason == "authorized"
    proof = JustificationProof.model_validate(resp.get_json()["justification_proof"])
    assert verify_justification_proof(proof, _na_keys(na_service), decision=decision).valid


def test_denies_app_not_in_attestation_claims(client):
    _apps_policy(client)
    att = _issue(client, apps=["billing"])
    decision = _decision(_evaluate(client, att["attestation_id"], app="payroll"))
    assert decision.authorized is False
    assert decision.denial_reason == "policy gate 'vendor-apps/app-claim' failed"
    evaluation = decision.policy_binding.gate_evaluations[0]
    assert evaluation.gate_type == "attestation_claim.v1" and evaluation.outcome == "fail"


def test_denies_capability_not_in_attested_capabilities(client):
    att = _issue(client, capabilities=["app.read"])
    decision = _decision(_evaluate(client, att["attestation_id"], capability="app.invoke"))
    assert decision.authorized is False
    assert decision.denial_reason == "capability out of scope"


def test_denies_after_issuer_revocation(client, na_service):
    att = _issue(client)
    assert _decision(_evaluate(client, att["attestation_id"])).authorized is True
    revoke = _post(client, f"/admin/attestations/{att['attestation_id']}/revoke", {"reason": "offboarded"})
    assert revoke.status_code == 200

    decision = _decision(_evaluate(client, att["attestation_id"]))
    assert decision.authorized is False
    assert decision.denial_reason == "attestation_revoked"
    assert [g.gate_name for g in decision.gate_results][0] == "attestation_status"
    dumped = json.dumps(na_service.db.list_audit_events())
    assert "boundary_attestation_decision_made" in dumped and "attestation_revoked" in dumped


def test_denies_after_revocation_in_imported_feed(client, na_service):
    att = _issue(client)
    feed = SovereignRevocationFeed(
        feed_id=str(uuid.uuid4()),
        issuer_sovereign_id=att["issuer_sovereign_id"],
        sequence=7,
        issued_at=datetime.now(timezone.utc),
        revoked_attestation_ids=[att["attestation_id"]],
        issued_by="peer-key",
    )
    na_service.db.save_sovereign_revocation_feed(feed)

    decision = _decision(_evaluate(client, att["attestation_id"]))
    assert decision.authorized is False
    assert decision.denial_reason == "attestation_revoked"
    assert decision.attestation_binding.revocation_seq_checked == 7
    assert "imported revocation feed" in decision.gate_results[0].detail


def test_denies_expired_and_not_yet_valid_attestations(client, na_service):
    now = datetime.now(timezone.utc)
    expired = _store(na_service, issued_at=now - timedelta(days=3), valid_from=now - timedelta(days=3),
                     expires_at=now - timedelta(days=1))
    decision = _decision(_evaluate(client, expired.attestation_id))
    assert decision.authorized is False and decision.denial_reason == "attestation_expired"

    future = _store(na_service, issued_at=now, valid_from=now + timedelta(days=1), expires_at=now + timedelta(days=3))
    decision = _decision(_evaluate(client, future.attestation_id))
    assert decision.authorized is False and decision.denial_reason == "attestation_not_yet_valid"


def test_denies_tampered_attestation(client, na_service):
    att = _store(na_service)
    tampered = att.model_copy(update={"claims": {"capabilities": ["app.invoke", "admin.all"], "apps": ["*"]}})
    na_service.db.save_membership_attestation(tampered)
    decision = _decision(_evaluate(client, att.attestation_id))
    assert decision.authorized is False and decision.denial_reason == "attestation_invalid"
    # The binding records what was evaluated, so the tampered digest is visible.
    assert decision.attestation_binding.attestation_digest == tampered.digest()


def test_denies_unknown_attestation_with_signed_decision(client, na_service):
    decision = _decision(_evaluate(client, "no-such-attestation"))
    assert decision.authorized is False and decision.denial_reason == "attestation_not_found"
    assert decision.attestation_binding.attestation_id == "no-such-attestation"
    assert decision.attestation_binding.attestation_digest is None
    assert verify_boundary_decision(decision, _na_keys(na_service)).accepted


def test_denies_requester_other_than_subject(client):
    att = _issue(client)
    decision = _decision(_evaluate(client, att["attestation_id"], requester="someone-else"))
    assert decision.authorized is False and decision.denial_reason == "attestation_subject_mismatch"


@pytest.mark.parametrize("basis", [
    {"agreement": {"x": 1}, "attestation_id": "a"},
    {},
])
def test_requires_exactly_one_basis(client, basis):
    body = {"requested_capability": "app.invoke", **basis}
    resp = _post(client, "/admin/boundary/evaluate", body)
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "ambiguous_basis"


def test_rejects_non_string_attestation_id(client):
    resp = _post(client, "/admin/boundary/evaluate", {"attestation_id": 5, "requested_capability": "x"})
    assert resp.status_code == 400 and resp.get_json()["error"]["code"] == "invalid_attestation_id"


def test_parent_kind_is_not_caller_controlled(client):
    att = _issue(client)
    body = {
        "attestation_id": att["attestation_id"],
        "requested_capability": "app.invoke",
        "context": {"parent_kind": "agreement", "request_parameters": {"app_id": "billing"}},
    }
    decision = _decision(_post(client, "/admin/boundary/evaluate", body))
    assert decision.authorized is True
    assert decision.agreement_id == att["attestation_id"]


# ---------------------------------------------------------------------------
# Agreement path unchanged, enforcement, offline verification
# ---------------------------------------------------------------------------


def test_agreement_path_decisions_and_contexts_stay_byte_identical(client, na_service):
    agreement = _make_agreement(client, na_service)
    resp = _post(client, "/admin/boundary/evaluate", {
        "agreement": agreement, "requested_capability": "read", "context": {},
    })
    decision = _decision(resp)
    assert decision.attestation_binding is None
    assert "attestation_binding" not in decision.to_canonical_json()
    assert verify_boundary_decision(decision, _na_keys(na_service)).accepted

    legacy = ContextRecord(
        agreement_id="agr-1", requester_sovereign_id="r", provider_sovereign_id="p",
        requested_capability="read", requested_at=datetime(2026, 1, 1, tzinfo=timezone.utc), context_id="c-1",
    )
    assert "attestation_id" not in legacy.to_canonical_json()
    expected = json.dumps(
        {k: v for k, v in legacy.model_dump(mode="json").items() if k != "attestation_id"},
        sort_keys=True, separators=(",", ":"),
    )
    assert legacy.to_canonical_json() == expected


def test_required_enforcement_applies_to_attestation_requests():
    service = _make_service(boundary_policy_enforcement="required")
    service.app.config["TESTING"] = True
    c = service.app.test_client()
    setattr(c, "operator_keypair", service._test_operator_keypair)
    att = _issue(c)

    refused = _post(c, "/admin/boundary/decide", {
        "attestation_id": att["attestation_id"], "requested_capability": "app.invoke",
    })
    assert refused.status_code == 409 and refused.get_json()["error"]["code"] == "boundary_policy_required"

    decision = _decision(_evaluate(c, att["attestation_id"]))
    assert decision.authorized is True and decision.policy_binding is not None


def test_offline_verification_matches_only_the_bound_attestation(client, na_service):
    att = MembershipAttestation.model_validate(_issue(client))
    other = MembershipAttestation.model_validate(_issue(client, apps=["payroll"]))
    decision = _decision(_evaluate(client, att.attestation_id))
    keys = _na_keys(na_service)

    assert verify_boundary_decision(decision, keys, expected_attestation=att).accepted
    mismatch = verify_boundary_decision(decision, keys, expected_attestation=other)
    assert not mismatch.accepted and mismatch.reason == "attestation_binding_mismatch"
    altered = att.model_copy(update={"claims": {**att.claims, "apps": ["billing", "payroll"]}})
    assert verify_boundary_decision(decision, keys, expected_attestation=altered).reason == "attestation_binding_mismatch"

    agreement_decision = _decision(_post(client, "/admin/boundary/evaluate", {
        "agreement": _make_agreement(client, na_service), "requested_capability": "read", "context": {},
    }))
    missing = verify_boundary_decision(agreement_decision, keys, expected_attestation=att)
    assert not missing.accepted and missing.reason == "attestation_binding_missing"


def test_denied_attestation_decision_verifies_with_attestation_reason(client, na_service):
    decision = _decision(_evaluate(client, "missing"))
    result = verify_boundary_decision(decision, _na_keys(na_service))
    assert result.accepted and result.reason == "unauthorized_attestation_basis"


def test_justification_proof_must_describe_the_decisions_gates(client, na_service):
    resp = _evaluate(client, _issue(client)["attestation_id"])
    decision = _decision(resp)
    proof = JustificationProof.model_validate(resp.get_json()["justification_proof"])
    keys = _na_keys(na_service)
    assert verify_justification_proof(proof, keys, decision=decision).valid

    swapped = decision.model_copy(update={"gate_results": [
        GateResult(gate_name="validity_window", passed=True, detail="x"), *decision.gate_results[1:],
    ]})
    result = verify_justification_proof(proof, keys, decision=swapped)
    assert not result.valid and result.reason == "trace_gate_mismatch"


# ---------------------------------------------------------------------------
# Fact paths, gate type, selector, forgery
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path,ok", [
    ("attestation.subject_id", True),
    ("attestation.roles", True),
    ("attestation.claims.apps", True),
    ("attestation.claims.region.code", True),
    ("attestation", False),
    ("attestation.subject_id.x", False),
    ("attestation.claims", False),
    ("attestation.signatures", False),
])
def test_attestation_fact_paths(path, ok):
    assert (fact_path_error(path) is None) is ok


def _context(**kw) -> ContextRecord:
    return ContextRecord(
        agreement_id="att-1", attestation_id="att-1", parent_kind="attestation",
        requester_sovereign_id=SUBJECT, provider_sovereign_id="na",
        requested_capability="app.invoke", request_parameters={"app_id": "billing"}, **kw,
    )


def test_attestation_facts_are_missing_without_a_bound_basis():
    ctx = _context()
    assert resolve_fact(ctx, "attestation.subject_id") is MISSING
    bound = ctx.with_attestation_facts({"subject_id": SUBJECT, "roles": ["role:client"], "claims": {"apps": ["billing"]}})
    assert resolve_fact(bound, "attestation.claims.apps") == ["billing"]
    assert resolve_fact(bound, "attestation.roles") == ["role:client"]
    assert bound.digest() == ctx.digest()


def test_requester_cannot_supply_attestation_facts():
    payload = _context().model_dump(mode="json")
    payload["_attestation_facts"] = {"claims": {"apps": ["anything"]}}
    forged = ContextRecord.model_validate(payload)
    assert forged.attestation_facts is None


def test_attestation_claim_gate_fails_without_basis_and_hides_values():
    gate = AttestationClaimGate()
    config = AttestationClaimConfig(path="request_parameters.app_id", claim="apps")
    outcome = gate.evaluate(_context(), config, disclose_input=False)
    assert not outcome.passed and outcome.outcome == "missing_context"

    bound = _context().with_attestation_facts({"subject_id": SUBJECT, "roles": [], "claims": {"apps": ["payroll"]}})
    outcome = gate.evaluate(bound, config, disclose_input=False)
    assert not outcome.passed and outcome.outcome == "fail"
    assert "value" not in outcome.inputs and "billing" not in outcome.detail

    bad = _context().with_attestation_facts({"subject_id": SUBJECT, "roles": [], "claims": {"apps": "billing"}})
    assert gate.evaluate(bad, config, disclose_input=False).outcome == "invalid_context"


def test_attestation_claim_gate_is_registered_and_selector_accepts_attestation():
    from genesis_mesh.models import BoundaryPolicy, GateSpec, PolicySelector

    registry = GateRegistry.default()
    assert "attestation_claim.v1" in registry.gate_types()
    now = datetime.now(timezone.utc)
    policy = BoundaryPolicy(
        policy_id="p", version=1, valid_from=now, valid_until=now + timedelta(days=1),
        selector=PolicySelector(parent_kinds=["attestation"], parameter_equals={"attestation.subject_id": [SUBJECT]}),
        gates=[GateSpec(gate_id="g", gate_type="attestation_claim.v1", order=0,
                        config={"path": "request_parameters.app_id", "claim": "apps"})],
        issued_at=now, issued_by="k", issuer_sovereign_id="na",
    )
    assert validate_boundary_policy(policy, registry).valid


def test_assessment_order_prefers_signature_over_revocation():
    import nacl.encoding
    import nacl.signing

    key = nacl.signing.SigningKey.generate()
    pub = key.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode()
    now = datetime.now(timezone.utc)
    att = MembershipAttestation(
        attestation_id="a", issuer_sovereign_id="na", subject_id=SUBJECT, issued_at=now,
        valid_from=now, expires_at=now + timedelta(days=1), issued_by="k",
    )
    unsigned = assess_attestation_basis("a", att, issuer_public_keys=[pub], stored_status="revoked",
                                        feed_revoked=True, revocation_seq_checked=0, requester_id=SUBJECT)
    assert unsigned.status_failure == "attestation_invalid" and unsigned.facts() is None
    att.signatures.append(sign_model(att, key, "k"))
    suspended = assess_attestation_basis("a", att, issuer_public_keys=[pub], stored_status="suspended",
                                         feed_revoked=False, revocation_seq_checked=0, requester_id=SUBJECT)
    assert suspended.status_failure == "attestation_revoked"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_context_request_with_attestation(tmp_path: Path):
    out = tmp_path / "ctx.json"
    result = CliRunner().invoke(context_group, [
        "request", "--attestation", "att-9", "--capability", "app.invoke",
        "--requester", SUBJECT, "--provider", "na", "--params", '{"app_id": "billing"}',
        "--output", str(out),
    ])
    assert result.exit_code == 0, result.output
    record = ContextRecord.model_validate_json(out.read_text())
    assert record.parent_kind == "attestation" and record.attestation_id == "att-9" == record.agreement_id

    neither = CliRunner().invoke(context_group, [
        "request", "--capability", "x", "--requester", "r", "--provider", "p", "--output", str(out),
    ])
    assert neither.exit_code != 0 and "exactly one" in neither.output


def test_cli_explain_shows_attestation_binding(client, tmp_path: Path):
    att = _issue(client)
    resp = _evaluate(client, att["attestation_id"])
    path = tmp_path / "decision.json"
    path.write_text(json.dumps(resp.get_json()))
    result = CliRunner().invoke(boundary_policy, ["explain", "--decision", str(path)])
    assert result.exit_code == 0, result.output
    assert f"Attestation: {att['attestation_id']}" in result.output
    assert f"subject  : {SUBJECT}" in result.output

    gate_types = CliRunner().invoke(boundary_policy, ["gate-types"])
    assert "attestation_claim.v1" in gate_types.output
