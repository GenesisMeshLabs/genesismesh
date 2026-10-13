"""Audit packs: verification, the completeness check and the report (v1.5.0, Stage 4).

A pack (``models.audit_pack``, format ``gm.audit.pack`` version 1) holds one
range of the evidence store between two anchors, everything the range's
records cite, the NA's key history and a countersigned manifest. It is
verified offline, with no network and no private key, from material the
security team holds itself: the root public key and its copies of the
anchors. Keys inside the pack prove nothing alone: the NA keys are accepted
only through the key history, from the root key down; executor and observer
keys only through registry records the NA signed (or keys the auditor
supplies).

``verify_audit_pack`` runs these checks, each failure named by a reason code
(``docs/reference/audit-pack-format.md`` lists them with the file each is
reported against):

1. the manifest: present, of this format, countersigned by the NA key valid
   at its ``created_at``; every file it lists present with its SHA-256 and
   size, no file it does not list, every file of the format listed. A pack
   whose manifest fails is not checked further: its files are not the pack;
2. the key history: the genesis block signed by the root key the verifier
   holds, each succession signed by the root key and the outgoing key;
3. the anchors: the pack's anchors signed (by the key valid at each one's
   time) and chained; each one the verifier holds equal to the pack's; the
   range's last entry named by the end anchor, which the verifier holds; the
   range's start tied to entry 1, a retention checkpoint in the range or a
   held start anchor; every held anchor inside the range naming its entry;
4. the entries: exactly the manifest's range, one unbroken store chain, every
   record signed by the key valid at its time (``verify_evidence_events``),
   the chains continuing from the records the pack cites; a record the
   range cites that the pack does not hold fails (``cited_record_missing``);
5. what the records cite outside the store: each policy version a decision
   or judgement was made under, with its digest; each attestation a decision
   rests on, signed by the NA (or by a key a treaty in the pack names), with
   the digest the decision bound; treaties and feeds signed by their issuers;
6. with a changes file, the completeness check (``check_completeness``).

Decisions are judged as of their own time (``at_record_time``): a decision
that expired since it was made and used is not a failure.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from pydantic import ValidationError

from .. import strict_json
from ..crypto import verify_model_signature
from ..models.audit_pack import (
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
    PACK_FILES,
    POLICIES_FILE,
    REPORT_FILE,
    TREATIES_FILE,
    AuditPackManifest,
)
from ..models.boundary_policy import BoundaryPolicy, policy_set_digest
from ..models.context import BoundaryDecision
from ..models.evidence_store import EvidenceEvent, RetentionCheckpoint, StoreAnchor
from ..models.key_succession import NAKeyHistory
from ..models.out_of_band import JudgementRecord, RegistryRecord
from ..models.sovereign import MembershipAttestation, RecognitionTreaty, SovereignRevocationFeed
from ..trust.context import verify_boundary_decision
from ..trust.evidence_store import (
    EvidenceVerification,
    ExecutorKey,
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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _check_manifest(files: Mapping[str, bytes], result: PackVerification) -> AuditPackManifest | None:
    from ..models.canonical_registry import unknown_fields

    raw = files.get(MANIFEST_FILE)
    if raw is None:
        result.fail(MANIFEST_FILE, None, "manifest_missing")
        return None
    try:
        data = _json(raw)
        if isinstance(data, dict) and unknown_fields("AuditPackManifest", data):
            raise ValueError("unknown field")
        manifest = AuditPackManifest.model_validate(data)
    except (ValueError, ValidationError, UnicodeDecodeError, strict_json.StrictJSONError) as exc:
        result.fail(MANIFEST_FILE, None, "manifest_invalid", str(exc)[:200])
        return None
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
        data = files.get(path)
        if data is None:
            result.fail(path, None, "manifest_file_missing")
        elif _sha256(data) != item.sha256 or len(data) != item.bytes:
            result.fail(path, None, "manifest_digest_mismatch")
    for path in sorted(files):
        if path != MANIFEST_FILE and path not in listed:
            result.fail(path, None, "manifest_unlisted_file")
    return manifest


def _signed_at(model: Any, signatures: Sequence[Any], history: NAKeyHistory, at: datetime) -> str | None:
    """None when one of ``signatures`` is by the NA key valid at ``at``; else the reason."""
    keys = history.keys_at(_utc(at))
    if any(verify_model_signature(model, s, k) for s in signatures for k in keys):
        return None
    others = [k for k in history.all_keys() if k not in keys]
    if any(verify_model_signature(model, s, k) for s in signatures for k in others):
        return "na_key_not_valid_at_time"
    return "invalid_signature"


def _registry_keys(events: Iterable[EvidenceEvent], history: NAKeyHistory) -> dict[str, ExecutorKey]:
    """Executor and observer keys from the registry records the NA signed (by the key valid then)."""
    keys: dict[str, ExecutorKey] = {}
    for event in sorted(events, key=lambda e: e.entry.store_sequence):
        if event.entry.entry_kind != "registry":
            continue
        try:
            record = RegistryRecord.model_validate(event.payload)
        except ValidationError:
            continue
        if record.signature is None or _signed_at(record, [record.signature], history,
                                                  event.entry.recorded_at) is not None:
            continue
        if record.event == "executor_key_registered" and record.key_id and record.public_key \
                and record.executor_sovereign_id:
            keys[record.key_id] = ExecutorKey(
                key_id=record.key_id, public_key=record.public_key,
                executor_sovereign_id=record.executor_sovereign_id, role=record.key_role or "executor",
                resource_prefix=record.resource_prefix)
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
) -> PackVerification:
    """Verify an audit pack offline (the module docstring lists the checks).

    ``held_anchors`` are the anchors the verifier holds (``--known-anchors``):
    without them a pack proves the integrity of what it holds, not that
    nothing was removed, and the result says so (``no_held_anchors``).
    ``executor_keys`` are keys the verifier supplies out of band, for a store
    without registry records. ``check_manifest=False`` verifies the files
    before a manifest exists (the NA, writing ``checks.json``).
    """
    result = PackVerification()
    manifest = _check_manifest(files, result) if check_manifest else None

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
        reason = _signed_at(manifest, [manifest.signature] if manifest.signature else [], history,
                            manifest.created_at)
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
    start_anchor = by_sequence.get(manifest.start_anchor_sequence) \
        if manifest and manifest.start_anchor_sequence else None
    if manifest and manifest.start_anchor_sequence and (
            start_anchor is None or start_anchor.store_sequence != first - 1
            or start_anchor.entry_digest != entries[0].entry.prev_entry_digest):
        result.fail(ANCHORS_FILE, first, "pack_start_not_tied", "the start anchor does not name the entry before the range")

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

    if held_anchors is None:
        result.warn(None, None, "no_held_anchors",
                    "verified without anchors held out of band: the pack's integrity, not that nothing was removed")
    else:
        held_chain = verify_store_anchors(list(held_anchors), na_public_keys=history,
                                          sovereign_id=history.sovereign_id)
        for failure in held_chain.failures:
            result.fail("known-anchors", None, failure["reason"], f"held anchor {failure['anchor_sequence']}")
        held = {a.anchor_sequence: a for a in held_anchors}
        for anchor in pack_anchors:
            mine = held.get(anchor.anchor_sequence)
            if mine is not None and mine.to_wire() != anchor.to_wire():
                result.fail(ANCHORS_FILE, anchor.store_sequence, "anchor_mismatch",
                            f"anchor {anchor.anchor_sequence} differs from the one held")
        if end is not None and end.anchor_sequence not in held:
            result.fail(ANCHORS_FILE, last, "pack_end_anchor_not_held",
                        f"anchor {end.anchor_sequence} is not among the anchors held")
        if start_anchor is not None and start_anchor.anchor_sequence not in held and start_checkpoint is None \
                and first != 1:
            result.fail(ANCHORS_FILE, first, "pack_start_anchor_not_held",
                        f"anchor {start_anchor.anchor_sequence} is not among the anchors held")
        inside = [a for a in held_anchors if a.store_sequence <= last]
        tied = EvidenceVerification()
        check_events_against_anchors(entries, inside, tied, from_anchor=True)
        for failure in tied.failures:
            result.fail(ENTRIES_FILE, failure["store_sequence"], failure["reason"], failure["detail"])
        result.anchors = tied.anchors

    # 4. Executor keys: from registry records the NA signed, and keys supplied out of band.
    keys = _registry_keys([*cited, *entries], history)
    keys.update(executor_keys or {})
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

    # 6. Completeness.
    if changes is not None:
        end_time = end.anchored_at if end is not None else entries[-1].entry.recorded_at
        result.completeness = check_completeness(
            changes, entries, cited, period=(_utc(entries[0].entry.recorded_at), _utc(end_time)), tolerance=tolerance)
        for item in result.completeness["unmatched_changes"]:
            result.fail("changes", None, "change_unmatched",
                        f"{item['source'] or '-'} {item['source_event_id'] or '-'} {item['resource_id']} "
                        f"{item['action']} {item['changed_at']}")
    return result


def _check_cited_trust(
    files: Mapping[str, bytes], entries: Sequence[EvidenceEvent], cited: Sequence[EvidenceEvent],
    history: NAKeyHistory, result: PackVerification,
) -> None:
    """Policies, attestations, treaties and feeds the records rest on (outside the store)."""
    try:
        policies = [BoundaryPolicy.model_validate(p) for p in _jsonl(files[POLICIES_FILE])]
        attestations = [MembershipAttestation.model_validate(a) for a in _jsonl(files[ATTESTATIONS_FILE])]
        treaties = [RecognitionTreaty.model_validate(t) for t in _jsonl(files[TREATIES_FILE])]
        feeds = [SovereignRevocationFeed.model_validate(f) for f in _jsonl(files[FEEDS_FILE])]
    except (KeyError, ValueError, ValidationError, UnicodeDecodeError) as exc:
        result.fail(POLICIES_FILE, None, "cited_trust_invalid", str(exc)[:200])
        return
    by_version: dict[tuple[str, int], BoundaryPolicy] = {}
    for policy in policies:
        reason = _signed_at(policy, [policy.signature] if policy.signature else [], history, policy.issued_at)
        if reason is not None:
            result.fail(POLICIES_FILE, None, "policy_invalid_signature" if reason == "invalid_signature" else reason,
                        f"{policy.policy_id} v{policy.version}")
        by_version[(policy.policy_id, policy.version)] = policy
    own = history.sovereign_id
    issuer_keys: dict[str, list[str]] = {}
    for treaty in treaties:
        reason = _signed_at(treaty, treaty.signatures, history, treaty.issued_at)
        if reason is not None:
            result.fail(TREATIES_FILE, None, "treaty_invalid_signature" if reason == "invalid_signature" else reason,
                        treaty.treaty_id)
            continue
        issuer_keys.setdefault(treaty.subject_sovereign_id, []).extend(treaty.subject_public_keys)
    by_attestation: dict[str, MembershipAttestation] = {}
    for attestation in attestations:
        if attestation.issuer_sovereign_id == own:
            reason = _signed_at(attestation, attestation.signatures, history, attestation.issued_at)
        else:
            keys = issuer_keys.get(attestation.issuer_sovereign_id, [])
            reason = None if any(verify_model_signature(attestation, s, k) for s in attestation.signatures
                                 for k in keys) else "invalid_signature"
        if reason is not None:
            result.fail(ATTESTATIONS_FILE, None,
                        "attestation_invalid_signature" if reason == "invalid_signature" else reason,
                        attestation.attestation_id)
        by_attestation[attestation.attestation_id] = attestation
    for feed in feeds:
        keys = issuer_keys.get(feed.issuer_sovereign_id, [])
        if not any(verify_model_signature(feed, s, k) for s in feed.signatures for k in keys):
            result.fail(FEEDS_FILE, None, "feed_invalid_signature", feed.feed_id)

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
) -> tuple[dict[str, bytes], AuditPackManifest]:
    """Every file of a pack (``PACK_FORMAT`` version 1) and its signed manifest.

    ``trust`` maps ``policies.jsonl`` and the ``trust/`` files to their
    records. ``checks.json`` is this module's verification of the files with
    ``held_anchors`` (the NA's own anchors), ``report.md`` the report;
    ``sign(manifest)`` returns the manifest's signature (the NA key). The
    bytes depend only on the arguments, so a pack is reproducible.
    """
    from ..models.audit_pack import PackFile, canonical_bytes, jsonl_bytes

    files: dict[str, bytes] = {
        GENESIS_FILE: canonical_bytes(dict(genesis)),
        KEY_HISTORY_FILE: canonical_bytes({"successions": [dict(s) for s in successions]}),
        EXECUTOR_KEYS_FILE: canonical_bytes({"executor_keys": [dict(k) for k in executor_keys]}),
        ANCHORS_FILE: jsonl_bytes([a.to_wire() for a in anchors]),
        ENTRIES_FILE: "".join(e.to_json_line() + "\n" for e in entries).encode("utf-8"),
        CITED_FILE: "".join(e.to_json_line() + "\n" for e in cited).encode("utf-8"),
    }
    for path in (POLICIES_FILE, ATTESTATIONS_FILE, TREATIES_FILE, FEEDS_FILE):
        files[path] = jsonl_bytes([dict(r) for r in trust.get(path, [])])
    root = str(genesis.get("root_public_key"))
    checks = verify_audit_pack(files, root_public_key=root, held_anchors=held_anchors, check_manifest=False).to_dict()
    files[CHECKS_FILE] = canonical_bytes(checks)
    header = {"pack_id": pack_id, "sovereign_id": genesis.get("network_name"), "from_sequence":
              entries[0].entry.store_sequence if entries else None,
              "through_sequence": entries[-1].entry.store_sequence if entries else None,
              "start_anchor_sequence": start_anchor_sequence, "end_anchor_sequence": end_anchor_sequence,
              "created_at": created_at.isoformat(), "requested_by": requested_by}
    files[REPORT_FILE] = render_report(manifest=header, entries=entries, checks=checks, states=states,
                                       notices=notices).encode("utf-8")
    manifest = AuditPackManifest(
        pack_id=pack_id, sovereign_id=str(genesis.get("network_name")), created_at=created_at,
        requested_by=requested_by, from_sequence=entries[0].entry.store_sequence,
        through_sequence=entries[-1].entry.store_sequence, start_anchor_sequence=start_anchor_sequence,
        end_anchor_sequence=end_anchor_sequence,
        files=[PackFile(path=path, sha256=_sha256(body), bytes=len(body)) for path, body in sorted(files.items())],
        issued_by=issued_by,
    )
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
                "changed_at": self.changed_at.isoformat(), "actor": self.actor}


CHANGE_COLUMNS = ("source", "source_event_id", "resource_id", "action", "changed_at", "actor")


def parse_changes(text: str, *, csv_format: bool) -> list[Change]:
    """Changes from CSV (a header row naming ``CHANGE_COLUMNS``) or JSON (a list, or ``{"changes": [...]}``).

    ``resource_id``, ``action`` and ``changed_at`` (ISO 8601 with an offset)
    are required; ``source`` and ``source_event_id`` go together. Raises
    ``ValueError`` naming the first bad row.
    """
    if csv_format:
        rows: list[Any] = list(csv.DictReader(io.StringIO(text)))
    else:
        data = json.loads(text)
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
            return str(raw).strip() if raw not in (None, "") else None

        resource, action, changed = value("resource_id"), value("action"), value("changed_at")
        if not resource or not action or not changed:
            raise ValueError(f"change {i}: resource_id, action and changed_at are required")
        try:
            at = datetime.fromisoformat(changed.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"change {i}: changed_at is not an ISO 8601 time") from None
        if at.tzinfo is None:
            raise ValueError(f"change {i}: changed_at needs an offset (Z for UTC)")
        source, event_id = value("source"), value("source_event_id")
        if (source is None) != (event_id is None):
            raise ValueError(f"change {i}: source and source_event_id go together")
        out.append(Change(index=i, resource_id=resource, action=action, changed_at=at.astimezone(timezone.utc),
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
        except (KeyError, TypeError, ValueError):
            continue
    # A governed change seen by an observer is one change: the observation and what it matched.
    for record in records:
        record.group = matched.get(record.record_id, record.record_id)
    return records


def check_completeness(
    changes: Sequence[Change], entries: Sequence[EvidenceEvent], cited: Sequence[EvidenceEvent] = (),
    *, period: tuple[datetime, datetime], tolerance: timedelta = DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    """Match changes from an outside log against the pack's records.

    First by source and source event ID (an observation of that very event),
    then by resource, action and time within ``tolerance`` (the closest
    record, each record matched once; an observation and the execution
    evidence it was matched to are one change). An unmatched change dated
    inside the pack's period is ``unmatched_changes`` (the store does not
    record it); one outside the period is ``outside_period``. Records no
    change matched are ``unmatched_records`` (the log may not cover every
    source).
    """
    records = _records(entries, cited)
    used: set[str] = set()
    pairs: list[dict[str, Any]] = []
    left: list[Change] = []
    by_event = {(str(r.source), str(r.source_event_id)): r for r in records if r.source and r.source_event_id}
    for change in changes:
        record = by_event.get((change.source, str(change.source_event_id))) if change.source else None
        if record is not None and record.group not in used:
            used.add(record.group)
            pairs.append({"change": change.index, "kind": record.kind, "record_id": record.record_id,
                          "store_sequence": record.store_sequence, "matched_by": "source_event_id"})
        else:
            left.append(change)
    unmatched: list[Change] = []
    for change in left:
        candidates = [r for r in records if r.group not in used and r.resource_id == change.resource_id
                      and r.action == change.action and r.distance(change.changed_at) <= tolerance]
        if not candidates:
            unmatched.append(change)
            continue
        record = min(candidates, key=lambda r: (r.distance(change.changed_at), r.store_sequence))
        used.add(record.group)
        pairs.append({"change": change.index, "kind": record.kind, "record_id": record.record_id,
                      "store_sequence": record.store_sequence, "matched_by": "resource_action_time"})
    start, end = period
    inside = [c for c in unmatched if start - tolerance <= c.changed_at <= end + tolerance]
    outside = [c for c in unmatched if c not in inside]
    unmatched_records = sorted({r.group: r for r in records if r.group not in used}.values(),
                               key=lambda r: r.store_sequence)
    return {
        "changes": len(changes), "tolerance_seconds": int(tolerance.total_seconds()),
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "pairs": sorted(pairs, key=lambda p: p["change"]),
        "unmatched_changes": [c.to_dict() for c in inside],
        "outside_period": [c.to_dict() for c in outside],
        "unmatched_records": [{"kind": r.kind, "record_id": r.record_id, "store_sequence": r.store_sequence,
                               "resource_id": r.resource_id, "action": r.action} for r in unmatched_records],
        "complete": not inside,
    }


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    if not rows:
        return ["None.", ""]
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return [*out, ""]


def render_report(
    *, manifest: Mapping[str, Any], entries: Sequence[EvidenceEvent], checks: Mapping[str, Any],
    states: Mapping[str, Mapping[str, Any]] | None = None, notices: Mapping[str, Any] | None = None,
) -> str:
    """``report.md``: what a reader of the pack sees first (Markdown, deterministic).

    ``states`` (the NA's remediation states by subject) and ``notices`` (when
    each actor was told) are the NA's operational records at pack time: they
    are reported, not signed, and the report says so.
    """
    states = states or {}
    notices = notices or {}
    judgements: dict[tuple[str, str], dict[str, Any]] = {}
    for e in entries:
        if e.entry.entry_kind == "judgement":
            judgements[(str(e.payload.get("subject_kind")), str(e.payload.get("subject_id")))] = e.payload
    lines = [
        f"# Audit pack {manifest.get('pack_id')}", "",
        f"- Sovereign: {manifest.get('sovereign_id')}",
        f"- Range: store entries {manifest.get('from_sequence')} to {manifest.get('through_sequence')}, "
        f"ending at anchor {manifest.get('end_anchor_sequence')}"
        + (f", starting after anchor {manifest.get('start_anchor_sequence')}"
           if manifest.get("start_anchor_sequence") else ""),
        f"- Created: {manifest.get('created_at')}" + (f" for {manifest.get('requested_by')}"
                                                      if manifest.get("requested_by") else ""),
        "",
        "Verify it with `genesis-mesh audit verify <dir> --anchor <root public key> --known-anchors <anchors>`, "
        "from the root key and the anchors you hold. The remediation states and notices below are the "
        "Network Authority's operational records at pack time, not signed records.", "",
        "## Checks", "",
        f"Verified by the Network Authority when it wrote the pack, against its own anchors: "
        f"**{'yes' if checks.get('verified') else 'no'}**.", "",
    ]
    lines += _table(["Reason", "File", "Entry", "Detail"],
                    [(f.get("reason"), f.get("file"), f.get("store_sequence"), f.get("detail"))
                     for f in checks.get("failures", [])])
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
    for e in entries:
        p, kind, seq = e.payload, e.entry.entry_kind, e.entry.store_sequence
        if kind == "execution":
            state = states.get(str(p.get("decision_id")), {}).get("state", "recorded")
            changes.append((seq, kind, p.get("resource_id"), p.get("resource_action"), p.get("executed_at"),
                            "prior_decision", state, p.get("executor_sovereign_id")))
        elif kind in ("observation", "break_glass"):
            record_id = str(p.get("observation_id") or p.get("break_glass_id"))
            judgement = judgements.get((kind, record_id))
            state = states.get(str(judgement.get("judgement_id")), {}).get("state") if judgement else None
            if state is None:
                state = ("observed" if judgement is None else
                         "matched" if judgement.get("governed_by") == "prior_decision"
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
    sections = [
        ("Changes", ["Entry", "Kind", "Resource", "Action", "Changed at", "Governed by", "State", "Actor"], changes),
        ("Denials", ["Entry", "Record", "ID", "Reason"], denials),
        ("Remediations", ["Entry", "Subject kind", "Subject", "Outcome", "Steps", "At", "Executor"], remediations),
        ("Reviews and deciders", ["Entry", "Subject", "Verdict", "Requested by", "Requester holder", "Decided by",
                                  "Decider holder", "Decided at"], reviews),
        ("Notices", ["Subject", "Notified at", "By"],
         [(k, v.get("notified_at"), v.get("notified_by")) for k, v in sorted(notices.items())]),
        ("Break-glass uses", ["Entry", "Resource", "Capability", "Executed at", "Failure", "Justification"],
         break_glass),
        ("Quarantined records", ["Entry", "Record kind", "Resource", "Rejection", "At"], quarantined),
        ("Key successions and archives", ["Entry", "Kind", "ID", "At"], others),
    ]
    for title, headers, rows in sections:
        lines += [f"## {title}", ""]
        lines += _table(headers, rows)
    return "\n".join(lines).rstrip("\n") + "\n"
