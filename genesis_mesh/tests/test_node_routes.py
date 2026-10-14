"""The node-scoped routes an edge agent calls (v1.7.0, Stage 6).

``/node/boundary/evaluate``, ``/node/state`` and ``/node/evidence/resource-head``
take requests the node key signs, bound to a purpose and this NA. A node
evaluates only under an attestation issued to it, as its own sovereign ID; a
refused request signs and stores no decision.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from genesis_mesh.crypto import sign_model
from genesis_mesh.crypto.node_auth import (
    executor_key_id,
    executor_proof_payload,
    node_signing_payload,
    sign_node_request,
)
from genesis_mesh.models.sovereign import MembershipAttestation
from genesis_mesh.na_service.rate_limit import RateLimits

from .edge_support import PREFIX, SOVEREIGN, EdgeAgent, frozen_window, invite_token, stale
from .test_edge_nodes import _attest, _details, _events, _grant
from .test_evidence_store import _client, _code
from .test_grants import CAPABILITY, _granting_service, _make_service, clock  # noqa: F401  (clock is a fixture)
from .test_na_boundary_policy import _get, _post


@pytest.fixture
def na_service(clock):
    return _granting_service()


@pytest.fixture
def client(na_service):
    return _client(na_service)


@pytest.fixture
def agent(client) -> EdgeAgent:
    return EdgeAgent(client).enrolled(invite_token(client))


def _decisions(service) -> int:
    return len(_events(service, "decision_stored"))


# -- node request signatures --------------------------------------------------------------


def test_node_signing_payload_is_the_canonical_body_without_its_signature():
    body = {"b": 1, "a": "Zürich", "ratio": 0.1, "eps": 1e-07, "signature": "x", "nested": {"z": None, "y": [1.0]}}
    legacy = json.dumps({k: v for k, v in sorted(body.items()) if k != "signature"}, sort_keys=True,
                        separators=(",", ":"))
    assert node_signing_payload(body) == legacy.encode("utf-8")
    assert b"\\u00fc" in node_signing_payload(body)
    assert executor_proof_payload({**body, "executor_signature": "y"}) == legacy.encode("utf-8")


@pytest.mark.parametrize("key", ["", "AAAA", "not base64!", None, 7])
def test_an_executor_key_id_needs_a_32_byte_key(key):
    with pytest.raises(ValueError):
        executor_key_id(key)  # type: ignore[arg-type]


def test_a_heartbeat_signed_as_the_conformance_vectors_sign_is_accepted(agent, client):
    body = sign_node_request({"cert_id": agent.cert_id, "node_public_key": agent.node_public_key, "status": "healthy",
                              "timestamp": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                              "nonce": str(uuid.uuid4())}, agent.node_key)
    assert client.post("/heartbeat", json=body).status_code == 200


# -- /node/boundary/evaluate ----------------------------------------------------------------


def test_a_node_evaluates_under_its_attestation(agent, client, na_service):
    attestation_id = _attest(client)
    resp = agent.evaluate(attestation_id, CAPABILITY)
    assert resp.status_code == 201, resp.get_json()
    decision = resp.get_json()["decision"]
    assert decision["authorized"] is True and resp.get_json()["justification_proof"]
    stored = _details(_events(na_service, "decision_stored")[-1])
    assert stored["decision_id"] == decision["decision_id"]
    assert stored["requested_by"] == f"node:{agent.executor_key_id}"
    made = _details(_events(na_service, "node_boundary_decision_made")[-1])
    assert made["requester_sovereign_id"] == SOVEREIGN and made["executor_key_id"] == agent.executor_key_id
    # The node may name itself as the requester.
    named = agent.evaluate(attestation_id, CAPABILITY, {"requester_sovereign_id": SOVEREIGN})
    assert named.status_code == 201


def test_an_attestation_bound_to_the_node_key_is_issued_to_the_node(agent, client):
    attestation_id = _attest(client, subject_public_key=agent.node_public_key)
    assert agent.evaluate(attestation_id, CAPABILITY).status_code == 201


def test_a_revoked_attestation_gives_a_signed_deny(agent, client):
    attestation_id = _attest(client)
    assert _post(client, f"/admin/attestations/{attestation_id}/revoke", {}).status_code == 200
    resp = agent.evaluate(attestation_id, CAPABILITY)
    assert resp.status_code == 201 and resp.get_json()["decision"]["authorized"] is False


def test_a_node_requests_as_its_own_sovereign_only(agent, client, na_service):
    attestation_id = _attest(client)
    before = _decisions(na_service)
    resp = agent.evaluate(attestation_id, CAPABILITY, {"requester_sovereign_id": "another-sovereign"})
    assert resp.status_code == 403 and _code(resp) == "node_requester_mismatch"
    assert _decisions(na_service) == before


def _foreign(client, na_service, agent: EdgeAgent, kind: str) -> str:
    if kind == "other_subject":
        return _attest(client, subject="site7-18")
    if kind == "other_key":
        return _attest(client, subject_public_key=EdgeAgent(client).node_public_key)
    if kind == "unknown":
        return str(uuid.uuid4())
    # Another issuer's attestation about this node's sovereign ID, imported into this NA's store.
    now = datetime.now(timezone.utc)
    other = MembershipAttestation(
        attestation_id=str(uuid.uuid4()), issuer_sovereign_id="OTHER", subject_id=SOVEREIGN,
        subject_public_key=None, roles=["role:client"], status="active", issued_at=now, valid_from=now,
        expires_at=now + timedelta(days=1), issued_by="other-key", claims={"capabilities": [CAPABILITY]},
        signatures=[],
    )
    other.signatures.append(sign_model(other, agent.executor_key, "other-key"))
    na_service.db.save_membership_attestation(other)
    return other.attestation_id


@pytest.mark.parametrize("kind", ["other_subject", "other_issuer", "other_key", "unknown"])
def test_a_foreign_attestation_is_refused_and_no_decision_is_stored(agent, client, na_service, kind):
    attestation_id = _foreign(client, na_service, agent, kind)
    before = _decisions(na_service)
    resp = agent.evaluate(attestation_id, CAPABILITY)
    assert resp.status_code == 403 and _code(resp) == "node_attestation_foreign"
    assert _decisions(na_service) == before
    refused = _details(_events(na_service, "node_request_refused")[-1])
    assert refused["reason"] == "node_attestation_foreign" and refused["attestation_id"] == attestation_id


@pytest.mark.parametrize(("fields", "code"), [
    ({"agreement": {"agreement_id": "a"}}, "node_basis_unsupported"),
    ({"attestation_id": ""}, "invalid_attestation_id"),
    ({"attestation_id": 7}, "invalid_attestation_id"),
    ({"requested_capability": ""}, "missing_boundary_fields"),
    ({"context": ["not", "an", "object"]}, "invalid_context"),
])
def test_a_malformed_evaluation_is_refused(agent, client, fields, code):
    body = {"attestation_id": _attest(client), "requested_capability": CAPABILITY,
            "context": {"request_parameters": {}}, **fields}
    resp = agent.call("/node/boundary/evaluate", **body)
    assert resp.status_code == 400 and _code(resp) == code


# -- authentication -------------------------------------------------------------------------


def test_a_replayed_request_is_refused(agent, client):
    nonce = str(uuid.uuid4())
    assert agent.call("/node/state", nonce=nonce).status_code == 200
    resp = agent.call("/node/state", nonce=nonce)
    assert resp.status_code == 401 and _code(resp) == "node_auth_failed"
    # The nonce scope is the node's, as for its heartbeats: one nonce once across every node route.
    resp = agent.call("/node/evidence/resource-head", nonce=nonce, resource_id=f"{PREFIX}kv/db")
    assert resp.status_code == 401


@pytest.mark.parametrize(("field", "reason"), [("purpose", "purpose_mismatch"), ("audience", "audience_mismatch")])
def test_a_request_signed_for_another_route_or_na_is_refused(agent, client, na_service, field, reason):
    wrong = {"purpose": "node_state", "audience": EdgeAgent(client).node_public_key}[field]
    resp = agent.call("/node/evidence/resource-head", resource_id=f"{PREFIX}kv/db", **{field: wrong})
    assert resp.status_code == 401 and _code(resp) == "node_auth_failed"
    failure = _details(_events(na_service, "node_auth_failed")[-1])
    assert failure["reason"] == reason


def test_a_stale_or_unsigned_request_is_refused(agent, client):
    resp = agent.call("/node/state", at=stale())
    assert resp.status_code == 401 and _code(resp) == "node_auth_failed"
    body = agent.signed(agent.node_body("/node/state"))
    body["signature"] = agent.signed(agent.node_body("/node/evidence/resource-head"))["signature"]
    assert _code(client.post("/node/state", json=body)) == "node_auth_failed"


def test_identity_and_certificate_refusals(agent, client, na_service):
    body = agent.signed(agent.node_body("/node/state"))
    body.pop("cert_id")
    resp = client.post("/node/state", json=body)
    assert resp.status_code == 400 and _code(resp) == "missing_certificate_identity"
    resp = agent.call("/node/state", cert_id=str(uuid.uuid4()))
    assert resp.status_code == 403 and _code(resp) == "certificate_not_found"
    other = EdgeAgent(client).enrolled(invite_token(client, "site7-18"))
    resp = agent.call("/node/state", cert_id=other.cert_id)
    assert resp.status_code == 403 and _code(resp) == "certificate_key_mismatch"
    with na_service.db.conn:
        na_service.db.conn.execute("UPDATE issued_certs SET expires_at = ? WHERE cert_id = ?",
                                   (stale().isoformat(), agent.cert_id))
    resp = agent.call("/node/state")
    assert resp.status_code == 403 and _code(resp) == "certificate_expired"


def test_a_revoked_certificate_is_refused(agent, client):
    assert _post(client, "/admin/revoke", {"cert_id": agent.cert_id}).status_code == 200
    resp = agent.call("/node/state")
    assert resp.status_code == 403 and _code(resp) == "certificate_revoked"


def test_a_plain_or_retired_node_is_refused(agent, client, na_service):
    token = _post(client, "/admin/invite", {}).get_json()["token_id"]
    plain = EdgeAgent(client)
    assert plain.join(token, executor=False).status_code == 201
    resp = plain.call("/node/state")
    assert resp.status_code == 403 and _code(resp) == "edge_node_not_enrolled"
    na_service.db.retire_edge_node(agent.node_public_key, datetime.now(timezone.utc).isoformat(), "test", "test")
    resp = agent.call("/node/state")
    assert resp.status_code == 403 and _code(resp) == "edge_node_retired"


# -- /node/state ------------------------------------------------------------------------------


def test_the_state_lists_what_was_issued_to_the_node(agent, client):
    mine = _attest(client)
    _attest(client, subject="site7-18")
    revoked = _attest(client)
    assert _post(client, f"/admin/attestations/{revoked}/revoke", {}).status_code == 200
    grant_id = _grant(client, agent)
    first = agent.cert_id
    assert agent.renew().status_code == 201
    # A request still signed with the predecessor (in its grace window) names the newest certificate.
    resp = agent.call("/node/state", cert_id=first)
    assert resp.status_code == 200, resp.get_json()
    state = resp.get_json()
    assert state["node"] == {"node_public_key": agent.node_public_key, "node_sovereign_id": SOVEREIGN,
                             "cert_id": agent.cert_id, "cert_expires_at": state["node"]["cert_expires_at"],
                             "roles": ["role:client"]}
    assert state["executor_key"]["key_id"] == agent.executor_key_id
    assert state["executor_key"]["resource_prefix"] == PREFIX
    # The grant rests on an attestation issued to the node too.
    listed = [a["attestation"]["attestation_id"] for a in state["attestations"]]
    assert mine in listed and revoked not in listed and len(listed) == 2
    assert all(a["status"] == "active" and a["attestation"]["signatures"] for a in state["attestations"])
    assert [g["grant_id"] for g in state["grants"]] == [grant_id]
    assert state["grants"][0]["bearer_key_id"] == agent.executor_key_id and state["grants"][0]["signature"]
    assert state["server_time"]


def test_the_state_has_no_grants_while_grants_are_off(client, na_service, agent):
    na_service.evidence_grants = "off"
    resp = agent.call("/node/state")
    assert resp.status_code == 200 and resp.get_json()["grants"] == []


# -- /node/evidence/resource-head --------------------------------------------------------------


def test_the_resource_head_is_scoped_to_the_node_prefix(agent, client, na_service):
    for resource in ("edge:site7-18/kv/db", "kv/db", None):
        resp = agent.call("/node/evidence/resource-head", resource_id=resource)
        assert resp.status_code == 403 and _code(resp) == "node_resource_out_of_scope"
    resp = agent.call("/node/evidence/resource-head", resource_id=f"{PREFIX}kv/db")
    assert resp.status_code == 404 and _code(resp) == "resource_not_found"
    na_service.evidence_store = "off"
    resp = agent.call("/node/evidence/resource-head", resource_id=f"{PREFIX}kv/db")
    assert resp.status_code == 404 and _code(resp) == "evidence_store_disabled"


def test_the_resource_head_matches_the_operators_view(agent, client, clock):
    from .test_grants import Holder, _issue_grant, _lifetime_policy, _submit_use

    holder = Holder(client, key_id=agent.executor_key_id, sovereign=SOVEREIGN, register=False)
    holder.key, holder.public_key = agent.executor_key, agent.executor_public_key
    _lifetime_policy(client, 90)
    resp = _issue_grant(client, holder, _attest(client))
    assert resp.status_code == 201, resp.get_json()
    holder.take(resp.get_json())
    use = holder.use(clock.advance(minutes=1), resource=f"{PREFIX}kv/db")
    assert _submit_use(client, use).status_code == 201
    resp = agent.call("/node/evidence/resource-head", resource_id=f"{PREFIX}kv/db")
    admin = _get(client, f"/admin/evidence/resource-heads/{PREFIX}kv/db")
    assert admin.status_code == 200, admin.get_json()
    assert resp.status_code == 200 and resp.get_json() == admin.get_json()
    assert resp.get_json()["entry_kind"] == "grant_execution"


# -- rate limits ---------------------------------------------------------------------------------


def test_node_routes_are_rate_limited_per_node_and_per_address(clock):
    service = frozen_window(_granting_service(rate_limits=RateLimits(node=2, node_address=4)))
    client = _client(service)
    agent = EdgeAgent(client).enrolled(invite_token(client))
    assert [agent.call("/node/state").status_code for _ in range(3)] == [200, 200, 429]
    assert _code(agent.call("/node/state")) == "rate_limit_exceeded"
    # The address limit counts before authentication: unsigned requests use it up.
    resp = client.post("/node/state", json={})
    assert resp.status_code == 429 and _code(resp) == "rate_limit_exceeded"


def test_the_node_rate_limits_are_settings():
    from genesis_mesh.na_service.settings import load_settings

    settings = load_settings({"GENESIS_FILE": "g.json", "NA_RATE_LIMIT_NODE_PER_MINUTE": "30",
                              "NA_RATE_LIMIT_NODE_ADDRESS_PER_MINUTE": "90"})
    assert settings.rate_limits.node == 30 and settings.rate_limits.node_address == 90
    defaults = load_settings({"GENESIS_FILE": "g.json"}).rate_limits
    assert (defaults.node, defaults.node_address) == (120, 600)
    with pytest.raises(ValueError):
        RateLimits(node=0)


def test_node_routes_are_inert_without_edge_nodes(clock):
    client = _client(_make_service())
    resp = client.post("/node/state", json={})
    assert resp.status_code == 400 and _code(resp) == "missing_certificate_identity"


# -- review fixes (1.7.0) --------------------------------------------------------------------


def test_a_node_whose_executor_key_is_retired_is_refused(agent, client, na_service):
    """M1: a key retired outside /admin/revoke (an earlier release, the database) ends the node's requests."""
    na_service.db.retire_executor_key(agent.executor_key_id, "op")
    resp = agent.call("/node/state")
    assert resp.status_code == 403 and _code(resp) == "edge_node_retired"


def test_a_revoked_certificate_is_audited_only_for_a_signed_request(agent, client, na_service):
    """C4: an unsigned request naming a revoked certificate writes no audit event."""
    assert _post(client, "/admin/revoke", {"cert_id": agent.cert_id}).status_code == 200
    before = len(_events(na_service, "node_request_refused"))
    forged = agent.signed(agent.node_body("/node/state"))
    forged["signature"] = EdgeAgent(client).signed(agent.node_body("/node/state"))["signature"]
    resp = client.post("/node/state", json=forged)
    assert resp.status_code == 403 and _code(resp) == "certificate_revoked"
    assert len(_events(na_service, "node_request_refused")) == before
    assert agent.call("/node/state").status_code == 403
    assert len(_events(na_service, "node_request_refused")) == before + 1
