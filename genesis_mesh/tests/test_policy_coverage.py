"""Policy coverage (1.10.0): BOUNDARY_POLICY_COVERAGE and expected policy IDs.

A controller that keeps its scope rules in a boundary policy loses them when
the policy is deactivated or its selector stops matching: the request then
rests on the built-in gates alone and is allowed. With
``BOUNDARY_POLICY_COVERAGE=required`` the NA signs a DENY instead
(``no_applicable_policy``), and ``expected_policy_ids`` lets a relying party
refuse such an ALLOW offline without pinning policy versions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

import pytest

from genesis_mesh.crypto import generate_keypair
from genesis_mesh.models import BoundaryPolicy, ContextRecord
from genesis_mesh.models.boundary_policy import GateSpec, PolicySelector
from genesis_mesh.models.context import BoundaryDecision
from genesis_mesh.na_service.settings import load_settings
from genesis_mesh.trust.context import GateRegistry, sign_boundary_policy, verify_boundary_decision
from genesis_mesh.trust.context.policy import resolve_policies
from genesis_mesh.trust.evidence_store import parse_export_lines

from .test_attestation_boundary import _issue
from .test_na_boundary_policy import _activate, _get, _iso, _make_service, _post
from .test_na_trust_api import _make_agreement

NOW = datetime.now(timezone.utc)


def _client(**kwargs):
    service = _make_service(**kwargs)
    service.app.config["TESTING"] = True
    c = service.app.test_client()
    setattr(c, "operator_keypair", service._test_operator_keypair)
    setattr(c, "std_keypair", service._std_keypair)
    return service, c


def _credentials_policy(client, *, mode: str = "enforce", capabilities=("credentials.*",)) -> int:
    """A policy holding the scope rule: the app must be in the attestation's claims."""
    body = {
        "policy_id": "internal-credentials",
        "description": "create and rotate credentials of attested apps only",
        "valid_from": _iso(-timedelta(hours=1)),
        "valid_until": _iso(timedelta(days=7)),
        "selector": {"parent_kinds": ["attestation"], "capabilities": list(capabilities)},
        "gates": [
            {"gate_id": "app-claim", "gate_type": "attestation_claim.v1", "order": 0, "mode": mode,
             "config": {"path": "request_parameters.app_id", "claim": "apps"}},
        ],
    }
    resp = _post(client, "/admin/boundary-policies", body)
    assert resp.status_code == 201, resp.get_json()
    version = resp.get_json()["version"]
    assert _activate(client, "internal-credentials", version).status_code == 200
    return version


def _deactivate(client, version: int) -> None:
    resp = _post(client, "/admin/boundary-policies/internal-credentials/deactivate", {"version": version})
    assert resp.status_code == 200, resp.get_json()


def _evaluate(client, attestation_id: str, *, capability: str = "credentials.rotate", app: str = "billing"):
    body = {"attestation_id": attestation_id, "requested_capability": capability,
            "context": {"request_parameters": {"app_id": app}}}
    resp = _post(client, "/admin/boundary/evaluate", body)
    assert resp.status_code == 201, resp.get_json()
    return BoundaryDecision.model_validate(resp.get_json()["decision"])


def _attestation(client) -> str:
    return _issue(client, capabilities=("credentials.rotate", "credentials.retire"))["attestation_id"]


def _na_keys(service) -> list[str]:
    return service.boundary_policies.policy_public_keys()


# ── resolution ──────────────────────────────────────────────────────────────


def _policy(mode: Literal["enforce", "observe"] = "enforce", capabilities=("read",)) -> BoundaryPolicy:
    signer = generate_keypair()
    policy = sign_boundary_policy(BoundaryPolicy(
        policy_id="read-limits", version=1, description="cap rows",
        valid_from=NOW - timedelta(hours=1), valid_until=NOW + timedelta(days=1),
        selector=PolicySelector(capabilities=list(capabilities)),
        gates=[GateSpec(gate_id="row-cap", gate_type="max_value.v1", order=0, mode=mode,
                        config={"path": "request_parameters.rows", "max": 100})],
        issued_at=NOW - timedelta(hours=1), issued_by="na-key", issuer_sovereign_id="TEST",
    ), signer.private_key, "na-key")
    setattr(policy, "_test_public_key", signer.public_key_b64)
    return policy


def _context(capability: str = "read") -> ContextRecord:
    return ContextRecord(
        context_id="ctx-1", agreement_id="agr-1", requester_sovereign_id="B", provider_sovereign_id="TEST",
        requested_capability=capability, request_parameters={"rows": 10}, attributes={}, requested_at=NOW,
    )


def _resolve(policies, capability: str = "read", **kwargs):
    keys = [getattr(p, "_test_public_key") for p in policies]
    return resolve_policies(policies, _context(capability), GateRegistry.default(), keys, NOW, **kwargs)


def test_resolution_without_coverage_resolves_a_request_no_policy_covers():
    resolution = _resolve([])
    assert resolution.resolved and resolution.applied == ()


def test_required_coverage_fails_resolution_when_no_policy_applies():
    resolution = _resolve([_policy()], capability="write", require_coverage=True)
    assert not resolution.resolved and resolution.failure == "no_applicable_policy"


def test_required_coverage_counts_only_enforce_mode_gates():
    resolution = _resolve([_policy(mode="observe")], require_coverage=True)
    assert not resolution.resolved and resolution.failure == "no_applicable_policy"


def test_required_coverage_resolves_a_request_an_enforcing_policy_covers():
    resolution = _resolve([_policy()], require_coverage=True)
    assert resolution.resolved and [p.policy_id for p in resolution.applied] == ["read-limits"]


def test_required_coverage_keeps_the_earlier_failure_codes():
    resolution = _resolve([_policy()], capability="write", require_coverage=True,
                          integrity_failures=["boundary_policy_versions:1"])
    assert resolution.failure == "policy_store_integrity_failed"


# ── the NA ──────────────────────────────────────────────────────────────────


def test_a_deactivated_policy_leaves_an_allow_by_default():
    service, client = _client()
    version = _credentials_policy(client)
    attestation_id = _attestation(client)
    assert _evaluate(client, attestation_id).authorized is True
    _deactivate(client, version)

    decision = _evaluate(client, attestation_id)
    assert decision.authorized is True
    assert decision.policy_binding is not None and decision.policy_binding.policies == []


def test_required_coverage_denies_once_the_policy_is_deactivated():
    service, client = _client(boundary_policy_coverage="required", evidence_store="on")
    version = _credentials_policy(client)
    attestation_id = _attestation(client)
    covered = _evaluate(client, attestation_id)
    assert covered.authorized is True
    _deactivate(client, version)

    decision = _evaluate(client, attestation_id)
    assert decision.authorized is False
    assert decision.denial_reason == "policy resolution failed: no_applicable_policy"
    binding = decision.policy_binding
    assert binding is not None and binding.resolution_status == "failed"
    assert binding.resolution_failure == "no_applicable_policy" and binding.policies == []
    result = verify_boundary_decision(decision, _na_keys(service))
    assert result.accepted and result.reason == "unauthorized_policy_resolution_failed"

    events = parse_export_lines(_get(client, "/admin/evidence/export").get_data(as_text=True).splitlines())
    stored = {e.payload["decision"]["decision_id"]: e.payload["decision"]
              for e in events if e.entry.entry_kind == "decision"}
    assert stored[covered.decision_id]["authorized"] is True
    denied = stored[decision.decision_id]
    assert denied["authorized"] is False
    assert denied["policy_binding"]["resolution_failure"] == "no_applicable_policy"


def test_required_coverage_denies_when_the_selector_stops_matching():
    _, client = _client(boundary_policy_coverage="required")
    _credentials_policy(client, capabilities=("credentials.rotate",))
    attestation_id = _attestation(client)
    assert _evaluate(client, attestation_id, capability="credentials.rotate").authorized is True

    decision = _evaluate(client, attestation_id, capability="credentials.retire")
    assert decision.authorized is False
    assert decision.policy_binding is not None
    assert decision.policy_binding.resolution_failure == "no_applicable_policy"


def test_required_coverage_denies_under_an_observe_only_policy():
    _, client = _client(boundary_policy_coverage="required")
    _credentials_policy(client, mode="observe")
    decision = _evaluate(client, _attestation(client))
    assert decision.authorized is False
    assert decision.policy_binding is not None
    assert decision.policy_binding.resolution_failure == "no_applicable_policy"


def test_required_coverage_denies_an_agreement_request_no_policy_covers():
    service, client = _client(boundary_policy_coverage="required")
    agreement = _make_agreement(client, service)
    resp = _post(client, "/admin/boundary/evaluate", {
        "agreement": agreement, "requested_capability": "read", "context": {"request_parameters": {}},
    })
    assert resp.status_code == 201
    decision = resp.get_json()["decision"]
    assert decision["authorized"] is False
    assert decision["policy_binding"]["resolution_failure"] == "no_applicable_policy"


def test_a_failing_builtin_gate_keeps_its_denial_reason_under_required_coverage():
    _, client = _client(boundary_policy_coverage="required")
    decision = _evaluate(client, _attestation(client), capability="credentials.delete")
    assert decision.authorized is False
    assert decision.denial_reason is not None and "no_applicable_policy" not in decision.denial_reason
    assert decision.policy_binding is not None
    assert decision.policy_binding.resolution_failure == "no_applicable_policy"


def test_required_coverage_refuses_the_legacy_decide_route():
    service, client = _client(boundary_policy_coverage="required")
    agreement = _make_agreement(client, service)
    resp = _post(client, "/admin/boundary/decide", {"agreement": agreement, "requested_capability": "read"})
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "boundary_policy_required"


def test_the_coverage_mode_is_reported():
    _, client = _client(boundary_policy_coverage="required")
    assert client.get("/health").get_json()["boundary_policy_coverage"] == "required"
    assert _get(client, "/admin/boundary-policies/active").get_json()["coverage"] == "required"
    assert "Coverage: required" in client.get("/dashboard").get_data(as_text=True)


def test_the_coverage_mode_defaults_to_optional():
    _, client = _client()
    assert client.get("/health").get_json()["boundary_policy_coverage"] == "optional"


def test_an_unknown_coverage_mode_is_refused():
    with pytest.raises(ValueError):
        _make_service(boundary_policy_coverage="sometimes")


def test_settings_read_the_coverage_mode():
    assert load_settings({"GENESIS_FILE": "g.json"}).boundary_policy_coverage == "optional"
    env = {"GENESIS_FILE": "g.json", "BOUNDARY_POLICY_COVERAGE": "required"}
    assert load_settings(env).boundary_policy_coverage == "required"


# ── expected policy IDs ─────────────────────────────────────────────────────


def test_expected_policy_ids_accept_an_allow_the_policy_governed():
    service, client = _client()
    _credentials_policy(client)
    decision = _evaluate(client, _attestation(client))
    result = verify_boundary_decision(decision, _na_keys(service), expected_policy_ids=["internal-credentials"])
    assert result.accepted and result.reason == "authorized"


def test_expected_policy_ids_accept_any_version_the_na_signed():
    service, client = _client()
    _credentials_policy(client)
    later = _credentials_policy(client)
    assert later == 2
    decision = _evaluate(client, _attestation(client))
    assert decision.policy_binding is not None and decision.policy_binding.policies[0].version == 2
    result = verify_boundary_decision(decision, _na_keys(service), expected_policy_ids=["internal-credentials"])
    assert result.accepted


def test_expected_policy_ids_refuse_an_allow_after_the_policy_is_deactivated():
    service, client = _client()
    version = _credentials_policy(client)
    attestation_id = _attestation(client)
    _deactivate(client, version)
    decision = _evaluate(client, attestation_id)
    assert decision.authorized is True
    result = verify_boundary_decision(decision, _na_keys(service), expected_policy_ids=["internal-credentials"])
    assert not result.accepted and result.reason == "policy_binding_mismatch"


def test_expected_policy_ids_refuse_an_allow_under_an_observe_only_policy():
    service, client = _client()
    _credentials_policy(client, mode="observe")
    decision = _evaluate(client, _attestation(client))
    assert decision.authorized is True
    result = verify_boundary_decision(decision, _na_keys(service), expected_policy_ids=["internal-credentials"])
    assert not result.accepted and result.reason == "policy_binding_mismatch"


def test_expected_policy_ids_report_a_deny_as_it_is():
    service, client = _client()
    _credentials_policy(client)
    decision = _evaluate(client, _attestation(client), app="payroll")
    assert decision.authorized is False
    result = verify_boundary_decision(decision, _na_keys(service), expected_policy_ids=["internal-credentials"])
    assert result.accepted and result.reason == "unauthorized_policy_gate_failure"


def test_expected_policy_ids_refuse_an_allow_without_a_policy_binding():
    service, client = _client()
    agreement = _make_agreement(client, service)
    resp = _post(client, "/admin/boundary/decide", {"agreement": agreement, "requested_capability": "read"})
    assert resp.status_code == 201
    raw = resp.get_json()
    decision = BoundaryDecision.model_validate(raw.get("decision", raw))
    assert decision.authorized is True and decision.policy_binding is None
    result = verify_boundary_decision(decision, _na_keys(service), expected_policy_ids=["internal-credentials"])
    assert not result.accepted and result.reason == "policy_binding_missing"


def test_an_edited_policy_binding_fails_the_signature_before_the_ids_are_read():
    service, client = _client()
    version = _credentials_policy(client)
    attestation_id = _attestation(client)
    covered = _evaluate(client, attestation_id)
    _deactivate(client, version)
    uncovered = _evaluate(client, attestation_id)
    forged = uncovered.model_copy(update={"policy_binding": covered.policy_binding})
    result = verify_boundary_decision(forged, _na_keys(service), expected_policy_ids=["internal-credentials"])
    assert not result.accepted and result.reason == "invalid_signature"
