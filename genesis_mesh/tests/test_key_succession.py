"""NA key succession (v1.5.0, Stage 4).

The root key, kept offline, and the outgoing NA key sign a succession record
naming the next NA key. Records, anchors, treaties and attestations signed
before and after verify in the store, its exports and agreement trust,
against the key valid at each record's time; the outgoing key signs nothing
after the succession takes effect, and a succeeded-to key's validity is
enforced.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import nacl.signing
import pytest
from click.testing import CliRunner

from genesis_mesh.crypto import save_keypair, sign_model
from genesis_mesh.models.context import BoundaryDecision
from genesis_mesh.models.evidence_store import StoreAnchor
from genesis_mesh.models.key_succession import SUCCESSION_HANDOVER, KeySuccessionRecord
from genesis_mesh.models import key_succession as key_models
from genesis_mesh.trust.context import verify_boundary_decision
from genesis_mesh.trust.evidence_store import (
    parse_export_lines,
    sign_store_anchor,
    verify_evidence_events,
    verify_store_anchors,
)
from genesis_mesh.trust.key_succession import sign_succession, verify_key_history

from .succession_support import Network, public_b64, wait_until
from .test_attestation_boundary import _issue
from .test_evidence_store import VENDOR, Controller, _client, _code, _decide, _submit
from .test_na_boundary_policy import _get, _post
from .test_na_trust_api import _make_agreement


@pytest.fixture(autouse=True)
def short_lead(monkeypatch):
    """Successions in these tests take effect two seconds after they are recorded."""
    monkeypatch.setattr(key_models, "SUCCESSION_MIN_LEAD", timedelta(seconds=1))


@pytest.fixture
def net(tmp_path):
    return Network(tmp_path)


def _succeed(client, record: dict):
    return _post(client, "/admin/na/succession", {"succession": record})


def _export(client):
    lines = _get(client, "/admin/evidence/export").get_data(as_text=True).splitlines()
    return parse_export_lines(lines)


def _succeeded(net, service, client, **kwargs):
    """Record a succession two seconds ahead, wait for it, start the NA with the new key."""
    record, new_key = net.succession(service, **kwargs)
    resp = _succeed(client, record)
    assert resp.status_code == 201, resp.get_json()
    net.adopt(new_key)
    wait_until(resp.get_json()["succession"]["effective_at"])
    service.db.close()
    restarted = net.start(evidence_out_of_band=service.evidence_out_of_band)
    return resp.get_json()["succession"], restarted, _client(restarted)


# ---------------------------------------------------------------------------
# The key history
# ---------------------------------------------------------------------------


def test_the_genesis_key_is_the_first_entry_of_the_key_history(net):
    service = net.start()
    view = _client(service).get("/na/key-history").get_json()
    assert view["successions"] == [] and view["root_public_key"] == public_b64(net.root)
    [key] = view["keys"]
    assert key["key_sequence"] == 1 and key["public_key"] == public_b64(net.na_keys[0])
    # Deployments before 1.5.0 carry a 90-day valid_to on the genesis key: it is shown, not enforced.
    assert key["valid_to_enforced"] is False and key["current"] is True
    assert service.db.na_key_history_rows()[0]["succession_json"] is None


def test_records_signed_before_and_after_a_succession_verify_in_the_store_and_exports(net):
    """Success criterion 1: the store and its exports, decisions, executions and anchors."""
    service = net.start()
    client = _client(service)
    controller = Controller(client)
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201
    assert _post(client, "/admin/evidence/anchors", {}).status_code == 201

    succession, restarted, client = _succeeded(net, service, client)
    assert succession["key_sequence"] == 2 and len(succession["signatures"]) == 3
    second = controller.record(_decide(client), action="rotate", prior_resource=first)
    assert _submit(client, second).status_code == 201
    assert _post(client, "/admin/evidence/anchors", {}).status_code == 201

    verified = _get(client, "/admin/evidence/verify").get_json()
    assert verified["verified"] is True, verified
    events = _export(client)
    kinds = [e.entry.entry_kind for e in events]
    assert "key_succession" in kinds
    history = net.history(restarted)
    keys = restarted.evidence_store_service.executor_keys()
    offline = verify_evidence_events(events, na_public_keys=history, executor_keys=keys)
    assert offline.verified, offline.to_dict()
    assert offline.key_successions == 1
    anchors = restarted.db.list_store_anchors(limit=100)
    assert {a.issued_by for a in anchors} == {"na-1", "na-2"}
    assert verify_store_anchors(anchors, na_public_keys=history, sovereign_id="TEST").verified
    # The genesis key alone verifies only what it signed.
    old_only = verify_evidence_events(events, na_public_keys=[public_b64(net.na_keys[0])], executor_keys=keys)
    assert {f["reason"] for f in old_only.failures} >= {"invalid_signature"}


def test_a_key_signs_only_inside_its_window(net):
    """A record dated after the hand-over but signed by the outgoing key is refused by name."""
    service = net.start()
    client = _client(service)
    decision = _decide(client)
    _, restarted, client = _succeeded(net, service, client)
    history = net.history(restarted)
    old = history.keys[0]
    assert old.succeeded_at is not None
    late = old.succeeded_at + SUCCESSION_HANDOVER + timedelta(seconds=1)
    anchor = sign_store_anchor(StoreAnchor(anchor_sequence=1, sovereign_id="TEST", store_sequence=1,
                                           entry_digest="0" * 64, anchored_at=late, issued_by="na-1"),
                               net.na_keys[0], "na-1")
    result = verify_store_anchors([anchor], na_public_keys=history)
    assert [f["reason"] for f in result.failures] == ["na_key_not_valid_at_time"]
    # Within the hand-over the outgoing key is still accepted.
    within = anchor.model_copy(update={"anchored_at": old.succeeded_at + timedelta(seconds=10), "signature": None})
    assert verify_store_anchors([sign_store_anchor(within, net.na_keys[0], "na-1")], na_public_keys=history).verified
    # A decision made before the succession still verifies, as of its own time.
    assert verify_boundary_decision(decision, history, at_record_time=True).accepted
    forged = decision.model_copy(update={"decision_made_at": late, "decision_valid_until": late + timedelta(hours=1),
                                         "signature": None})
    forged = forged.model_copy(update={"signature": sign_model(forged, net.na_keys[0], "na-1")})
    assert verify_boundary_decision(forged, history, at_record_time=True).reason == "na_key_not_valid_at_time"


def test_the_outgoing_key_signs_nothing_after_the_succession_takes_effect(net):
    service = net.start()
    client = _client(service)
    record, new_key = net.succession(service)
    resp = _succeed(client, record)
    assert resp.status_code == 201, resp.get_json()
    # Until it takes effect the outgoing key keeps signing.
    assert _decide(client).authorized
    wait_until(resp.get_json()["succession"]["effective_at"])
    refused = _post(client, "/admin/evidence/anchors", {})
    assert refused.status_code == 503 and _code(refused) == "na_key_succeeded"
    # The NA refuses to start with the succeeded key, and starts with the new one.
    service.db.close()
    with pytest.raises(ValueError, match="succeeded"):
        net.start(net.na_keys[0])
    net.adopt(new_key)
    restarted = net.start()
    assert _post(_client(restarted), "/admin/evidence/anchors", {}).status_code in (200, 201)


def test_the_new_key_starts_early_but_signs_nothing_and_is_not_ready_before_it_takes_effect(net):
    """Review fix 16: an instance may start with the new key ahead of the succession."""
    service = net.start()
    record, new_key = net.succession(service, effective_in=3600)
    assert _succeed(_client(service), record).status_code == 201
    service.db.close()
    with pytest.raises(ValueError, match="does not match"):
        net.start(nacl.signing.SigningKey.generate())
    net.adopt(new_key)
    pending = net.start(new_key)
    client = _client(pending)
    refused = _post(client, "/admin/boundary/evaluate", {
        "attestation_id": "att-x", "requested_capability": "secret.manage", "context": {}})
    assert pending.key_history.signing_state()["state"] == "pending"
    with pytest.raises(Exception) as signing:
        pending.signer.sign(b"x")
    assert getattr(signing.value, "code", None) == "na_key_not_yet_effective"
    assert refused.status_code != 201
    ready = client.get("/readyz")
    assert ready.status_code == 503
    assert ready.get_json()["error"]["details"]["na_key"]["state"] == "pending"
    assert pending.key_history.signing_state()["signs_from"] == record["effective_at"].replace("Z", "+00:00") \
        or pending.key_history.signing_state()["signs_from"].startswith(record["effective_at"][:19])
    # The outgoing key's instance is ready until the succession takes effect.
    pending.db.close()
    outgoing = net.start(net.na_keys[0])
    assert _client(outgoing).get("/readyz").status_code == 200


def test_a_succeeded_to_keys_validity_is_enforced_but_the_genesis_keys_is_not(tmp_path):
    # The genesis key's valid_to passed long ago (a deployment created before 1.5.0): it still signs.
    net = Network(tmp_path, na_valid_to=datetime.now(timezone.utc) - timedelta(days=30))
    service = net.start()
    client = _client(service)
    assert _decide(client).authorized
    _, restarted, client = _succeeded(net, service, client, valid_days=4 / 86400)
    assert _post(client, "/admin/evidence/anchors", {}).status_code in (200, 201)
    key = net.history(restarted).keys[-1]
    assert key.valid_to_enforced
    wait_until(key.valid_to)
    expired = _post(client, "/admin/attestations", {"subject_id": VENDOR, "roles": ["role:client"], "claims": {}})
    assert expired.status_code == 503 and _code(expired) == "na_key_expired"


def test_treaties_and_attestations_signed_before_a_succession_still_vouch(net):
    """Agreement trust: a treaty and an NA-issued attestation signed by the outgoing key."""
    service = net.start()
    client = _client(service)
    agreement = _make_agreement(client, service)
    attestation_id = _issue(client, capabilities=["secret.manage"], subject=VENDOR)["attestation_id"]
    _, restarted, client = _succeeded(net, service, client)
    decided = _post(client, "/admin/boundary/evaluate", {
        "agreement": agreement, "requested_capability": "read", "context": {}})
    assert decided.status_code == 201, decided.get_json()
    assert _decide(client, attestation_id=attestation_id).authorized
    decision = BoundaryDecision.model_validate(decided.get_json()["decision"])
    assert decision.signature is not None and decision.signature.key_id == "na-2"
    # The NA's own verify route reads the key history at each decision's time.
    verified = client.post("/boundary/verify", json={"decision": decided.get_json()["decision"]})
    assert verified.get_json()["accepted"] is True


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_succession_must_continue_the_history_and_be_signed_by_the_root_key(net):
    service = net.start()
    client = _client(service)
    record, _ = net.succession(service, sign_with=nacl.signing.SigningKey.generate())
    bad_root = _succeed(client, record)
    assert bad_root.status_code == 422 and _code(bad_root) == "succession_invalid_root_signature"
    record, _ = net.succession(service, key_sequence=3)
    assert _code(_succeed(client, record)) == "succession_chain_break"
    record, _ = net.succession(service, new_key=net.na_keys[0])
    assert _code(_succeed(client, record)) == "succession_key_reused"
    # Review fix 9: the root key is never an NA key.
    record, _ = net.succession(service, new_key=net.root)
    assert _code(_succeed(client, record)) == "succession_key_reused"
    # Review fix 8: the new key proves it is held.
    record, _ = net.succession(service, prove=False)
    unproved = _succeed(client, record)
    assert unproved.status_code == 422 and _code(unproved) == "succession_invalid_new_key_signature"
    # Review fix 10: a succession issued after it takes effect is refused.
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    record, _ = net.succession(service, issued_at=later)
    assert _code(_succeed(client, record)) == "succession_backdated"
    record, _ = net.succession(service, sovereign_id="OTHER")
    assert _code(_succeed(client, record)) == "succession_sovereign_mismatch"
    record, _ = net.succession(service, effective_in=0.2)
    assert _code(_succeed(client, record)) == "succession_times_invalid"
    record, _ = net.succession(service)
    assert _code(_post(client, "/admin/na/succession", {"succession": {**record, "x": 1}})) == "invalid_succession"
    standard = _post(client, "/admin/na/succession", {"succession": record}, standard=True)
    assert standard.status_code == 403 and _code(standard) == "insufficient_operator_tier"
    assert _succeed(client, record).status_code == 201
    # A second succession while the first is pending is refused.
    again, _ = net.succession(service)
    assert _code(_succeed(client, again)) == "succession_pending"
    assert service.db.na_key_history_length() == 2


def test_the_key_history_verifier_names_each_refusal(net):
    service = net.start()
    view = service.key_history.public_view()
    root = public_b64(net.root)
    assert verify_key_history(view["genesis"], [], root).verified
    other = public_b64(nacl.signing.SigningKey.generate())
    assert verify_key_history(view["genesis"], [], other).failures[0]["reason"] == "genesis_root_mismatch"
    tampered = {**view["genesis"], "network_version": "v9"}
    assert verify_key_history(tampered, [], root).failures[0]["reason"] == "genesis_invalid_signature"

    record, new_key = net.succession(service)
    unsigned = KeySuccessionRecord.model_validate(record)
    both = sign_succession(unsigned, net.na_keys[0], "na-1").to_wire()
    assert verify_key_history(view["genesis"], [both], root).verified
    body = {k: v for k, v in both.items() if k != "signatures"}
    cases = {
        "succession_invalid_previous_signature": record,
        "succession_invalid_root_signature": sign_succession(sign_succession(
            unsigned.model_copy(update={"signatures": []}), new_key, "na-2"), net.na_keys[0], "na-1").to_wire(),
        "succession_invalid_new_key_signature": _resigned(net, unsigned, prove_with=None),
        "succession_not_increasing": _resigned(net, unsigned, new_key, new_valid_to=unsigned.effective_at),
        "succession_chain_break": _resigned(net, unsigned, new_key, previous_public_key=public_b64(net.root)),
        # Review fix 9: the root key as the next NA key.
        "succession_key_reused": _resigned(net, unsigned, net.root, new_public_key=root),
        # Review fix 10: issued after it takes effect.
        "succession_backdated": _resigned(net, unsigned, new_key,
                                          issued_at=unsigned.effective_at + timedelta(seconds=1)),
        "invalid_signature": {**both, "x": 1},
        "unknown_field": _signed_raw(net, {**body, "x": 1}),
        # Review fix 17: a record that does not parse is payload_invalid, whatever else is wrong.
        "payload_invalid": _signed_raw(net, {**body, "key_sequence": 1, "x": 1}),
    }
    for reason, raw in cases.items():
        result = verify_key_history(view["genesis"], [raw], root)
        assert [f["reason"] for f in result.failures] == [reason], reason


def _signed_raw(net, body: dict) -> dict:
    """A record signed as received, with whatever fields it has (a newer signer's)."""
    from genesis_mesh.crypto import sign_data

    data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return {**body, "signatures": [{"key_id": "root", "sig": sign_data(data, net.root)},
                                   {"key_id": "na-1", "sig": sign_data(data, net.na_keys[0])}]}


def _resigned(net, record: KeySuccessionRecord, prove_with=None, **changes) -> dict:
    """The record changed and signed again: by the root key, the new key (``prove_with``) and the outgoing key."""
    changed = record.model_copy(update={**changes, "signatures": []})
    signed = sign_succession(changed, net.root, "root")
    if prove_with is not None:
        signed = sign_succession(signed, prove_with, changed.new_key_id)
    return sign_succession(signed, net.na_keys[0], "na-1").to_wire()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_the_cli_signs_offline_and_submits_a_succession(net, tmp_path, monkeypatch):
    from genesis_mesh.cli import key_ops, support
    from genesis_mesh.cli.main import cli

    from .test_evidence_anchors import _FlaskSession

    service = net.start()
    client = _client(service)
    monkeypatch.setattr(key_ops.requests, "Session", lambda: _FlaskSession(client))
    monkeypatch.setattr(support.requests, "Session", lambda: _FlaskSession(client))
    root_key = tmp_path / "root.key"
    root_key.write_text(__import__("base64").b64encode(bytes(net.root)).decode() + "\n", encoding="utf-8")
    new_key = nacl.signing.SigningKey.generate()
    operator, _ = save_keypair(net.privileged, str(tmp_path / "op"))
    runner = CliRunner()
    history = runner.invoke(cli, ["na", "succession", "history", "--na", "http://na.test",
                                  "--out", str(tmp_path / "history.json")])
    assert history.exit_code == 0, history.output
    signed = runner.invoke(cli, ["na", "succession", "sign", "--history", str(tmp_path / "history.json"),
                                 "--root-key", str(root_key), "--new-public-key", public_b64(new_key),
                                 "--new-key-id", "na-2", "--effective-in", "120", "--valid-days", "30",
                                 "--out", str(tmp_path / "succession.json")])
    assert signed.exit_code == 0, signed.output
    # The wrong root key is refused before anything is signed.
    wrong = tmp_path / "wrong.key"
    wrong.write_text(__import__("base64").b64encode(bytes(nacl.signing.SigningKey.generate())).decode(),
                     encoding="utf-8")
    refused = runner.invoke(cli, ["na", "succession", "sign", "--history", str(tmp_path / "history.json"),
                                  "--root-key", str(wrong), "--new-public-key", public_b64(new_key),
                                  "--new-key-id", "na-2", "--effective-in", "120", "--out", str(tmp_path / "x.json")])
    assert refused.exit_code != 0 and "genesis_root_mismatch" in refused.output
    # Review fix 9: the root key is refused as the next NA key before anything is signed.
    as_root = runner.invoke(cli, ["na", "succession", "sign", "--history", str(tmp_path / "history.json"),
                                  "--root-key", str(root_key), "--new-public-key", public_b64(net.root),
                                  "--new-key-id", "na-2", "--effective-in", "120", "--out", str(tmp_path / "y.json")])
    assert as_root.exit_code != 0 and "root key" in as_root.output
    # Review fix 8: without the new key's proof of possession the NA refuses it.
    unproved = runner.invoke(cli, ["na", "succession", "submit", "--na", "http://na.test",
                                   "--file", str(tmp_path / "succession.json"), "--operator-key", str(operator),
                                   "--operator-key-id", "operator-test", "--out", str(tmp_path / "z.json")])
    assert unproved.exit_code != 0 and "succession_invalid_new_key_signature" in unproved.output
    new_key_file = tmp_path / "new.key"
    new_key_file.write_text(__import__("base64").b64encode(bytes(new_key)).decode() + "\n", encoding="utf-8")
    wrong_prover = runner.invoke(cli, ["na", "succession", "prove", "--file", str(tmp_path / "succession.json"),
                                       "--new-key", str(wrong), "--out", str(tmp_path / "w.json")])
    assert wrong_prover.exit_code != 0 and "not the new key" in wrong_prover.output
    proved = runner.invoke(cli, ["na", "succession", "prove", "--file", str(tmp_path / "succession.json"),
                                 "--new-key", str(new_key_file), "--out", str(tmp_path / "succession.json")])
    assert proved.exit_code == 0, proved.output
    submitted = runner.invoke(cli, ["na", "succession", "submit", "--na", "http://na.test",
                                    "--file", str(tmp_path / "succession.json"), "--operator-key", str(operator),
                                    "--operator-key-id", "operator-test", "--out", str(tmp_path / "signed.json")])
    assert submitted.exit_code == 0, submitted.output
    signed_record = json.loads((tmp_path / "signed.json").read_text(encoding="utf-8"))
    assert len(signed_record["signatures"]) == 3
    view = client.get("/na/key-history").get_json()
    assert [k["key_sequence"] for k in view["keys"]] == [1, 2]


def test_a_pack_across_a_succession_verifies_from_the_root_key(net):
    """Success criterion 1, packs: records and anchors signed by both keys, one pack."""
    from genesis_mesh.models.audit_pack import MANIFEST_FILE, AuditPackManifest
    from genesis_mesh.workflows.audit_pack import verify_audit_pack

    service = net.start(evidence_out_of_band="on")
    client = _client(service)
    controller = Controller(client)
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201
    assert _post(client, "/admin/evidence/anchors", {}).status_code in (200, 201)
    _, restarted, client = _succeeded(net, service, client)
    second = controller.record(_decide(client), action="rotate", prior_resource=first)
    assert _submit(client, second).status_code == 201
    assert _post(client, "/admin/evidence/anchors", {}).status_code == 201
    resp = _post(client, "/admin/evidence/audit-pack", {})
    assert resp.status_code == 200, resp.get_json()
    files = {path: text.encode() for path, text in resp.get_json()["files"].items()}
    files[MANIFEST_FILE] = AuditPackManifest.model_validate(resp.get_json()["manifest"]).file_bytes()
    held = restarted.db.list_store_anchors(limit=100)
    result = verify_audit_pack(files, root_public_key=public_b64(net.root), held_anchors=held)
    assert result.verified, result.failures
    assert result.counts["key_successions"] == 1 and len(result.keys) == 2
    # Keys inside the pack prove nothing alone: the genesis key as the "root" refuses the history.
    other = verify_audit_pack(files, root_public_key=public_b64(net.na_keys[0]), held_anchors=held)
    assert [f["reason"] for f in other.failures] == ["genesis_root_mismatch"]


def test_verify_db_places_each_key_of_the_history_in_time(net):
    """na verify-db (after a restore or a migration) checks records signed by every key of the history."""
    from genesis_mesh.workflows.db_migration import verify_database

    service = net.start()
    client = _client(service)
    controller = Controller(client)
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201
    _, restarted, client = _succeeded(net, service, client)
    assert _submit(client, controller.record(_decide(client), action="rotate", prior_resource=first)).status_code == 201
    assert _post(client, "/admin/evidence/anchors", {}).status_code in (200, 201)
    genesis = net.genesis.model_dump(mode="json")
    report = verify_database(restarted.db, genesis=genesis)
    assert report.ok, report.to_dict()
    assert report.checks["key_history"]["verified_from_root"] is True
    # Review fix 6: without the genesis block the database's rows prove nothing: the genesis key only.
    alone = verify_database(restarted.db, public_b64(net.na_keys[0]))
    assert not alone.ok and "give the genesis block" in alone.checks["key_history"]["note"]


def test_verify_db_refuses_a_key_history_row_the_root_key_did_not_sign(net):
    """Review fix 6 (skeptic P11): a database writer appends a succession of its own; verify-db checks the
    history from the genesis block's root key, never the rows alone."""
    from genesis_mesh.workflows.db_migration import verify_database

    service = net.start()
    client = _client(service)
    assert _submit(client, Controller(client).record(_decide(client))).status_code == 201
    forger = nacl.signing.SigningKey.generate()
    record, new_key = net.succession(service, sign_with=forger)
    signed = sign_succession(KeySuccessionRecord.model_validate(record), net.na_keys[0], "na-1")
    service.db.add_na_key_row({
        "key_sequence": 2, "key_id": "na-2", "public_key": public_b64(new_key),
        "effective_at": signed.effective_at.isoformat(), "valid_to": signed.new_valid_to.isoformat(),
        "valid_to_enforced": 1, "succession_digest": signed.digest(),
        "succession_json": json.dumps(signed.to_wire()), "recorded_at": datetime.now(timezone.utc).isoformat(),
    })
    report = verify_database(service.db, genesis=net.genesis.model_dump(mode="json"))
    assert not report.ok
    assert any("succession_invalid_root_signature" in f for f in report.failures), report.failures


def test_verify_export_reads_the_key_history_from_the_root_key(net, tmp_path):
    """evidence verify-export --key-history --root-key: each NA key verifies what it signed while valid."""
    from genesis_mesh.cli.main import cli

    service = net.start()
    client = _client(service)
    controller = Controller(client)
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201
    _, restarted, client = _succeeded(net, service, client)
    assert _submit(client, controller.record(_decide(client), action="rotate", prior_resource=first)).status_code == 201
    export = tmp_path / "export.jsonl"
    export.write_text(_get(client, "/admin/evidence/export").get_data(as_text=True), encoding="utf-8")
    keys = tmp_path / "keys.json"
    keys.write_text(_get(client, "/admin/evidence/executor-keys").get_data(as_text=True), encoding="utf-8")
    history = tmp_path / "history.json"
    history.write_text(json.dumps(client.get("/na/key-history").get_json()), encoding="utf-8")
    base = ["evidence", "verify-export", "--file", str(export), "--executor-keys", str(keys)]
    ok = CliRunner().invoke(cli, [*base, "--key-history", str(history), "--root-key", public_b64(net.root)])
    assert ok.exit_code == 0, ok.output
    old_only = CliRunner().invoke(cli, [*base, "--na-public-key", public_b64(net.na_keys[0])])
    assert old_only.exit_code == 1
    wrong_root = CliRunner().invoke(cli, [*base, "--key-history", str(history), "--root-key",
                                          public_b64(net.na_keys[0])])
    assert wrong_root.exit_code != 0 and "genesis_root_mismatch" in wrong_root.output
