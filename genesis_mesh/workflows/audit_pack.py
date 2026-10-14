"""Audit packs: verification, the completeness check and the report (v1.5.0, Stage 4).

A pack (``models.audit_pack``, format ``gm.audit.pack`` version 1) holds one
range of the evidence store between two anchors, everything the range's
records cite, the NA's key history and a countersigned manifest. It is
verified offline, with no network and no private key, from material the
security team holds itself: the root public key and its copies of the
anchors. Keys inside the pack prove nothing alone: the NA keys are accepted
only through the key history, from the root key down; executor and observer
keys only through registry records the NA signed, placed in the store before
the records they verify (or keys the auditor supplies).

``verify_audit_pack`` runs these checks, each failure named by a reason code
(``docs/reference/audit-pack-format.md`` lists them with the file each is
reported against):

1. the manifest: present, of this format, in canonical form, every file it
   lists a file of the format (``manifest_unknown_file``) present with its
   SHA-256 and size, no file it does not list, every file of the format
   listed. A pack whose manifest fails here is not checked further: its
   files are not the pack;
2. the key history: the genesis block signed by the root key the verifier
   holds, each succession signed by the root key, the new key and the
   outgoing key; the manifest signed, as received, by the NA key valid at its
   ``created_at``;
3. the anchors: the pack's anchors signed (by the key valid at each one's
   time) and chained; each one the verifier holds equal to the pack's; the
   range's last entry named by the end anchor, which the verifier holds; the
   range's start tied to entry 1, a retention checkpoint in the range or a
   held start anchor; every held anchor inside the range naming its entry;
   the manifest dated no earlier than the end anchor and the last entry
   (``manifest_backdated``); each cited entry equal to the one a prior pack
   or a held anchor names at its position (``cited_entry_mismatch``), and a
   warning for each that neither covers (``cited_entry_unanchored``);
4. the entries: exactly the manifest's range, one unbroken store chain, every
   record signed by the key valid at its time (``verify_evidence_events``),
   the chains continuing from the records the pack cites; a record the
   range cites that the pack does not hold fails (``cited_record_missing``);
5. what the records cite outside the store: each policy version a decision
   or judgement was made under, with its digest; each attestation a decision
   rests on, signed by the NA (or by a key a treaty in the pack names), with
   the digest the decision bound; treaties and feeds signed by their issuers;
   every signature checked over the record as received;
6. the report: ``report.md`` is what ``render_report`` writes from the
   manifest, the entries, ``checks.json`` and ``states.json``
   (``report_mismatch``);
7. the period: with one asked for, the pack covers it
   (``pack_period_not_covered``);
8. with a changes file, the completeness check (``check_completeness``).

Decisions are judged as of their own time (``at_record_time``): a decision
that expired since it was made and used is not a failure.
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from pydantic import ValidationError

from .. import strict_json
from ..models.audit_pack import (
    AGREEMENTS_FILE,
    ANCHORS_FILE,
    ATTESTATIONS_FILE,
    CHECKS_FILE,
    CITED_FILE,
    ENTRIES_FILE,
    EXECUTOR_KEYS_FILE,
    FEEDS_FILE,
    GENESIS_FILE,
    KEY_HISTORY_FILE,
    MANIFEST_FILE,
    OPTIONAL_PACK_FILES,
    PACK_FILES,
    POLICIES_FILE,
    REPORT_FILE,
    STATES_FILE,
    TREATIES_FILE,
    AuditPackManifest,
)
from ..models.boundary_policy import BoundaryPolicy, policy_set_digest
from ..models.context import BoundaryDecision
from ..models.evidence_store import EvidenceEvent, RetentionCheckpoint, StoreAnchor
from ..models.grants import CapabilityGrant
from ..models.key_succession import NAKeyHistory
from ..models.out_of_band import JudgementRecord, RegistryRecord
from ..models.sovereign import MembershipAttestation, RecognitionTreaty, SovereignRevocationFeed
from ..trust.context import verify_boundary_decision
from ..trust.evidence_store import (
    EvidenceVerification,
    ExecutorKey,
    carried_sequences,
    check_events_against_anchors,
    parse_export_lines,
    verify_evidence_events,
    verify_store_anchors,
)
from ..trust.key_succession import verify_key_history

#: The default time tolerance of the completeness check.
DEFAULT_TOLERANCE = timedelta(seconds=300)


@dataclass
class PackVerification:
    """Result of verifying an audit pack."""

    verified: bool = True
    failures: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    range: dict[str, Any] = field(default_factory=dict)
    anchors: dict[str, Any] | None = None
    keys: list[dict[str, Any]] = field(default_factory=list)
    completeness: dict[str, Any] | None = None
    #: v1.5.0 review fixes: the period the pack covers (and the one it was asked for).
    period: dict[str, Any] | None = None
    #: v1.5.0 review fixes: the lines where ``report.md`` differs from the report the pack renders to.
    report_differences: list[dict[str, Any]] = field(default_factory=list)

    def fail(self, file: str | None, store_sequence: int | None, reason: str, detail: str = "") -> None:
        self.verified = False
        self.failures.append({"file": file, "store_sequence": store_sequence, "reason": reason, "detail": detail})

    def warn(self, file: str | None, store_sequence: int | None, reason: str, detail: str = "") -> None:
        self.warnings.append({"file": file, "store_sequence": store_sequence, "reason": reason, "detail": detail})

    def reasons(self) -> list[str]:
        """The failure reason codes, sorted (what two verifiers compare)."""
        return sorted({f["reason"] for f in self.failures})

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "verified": self.verified, "failures": self.failures, "warnings": self.warnings,
            "counts": dict(sorted(self.counts.items())), "range": self.range, "keys": self.keys,
        }
        if self.anchors is not None:
            out["anchors"] = self.anchors
        if self.period is not None:
            out["period"] = self.period
        if self.report_differences:
            out["report_differences"] = self.report_differences
        if self.completeness is not None:
            out["completeness"] = self.completeness
        return out


# ---------------------------------------------------------------------------
# Reading a pack
# ---------------------------------------------------------------------------


def read_pack_dir(directory: str | Path) -> dict[str, bytes]:
    """Every file under ``directory``, by its ``/``-separated relative path, as bytes."""
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"not a directory: {directory}")
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def _json(data: bytes) -> Any:
    return strict_json.loads(data.decode("utf-8"))


def _jsonl(data: bytes) -> list[Any]:
    """JSON Lines: one value per LF-separated line, blank lines ignored (as every SDK reads them)."""
    return [strict_json.loads(line) for line in data.decode("utf-8").split("\n") if line.strip(" \t\r")]


def _events(data: bytes) -> list[EvidenceEvent]:
    return parse_export_lines(data.decode("utf-8").split("\n"))


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pack_entry_digests(files: Mapping[str, bytes]) -> dict[int, str]:
    """The entries a pack holds, by store position: their digests as received (v1.5.0 review fixes).

    What ``verify_audit_pack(prior_entries=...)`` takes from packs verified
    before, to check the entries a later pack cites.
    """
    return {e.entry.store_sequence: e.received_entry_digest() for e in _events(files[ENTRIES_FILE])}


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _check_manifest(
    files: Mapping[str, bytes], result: PackVerification,
) -> tuple[AuditPackManifest | None, dict[str, Any] | None]:
    """The manifest and its JSON as received, or (None, None) when it cannot be read."""
    from ..models.canonical_registry import unknown_fields

    raw = files.get(MANIFEST_FILE)
    if raw is None:
        result.fail(MANIFEST_FILE, None, "manifest_missing")
        return None, None
    try:
        data = _json(raw)
        if isinstance(data, dict) and unknown_fields("AuditPackManifest", data):
            raise ValueError("unknown field")
        manifest = AuditPackManifest.model_validate(data)
    except (ValueError, ValidationError, UnicodeDecodeError, strict_json.StrictJSONError) as exc:
        result.fail(MANIFEST_FILE, None, "manifest_invalid", str(exc)[:200])
        return None, None
    if manifest.file_bytes() != raw:
        result.fail(MANIFEST_FILE, None, "manifest_invalid", "not in canonical form")
    listed: dict[str, Any] = {}
    for item in manifest.files:
        if item.path in listed or item.path == MANIFEST_FILE:
            result.fail(MANIFEST_FILE, None, "manifest_invalid", f"lists {item.path} twice or itself")
        listed[item.path] = item
    for path in PACK_FILES:
        if path not in listed:
            result.fail(MANIFEST_FILE, None, "manifest_file_missing", f"{path} is not listed")
    for path, item in sorted(listed.items()):
        if path not in PACK_FILES and path not in OPTIONAL_PACK_FILES:
            # v1.5.0 review fixes: a pack holds the files of its format and nothing else.
            result.fail(MANIFEST_FILE, None, "manifest_unknown_file", f"{path} is not a file of the format")
            continue
        body = files.get(path)
        if body is None:
            result.fail(path, None, "manifest_file_missing")
        elif _sha256(body) != item.sha256 or len(body) != item.bytes:
            result.fail(path, None, "manifest_digest_mismatch")
    for path in sorted(files):
        if path != MANIFEST_FILE and path not in listed:
            result.fail(path, None, "manifest_unlisted_file")
    return manifest, data


def received_signature_reason(model: str, raw: Any, history: NAKeyHistory, at: datetime) -> str | None:
    """None when a signature on ``raw`` verifies, over the record as received, with the NA key valid
    at ``at``; else why not (v1.5.0 review fixes: every signed kind a pack carries is checked as
    received, never over a form re-written from a model with its defaults filled in).

    ``unknown_field`` or ``non_canonical_form`` for a record its signer signed in another form,
    ``na_key_not_valid_at_time`` for one signed by another key of the history,
    ``invalid_signature`` otherwise.
    """
    from ..models.canonical_registry import signed_as_received, strict_refusal

    if not isinstance(raw, dict):
        return "invalid_signature"
    keys = history.keys_at(_utc(at))
    if signed_as_received(model, raw, keys):
        return strict_refusal(model, raw, keys)
    others = [k for k in history.all_keys() if k not in keys]
    if others and signed_as_received(model, raw, others):
        return "na_key_not_valid_at_time"
    return "invalid_signature"


def _received_by(model: str, raw: Any, keys: Sequence[str]) -> str | None:
    """As ``received_signature_reason``, for keys with no time (a treaty's subject keys)."""
    from ..models.canonical_registry import signed_as_received, strict_refusal

    if not isinstance(raw, dict) or not signed_as_received(model, raw, keys):
        return "invalid_signature"
    return strict_refusal(model, raw, keys)


def _registry_keys(events: Iterable[EvidenceEvent], history: NAKeyHistory) -> dict[str, ExecutorKey]:
    """Executor and observer keys from the registry records the NA signed (by the key valid then).

    v1.5.0 review fixes: each key is placed where the store registered and
    retired it (``ExecutorKey.position_problem``): by store position, or, for a
    record backfilled at an upgrade (``reconstructed``) or carried past
    retention, by its ``effective_at``.
    """
    ordered = sorted(events, key=lambda e: e.entry.store_sequence)
    carried = carried_sequences(ordered)
    keys: dict[str, ExecutorKey] = {}
    for event in ordered:
        if event.entry.entry_kind != "registry":
            continue
        try:
            record = RegistryRecord.model_validate(event.payload)
        except ValidationError:
            continue
        if received_signature_reason("RegistryRecord", event.payload, history, event.entry.recorded_at) is not None:
            continue
        seq = event.entry.store_sequence
        by_time = bool(record.reconstructed) or seq in carried
        if record.event == "executor_key_registered" and record.key_id and record.public_key \
                and record.executor_sovereign_id:
            held = keys.get(record.key_id)
            if held is not None and held.public_key == record.public_key:
                continue  # registered again: the first registration places it
            keys[record.key_id] = ExecutorKey(
                key_id=record.key_id, public_key=record.public_key,
                executor_sovereign_id=record.executor_sovereign_id, role=record.key_role or "executor",
                resource_prefix=record.resource_prefix,
                registered_sequence=None if by_time else seq,
                registered_at=_utc(record.effective_at) if by_time else None)
        elif record.event == "executor_key_retired" and record.key_id and record.key_id in keys:
            held = keys[record.key_id]
            if held.retired_sequence is None and held.retired_at is None:
                keys[record.key_id] = dataclasses.replace(
                    held, retired=True, retired_sequence=None if by_time else seq,
                    retired_at=_utc(record.effective_at) if by_time else None)
    return keys


def _file_of(seq: int | None, from_sequence: int) -> str:
    return CITED_FILE if seq is not None and seq < from_sequence else ENTRIES_FILE


def verify_audit_pack(
    files: Mapping[str, bytes],
    *,
    root_public_key: str,
    held_anchors: Sequence[StoreAnchor] | None,
    executor_keys: Mapping[str, ExecutorKey] | None = None,
    changes: Sequence["Change"] | None = None,
    tolerance: timedelta = DEFAULT_TOLERANCE,
    check_manifest: bool = True,
    period: tuple[datetime, datetime] | None = None,
    prior_entries: Mapping[int, str] | None = None,
) -> PackVerification:
    """Verify an audit pack offline (the module docstring lists the checks).

    ``held_anchors`` are the anchors the verifier holds (``--known-anchors``):
    without them a pack proves the integrity of what it holds, not that
    nothing was removed, and the result says so (``no_held_anchors``).
    ``executor_keys`` are keys the verifier supplies out of band, for a store
    without registry records (a key the pack's registry records place wins).
    ``check_manifest=False`` verifies the files before a manifest exists (the
    NA, writing ``checks.json``). ``period`` is a period the pack must cover
    (``--period``); ``prior_entries`` the entries of packs verified before
    (``pack_entry_digests``, ``--prior``), which the entries this pack cites
    must equal.
    """
    result = PackVerification()
    manifest, manifest_raw = _check_manifest(files, result) if check_manifest else (None, None)

    # 2. The key history, from the root key down.
    try:
        genesis = _json(files[GENESIS_FILE])
        successions = _json(files[KEY_HISTORY_FILE]).get("successions", [])
    except (KeyError, ValueError, AttributeError, UnicodeDecodeError) as exc:
        result.fail(KEY_HISTORY_FILE, None, "key_history_invalid", str(exc)[:200])
        return result
    keyed = verify_key_history(genesis, successions if isinstance(successions, list) else [], root_public_key)
    for failure in keyed.failures:
        where = GENESIS_FILE if failure["key_sequence"] == 1 else KEY_HISTORY_FILE
        result.fail(where, None, failure["reason"], f"key {failure['key_sequence']}")
    if not keyed.verified or keyed.history is None:
        return result
    history = keyed.history
    result.keys = [k.to_dict() for k in history.keys]

    if manifest is not None:
        if manifest.sovereign_id != history.sovereign_id:
            result.fail(MANIFEST_FILE, None, "manifest_invalid", "names another sovereign")
        # v1.5.0 review fixes: over the manifest as received, not the model with its defaults.
        reason = received_signature_reason("AuditPackManifest", manifest_raw, history, manifest.created_at)
        if reason is not None:
            result.fail(MANIFEST_FILE, None, "manifest_invalid_signature" if reason == "invalid_signature" else reason)
    if check_manifest and not result.verified:
        # Files that do not match a manifest the NA signed are not the pack: nothing else is checked.
        return result

    # 3 and 4. Anchors and entries.
    try:
        pack_anchors = sorted((StoreAnchor.model_validate(a) for a in _jsonl(files[ANCHORS_FILE])),
                              key=lambda a: a.anchor_sequence)
        entries = _events(files[ENTRIES_FILE])
        cited = _events(files[CITED_FILE])
    except (KeyError, ValueError, ValidationError, UnicodeDecodeError) as exc:
        result.fail(ENTRIES_FILE, None, "entries_invalid", str(exc)[:200])
        return result
    if not entries:
        result.fail(ENTRIES_FILE, None, "pack_range_mismatch", "the pack holds no entry")
        return result
    first, last = entries[0].entry.store_sequence, entries[-1].entry.store_sequence
    from_sequence = manifest.from_sequence if manifest else first
    through = manifest.through_sequence if manifest else last
    result.range = {"from_sequence": first, "through_sequence": last, "entries": len(entries),
                    "first_recorded_at": entries[0].entry.recorded_at.isoformat(),
                    "last_recorded_at": entries[-1].entry.recorded_at.isoformat()}
    if (first, last) != (from_sequence, through) or len(entries) != through - from_sequence + 1:
        result.fail(ENTRIES_FILE, None, "pack_range_mismatch",
                    f"the entries run {first}..{last}, the manifest says {from_sequence}..{through}")
    for event in cited:
        if event.entry.store_sequence >= from_sequence:
            result.fail(CITED_FILE, event.entry.store_sequence, "cited_out_of_range")

    chain = verify_store_anchors(pack_anchors, na_public_keys=history, sovereign_id=history.sovereign_id)
    for failure in chain.failures:
        result.fail(ANCHORS_FILE, None, failure["reason"], f"anchor {failure['anchor_sequence']}")
    by_sequence = {a.anchor_sequence: a for a in pack_anchors}
    end = by_sequence.get(manifest.end_anchor_sequence) if manifest else (pack_anchors[-1] if pack_anchors else None)
    if end is None or end.store_sequence != last or end.entry_digest != entries[-1].received_entry_digest():
        result.fail(ANCHORS_FILE, last, "pack_end_anchor_mismatch", "no anchor of the pack names the range's last entry")
    if manifest is not None:
        start_anchor = by_sequence.get(manifest.start_anchor_sequence) if manifest.start_anchor_sequence else None
    else:
        start_anchor = next((a for a in reversed(pack_anchors) if a.store_sequence == first - 1), None)
    if manifest and manifest.start_anchor_sequence and (
            start_anchor is None or start_anchor.store_sequence != first - 1
            or start_anchor.entry_digest != entries[0].entry.prev_entry_digest):
        result.fail(ANCHORS_FILE, first, "pack_start_not_tied", "the start anchor does not name the entry before the range")
    if manifest is not None:
        # v1.5.0 review fixes: the NA writes a pack after its end anchor and its last entry.
        latest = max([_utc(entries[-1].entry.recorded_at), *([_utc(end.anchored_at)] if end is not None else [])])
        if _utc(manifest.created_at) < latest:
            result.fail(MANIFEST_FILE, None, "manifest_backdated",
                        f"created at {_iso(manifest.created_at)}, before {_iso(latest)}")

    # The start checkpoint: a retention checkpoint (in the range or cited) that removed the entries before it.
    start_checkpoint: RetentionCheckpoint | None = None
    for event in [*entries, *cited]:
        if event.entry.entry_kind == "retention_checkpoint":
            try:
                cp = RetentionCheckpoint.model_validate(event.payload)
            except ValidationError:
                continue
            if cp.removed_through_sequence == first - 1 and cp.last_removed_entry_digest == entries[0].entry.prev_entry_digest:
                start_checkpoint = cp
    if first == 1 and entries[0].entry.prev_entry_digest is not None:
        result.fail(ENTRIES_FILE, 1, "store_chain_break", "entry 1 names a previous entry")

    held = {a.anchor_sequence: a for a in held_anchors or []}
    if held_anchors is None:
        result.warn(None, None, "no_held_anchors",
                    "verified without anchors held out of band: the pack's integrity, not that nothing was removed")
    else:
        held_chain = verify_store_anchors(list(held_anchors), na_public_keys=history,
                                          sovereign_id=history.sovereign_id)
        for failure in held_chain.failures:
            result.fail("known-anchors", None, failure["reason"], f"held anchor {failure['anchor_sequence']}")
        for anchor in pack_anchors:
            mine = held.get(anchor.anchor_sequence)
            if mine is not None and mine.to_wire() != anchor.to_wire():
                result.fail(ANCHORS_FILE, anchor.store_sequence, "anchor_mismatch",
                            f"anchor {anchor.anchor_sequence} differs from the one held")
        if end is not None and end.anchor_sequence not in held:
            result.fail(ANCHORS_FILE, last, "pack_end_anchor_not_held",
                        f"anchor {end.anchor_sequence} is not among the anchors held")
        inside = [a for a in held_anchors if a.store_sequence <= last]
        tied = EvidenceVerification()
        check_events_against_anchors(entries, inside, tied, from_anchor=True)
        for failure in tied.failures:
            result.fail(ENTRIES_FILE, failure["store_sequence"], failure["reason"], failure["detail"])
        result.anchors = tied.anchors

    # v1.5.0 review fixes: a cited entry is checked against what the verifier holds at its position: an
    # entry of a pack verified before, or an anchor naming that very entry. Neither: a warning.
    held_at = {a.store_sequence: a for a in held_anchors or []}
    for event in cited:
        seq = event.entry.store_sequence
        digest = event.received_entry_digest()
        known = (prior_entries or {}).get(seq)
        held_anchor = held_at.get(seq)
        if known is not None and known != digest:
            result.fail(CITED_FILE, seq, "cited_entry_mismatch", "differs from the entry a prior pack holds")
        elif held_anchor is not None and held_anchor.entry_digest != digest:
            result.fail(CITED_FILE, seq, "cited_entry_mismatch", f"differs from held anchor {held_anchor.anchor_sequence}")
        elif known is None and held_anchor is None:
            result.warn(CITED_FILE, seq, "cited_entry_unanchored",
                        "signed, but neither a prior pack nor a held anchor covers this entry")

    # 4. Executor keys: from registry records the NA signed, and keys supplied out of band.
    keys = dict(executor_keys or {})
    keys.update(_registry_keys([*cited, *entries], history))
    verification = verify_evidence_events(
        entries, na_public_keys=history, executor_keys=keys, contiguous=True,
        checkpoint=start_checkpoint, prior=cited,
    )
    for failure in verification.failures:
        seq = failure["store_sequence"]
        result.fail(_file_of(seq, from_sequence), seq, failure["reason"], failure["detail"])
    for warning in verification.warnings:
        result.warn(_file_of(warning["store_sequence"], from_sequence), warning["store_sequence"], warning["reason"],
                    warning["detail"])
    result.counts = {k: v for k, v in verification.to_dict().items()
                     if isinstance(v, int) and not isinstance(v, bool)}

    # 5. What the records cite outside the store.
    _check_cited_trust(files, entries, cited, history, result)

    # 6. The report renders from the pack's own files.
    if manifest is not None:
        _check_report(files, manifest, entries, result)

    # 7. The period the pack covers: from its start anchor (or the retention checkpoint it starts after,
    # or its first entry, at the start of the store) to its end anchor.
    if start_anchor is not None:
        covered_from = _utc(start_anchor.anchored_at)
    elif start_checkpoint is not None:
        covered_from = _utc(start_checkpoint.created_at)
    else:
        covered_from = _utc(entries[0].entry.recorded_at)
    covered_until = _utc(end.anchored_at) if end is not None else _utc(entries[-1].entry.recorded_at)
    result.period = {"from": _iso(covered_from), "until": _iso(covered_until)}
    if manifest is not None and manifest.period_from is not None:
        result.period["requested_from"] = _iso(manifest.period_from)
    if manifest is not None and manifest.period_until is not None:
        result.period["requested_until"] = _iso(manifest.period_until)
    if period is not None:
        wanted_from, wanted_until = _utc(period[0]), _utc(period[1])
        result.period.update({"asked_from": _iso(wanted_from), "asked_until": _iso(wanted_until)})
        if wanted_from < covered_from or wanted_until > covered_until:
            result.fail(None, None, "pack_period_not_covered",
                        f"the pack covers {_iso(covered_from)} to {_iso(covered_until)}")

    # 8. Completeness.
    if changes is not None:
        result.completeness = check_completeness(
            changes, entries, cited, period=(covered_from, covered_until), tolerance=tolerance)
        for item in result.completeness["unmatched_changes"]:
            result.fail("changes", None, "change_unmatched",
                        f"{item['source'] or '-'} {item['source_event_id'] or '-'} {item['resource_id']} "
                        f"{item['action']} {item['changed_at']}")
        if result.completeness["outside_period"]:
            result.warn("changes", None, "changes_outside_period",
                        f"{len(result.completeness['outside_period'])} change(s) dated outside the period "
                        f"the pack covers ({_iso(covered_from)} to {_iso(covered_until)})")
        for item in result.completeness["duplicate_changes"]:
            result.warn("changes", None, "change_duplicate",
                        f"change {item['index']} repeats {item['source']} {item['source_event_id']}")
    return result


def _check_report(
    files: Mapping[str, bytes], manifest: AuditPackManifest, entries: Sequence[EvidenceEvent],
    result: PackVerification,
) -> None:
    """``report.md`` is the report ``render_report`` writes from the pack's own files (v1.5.0 review
    fixes): a statement in it that the pack does not hold is ``report_mismatch``."""
    try:
        checks = _json(files[CHECKS_FILE])
        states = _json(files[STATES_FILE])
        claimed = files[REPORT_FILE].decode("utf-8")
    except (KeyError, ValueError, UnicodeDecodeError, strict_json.StrictJSONError) as exc:
        result.fail(REPORT_FILE, None, "report_mismatch", f"cannot be rendered: {str(exc)[:160]}")
        return
    if not isinstance(checks, dict) or not isinstance(states, dict):
        result.fail(REPORT_FILE, None, "report_mismatch", "checks.json and states.json are JSON objects")
        return
    expected = render_report(manifest=report_header(manifest), entries=entries, checks=checks,
                             states=states.get("states") or {}, notices=states.get("notices") or {})
    if expected == claimed:
        return
    ours, theirs = expected.split("\n"), claimed.split("\n")
    for i in range(max(len(ours), len(theirs))):
        mine = ours[i] if i < len(ours) else None
        pack = theirs[i] if i < len(theirs) else None
        if mine != pack:
            result.report_differences.append({"line": i + 1, "pack": pack, "verifier": mine})
    result.fail(REPORT_FILE, None, "report_mismatch",
                f"{len(result.report_differences)} line(s) differ from the report the pack renders to")


def _check_cited_trust(
    files: Mapping[str, bytes], entries: Sequence[EvidenceEvent], cited: Sequence[EvidenceEvent],
    history: NAKeyHistory, result: PackVerification,
) -> None:
    """Policies, attestations, treaties and feeds the records rest on (outside the store).

    v1.5.0 review fixes: each signature is checked over the record as received
    (``received_signature_reason``), at the record's own time (``issued_at``).
    """
    try:
        raw_policies = _jsonl(files[POLICIES_FILE])
        raw_attestations = _jsonl(files[ATTESTATIONS_FILE])
        raw_treaties = _jsonl(files[TREATIES_FILE])
        raw_feeds = _jsonl(files[FEEDS_FILE])
        raw_agreements = _jsonl(files[AGREEMENTS_FILE]) if AGREEMENTS_FILE in files else []
        agreements = {str(a.get("agreement_id")): a for a in raw_agreements if isinstance(a, dict)}
        policies = [BoundaryPolicy.model_validate(p) for p in raw_policies]
        attestations = [MembershipAttestation.model_validate(a) for a in raw_attestations]
        treaties = [RecognitionTreaty.model_validate(t) for t in raw_treaties]
        feeds = [SovereignRevocationFeed.model_validate(f) for f in raw_feeds]
    except (KeyError, ValueError, ValidationError, UnicodeDecodeError) as exc:
        result.fail(POLICIES_FILE, None, "cited_trust_invalid", str(exc)[:200])
        return
    by_version: dict[tuple[str, int], BoundaryPolicy] = {}
    for policy, raw in zip(policies, raw_policies):
        reason = received_signature_reason("BoundaryPolicy", raw, history, policy.issued_at)
        if reason is not None:
            result.fail(POLICIES_FILE, None, "policy_invalid_signature" if reason == "invalid_signature" else reason,
                        f"{policy.policy_id} v{policy.version}")
        by_version[(policy.policy_id, policy.version)] = policy
    own = history.sovereign_id
    issuer_keys: dict[str, list[str]] = {}
    for treaty, raw in zip(treaties, raw_treaties):
        reason = received_signature_reason("RecognitionTreaty", raw, history, treaty.issued_at)
        if reason is not None:
            result.fail(TREATIES_FILE, None, "treaty_invalid_signature" if reason == "invalid_signature" else reason,
                        treaty.treaty_id)
            continue
        issuer_keys.setdefault(treaty.subject_sovereign_id, []).extend(treaty.subject_public_keys)
    by_attestation: dict[str, MembershipAttestation] = {}
    for attestation, raw in zip(attestations, raw_attestations):
        if attestation.issuer_sovereign_id == own:
            reason = received_signature_reason("MembershipAttestation", raw, history, attestation.issued_at)
        else:
            reason = _received_by("MembershipAttestation", raw, issuer_keys.get(attestation.issuer_sovereign_id, []))
        if reason is not None:
            result.fail(ATTESTATIONS_FILE, None,
                        "attestation_invalid_signature" if reason == "invalid_signature" else reason,
                        attestation.attestation_id)
        by_attestation[attestation.attestation_id] = attestation
    for feed, raw in zip(feeds, raw_feeds):
        reason = _received_by("SovereignRevocationFeed", raw, issuer_keys.get(feed.issuer_sovereign_id, []))
        if reason is not None:
            result.fail(FEEDS_FILE, None, "feed_invalid_signature" if reason == "invalid_signature" else reason,
                        feed.feed_id)

    from_sequence = entries[0].entry.store_sequence if entries else 0
    for event in [*cited, *entries]:
        kind = event.entry.entry_kind
        seq = event.entry.store_sequence
        where = _file_of(seq, from_sequence)
        binding: Any = None
        if kind == "decision":
            try:
                decision = BoundaryDecision.model_validate(event.payload["decision"])
            except (ValidationError, KeyError, TypeError):
                continue
            binding = decision.policy_binding
            if decision.attestation_binding is not None and decision.attestation_binding.attestation_digest:
                bound = by_attestation.get(decision.attestation_binding.attestation_id)
                if bound is None:
                    result.fail(where, seq, "cited_attestation_missing", decision.attestation_binding.attestation_id)
                else:
                    # As of the decision's own time: its expiry since then says nothing against it.
                    verdict = verify_boundary_decision(decision, history, expected_attestation=bound,
                                                       at_record_time=True)
                    if verdict.reason in ("attestation_binding_mismatch", "attestation_binding_missing"):
                        result.fail(where, seq, "cited_attestation_mismatch", bound.attestation_id)
        elif kind == "judgement":
            try:
                binding = JudgementRecord.model_validate(event.payload).policy_binding
            except ValidationError:
                continue
        elif kind == "grant":
            # v1.6.0: the policy versions a grant is bound to, and the attestation it rests on.
            try:
                grant = CapabilityGrant.model_validate(event.payload)
            except ValidationError:
                continue
            binding = grant.policy_binding
            if grant.basis_kind == "attestation":
                bound = by_attestation.get(grant.basis_id)
                if bound is None:
                    result.fail(where, seq, "cited_attestation_missing", grant.basis_id)
                elif bound.digest() != grant.basis_digest:
                    result.fail(where, seq, "cited_attestation_mismatch", grant.basis_id)
            else:
                # v1.6.0 review fixes: an agreement basis too: held, the one the grant names, between the
                # grant's parties, and signed by both with keys the pack vouches for.
                problem = _agreement_problem(grant, agreements.get(grant.basis_id), history, issuer_keys)
                if problem is not None:
                    result.fail(AGREEMENTS_FILE if problem != "cited_agreement_missing" else where, seq, problem,
                                grant.basis_id)
        if binding is None:
            continue
        if policy_set_digest(binding.policies) != binding.policy_set_digest:
            result.fail(where, seq, "cited_policy_mismatch", "policy_set_digest")
        for applied in binding.policies:
            held = by_version.get((applied.policy_id, applied.version))
            if held is None:
                result.fail(where, seq, "cited_policy_missing", f"{applied.policy_id} v{applied.version}")
            elif held.digest() != applied.policy_digest:
                result.fail(where, seq, "cited_policy_mismatch", f"{applied.policy_id} v{applied.version}")


def _agreement_problem(grant: CapabilityGrant, raw: Any, history: NAKeyHistory,
                       treaty_keys: Mapping[str, list[str]]) -> str | None:
    """Why the agreement a grant rests on does not hold up in a pack, or None (v1.6.0 review fixes).

    ``cited_agreement_missing``: the pack does not hold it; ``cited_agreement_mismatch``: it is not the
    one the grant's ``basis_digest`` names, or its parties are not the grant's (the responder is the
    requester, the offerer the provider); ``agreement_invalid_signature``: its two parties did not
    sign it, as received, with keys the pack vouches for (the NA's key valid at
    ``agreed_terms.valid_from`` for its own sovereign, a treaty's subject keys for another; an
    agreement the NA offered and accepted itself carries the NA's signature for both).
    """
    import hashlib

    from ..models.agreement import AgreementRecord
    from ..models.canonical_registry import agreement_refusal
    from ..models.key_succession import na_keys_at
    from ..trust.agreement import verify_agreement

    if raw is None:
        return "cited_agreement_missing"
    try:
        agreement = AgreementRecord.model_validate(raw)
    except ValidationError:
        return "cited_agreement_mismatch"
    digest = hashlib.sha256(agreement.to_canonical_json().encode("utf-8")).hexdigest()
    if digest != grant.basis_digest or agreement.responder_sovereign_id != grant.requester_sovereign_id \
            or agreement.offerer_sovereign_id != grant.provider_sovereign_id:
        return "cited_agreement_mismatch"
    own = history.sovereign_id
    na_keys = na_keys_at(history, agreement.agreed_terms.valid_from)

    def keys(party: str) -> list[str]:
        return list(na_keys) if party == own else [k for k in treaty_keys.get(party, []) if k not in na_keys]

    # The NA-offered-and-accepted exception holds, as on the NA's routes, only while the responder
    # holds a treaty from this NA (one the pack carries).
    self_accepted = agreement.offerer_sovereign_id == own and bool(treaty_keys.get(agreement.responder_sovereign_id))
    for offerer, responder in ((keys(agreement.offerer_sovereign_id), keys(agreement.responder_sovereign_id)),
                               (na_keys, na_keys) if self_accepted else ([], [])):
        if offerer and responder and verify_agreement(agreement, offerer, responder).accepted \
                and agreement_refusal(raw, offerer, responder) is None:
            return None
    return "agreement_invalid_signature"


def differences_from_pack_checks(result: PackVerification, files: Mapping[str, bytes]) -> list[dict[str, Any]]:
    """Where this verification differs from the checks the NA wrote into the pack (``checks.json``).

    A difference is not a failure by itself (the NA's checks ran with the NA's
    anchors): it is reported so a reader sees what the pack claimed.
    """
    try:
        claimed = _json(files[CHECKS_FILE])
    except (KeyError, ValueError, UnicodeDecodeError):
        return [{"field": "checks.json", "pack": None, "verifier": "unreadable"}]
    out: list[dict[str, Any]] = []
    if claimed.get("verified") != result.verified:
        out.append({"field": "verified", "pack": claimed.get("verified"), "verifier": result.verified})
    reasons = sorted({str(f.get("reason")) for f in claimed.get("failures", []) if isinstance(f, dict)})
    if reasons != result.reasons():
        out.append({"field": "failures", "pack": reasons, "verifier": result.reasons()})
    counts = claimed.get("counts") or {}
    for name, value in sorted(result.counts.items()):
        if counts.get(name, 0) != value:
            out.append({"field": f"counts.{name}", "pack": counts.get(name, 0), "verifier": value})
    return out


# ---------------------------------------------------------------------------
# Writing a pack
# ---------------------------------------------------------------------------


def compose_pack(
    *,
    genesis: Mapping[str, Any],
    successions: Sequence[Mapping[str, Any]],
    executor_keys: Sequence[Mapping[str, Any]],
    anchors: Sequence[StoreAnchor],
    entries: Sequence[EvidenceEvent],
    cited: Sequence[EvidenceEvent],
    trust: Mapping[str, Sequence[Mapping[str, Any]]],
    held_anchors: Sequence[StoreAnchor] | None,
    pack_id: str,
    created_at: datetime,
    requested_by: str | None,
    start_anchor_sequence: int | None,
    end_anchor_sequence: int,
    issued_by: str,
    sign: Any,
    states: Mapping[str, Mapping[str, Any]] | None = None,
    notices: Mapping[str, Any] | None = None,
    check_executor_keys: Mapping[str, ExecutorKey] | None = None,
    period_from: datetime | None = None,
    period_until: datetime | None = None,
) -> tuple[dict[str, bytes], AuditPackManifest]:
    """Every file of a pack (``PACK_FORMAT`` version 1) and its signed manifest.

    ``trust`` maps ``policies.jsonl`` and the ``trust/`` files to their
    records. ``checks.json`` is this module's verification of the files with
    ``held_anchors`` (the NA's own anchors) and ``check_executor_keys`` (the
    NA's own key table, for a store without registry records);
    ``states.json`` the remediation ``states`` and ``notices``; ``report.md``
    the report rendered from them. ``created_at`` is moved up to the end
    anchor's time and the last entry's when it is earlier (another
    instance's clock ahead of this one): a manifest is never dated before
    them. ``sign(manifest)`` returns the manifest's signature (the NA key).
    The bytes depend only on the arguments, so a pack is reproducible.
    """
    from ..models.audit_pack import PackFile, canonical_bytes, jsonl_bytes

    end = next((a for a in anchors if a.anchor_sequence == end_anchor_sequence), None)
    created_at = max([_utc(created_at), *([_utc(entries[-1].entry.recorded_at)] if entries else []),
                      *([_utc(end.anchored_at)] if end is not None else [])])
    files: dict[str, bytes] = {
        GENESIS_FILE: canonical_bytes(dict(genesis)),
        KEY_HISTORY_FILE: canonical_bytes({"successions": [dict(s) for s in successions]}),
        EXECUTOR_KEYS_FILE: canonical_bytes({"executor_keys": [dict(k) for k in executor_keys]}),
        ANCHORS_FILE: jsonl_bytes([a.to_wire() for a in anchors]),
        ENTRIES_FILE: "".join(e.to_json_line() + "\n" for e in entries).encode("utf-8"),
        CITED_FILE: "".join(e.to_json_line() + "\n" for e in cited).encode("utf-8"),
        STATES_FILE: canonical_bytes({"states": {k: dict(v) for k, v in sorted((states or {}).items())},
                                      "notices": dict(sorted((notices or {}).items()))}),
    }
    for path in (POLICIES_FILE, ATTESTATIONS_FILE, TREATIES_FILE, FEEDS_FILE):
        files[path] = jsonl_bytes([dict(r) for r in trust.get(path, [])])
    if trust.get(AGREEMENTS_FILE):
        # v1.6.0 review fixes: only when the pack holds a grant under an agreement.
        files[AGREEMENTS_FILE] = jsonl_bytes([dict(r) for r in trust[AGREEMENTS_FILE]])
    root = str(genesis.get("root_public_key"))
    checks = verify_audit_pack(files, root_public_key=root, held_anchors=held_anchors,
                               executor_keys=check_executor_keys, check_manifest=False).to_dict()
    files[CHECKS_FILE] = canonical_bytes(checks)
    draft = AuditPackManifest(
        pack_id=pack_id, sovereign_id=str(genesis.get("network_name")), created_at=created_at,
        requested_by=requested_by, from_sequence=entries[0].entry.store_sequence,
        through_sequence=entries[-1].entry.store_sequence, start_anchor_sequence=start_anchor_sequence,
        end_anchor_sequence=end_anchor_sequence, period_from=period_from, period_until=period_until,
        files=[], issued_by=issued_by,
    )
    stored = json.loads(files[STATES_FILE])
    files[REPORT_FILE] = render_report(manifest=report_header(draft), entries=entries, checks=checks,
                                       states=stored["states"], notices=stored["notices"]).encode("utf-8")
    manifest = draft.model_copy(update={
        "files": [PackFile(path=path, sha256=_sha256(body), bytes=len(body)) for path, body in sorted(files.items())],
    })
    manifest = manifest.model_copy(update={"signature": sign(manifest)})
    files[MANIFEST_FILE] = manifest.file_bytes()
    return files, manifest


# ---------------------------------------------------------------------------
# The completeness check
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Change:
    """One change from a log outside Genesis Mesh (a cloud audit log, a ticketing export)."""

    index: int
    resource_id: str
    action: str
    changed_at: datetime
    source: str | None = None
    source_event_id: str | None = None
    actor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "source": self.source, "source_event_id": self.source_event_id,
                "resource_id": self.resource_id, "action": self.action,
                "changed_at": _iso(self.changed_at), "actor": self.actor}


CHANGE_COLUMNS = ("source", "source_event_id", "resource_id", "action", "changed_at", "actor")

#: v1.5.0 review fixes: an RFC 3339 ``date-time`` (``T`` and ``Z`` in either case), nothing else.
_RFC3339 = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?([Zz]|[+-](\d{2}):(\d{2}))$",
    re.ASCII)  # \d: ASCII digits only, as every SDK reads them


def parse_rfc3339(value: str) -> datetime:
    """An RFC 3339 ``date-time`` as an aware UTC datetime; ``ValueError`` for anything else.

    v1.5.0 review fixes: a changes file's times are strict RFC 3339, so every
    verifier reads the same instants: a date without a time, a space for
    ``T``, a missing offset, a leap second or an out-of-range field is
    refused. Fractions beyond microseconds are cut, not rounded.
    """
    match = _RFC3339.match(value)
    if match is None:
        raise ValueError("not an RFC 3339 date-time")
    year, month, day, hour, minute, second, fraction, zone, zone_h, zone_m = match.groups()
    micro = int((fraction or ".0")[1:7].ljust(6, "0"))
    if zone in ("Z", "z"):
        offset = timedelta(0)
    else:
        if int(zone_h) > 23 or int(zone_m) > 59:
            raise ValueError("not an RFC 3339 date-time")
        offset = timedelta(hours=int(zone_h), minutes=int(zone_m)) * (1 if zone[0] == "+" else -1)
    parsed = datetime(int(year), int(month), int(day), int(hour), int(minute), int(second), micro,
                      tzinfo=timezone(offset))
    return parsed.astimezone(timezone.utc)


def parse_changes(text: str, *, csv_format: bool) -> list[Change]:
    """Changes from CSV (a header row naming ``CHANGE_COLUMNS``) or JSON (a list, or ``{"changes": [...]}``).

    ``resource_id``, ``action`` and ``changed_at`` (RFC 3339, with an offset)
    are required; ``source`` and ``source_event_id`` go together. In JSON a
    field is a string or null (v1.5.0 review fixes: ``true`` or ``7`` is
    refused, not turned into text); an empty string is absent. Raises
    ``ValueError`` naming the first bad row.
    """
    if csv_format:
        rows: list[Any] = list(csv.DictReader(io.StringIO(text)))
    else:
        data = strict_json.loads(text)
        listed = data.get("changes") if isinstance(data, dict) else data
        if not isinstance(listed, list):
            raise ValueError("a JSON changes file is a list of changes or {\"changes\": [...]}")
        rows = listed
    out: list[Change] = []
    for i, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"change {i} is not an object")

        def value(name: str) -> str | None:
            raw = row.get(name)
            if raw is None:
                return None
            if not isinstance(raw, str):
                raise ValueError(f"change {i}: {name} must be a string")
            raw = raw.strip()
            return raw or None

        resource, action, changed = value("resource_id"), value("action"), value("changed_at")
        if not resource or not action or not changed:
            raise ValueError(f"change {i}: resource_id, action and changed_at are required")
        try:
            at = parse_rfc3339(changed)
        except ValueError:
            raise ValueError(f"change {i}: changed_at is not an RFC 3339 time with an offset (Z for UTC)") from None
        source, event_id = value("source"), value("source_event_id")
        if (source is None) != (event_id is None):
            raise ValueError(f"change {i}: source and source_event_id go together")
        out.append(Change(index=i, resource_id=resource, action=action, changed_at=at,
                          source=source, source_event_id=event_id, actor=value("actor")))
    return out


@dataclass
class _Record:
    """A change as the pack records it: an observation, a break-glass record or execution evidence."""

    kind: str
    record_id: str
    store_sequence: int
    resource_id: str
    action: str
    earliest: datetime
    latest: datetime
    source: str | None = None
    source_event_id: str | None = None
    group: str = ""

    def distance(self, at: datetime) -> timedelta:
        if self.earliest <= at <= self.latest:
            return timedelta(0)
        return min(abs(at - self.earliest), abs(at - self.latest))


def _records(entries: Sequence[EvidenceEvent], cited: Sequence[EvidenceEvent]) -> list[_Record]:
    records: list[_Record] = []
    matched: dict[str, str] = {}
    for event in [*cited, *entries]:
        if event.entry.entry_kind == "judgement":
            payload = event.payload
            if payload.get("matched_evidence_id"):
                matched[str(payload["subject_id"])] = str(payload["matched_evidence_id"])
    for event in entries:
        p, kind = event.payload, event.entry.entry_kind
        try:
            if kind == "observation":
                start = str(p.get("changed_at") or p.get("changed_not_before"))
                stop = str(p.get("changed_at") or p.get("changed_not_after"))
                records.append(_Record(kind, p["observation_id"], event.entry.store_sequence, p["resource_id"],
                                       p["action"], _utc(datetime.fromisoformat(start)),
                                       _utc(datetime.fromisoformat(stop)), p.get("source"), p.get("source_event_id")))
            elif kind == "break_glass":
                at = _utc(datetime.fromisoformat(p["executed_at"]))
                records.append(_Record(kind, p["break_glass_id"], event.entry.store_sequence, p["resource_id"],
                                       p["resource_action"], at, at))
            elif kind == "execution" and p.get("resource_id"):
                at = _utc(datetime.fromisoformat(p["executed_at"]))
                records.append(_Record(kind, p["evidence_id"], event.entry.store_sequence, p["resource_id"],
                                       p["resource_action"], at, at))
            elif kind == "grant_execution" and p.get("resource_id"):
                # v1.6.0: a change made under a grant.
                at = _utc(datetime.fromisoformat(p["executed_at"]))
                records.append(_Record(kind, p["use_id"], event.entry.store_sequence, p["resource_id"],
                                       p["resource_action"], at, at))
        except (KeyError, TypeError, ValueError):
            continue
    # A governed change seen by an observer is one change: the observation and what it matched.
    for record in records:
        record.group = matched.get(record.record_id, record.record_id)
    return records


@dataclass
class _Group:
    """One recorded change: the records of one group, matched by its representative."""

    group: str
    members: list[_Record]

    @property
    def representative(self) -> _Record:
        # The execution evidence, grant use or break-glass record when the group holds one, else its
        # observation.
        return min(self.members, key=lambda r: (r.kind == "observation", r.store_sequence))


def _micros(delta: timedelta) -> int:
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _match_bucket(changes: Sequence[Change], groups: Sequence[_Group], tolerance: timedelta) -> list[tuple[Change, _Group]]:
    """The matching of one (resource, action): the most pairs, then the least total distance.

    Changes in time order (then by index) are matched to groups in time
    order (their representative's earliest time, then store position) without
    crossing, by dynamic programming. At each step the choices are, in this
    order, pairing the change with the group (when within ``tolerance``),
    leaving the change unmatched, leaving the group unmatched; the first
    choice that is best (more pairs, then less total distance in
    microseconds) is taken, so every verifier finds the same pairs.
    """
    cs = sorted(changes, key=lambda c: (c.changed_at, c.index))
    gs = sorted(groups, key=lambda g: (g.representative.earliest, g.representative.store_sequence))
    n, m = len(cs), len(gs)
    # best[i][j]: (pairs, -distance) using changes i.. and groups j..
    best = [[(0, 0)] * (m + 1) for _ in range(n + 1)]
    choice = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            options: list[tuple[tuple[int, int], int]] = []
            distance = gs[j].representative.distance(cs[i].changed_at)
            if distance <= tolerance:
                pairs, cost = best[i + 1][j + 1]
                options.append(((pairs + 1, cost - _micros(distance)), 0))
            options.append((best[i + 1][j], 1))
            options.append((best[i][j + 1], 2))
            top = max(o[0] for o in options)
            value, taken = next(o for o in options if o[0] == top)
            best[i][j], choice[i][j] = value, taken
        # row n stays (0, 0)
    out: list[tuple[Change, _Group]] = []
    i = j = 0
    while i < n and j < m:
        if choice[i][j] == 0:
            out.append((cs[i], gs[j]))
            i, j = i + 1, j + 1
        elif choice[i][j] == 1:
            i += 1
        else:
            j += 1
    return out


def check_completeness(
    changes: Sequence[Change], entries: Sequence[EvidenceEvent], cited: Sequence[EvidenceEvent] = (),
    *, period: tuple[datetime, datetime], tolerance: timedelta = DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    """Match changes from an outside log against the pack's records (v1.5.0 review fixes).

    1. Changes repeating a (source, source event ID) pair already seen are
       set aside (``duplicate_changes``).
    2. A change with a source and source event ID matches the record that
       names that very event when it agrees on resource and action (an
       observation of that event); a record that names the event but another
       resource or action is no match.
    3. The rest are matched per (resource, action) by ``_match_bucket``: an
       observation and the execution evidence it was matched to are one
       change, represented by the execution evidence.

    An unmatched change dated inside ``period`` (with ``tolerance`` either
    side) is ``unmatched_changes`` (the store does not record it); one outside
    is ``outside_period``. Records no change matched are ``unmatched_records``
    (the log may not cover every source).
    """
    records = _records(entries, cited)
    groups: dict[str, _Group] = {}
    for record in records:
        groups.setdefault(record.group, _Group(record.group, [])).members.append(record)
    used: set[str] = set()
    pairs: list[dict[str, Any]] = []
    seen_events: set[tuple[str, str]] = set()
    duplicates: list[Change] = []
    unique: list[Change] = []
    for change in changes:
        if change.source is not None and change.source_event_id is not None:
            key = (change.source, change.source_event_id)
            if key in seen_events:
                duplicates.append(change)
                continue
            seen_events.add(key)
        unique.append(change)
    by_event: dict[tuple[str, str], _Record] = {}
    for r in records:
        if r.source is not None and r.source_event_id is not None:
            by_event.setdefault((r.source, r.source_event_id), r)
    left: list[Change] = []
    for change in unique:
        named = by_event.get((change.source, change.source_event_id)) \
            if change.source is not None and change.source_event_id is not None else None
        if named is not None and named.group not in used and named.resource_id == change.resource_id \
                and named.action == change.action:
            used.add(named.group)
            pairs.append({"change": change.index, "kind": named.kind, "record_id": named.record_id,
                          "store_sequence": named.store_sequence, "matched_by": "source_event_id"})
        else:
            left.append(change)
    buckets: dict[tuple[str, str], tuple[list[Change], list[_Group]]] = {}
    for change in left:
        buckets.setdefault((change.resource_id, change.action), ([], []))[0].append(change)
    for group in groups.values():
        if group.group in used:
            continue
        rep = group.representative
        if (rep.resource_id, rep.action) in buckets:
            buckets[(rep.resource_id, rep.action)][1].append(group)
    matched_changes: set[int] = set()
    for key in sorted(buckets):
        bucket_changes, bucket_groups = buckets[key]
        for change, group in _match_bucket(bucket_changes, bucket_groups, tolerance):
            used.add(group.group)
            matched_changes.add(change.index)
            rep = group.representative
            pairs.append({"change": change.index, "kind": rep.kind, "record_id": rep.record_id,
                          "store_sequence": rep.store_sequence, "matched_by": "resource_action_time"})
    unmatched = [c for c in left if c.index not in matched_changes]
    start, end = period
    inside = [c for c in unmatched if start - tolerance <= c.changed_at <= end + tolerance]
    outside = [c for c in unmatched if c not in inside]
    unmatched_records = sorted((g.representative for g in groups.values() if g.group not in used),
                               key=lambda r: r.store_sequence)
    return {
        "changes": len(changes), "tolerance_seconds": int(tolerance.total_seconds()),
        "period": {"from": _iso(start), "to": _iso(end)},
        "pairs": sorted(pairs, key=lambda p: p["change"]),
        "unmatched_changes": [c.to_dict() for c in sorted(inside, key=lambda c: c.index)],
        "outside_period": [c.to_dict() for c in sorted(outside, key=lambda c: c.index)],
        "duplicate_changes": [c.to_dict() for c in duplicates],
        "unmatched_records": [{"kind": r.kind, "record_id": r.record_id, "store_sequence": r.store_sequence,
                               "resource_id": r.resource_id, "action": r.action} for r in unmatched_records],
        "complete": not inside,
    }


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def _cell(value: Any) -> str:
    """One value of the report, on one line (v1.5.0 review fixes).

    A backslash is written ``\\\\``, a ``|`` ``\\|``; a line feed, carriage
    return or tab ``\\n``, ``\\r``, ``\\t``; any other control character
    (U+0000 to U+001F, U+007F to U+009F) and the line and paragraph
    separators (U+2028, U+2029) ``\\uXXXX``. Nothing a record holds can end a
    table row or start a line of its own. A value is written as itself when it
    is a string, in decimal when it is an integer, ``true`` or ``false``, empty
    when absent, and as canonical JSON otherwise. A number with an integral
    value is written as an integer even when it was read as a float (``1.0`` is
    ``1``), since JSON does not tell the two apart in every language.
    """
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, float) and value.is_integer() and abs(value) < 2**53:
        text = str(int(value))
    elif isinstance(value, (str, int)):
        text = str(value)
    else:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == "|":
            out.append("\\|")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif code < 0x20 or 0x7F <= code <= 0x9F or code in (0x2028, 0x2029):
            out.append(f"\\u{code:04X}")
        else:
            out.append(ch)
    return "".join(out)


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    if not rows:
        return ["None.", ""]
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return [*out, ""]


def report_header(manifest: AuditPackManifest) -> dict[str, Any]:
    """What ``render_report`` reads of a manifest (the NA renders it before the manifest is signed)."""
    return {
        "pack_id": manifest.pack_id, "sovereign_id": manifest.sovereign_id,
        "from_sequence": manifest.from_sequence, "through_sequence": manifest.through_sequence,
        "start_anchor_sequence": manifest.start_anchor_sequence, "end_anchor_sequence": manifest.end_anchor_sequence,
        "created_at": _iso(manifest.created_at), "requested_by": manifest.requested_by,
        "period_from": _iso(manifest.period_from) if manifest.period_from else None,
        "period_until": _iso(manifest.period_until) if manifest.period_until else None,
    }


def render_report(
    *, manifest: Mapping[str, Any], entries: Sequence[EvidenceEvent], checks: Mapping[str, Any],
    states: Mapping[str, Mapping[str, Any]] | None = None, notices: Mapping[str, Any] | None = None,
) -> str:
    """``report.md``: what a reader of the pack sees first (Markdown, deterministic).

    ``manifest`` is ``report_header(manifest)``. ``states`` (the NA's
    remediation states by subject) and ``notices`` (when each actor was told)
    are the NA's operational records at pack time (``states.json``): they are
    reported, not signed, and the report says so. A verifier renders the
    report from the pack's files and compares (``report_mismatch``).
    """
    states = states or {}
    notices = notices or {}
    judgements: dict[tuple[str, str], dict[str, Any]] = {}
    for e in entries:
        if e.entry.entry_kind == "judgement":
            judgements[(str(e.payload.get("subject_kind")), str(e.payload.get("subject_id")))] = e.payload
    period = ""
    if manifest.get("period_from") or manifest.get("period_until"):
        period = (f"- Asked for: {_cell(manifest.get('period_from') or 'the start')} to "
                  f"{_cell(manifest.get('period_until') or 'the last anchor')}")
    lines = [
        f"# Audit pack {_cell(manifest.get('pack_id'))}", "",
        f"- Sovereign: {_cell(manifest.get('sovereign_id'))}",
        f"- Range: store entries {_cell(manifest.get('from_sequence'))} to {_cell(manifest.get('through_sequence'))}, "
        f"ending at anchor {_cell(manifest.get('end_anchor_sequence'))}"
        + (f", starting after anchor {_cell(manifest.get('start_anchor_sequence'))}"
           if manifest.get("start_anchor_sequence") else ""),
        f"- Created: {_cell(manifest.get('created_at'))}" + (f" for {_cell(manifest.get('requested_by'))}"
                                                              if manifest.get("requested_by") else ""),
        *([period] if period else []),
        "",
        "Verify it with `genesis-mesh audit verify <dir> --anchor <root public key> --known-anchors <anchors>`, "
        "from the root key and the anchors you hold. The remediation states and notices below are the "
        "Network Authority's operational records at pack time (states.json), not signed records.", "",
        "## Checks", "",
        f"Verified by the Network Authority when it wrote the pack, against its own anchors: "
        f"**{'yes' if checks.get('verified') else 'no'}**.", "",
    ]
    lines += _table(["Reason", "File", "Entry", "Detail"],
                    [(f.get("reason"), f.get("file"), f.get("store_sequence"), f.get("detail"))
                     for f in checks.get("failures", []) if isinstance(f, dict)])
    counts = checks.get("counts") or {}
    lines += ["## Totals", ""]
    lines += _table(["Records", "Count"], [(k, v) for k, v in sorted(counts.items()) if v])

    changes: list[tuple[Any, ...]] = []
    denials: list[tuple[Any, ...]] = []
    remediations: list[tuple[Any, ...]] = []
    reviews: list[tuple[Any, ...]] = []
    break_glass: list[tuple[Any, ...]] = []
    quarantined: list[tuple[Any, ...]] = []
    others: list[tuple[Any, ...]] = []
    grants: list[tuple[Any, ...]] = []
    grant_revocations: list[tuple[Any, ...]] = []

    def state_of(subject: Any) -> Any:
        value = states.get(str(subject))
        return value.get("state") if isinstance(value, Mapping) else None

    for e in entries:
        p, kind, seq = e.payload, e.entry.entry_kind, e.entry.store_sequence
        if kind == "execution":
            changes.append((seq, kind, p.get("resource_id"), p.get("resource_action"), p.get("executed_at"),
                            "prior_decision", state_of(p.get("decision_id")) or "recorded",
                            p.get("executor_sovereign_id")))
        elif kind == "grant_execution":
            # v1.6.0: a change made under a grant, governed by it.
            changes.append((seq, kind, p.get("resource_id"), p.get("resource_action"), p.get("executed_at"),
                            "grant", "recorded", p.get("executor_sovereign_id")))
        elif kind == "grant":
            grants.append((seq, p.get("grant_id"), p.get("bearer_sovereign_id"), p.get("capabilities"),
                           p.get("valid_from"), p.get("valid_until"), p.get("max_uses")))
        elif kind == "grant_revocation":
            grant_revocations.append((seq, p.get("grant_id"), p.get("reason"), p.get("revoked_at")))
        elif kind in ("observation", "break_glass"):
            record_id = str(p.get("observation_id") or p.get("break_glass_id"))
            judgement = judgements.get((kind, record_id))
            state = state_of(judgement.get("judgement_id")) if judgement else None
            if state is None:
                state = ("observed" if judgement is None else
                         "matched" if judgement.get("governed_by") in ("prior_decision", "grant")
                         and judgement.get("verdict") != "deny" else
                         {"allow": "judged_allowed", "deny": "judged_denied"}.get(str(judgement.get("verdict")),
                                                                                  "indeterminate"))
            changes.append((seq, kind, p.get("resource_id"), p.get("action") or p.get("resource_action"),
                            p.get("changed_at") or p.get("changed_not_after") or p.get("executed_at"),
                            judgement.get("governed_by") if judgement else None, state, p.get("actor")))
            if kind == "break_glass":
                break_glass.append((seq, p.get("resource_id"), p.get("capability"), p.get("executed_at"),
                                    p.get("evaluation_failure"), p.get("justification")))
        elif kind == "decision":
            decision = p.get("decision") or {}
            if decision.get("authorized") is False:
                denials.append((seq, "decision", decision.get("decision_id"), decision.get("denial_reason")))
        elif kind == "judgement" and p.get("verdict") in ("deny", "indeterminate"):
            denials.append((seq, "judgement", p.get("judgement_id"), f"{p.get('verdict')}: {p.get('reason') or ''}"))
        elif kind == "remediation":
            remediations.append((seq, p.get("subject_kind"), p.get("subject_id"), p.get("outcome"), p.get("steps"),
                                 p.get("remediated_at"), p.get("executor_sovereign_id")))
        elif kind == "review":
            reviews.append((seq, p.get("subject_id"), p.get("verdict"), p.get("requested_by"),
                            p.get("requester_holder"), p.get("decided_by"), p.get("decider_holder"),
                            p.get("decided_at")))
        elif kind == "quarantine":
            quarantined.append((seq, p.get("record_kind"), p.get("resource_id"), p.get("rejection_code"),
                                p.get("quarantined_at")))
        elif kind in ("key_succession", "archive"):
            others.append((seq, kind, p.get("succession_id") or p.get("archive_id"),
                           p.get("effective_at") or p.get("archived_at")))
    notice_rows = [(k, v.get("notified_at"), v.get("notified_by")) for k, v in sorted(notices.items())
                   if isinstance(v, Mapping)]
    sections = [
        ("Changes", ["Entry", "Kind", "Resource", "Action", "Changed at", "Governed by", "State", "Actor"], changes),
        ("Denials", ["Entry", "Record", "ID", "Reason"], denials),
        ("Remediations", ["Entry", "Subject kind", "Subject", "Outcome", "Steps", "At", "Executor"], remediations),
        ("Reviews and deciders", ["Entry", "Subject", "Verdict", "Requested by", "Requester holder", "Decided by",
                                  "Decider holder", "Decided at"], reviews),
        ("Notices", ["Subject", "Notified at", "By"], notice_rows),
        ("Break-glass uses", ["Entry", "Resource", "Capability", "Executed at", "Failure", "Justification"],
         break_glass),
        ("Quarantined records", ["Entry", "Record kind", "Resource", "Rejection", "At"], quarantined),
        ("Key successions and archives", ["Entry", "Kind", "ID", "At"], others),
    ]
    # v1.6.0: grants and their revocations, only in a pack that holds them (a pack without them renders as
    # it did in 1.5).
    if grants:
        sections.append(("Grants", ["Entry", "Grant", "Bearer", "Capabilities", "Valid from", "Valid until",
                                    "Budget"], grants))
    if grant_revocations:
        sections.append(("Grant revocations", ["Entry", "Grant", "Reason", "Revoked at"], grant_revocations))
    for title, headers, rows in sections:
        lines += [f"## {title}", ""]
        lines += _table(headers, rows)
    return "\n".join(lines).rstrip("\n") + "\n"
