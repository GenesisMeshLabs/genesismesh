"""Agreements presented by callers must be signed by trusted parties (v1.1.1).

Before 1.1.1 the NA parsed the agreement a caller sent and decided under it
without checking who signed it, so a fabricated agreement earned an NA-signed
ALLOW. The NA now trusts an agreement only if two different parties signed it
with keys it trusts (its own key, or a key from an active recognition treaty it
issued), and binds the requester and provider to the agreement's parties.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models.agreement import AgreementRecord
from genesis_mesh.trust.agreement import AgreementTerms, accept_counter, build_counter, build_offer

from .test_attestation_boundary import _issue
from .test_na_boundary_policy import _make_service, _post

ORG = "org-a"
BANK = "bank-a"


def _client(service):
    service.app.config["TESTING"] = True
    c = service.app.test_client()
    setattr(c, "operator_keypair", getattr(service, "_test_operator_keypair"))
    setattr(c, "std_keypair", getattr(service, "_std_keypair"))
    setattr(c, "service", service)
    return c


@pytest.fixture
def client():
    return _client(_make_service())


def _graph(org_pub: str, bank_pub: str, now: datetime) -> dict:
    edge = {"status": "active", "lifecycle_state": "active", "expiry_risk": "low",
            "valid_from": now.isoformat(), "expires_at": (now + timedelta(days=365)).isoformat()}
    return {
        "sovereigns": [{"sovereign_id": ORG, "public_key": org_pub}, {"sovereign_id": BANK, "public_key": bank_pub}],
        "recognition_edges": [{"from": ORG, "to": BANK, "treaty_id": "t-ab", **edge},
                              {"from": BANK, "to": ORG, "treaty_id": "t-ba", **edge}],
    }


def _foreign_agreement():
    """A dual-signed agreement between two sovereigns the NA does not know yet."""
    now = datetime.now(timezone.utc)
    org, bank = generate_keypair(), generate_keypair()
    terms = AgreementTerms(capabilities=["transactions.read"], scope={"accounts": ["acc-001"]},
                           valid_from=now - timedelta(hours=1), valid_until=now + timedelta(days=30))
    graph = _graph(org.public_key_b64, bank.public_key_b64, now)
    offer = build_offer(ORG, BANK, terms, graph, org.private_key, issued_by=org.public_key_b64,
                        expires_at=now + timedelta(days=1))
    counter = build_counter(offer, terms, graph, bank.private_key, issued_by=bank.public_key_b64)
    agreement = accept_counter(counter, offer, org.private_key, issued_by=org.public_key_b64)
    return agreement.model_dump(mode="json"), org, bank


def _recognise(client, sovereign: str, public_key: str, hours: int = 24) -> dict:
    resp = _post(client, "/admin/recognition-treaties", {
        "subject_sovereign_id": sovereign, "subject_public_keys": [public_key],
        "scope": {"allowed_roles": ["role:client"]}, "validity_hours": hours,
    })
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def _evaluate(client, agreement: dict, **context):
    return _post(client, "/admin/boundary/evaluate", {
        "agreement": agreement, "requested_capability": "transactions.read", "context": context,
    })


def _error(resp) -> dict:
    return resp.get_json()["error"]


# --- agreement trust ------------------------------------------------------------


def test_agreement_between_unknown_parties_is_refused_and_audited(client):
    agreement, _, _ = _foreign_agreement()
    resp = _evaluate(client, agreement)
    assert resp.status_code == 422
    assert _error(resp)["code"] == "agreement_untrusted"
    assert _error(resp)["details"] == {"reason": "unknown_party", "party": ORG}
    events = [e for e in client.service.db.list_audit_events() if e["event_type"] == "agreement_untrusted"]
    assert events and events[-1]["details"]["route"] == "/admin/boundary/evaluate"


def test_agreement_between_recognised_parties_is_accepted(client):
    agreement, org, bank = _foreign_agreement()
    _recognise(client, ORG, org.public_key_b64)
    _recognise(client, BANK, bank.public_key_b64)
    resp = _evaluate(client, agreement)
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["decision"]["authorized"] is True


def test_fabricated_capability_breaks_the_signatures(client):
    agreement, org, bank = _foreign_agreement()
    _recognise(client, ORG, org.public_key_b64)
    _recognise(client, BANK, bank.public_key_b64)
    forged = copy.deepcopy(agreement)
    forged["agreed_terms"]["capabilities"].append("secret.delete_everything")
    resp = _post(client, "/admin/boundary/evaluate", {
        "agreement": forged, "requested_capability": "secret.delete_everything",
    })
    assert resp.status_code == 422 and _error(resp)["code"] == "agreement_untrusted"


def test_unsigned_agreement_is_refused(client):
    agreement, org, bank = _foreign_agreement()
    _recognise(client, ORG, org.public_key_b64)
    _recognise(client, BANK, bank.public_key_b64)
    agreement["signatures"] = []
    resp = _evaluate(client, agreement)
    assert resp.status_code == 422 and _error(resp)["code"] == "agreement_untrusted"


def test_a_party_signing_with_another_key_is_refused(client):
    agreement, org, _ = _foreign_agreement()
    _recognise(client, ORG, org.public_key_b64)
    _recognise(client, BANK, generate_keypair().public_key_b64)
    resp = _evaluate(client, agreement)
    assert resp.status_code == 422 and _error(resp)["code"] == "agreement_untrusted"


def test_revoked_treaty_no_longer_vouches_for_a_party(client):
    agreement, org, bank = _foreign_agreement()
    _recognise(client, ORG, org.public_key_b64)
    treaty = _recognise(client, BANK, bank.public_key_b64)
    resp = _post(client, f"/admin/recognition-treaties/{treaty['treaty_id']}/revoke", {"reason": "test"})
    assert resp.status_code == 200, resp.get_json()
    resp = _evaluate(client, agreement)
    assert resp.status_code == 422 and _error(resp)["details"]["party"] == BANK


def test_decide_and_disclosure_commit_check_the_agreement_too(client):
    agreement, _, _ = _foreign_agreement()
    decide = _post(client, "/admin/boundary/decide", {"agreement": agreement, "requested_capability": "transactions.read"})
    assert decide.status_code == 422 and _error(decide)["code"] == "agreement_untrusted"
    commit = _post(client, "/admin/disclosure/commit", {"agreement": agreement, "capabilities": ["transactions.read"]})
    assert commit.status_code == 422 and _error(commit)["code"] == "agreement_untrusted"


def _self_agreement(keypair, sovereign: str = ORG) -> dict:
    """An agreement whose offerer and responder are one sovereign, signed once.

    The negotiation helpers refuse to build one, so it is assembled directly.
    """
    now = datetime.now(timezone.utc)
    terms = AgreementTerms(capabilities=["transactions.read"], scope={},
                           valid_from=now - timedelta(hours=1), valid_until=now + timedelta(days=30))
    record = AgreementRecord(offer_id="o-self", offerer_sovereign_id=sovereign, responder_sovereign_id=sovereign,
                             agreed_terms=terms, offerer_evidence={}, responder_evidence={},
                             graph_digest="0" * 64, expires_at=now + timedelta(days=1))
    record.signatures.append(sign_model(record, keypair.private_key, "self"))
    return record.model_dump(mode="json")


def test_a_sovereign_cannot_agree_with_itself(client):
    org = generate_keypair()
    _recognise(client, ORG, org.public_key_b64)
    resp = _evaluate(client, _self_agreement(org))
    assert resp.status_code == 422
    assert _error(resp)["details"] == {"reason": "same_party", "party": ORG}


def test_one_key_cannot_sign_for_both_parties(client):
    agreement, org, _ = _foreign_agreement()
    _recognise(client, ORG, org.public_key_b64)
    _recognise(client, BANK, org.public_key_b64)
    resp = _evaluate(client, agreement)
    assert resp.status_code == 422
    assert _error(resp)["details"] == {"reason": "overlapping_party_keys"}


def test_the_na_key_never_vouches_for_another_sovereign(client):
    agreement, org, _ = _foreign_agreement()
    _recognise(client, ORG, org.public_key_b64)
    _recognise(client, BANK, client.service.signer.public_key_b64)
    resp = _evaluate(client, agreement)
    assert resp.status_code == 422
    assert _error(resp)["details"] == {"reason": "unknown_party", "party": BANK}


def test_a_treaty_that_grants_no_role_vouches_for_nothing(client):
    agreement, org, bank = _foreign_agreement()
    _recognise(client, ORG, org.public_key_b64)
    resp = _post(client, "/admin/recognition-treaties", {
        "subject_sovereign_id": BANK, "subject_public_keys": [bank.public_key_b64],
        "scope": {"allowed_roles": []}, "validity_hours": 24,
    })
    assert resp.status_code == 201, resp.get_json()
    resp = _evaluate(client, agreement)
    assert resp.status_code == 422
    assert _error(resp)["details"] == {"reason": "unknown_party", "party": BANK}


def test_a_party_key_need_not_be_first_in_its_treaty(client):
    agreement, org, bank = _foreign_agreement()
    _recognise(client, ORG, org.public_key_b64)
    resp = _post(client, "/admin/recognition-treaties", {
        "subject_sovereign_id": BANK,
        "subject_public_keys": [generate_keypair().public_key_b64, bank.public_key_b64],
        "scope": {"allowed_roles": ["role:client"]}, "validity_hours": 24,
    })
    assert resp.status_code == 201, resp.get_json()
    assert _evaluate(client, agreement).status_code == 201


# --- bound parties ------------------------------------------------------------


@pytest.mark.parametrize("field, value", [("requester_sovereign_id", ORG), ("provider_sovereign_id", BANK),
                                          ("requester_sovereign_id", "not-a-party")])
def test_context_cannot_name_another_party(client, field, value):
    agreement, org, bank = _foreign_agreement()
    _recognise(client, ORG, org.public_key_b64)
    _recognise(client, BANK, bank.public_key_b64)
    resp = _evaluate(client, agreement, **{field: value})
    assert resp.status_code == 400 and _error(resp)["code"] == "context_party_mismatch"


def test_an_agreement_is_checked_as_received(client):
    """v1.2.0: a field added after signing, dropped by the model, still breaks the signatures."""
    agreement, org, bank = _foreign_agreement()
    _recognise(client, ORG, org.public_key_b64)
    _recognise(client, BANK, bank.public_key_b64)
    changed = copy.deepcopy(agreement)
    changed["agreed_terms"]["future_field"] = "x"
    for route, body in [
        ("/admin/boundary/evaluate", {"agreement": changed, "requested_capability": "transactions.read"}),
        ("/admin/boundary/decide", {"agreement": changed, "requested_capability": "transactions.read"}),
        ("/admin/disclosure/commit", {"agreement": changed, "capabilities": ["transactions.read"]}),
    ]:
        resp = _post(client, route, body)
        assert resp.status_code == 422, (route, resp.get_json())
        assert _error(resp)["details"]["reason"] == "invalid_offerer_signature", route


def test_an_agreement_this_na_issued_is_checked_as_received(client):
    from .test_na_trust_api import _make_agreement
    agreement = _make_agreement(client, client.service)
    agreement["agreed_terms"]["future_field"] = "x"
    resp = _post(client, "/admin/boundary/evaluate", {"agreement": agreement, "requested_capability": "read"})
    assert resp.status_code == 422 and _error(resp)["details"]["reason"] == "invalid_offerer_signature"


def test_an_agreement_this_na_issued_itself_is_trusted(client):
    from .test_na_trust_api import _make_agreement
    agreement = _make_agreement(client, client.service)
    assert agreement["offerer_sovereign_id"] == client.service.genesis_block.network_name
    assert _post(client, "/admin/boundary/evaluate", {
        "agreement": agreement, "requested_capability": "read"}).status_code == 201


def test_the_na_signature_does_not_stand_for_a_foreign_offerer(client):
    agreement, org, bank = _foreign_agreement()
    _recognise(client, ORG, org.public_key_b64)
    _recognise(client, BANK, bank.public_key_b64)
    forged = AgreementRecord.model_validate(agreement)
    forged.signatures = [sign_model(forged, client.service.signer, "na")]
    resp = _evaluate(client, forged.model_dump(mode="json"))
    assert resp.status_code == 422 and _error(resp)["code"] == "agreement_untrusted"


def test_countering_an_offer_needs_a_privileged_key(client):
    from .test_na_trust_api import _make_offer
    offer = _make_offer(client, client.service).get_json()
    terms = offer["requested_terms"]
    body = {"offer": offer, "capabilities": ["read"], "scope": {},
            "valid_from": terms["valid_from"], "valid_until": terms["valid_until"]}
    resp = _post(client, "/admin/agreements/counter", body, standard=True)
    assert resp.status_code == 403 and _error(resp)["code"] == "insufficient_operator_tier"


def test_decide_binds_the_parties_too(client):
    agreement, org, bank = _foreign_agreement()
    _recognise(client, ORG, org.public_key_b64)
    _recognise(client, BANK, bank.public_key_b64)
    resp = _post(client, "/admin/boundary/decide", {
        "agreement": agreement, "requested_capability": "transactions.read",
        "context": {"requester_sovereign_id": ORG},
    })
    assert resp.status_code == 400 and _error(resp)["code"] == "context_party_mismatch"


def test_context_may_repeat_the_agreements_own_parties(client):
    agreement, org, bank = _foreign_agreement()
    _recognise(client, ORG, org.public_key_b64)
    _recognise(client, BANK, bank.public_key_b64)
    resp = _evaluate(client, agreement, requester_sovereign_id=BANK, provider_sovereign_id=ORG)
    assert resp.status_code == 201, resp.get_json()


def test_attestation_basis_refuses_a_foreign_provider(client):
    attestation = _issue(client, capabilities=["secret.manage"], subject="vendor-acme")
    resp = _post(client, "/admin/boundary/evaluate", {
        "attestation_id": attestation["attestation_id"], "requested_capability": "secret.manage",
        "context": {"provider_sovereign_id": "someone-else"},
    })
    assert resp.status_code == 400 and _error(resp)["code"] == "context_party_mismatch"
