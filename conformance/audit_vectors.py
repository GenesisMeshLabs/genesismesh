"""The ``audit`` conformance suite (v1.5.0): key history, key windows, exports across a succession,
packs and the completeness check.

``audit_vectors()`` builds every vector from the deterministic world
(``audit_world``) and fills ``expected`` with ``evaluate``, the Python
reference's verdict; the runner calls ``evaluate`` again on each vector's
input and compares. Reason codes are the contract: every verifier must name
the same ones for the same input.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from audit_world import (
    KEYS,
    RESOURCE,
    SOVEREIGN,
    SUCCESSION_AT,
    T0,
    build_pack,
    build_world,
    canonical,
    frozen_pack,
    pub,
    sha256,
    uid,
)


def _history(inp: dict[str, Any]) -> Any:
    from genesis_mesh.trust.key_succession import verify_key_history

    result = verify_key_history(inp["genesis"], inp["successions"], inp["root_public_key"])
    assert result.history is not None, result.failures
    return result.history


def _when(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def evaluate(vector: dict[str, Any]) -> dict[str, Any]:
    """What the Python reference makes of one vector's input (the runner compares it with ``expected``)."""
    from genesis_mesh.models.canonical_registry import received_canonical
    from genesis_mesh.models.context import BoundaryDecision
    from genesis_mesh.models.evidence_store import EvidenceEvent, StoreAnchor
    from genesis_mesh.trust.context import verify_boundary_decision
    from genesis_mesh.trust.evidence_store import (
        ExecutorKey,
        parse_export_lines,
        verify_evidence_events,
        verify_store_anchors,
    )
    from genesis_mesh.trust.key_succession import verify_key_history
    from genesis_mesh.workflows.audit_pack import Change, check_completeness, verify_audit_pack

    kind, inp = vector["kind"], vector.get("input", {})

    def executor_keys(rows: list[dict[str, Any]]) -> dict[str, Any]:
        # v1.5.0 review fixes: a key may be placed in the store (registered_sequence and so on).
        return {r["key_id"]: ExecutorKey(
            key_id=r["key_id"], public_key=r["public_key"], executor_sovereign_id=r["executor_sovereign_id"],
            role=r["role"], resource_prefix=r.get("resource_prefix"),
            registered_sequence=r.get("registered_sequence"), retired_sequence=r.get("retired_sequence"),
            registered_at=_when(r["registered_at_time"]) if r.get("registered_at_time") else None,
            retired_at=_when(r["retired_at_time"]) if r.get("retired_at_time") else None) for r in rows}

    def changes_of(rows: list[dict[str, Any]]) -> list[Any]:
        return [Change(index=i, resource_id=c["resource_id"], action=c["action"], changed_at=_when(c["changed_at"]),
                       source=c.get("source"), source_event_id=c.get("source_event_id"), actor=c.get("actor"))
                for i, c in enumerate(rows, start=1)]

    if kind == "canonical_form":
        body = received_canonical(vector["model"], vector["record"])
        return {"canonical": body, "digest": hashlib.sha256(body.encode()).hexdigest()}
    if kind == "key_history":
        result = verify_key_history(inp["genesis"], inp["successions"], inp["root_public_key"])
        return {"verified": result.verified,
                "failures": [{"key_sequence": f["key_sequence"], "reason": f["reason"]} for f in result.failures],
                "keys": [k.to_dict() for k in result.history.keys] if result.history else []}
    if kind == "key_at":
        return {"keys": _history(inp).keys_at(_when(inp["at"]))}
    if kind == "verify_export":
        events = parse_export_lines(inp["lines"].split("\n"))
        result = verify_evidence_events(events, na_public_keys=_history(inp),
                                        executor_keys=executor_keys(inp["executor_keys"]))
        return {"failures": [{"store_sequence": f["store_sequence"], "reason": f["reason"]} for f in result.failures],
                "warnings": [{"store_sequence": w["store_sequence"], "reason": w["reason"]} for w in result.warnings]}
    if kind == "verify_range":
        # v1.5.0 review fixes: a pack's range verified with the entries it cites (prior), as verify_audit_pack does.
        events = parse_export_lines(inp["lines"].split("\n"))
        cited = parse_export_lines(inp["cited_lines"].split("\n"))
        result = verify_evidence_events(events, na_public_keys=_history(inp),
                                        executor_keys=executor_keys(inp["executor_keys"]), prior=cited)
        return {"failures": [{"store_sequence": f["store_sequence"], "reason": f["reason"]} for f in result.failures]}
    if kind == "registry_keys":
        from genesis_mesh.workflows.audit_pack import _registry_keys

        events = parse_export_lines(inp["lines"].split("\n"))
        placed = _registry_keys(events, _history(inp))

        def iso(value: Any) -> Any:
            return value.isoformat().replace("+00:00", "Z") if value is not None else None

        return {"keys": [{"key_id": k.key_id, "public_key": k.public_key, "role": k.role,
                          "registered_sequence": k.registered_sequence, "registered_at": iso(k.registered_at),
                          "retired_sequence": k.retired_sequence, "retired_at": iso(k.retired_at)}
                         for k in sorted(placed.values(), key=lambda k: k.key_id)]}
    if kind == "report_cell":
        from genesis_mesh.workflows.audit_pack import _cell

        return {"cells": [_cell(value) for value in inp["values"]]}
    if kind == "changes_file":
        from genesis_mesh.workflows.audit_pack import parse_changes

        try:
            parsed = parse_changes(inp["text"], csv_format=inp["csv"])
        except ValueError:
            return {"refused": True}
        return {"refused": False, "changes": [c.to_dict() for c in parsed]}
    if kind == "record_time":
        from genesis_mesh.models.key_succession import NA_RECORD_TIME_FIELDS

        return {"field": NA_RECORD_TIME_FIELDS.get(vector["model"])}
    if kind == "verify_anchors":
        anchors = [StoreAnchor.model_validate(a) for a in inp["anchors"]]
        result = verify_store_anchors(anchors, na_public_keys=_history(inp), sovereign_id=inp["genesis"]["network_name"])
        return {"failures": [{"anchor_sequence": f["anchor_sequence"], "reason": f["reason"]} for f in result.failures]}
    if kind == "decision_at_record_time":
        decision = BoundaryDecision.model_validate(inp["decision"])
        history = _history(inp)
        return {"at_record_time": verify_boundary_decision(decision, history, at_record_time=True).reason,
                "now": verify_boundary_decision(decision, history, now=_when(inp["now"])).reason}
    if kind == "pack":
        files = {path: text.encode("utf-8") for path, text in inp["files"].items()}
        held = [StoreAnchor.model_validate(a) for a in inp["held_anchors"]] if inp["held_anchors"] is not None else None
        changes = changes_of(inp["changes"]) if inp.get("changes") is not None else None
        period = (_when(inp["period"][0]), _when(inp["period"][1])) if inp.get("period") else None
        prior = {int(k): v for k, v in inp["prior_entries"].items()} if inp.get("prior_entries") else None
        result = verify_audit_pack(files, root_public_key=inp["root_public_key"], held_anchors=held, changes=changes,
                                   period=period, prior_entries=prior)
        out: dict[str, Any] = {"verified": result.verified, "reasons": result.reasons(),
                               "warnings": sorted({w["reason"] for w in result.warnings})}
        if result.completeness is not None:
            out["unmatched_changes"] = [c["index"] for c in result.completeness["unmatched_changes"]]
        if result.period is not None:
            out["period"] = {k: result.period[k] for k in ("from", "until")}
        return out
    if kind == "completeness":
        events = [EvidenceEvent.received(json.loads(line)) for line in inp["lines"].split("\n") if line]
        report = check_completeness(changes_of(inp["changes"]), events,
                                    period=(_when(inp["period"][0]), _when(inp["period"][1])),
                                    tolerance=timedelta(seconds=inp["tolerance_seconds"]))
        return {"pairs": [[p["change"], p["record_id"], p["matched_by"]] for p in report["pairs"]],
                "unmatched_changes": [c["index"] for c in report["unmatched_changes"]],
                "outside_period": [c["index"] for c in report["outside_period"]],
                "duplicate_changes": [c["index"] for c in report["duplicate_changes"]],
                "unmatched_records": [rec["record_id"] for rec in report["unmatched_records"]]}
    raise ValueError(f"unknown vector kind {kind!r}")


def _lines(events: list[Any]) -> str:
    return "".join(e.to_json_line() + "\n" for e in events)


def _relink(events: list[Any]) -> list[Any]:
    """Events re-chained after a payload changed (as a database writer would), positions kept."""
    from genesis_mesh.models.evidence_store import EvidenceEvent, payload_digest

    out: list[Any] = []
    prev: str | None = None
    for event in events:
        entry = event.entry.model_copy(update={"payload_digest": payload_digest(event.payload),
                                               "prev_entry_digest": prev})
        out.append(EvidenceEvent(entry=entry, entry_digest=entry.digest(), payload=event.payload))
        prev = entry.digest()
    return out


def _text(files: dict[str, bytes]) -> dict[str, str]:
    return {path: body.decode("utf-8") for path, body in sorted(files.items())}


def resigned(files: dict[str, bytes], changed: dict[str, bytes | None], *, key: str = "g", key_id: str = "na-2",
             **manifest_changes: Any) -> dict[str, bytes]:
    """Files changed (or removed, ``None``) and a new manifest signed with an NA key: what its holder can do.

    The report is rendered again from the changed files (v1.5.0 review fixes), as that holder would, unless
    ``report.md`` itself is one of the changes."""
    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models.audit_pack import (
        CHECKS_FILE, ENTRIES_FILE, MANIFEST_FILE, REPORT_FILE, STATES_FILE, AuditPackManifest, PackFile,
    )
    from genesis_mesh.trust.evidence_store import parse_export_lines
    from genesis_mesh.workflows.audit_pack import render_report, report_header

    out = {**files}
    for path, body in changed.items():
        if body is None:
            out.pop(path, None)
        else:
            out[path] = body
    manifest = AuditPackManifest.model_validate_json(files[MANIFEST_FILE])
    manifest = manifest.model_copy(update={**manifest_changes, "signature": None})
    if REPORT_FILE not in changed:
        states = json.loads(out[STATES_FILE])
        out[REPORT_FILE] = render_report(
            manifest=report_header(manifest), entries=parse_export_lines(out[ENTRIES_FILE].decode().split("\n")),
            checks=json.loads(out[CHECKS_FILE]), states=states["states"], notices=states["notices"]).encode()
    manifest = manifest.model_copy(update={"files": [
        PackFile(path=p, sha256=sha256(b), bytes=len(b)) for p, b in sorted(out.items()) if p != MANIFEST_FILE]})
    manifest = manifest.model_copy(update={"signature": sign_model(manifest, KEYS[key], key_id)})
    out[MANIFEST_FILE] = manifest.file_bytes()
    return out


def pack_variants(world: Any, frozen: dict[str, bytes]) -> list[tuple[str, str, dict[str, Any]]]:
    """(id, description, input) of every pack case: the frozen pack, valid and refused variants."""
    from genesis_mesh.models.audit_pack import ANCHORS_FILE, CITED_FILE, ENTRIES_FILE
    from genesis_mesh.models.evidence_store import EvidenceEvent
    from genesis_mesh.trust.evidence_store import sign_store_anchor

    root = pub("f")
    held = [a.to_wire() for a in world.anchors]
    base = {"root_public_key": root, "held_anchors": held}
    whole = build_pack(world, start=1, through=world.anchors[-1].store_sequence, pack_id=uid(803),
                       created_at=SUCCESSION_AT + timedelta(days=5), cited_sequences=[])
    cases: list[tuple[str, str, dict[str, Any]]] = [
        ("pack-whole-store", "A pack of the whole store, from entry 1", {**base, "files": _text(whole)}),
        ("pack-frozen-1.5.0", "The frozen 1.5.0 pack: after anchor 1, across the succession",
         {**base, "files": _text(frozen)}),
    ]
    entries = bytearray(frozen[ENTRIES_FILE])
    entries[entries.index(b"rotate")] = ord("R")
    cases += [
        ("pack-tampered-file", "A file changed after the manifest was signed",
         {**base, "files": _text({**frozen, ENTRIES_FILE: bytes(entries)})}),
        ("pack-unlisted-file", "A file the manifest does not list",
         {**base, "files": _text({**frozen, "extra.txt": b"x\n"})}),
        ("pack-root-mismatch", "Another root key: the pack's keys prove nothing alone",
         {**base, "root_public_key": pub("c"), "files": _text(frozen)}),
        ("pack-end-anchor-not-held", "The auditor does not hold the anchor that ends the range",
         {**base, "held_anchors": held[:-1], "files": _text(frozen)}),
        ("pack-no-held-anchors", "Without held anchors: the integrity of what is present only",
         {**base, "held_anchors": None, "files": _text(frozen)}),
    ]
    lines = frozen[ENTRIES_FILE].decode().splitlines(keepends=True)
    executions = [i for i, line in enumerate(lines) if '"entry_kind":"execution"' in line]
    removed = "".join(line for i, line in enumerate(lines) if i != executions[-1]).encode()
    cases.append(("pack-removed-record", "A record removed by someone holding the NA key, the manifest signed again",
                  {**base, "files": _text(resigned(frozen, {ENTRIES_FILE: removed}))}))
    cited_lines = frozen[CITED_FILE].decode().splitlines(keepends=True)
    no_head = "".join(line for line in cited_lines if '"entry_kind":"execution"' not in line).encode()
    cases.append(("pack-head-missing", "A pack without the record its resource chain continues from",
                  {**base, "files": _text(resigned(frozen, {CITED_FILE: no_head}))}))
    # A rewritten range: the last execution removed, the chain re-linked and re-anchored with the NA key.
    events = [EvidenceEvent.received(json.loads(line)) for line in lines]
    kept = [e for i, e in enumerate(events) if i != executions[-1]]
    rebuilt, prev = [], events[0].entry.prev_entry_digest
    for i, e in enumerate(kept):
        entry = e.entry.model_copy(update={"store_sequence": events[0].entry.store_sequence + i,
                                           "prev_entry_digest": prev})
        rebuilt.append(EvidenceEvent(entry=entry, entry_digest=entry.digest(), payload=e.payload))
        prev = entry.digest()
    anchors = [a for a in world.anchors if a.store_sequence >= events[0].entry.store_sequence - 1]
    forged_end = sign_store_anchor(anchors[-1].model_copy(update={
        "store_sequence": rebuilt[-1].entry.store_sequence, "entry_digest": prev, "signature": None}),
        KEYS["g"], "na-2")
    rewritten = resigned(frozen, {ENTRIES_FILE: _lines(rebuilt).encode(),
                                  ANCHORS_FILE: "".join(canonical(a.to_wire()) + "\n"
                                                        for a in [*anchors[:-1], forged_end]).encode()},
                         through_sequence=rebuilt[-1].entry.store_sequence)
    cases.append(("pack-rewritten-re-anchored", "A range rewritten without a record, re-linked and re-anchored "
                  "with the NA key", {**base, "files": _text(rewritten)}))
    second = world.records["second"]
    changes = [
        {"source": "cloud-activity-log", "source_event_id": "event-0002", "resource_id": RESOURCE, "action": "rotate",
         "changed_at": second.executed_at.isoformat()},
        {"resource_id": RESOURCE, "action": "update", "changed_at": second.executed_at.isoformat()},
    ]
    cases.append(("pack-unmatched-change", "A change from an outside log that no record of the pack matches",
                  {**base, "files": _text(frozen), "changes": changes}))
    return [*cases, *review_pack_variants(world, frozen, base)]


def review_pack_variants(world: Any, frozen: dict[str, bytes], base: dict[str, Any]) -> list[tuple[str, str, dict]]:
    """v1.5.0 review fixes: the pack cases each finding added."""
    from genesis_mesh.crypto import sign_data
    from genesis_mesh.models.audit_pack import CITED_FILE, MANIFEST_FILE, REPORT_FILE, STATES_FILE
    from genesis_mesh.models.evidence_store import EvidenceEvent

    cases: list[tuple[str, str, dict[str, Any]]] = []
    manifest = json.loads(frozen[MANIFEST_FILE])
    # 26: a manifest without a field its model defaults ("format"), as received.
    bare = {k: v for k, v in manifest.items() if k != "format"}
    cases.append(("pack-manifest-defaulted-field-omitted", "A manifest without \"format\", which its model "
                  "defaults: the signature does not cover what was received",
                  {**base, "files": _text({**frozen, MANIFEST_FILE: (canonical(bare) + "\n").encode()})}))
    body = {k: v for k, v in bare.items() if k != "signature"}
    resigned_bare = {**body, "signature": {"key_id": "na-2", "sig": sign_data(canonical(body).encode(), KEYS["g"])}}
    cases.append(("pack-manifest-defaulted-field-omitted-signed", "A manifest signed without \"format\": signed as "
                  "received, but not in its canonical form",
                  {**base, "files": _text({**frozen, MANIFEST_FILE: (canonical(resigned_bare) + "\n").encode()})}))
    # 13: the report says what the pack does not hold; a listed file outside the format.
    cases.append(("pack-report-mismatch", "report.md rewritten and the manifest signed again: it is not what the "
                  "pack renders to", {**base, "files": _text(resigned(frozen, {
                      REPORT_FILE: b"# Audit pack\n\nNothing happened.\n"}))}))
    states = json.loads(frozen[STATES_FILE])
    states["notices"] = {"x": {"notified_at": "2026-01-01T00:00:00Z", "notified_by": "operator-1"}}
    cases.append(("pack-states-changed", "states.json changed and the manifest signed again: the report no longer "
                  "renders from it", {**base, "files": _text(resigned(frozen, {
                      STATES_FILE: (canonical(states) + "\n").encode()}))}))
    cases.append(("pack-unknown-listed-file", "A listed file that is not a file of the format",
                  {**base, "files": _text(resigned(frozen, {"READ-ME-FIRST.md": b"All checks passed.\n"}))}))
    # 12: the manifest dated before the end anchor, signed by the key valid then (the outgoing key).
    cases.append(("pack-manifest-backdated", "A manifest dated before its end anchor, signed by the key valid at "
                  "that date", {**base, "files": _text(resigned(
                      frozen, {}, key="c", key_id="na-1", created_at=SUCCESSION_AT - timedelta(days=1),
                      issued_by="na-1"))}))
    # 11: the period asked for; changes outside the period.
    covered_until = world.anchors[-1].anchored_at
    cases.append(("pack-period-covered", "A period the pack covers (from its start anchor to its end anchor)",
                  {**base, "files": _text(frozen), "period": [
                      (world.anchors[0].anchored_at + timedelta(hours=1)).isoformat(), covered_until.isoformat()]}))
    cases.append(("pack-period-not-covered", "A period running past the pack's end anchor",
                  {**base, "files": _text(frozen), "period": [
                      world.anchors[0].anchored_at.isoformat(), (covered_until + timedelta(days=1)).isoformat()]}))
    cases.append(("pack-changes-outside-period", "A change dated long after the pack's end: a warning, not a failure",
                  {**base, "files": _text(frozen), "changes": [
                      {"resource_id": RESOURCE, "action": "delete",
                       "changed_at": (covered_until + timedelta(days=30)).isoformat()}]}))
    # 4: cited entries against a prior pack's entries and held anchors.
    cited = [EvidenceEvent.received(json.loads(line)) for line in frozen[CITED_FILE].decode().splitlines() if line]
    prior = {str(e.entry.store_sequence): e.received_entry_digest() for e in cited}
    cases.append(("pack-cited-covered-by-prior", "Every cited entry equal to the one a pack verified before holds",
                  {**base, "files": _text(frozen), "prior_entries": prior}))
    wrong = {**prior, str(cited[0].entry.store_sequence): "0" * 64}
    cases.append(("pack-cited-entry-mismatch", "A cited entry that differs from the one a pack verified before "
                  "holds at its position", {**base, "files": _text(frozen), "prior_entries": wrong}))
    return cases


def review_vectors(world: Any, base: dict[str, Any], both: Any) -> list[tuple[str, str, str, dict[str, Any]]]:
    """v1.5.0 review fixes: (id, kind, description, fields) of the non-pack vectors each finding added."""
    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models.evidence_store import EvidenceEvent, ResourceHead, RetentionCheckpoint
    from genesis_mesh.models.execution import ExecutionEvidence
    from genesis_mesh.models.out_of_band import RegistryRecord
    from genesis_mesh.trust.evidence_store import build_entry, sign_retention_checkpoint
    from genesis_mesh.trust.out_of_band import entry_index

    r = world.records
    out: list[tuple[str, str, str, dict[str, Any]]] = []
    keys_file = world.keys_file()
    events = world.events

    def relinked(changed: dict[int, Any]) -> list[Any]:
        """The world's events with some replaced (by store position), re-linked."""
        return _relink([changed.get(e.entry.store_sequence, e) for e in events])

    def with_time(event: Any, at: datetime) -> Any:
        entry = event.entry.model_copy(update={"recorded_at": at})
        return EvidenceEvent(entry=entry, entry_digest=entry.digest(), payload=event.payload)

    # 6: time goes backwards; a key valid at the entry's time but not at a later one stored before it.
    judgement = next(e for e in events if e.entry.entry_kind == "judgement")
    out.append(("export-recorded-at-out-of-order", "verify_export",
                "An entry recorded a day before the entry stored ahead of it",
                {"input": {**base, "lines": _lines(relinked({judgement.entry.store_sequence: with_time(
                    judgement, judgement.entry.recorded_at - timedelta(days=1))})), "executor_keys": keys_file}}))
    appended = [e for e in events if e.entry.recorded_at <= SUCCESSION_AT]
    for n, at, seed, key_id in ((951, SUCCESSION_AT + timedelta(seconds=400), "g", "na-2"),
                                (952, SUCCESSION_AT + timedelta(seconds=299), "c", "na-1")):
        record = RegistryRecord(registry_record_id=uid(n), event="policy_history_started", effective_at=at,
                                issuer_sovereign_id=SOVEREIGN, issued_by=key_id)
        record = record.model_copy(update={"signature": sign_model(record, KEYS[seed], key_id)})
        entry = build_entry(store_sequence=appended[-1].entry.store_sequence + 1, entry_kind="registry",
                            recorded_at=at, payload=record.to_wire(), prev_entry_digest=appended[-1].entry.digest(),
                            index=entry_index("registry", record))
        appended.append(EvidenceEvent(entry=entry, entry_digest=entry.digest(), payload=record.to_wire()))
    out.append(("export-outgoing-key-after-the-store-moved-on", "verify_export",
                "An entry signed by the outgoing key, dated in the last second of the hand-over, stored after an "
                "entry dated past it (within the time tolerance): the key must be valid at that later time too",
                {"input": {**base, "lines": _lines(appended), "executor_keys": keys_file}}))
    # 10: a key succession entry recorded less than the lead before it takes effect.
    succession_event = next(e for e in events if e.entry.entry_kind == "key_succession")
    previous_time = events[succession_event.entry.store_sequence - 2].entry.recorded_at
    out.append(("export-succession-backdated", "verify_export",
                "A key succession entry recorded 30 seconds before the succession takes effect",
                {"input": {**base, "lines": _lines(relinked({succession_event.entry.store_sequence: with_time(
                    succession_event, max(previous_time, SUCCESSION_AT - timedelta(seconds=30)))})),
                    "executor_keys": keys_file}}))
    # 5: a decision signed by the outgoing key, valid for a year.
    decision_event = next(e for e in events if e.entry.entry_kind == "decision")
    long_lived = r["first_decision"].model_copy(update={
        "decision_valid_until": r["first_decision"].decision_made_at + timedelta(days=365), "signature": None})
    long_lived = long_lived.model_copy(update={"signature": sign_model(long_lived, KEYS["c"], "na-1")})
    out.append(("export-decision-outlives-key", "verify_export",
                "A decision signed by the outgoing key that stays valid a year past its end",
                {"input": {**base, "lines": _lines(relinked({decision_event.entry.store_sequence: EvidenceEvent(
                    entry=decision_event.entry, entry_digest=decision_event.entry_digest,
                    payload={**decision_event.payload, "decision": long_lived.model_dump(mode="json")})})),
                    "executor_keys": keys_file}}))
    out.append(("decision-outlives-key", "decision_at_record_time",
                "A decision signed by the outgoing key that stays valid a year past its end",
                {"input": {**base, "decision": long_lived.model_dump(mode="json"), "now": "2026-01-02T00:00:00Z"}}))
    # 30 and 21: keys placed where the registry records them.
    executions = [e.entry.store_sequence for e in events if e.entry.entry_kind == "execution"]
    placed = [{**k, "registered_sequence": 1} for k in keys_file]
    later = [{**k, "registered_sequence": executions[-1]} if k["key_id"] == "executor-b" else k for k in placed]
    out.append(("export-key-registered-later", "verify_export",
                "Execution evidence stored before its key was registered",
                {"input": {**base, "lines": _lines(events), "executor_keys": later}}))
    retired = [{**k, "retired_sequence": executions[0]} if k["key_id"] == "executor-b" else k for k in placed]
    out.append(("export-key-retired", "verify_export", "Execution evidence stored after its key was retired",
                {"input": {**base, "lines": _lines(events), "executor_keys": retired}}))
    reconstructed = [{**k, "registered_sequence": None, "registered_at_time": "2026-01-01T00:30:00Z"}
                     if k["key_id"] == "executor-b" else k for k in placed]
    out.append(("export-key-placed-by-time", "verify_export",
                "A key backfilled at an upgrade (or carried past retention) is placed by its effective time",
                {"input": {**base, "lines": _lines(events), "executor_keys": reconstructed}}))
    retire = RegistryRecord(registry_record_id=uid(952), event="executor_key_retired", key_id="executor-b",
                            effective_at=SUCCESSION_AT + timedelta(days=4, hours=1), issuer_sovereign_id=SOVEREIGN,
                            issued_by="na-2")
    retire = retire.model_copy(update={"signature": sign_model(retire, KEYS["g"], "na-2")})
    backfilled = RegistryRecord(registry_record_id=uid(953), event="executor_key_registered", key_id="executor-z",
                                public_key=pub("a"), executor_sovereign_id="sovereign-z", key_role="executor",
                                reconstructed=True, effective_at=T0 + timedelta(hours=3),
                                issuer_sovereign_id=SOVEREIGN, issued_by="na-2")
    backfilled = backfilled.model_copy(update={"signature": sign_model(backfilled, KEYS["g"], "na-2")})
    extended = list(events)
    for at, record in ((SUCCESSION_AT + timedelta(days=4, hours=1), retire),
                       (SUCCESSION_AT + timedelta(days=4, hours=2), backfilled)):
        entry = build_entry(store_sequence=extended[-1].entry.store_sequence + 1, entry_kind="registry",
                            recorded_at=at, payload=record.to_wire(), prev_entry_digest=extended[-1].entry.digest(),
                            index=entry_index("registry", record))
        extended.append(EvidenceEvent(entry=entry, entry_digest=entry.digest(), payload=record.to_wire()))
    out.append(("registry-keys-placed", "registry_keys",
                "Keys from the registry records the NA signed: by store position, a backfilled one by its time",
                {"input": {**base, "lines": _lines(extended)}}))
    # 2: a range after a prune continues the resource chain from the cited checkpoint.
    second = r["second"]
    second_event = next(e for e in events if e.entry.entry_kind == "execution"
                        and e.payload["evidence_id"] == second.evidence_id)
    removed_through = second_event.entry.store_sequence
    pruned_at = SUCCESSION_AT + timedelta(days=4, hours=3)
    checkpoint = RetentionCheckpoint(
        checkpoint_id=uid(961), created_at=pruned_at, cutoff=pruned_at - timedelta(days=1),
        removed_through_sequence=removed_through, last_removed_entry_digest=second_event.entry_digest,
        removed_count=removed_through,
        resource_heads={RESOURCE: ResourceHead(resource_sequence=second.resource_sequence or 0,
                                               record_digest=second.digest())},
        issued_by="na-2")
    checkpoint = sign_retention_checkpoint(checkpoint, KEYS["g"], "na-2")
    cp_entry = build_entry(store_sequence=events[-1].entry.store_sequence + 1, entry_kind="retention_checkpoint",
                           recorded_at=pruned_at, payload=json.loads(checkpoint.model_dump_json()),
                           prev_entry_digest=events[-1].entry.digest(), index={})
    cp_event = EvidenceEvent(entry=cp_entry, entry_digest=cp_entry.digest(),
                             payload=json.loads(checkpoint.model_dump_json()))
    third_decision = r["second_decision"].model_copy(update={
        "decision_id": uid(203), "decision_made_at": pruned_at + timedelta(hours=1),
        "decision_valid_until": pruned_at + timedelta(hours=1, minutes=5), "signature": None})
    third_decision = third_decision.model_copy(update={"signature": sign_model(third_decision, KEYS["g"], "na-2")})
    context = dict(decision_event.payload["context"])
    d_entry = build_entry(store_sequence=cp_entry.store_sequence + 1, entry_kind="decision",
                          recorded_at=pruned_at + timedelta(hours=1),
                          payload={"decision": third_decision.model_dump(mode="json"), "context": context},
                          prev_entry_digest=cp_entry.digest(), index={"decision_id": third_decision.decision_id})
    d_event = EvidenceEvent(entry=d_entry, entry_digest=d_entry.digest(),
                            payload={"decision": third_decision.model_dump(mode="json"), "context": context})
    third = ExecutionEvidence(
        evidence_id=uid(303), sequence_no=1, decision_id=third_decision.decision_id,
        context_id=third_decision.context_id, agreement_id=third_decision.agreement_id,
        executor_sovereign_id=second.executor_sovereign_id, executed_capability=second.executed_capability,
        outcome="success", execution_parameters={"version_id": "v3"},
        executed_at=pruned_at + timedelta(hours=1, minutes=1), resource_id=RESOURCE, resource_action="rotate",
        resource_sequence=(second.resource_sequence or 0) + 1, prev_resource_digest=second.digest())
    third = third.model_copy(update={"signature": sign_model(third, KEYS["b"], "executor-b")})
    e_payload = third.model_dump(mode="json")
    e_entry = build_entry(store_sequence=d_entry.store_sequence + 1, entry_kind="execution",
                          recorded_at=pruned_at + timedelta(hours=1, minutes=1), payload=e_payload,
                          prev_entry_digest=d_entry.digest(),
                          index={"decision_id": third.decision_id, "evidence_id": third.evidence_id,
                                 "executor_sovereign_id": third.executor_sovereign_id, "exec_sequence_no": 1,
                                 "resource_id": RESOURCE, "resource_action": "rotate",
                                 "resource_sequence": third.resource_sequence})
    e_event = EvidenceEvent(entry=e_entry, entry_digest=e_entry.digest(), payload=e_payload)
    registries = [e for e in events if e.entry.entry_kind == "registry"]
    out.append(("range-after-prune", "verify_range",
                "A range after a prune: the resource chain continues from the cited retention checkpoint's head",
                {"input": {**base, "lines": _lines([d_event, e_event]),
                           "cited_lines": _lines([*registries, cp_event]), "executor_keys": keys_file}}))
    out.append(("range-after-prune-without-checkpoint", "verify_range",
                "The same range without the checkpoint: the chain has no head",
                {"input": {**base, "lines": _lines([d_event, e_event]), "cited_lines": _lines(registries),
                           "executor_keys": keys_file}}))
    # 32: a retention checkpoint with a field outside its signature is refused (strict, as every Stage 2 record);
    # execution evidence with one is reported (unsigned_field).
    extra = {**cp_event.payload, "note": "added after signing"}
    x_entry = cp_entry.model_copy(update={"payload_digest": __import__("genesis_mesh.models.evidence_store",
                                                                       fromlist=["payload_digest"]).payload_digest(extra)})
    x_event = EvidenceEvent(entry=x_entry, entry_digest=x_entry.digest(), payload=extra)
    out.append(("export-checkpoint-unsigned-field", "verify_export",
                "A retention checkpoint carrying a field its signature does not cover: payload_invalid",
                {"input": {**base, "lines": _lines([x_event]), "executor_keys": keys_file}}))
    first_event = next(e for e in events if e.entry.entry_kind == "execution")
    noted = {**first_event.payload, "note": "added after signing"}
    out.append(("export-execution-unsigned-field", "verify_export",
                "Execution evidence carrying a field its signature does not cover: a warning (unsigned_field)",
                {"input": {**base, "lines": _lines(relinked({first_event.entry.store_sequence: EvidenceEvent(
                    entry=first_event.entry, entry_digest=first_event.entry_digest, payload=noted)})),
                    "executor_keys": keys_file}}))
    return out


def review_misc_vectors() -> list[tuple[str, str, str, dict[str, Any]]]:
    """v1.5.0 review fixes: report cells, the changes file, record times and completeness matching."""
    from genesis_mesh.models.key_succession import NA_RECORD_TIME_FIELDS

    out: list[tuple[str, str, str, dict[str, Any]]] = []
    out.append(("report-cells", "report_cell", "Report cells: backslash, bar, line breaks, controls, separators",
                {"input": {"values": ["plain", "a|b", "back\\slash", "line\nfeed", "lone\rreturn", "tab\there",
                                      "bell\x07", "del\x7f", "nel\x85", "ls\u2028ps\u2029", "Zürich ✓", "",
                                      True, 5, None, {"b": [1, "|"], "a": "x"}]}}))
    good = [{"resource_id": RESOURCE, "action": "rotate", "changed_at": "2026-01-01T02:00:00.1234567+02:00",
             "source": "log", "source_event_id": "e-1", "actor": "principal-1"},
            {"resource_id": RESOURCE, "action": "rotate", "changed_at": "2026-01-01t00:00:00z",
             "source": None, "source_event_id": None, "actor": ""}]
    out.append(("changes-json", "changes_file", "A JSON changes file: RFC 3339 times, null and empty values absent",
                {"input": {"text": canonical({"changes": good}), "csv": False}}))
    out.append(("changes-csv", "changes_file", "A CSV changes file",
                {"input": {"text": "source,source_event_id,resource_id,action,changed_at,actor\n"
                                   f"log,e-1,{RESOURCE},rotate,2026-01-01T00:00:00Z,principal-1\n"
                                   f",,{RESOURCE},update,2026-01-01T00:05:00+00:00,\n", "csv": True}}))
    for vid, value in (("date-only", "2026-01-01"), ("space-separator", "2026-01-01 00:00:00Z"),
                       ("no-offset", "2026-01-01T00:00:00"), ("leap-second", "2026-01-01T00:00:60Z"),
                       ("month-13", "2026-13-01T00:00:00Z"), ("offset-24", "2026-01-01T00:00:00+24:00"),
                       ("basic-format", "20260101T000000Z")):
        out.append((f"changes-time-{vid}", "changes_file", f"changed_at {value!r} is not an RFC 3339 date-time",
                    {"input": {"text": canonical([{"resource_id": RESOURCE, "action": "rotate",
                                                   "changed_at": value}]), "csv": False}}))
    for vid, row in (("boolean", {"resource_id": True}), ("number", {"action": 7}),
                     ("object", {"actor": {"name": "x"}}), ("source-alone", {"source": "log"})):
        base_row = {"resource_id": RESOURCE, "action": "rotate", "changed_at": "2026-01-01T00:00:00Z"}
        out.append((f"changes-refused-{vid}", "changes_file", f"A changes file with {vid}: refused",
                    {"input": {"text": canonical([{**base_row, **row}]), "csv": False}}))
    for model in sorted(NA_RECORD_TIME_FIELDS):
        out.append((f"record-time-{model}", "record_time", f"The time a {model} read alone is placed at",
                    {"model": model}))
    out.append(("record-time-unlisted", "record_time", "A model not signed by the NA has no record time",
                {"model": "ExecutionEvidence"}))

    def execution(n: int, at: datetime, resource: str = RESOURCE, action: str = "rotate") -> dict[str, Any]:
        return {"evidence_id": uid(970 + n), "resource_id": resource, "resource_action": action,
                "executed_at": at.isoformat()}

    def observation(n: int, at: datetime, event: str, resource: str = RESOURCE, action: str = "rotate") -> dict:
        return {"observation_id": uid(980 + n), "resource_id": resource, "action": action,
                "changed_at": at.isoformat(), "source": "log", "source_event_id": event}

    def lines(payloads: list[tuple[str, dict[str, Any]]]) -> str:
        from genesis_mesh.models.evidence_store import EvidenceEvent
        from genesis_mesh.trust.evidence_store import build_entry

        events, prev = [], None
        for i, (kind, payload) in enumerate(payloads, start=1):
            entry = build_entry(store_sequence=i, entry_kind=kind, recorded_at=T0, payload=payload,
                                prev_entry_digest=prev, index={})
            events.append(EvidenceEvent(entry=entry, entry_digest=entry.digest(), payload=payload))
            prev = entry.digest()
        return _lines(events)

    window = [(T0 - timedelta(hours=1)).isoformat(), (T0 + timedelta(hours=1)).isoformat()]
    out.append(("completeness-least-distance", "completeness",
                "The most pairs at the least total distance: a closest-first pass would leave change 2 unmatched",
                {"input": {"lines": lines([("execution", execution(1, T0 - timedelta(seconds=200))),
                                           ("execution", execution(2, T0 + timedelta(seconds=100)))]),
                           "tolerance_seconds": 300, "period": window,
                           "changes": [{"resource_id": RESOURCE, "action": "rotate", "changed_at": T0.isoformat()},
                                       {"resource_id": RESOURCE, "action": "rotate",
                                        "changed_at": (T0 + timedelta(seconds=250)).isoformat()}]}}))
    out.append(("completeness-duplicate-event", "completeness", "The same source event listed twice is one change",
                {"input": {"lines": lines([("observation", observation(1, T0, "e-1"))]), "tolerance_seconds": 300,
                           "period": window, "changes": [
                               {"resource_id": RESOURCE, "action": "rotate", "changed_at": T0.isoformat(),
                                "source": "log", "source_event_id": "e-1"},
                               {"resource_id": RESOURCE, "action": "rotate", "changed_at": T0.isoformat(),
                                "source": "log", "source_event_id": "e-1"}]}}))
    out.append(("completeness-event-id-other-resource", "completeness",
                "A source event ID naming another resource and action is no match",
                {"input": {"lines": lines([("observation", observation(2, T0, "e-2", "other", "delete"))]),
                           "tolerance_seconds": 300, "period": window, "changes": [
                               {"resource_id": RESOURCE, "action": "rotate", "changed_at": T0.isoformat(),
                                "source": "log", "source_event_id": "e-2"}]}}))
    out.append(("completeness-no-event-id", "completeness",
                "A change without a source event ID is matched by time only (never under a \"None\" ID)",
                {"input": {"lines": lines([("observation", {**observation(3, T0 + timedelta(days=1), "None"),
                                                            "source": "None"})]),
                           "tolerance_seconds": 300, "period": window, "changes": [
                               {"resource_id": RESOURCE, "action": "rotate", "changed_at": T0.isoformat()}]}}))
    return out


def audit_vectors() -> list[dict[str, Any]]:
    """Every vector of the ``audit`` suite, ``expected`` filled in by the reference."""
    from genesis_mesh.crypto import sign_data, sign_model
    from genesis_mesh.models.audit_pack import MANIFEST_FILE
    from genesis_mesh.models.evidence_store import EvidenceEvent
    from genesis_mesh.models.key_succession import KeySuccessionRecord
    from genesis_mesh.trust.evidence_store import sign_store_anchor
    from genesis_mesh.trust.key_succession import sign_succession

    world = build_world()
    r = world.records
    root = pub("f")
    base = {"genesis": world.genesis, "successions": world.successions, "root_public_key": root}
    vectors: list[dict[str, Any]] = []

    def add(vid: str, kind: str, description: str, **fields: Any) -> None:
        vector = {"id": vid, "kind": kind, "description": description, **fields}
        vector["expected"] = evaluate(vector)
        vectors.append(vector)

    # Canonical forms of the new signed records.
    frozen = frozen_pack(world)
    for model, record in (("KeySuccessionRecord", r["succession"].to_wire()), ("ArchiveRecord", r["archive"].to_wire()),
                          ("AuditPackManifest", json.loads(frozen[MANIFEST_FILE]))):
        add(f"canonical-{model}", "canonical_form", f"The signed form of a {model}", model=model, record=record)

    # The key history.
    succession = r["succession"]
    unsigned = succession.model_copy(update={"signatures": []})

    def held(record: Any) -> Any:
        """The private key of the new key a record names (its proof of possession)."""
        return next(KEYS[k] for k in KEYS if pub(k) == record.new_public_key)

    def both(record: Any, *, root_key: bool = True, prove: bool = True, previous: bool = True) -> dict[str, Any]:
        """The record signed by the root key, the new key and the outgoing key (each optional)."""
        signed = record.model_copy(update={"signatures": []})
        for wanted, key, key_id in ((root_key, KEYS["f"], "root"), (prove, held(record), record.new_key_id),
                                    (previous, KEYS["c"], "na-1")):
            if wanted:
                signed = sign_succession(signed, key, key_id)
        return signed.to_wire()

    def signed_raw(body: dict[str, Any]) -> dict[str, Any]:
        data = canonical(body).encode()
        return {**body, "signatures": [{"key_id": "root", "sig": sign_data(data, KEYS["f"])},
                                       {"key_id": "na-2", "sig": sign_data(data, KEYS["g"])},
                                       {"key_id": "na-1", "sig": sign_data(data, KEYS["c"])}]}

    third = KeySuccessionRecord(
        succession_id=uid(402), sovereign_id=SOVEREIGN, key_sequence=3, previous_key_id="na-2",
        previous_public_key=pub("g"), previous_succession_digest=succession.digest(), new_key_id="na-3",
        new_public_key=pub("a"), effective_at=succession.new_valid_to + timedelta(days=1),
        new_valid_to=succession.new_valid_to + timedelta(days=400), issued_at=succession.new_valid_to,
    )
    late = sign_succession(sign_succession(sign_succession(third, KEYS["f"], "root"), KEYS["a"], "na-3"),
                           KEYS["g"], "na-2").to_wire()
    body = {k: v for k, v in succession.to_wire().items() if k != "signatures"}
    history_cases = [
        ("genesis-only", "The genesis key alone", [], root),
        ("one-succession", "The genesis key and one succession", world.successions, root),
        ("root-mismatch", "A root key the genesis block does not name", world.successions, pub("c")),
        ("root-signature", "A succession the root key did not sign",
         [both(unsigned, root_key=False)], root),
        ("new-key-signature", "A succession the new key did not sign (no proof the new key is held)",
         [both(unsigned, prove=False)], root),
        ("previous-signature", "A succession the outgoing key did not sign",
         [both(unsigned, previous=False)], root),
        ("root-as-na-key", "A succession naming the root key as the next NA key",
         [both(succession.model_copy(update={"new_public_key": root}))], root),
        ("backdated", "A succession issued after it takes effect",
         [both(succession.model_copy(update={"issued_at": succession.effective_at + timedelta(seconds=1)}))], root),
        ("chain-break", "A succession that does not continue the history (wrong position)",
         [both(succession.model_copy(update={"key_sequence": 3}))], root),
        ("key-reused", "A succession naming a key the history already held",
         [both(succession.model_copy(update={"new_public_key": pub("c")}))], root),
        ("not-increasing", "A succession whose new key ends before it starts",
         [both(succession.model_copy(update={"new_valid_to": succession.effective_at}))], root),
        ("sovereign-mismatch", "A succession of another sovereign",
         [both(succession.model_copy(update={"sovereign_id": "sovereign-x"}))], root),
        ("after-expiry", "A succession taking effect after the previous key's enforced end",
         [*world.successions, late], root),
        ("unknown-field", "A succession signed over a field this release does not know",
         [signed_raw({**body, "x_added_field": 1})], root),
        ("unsigned-field", "A succession with a field outside its signatures",
         [{**succession.to_wire(), "x_added_field": 1}], root),
        ("payload-invalid", "A succession missing a field",
         [{k: v for k, v in succession.to_wire().items() if k != "new_valid_to"}], root),
        ("payload-invalid-and-unknown-field", "A succession that does not parse and has an unknown field, "
         "signed: payload_invalid comes first",
         [signed_raw({**{k: v for k, v in body.items() if k != "new_valid_to"}, "x_added_field": 1})], root),
    ]
    for vid, description, successions, anchor_key in history_cases:
        add(f"history-{vid}", "key_history", description,
            input={"genesis": world.genesis, "successions": successions, "root_public_key": anchor_key})
    add("history-genesis-tampered", "key_history", "A genesis block changed after the root key signed it",
        input={"genesis": {**world.genesis, "network_version": "v9"}, "successions": [], "root_public_key": root})
    genesis_body = {k: v for k, v in world.genesis.items() if k != "signatures"}
    genesis_extra = {**genesis_body, "x_added_field": 1}
    add("history-genesis-unknown-field", "key_history",
        "A genesis block signed by the root key over a field this release does not know (it is strict)",
        input={"genesis": {**genesis_extra, "signatures": [
            {"key_id": "root", "sig": sign_data(canonical(genesis_extra).encode(), KEYS["f"])}]},
            "successions": [], "root_public_key": root})

    # Which key a record dated at a time may be signed with.
    for vid, at, description in (
        ("long-before", T0 - timedelta(days=365), "Long before the genesis block: the genesis key's start is not "
         "enforced"),
        ("genesis-window", T0 + timedelta(days=9), "Within the genesis key's window"),
        ("before-succession", SUCCESSION_AT - timedelta(seconds=1), "Just before the succession takes effect"),
        ("at-succession", SUCCESSION_AT, "When the succession takes effect: both keys (hand-over)"),
        ("handover-end", SUCCESSION_AT + timedelta(seconds=299), "The last second of the hand-over"),
        ("after-handover", SUCCESSION_AT + timedelta(seconds=300), "After the hand-over: the new key only"),
        ("after-new-valid-to", succession.new_valid_to, "At the new key's enforced end: no key"),
    ):
        add(f"key-at-{vid}", "key_at", description, input={**base, "at": at.isoformat().replace("+00:00", "Z")})
    add("key-at-genesis-valid-to-not-enforced", "key_at",
        "Without a succession, long after the genesis block's valid_to: the genesis key's end is not enforced",
        input={**base, "successions": [], "at": (T0 + timedelta(days=400)).isoformat().replace("+00:00", "Z")})

    # Exports across the succession.
    keys_file = world.keys_file()
    add("export-across-succession", "verify_export", "The whole store, signed by both keys, with the key history",
        input={**base, "lines": _lines(world.events), "executor_keys": keys_file})
    judgement_event = next(e for e in world.events if e.entry.entry_kind == "judgement")
    forged = r["judgement"].model_copy(update={"signature": None})
    forged = forged.model_copy(update={"signature": sign_model(forged, KEYS["c"], "na-1")}).to_wire()
    swapped = _relink([EvidenceEvent(entry=e.entry, entry_digest=e.entry_digest,
                                     payload=forged if e is judgement_event else e.payload) for e in world.events])
    add("export-outgoing-key-after-handover", "verify_export",
        "A judgement recorded after the hand-over but signed by the outgoing key",
        input={**base, "lines": _lines(swapped), "executor_keys": keys_file})
    decision_event = next(e for e in world.events if e.entry.entry_kind == "decision")
    early = r["first_decision"].model_copy(update={"signature": None})
    early = early.model_copy(update={"signature": sign_model(early, KEYS["g"], "na-2")})
    swapped = _relink([EvidenceEvent(entry=e.entry, entry_digest=e.entry_digest,
                                     payload={**e.payload, "decision": early.model_dump(mode="json")}
                                     if e is decision_event else e.payload) for e in world.events])
    add("export-new-key-before-succession", "verify_export",
        "A decision recorded before the succession but signed by the new key",
        input={**base, "lines": _lines(swapped), "executor_keys": keys_file})
    stray = both(succession.model_copy(update={"succession_id": uid(499), "new_key_id": "na-x",
                                               "new_public_key": pub("a")}))
    swapped = _relink([EvidenceEvent(entry=e.entry.model_copy(update={"record_id": uid(499)})
                                     if e.entry.entry_kind == "key_succession" else e.entry,
                                     entry_digest=e.entry_digest,
                                     payload=stray if e.entry.entry_kind == "key_succession" else e.payload)
                       for e in world.events])
    add("export-succession-not-in-history", "verify_export",
        "A succession entry signed by the root and outgoing keys that the key history does not hold",
        input={**base, "lines": _lines(swapped), "executor_keys": keys_file})

    # Anchors across the succession.
    add("anchors-across-succession", "verify_anchors", "Anchors signed by both keys, each at its time",
        input={**base, "anchors": [a.to_wire() for a in world.anchors]})
    resigned_anchor = sign_store_anchor(world.anchors[-1].model_copy(update={"signature": None}), KEYS["c"], "na-1")
    add("anchors-outgoing-key", "verify_anchors", "An anchor after the hand-over signed by the outgoing key",
        input={**base, "anchors": [a.to_wire() for a in world.anchors[:-1]] + [resigned_anchor.to_wire()]})

    # A decision judged as of its own time, not now.
    add("decision-at-record-time", "decision_at_record_time",
        "An archived decision: valid when it was made, expired since",
        input={**base, "decision": r["first_decision"].model_dump(mode="json"), "now": "2030-01-01T00:00:00Z"})

    # Packs.
    for vid, description, inp in pack_variants(world, frozen):
        add(vid, "pack", description, input=inp)

    # v1.5.0 review fixes.
    for vid, kind, description, fields in [*review_vectors(world, base, both), *review_misc_vectors()]:
        add(vid, kind, description, **fields)

    # The completeness check alone.
    stored = [e for e in world.events if e.entry.entry_kind in ("execution", "observation", "judgement")]
    second = r["second"]
    add("completeness-matching", "completeness",
        "By source event, then by resource, action and time; an observation and the execution it matched are one "
        "change; a change outside the period is not missing", input={
            "lines": _lines(stored), "tolerance_seconds": 300,
            "period": [T0.isoformat(), (SUCCESSION_AT + timedelta(days=5)).isoformat()],
            "changes": [
                {"source": "cloud-activity-log", "source_event_id": "event-0002", "resource_id": RESOURCE,
                 "action": "rotate", "changed_at": second.executed_at.isoformat()},
                {"resource_id": RESOURCE, "action": "create", "changed_at": r["first"].executed_at.isoformat()},
                {"resource_id": RESOURCE, "action": "delete",
                 "changed_at": (SUCCESSION_AT + timedelta(days=2)).isoformat()},
                {"resource_id": RESOURCE, "action": "delete", "changed_at": (T0 - timedelta(days=30)).isoformat()},
            ]})
    return vectors
