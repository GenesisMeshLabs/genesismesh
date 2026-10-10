"""Signed store anchors (v1.2.0).

The evidence store is a hash chain: whoever can write the database can remove
an entry and rebuild every later link, and the export still verifies. The NA
now signs the store's head (an anchor) as it grows; an auditor keeps copies of
the anchors outside the operator's reach and verifies exports against them.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import pytest
from click.testing import CliRunner

from genesis_mesh.cli import evidence_store_ops, support
from genesis_mesh.cli.evidence_store_ops import evidence as evidence_cli
from genesis_mesh.crypto import generate_keypair, save_keypair
from genesis_mesh.models.evidence_store import EvidenceEvent, StoreAnchor
from genesis_mesh.trust.evidence_store import (
    EvidenceVerification,
    check_events_against_anchors,
    parse_export_lines,
    sign_store_anchor,
    verify_store_anchors,
)

from .test_evidence_store import Controller, _client, _decide, _submit
from .test_na_boundary_policy import _get, _headers, _make_service, _post

ANCHORS = "/admin/evidence/anchors"


def _service(**kwargs):
    service = _make_service(evidence_store="on", **kwargs)
    reader = generate_keypair()
    service.operator_public_keys["operator-read"] = reader.public_key_b64
    service.operator_key_tiers["operator-read"] = "read"
    setattr(service, "_read_keypair", reader)
    return service


@pytest.fixture
def na_service():
    return _service()


@pytest.fixture
def client(na_service):
    c = _client(na_service)
    setattr(c, "service", na_service)
    return c


def _anchors(client) -> list[dict]:
    resp = _get(client, ANCHORS)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["anchors"]


def _export(client) -> list[EvidenceEvent]:
    resp = _get(client, "/admin/evidence/export")
    assert resp.status_code == 200
    return parse_export_lines(resp.get_data(as_text=True).splitlines())


def _na_key(service) -> str:
    return service.signer.public_key_b64


def _tamper(db, trigger: str, table: str, sql: str, params: tuple = ()) -> None:
    """Change the database behind the NA's back: drop a guard trigger, then write.

    What a database writer without the NA key can do; works on SQLite and
    PostgreSQL alike (the suite runs on both).
    """
    drop = f"DROP TRIGGER {trigger}" if db.backend == "sqlite" else f"DROP TRIGGER {trigger} ON {table}"
    with db.conn:
        db.conn.execute(drop)
        db.conn.execute(sql, params)


def _activity(client, n: int = 2) -> None:
    controller = Controller(client, key_id=f"ctrl-{os.urandom(3).hex()}")
    for i in range(n):
        record = controller.record(_decide(client), resource=f"kv:anchors/secret-{os.urandom(3).hex()}-{i}")
        assert _submit(client, record).status_code == 201


# --- anchoring ------------------------------------------------------------------


def test_the_first_append_is_anchored_and_the_interval_holds_the_next(client, na_service):
    _decide(client)  # a decision and its justification: entries 1 and 2
    anchors = _anchors(client)
    assert len(anchors) == 1
    first = StoreAnchor.model_validate(anchors[0])
    assert first.anchor_sequence == 1 and first.previous_anchor_digest is None
    assert (first.store_sequence, first.entry_digest) == na_service.db.store_head()
    assert first.sovereign_id == "TEST"
    _decide(client)
    assert len(_anchors(client)) == 1, "a second anchor within the interval"


def test_anchoring_on_request_is_idempotent_while_the_head_is_unchanged(client, na_service):
    _decide(client)
    _decide(client)
    created = _post(client, ANCHORS, {}, standard=True)
    assert created.status_code == 201 and created.get_json()["status"] == "anchored"
    anchor = StoreAnchor.model_validate(created.get_json()["anchor"])
    assert anchor.anchor_sequence == 2
    assert anchor.store_sequence == na_service.db.store_head()[0]
    again = _post(client, ANCHORS, {}, standard=True)
    assert again.status_code == 200 and again.get_json()["status"] == "unchanged"
    assert again.get_json()["anchor"] == created.get_json()["anchor"]


def test_an_interval_of_zero_anchors_only_on_request():
    client = _client(_service(anchor_interval_seconds=0))
    _decide(client)
    assert _anchors(client) == []
    assert _post(client, ANCHORS, {}, standard=True).status_code == 201


def test_a_negative_interval_is_refused():
    with pytest.raises(ValueError, match="anchor_interval_seconds"):
        _service(anchor_interval_seconds=-1)


def test_settings_read_the_interval():
    from genesis_mesh.na_service.settings import load_settings
    assert load_settings({"GENESIS_FILE": "g.json"}).anchor_interval_seconds == 3600
    assert load_settings({"GENESIS_FILE": "g.json", "NA_ANCHOR_INTERVAL_SECONDS": "60"}).anchor_interval_seconds == 60
    with pytest.raises(ValueError, match="NA_ANCHOR_INTERVAL_SECONDS"):
        load_settings({"GENESIS_FILE": "g.json", "NA_ANCHOR_INTERVAL_SECONDS": "hourly"})


def test_a_failed_anchor_never_fails_the_append(client, na_service, monkeypatch):
    def boom(_make):
        raise RuntimeError("signer unavailable")
    monkeypatch.setattr(na_service.db, "append_store_anchor", boom)
    _decide(client)  # the decision is stored and returned
    assert na_service.db.evidence_stats()["entries"] >= 1
    events = [e["event_type"] for e in na_service.db.list_audit_events()]
    assert "evidence_anchor_failed" in events


def test_read_keys_list_anchors_and_may_ask_for_one(client, na_service):
    """An auditor's read key bounds the unanchored window itself (v1.2.0)."""
    _decide(client)
    reader = na_service._read_keypair
    listed = client.get(ANCHORS, headers=_headers(reader, "operator-read", {}, client=client, method="GET", url=ANCHORS))
    assert listed.status_code == 200 and listed.get_json()["count"] == 1
    _decide(client)
    asked = client.post(ANCHORS, json={}, headers=_headers(
        reader, "operator-read", {}, client=client, method="POST", url=ANCHORS))
    assert asked.status_code == 201
    body = {"older_than_days": 1}
    other = client.post("/admin/evidence/retention/apply", json=body, headers=_headers(
        reader, "operator-read", body, client=client, method="POST", url="/admin/evidence/retention/apply"))
    assert other.status_code == 403


def test_anchor_listing_pages(client):
    client.application.extensions["genesis_mesh_na"].anchor_interval_seconds = 0
    for _ in range(3):
        _decide(client)
        assert _post(client, ANCHORS, {}, standard=True).status_code == 201
    page = _get(client, f"{ANCHORS}?limit=2").get_json()
    assert page["count"] == 2 and page["next_after_anchor"] == 2
    rest = _get(client, f"{ANCHORS}?after_anchor=2&limit=2").get_json()
    assert [a["anchor_sequence"] for a in rest["anchors"]] == [3] and rest["next_after_anchor"] is None
    assert _get(client, f"{ANCHORS}?limit=0").status_code == 400


def test_status_reports_the_latest_anchor_and_what_follows_it(client):
    _decide(client)
    _decide(client)
    status = _get(client, "/admin/evidence/status").get_json()
    assert status["latest_anchor"]["anchor_sequence"] == 1
    assert status["unanchored_entries"] == status["last_store_sequence"] - status["latest_anchor"]["store_sequence"]
    assert status["unanchored_entries"] > 0


def test_store_verification_includes_the_anchor_chain(client):
    _activity(client)
    _post(client, ANCHORS, {}, standard=True)
    result = _get(client, "/admin/evidence/verify").get_json()
    assert result["verified"] is True, result["failures"]
    assert result["anchors"]["anchors_matched"] == 2
    assert result["anchors"]["chain"]["verified"] is True
    assert result["anchors"]["unanchored_entries"] == 0


def test_anchors_survive_retention_and_the_store_still_verifies(client, na_service, monkeypatch):
    controller = Controller(client)
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201
    second = controller.record(_decide(client), action="rotate", prior_resource=first)
    assert _submit(client, second).status_code == 201
    assert _post(client, ANCHORS, {}, standard=True).status_code == 201
    before = _anchors(client)

    import genesis_mesh.na_service.services.evidence_store as svc

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=400)

    registry = _get(client, "/admin/evidence?entry_kind=registry").get_json()["count"]
    monkeypatch.setattr(svc, "datetime", Later)
    result = _post(client, "/admin/evidence/retention/apply", {"older_than_days": 30}).get_json()
    monkeypatch.undo()
    assert result["removed_count"] == 3 + registry  # registry records are carried forward (v1.3.0)
    assert _anchors(client)[: len(before)] == before, "retention never removes or changes anchors"
    verified = _get(client, "/admin/evidence/verify").get_json()
    assert verified["verified"] is True, verified["failures"]


def test_the_anchor_table_is_append_only(client, na_service):
    _decide(client)
    db = na_service.db
    for sql in ("UPDATE evidence_anchors SET anchored_at = 'x'", "DELETE FROM evidence_anchors"):
        with pytest.raises(db.integrity_errors + db.database_errors):
            with db.conn:
                db.conn.execute(sql)
    assert len(_anchors(client)) == 1


# --- verifying exports against held anchors --------------------------------------------


def _rebuild_without(events: list[EvidenceEvent], drop_sequence: int) -> list[EvidenceEvent]:
    """What a database writer without the NA key can do: drop an entry and re-link the rest."""
    kept = [e for e in events if e.entry.store_sequence != drop_sequence]
    rebuilt: list[EvidenceEvent] = []
    prev = None
    for i, e in enumerate(kept, start=kept[0].entry.store_sequence):
        entry = e.entry.model_copy(update={
            "store_sequence": i,
            "prev_entry_digest": prev if rebuilt else e.entry.prev_entry_digest,
        })
        rebuilt.append(EvidenceEvent(entry=entry, entry_digest=entry.digest(), payload=e.payload))
        prev = entry.digest()
    return rebuilt


def _verify(events, anchors, **kw) -> EvidenceVerification:
    result = EvidenceVerification()
    check_events_against_anchors(events, anchors, result, **kw)
    return result


def _held(client) -> list[StoreAnchor]:
    return [StoreAnchor.model_validate(a) for a in _anchors(client)]


def test_an_export_matches_the_anchors_that_cover_it(client):
    _activity(client)
    _post(client, ANCHORS, {}, standard=True)
    result = _verify(_export(client), _held(client))
    assert result.verified and result.anchors["unanchored_entries"] == 0


def test_a_removed_and_relinked_entry_is_detected(client):
    _activity(client)
    _post(client, ANCHORS, {}, standard=True)
    events = _export(client)
    forged = _rebuild_without(events, drop_sequence=3)
    from genesis_mesh.trust.evidence_store import verify_evidence_events
    # Without anchors the forged chain links up again.
    plain = verify_evidence_events(forged, na_public_keys=[_na_key(client.application.extensions["genesis_mesh_na"])],
                                   executor_keys={}, contiguous=True)
    assert not any(f["reason"] in ("store_chain_break", "store_sequence_gap") for f in plain.failures)
    result = _verify(forged, _held(client))
    assert not result.verified
    assert {f["reason"] for f in result.failures} & {"anchor_mismatch", "export_ends_before_anchor"}


def test_re_anchoring_with_the_na_key_does_not_fool_held_anchors(client, na_service):
    """An operator holds the NA key and can sign new anchors; the auditor's copies differ."""
    _activity(client)
    _post(client, ANCHORS, {}, standard=True)
    held = _held(client)
    # Remove an entry after the first held anchor, which still fits the forged chain.
    forged = _rebuild_without(_export(client), drop_sequence=held[0].store_sequence + 1)
    head = forged[-1]
    fake = sign_store_anchor(StoreAnchor(
        anchor_sequence=held[-1].anchor_sequence, sovereign_id="TEST", store_sequence=head.entry.store_sequence,
        entry_digest=head.entry_digest, anchored_at=held[-1].anchored_at,
        previous_anchor_digest=held[-1].previous_anchor_digest, issued_by="test-key",
    ), na_service.signer, "test-key")
    assert _verify(forged, held[:-1] + [fake]).verified, "the re-signed anchors fit the forged chain"
    assert not _verify(forged, held).verified, "the anchors held outside the NA do not"


def test_an_export_that_stops_before_the_last_anchor_fails_unless_partial(client):
    _activity(client)
    _post(client, ANCHORS, {}, standard=True)
    events = _export(client)
    sliced = events[: len(events) // 2]
    assert not _verify(sliced, _held(client)).verified
    assert _verify(sliced, _held(client), partial=True).verified


def test_anchor_chain_failures_are_named(client, na_service):
    client.application.extensions["genesis_mesh_na"].anchor_interval_seconds = 0
    for _ in range(3):
        _decide(client)
        _post(client, ANCHORS, {}, standard=True)
    held = _held(client)
    keys = [_na_key(na_service)]
    assert verify_store_anchors(held, na_public_keys=keys, sovereign_id="TEST").verified

    def reasons(anchors, **kw):
        return {f["reason"] for f in verify_store_anchors(anchors, na_public_keys=keys, **kw).failures}

    assert reasons([held[0], held[2]]) == {"anchor_sequence_gap"}
    assert "anchor_invalid_signature" in reasons([held[0].model_copy(update={"store_sequence": 99})])
    other = generate_keypair()
    resigned = sign_store_anchor(held[1].model_copy(update={"previous_anchor_digest": "0" * 64}), other.private_key, "x")
    assert reasons([held[0], resigned]) >= {"anchor_invalid_signature", "anchor_chain_break"}
    assert reasons(held, sovereign_id="OTHER") == {"anchor_sovereign_mismatch"}
    backwards = sign_store_anchor(held[1].model_copy(update={"store_sequence": held[0].store_sequence}),
                                  na_service.signer, "test-key")
    assert reasons([held[0], backwards]) == {"anchor_not_increasing"}


# --- CLI ---------------------------------------------------------------------


class _FlaskSession:
    """Route the CLI's requests into the Flask test client."""

    def __init__(self, client):
        self.client = client

    def _call(self, method, url, **kwargs):
        parts = urlsplit(url)
        resp = self.client.open(parts.path, method=method, query_string=kwargs.get("params"),
                                json=kwargs.get("json"), headers=kwargs.get("headers"))

        class _Resp:
            status_code = resp.status_code
            text = resp.get_data(as_text=True)

            @staticmethod
            def json():
                return json.loads(resp.get_data(as_text=True))
        return _Resp()

    def request(self, method, url, timeout=None, **kwargs):
        return self._call(method, url, **kwargs)

    def post(self, url, timeout=None, **kwargs):
        return self._call("POST", url, **kwargs)


@pytest.fixture
def cli(client, na_service, tmp_path, monkeypatch):
    monkeypatch.setattr(evidence_store_ops.requests, "Session", lambda: _FlaskSession(client))
    monkeypatch.setattr(support.requests, "Session", lambda: _FlaskSession(client))
    priv, _ = save_keypair(na_service._std_keypair, str(tmp_path / "keys" / "std"))
    na_pub = tmp_path / "na.pub"
    na_pub.write_text(_na_key(na_service) + "\n", encoding="utf-8")

    def run(*args):
        return CliRunner().invoke(evidence_cli, [*args], catch_exceptions=False)

    base = ["--na", "http://na.test", "--na-public-key", str(na_pub),
            "--operator-key", str(priv), "--operator-key-id", "operator-std"]
    return run, base, tmp_path


def test_fetch_copies_new_anchors_and_never_replaces_files(client, cli):
    run, base, tmp = cli
    out = tmp / "held"
    _decide(client)
    first = run("anchors", "fetch", *base, "--out", str(out))
    assert first.exit_code == 0, first.output
    assert sorted(p.name for p in out.iterdir()) == ["anchor-0000000001.json"]
    _decide(client)
    second = run("anchors", "fetch", *base, "--out", str(out), "--anchor-now")
    assert second.exit_code == 0, second.output
    assert "1 new anchor" in second.output
    assert len(list(out.iterdir())) == 2


def test_fetch_refuses_a_rewritten_anchor_history(client, cli, na_service):
    run, base, tmp = cli
    out = tmp / "held"
    _decide(client)
    assert run("anchors", "fetch", *base, "--out", str(out)).exit_code == 0
    held = out / "anchor-0000000001.json"
    os.chmod(held, 0o644)
    data = json.loads(held.read_text(encoding="utf-8"))
    data["entry_digest"] = "f" * 64  # what the auditor holds differs from what the NA now serves
    held.write_text(json.dumps(data), encoding="utf-8")
    result = CliRunner().invoke(evidence_cli, ["anchors", "fetch", *base, "--out", str(out)])
    assert result.exit_code != 0 and "rewritten" in result.output


def test_verify_export_with_known_anchors(client, cli, tmp_path):
    run, base, tmp = cli
    _activity(client)
    out = tmp / "held"
    assert run("anchors", "fetch", *base, "--out", str(out), "--anchor-now").exit_code == 0
    export = tmp_path / "export.jsonl"
    export.write_text(_get(client, "/admin/evidence/export").get_data(as_text=True), encoding="utf-8")
    keys = tmp_path / "keys.json"
    keys.write_text(json.dumps(_get(client, "/admin/evidence/executor-keys").get_json()), encoding="utf-8")
    na_pub = str(tmp / "na.pub")
    args = ["verify-export", "--file", str(export), "--na-public-key", na_pub,
            "--executor-keys", str(keys), "--known-anchors", str(out)]
    ok = CliRunner().invoke(evidence_cli, args)
    assert ok.exit_code == 0, ok.output
    assert "Anchors    :" in ok.output and "VERIFIED" in ok.output

    forged = _rebuild_without(parse_export_lines(export.read_text(encoding="utf-8").splitlines()), 3)
    export.write_text("".join(e.to_json_line() + "\n" for e in forged), encoding="utf-8")
    bad = CliRunner().invoke(evidence_cli, args)
    assert bad.exit_code == 1 and "FAILED" in bad.output


def test_known_anchors_load_from_a_json_file(tmp_path, client):
    _decide(client)
    path = tmp_path / "anchors.json"
    path.write_text(json.dumps(_get(client, ANCHORS).get_json()), encoding="utf-8")
    assert [a.anchor_sequence for a in evidence_store_ops.load_anchors(str(path))] == [1]
    lines = tmp_path / "anchors.jsonl"
    lines.write_text("\n".join(json.dumps(a) for a in _anchors(client)), encoding="utf-8")
    assert len(evidence_store_ops.load_anchors(str(lines))) == 1


def test_verify_db_checks_the_anchors(tmp_path):
    from genesis_mesh.na_service.db import NADatabase
    from genesis_mesh.workflows.db_migration import verify_database

    path = tmp_path / "na.db"
    service = _service(db_path=str(path))
    client = _client(service)
    _activity(client)
    _post(client, ANCHORS, {}, standard=True)
    key = _na_key(service)
    report = verify_database(NADatabase(str(path)), key)
    assert report.ok, report.to_dict()
    assert report.checks["evidence_anchors"]["anchors"] == 2
    assert report.checks["evidence_anchors"]["unanchored_entries"] == 0

    # Someone with write access to the file replaces an anchor's digest.
    db = NADatabase(str(path))
    row = db.conn.execute("SELECT anchor_json FROM evidence_anchors WHERE anchor_sequence = 2").fetchone()
    forged = json.loads(row["anchor_json"])
    forged["entry_digest"] = "0" * 64
    _tamper(db, "evidence_anchors_no_update", "evidence_anchors",
            "UPDATE evidence_anchors SET anchor_json = ? WHERE anchor_sequence = 2", (json.dumps(forged),))
    report = verify_database(NADatabase(str(path)), key)
    assert not report.ok
    assert any("anchor" in f for f in report.failures)


# --- review fixes: both ends of an export, refusals, fetch robustness -------------------


def test_the_first_anchor_omits_its_absent_previous_digest(client):
    _decide(client)
    first = _anchors(client)[0]
    assert "previous_anchor_digest" not in first
    assert "previous_anchor_digest" not in StoreAnchor.model_validate(first).to_canonical_json()


def test_removing_the_oldest_records_is_detected(client):
    _activity(client, 3)
    _post(client, ANCHORS, {}, standard=True)
    held = _held(client)
    events = _export(client)
    cut = [e for e in events if e.entry.store_sequence > held[0].store_sequence + 1]
    result = _verify(cut, held)
    assert not result.verified
    assert "export_not_linked_to_anchors" in {f["reason"] for f in result.failures}


def test_a_slice_linked_to_a_held_anchor_verifies_and_an_unlinked_one_needs_partial(client):
    _activity(client, 3)
    _post(client, ANCHORS, {}, standard=True)
    held = _held(client)
    events = _export(client)
    start = held[0].store_sequence
    linked = [e for e in events if e.entry.store_sequence > start]
    result = _verify(linked, held)
    assert result.verified and result.anchors["linked_start"] is True
    unlinked = [e for e in events if e.entry.store_sequence > start + 1]
    assert not _verify(unlinked, held).verified
    assert _verify(unlinked, held, partial=True).verified
    forged = _rebuild_without(events, drop_sequence=start + 1)
    after = [e for e in forged if e.entry.store_sequence > start]
    assert not _verify(after, held).verified  # it links, but stops before the newest anchor
    detached = [e.model_copy(update={"entry": e.entry.model_copy(update={"prev_entry_digest": "0" * 64})})
                if e.entry.store_sequence == start + 1 else e for e in linked]
    assert "anchor_mismatch" in {f["reason"] for f in _verify(detached, held).failures}


def test_an_export_after_retention_is_linked_by_its_checkpoint(client, monkeypatch):
    controller = Controller(client)
    first = controller.record(_decide(client))
    assert _submit(client, first).status_code == 201
    second = controller.record(_decide(client), action="rotate", prior_resource=first)
    assert _submit(client, second).status_code == 201
    assert _post(client, ANCHORS, {}, standard=True).status_code == 201

    import genesis_mesh.na_service.services.evidence_store as svc

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=400)

    monkeypatch.setattr(svc, "datetime", Later)
    assert _post(client, "/admin/evidence/retention/apply", {"older_than_days": 30}).status_code == 200
    monkeypatch.undo()
    result = _verify(_export(client), _held(client))
    assert result.verified, result.failures
    assert result.anchors["linked_start"] is True and result.anchors["anchors_before_export"] >= 1


def test_the_nas_own_verification_detects_deleted_old_entries(client, na_service):
    _activity(client, 3)
    _post(client, ANCHORS, {}, standard=True)
    db = na_service.db
    first_anchored = _held(client)[0].store_sequence
    _tamper(db, "evidence_entries_retention_only_delete", "evidence_entries",
            "DELETE FROM evidence_entries WHERE store_sequence <= ?", (first_anchored + 1,))
    result = _get(client, "/admin/evidence/verify").get_json()
    assert result["verified"] is False
    assert "export_not_linked_to_anchors" in {f["reason"] for f in result["failures"]}


def test_the_na_refuses_to_anchor_a_rewritten_store(client, na_service):
    """A database writer without the NA key cannot get the NA to sign over a rewrite."""
    _activity(client, 2)
    _post(client, ANCHORS, {}, standard=True)
    _decide(client)  # recorded after the last anchor (the interval holds the automatic one)
    db = na_service.db
    head, _ = db.store_head()
    row = db.conn.execute("SELECT payload_json FROM evidence_entries WHERE store_sequence = ?", (head,)).fetchone()
    payload = json.loads(row["payload_json"])
    payload["tampered"] = True
    _tamper(db, "evidence_entries_no_update", "evidence_entries",
            "UPDATE evidence_entries SET payload_json = ? WHERE store_sequence = ?", (json.dumps(payload), head))
    refused = _post(client, ANCHORS, {}, standard=True)
    assert refused.status_code == 409
    assert refused.get_json()["error"]["code"] == "evidence_anchor_refused"
    assert "evidence_anchor_refused" in [e["event_type"] for e in db.list_audit_events()]


def test_a_far_future_anchor_stops_anchoring_instead_of_freezing_time(client, monkeypatch):
    import genesis_mesh.na_service.services.evidence_store as svc

    class Ahead(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=365)

    client.application.extensions["genesis_mesh_na"].anchor_interval_seconds = 0
    _decide(client)
    monkeypatch.setattr(svc, "datetime", Ahead)
    assert _post(client, ANCHORS, {}, standard=True).status_code == 201
    monkeypatch.undo()
    _decide(client)
    refused = _post(client, ANCHORS, {}, standard=True)
    assert refused.status_code == 409
    assert "ahead of this instance" in refused.get_json()["error"]["message"]


def test_fetch_refills_a_missing_file_and_pages(client, cli, monkeypatch):
    run, base, tmp = cli
    out = tmp / "held"
    client.application.extensions["genesis_mesh_na"].anchor_interval_seconds = 0
    for _ in range(3):
        _decide(client)
        _post(client, ANCHORS, {}, standard=True)
    monkeypatch.setattr(evidence_store_ops, "PAGE", 1)
    assert run("anchors", "fetch", *base, "--out", str(out)).exit_code == 0
    middle = out / "anchor-0000000002.json"
    os.chmod(middle, 0o644)
    middle.unlink()
    again = run("anchors", "fetch", *base, "--out", str(out))
    assert again.exit_code == 0 and "refilled" in again.output
    assert middle.exists()


def test_fetch_fails_when_the_na_no_longer_serves_a_held_anchor(client, cli, na_service):
    run, base, tmp = cli
    out = tmp / "held"
    _decide(client)
    assert run("anchors", "fetch", *base, "--out", str(out)).exit_code == 0
    db = na_service.db
    _tamper(db, "evidence_anchors_no_delete", "evidence_anchors", "DELETE FROM evidence_anchors")
    result = CliRunner().invoke(evidence_cli, ["anchors", "fetch", *base, "--out", str(out)])
    assert result.exit_code != 0 and "no longer serves anchor 1" in result.output


def test_fetch_refuses_a_listing_that_does_not_advance(client, cli, monkeypatch):
    run, base, tmp = cli
    _decide(client)
    _decide(client)
    _post(client, ANCHORS, {}, standard=True)
    monkeypatch.setattr(evidence_store_ops, "PAGE", 1)
    real = evidence_store_ops._request_json

    def stuck(*args, **kwargs):
        page = real(*args, **kwargs)
        page["next_after_anchor"] = 0
        return page
    monkeypatch.setattr(evidence_store_ops, "_request_json", stuck)
    result = CliRunner().invoke(evidence_cli, ["anchors", "fetch", *base, "--out", str(tmp / "held")])
    assert result.exit_code != 0
    assert "out of order" in result.output or "does not advance" in result.output
    assert not list((tmp / "held").glob("anchor-*.json"))


def test_writing_an_anchor_twice_is_accepted_and_a_different_one_refused(tmp_path, client):
    _decide(client)
    anchor = _held(client)[0]
    evidence_store_ops._write_anchor(tmp_path, anchor)
    evidence_store_ops._write_anchor(tmp_path, anchor)
    other = anchor.model_copy(update={"entry_digest": "e" * 64})
    with pytest.raises(Exception, match="different anchor"):
        evidence_store_ops._write_anchor(tmp_path, other)
    assert not list(tmp_path.glob(".*.tmp"))


def test_verify_db_without_the_key_still_checks_the_anchor_chain(tmp_path):
    from genesis_mesh.na_service.db import NADatabase
    from genesis_mesh.workflows.db_migration import verify_database

    path = tmp_path / "na.db"
    service = _service(db_path=str(path))
    client = _client(service)
    _activity(client)
    _post(client, ANCHORS, {}, standard=True)
    report = verify_database(NADatabase(str(path)))
    assert report.ok, report.to_dict()
    assert report.checks["evidence_anchors"]["chain"]["checked_anchors"] == 2
