"""The vouching horizon on the NA's routes, and its setting (v1.8.0).

Judged now, a record in the NA's own name signed by a key whose vouching
horizon has passed is refused as ``outlives_key`` on ``/attestations/verify``,
``/recognition-treaties/verify`` and ``/attestations/verify-with-treaty``; its
re-issued copy verifies. ``/boundary-policies/verify`` gets the held check only
(``not_held``). ``NA_SUCCESSION_VOUCHING_GRACE_SECONDS`` sets the grace (0 to
86400) and ``GET /na/key-history`` publishes it as ``vouching_grace_seconds``.

The tests shorten the hand-over to one second and set the grace to 0, so a
horizon passes within a test.
"""

from __future__ import annotations

import json
import time
from datetime import timedelta

import nacl.signing
import pytest

import genesis_mesh.models.key_succession as key_models
from genesis_mesh.crypto import sign_model
from genesis_mesh.models import RecognitionPolicy, RecognizedIssuer
from genesis_mesh.models.boundary_policy import BoundaryPolicy
from genesis_mesh.na_service.settings import load_settings

from .succession_support import Network, public_b64, wait_until
from .test_evidence_store import _client
from .test_na_boundary_policy import _intent, _post


@pytest.fixture(autouse=True)
def short_times(monkeypatch):
    """Successions take effect two seconds after they are recorded; the hand-over lasts one second."""
    monkeypatch.setattr(key_models, "SUCCESSION_MIN_LEAD", timedelta(seconds=1))
    monkeypatch.setattr(key_models, "SUCCESSION_HANDOVER", timedelta(seconds=1))


@pytest.fixture
def net(tmp_path):
    return Network(tmp_path)


def _attestation(client) -> dict:
    resp = _post(client, "/admin/attestations", {"subject_id": "alice", "roles": ["role:client"],
                                                 "validity_hours": 72})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def _treaty(client) -> dict:
    resp = _post(client, "/admin/recognition-treaties", {
        "subject_sovereign_id": "partner", "subject_public_keys": [public_b64(nacl.signing.SigningKey.generate())],
        "scope": {"allowed_roles": ["role:client"]}, "validity_hours": 72})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def _policy(net) -> dict:
    """A recognition policy trusting both NA keys, as a relying party holding the key history would."""
    return json.loads(RecognitionPolicy(local_sovereign_id="acceptor", recognized_issuers=[RecognizedIssuer(
        sovereign_id="TEST", public_keys=[public_b64(k) for k in net.na_keys], allowed_roles=["role:client"],
    )]).model_dump_json())


def _succeed_and_pass_the_horizon(net, service, client, **settings):
    """Record a succession, let it take effect and its horizon pass (grace 0), restart with the new key."""
    record, new_key = net.succession(service)
    resp = _post(client, "/admin/na/succession", {"succession": record})
    assert resp.status_code == 201, resp.get_json()
    net.adopt(new_key)
    wait_until(resp.get_json()["succession"]["effective_at"])
    service.db.close()
    restarted = net.start(**settings)
    time.sleep(1.2)  # past the hand-over: with the grace at 0, the old key's horizon
    return restarted, _client(restarted)


# ---------------------------------------------------------------------------
# The setting
# ---------------------------------------------------------------------------


def test_the_grace_setting_is_0_to_86400_seconds():
    base = {"GENESIS_FILE": "g.json"}
    assert load_settings(base).succession_vouching_grace_seconds == 86400
    assert load_settings({**base, "NA_SUCCESSION_VOUCHING_GRACE_SECONDS": "0"}).succession_vouching_grace_seconds == 0
    for bad in ("86401", "-1"):
        with pytest.raises(ValueError, match="NA_SUCCESSION_VOUCHING_GRACE_SECONDS"):
            load_settings({**base, "NA_SUCCESSION_VOUCHING_GRACE_SECONDS": bad})


def test_the_service_refuses_a_grace_above_the_default(net):
    with pytest.raises(ValueError, match="NA_SUCCESSION_VOUCHING_GRACE_SECONDS"):
        net.start(succession_vouching_grace_seconds=86401)


def test_the_key_history_publishes_the_grace(net):
    assert _client(net.start()).get("/na/key-history").get_json()["vouching_grace_seconds"] == 86400
    service = net.start(succession_vouching_grace_seconds=600)
    assert _client(service).get("/na/key-history").get_json()["vouching_grace_seconds"] == 600
    assert service.key_history.history().vouching_grace == timedelta(seconds=600)


# ---------------------------------------------------------------------------
# Attestations and treaties
# ---------------------------------------------------------------------------


def test_past_the_horizon_the_old_copy_outlives_its_key_and_the_reissued_copy_verifies(net):
    service = net.start(succession_vouching_grace_seconds=0)
    client = _client(service)
    attestation = _attestation(client)
    treaty = _treaty(client)
    restarted, client = _succeed_and_pass_the_horizon(net, service, client, succession_vouching_grace_seconds=0)
    policy = _policy(net)

    old = client.post("/attestations/verify", json={"attestation": attestation, "recognition_policy": policy})
    assert old.get_json()["accepted"] is False and old.get_json()["reason"] == "outlives_key"
    successor_id = client.get(f"/attestations/{attestation['attestation_id']}").get_json()["superseded_by"]
    successor = client.get(f"/attestations/{successor_id}").get_json()["attestation"]
    new = client.post("/attestations/verify", json={"attestation": successor, "recognition_policy": policy})
    assert new.get_json()["accepted"] is True, new.get_json()

    old_treaty = client.post("/recognition-treaties/verify", json={"treaty": treaty}).get_json()
    assert old_treaty["accepted"] is False and old_treaty["reason"] == "outlives_key"
    assert old_treaty["trust_basis"] == "this_authority"
    new_id = client.get(f"/recognition-treaties/{treaty['treaty_id']}").get_json()["superseded_by"]
    new_treaty = client.get(f"/recognition-treaties/{new_id}").get_json()["treaty"]
    assert client.post("/recognition-treaties/verify", json={"treaty": new_treaty}).get_json()["accepted"] is True

    with_treaty = client.post("/attestations/verify-with-treaty", json={
        "attestation": attestation, "treaty": treaty}).get_json()
    assert with_treaty["reason"] == "treaty_outlives_key"


def test_within_the_grace_the_old_copy_still_verifies(net):
    service = net.start()
    client = _client(service)
    attestation = _attestation(client)
    treaty = _treaty(client)
    restarted, client = _succeed_and_pass_the_horizon(net, service, client)  # default grace: 24 hours
    resp = client.post("/attestations/verify", json={"attestation": attestation, "recognition_policy": _policy(net)})
    assert resp.get_json()["accepted"] is True, resp.get_json()
    assert client.post("/recognition-treaties/verify", json={"treaty": treaty}).get_json()["accepted"] is True


def test_another_sovereigns_records_are_not_judged_by_this_key_history(net):
    from genesis_mesh.models import MembershipAttestation

    service = net.start(succession_vouching_grace_seconds=0)
    foreign = MembershipAttestation.model_validate({
        "attestation_id": "foreign-1", "issuer_sovereign_id": "OTHER", "subject_id": "bob", "roles": ["role:client"],
        "status": "active", "issued_at": "2026-01-01T00:00:00Z", "valid_from": "2026-01-01T00:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z", "issued_by": "other-na"})
    foreign.signatures.append(sign_model(foreign, nacl.signing.SigningKey.generate(), "other-na"))
    assert service.own_record_outlives_key(foreign) is False


# ---------------------------------------------------------------------------
# Boundary policies: the held check only
# ---------------------------------------------------------------------------


def test_a_boundary_policy_verifies_against_the_na_keys_only_as_held(net):
    service = net.start()
    client = _client(service)
    created = _post(client, "/admin/boundary-policies", _intent())
    assert created.status_code == 201, created.get_json()
    policy = created.get_json()
    assert client.post("/boundary-policies/verify", json={"policy": policy}).get_json()["valid"] is True

    # Signed with the NA key but never stored: not this NA's policy.
    unheld = BoundaryPolicy.model_validate(policy).model_copy(update={"policy_id": "never-published",
                                                                      "signature": None})
    unheld = unheld.model_copy(update={"signature": sign_model(unheld, net.na_keys[0], "na-1")})
    refused = client.post("/boundary-policies/verify", json={"policy": unheld.model_dump(mode="json")}).get_json()
    assert refused["valid"] is False and refused["reason"] == "not_held"
    # With the issuer's keys supplied, the route checks the signature only, as before.
    supplied = client.post("/boundary-policies/verify", json={
        "policy": unheld.model_dump(mode="json"), "issuer_public_keys": [public_b64(net.na_keys[0])]}).get_json()
    assert supplied["valid"] is True

    # Policies get no horizon: one the old key signed still verifies long after its succession.
    restarted, client = _succeed_and_pass_the_horizon(net, service, client, succession_vouching_grace_seconds=0)
    assert client.post("/boundary-policies/verify", json={"policy": policy}).get_json()["valid"] is True
