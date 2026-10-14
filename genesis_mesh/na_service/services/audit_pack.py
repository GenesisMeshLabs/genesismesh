"""Audit packs and archives (v1.5.0, Stage 4).

``build`` writes one range of the store between two anchors as an audit pack
(``models.audit_pack``): the entries, everything their records cite, the key
history, the trust material decisions rest on, the NA's own verification of
it (``checks.json``), a Markdown report, and the manifest the NA signs. A
read-tier key may ask for one: a pack holds what the read routes serve.

``record_archive`` records that a pack was written to immutable storage and
read back intact (entry kind ``archive``); retention removes only what
archive records cover while ``NA_RETENTION_REQUIRE_ARCHIVE`` is on.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError as PydanticValidationError

from ...models.audit_pack import (
    AGREEMENTS_FILE,
    ATTESTATIONS_FILE,
    CHECKS_FILE,
    FEEDS_FILE,
    MANIFEST_FILE,
    POLICIES_FILE,
    TREATIES_FILE,
    ArchiveRecord,
    AuditPackManifest,
)
from ...models.evidence_store import EvidenceEvent, StoreAnchor
from ...trust.evidence_store import build_entry
from ...workflows.audit_pack import compose_pack
from ..errors import BadRequestError, ConflictError, ServiceUnavailableError, ValidationError

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService

#: The largest range one pack holds; a longer period is several packs, chained by their anchors.
MAX_PACK_ENTRIES = 50_000


def _event(stored: dict[str, Any]) -> EvidenceEvent:
    return EvidenceEvent(entry=stored["entry"], entry_digest=stored["entry_digest"], payload=stored["payload"])


def _int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BadRequestError(f"{name} must be a positive integer", code="invalid_audit_pack")
    return value


def _time(value: Any, name: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise BadRequestError(f"{name} must be an ISO 8601 time", code="invalid_audit_pack") from None
    if parsed.tzinfo is None:
        raise BadRequestError(f"{name} needs an offset (Z for UTC)", code="invalid_audit_pack")
    return parsed.astimezone(timezone.utc)


class AuditPackService:
    """Build audit packs and record archives."""

    def __init__(self, na: "NetworkAuthorityService") -> None:
        self._na = na

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    # -- the range ----------------------------------------------------------------

    def _range(self, data: dict[str, Any]) -> tuple[int, int, StoreAnchor | None, StoreAnchor]:
        """(first, last, start anchor or None, end anchor): the range widens to the anchors around it."""
        db = self._na.db
        store = self._na.evidence_store_service
        from_sequence = _int(data.get("from_sequence"), "from_sequence")
        until_sequence = _int(data.get("until_sequence"), "until_sequence")
        since, until = _time(data.get("since"), "since"), _time(data.get("until"), "until")
        start_of_store = store.store_start()
        anchors = db.list_store_anchors(limit=10**9)
        candidates = [a for a in anchors if a.store_sequence >= start_of_store
                      and (until_sequence is None or a.store_sequence <= until_sequence)
                      and (until is None or a.anchored_at <= until)]
        if not candidates:
            raise ConflictError("no anchor ends the range: anchor the store first (POST /admin/evidence/anchors)",
                                code="audit_pack_not_anchored")
        end = candidates[-1]
        want = max(start_of_store, from_sequence or start_of_store)
        if since is not None:
            first = db.first_sequence_since(since.isoformat())
            want = max(want, first if first is not None else end.store_sequence + 1)
        if want > end.store_sequence:
            raise BadRequestError("the range is empty: it starts after the last anchor it may end at",
                                  code="invalid_audit_pack")
        before = [a for a in anchors if start_of_store - 1 <= a.store_sequence < want]
        start = before[-1].store_sequence + 1 if before else start_of_store
        start_anchor = before[-1] if before else None
        if end.store_sequence - start + 1 > MAX_PACK_ENTRIES:
            raise ConflictError(
                f"the range holds {end.store_sequence - start + 1} entries, more than {MAX_PACK_ENTRIES}: "
                "make several packs, each between two anchors", code="audit_pack_too_large")
        return start, end.store_sequence, start_anchor, end

    # -- what the range cites ---------------------------------------------------

    def _cited(self, entries: list[dict[str, Any]], start: int) -> list[dict[str, Any]]:
        """Store entries before the range that the range's records rest on (see the pack format)."""
        db = self._na.db
        found: dict[int, dict[str, Any]] = {}

        def keep(stored: dict[str, Any] | None) -> dict[str, Any] | None:
            if stored is None or stored["entry"].store_sequence >= start:
                return None
            seq = stored["entry"].store_sequence
            if seq in found:
                return None
            found[seq] = stored
            return stored

        def lookup(kind: str, record_id: str | None) -> dict[str, Any] | None:
            if not record_id:
                return None
            if kind == "decision":
                return db.get_decision_entry(record_id)
            if kind == "execution":
                return db.get_entry_by_evidence_id(record_id)
            if kind == "grant_revocation_of":  # v1.6.0: a grant's revocation, by its grant
                return db.grant_revocation_entry(record_id)
            return db.get_entry_by_record(kind, record_id)

        def refs(stored: dict[str, Any]) -> list[tuple[str, str | None]]:
            kind, p = stored["entry"].entry_kind, stored["payload"]
            if kind == "execution":
                return [("decision", p.get("decision_id"))]
            if kind == "judgement":
                return [(str(p.get("subject_kind")), p.get("subject_id")),
                        ("execution", p.get("matched_evidence_id")), ("break_glass", p.get("matched_evidence_id")),
                        ("grant_execution", p.get("matched_evidence_id"))]
            if kind == "remediation":
                return [(str(p.get("subject_kind")), p.get("subject_id")),
                        (str(p.get("change_kind")), p.get("change_id")), ("execution", p.get("rotation_evidence_id"))]
            if kind == "review":
                return [(str(p.get("subject_kind")), p.get("subject_id"))]
            # v1.6.0: a grant use rests on its grant and is checked against its revocation; a judgement
            # may match a grant use.
            if kind == "grant_execution":
                return [("grant", p.get("grant_id")), ("grant_revocation_of", p.get("grant_id"))]
            if kind == "grant_revocation":
                return [("grant", p.get("grant_id"))]
            return []

        queue = list(entries)
        while queue:
            nxt: list[dict[str, Any]] = []
            for stored in queue:
                for kind, record_id in refs(stored):
                    added = keep(lookup(kind, record_id))
                    if added is not None:
                        nxt.append(added)
            queue = nxt
        # The heads the range's chains continue from: per decision, per resource (v1.6.0: execution evidence
        # or a grant use), per observed resource, per grant.
        decisions = {s["entry"].decision_id for s in entries if s["entry"].entry_kind == "execution"}
        resources = {s["entry"].resource_id for s in entries
                     if s["entry"].entry_kind in ("execution", "grant_execution") and s["entry"].resource_id}
        granted = {s["entry"].subject_id for s in entries if s["entry"].entry_kind == "grant_execution"}
        # v1.6.0 review fixes: and a quarantined use's grant (it may be its chain's head).
        granted |= {s["payload"]["record"].get("grant_id") for s in entries if s["entry"].entry_kind == "quarantine"
                    and s["payload"].get("record_kind") == "grant_execution" and isinstance(s["payload"].get("record"), dict)}
        observed = {s["entry"].resource_id for s in entries if s["entry"].entry_kind == "observation"
                    and s["entry"].resource_id}
        for decision_id in sorted(d for d in decisions if d):
            keep(db.last_entry_before("execution", "decision_id", decision_id, start))
        for resource_id in sorted(r for r in resources if r):
            keep(db.last_resource_entry_before(resource_id, start))
        for grant_id in sorted(g for g in granted if isinstance(g, str) and g):
            # v1.6.0 review fixes: the grant's whole chain before the range (its uses, and the quarantined
            # uses that continued it), so the budget, the time-token heads and the chain are checked.
            keep(db.get_entry_by_record("grant", grant_id))
            for stored in db.grant_chain_entries_before(grant_id, start):
                keep(stored)
        for resource_id in sorted(r for r in observed if r):
            keep(db.last_entry_before("observation", "resource_id", resource_id, start))
        # The registry and key history before the range, and the latest retention checkpoint.
        for stored in db.entries_of_kinds_before(("registry", "key_succession", "archive"), start):
            keep(stored)
        checkpoints = db.entries_of_kinds_before(("retention_checkpoint",), start)
        if checkpoints:
            keep(checkpoints[-1])
        return [found[seq] for seq in sorted(found)]

    def _trust_material(self, events: list[EvidenceEvent]) -> dict[str, list[dict[str, Any]]]:
        """Policies, attestations, treaties and feeds the records rest on."""
        db = self._na.db
        own = self._na.genesis_block.network_name
        versions: set[tuple[str, int]] = set()
        attestation_ids: set[str] = set()
        agreements: dict[str, Any] = {}
        parties: set[str] = set()
        for event in events:
            kind, p = event.entry.entry_kind, event.payload
            binding = None
            if kind == "decision":
                decision = p.get("decision") or {}
                binding = decision.get("policy_binding")
                att = decision.get("attestation_binding") or {}
                for value in (att.get("attestation_id"), (p.get("context") or {}).get("attestation_id")):
                    if value:
                        attestation_ids.add(str(value))
            elif kind == "judgement":
                binding = p.get("policy_binding")
            elif kind == "break_glass" and p.get("attestation_id"):
                attestation_ids.add(str(p["attestation_id"]))
            elif kind == "grant":
                # v1.6.0: the policy versions a grant is bound to, and its basis attestation (review fixes:
                # or agreement, with the treaties of its parties).
                binding = p.get("policy_binding")
                if p.get("basis_kind") == "attestation" and p.get("basis_id"):
                    attestation_ids.add(str(p["basis_id"]))
                elif p.get("basis_kind") == "agreement" and p.get("grant_id"):
                    row = db.get_grant_row(str(p["grant_id"]))
                    if row is not None and row["basis_json"]:
                        agreements[str(p["basis_id"])] = json.loads(row["basis_json"])
            elif kind == "registry" and p.get("event") == "policy_activated" and p.get("policy_id") \
                    and p.get("policy_version"):
                versions.add((str(p["policy_id"]), int(p["policy_version"])))
            for applied in (binding or {}).get("policies", []) if isinstance(binding, dict) else []:
                versions.add((str(applied.get("policy_id")), int(applied.get("version") or 0)))
        policies = []
        for policy_id, version in sorted(versions):
            row = db.get_boundary_policy_row(policy_id, version)
            policy = db.parse_boundary_policy_row(row) if row else None
            if policy is not None:
                policies.append(policy.model_dump(mode="json"))
        attestations, issuers = [], set()
        for attestation_id in sorted(attestation_ids):
            row = db.get_membership_attestation(attestation_id)
            if row is not None:
                attestations.append(row["attestation"].model_dump(mode="json"))
                if row["attestation"].issuer_sovereign_id != own:
                    issuers.add(row["attestation"].issuer_sovereign_id)
        for agreement in agreements.values():
            for party in (agreement.get("offerer_sovereign_id"), agreement.get("responder_sovereign_id")):
                if isinstance(party, str) and party != own:
                    parties.add(party)
        treaties, feeds = [], []
        for party in sorted(parties - issuers):
            treaties += [r["treaty"].model_dump(mode="json")
                         for r in db.list_recognition_treaties(issuer_sovereign_id=own, subject_sovereign_id=party)]
        for issuer in sorted(issuers):
            treaties += [r["treaty"].model_dump(mode="json")
                         for r in db.list_recognition_treaties(issuer_sovereign_id=own, subject_sovereign_id=issuer)]
            feeds += [r["feed"].model_dump(mode="json") for r in db.list_sovereign_revocation_feeds(issuer)]
        return {POLICIES_FILE: policies, ATTESTATIONS_FILE: attestations, TREATIES_FILE: treaties, FEEDS_FILE: feeds,
                AGREEMENTS_FILE: [agreements[k] for k in sorted(agreements)]}

    # -- the pack ------------------------------------------------------------------

    def build(self, data: dict[str, Any], requested_by: str | None) -> dict[str, Any]:
        """``POST /admin/evidence/audit-pack``: the pack's files (as text) and its signed manifest."""
        store = self._na.evidence_store_service
        store.require_enabled()
        db = self._na.db
        start, through, start_anchor, end = self._range(data)
        rows = db.search_evidence({}, after_sequence=start - 1, limit=through - start + 1)
        if len(rows) != through - start + 1 or rows[0]["entry"].store_sequence != start:
            raise ConflictError("the store does not hold every entry of the range", code="evidence_store_incomplete")
        entries = [_event(r) for r in rows]
        cited_rows = self._cited(rows, start)
        cited = [_event(r) for r in cited_rows]
        anchors = [a for a in db.list_store_anchors(limit=10**9)
                   if start - 1 <= a.store_sequence <= through and a.anchor_sequence <= end.anchor_sequence]
        history = self._na.key_history.public_view()
        subjects = sorted({str(e.payload.get("judgement_id")) for e in entries if e.entry.entry_kind == "judgement"}
                          | {str(e.entry.decision_id) for e in entries if e.entry.decision_id})
        states = self._na.remediation_service.states_for(subjects) if self._na.remediation_service.enabled else {}
        files, manifest = compose_pack(
            genesis=self._na.genesis_block.model_dump(mode="json"), successions=history["successions"],
            executor_keys=store.list_executor_keys(), anchors=anchors, entries=entries, cited=cited,
            trust=self._trust_material([*cited, *entries]), held_anchors=db.list_store_anchors(limit=10**9),
            pack_id=str(uuid.uuid4()), created_at=self._now(), requested_by=requested_by,
            start_anchor_sequence=start_anchor.anchor_sequence if start_anchor else None,
            end_anchor_sequence=end.anchor_sequence, issued_by=self._na.key_id, sign=self._na.signer.sign_model,
            states=states, notices={k: v for k, v in states.items() if v.get("notified_at")},
            check_executor_keys=store.executor_keys(),
            period_from=_time(data.get("since"), "since"), period_until=_time(data.get("until"), "until"),
        )
        checks = json.loads(files[CHECKS_FILE])
        pack_id = manifest.pack_id
        # v1.5.0 review fixes: the NA records each pack it builds, so an archive names one of them.
        db.add_audit_pack_row({
            "pack_id": pack_id, "manifest_sha256": hashlib.sha256(files[MANIFEST_FILE]).hexdigest(),
            "from_sequence": start, "through_sequence": through, "end_anchor_sequence": end.anchor_sequence,
            "verified": 1 if checks["verified"] else 0, "built_at": manifest.created_at.isoformat(),
            "requested_by": requested_by,
        })
        db.add_audit_event("audit_pack_built", {
            "pack_id": pack_id, "from_sequence": start, "through_sequence": through,
            "end_anchor_sequence": end.anchor_sequence, "requested_by": requested_by,
            "verified": checks["verified"],
        })
        return {"manifest": manifest.to_wire(),
                "files": {path: body.decode("utf-8") for path, body in files.items() if path != MANIFEST_FILE}}

    # -- archives ------------------------------------------------------------------

    def record_archive(self, data: dict[str, Any], recorded_by: str) -> tuple[dict[str, Any], int]:
        """``POST /admin/evidence/archives``: a pack this NA built, written and read back intact."""
        from ...models.canonical_registry import unknown_fields

        store = self._na.evidence_store_service
        store.require_enabled()
        raw, location = data.get("manifest"), data.get("location")
        if not isinstance(raw, dict) or not isinstance(location, str) or not 1 <= len(location) <= 1024:
            raise BadRequestError("manifest (the pack's manifest.json) and location (1 to 1024 characters) "
                                  "are required", code="invalid_archive")
        if unknown_fields("AuditPackManifest", raw):
            raise BadRequestError("the manifest has fields this release does not know", code="invalid_archive")
        try:
            manifest = AuditPackManifest.model_validate(raw)
        except PydanticValidationError as exc:
            raise BadRequestError("manifest is not an audit pack manifest", code="invalid_archive") from exc
        from ...workflows.audit_pack import received_signature_reason

        # v1.5.0 review fixes: signed as received, by the key valid when the pack was built.
        if received_signature_reason("AuditPackManifest", raw, self._na.key_history.history(),
                                     manifest.created_at) is not None \
                or manifest.sovereign_id != self._na.genesis_block.network_name:
            raise ValidationError("the manifest is not signed by this Network Authority", code="archive_manifest_invalid")
        end = next((a for a in self._na.db.list_store_anchors(after_anchor=manifest.end_anchor_sequence - 1, limit=1)),
                   None)
        if end is None or end.anchor_sequence != manifest.end_anchor_sequence \
                or end.store_sequence != manifest.through_sequence:
            raise ConflictError("the manifest's end anchor is not this NA's anchor of its last entry",
                                code="archive_anchor_mismatch")
        manifest_sha256 = hashlib.sha256(manifest.file_bytes()).hexdigest()
        # v1.5.0 review fixes: only a pack this NA built, as it built it, whose own checks passed.
        built = self._na.db.get_audit_pack_row(manifest.pack_id)
        if built is None or built["manifest_sha256"] != manifest_sha256:
            raise ConflictError("this NA did not build a pack with this manifest", code="archive_pack_unknown")
        if not built["verified"]:
            raise ConflictError("the pack failed the checks the NA ran when it built it (checks.json): an archive "
                                "records only a pack that verified", code="archive_pack_unverified")
        existing = next((r for r in self._na.db.list_archive_rows() if r["pack_id"] == manifest.pack_id), None)
        if existing is not None:
            if existing["manifest_sha256"] != manifest_sha256:
                raise ConflictError("another manifest with this pack ID is archived", code="archive_conflict")
            return {"status": "duplicate", "archive": json.loads(existing["record_json"]),
                    "archived_through_sequence": store.archived_through()}, 200
        covered = store.archived_through()
        if manifest.from_sequence > covered + 1:
            raise ConflictError(
                f"archives must cover the store without a gap: this pack starts at {manifest.from_sequence}, "
                f"archives cover through {covered}", code="archive_not_contiguous")
        now = self._now()
        record = ArchiveRecord(
            pack_id=manifest.pack_id, from_sequence=manifest.from_sequence,
            through_sequence=manifest.through_sequence, through_entry_digest=end.entry_digest,
            end_anchor_sequence=end.anchor_sequence, manifest_sha256=manifest_sha256, location=location,
            archived_at=now, recorded_by=recorded_by, issuer_sovereign_id=self._na.genesis_block.network_name,
            issued_by=self._na.key_id,
        )
        record = record.model_copy(update={"signature": self._na.signer.sign_model(record)})
        payload = record.to_wire()
        row = {
            "archive_id": record.archive_id, "pack_id": record.pack_id, "from_sequence": record.from_sequence,
            "through_sequence": record.through_sequence, "through_entry_digest": record.through_entry_digest,
            "end_anchor_sequence": record.end_anchor_sequence, "manifest_sha256": manifest_sha256,
            "location": location, "archived_at": now.isoformat(), "recorded_by": recorded_by,
            "record_json": json.dumps(payload, sort_keys=True, separators=(",", ":")),
        }

        def make(db: Any) -> list[Any]:
            db.insert_archive_row(row)
            return [(lambda seq, prev: build_entry(
                store_sequence=seq, entry_kind="archive", recorded_at=now, payload=payload,
                prev_entry_digest=prev, index={"record_id": record.archive_id}), payload)]

        try:
            self._na.db.append_evidence_entries_with(make)
        except self._na.db.integrity_errors as exc:
            raise ConflictError("this archive is already recorded", code="archive_conflict") from exc
        except self._na.db.database_errors as exc:
            raise ServiceUnavailableError("The archive could not be stored", code="evidence_store_unavailable") from exc
        self._na.db.add_audit_event("evidence_archived", {
            "archive_id": record.archive_id, "pack_id": record.pack_id, "from_sequence": record.from_sequence,
            "through_sequence": record.through_sequence, "location": location, "recorded_by": recorded_by,
        })
        store.maybe_anchor()
        return {"status": "recorded", "archive": payload, "archived_through_sequence": store.archived_through()}, 201

    def list_archives(self) -> dict[str, Any]:
        store = self._na.evidence_store_service
        store.require_enabled()
        rows = self._na.db.list_archive_rows()
        return {"archives": [json.loads(r["record_json"]) for r in rows],
                "archived_through_sequence": store.archived_through(),
                "require_archive": self._na.retention_require_archive}

