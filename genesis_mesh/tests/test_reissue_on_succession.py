"""Re-issue at a key succession (v1.8.0): the job, its triggers, its route and command.

After a succession takes effect, the instance signing with the new key
re-issues the attestations and treaties the old key signed that are still
valid past the old key's vouching horizon, and signs the active policy
manifest again (``services/reissue.py``).
"""

from __future__ import annotations

import json
import threading
from datetime import timedelta

import pytest
from click.testing import CliRunner

import genesis_mesh.models.key_succession as key_models
from genesis_mesh.crypto import save_keypair, verify_model_signature
from genesis_mesh.models import MembershipAttestation, PolicyManifest
from genesis_mesh.na_service.services import reissue as reissue_module
from genesis_mesh.na_service.services.reissue import ReissueService, due_records

from .succession_support import Network, public_b64, wait_until
from .test_attestation_boundary import _issue
from .test_evidence_store import _client
from .test_na_boundary_policy import _post


@pytest.fixture(autouse=True)
def short_lead(monkeypatch):
    """Successions in these tests take effect two seconds after they are recorded."""
    monkeypatch.setattr(key_models, "SUCCESSION_MIN_LEAD", timedelta(seconds=1))


@pytest.fixture
def net(tmp_path):
    return Network(tmp_path)


def _treaty(client) -> dict:
    resp = _post(client, "/admin/recognition-treaties", {
        "subject_sovereign_id": "partner", "subject_public_keys": ["cGFydG5lci1rZXk="],
        "scope": {"allowed_roles": ["role:client"]}, "validity_hours": 24 * 30})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def _policy(client) -> dict:
    resp = _post(client, "/admin/policy", {"policy_id": "policy-before", "allowed_services": ["billing"]})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def _record_succession(net, service, client):
    record, new_key = net.succession(service)
    resp = _post(client, "/admin/na/succession", {"succession": record})
    assert resp.status_code == 201, resp.get_json()
    net.adopt(new_key)
    return resp.get_json()["succession"]


def _signed_by(record, key) -> bool:
    return any(verify_model_signature(record, s, public_b64(key)) for s in record.signatures)


def _events(service, event_type: str) -> list[dict]:
    return [e for e in service.db.list_audit_events() if e["event_type"] == event_type]


# ---------------------------------------------------------------------------
# The job
# ---------------------------------------------------------------------------


def test_the_new_key_reissues_what_outlives_the_old_keys_horizon(net):
    service = net.start()
    client = _client(service)
    lasting = _issue(client)  # 168 hours: past the horizon
    brief = _post(client, "/admin/attestations", {
        "subject_id": "brief", "roles": ["role:client"], "validity_hours": 1}).get_json()  # lapses in the grace
    revoked = _issue(client, subject="gone")
    _post(client, "/admin/attestations/" + revoked["attestation_id"] + "/revoke", {"reason": "left"})
    treaty = _treaty(client)
    _policy(client)
    succession = _record_succession(net, service, client)
    wait_until(succession["effective_at"])
    service.db.close()

    restarted = net.start()  # the start-up run re-issues
    db = restarted.db
    old = db.get_membership_attestation(lasting["attestation_id"])
    assert old["status"] == "active" and old["superseded_by"] is not None
    new = db.get_membership_attestation(old["superseded_by"])
    copy: MembershipAttestation = new["attestation"]
    assert new["reissued_from"] == lasting["attestation_id"] and copy.issued_by == "na-2"
    assert _signed_by(copy, net.na_keys[1]) and not _signed_by(copy, net.na_keys[0])
    # Same content otherwise: subject, roles, claims, window.
    original = old["attestation"]
    assert (copy.subject_id, copy.roles, copy.claims, copy.valid_from, copy.expires_at) == (
        original.subject_id, original.roles, original.claims, original.valid_from, original.expires_at)
    assert db.get_membership_attestation(brief["attestation_id"])["superseded_by"] is None
    assert db.get_membership_attestation(revoked["attestation_id"])["superseded_by"] is None
    old_treaty = db.get_recognition_treaty(treaty["treaty_id"])
    new_treaty = db.get_recognition_treaty(old_treaty["superseded_by"])
    assert _signed_by(new_treaty["treaty"], net.na_keys[1])
    assert new_treaty["treaty"].subject_public_keys == treaty["subject_public_keys"]

    policy = db.get_active_policy()
    assert policy.policy_id == "policy-before" and policy.issued_by == "na-2"
    assert _signed_by(policy, net.na_keys[1])

    [event] = _events(restarted, "na_records_reissued")
    assert event["details"]["attestations"] == 1 and event["details"]["treaties"] == 1
    assert event["details"]["policy_manifest"] == "policy-before"
    assert event["details"]["previous_key_ids"] == ["na-1"] and event["details"]["key_id"] == "na-2"
    ready, checks = restarted.readiness()
    assert ready and checks["reissue"] == {
        "reissue_pending": False, "due": {"attestations": 0, "treaties": 0, "policy_manifest": False}}
    # Nothing is due twice.
    assert restarted.reissue_service.run()["reissued"] == {"attestations": 0, "treaties": 0, "policy_manifest": None}


def test_decisions_keep_the_id_they_were_given(net):
    """The previous copy stays active, so a decision on its ID still allows (it is not resolved)."""
    from .test_evidence_store import _decide

    service = net.start()
    client = _client(service)
    attestation_id = _issue(client, capabilities=["secret.manage"], subject="vendor-acme")["attestation_id"]
    wait_until(_record_succession(net, service, client)["effective_at"])
    service.db.close()
    restarted = net.start()
    client = _client(restarted)
    assert restarted.db.get_membership_attestation(attestation_id)["superseded_by"] is not None
    decision = _decide(client, attestation_id=attestation_id)
    assert decision.authorized and decision.attestation_binding.attestation_id == attestation_id


def test_only_an_instance_whose_key_signs_reissues(net):
    service = net.start()
    client = _client(service)
    attestation_id = _issue(client)["attestation_id"]
    succession = _record_succession(net, service, client)
    # The new key started early is pending: it signs nothing, so it re-issues nothing.
    early = net.start()
    assert early.key_history.signing_state()["state"] == "pending"
    assert early.reissue_service.due().pending is False
    early.reissue_service.maybe_reissue()
    assert early.db.get_membership_attestation(attestation_id)["superseded_by"] is None
    wait_until(succession["effective_at"])
    # The old key's instance is stopped: it may not sign, so the route refuses (503).
    resp = _post(client, "/admin/na/reissue", {})
    assert resp.status_code == 503 and resp.get_json()["error"]["code"] == "na_key_succeeded"
    assert service.db.get_membership_attestation(attestation_id)["superseded_by"] is None
    # The early instance now signs: the next trigger re-issues.
    early.reissue_service._next_run = 0.0
    early.readiness()
    assert early.db.get_membership_attestation(attestation_id)["superseded_by"] is not None


def test_a_run_reissues_in_batches_and_the_next_trigger_continues(net, monkeypatch):
    monkeypatch.setattr(reissue_module, "REISSUE_BATCH", 2)
    service = net.start()
    client = _client(service)
    ids = [_issue(client, subject=f"member-{n}")["attestation_id"] for n in range(5)]
    wait_until(_record_succession(net, service, client)["effective_at"])
    service.db.close()

    restarted = net.start()
    superseded = lambda: sum(  # noqa: E731
        restarted.db.get_membership_attestation(i)["superseded_by"] is not None for i in ids)
    assert superseded() == 2
    _, checks = restarted.readiness()
    assert superseded() == 4 and checks["reissue"]["reissue_pending"] is True
    assert checks["reissue"]["due"]["attestations"] == 1
    _, checks = restarted.readiness()
    assert superseded() == 5 and checks["reissue"]["reissue_pending"] is False


def test_the_route_and_command_reissue_at_once(net, tmp_path, monkeypatch):
    from genesis_mesh.cli import key_ops, support
    from genesis_mesh.cli.main import cli

    from .test_evidence_anchors import _FlaskSession

    service = net.start()
    client = _client(service)
    ids = [_issue(client, subject=f"member-{n}")["attestation_id"] for n in range(3)]
    wait_until(_record_succession(net, service, client)["effective_at"])
    service.db.close()
    monkeypatch.setattr(ReissueService, "maybe_reissue", lambda self: None)  # no start-up or lazy run
    restarted = net.start()
    client = _client(restarted)
    assert restarted.reissue_service.due().summary()["due"]["attestations"] == 3

    monkeypatch.setattr(key_ops.requests, "Session", lambda: _FlaskSession(client))
    monkeypatch.setattr(support.requests, "Session", lambda: _FlaskSession(client))
    operator, _ = save_keypair(net.privileged, str(tmp_path / "op"))
    result = CliRunner().invoke(cli, ["na", "reissue", "--na", "http://na.test", "--operator-key", str(operator),
                                      "--operator-key-id", "operator-test"])
    assert result.exit_code == 0, result.output
    assert "Re-issued 3 attestations and 0 treaties" in result.output and "Nothing left" in result.output
    assert all(restarted.db.get_membership_attestation(i)["superseded_by"] for i in ids)
    again = _post(client, "/admin/na/reissue", {})
    assert again.status_code == 200 and again.get_json()["reissued"]["attestations"] == 0
    assert _post(client, "/admin/na/reissue", {}, standard=True).status_code == 403


def test_the_policy_manifest_is_signed_again_when_served_or_rolled_back(net, monkeypatch):
    service = net.start()
    client = _client(service)
    _policy(client)
    second = _post(client, "/admin/policy", {"policy_id": "policy-later"})
    assert second.status_code == 201
    wait_until(_record_succession(net, service, client)["effective_at"])
    service.db.close()
    monkeypatch.setattr(ReissueService, "maybe_reissue", lambda self: None)
    restarted = net.start()
    client = _client(restarted)

    served = PolicyManifest.model_validate(client.get("/policy").get_json())
    assert served.policy_id == "policy-later" and _signed_by(served, net.na_keys[1])
    # Rolling back to a version the old key signed serves it signed by the new key.
    rolled = _post(client, "/admin/policy/rollback", {"policy_id": "policy-before"})
    assert rolled.status_code == 200, rolled.get_json()
    manifest = PolicyManifest.model_validate(rolled.get_json())
    assert manifest.policy_id == "policy-before" and _signed_by(manifest, net.na_keys[1])
    assert _signed_by(PolicyManifest.model_validate(client.get("/policy").get_json()), net.na_keys[1])


# ---------------------------------------------------------------------------
# Two instances, and a revocation racing the job (SQLite and PostgreSQL)
# ---------------------------------------------------------------------------


def test_two_instances_reissue_each_record_once_and_a_racing_revocation_wins(net, monkeypatch):
    service = net.start()
    client = _client(service)
    ids = [_issue(client, subject=f"member-{n}")["attestation_id"] for n in range(6)]
    wait_until(_record_succession(net, service, client)["effective_at"])
    service.db.close()
    monkeypatch.setattr(ReissueService, "maybe_reissue", lambda self: None)
    first, second = net.start(), net.start()

    start = threading.Barrier(3)
    results: list[dict] = []

    def job(instance) -> None:
        start.wait()
        results.append(instance.reissue_service.run(all_due=True))

    def revoke() -> None:
        start.wait()
        second.revoke_attestation_lineage(ids[3], "left")

    threads = [threading.Thread(target=job, args=(first,)), threading.Thread(target=job, args=(second,)),
               threading.Thread(target=revoke)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not any(t.is_alive() for t in threads)

    db = first.db
    for attestation_id in ids:
        lineage = db.membership_attestation_lineage(attestation_id)
        assert len(lineage) <= 2  # one copy at most, whichever instance made it
        if attestation_id == ids[3]:
            # The revocation reaches every copy, whichever came first.
            assert {db.get_membership_attestation(i)["status"] for i in lineage} == {"revoked"}
        else:
            assert len(lineage) == 2
            assert db.get_membership_attestation(lineage[1])["status"] == "active"
    total = sum(r["reissued"]["attestations"] for r in results)
    assert total == len([i for i in ids if len(db.membership_attestation_lineage(i)) == 2])
    assert first.reissue_service.due().pending is False


# ---------------------------------------------------------------------------
# What is due (also read by `genesis-mesh na doctor`)
# ---------------------------------------------------------------------------


def test_nothing_is_due_without_a_succession(net):
    service = net.start()
    client = _client(service)
    _issue(client)
    history = service.key_history.history()
    signing = history.key_for(public_b64(net.na_keys[0]))
    from datetime import datetime, timezone

    assert due_records(service.db, history, "TEST", signing, datetime.now(timezone.utc)).pending is False
    assert service.readiness()[1]["reissue"]["reissue_pending"] is False


def test_due_records_names_each_record_and_the_key_that_signed_it(net, monkeypatch):
    from datetime import datetime, timezone

    service = net.start()
    client = _client(service)
    attestation_id = _issue(client)["attestation_id"]
    treaty_id = _treaty(client)["treaty_id"]
    wait_until(_record_succession(net, service, client)["effective_at"])
    service.db.close()
    monkeypatch.setattr(ReissueService, "maybe_reissue", lambda self: None)
    restarted = net.start()
    history = restarted.key_history.history()
    signing = history.key_for(public_b64(net.na_keys[1]))
    due = due_records(restarted.db, history, "TEST", signing, datetime.now(timezone.utc))
    assert [(a.attestation_id, k.key_id) for a, k in due.attestations] == [(attestation_id, "na-1")]
    assert [(t.treaty_id, k.key_id) for t, k in due.treaties] == [(treaty_id, "na-1")]
    # With the grace at zero the horizon is the hand-over: still due, the records outlive it.
    short = history.with_vouching_grace(0)
    assert due_records(restarted.db, short, "TEST", signing, datetime.now(timezone.utc)).pending
    # Records the given key signed itself are never due.
    old = history.key_for(public_b64(net.na_keys[0]))
    assert due_records(restarted.db, history, "TEST", old, datetime.now(timezone.utc)).pending is False
    assert json.loads(json.dumps(restarted.reissue_service.due().summary())) == {
        "reissue_pending": True, "due": {"attestations": 1, "treaties": 1, "policy_manifest": False}}


def test_once_reissued_the_check_reads_no_signed_record(net, monkeypatch):
    """Re-issued copies were issued after the new key took effect: the periodic check skips them unread."""
    service = net.start()
    client = _client(service)
    for n in range(3):
        _issue(client, subject=f"member-{n}")
    _treaty(client)
    wait_until(_record_succession(net, service, client)["effective_at"])
    service.db.close()
    restarted = net.start()
    assert restarted.reissue_service.summary()["reissue_pending"] is False
    reads: list[str] = []
    for name in ("get_membership_attestation", "get_recognition_treaty"):
        real = getattr(restarted.db, name)
        monkeypatch.setattr(restarted.db, name, lambda record_id, real=real: reads.append(record_id) or real(record_id))
    assert restarted.reissue_service.due().pending is False
    assert reads == []
