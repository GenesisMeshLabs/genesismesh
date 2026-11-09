"""1.9.2 and 1.10.0: attestation-basis evaluation is bound to the operator key that asked.

``POST /admin/boundary/evaluate`` with ``attestation_id`` checked the caller's
tier but not that the caller was the attestation's subject, so any operator
key could get decisions under another subject's attestation. The caller's key
must now be the subject: its public key equals ``subject_public_key`` when the
attestation binds one, and its key ID equals ``subject_id`` otherwise. A
mismatch is a signed, stored DENY, for every tier. The numbers in the test
names are the acceptance tests of ``ops/plan-v1.9.2.md``.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models import MembershipAttestation
from genesis_mesh.models.canonical_registry import (
    build_registry,
    decision_refusal,
    signed_as_received,
    unknown_fields,
)
from genesis_mesh.models.context import AttestationBinding, BoundaryDecision
from genesis_mesh.trust.context import verify_boundary_decision

from .test_attestation_boundary import _store
from .test_na_boundary_policy import _activate, _headers, _iso, _make_service
from .test_na_trust_api import _make_agreement

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
    assert made[-1]["requested_by"] == "asl" and made[-1]["requester_sovereign_id"] == "psl"
    assert made[-1]["denial_reason"] == "attestation_subject_mismatch"
    assert "attestation_status" in made[-1]["failed_gates"]


@pytest.mark.parametrize("bound_key", ["psl", None])
def test_3_a_privileged_key_is_denied_too(setup, bound_key):
    att = _issue(setup, subject_public_key=bound_key)
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


def test_9_agreement_basis_evaluation_is_unchanged(setup, na_service):
    # Any operator key evaluates under an agreement as before: the binding is for attestations.
    agreement = _make_agreement(setup, na_service)
    for key_id in ("asl", "operator-test"):
        resp = _post(setup, "/admin/boundary/evaluate",
                     {"agreement": agreement, "requested_capability": "read", "context": {}}, key_id)
        decision = _decision(resp)
        assert decision.authorized is True and decision.attestation_binding is None


#: AttestationBinding's fields in 1.9.1, which has ``extra="forbid"``.
BINDING_FIELDS_1_9_1 = {
    "attestation_id", "subject_id", "issuer_sovereign_id", "attestation_digest", "revocation_seq_checked",
}


def test_10_the_signed_form_is_unchanged(setup, na_service):
    """1.9.2 added no field. From 1.10.0 the binding adds only ``requester_key_id``
    (ops/plan-v1.9.2.md R8), and a binding without it keeps the 1.9.1 form."""
    att = _issue(setup)
    assert set(AttestationBinding.model_fields) == BINDING_FIELDS_1_9_1 | {"requester_key_id"}
    for key_id in ("psl", "asl"):
        raw = _evaluate(setup, att["attestation_id"], key_id).get_json()["decision"]
        assert set(raw["attestation_binding"]) == BINDING_FIELDS_1_9_1 | {"requester_key_id"}
        assert decision_refusal(raw, _na_keys(na_service)) is None
        assert verify_boundary_decision(BoundaryDecision.model_validate(raw), _na_keys(na_service)).accepted
    unbound = AttestationBinding(attestation_id="a", subject_id="s")
    assert set(unbound.model_dump()) == BINDING_FIELDS_1_9_1
    assert "requester_key_id" not in unbound.model_dump_json()


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
    # Key formats are not normalised: a key with whitespace or without padding fails closed.
    assert not caller_is_subject(att, "psl", own.public_key_b64 + " ")
    assert not caller_is_subject(att, "psl", own.public_key_b64.rstrip("="))
    unbound = att.model_copy(update={"subject_public_key": None})
    assert caller_is_subject(unbound, "psl", other.public_key_b64)
    assert not caller_is_subject(unbound, "asl", own.public_key_b64)


# -- 1.10.0 (R8, R9): the operator key that asked is signed into the decision ------------------
# ``AttestationBinding.requester_key_id`` names the key that asked, whatever the outcome, under
# the decision's signature; ``verify_boundary_decision`` takes ``expected_requester_key_id``. A
# decision without the field (a 1.9.x NA) verifies, and fails only when a requester is expected.


def _raw(setup, key_id: str) -> dict:
    att = _issue(setup)
    resp = _evaluate(setup, att["attestation_id"], key_id)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["decision"]


def _resigned_without_requester(raw: dict, na_service) -> BoundaryDecision:
    """The same decision as a 1.9.x NA wrote it: no requester, signed by the NA key."""
    decision = BoundaryDecision.model_validate(raw)
    assert decision.attestation_binding is not None
    binding = decision.attestation_binding.model_copy(update={"requester_key_id": None})
    unsigned = decision.model_copy(
        update={"attestation_binding": binding, "signature": None}
    )
    return unsigned.model_copy(
        update={
            "signature": sign_model(
                unsigned, na_service.na_private_key, na_service.key_id
            )
        }
    )


@pytest.mark.parametrize("key_id, authorized", [("psl", True), ("asl", False)])
def test_12_the_decision_names_the_asking_key_under_its_signature(
    setup, na_service, key_id, authorized
):
    raw = _raw(setup, key_id)
    assert raw["authorized"] is authorized
    assert raw["attestation_binding"]["requester_key_id"] == key_id
    keys = _na_keys(na_service)
    assert decision_refusal(raw, keys) is None
    assert verify_boundary_decision(BoundaryDecision.model_validate(raw), keys).accepted
    edited = copy.deepcopy(raw)
    edited["attestation_binding"]["requester_key_id"] = (
        "psl" if key_id == "asl" else "asl"
    )
    # The SDKs verify the signature over the record as received: the field is covered.
    assert signed_as_received("BoundaryDecision", raw, keys)
    assert not signed_as_received("BoundaryDecision", edited, keys)
    assert (
        verify_boundary_decision(BoundaryDecision.model_validate(edited), keys).reason
        == "invalid_signature"
    )


def test_13_an_expected_requester_passes_only_for_the_key_that_asked(setup, na_service):
    decision = _decision(_evaluate(setup, _issue(setup)["attestation_id"], "psl"))
    keys = _na_keys(na_service)
    assert (
        verify_boundary_decision(decision, keys, expected_requester_key_id="psl").reason
        == "authorized"
    )
    other = verify_boundary_decision(decision, keys, expected_requester_key_id="asl")
    assert (other.accepted, other.reason) == (False, "attestation_binding_mismatch")
    both = verify_boundary_decision(
        decision, keys, expected_subject_id="psl", expected_requester_key_id="asl"
    )
    assert both.reason == "attestation_binding_mismatch"


def test_14_a_decision_without_a_requester_fails_only_when_one_is_expected(
    setup, na_service
):
    old = _resigned_without_requester(_raw(setup, "psl"), na_service)
    assert old.attestation_binding.requester_key_id is None
    assert "requester_key_id" not in old.model_dump_json()
    keys = _na_keys(na_service)
    assert verify_boundary_decision(old, keys).reason == "authorized"
    assert (
        verify_boundary_decision(old, keys, expected_subject_id="psl").reason
        == "authorized"
    )
    missing = verify_boundary_decision(old, keys, expected_requester_key_id="psl")
    assert (missing.accepted, missing.reason) == (False, "attestation_binding_missing")
    assert decision_refusal(old.model_dump(mode="json"), keys) is None


def test_a_1_9_verifier_refuses_the_new_field_as_unknown(setup):
    """Why verifying 1.10.0 decisions needs 1.10.0 SDKs: the 1.9.x registry lacks the field."""
    raw = _raw(setup, "psl")
    registry = build_registry()
    assert unknown_fields("BoundaryDecision", raw, registry) == []
    old = copy.deepcopy(registry)
    del old["models"]["AttestationBinding"]["fields"]["requester_key_id"]
    assert unknown_fields("BoundaryDecision", raw, old) == [
        "attestation_binding.requester_key_id"
    ]


# -- 1.10.0 (R10): a standard-tier key sees only the attestations whose subject it is -----------
# GET /attestations lists, and a signed GET /attestations/<id> reads, only the caller's own
# attestations for a standard-tier key, by the subject rule of 1.9.2; another subject's
# attestation is answered as one that does not exist. Read and privileged keys see all of them.
# Unsigned, the list is the count only (v1.0.2), and the read by ID is the status and lineage
# only (1.10.0): the public revocation feed names every revoked ID, so an ID is no secret.


def _get(client, url: str, key_id: str | None):
    if key_id is None:
        return client.get(url)
    return client.get(url, headers=_headers(client.keys[key_id], key_id, {}, client=client, method="GET", url=url))


@pytest.fixture
def roster(client, na_service):
    reader = generate_keypair()
    na_service.operator_public_keys["rdr"] = reader.public_key_b64
    na_service.operator_key_tiers["rdr"] = "read"
    client.keys["rdr"] = reader
    own = _issue(client, subject="psl", subject_public_key="psl")
    by_id = _issue(client, subject="psl", subject_public_key=None)  # no key bound: the key ID is the subject
    other = _issue(client, subject="asl", subject_public_key="asl")
    foreign_key = _issue(client, subject="psl", subject_public_key="asl")  # psl's ID, asl's key bound
    return client, {"own": own, "by_id": by_id, "other": other, "foreign_key": foreign_key}


def _listed(client, key_id: str, query: str = "") -> set[str]:
    resp = _get(client, f"/attestations{query}", key_id)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    ids = {row["attestation"]["attestation_id"] for row in body["attestations"]}
    assert body["count"] == len(ids)
    return ids


def test_15_a_standard_key_lists_only_its_own_attestations(roster):
    client, att = roster
    mine = {att["own"]["attestation_id"], att["by_id"]["attestation_id"]}
    assert _listed(client, "psl") == mine
    assert _listed(client, "psl", "?subject_id=asl") == set()
    assert _listed(client, "asl") == {att["other"]["attestation_id"], att["foreign_key"]["attestation_id"]}
    assert _listed(client, "operator-std") == set()


def test_16_a_standard_key_reads_another_subjects_attestation_as_missing(roster):
    client, att = roster
    assert _get(client, f"/attestations/{att['own']['attestation_id']}", "psl").status_code == 200
    assert _get(client, f"/attestations/{att['by_id']['attestation_id']}", "psl").status_code == 200
    missing = _get(client, "/attestations/00000000-0000-4000-8000-00000000dead", "psl")
    for name in ("other", "foreign_key"):
        resp = _get(client, f"/attestations/{att[name]['attestation_id']}", "psl")
        assert resp.status_code == 404, name
        # Indistinguishable from an ID that does not exist (decision 3), apart from the request ID.
        assert {k: v for k, v in resp.get_json()["error"].items() if k != "request_id"} == {
            k: v for k, v in missing.get_json()["error"].items() if k != "request_id"
        }


@pytest.mark.parametrize("key_id", ["rdr", "operator-test"])
def test_17_read_and_privileged_keys_see_every_attestation(roster, key_id):
    client, att = roster
    assert _listed(client, key_id) == {a["attestation_id"] for a in att.values()}
    for a in att.values():
        assert _get(client, f"/attestations/{a['attestation_id']}", key_id).status_code == 200


STATUS_FIELDS = {"attestation_id", "status", "revoked_at", "revocation_reason", "reissued_from", "superseded_by"}


def test_an_unsigned_list_is_the_count_only(roster):
    client, _ = roster
    body = _get(client, "/attestations", None).get_json()
    assert body == {"count": 4}
    assert _get(client, "/attestations?subject_id=psl", None).status_code == 401


def test_an_unsigned_read_by_id_is_the_status_only(roster):
    client, att = roster
    for a in att.values():
        resp = _get(client, f"/attestations/{a['attestation_id']}", None)
        assert resp.status_code == 200
        body = resp.get_json()
        assert set(body) == STATUS_FIELDS
        assert (body["attestation_id"], body["status"]) == (a["attestation_id"], "active")
    missing = _get(client, "/attestations/00000000-0000-4000-8000-00000000dead", None)
    assert (missing.status_code, missing.get_json()["error"]["code"]) == (404, "attestation_not_found")


def test_the_revocation_feed_does_not_lead_to_revoked_members(roster):
    """The public feed names revoked IDs: reading one unsigned gives no subject, key, roles or claims."""
    client, att = roster
    url = f"/admin/attestations/{att['other']['attestation_id']}/revoke"
    body = {"reason": "offboarded"}
    headers = _headers(client.keys["operator-test"], "operator-test", body, client=client, method="POST", url=url)
    assert client.post(url, json=body, headers=headers).status_code == 200
    feed = client.get("/sovereign-revocation-feed").get_json()
    assert att["other"]["attestation_id"] in feed["revoked_attestation_ids"]
    for attestation_id in feed["revoked_attestation_ids"]:
        read = _get(client, f"/attestations/{attestation_id}", None).get_json()
        assert set(read) == STATUS_FIELDS
        assert (read["status"], read["revocation_reason"]) == ("revoked", "offboarded")
        assert "asl" not in json.dumps(read)


def test_a_signed_read_by_id_must_verify(roster):
    client, att = roster
    url = f"/attestations/{att['own']['attestation_id']}"
    headers = _headers(client.keys["psl"], "psl", {}, client=client, method="GET", url=url)
    headers["X-Admin-Key-Id"] = "asl"  # psl's signature presented as asl's
    assert client.get(url, headers=headers).status_code == 401
