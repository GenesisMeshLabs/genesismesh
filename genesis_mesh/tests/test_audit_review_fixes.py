"""v1.5.0 review fixes: one regression test per finding of the Stage 4 review.

Each test reproduces what a reviewer showed (a probe) and asserts the fixed
behaviour: packs after a prune, archives of packs that did not verify, cited
entries tied to what the verifier holds, decisions outliving their key, time
order in the store, mesh nodes following the key history, the new key's proof
of possession, completeness matching, backdated manifests, reports that lie,
live routes and agreements placed at their own time, and the smaller ones.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nacl.signing
import pytest
from click.testing import CliRunner

from genesis_mesh.crypto import sign_model
from genesis_mesh.models import key_succession as key_models
from genesis_mesh.models.audit_pack import (
    CITED_FILE,
    ENTRIES_FILE,
    MANIFEST_FILE,
    REPORT_FILE,
    STATES_FILE,
    AuditPackManifest,
    PackFile,
)
from genesis_mesh.models.context import BoundaryDecision
from genesis_mesh.models.evidence_store import payload_digest
from genesis_mesh.models.out_of_band import RegistryRecord
from genesis_mesh.trust.context import verify_boundary_decision
from genesis_mesh.trust.evidence_store import build_entry, parse_export_lines, verify_evidence_events
from genesis_mesh.workflows.audit_pack import (
    Change,
    _cell,
    _Record,
    check_completeness,
    pack_entry_digests,
    parse_changes,
    parse_rfc3339,
)

from .succession_support import Network, public_b64, wait_until
from .test_audit_pack import (
    _anchor,
    _entries,
    _held,
    _history,
    _jsonl,
    _later,
    _lines,
    _pack,
    _read,
    _reasons,
    _resign,
    _verify,
)
from .test_evidence_store import SECRET, Controller, _client, _code, _decide, _submit
from .test_na_boundary_policy import _get, _post


@pytest.fixture(autouse=True)
def short_lead(monkeypatch):
    """Successions in these tests take effect a second or two after they are recorded."""
    monkeypatch.setattr(key_models, "SUCCESSION_MIN_LEAD", timedelta(seconds=1))


@pytest.fixture
def net(tmp_path):
    return Network(tmp_path)


def _succeed_now(net, service, client):
    """Record a succession, wait for it, restart the NA with the new key."""
    record, new_key = net.succession(service)
    resp = _post(client, "/admin/na/succession", {"succession": record})
    assert resp.status_code == 201, resp.get_json()
    net.adopt(new_key)
    wait_until(resp.get_json()["succession"]["effective_at"])
    service.db.close()
    restarted = net.start(evidence_out_of_band=service.evidence_out_of_band)
    return resp.get_json()["succession"], restarted, _client(restarted)


def _rebuild(line: dict, payload: dict, *, recorded_at: str | None = None) -> dict:
    entry = {**line["entry"], "payload_digest": payload_digest(payload)}
    if recorded_at:
        entry["recorded_at"] = recorded_at
    digest = hashlib.sha256(json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**line, "entry": entry, "payload": payload, "entry_digest": digest}


# ---------------------------------------------------------------------------
# 1. The frozen fixture is complete and tracked
# ---------------------------------------------------------------------------


FIXTURE = Path(__file__).resolve().parents[2] / "conformance" / "fixtures" / "audit-pack-1.5.0"


def test_every_file_the_frozen_manifest_lists_is_present_and_tracked_by_git():
    """Finding 1: a .gitignore rule dropped the fixture's keys/ directory from the commit."""
    import shutil
    import subprocess
    import sys

    sys.path.insert(0, str(FIXTURE.parents[1]))
    from generate_vectors import fixture_problems

    assert fixture_problems(FIXTURE) == []
    manifest = json.loads((FIXTURE / "pack" / MANIFEST_FILE).read_text(encoding="utf-8"))
    listed = {f"pack/{item['path']}" for item in manifest["files"]} | {"pack/manifest.json", "root.pub",
                                                                         "anchors.json"}
    git = shutil.which("git")
    repo = FIXTURE.parents[2]
    if git is None or not (repo / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run([git, "ls-files", "--", str(FIXTURE)], cwd=repo, capture_output=True, text=True, check=True)
    tracked = {Path(line).relative_to(FIXTURE.relative_to(repo)).as_posix() for line in out.stdout.splitlines()}
    ignored = subprocess.run([git, "check-ignore", "--no-index", *(str(FIXTURE / p) for p in sorted(listed))],
                             cwd=repo, capture_output=True, text=True)
    assert ignored.stdout.strip() == "", f"ignored by .gitignore: {ignored.stdout}"
    if tracked:  # a working tree before its first commit of the fixture tracks none of it yet
        assert listed <= tracked, f"not tracked by git: {sorted(listed - tracked)}"


def test_generate_vectors_refuses_an_incomplete_frozen_fixture(tmp_path):
    import shutil
    import sys

    sys.path.insert(0, str(FIXTURE.parents[1]))
    from generate_vectors import fixture_problems

    copy = tmp_path / "audit-pack-1.5.0"
    shutil.copytree(FIXTURE, copy)
    (copy / "pack" / "keys" / "na-key-history.json").unlink()
    assert fixture_problems(copy) == ["pack/keys/na-key-history.json is missing"]


# ---------------------------------------------------------------------------
# 2. A pack after a prune continues the chains from the checkpoint
# ---------------------------------------------------------------------------


def test_a_pack_after_a_prune_continues_a_resource_chain_from_the_checkpoint(net, monkeypatch):
    """Finding 2 (critic probe): archive, prune, a new record on an old resource, a pack of it."""
    service, client, controller, _ = _history(net)
    first, second = client._records
    whole = json.loads(_pack(client)[MANIFEST_FILE])
    assert _post(client, "/admin/evidence/archives", {"manifest": whole, "location": "vault/1"}).status_code == 201
    with monkeypatch.context() as patch:
        _later(patch)
        result = _post(client, "/admin/evidence/retention/apply", {"older_than_days": 30}).get_json()
        assert result["removed_count"] > 0
        assert "held_back" not in result, "finding 19: an archive covering the whole store holds nothing back"
        _anchor(client)
        held_mid = _held(client)
        third = controller.record(_decide(client), action="rotate", prior_resource=second,
                                  params={"version_id": "v3"})
        assert _submit(client, third).status_code == 201
        _anchor(client)
        files = _pack(client, from_sequence=held_mid[-1].store_sequence + 1)
    assert json.loads(files["checks.json"])["verified"] is True
    res = _verify(net, files, _held(client))
    assert res.verified, res.failures


# ---------------------------------------------------------------------------
# 3. Archives: only a pack the NA built, that verified; the CLI verifies what it reads back
# ---------------------------------------------------------------------------


def test_an_archive_names_a_pack_this_na_built_and_verified(net):
    """Finding 3 (skeptic P8): a manifest the NA never built, or one whose own checks failed, is refused."""
    service, client, _, _ = _history(net)
    built = _read(client, "POST", "/admin/evidence/audit-pack", {}).get_json()
    manifest = AuditPackManifest.model_validate(built["manifest"])
    # Re-signed by the NA key over other files: not the pack the NA built.
    other = manifest.model_copy(update={"signature": None, "files": [*manifest.files[:-1], PackFile(
        path=manifest.files[-1].path, sha256="0" * 64, bytes=1)]})
    other = other.model_copy(update={"signature": sign_model(other, net.na_keys[-1], "na-1")})
    refused = _post(client, "/admin/evidence/archives", {"manifest": other.to_wire(), "location": "vault/x"})
    assert refused.status_code == 409 and _code(refused) == "archive_pack_unknown"
    # A pack whose own checks failed (as the NA recorded it when it built it).
    failed = manifest.model_copy(update={"pack_id": "failed-pack", "signature": None})
    failed = failed.model_copy(update={"signature": sign_model(failed, net.na_keys[-1], "na-1")})
    service.db.add_audit_pack_row({
        "pack_id": "failed-pack", "manifest_sha256": hashlib.sha256(failed.file_bytes()).hexdigest(),
        "from_sequence": manifest.from_sequence, "through_sequence": manifest.through_sequence,
        "end_anchor_sequence": manifest.end_anchor_sequence, "verified": 0,
        "built_at": manifest.created_at.isoformat(), "requested_by": None})
    unverified = _post(client, "/admin/evidence/archives", {"manifest": failed.to_wire(), "location": "vault/y"})
    assert unverified.status_code == 409 and _code(unverified) == "archive_pack_unverified"
    ok = _post(client, "/admin/evidence/archives", {"manifest": built["manifest"], "location": "vault/1"})
    assert ok.status_code == 201, ok.get_json()


def test_audit_archive_refuses_a_pack_that_does_not_verify_once_read_back(net, tmp_path, monkeypatch):
    """Finding 3: the CLI verifies the files it read back before it records anything (--force overrides)."""
    from genesis_mesh.cli import audit_ops, support
    from genesis_mesh.cli.main import cli
    from genesis_mesh.crypto import save_keypair

    from .test_evidence_anchors import _FlaskSession

    service, client, _, _ = _history(net)
    monkeypatch.setattr(audit_ops.requests, "Session", lambda: _FlaskSession(client))
    monkeypatch.setattr(support.requests, "Session", lambda: _FlaskSession(client))
    operator, _ = save_keypair(net.privileged, str(tmp_path / "op"))
    wrong_root = public_b64(nacl.signing.SigningKey.generate())
    args = ["audit", "archive", "--na", "http://na.test", "--to", str(tmp_path / "vault"), "--no-prune",
            "--operator-key", str(operator), "--operator-key-id", "operator-test"]
    refused = CliRunner().invoke(cli, [*args, "--anchor", wrong_root])
    assert refused.exit_code != 0 and "does not verify" in refused.output, refused.output
    assert _get(client, "/admin/evidence/archives").get_json()["archives"] == []
    ok = CliRunner().invoke(cli, args)
    assert ok.exit_code == 0, ok.output


# ---------------------------------------------------------------------------
# 4. Cited entries are tied to prior packs and held anchors
# ---------------------------------------------------------------------------


def test_a_forged_cited_entry_is_refused_by_a_prior_pack_or_a_held_anchor(net):
    """Finding 4 (skeptic P1): the NA key holder substitutes a cited decision and re-signs the manifest."""
    service, client, controller, _ = _history(net)
    held = _held(client)
    earlier = _pack(client, until_sequence=held[-2].store_sequence)
    files = _pack(client, from_sequence=held[-2].store_sequence + 1)
    clean = _verify(net, files, held)
    assert clean.verified and "cited_entry_unanchored" in {w["reason"] for w in clean.warnings}
    assert _verify(net, files, held, prior_entries=pack_entry_digests(earlier)).verified
    cited = _lines(files[CITED_FILE])
    i = next(i for i, e in enumerate(cited) if e["entry"]["entry_kind"] == "decision")
    payload = json.loads(json.dumps(cited[i]["payload"]))
    d = BoundaryDecision.model_validate(payload["decision"])
    forged = d.model_copy(update={"denial_reason": "forged", "signature": None})
    forged = forged.model_copy(update={"signature": sign_model(forged, net.na_keys[-1], "na-1")})
    payload["decision"] = forged.model_dump(mode="json")
    cited[i] = _rebuild(cited[i], payload)
    out = _resign(net, files, {CITED_FILE: _jsonl(cited)})
    alone = _verify(net, out, held)
    assert alone.verified, "signed: alone, the forgery is only the warning"
    assert "cited_entry_unanchored" in {w["reason"] for w in alone.warnings}
    against_prior = _verify(net, out, held, prior_entries=pack_entry_digests(earlier))
    assert "cited_entry_mismatch" in _reasons(against_prior)


def test_audit_verify_prior_checks_cited_entries(net, tmp_path):
    from genesis_mesh.cli.audit_ops import write_pack
    from genesis_mesh.cli.main import cli

    service, client, _, _ = _history(net)
    held = _held(client)
    write_pack(tmp_path / "earlier", _pack(client, until_sequence=held[-2].store_sequence))
    write_pack(tmp_path / "later", _pack(client, from_sequence=held[-2].store_sequence + 1))
    (tmp_path / "root.pub").write_text(public_b64(net.root), encoding="utf-8")
    (tmp_path / "anchors.json").write_text(json.dumps([a.to_wire() for a in held]), encoding="utf-8")
    result = CliRunner().invoke(cli, ["audit", "verify", str(tmp_path / "later"), "--anchor", str(tmp_path / "root.pub"),
                                      "--known-anchors", str(tmp_path / "anchors.json"),
                                      "--prior", str(tmp_path / "earlier"), "--format", "json"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert "cited_entry_unanchored" not in {w["reason"] for w in body["warnings"]}


# ---------------------------------------------------------------------------
# 5. A decision may not outlive its key
# ---------------------------------------------------------------------------


def test_a_decision_outliving_its_succeeded_key_is_refused_offline_and_by_the_na(net):
    """Finding 5 (skeptic P4): the holder of a succeeded key mints a decision valid for a year."""
    service = net.start()
    client = _client(service)
    decision = _decide(client)
    assert decision.decision_valid_until - decision.decision_made_at <= key_models.MAX_DECISION_LIFETIME
    _, restarted, client = _succeed_now(net, service, client)
    history = net.history(restarted)
    old = history.keys[0]
    made = old.succeeded_at - timedelta(seconds=5)
    forged = decision.model_copy(update={"decision_made_at": made, "decision_valid_until": made + timedelta(days=365),
                                         "signature": None})
    forged = forged.model_copy(update={"signature": sign_model(forged, net.na_keys[0], "na-1")})
    assert verify_boundary_decision(forged, history, now=made).reason == "decision_outlives_key"
    resp = client.post("/boundary/verify", json={"decision": forged.model_dump(mode="json")}).get_json()
    assert resp["accepted"] is False and resp["reason"] == "decision_outlives_key"
    # Within the cap it still verifies, as of its own time.
    short = forged.model_copy(update={"decision_valid_until": made + timedelta(seconds=300), "signature": None})
    short = short.model_copy(update={"signature": sign_model(short, net.na_keys[0], "na-1")})
    assert verify_boundary_decision(short, history, at_record_time=True).accepted


def test_the_decision_lifetime_setting_is_capped():
    from genesis_mesh.na_service.settings import load_settings

    base = {"GENESIS_FILE": "g.json"}
    assert load_settings({**base, "NA_DECISION_LIFETIME_SECONDS": "60"}).decision_lifetime_seconds == 60
    with pytest.raises(ValueError, match="NA_DECISION_LIFETIME_SECONDS"):
        load_settings({**base, "NA_DECISION_LIFETIME_SECONDS": "301"})


def test_the_na_issues_decisions_with_its_configured_lifetime(net):
    service = net.start(decision_lifetime_seconds=60)
    decision = _decide(_client(service))
    assert decision.decision_valid_until - decision.decision_made_at == timedelta(seconds=60)


# ---------------------------------------------------------------------------
# 6. Time order in the store
# ---------------------------------------------------------------------------


def _forged_registry(net, service, at: datetime):
    """What a database writer holding a succeeded NA key appends: an executor key of its own."""
    attacker = nacl.signing.SigningKey.generate()
    record = RegistryRecord(event="executor_key_registered", key_id="evil", public_key=public_b64(attacker),
                            executor_sovereign_id="EXEC", key_role="executor", effective_at=at,
                            issuer_sovereign_id="TEST", issued_by="na-1")
    record = record.model_copy(update={"signature": sign_model(record, net.na_keys[0], "na-1")})
    payload = record.to_wire()
    service.db.append_evidence_entries_with(lambda db: [(lambda seq, prev: build_entry(
        store_sequence=seq, entry_kind="registry", recorded_at=at, payload=payload, prev_entry_digest=prev,
        index={"record_id": record.registry_record_id, "outcome": record.event}), payload)])


def test_an_entry_dated_back_into_a_succeeded_keys_window_is_refused(net):
    """Finding 6 (skeptic P5): the store's time does not go backwards, and the NA does not anchor it."""
    service = net.start(evidence_out_of_band="on")
    client = _client(service)
    controller = Controller(client)
    assert _submit(client, controller.record(_decide(client))).status_code == 201
    _anchor(client)
    _, restarted, client = _succeed_now(net, service, client)
    assert _submit(client, controller.record(_decide(client), resource=None)).status_code == 201
    old = net.history(restarted).keys[0]
    _forged_registry(net, restarted, old.succeeded_at - timedelta(seconds=600))
    refused = _read(client, "POST", "/admin/evidence/anchors", {})
    assert refused.status_code == 409 and "goes backwards" in refused.get_json()["error"]["message"]
    export = parse_export_lines(_get(client, "/admin/evidence/export").get_data(as_text=True).splitlines())
    result = verify_evidence_events(export, na_public_keys=net.history(restarted), executor_keys={})
    assert "recorded_at_out_of_order" in {f["reason"] for f in result.failures}


def test_an_entry_signed_by_a_key_whose_window_the_store_moved_past_is_refused(net):
    """Finding 6: dated inside the hand-over (so no time goes backwards past the tolerance) but stored after
    an entry dated beyond it: the key must be valid at the later time too."""
    service = net.start(evidence_out_of_band="on")
    client = _client(service)
    assert _submit(client, Controller(client).record(_decide(client))).status_code == 201
    _, restarted, client = _succeed_now(net, service, client)
    old = net.history(restarted).keys[0]
    end = old.succeeded_at + key_models.SUCCESSION_HANDOVER
    # An honest entry stored once the hand-over ended, then one dated just inside it.
    record = RegistryRecord(event="policy_history_started", effective_at=end + timedelta(seconds=10),
                            issuer_sovereign_id="TEST", issued_by="na-2")
    record = record.model_copy(update={"signature": sign_model(record, net.na_keys[1], "na-2")})
    payload = record.to_wire()
    restarted.db.append_evidence_entries_with(lambda db: [(lambda seq, prev: build_entry(
        store_sequence=seq, entry_kind="registry", recorded_at=end + timedelta(seconds=10), payload=payload,
        prev_entry_digest=prev, index={"record_id": record.registry_record_id, "outcome": record.event}), payload)])
    _forged_registry(net, restarted, end - timedelta(seconds=1))
    export = parse_export_lines(_get(client, "/admin/evidence/export").get_data(as_text=True).splitlines())
    keys = restarted.evidence_store_service.executor_keys()
    result = verify_evidence_events(export, na_public_keys=net.history(restarted), executor_keys=keys)
    assert [f["reason"] for f in result.failures] == ["na_key_not_valid_at_time"], result.failures
    assert result.failures[0]["store_sequence"] == export[-1].entry.store_sequence


# ---------------------------------------------------------------------------
# 7. Mesh nodes follow the key history
# ---------------------------------------------------------------------------


def test_a_mesh_node_verifies_certificates_signed_by_a_succeeded_to_key(net, tmp_path, monkeypatch):
    """Finding 7: a node checks join certificates, policies and CRLs against the key history verified from
    the genesis block's root key (GET /na/key-history), cached between runs."""
    from genesis_mesh.models import JoinCertificate
    from genesis_mesh.node.node import MeshNode

    service = net.start()
    client = _client(service)
    _, restarted, client = _succeed_now(net, service, client)
    view = client.get("/na/key-history").get_json()
    node = MeshNode(net.genesis, key_history_cache=tmp_path / "keys.json")
    now = datetime.now(timezone.utc)
    cert = JoinCertificate(cert_id="c1", network_name="TEST", node_public_key=public_b64(nacl.signing.SigningKey.generate()),
                           roles=["role:client"], issued_at=now, expires_at=now + timedelta(hours=1), issued_by="na-2")
    cert.signatures.append(sign_model(cert, net.na_keys[1], "na-2"))
    assert not node._verify_join_certificate(cert), "the genesis key alone does not know the new key"

    class _Resp:
        status_code, ok = 200, True

        @staticmethod
        def json():
            return view

    monkeypatch.setattr("genesis_mesh.node.node.requests.get", lambda url, timeout: _Resp())
    assert node.refresh_key_history("http://na.test")
    assert node._verify_join_certificate(cert)
    # Cached: a node started again knows the key without asking the NA.
    again = MeshNode(net.genesis, key_history_cache=tmp_path / "keys.json")
    assert again._verify_join_certificate(cert)
    # A history the root key did not sign is refused.
    forged = json.loads(json.dumps(view))
    forged["successions"][0]["new_key_id"] = "evil"
    fresh = MeshNode(net.genesis)
    assert not fresh.adopt_key_history(forged["successions"])
    # A certificate the old key signs after its window is refused.
    late = cert.model_copy(update={"issued_by": "na-1", "signatures": [],
                                   "issued_at": now + timedelta(seconds=key_models.SUCCESSION_HANDOVER.seconds + 5)})
    late.signatures.append(sign_model(late, net.na_keys[0], "na-1"))
    assert not node._verify_join_certificate(late)


# ---------------------------------------------------------------------------
# 10. A backdated succession entry in the store
# ---------------------------------------------------------------------------


def test_a_succession_entry_recorded_less_than_the_lead_before_it_takes_effect_is_refused(net):
    """Finding 10: in the store, recorded_at + SUCCESSION_MIN_LEAD <= effective_at (succession_backdated)."""
    service = net.start()
    client = _client(service)
    record, new_key = net.succession(service, effective_in=1.5)
    assert _post(client, "/admin/na/succession", {"succession": record}).status_code == 201
    export = parse_export_lines(_get(client, "/admin/evidence/export").get_data(as_text=True).splitlines())
    history = net.history(service)
    assert verify_evidence_events(export, na_public_keys=history, executor_keys={}).verified
    key_models.SUCCESSION_MIN_LEAD = timedelta(seconds=60)  # the real lead (the fixture restores it)
    result = verify_evidence_events(export, na_public_keys=history, executor_keys={})
    assert [f["reason"] for f in result.failures] == ["succession_backdated"]


# ---------------------------------------------------------------------------
# 11. Completeness: the period, the matching, duplicates, event IDs
# ---------------------------------------------------------------------------

T = datetime(2026, 1, 1, tzinfo=timezone.utc)
PERIOD = (T - timedelta(hours=1), T + timedelta(hours=1))


def _records(monkeypatch, records):
    import genesis_mesh.workflows.audit_pack as ap

    for r in records:
        r.group = r.group or r.record_id
    monkeypatch.setattr(ap, "_records", lambda e, c: records)


def test_completeness_finds_the_matching_a_greedy_pass_misses(monkeypatch):
    """Finding 11 (critic): change 1 takes r1 (200 s), change 2 r2 (150 s); a greedy pass took r2 for change 1."""
    _records(monkeypatch, [
        _Record("execution", "r1", 1, "R", "rotate", T - timedelta(seconds=200), T - timedelta(seconds=200)),
        _Record("execution", "r2", 2, "R", "rotate", T + timedelta(seconds=100), T + timedelta(seconds=100))])
    out = check_completeness([Change(1, "R", "rotate", T), Change(2, "R", "rotate", T + timedelta(seconds=250))],
                             [], period=PERIOD)
    assert out["unmatched_changes"] == [] and [p["record_id"] for p in out["pairs"]] == ["r1", "r2"]


def test_completeness_sets_aside_a_repeated_source_event(monkeypatch):
    _records(monkeypatch, [_Record("observation", "o1", 1, "R", "rotate", T, T, "log", "evt-1")])
    out = check_completeness([Change(1, "R", "rotate", T, "log", "evt-1"), Change(2, "R", "rotate", T, "log", "evt-1")],
                             [], period=PERIOD)
    assert out["unmatched_changes"] == [] and [d["index"] for d in out["duplicate_changes"]] == [2]


def test_completeness_matches_an_event_id_only_on_its_resource_and_action(monkeypatch):
    """Finding 11 (critic and skeptic P6): an event ID naming another resource or action is no match."""
    _records(monkeypatch, [_Record("observation", "o1", 1, "OTHER", "delete", T, T, "log", "evt-1")])
    out = check_completeness([Change(1, "R", "rotate", T, "log", "evt-1")], [], period=PERIOD)
    assert out["pairs"] == [] and [c["index"] for c in out["unmatched_changes"]] == [1]


def test_completeness_looks_a_change_without_an_event_id_up_by_time_only(monkeypatch):
    """Finding 29: a change without a source event ID never matches a record whose event ID is "None"."""
    _records(monkeypatch, [_Record("observation", "o1", 1, "R", "rotate", T + timedelta(days=1),
                                   T + timedelta(days=1), "None", "None")])
    out = check_completeness([Change(1, "R", "rotate", T)], [], period=PERIOD)
    assert out["pairs"] == [] and len(out["unmatched_changes"]) == 1


def test_the_pack_period_starts_at_its_start_anchor(net):
    """Finding 11 (critic): a change between the start anchor and the first entry is inside the period."""
    import time

    service, client, controller, _ = _history(net)
    start = _held(client)[-1]
    time.sleep(1.0)
    t = datetime.now(timezone.utc)
    time.sleep(1.0)
    assert _submit(client, controller.record(_decide(client), resource=None)).status_code == 201
    _anchor(client)
    files = _pack(client, from_sequence=start.store_sequence + 1)
    res = _verify(net, files, _held(client), changes=[Change(1, SECRET, "delete", t)], tolerance=timedelta(0))
    assert "change_unmatched" in _reasons(res)
    assert res.period["from"] == start.anchored_at.isoformat().replace("+00:00", "Z")


def test_a_short_pack_fails_the_period_asked_for_and_warns_of_changes_outside(net):
    """Finding 11 (skeptic P7): a pack that ends early cannot hide a change from a period it was asked for."""
    service, client, _, _ = _history(net)
    held = _held(client)
    files = _pack(client, until_sequence=held[0].store_sequence)
    later = datetime.now(timezone.utc) + timedelta(hours=2)
    result = _verify(net, files, held, changes=[Change(1, SECRET, "delete", later)])
    assert result.verified and "changes_outside_period" in {w["reason"] for w in result.warnings}
    asked = _verify(net, files, held, period=(datetime.now(timezone.utc) - timedelta(hours=1), later))
    assert "pack_period_not_covered" in _reasons(asked)


def test_the_period_asked_for_is_recorded_in_the_manifest(net):
    service, client, _, _ = _history(net)
    since = (datetime.now(timezone.utc) - timedelta(days=1)).replace(microsecond=0)
    files = _pack(client, since=since.isoformat())
    manifest = AuditPackManifest.model_validate_json(files[MANIFEST_FILE])
    assert manifest.period_from == since and manifest.period_until is None
    assert _verify(net, files, _held(client)).period["requested_from"] == since.isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# 12. A manifest is not dated before its end anchor
# ---------------------------------------------------------------------------


def test_a_manifest_backdated_by_a_succeeded_key_is_refused(net):
    """Finding 12 (skeptic P2)."""
    service = net.start(evidence_out_of_band="on")
    client = _client(service)
    controller = Controller(client)
    assert _submit(client, controller.record(_decide(client))).status_code == 201
    _anchor(client)
    succession, restarted, client = _succeed_now(net, service, client)
    assert _submit(client, controller.record(_decide(client), resource=None)).status_code == 201
    _anchor(client)
    files = _pack(client)
    held = _held(client)
    assert _verify(net, files, held).verified
    m = AuditPackManifest.model_validate_json(files[MANIFEST_FILE])
    eff = datetime.fromisoformat(succession["effective_at"].replace("Z", "+00:00"))
    m = m.model_copy(update={"signature": None, "created_at": eff - timedelta(seconds=30), "issued_by": "na-1"})
    m = m.model_copy(update={"signature": sign_model(m, net.na_keys[0], "na-1")})
    result = _verify(net, {**files, MANIFEST_FILE: m.file_bytes()}, held)
    assert "manifest_backdated" in _reasons(result)


# ---------------------------------------------------------------------------
# 13. The report renders from the pack; cells are escaped; no file outside the format
# ---------------------------------------------------------------------------


def test_a_report_that_says_what_the_pack_does_not_hold_fails(net, tmp_path):
    """Finding 13 (skeptic P3)."""
    from genesis_mesh.cli.audit_ops import write_pack
    from genesis_mesh.cli.main import cli

    service, client, _, _ = _history(net)
    held = _held(client)
    files = _pack(client)
    assert STATES_FILE in files and _verify(net, files, held).verified
    out = _resign(net, files, {REPORT_FILE: b"# Audit pack\n\nNothing happened.\n"})
    result = _verify(net, out, held)
    assert "report_mismatch" in _reasons(result) and result.report_differences
    # The states the report shows are in a listed file: changing them changes the report.
    states = json.loads(files[STATES_FILE])
    states["notices"] = {"x": {"notified_at": "2026-01-01T00:00:00Z", "notified_by": "op"}}
    changed = _resign(net, files, {STATES_FILE: json.dumps(states).encode()})
    assert "report_mismatch" in _reasons(_verify(net, changed, held))
    # audit verify writes the report it renders itself.
    write_pack(tmp_path / "pack", files)
    (tmp_path / "root.pub").write_text(public_b64(net.root), encoding="utf-8")
    (tmp_path / "anchors.json").write_text(json.dumps([a.to_wire() for a in held]), encoding="utf-8")
    ran = CliRunner().invoke(cli, ["audit", "verify", str(tmp_path / "pack"), "--anchor", str(tmp_path / "root.pub"),
                                   "--known-anchors", str(tmp_path / "anchors.json"),
                                   "--report", str(tmp_path / "own.md")])
    assert ran.exit_code == 0, ran.output
    assert "Verified by this verifier" in (tmp_path / "own.md").read_text(encoding="utf-8")


def test_report_cells_escape_what_could_end_a_row_or_a_line():
    assert _cell("a|b") == "a\\|b"
    assert _cell("back\\slash") == "back\\\\slash"
    assert _cell("line\nfeed\rreturn\ttab") == "line\\nfeed\\rreturn\\ttab"
    assert _cell("bell\x07 del\x7f nel\x85 ls\u2028") == "bell\\u0007 del\\u007F nel\\u0085 ls\\u2028"
    assert _cell("lone\r") == "lone\\r"


def test_a_listed_file_outside_the_format_is_refused(net):
    """Finding 13 (skeptic P14)."""
    service, client, _, _ = _history(net)
    held = _held(client)
    out = _resign(net, _pack(client), {"READ-ME-FIRST.md": b"All checks passed.\n"})
    assert "manifest_unknown_file" in _reasons(_verify(net, out, held))


# ---------------------------------------------------------------------------
# 14 and 15. Live routes and agreements: keys at the record's own time
# ---------------------------------------------------------------------------


def test_the_na_votes_only_over_proofs_its_current_key_signed(net):
    """Finding 14 (skeptic P12)."""
    from genesis_mesh.models.justification import JustificationProof

    from .test_evidence_store import _issue

    service = net.start()
    client = _client(service)
    att = _issue(client, capabilities=["secret.manage"], subject="vendor-acme")["attestation_id"]
    resp = _post(client, "/admin/boundary/evaluate", {"attestation_id": att, "requested_capability": "secret.manage",
                                                      "context": {"request_parameters": {"app_id": "billing"}}})
    proof = JustificationProof.model_validate(resp.get_json()["justification_proof"])
    _, restarted, client = _succeed_now(net, service, client)
    forged = proof.model_copy(update={"proof_id": "forged", "decision_id": "invented",
                                      "proof_issued_at": datetime.now(timezone.utc), "signature": None})
    forged = forged.model_copy(update={"signature": sign_model(forged, net.na_keys[0], "na-1")})
    vote = _post(client, "/admin/consensus/vote", {"justification_proof": forged.model_dump(mode="json"), "vote": True})
    assert vote.status_code == 422 and _code(vote) == "justification_untrusted"


def test_boundary_policy_verify_uses_the_key_valid_when_the_policy_was_issued(net):
    """Finding 14: a policy issued before a succession verifies after it; one the old key signs later does not."""
    from .test_na_boundary_policy import _intent

    service = net.start()
    client = _client(service)
    created = _post(client, "/admin/boundary-policies", _intent())
    assert created.status_code == 201, created.get_json()
    policy = created.get_json()
    _, restarted, client = _succeed_now(net, service, client)
    ok = client.post("/boundary-policies/verify", json={"policy": policy}).get_json()
    assert ok["valid"] is True, ok
    from genesis_mesh.models.boundary_policy import BoundaryPolicy

    late = BoundaryPolicy.model_validate(policy).model_copy(update={
        "issued_at": datetime.now(timezone.utc) + timedelta(minutes=10), "signature": None})
    late = late.model_copy(update={"signature": sign_model(late, net.na_keys[0], "na-1")})
    refused = client.post("/boundary-policies/verify", json={"policy": late.model_dump(mode="json")}).get_json()
    assert refused["valid"] is False


def test_an_agreement_the_succeeded_key_signed_stops_vouching_after_the_hand_over(net):
    """Finding 15: established_at is not signed; the key is placed at agreed_terms.valid_from and must still
    be accepted now."""
    service = net.start()
    assert service.na_keys_vouching(datetime.now(timezone.utc)) == [public_b64(net.na_keys[0])]
    client = _client(service)
    _, restarted, client = _succeed_now(net, service, client)
    old_era = datetime.now(timezone.utc) - timedelta(seconds=5)
    assert public_b64(net.na_keys[0]) in restarted.na_keys_vouching(old_era), "within the hand-over"
    after = datetime.now(timezone.utc) + key_models.SUCCESSION_HANDOVER + timedelta(seconds=5)
    assert restarted.na_keys_vouching(old_era, now=after) == []
    # A key's own record time is not enough: an agreement dated in the old window, judged later, is not vouched.
    assert restarted.na_keys_vouching((old_era).isoformat(), now=after) == []


# ---------------------------------------------------------------------------
# 20, 21, 22, 23
# ---------------------------------------------------------------------------


def test_a_managed_deployment_refuses_to_run_without_archives(tmp_path):
    """Finding 20."""
    from genesis_mesh.na_service.app_factory import build_app
    from genesis_mesh.na_service.settings import load_settings

    net = Network(tmp_path)
    genesis = tmp_path / "genesis.json"
    genesis.write_text(net.genesis.model_dump_json(), encoding="utf-8")
    key = tmp_path / "na.key"
    import base64

    key.write_text(base64.b64encode(bytes(net.na_keys[0])).decode(), encoding="utf-8")
    settings = load_settings({"GENESIS_FILE": str(genesis), "NA_PRIVATE_KEY_FILE": str(key),
                              "DB_PATH": str(tmp_path / "na.db"), "NA_DEPLOYMENT": "managed",
                              "NA_RETENTION_REQUIRE_ARCHIVE": "off"})
    with pytest.raises(ValueError, match="NA_RETENTION_REQUIRE_ARCHIVE=off"):
        build_app(settings)


def test_a_pack_refuses_a_record_signed_by_a_retired_or_later_registered_key(net):
    """Findings 21 and 30: a key verifies only records stored after it was registered and before it retired."""
    from genesis_mesh.trust.evidence_store import ExecutorKey

    key = ExecutorKey("k", "pub", "S", registered_sequence=5, retired_sequence=9)
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert key.position_problem(4, at) == "evidence_unknown_executor"
    assert key.position_problem(5, at) == "evidence_unknown_executor"
    assert key.position_problem(6, at) is None
    assert key.position_problem(10, at) == "evidence_executor_key_retired"
    by_time = ExecutorKey("k", "pub", "S", registered_at=at)
    assert by_time.position_problem(1, at - timedelta(seconds=1)) == "evidence_unknown_executor"
    assert by_time.position_problem(1, at) is None
    assert ExecutorKey("k", "pub", "S").position_problem(1, at) is None, "a key supplied out of band is not placed"


def test_a_pack_places_executor_keys_where_the_registry_records_them(net):
    """Finding 30 (Rust port): a key registered at a later position does not verify an earlier record; a
    retired key verifies what was stored before it retired."""
    import dataclasses

    from genesis_mesh.workflows.audit_pack import _registry_keys

    service, client, controller, _ = _history(net)
    assert _post(client, f"/admin/evidence/executor-keys/{controller.key_id}/retire", {}).status_code == 200
    _anchor(client)
    files = _pack(client)
    held = _held(client)
    assert _verify(net, files, held).verified
    events = parse_export_lines(files[ENTRIES_FILE].decode().splitlines())
    history = net.history(service)
    keys = _registry_keys(events, history)
    key = keys[controller.key_id]
    registry = [e.entry.store_sequence for e in events if e.entry.entry_kind == "registry"
                and e.payload.get("key_id") == controller.key_id]
    assert (key.registered_sequence, key.retired_sequence) == (registry[0], registry[-1])
    executions = [e.entry.store_sequence for e in events if e.entry.entry_kind == "execution"]
    assert key.registered_sequence < min(executions) and max(executions) < key.retired_sequence
    # Registered after the records it signed: they do not verify.
    later = {controller.key_id: dataclasses.replace(key, registered_sequence=max(executions), retired_sequence=None)}
    result = verify_evidence_events(events, na_public_keys=history, executor_keys=later)
    assert "evidence_unknown_executor" in {f["reason"] for f in result.failures}
    # Retired before them: they do not verify either.
    early = {controller.key_id: dataclasses.replace(key, retired_sequence=min(executions) - 1)}
    result = verify_evidence_events(events, na_public_keys=history, executor_keys=early)
    assert "evidence_executor_key_retired" in {f["reason"] for f in result.failures}


def test_the_custody_check_finds_the_root_key_in_a_sibling_directory_and_the_environment(net, tmp_path):
    """Finding 22."""
    import base64

    from genesis_mesh.na_service.key_provider import root_key_findings

    config = tmp_path / "etc" / "genesis-mesh"
    (config / "na").mkdir(parents=True)
    (config / "secrets" / "offline").mkdir(parents=True)
    seed = base64.b64encode(bytes(net.root)).decode()
    (config / "secrets" / "offline" / "root.seed").write_text(seed, encoding="utf-8")
    genesis = config / "na" / "genesis.json"
    genesis.write_text("{}", encoding="utf-8")
    findings = root_key_findings(public_b64(net.root), na_public_key=public_b64(net.na_keys[0]),
                                 paths=[genesis], environ={"ROOT_SEED_BACKUP": seed})
    assert any("root.seed" in f for f in findings), findings
    assert any("ROOT_SEED_BACKUP" in f for f in findings), findings


def test_fleet_generate_warns_where_the_root_keys_are(tmp_path):
    from genesis_mesh.cli.main import cli

    result = CliRunner().invoke(cli, ["fleet", "generate", "--count", "1", "--output", str(tmp_path / "fleet")])
    assert result.exit_code == 0, result.output
    assert "root private key" in result.output


def test_audit_packs_have_a_rate_limit_of_their_own(net):
    """Finding 23."""
    from genesis_mesh.na_service.rate_limit import RateLimits

    service, client, _, _ = _history(net)
    service.rate_limits = RateLimits(audit_packs=1)
    assert _read(client, "POST", "/admin/evidence/audit-pack", {}).status_code == 200
    second = _read(client, "POST", "/admin/evidence/audit-pack", {})
    assert second.status_code == 429


# ---------------------------------------------------------------------------
# 31 and 35. The CLI without held anchors; the changes file
# ---------------------------------------------------------------------------


def test_audit_verify_runs_without_held_anchors_unless_they_are_required(net, tmp_path):
    """Finding 31: as the library and the spec, a warning (no_held_anchors); --require-anchors fails."""
    from genesis_mesh.cli.audit_ops import write_pack
    from genesis_mesh.cli.main import cli

    service, client, _, _ = _history(net)
    write_pack(tmp_path / "pack", _pack(client))
    (tmp_path / "root.pub").write_text(public_b64(net.root), encoding="utf-8")
    base = ["audit", "verify", str(tmp_path / "pack"), "--anchor", str(tmp_path / "root.pub")]
    ran = CliRunner().invoke(cli, [*base, "--format", "json"])
    assert ran.exit_code == 0, ran.output
    assert "WARNING: no --known-anchors" in ran.output
    required = CliRunner().invoke(cli, [*base, "--require-anchors"])
    assert required.exit_code != 0 and "--require-anchors" in required.output


@pytest.mark.parametrize("value", ["2026-01-01", "2026-01-01 00:00:00Z", "2026-01-01T00:00:00", "2026-13-01T00:00:00Z",
                                   "2026-01-01T00:00:60Z", "2026-01-01T00:00:00+24:00", "20260101T000000Z"])
def test_a_changes_file_time_is_strict_rfc3339(value):
    """Finding 35."""
    with pytest.raises(ValueError):
        parse_rfc3339(value)


def test_rfc3339_times_in_either_case_and_with_offsets_are_read():
    assert parse_rfc3339("2026-01-01t02:00:00.1234567+02:00") == datetime(2026, 1, 1, 0, 0, 0, 123456,
                                                                          tzinfo=timezone.utc)
    assert parse_rfc3339("2026-01-01T00:00:00z") == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_a_changes_file_refuses_non_string_values():
    """Finding 35: true is not "True"."""
    with pytest.raises(ValueError, match="must be a string"):
        parse_changes(json.dumps([{"resource_id": True, "action": "rotate", "changed_at": "2026-01-01T00:00:00Z"}]),
                      csv_format=False)
    with pytest.raises(ValueError, match="must be a string"):
        parse_changes(json.dumps([{"resource_id": "r", "action": "rotate", "changed_at": "2026-01-01T00:00:00Z",
                                   "source": 7, "source_event_id": "e"}]), csv_format=False)
    rows = parse_changes(json.dumps([{"resource_id": "r", "action": "rotate", "changed_at": "2026-01-01T00:00:00Z",
                                      "source": None, "source_event_id": None, "actor": ""}]), csv_format=False)
    assert rows[0].source is None and rows[0].actor is None


# ---------------------------------------------------------------------------
# 26 and 34. Signatures over what was received
# ---------------------------------------------------------------------------


def test_a_manifest_missing_a_defaulted_field_is_checked_as_received(net):
    """Finding 26 (TypeScript port): a manifest without "format" is not the record the NA signed."""
    service, client, _, _ = _history(net)
    files = _pack(client)
    data = json.loads(files[MANIFEST_FILE])
    del data["format"]
    body = (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()
    result = _verify(net, {**files, MANIFEST_FILE: body}, _held(client))
    assert "manifest_invalid_signature" in _reasons(result)


def test_an_attestation_in_a_pack_with_a_field_outside_its_signature_is_refused(net):
    """Finding 34: trust files are checked as received, not over a model that drops extra fields."""
    from genesis_mesh.models.audit_pack import ATTESTATIONS_FILE

    service, client, _, _ = _history(net)
    files = _pack(client)
    attestations = _lines(files[ATTESTATIONS_FILE])
    assert attestations, "the decisions rest on an attestation"
    assert _verify(net, files, _held(client)).verified
    attestations[0]["x_added_field"] = 1
    out = _resign(net, files, {ATTESTATIONS_FILE: _jsonl(attestations)})
    assert "attestation_invalid_signature" in _reasons(_verify(net, out, _held(client)))
