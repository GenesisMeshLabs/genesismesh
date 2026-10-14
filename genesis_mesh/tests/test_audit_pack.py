"""Audit packs, independent verification, completeness and archive before prune (v1.5.0, Stage 4).

Each test is one of the plan's success criteria, or one of its refusals: a
pack verifies offline from the root key and the anchors an auditor holds; a
removed record, a rewritten and re-anchored range and a tampered file each
fail by name; the completeness check reports a change the store does not
record; archiving never prunes past what it read back; a read key produces
a pack, and every route above the read tier refuses it.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from genesis_mesh.crypto import save_keypair, sign_model
from genesis_mesh.models.audit_pack import (
    CITED_FILE,
    ENTRIES_FILE,
    MANIFEST_FILE,
    AuditPackManifest,
    PackFile,
)
from genesis_mesh.models.evidence_store import EvidenceEvent, StoreAnchor
from genesis_mesh.trust.evidence_store import sign_store_anchor
from genesis_mesh.workflows.audit_pack import (
    Change,
    check_completeness,
    parse_changes,
    verify_audit_pack,
)

from .succession_support import Network, public_b64
from .test_attestation_boundary import _issue
from .test_evidence_store import SECRET, VENDOR, Controller, _client, _code, _decide, _submit
from .test_na_boundary_policy import _get, _headers, _post
from .test_out_of_band import CAPABILITY, Clock, Observer, _observe


@pytest.fixture
def net(tmp_path):
    return Network(tmp_path)


def _read(client, method: str, url: str, body: dict | None = None):
    """A request signed by the read-tier key (an auditor's)."""
    service = client.application.extensions["genesis_mesh_na"]
    body = body if body is not None else {}
    headers = _headers(service._read_keypair, "operator-read", body, client=client, method=method, url=url)
    return client.open(url, method=method, json=body if method != "GET" else None, headers=headers)


def _anchor(client) -> dict:
    resp = _read(client, "POST", "/admin/evidence/anchors", {})
    assert resp.status_code in (200, 201), resp.get_json()
    return resp.get_json()["anchor"]


def _held(client) -> list[StoreAnchor]:
    """The anchors an auditor copied out (anchors fetch)."""
    page = _read(client, "GET", "/admin/evidence/anchors?limit=1000").get_json()
    return [StoreAnchor.model_validate(a) for a in page["anchors"]]


def _pack(client, **body: Any) -> dict[str, bytes]:
    resp = _read(client, "POST", "/admin/evidence/audit-pack", body)
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    files = {path: text.encode("utf-8") for path, text in data["files"].items()}
    files[MANIFEST_FILE] = AuditPackManifest.model_validate(data["manifest"]).file_bytes()
    return files


def _verify(net, files, held, **kwargs):
    return verify_audit_pack(files, root_public_key=public_b64(net.root), held_anchors=held, **kwargs)


def _reasons(result) -> set[str]:
    return {f["reason"] for f in result.failures}


def _history(net) -> tuple[Any, Any, Controller, Observer]:
    """An NA with the out-of-band records on, and some history: decisions, a resource chain, an
    observation judged, an anchor after each step."""
    service = net.start(evidence_out_of_band="on")
    client = _client(service)
    controller = Controller(client)
    observer = Observer(client)
    attestation = _issue(client, capabilities=[CAPABILITY], subject=VENDOR)["attestation_id"]
    decision = _decide(client, attestation_id=attestation)
    first = controller.record(decision, params={"version_id": "v1"})
    assert _submit(client, first).status_code == 201
    _anchor(client)
    second = controller.record(decision, action="rotate", prior=first, sequence_no=2, prior_resource=first,
                               params={"version_id": "v2"})
    assert _submit(client, second).status_code == 201
    clock = Clock(datetime.now(timezone.utc))
    assert _observe(client, observer.observe(clock, version_id="v2", event_id="evt-v2")).status_code == 201
    _anchor(client)
    setattr(client, "_records", (first, second))
    return service, client, controller, observer


def _resign(net, files: dict[str, bytes], changed: dict[str, bytes]) -> dict[str, bytes]:
    """What an operator holding the NA key can do: change files and sign a new manifest over them."""
    out = {**files, **changed}
    manifest = AuditPackManifest.model_validate_json(files[MANIFEST_FILE])
    manifest = manifest.model_copy(update={"signature": None, "files": [
        PackFile(path=p, sha256=hashlib.sha256(b).hexdigest(), bytes=len(b))
        for p, b in sorted(out.items()) if p != MANIFEST_FILE]})
    manifest = manifest.model_copy(update={"signature": sign_model(manifest, net.na_keys[-1], "na-1")})
    out[MANIFEST_FILE] = manifest.file_bytes()
    return out


def _lines(data: bytes) -> list[dict]:
    return [json.loads(line) for line in data.decode().splitlines() if line]


def _jsonl(items: list[dict]) -> bytes:
    return "".join(json.dumps(i, sort_keys=True, separators=(",", ":")) + "\n" for i in items).encode()


# ---------------------------------------------------------------------------
# A pack verifies offline; a read key produces it
# ---------------------------------------------------------------------------


def test_a_read_key_produces_a_pack_that_verifies_offline_from_the_root_key_and_held_anchors(net, tmp_path,
                                                                                            monkeypatch):
    """Success criteria 2 and 6: the pack, the root key and the held anchors are enough."""
    from genesis_mesh.cli import audit_ops, support
    from genesis_mesh.cli.main import cli

    from .test_evidence_anchors import _FlaskSession

    service, client, _, _ = _history(net)
    monkeypatch.setattr(audit_ops.requests, "Session", lambda: _FlaskSession(client))
    monkeypatch.setattr(support.requests, "Session", lambda: _FlaskSession(client))
    reader, _ = save_keypair(net.reader, str(tmp_path / "reader"))
    runner = CliRunner()
    written = runner.invoke(cli, ["audit", "pack", "--na", "http://na.test", "--out", str(tmp_path / "pack"),
                                  "--operator-key", str(reader), "--operator-key-id", "operator-read"])
    assert written.exit_code == 0, written.output
    names = sorted(p.relative_to(tmp_path / "pack").as_posix() for p in (tmp_path / "pack").rglob("*") if p.is_file())
    assert MANIFEST_FILE in names and "report.md" in names and "keys/na-key-history.json" in names
    report = (tmp_path / "pack" / "report.md").read_text(encoding="utf-8")
    assert "## Changes" in report and "prior_decision" in report

    # The auditor holds the root public key and its copy of the anchors; nothing else.
    root = tmp_path / "root.pub"
    root.write_text(public_b64(net.root) + "\n", encoding="utf-8")
    anchors = tmp_path / "anchors.json"
    anchors.write_text(json.dumps([a.to_wire() for a in _held(client)]), encoding="utf-8")
    service.db.close()  # the NA is gone

    # No network at all: any connection the verifier tried would fail the test.
    import socket

    def no_network(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("audit verify tried to reach the network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    verified = runner.invoke(cli, ["audit", "verify", str(tmp_path / "pack"), "--anchor", str(root),
                                   "--known-anchors", str(anchors), "--format", "json"])
    assert verified.exit_code == 0, verified.output
    body = json.loads(verified.output)
    assert body["verified"] is True and body["check_differences"] == [] and "report_differences" not in body
    assert body["counts"]["executions"] == 2 and body["counts"]["observations"] == 1

    # Another root key proves nothing about this NA.
    other = tmp_path / "other.pub"
    other.write_text(public_b64(net.na_keys[0]) + "\n", encoding="utf-8")
    refused = runner.invoke(cli, ["audit", "verify", str(tmp_path / "pack"), "--anchor", str(other),
                                  "--known-anchors", str(anchors)])
    assert refused.exit_code == 1 and "genesis_root_mismatch" in refused.output


def test_a_pack_that_starts_mid_store_carries_the_heads_and_records_its_range_cites(net):
    """Review finding: an export starting mid-store failed resource chains and passed executions
    whose decisions were outside it. A pack carries the heads and the decisions."""
    service, client, controller, _ = _history(net)
    first, second = client._records
    held = _held(client)
    # The range after the first anchor: the second execution, its observation and judgement.
    files = _pack(client, from_sequence=held[-2].store_sequence + 1)
    manifest = AuditPackManifest.model_validate_json(files[MANIFEST_FILE])
    assert manifest.start_anchor_sequence == held[-2].anchor_sequence
    assert manifest.end_anchor_sequence == held[-1].anchor_sequence
    cited = {(e["entry"]["entry_kind"], e["entry"].get("evidence_id") or e["entry"].get("decision_id"))
             for e in _lines(files[CITED_FILE])}
    assert ("execution", first.evidence_id) in cited, "the head the chains continue from"
    assert ("decision", second.decision_id) in cited, "the decision the range's execution rests on"
    result = _verify(net, files, held)
    assert result.verified, result.failures

    # Without the head or the decision, the chains and the citation fail by name.
    def without(kind_id: tuple[str, str]) -> dict[str, bytes]:
        kept = [e for e in _lines(files[CITED_FILE])
                if (e["entry"]["entry_kind"], e["entry"].get("evidence_id") or e["entry"].get("decision_id")) != kind_id]
        return _resign(net, files, {CITED_FILE: _jsonl(kept)})

    no_head = _reasons(_verify(net, without(("execution", first.evidence_id)), held))
    assert {"resource_chain_break", "evidence_chain_break"} <= no_head
    assert "cited_record_missing" in _reasons(_verify(net, without(("decision", second.decision_id)), held))


# ---------------------------------------------------------------------------
# Tampering fails by name
# ---------------------------------------------------------------------------


def test_a_tampered_file_a_removed_record_and_a_rewritten_re_anchored_range_each_fail(net):
    """Success criterion 2."""
    service, client, _, _ = _history(net)
    held = _held(client)
    files = _pack(client)
    assert _verify(net, files, held).verified

    # A tampered file: its digest no longer matches the manifest.
    entries = bytearray(files[ENTRIES_FILE])
    entries[entries.index(b"rotate")] = ord("R")
    assert "manifest_digest_mismatch" in _reasons(_verify(net, {**files, ENTRIES_FILE: bytes(entries)}, held))

    # A removed record, by someone holding the NA key who signs a new manifest.
    lines = _lines(files[ENTRIES_FILE])
    executions = [i for i, e in enumerate(lines) if e["entry"]["entry_kind"] == "execution"]
    removed = [e for i, e in enumerate(lines) if i != executions[-1]]
    gone = _reasons(_verify(net, _resign(net, files, {ENTRIES_FILE: _jsonl(removed)}), held))
    assert {"store_sequence_gap", "pack_range_mismatch"} & gone

    # A rewritten range: the record removed, the chain re-linked and re-anchored with the NA key.
    rebuilt, prev = [], None
    for position, line in enumerate(removed, start=lines[0]["entry"]["store_sequence"]):
        envelope = {**line["entry"], "store_sequence": position, "prev_entry_digest": prev}
        digest = hashlib.sha256(json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        rebuilt.append({**line, "entry": envelope, "entry_digest": digest})
        prev = digest
    anchors = [StoreAnchor.model_validate(a) for a in _lines(files["anchors.jsonl"])]
    end = anchors[-1]
    forged = sign_store_anchor(end.model_copy(update={
        "store_sequence": rebuilt[-1]["entry"]["store_sequence"], "entry_digest": prev, "signature": None}),
        net.na_keys[-1], "na-1")
    manifest = AuditPackManifest.model_validate_json(files[MANIFEST_FILE])
    changed = _resign(net, files, {ENTRIES_FILE: _jsonl(rebuilt),
                                   "anchors.jsonl": _jsonl([a.to_wire() for a in anchors[:-1]] + [forged.to_wire()])})
    relabel = AuditPackManifest.model_validate_json(changed[MANIFEST_FILE]).model_copy(update={
        "through_sequence": rebuilt[-1]["entry"]["store_sequence"], "signature": None})
    relabel = relabel.model_copy(update={"signature": sign_model(relabel, net.na_keys[-1], "na-1")})
    changed[MANIFEST_FILE] = relabel.file_bytes()
    assert manifest.end_anchor_sequence == forged.anchor_sequence
    reasons = _reasons(_verify(net, changed, held))
    assert "anchor_mismatch" in reasons, reasons


def test_without_held_anchors_a_pack_proves_only_what_it_holds(net):
    service, client, _, _ = _history(net)
    result = _verify(net, _pack(client), None)
    assert result.verified and [w["reason"] for w in result.warnings] == ["no_held_anchors"]
    # An end anchor the auditor does not hold proves nothing about removal.
    held = _held(client)[:-1]
    assert "pack_end_anchor_not_held" in _reasons(_verify(net, _pack(client), held))


# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------


def test_the_completeness_check_reports_a_removed_record_and_an_unmatched_outside_change(net, tmp_path):
    """Success criterion 4: changes from an outside log, matched by source event and by time."""
    service, client, _, _ = _history(net)
    first, second = client._records
    files = _pack(client)
    held = _held(client)
    log = [
        {"source": "cloud-activity-log", "source_event_id": "evt-v2", "resource_id": SECRET, "action": "rotate",
         "changed_at": second.executed_at.isoformat(), "actor": "principal-7f3a"},
        {"source": "", "source_event_id": "", "resource_id": SECRET, "action": "create",
         "changed_at": first.executed_at.isoformat(), "actor": "controller"},
        {"source": "cloud-activity-log", "source_event_id": "evt-unknown", "resource_id": SECRET, "action": "update",
         "changed_at": second.executed_at.isoformat(), "actor": "someone-else"},
    ]
    csv_text = "source,source_event_id,resource_id,action,changed_at,actor\n" + "".join(
        ",".join(str(row[c]) for c in ("source", "source_event_id", "resource_id", "action", "changed_at", "actor"))
        + "\n" for row in log)
    changes = parse_changes(csv_text, csv_format=True)
    assert parse_changes(json.dumps({"changes": log}), csv_format=False)[0].source_event_id == "evt-v2"
    result = _verify(net, files, held, changes=changes)
    report = result.completeness
    assert report is not None
    assert [(p["change"], p["matched_by"]) for p in report["pairs"]] == [
        (1, "source_event_id"), (2, "resource_action_time")]
    assert [c["source_event_id"] for c in report["unmatched_changes"]] == ["evt-unknown"]
    assert not result.verified and "change_unmatched" in _reasons(result)

    # A deliberately removed record: the change has no record left in the pack (neither the
    # controller's execution evidence nor the observation of it).
    lines = _lines(files[ENTRIES_FILE])
    removed = [e for e in lines if e["entry"]["entry_kind"] != "observation"
               and e["entry"].get("evidence_id") != second.evidence_id]
    entries = [EvidenceEvent.received(e) for e in removed]
    gone = check_completeness(changes[:1], entries, period=(datetime.now(timezone.utc) - timedelta(hours=1),
                                                            datetime.now(timezone.utc) + timedelta(hours=1)))
    assert [c["source_event_id"] for c in gone["unmatched_changes"]] == ["evt-v2"]
    # A change dated long before the pack's period is outside it, not missing.
    old = Change(index=9, resource_id=SECRET, action="delete",
                 changed_at=datetime.now(timezone.utc) - timedelta(days=400))
    far = check_completeness([old], entries, period=(datetime.now(timezone.utc) - timedelta(hours=1),
                                                     datetime.now(timezone.utc)))
    assert far["outside_period"] and not far["unmatched_changes"]


# ---------------------------------------------------------------------------
# Archive before prune
# ---------------------------------------------------------------------------


def _cli(client, net, tmp_path, monkeypatch):
    from genesis_mesh.cli import audit_ops, support
    from genesis_mesh.cli.main import cli

    from .test_evidence_anchors import _FlaskSession

    monkeypatch.setattr(audit_ops.requests, "Session", lambda: _FlaskSession(client))
    monkeypatch.setattr(support.requests, "Session", lambda: _FlaskSession(client))
    operator, _ = save_keypair(net.privileged, str(tmp_path / "op"))

    def run(*args: str):
        return CliRunner().invoke(cli, ["audit", *args, "--na", "http://na.test", "--operator-key", str(operator),
                                        "--operator-key-id", "operator-test"])

    return run


def _later(monkeypatch) -> None:
    import genesis_mesh.na_service.services.evidence_store as svc

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return datetime.now(tz) + timedelta(days=400)

    monkeypatch.setattr(svc, "datetime", Later)


def _entries(client) -> list[dict]:
    return _get(client, "/admin/evidence?limit=1000").get_json()["entries"]


def test_retention_refuses_to_prune_what_no_archive_covers_by_default(net, monkeypatch):
    """Success criterion 5, second half: NA_RETENTION_REQUIRE_ARCHIVE is on by default."""
    service, client, _, _ = _history(net)
    assert service.retention_require_archive is True
    before = len(_entries(client))
    with monkeypatch.context() as patch:
        _later(patch)
        result = _post(client, "/admin/evidence/retention/apply", {"older_than_days": 30}).get_json()
    assert result["removed_count"] == 0 and result["held_back"]["reason"] == "not_archived"
    assert len(_entries(client)) == before
    assert _code(_post(client, "/admin/evidence/retention/apply", {})) == "invalid_retention"


def test_audit_archive_writes_reads_back_records_and_prunes_through_the_archive(net, tmp_path, monkeypatch):
    """Success criterion 5: written to storage, read back, recorded (entry kind archive), pruned."""
    service, client, _, _ = _history(net)
    run = _cli(client, net, tmp_path, monkeypatch)
    _later(monkeypatch)
    archived = run("archive", "--to", str(tmp_path / "vault"))
    monkeypatch.undo()
    assert archived.exit_code == 0, archived.output
    listing = _get(client, "/admin/evidence/archives").get_json()
    [record] = listing["archives"]
    end = _held(client)[-1]
    assert record["through_sequence"] == end.store_sequence
    assert listing["archived_through_sequence"] == end.store_sequence
    pack_dir = tmp_path / "vault" / record["pack_id"]
    assert (pack_dir / MANIFEST_FILE).is_file()
    assert hashlib.sha256((pack_dir / MANIFEST_FILE).read_bytes()).hexdigest() == record["manifest_sha256"]
    kinds = [e["entry"]["entry_kind"] for e in _entries(client)]
    assert "retention_checkpoint" in kinds and "archive" in kinds
    # Never pruned: anchors, the registry and the archive record itself are kept.
    assert "registry" in kinds and len(_held(client)) >= 2
    verified = _get(client, "/admin/evidence/verify").get_json()
    assert verified["verified"] is True, verified
    # The archived pack still verifies offline after the prune.
    from genesis_mesh.workflows.audit_pack import read_pack_dir
    assert _verify(net, read_pack_dir(pack_dir), _held(client)).verified


@pytest.mark.parametrize("failure", ["write", "read_back"])
def test_audit_archive_records_and_prunes_nothing_when_the_write_or_the_read_back_fails(
        net, tmp_path, monkeypatch, failure):
    """Success criterion 5: tested by failing the write and the read-back."""
    from genesis_mesh.cli import audit_ops

    service, client, _, _ = _history(net)
    run = _cli(client, net, tmp_path, monkeypatch)
    before = _entries(client)
    if failure == "write":
        def broken_write(directory: Path, files: dict[str, bytes]) -> None:
            raise OSError("no space left on device")
        monkeypatch.setattr(audit_ops, "write_pack", broken_write)
    else:
        real = audit_ops.read_pack_dir

        def corrupted(directory: Path) -> dict[str, bytes]:
            files = real(directory)
            files[ENTRIES_FILE] = files[ENTRIES_FILE][:-10]
            return files
        monkeypatch.setattr(audit_ops, "read_pack_dir", corrupted)
    result = run("archive", "--to", str(tmp_path / "vault"))
    assert result.exit_code != 0 and "Nothing was recorded or pruned" in result.output.replace("nothing", "Nothing")
    assert _get(client, "/admin/evidence/archives").get_json()["archives"] == []
    assert _entries(client) == before


def test_an_archive_must_be_this_nas_pack_and_continue_the_archives(net):
    service, client, _, _ = _history(net)
    held = _held(client)
    late = _pack(client, from_sequence=held[-2].store_sequence + 1)
    manifest = json.loads(late[MANIFEST_FILE])
    gap = _post(client, "/admin/evidence/archives", {"manifest": manifest, "location": "vault://x"})
    assert gap.status_code == 409 and _code(gap) == "archive_not_contiguous"
    forged = {**manifest, "pack_id": "forged"}
    bad = _post(client, "/admin/evidence/archives", {"manifest": forged, "location": "vault://x"})
    assert bad.status_code == 422 and _code(bad) == "archive_manifest_invalid"
    whole = json.loads(_pack(client)[MANIFEST_FILE])
    reader = _read(client, "POST", "/admin/evidence/archives", {"manifest": whole, "location": "vault://y"})
    assert reader.status_code == 403 and _code(reader) == "insufficient_operator_tier"
    ok = _post(client, "/admin/evidence/archives", {"manifest": whole, "location": "vault://y"})
    assert ok.status_code == 201, ok.get_json()
    again = _post(client, "/admin/evidence/archives", {"manifest": whole, "location": "vault://y"})
    assert again.status_code == 200 and again.get_json()["status"] == "duplicate"


def test_retention_never_prunes_past_the_archive_or_the_sequence_asked_for(net, monkeypatch):
    service, client, _, _ = _history(net)
    held = _held(client)
    # Archive only the first anchored range.
    first = json.loads(_pack(client, until_sequence=held[-2].store_sequence)[MANIFEST_FILE])
    assert _post(client, "/admin/evidence/archives", {"manifest": first, "location": "vault/1"}).status_code == 201
    with monkeypatch.context() as patch:
        _later(patch)
        result = _post(client, "/admin/evidence/retention/apply", {"older_than_days": 30}).get_json()
    assert 0 < result["checkpoint"]["removed_through_sequence"] <= held[-2].store_sequence
    assert result["held_back"]["reason"] == "not_archived"


# ---------------------------------------------------------------------------
# Read access
# ---------------------------------------------------------------------------

#: Admin routes a read-tier key may call (v1.5.0: read-tier evidence access; v1.2.0 anchors;
#: v1.3.0 and v1.4.0 views).
READ_ROUTES = {
    ("GET", "/admin/evidence"), ("GET", "/admin/evidence/status"), ("GET", "/admin/evidence/verify"),
    ("GET", "/admin/evidence/resources/<path:resource_id>"), ("GET", "/admin/evidence/resource-heads/<path:resource_id>"),
    ("GET", "/admin/evidence/vendors/<vendor_id>"), ("GET", "/admin/evidence/export"),
    ("GET", "/admin/evidence/executor-keys"), ("GET", "/admin/evidence/anchors"), ("POST", "/admin/evidence/anchors"),
    ("POST", "/admin/evidence/audit-pack"), ("GET", "/admin/evidence/archives"),
    ("GET", "/admin/evidence/changes/<path:resource_id>"), ("GET", "/admin/evidence/operator-holders"),
    ("GET", "/admin/evidence/remediations"), ("GET", "/admin/evidence/remediations/<subject_id>"),
    ("GET", "/admin/evidence/reviews/<review_id>"),
    # v1.6.0: grants, read as the rest of the store is.
    ("GET", "/admin/grants"), ("GET", "/admin/grants/<grant_id>"), ("GET", "/admin/grants/<grant_id>/uses"),
    # v1.7.0: the edge nodes view.
    ("GET", "/admin/edge-nodes"),
}


def test_every_route_above_the_read_tier_refuses_a_read_key(net):
    """Success criterion 6: 403 insufficient_operator_tier for every route that needs the standard
    tier or above; the read routes serve it."""
    import re

    service = net.start(evidence_out_of_band="on", evidence_remediation="on")
    client = _client(service)
    _issue(client, capabilities=[CAPABILITY], subject=VENDOR)
    _anchor(client)
    seen_read: set[tuple[str, str]] = set()
    refused: list[str] = []
    for rule in service.app.url_map.iter_rules():
        if not rule.rule.startswith("/admin"):
            continue
        url = re.sub(r"<(?:[a-z]+:)?\w+>", "x", rule.rule)
        for method in sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}):
            resp = _read(client, method, url, {} if method != "GET" else None)
            code = (resp.get_json() or {}).get("error", {}).get("code") if resp.is_json else None
            if (method, rule.rule) in READ_ROUTES:
                seen_read.add((method, rule.rule))
                assert resp.status_code not in (401, 403), (method, rule.rule, resp.get_json())
            elif resp.status_code != 403 or code != "insufficient_operator_tier":
                refused.append(f"{method} {rule.rule}: {resp.status_code} {code}")
    assert refused == []
    assert seen_read == READ_ROUTES


# ---------------------------------------------------------------------------
# The frozen 1.5.0 pack
# ---------------------------------------------------------------------------


def test_the_frozen_1_5_0_pack_verifies(tmp_path):
    """Success criterion 3: a pack written by 1.5.0 is committed and verified by every later release,
    as an auditor would, with the CLI."""
    from genesis_mesh.cli.main import cli

    fixture = Path(__file__).resolve().parents[2] / "conformance" / "fixtures" / "audit-pack-1.5.0"
    result = CliRunner().invoke(cli, ["audit", "verify", str(fixture / "pack"), "--anchor", str(fixture / "root.pub"),
                                      "--known-anchors", str(fixture / "anchors.json"), "--format", "json"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert body["verified"] is True and body["check_differences"] == [] and "report_differences" not in body
    assert body["counts"]["key_successions"] == 1 and len(body["keys"]) == 2


def test_a_store_without_registry_records_needs_the_auditors_executor_keys(net, tmp_path):
    """Keys inside a pack prove nothing alone: without signed registry records (the out-of-band records
    off), the executor keys come from the auditor."""
    from genesis_mesh.trust.evidence_store import ExecutorKey

    service = net.start()
    client = _client(service)
    controller = Controller(client)
    assert _submit(client, controller.record(_decide(client))).status_code == 201
    _anchor(client)
    files = _pack(client)
    assert json.loads(files["checks.json"])["verified"] is True, "the NA checks with its own key table"
    held = _held(client)
    assert "invalid_signature" in _reasons(_verify(net, files, held))
    keys = {controller.key_id: ExecutorKey(controller.key_id, controller.public_key, controller.sovereign)}
    assert _verify(net, files, held, executor_keys=keys).verified
