"""Remediation, reviews and emergency changes (v1.4.0, Stage 3): the NA side.

Routes in ``routes/remediation.py`` parse HTTP and call this service. The NA
states the remediation and the controller performs it (Decision 1 of the
1.4.0 plan):

* a judged DENY (or ``indeterminate``) arms a remediation: what to do
  (``trust.remediation.remediation_plan``) and when it is due
  (``remediation_due_at = judged_at + grace``);
* a judgement flagged for review, and a change allowed under a policy that
  requires review (an emergency policy always does), opens a review; a
  second holder decides it, and the NA records the decision as a signed
  ``ReviewRecord`` with the requester's and decider's signed requests
  embedded;
* the controller submits a ``RemediationRecord`` signed by its executor key
  once it has cancelled the change (or alerted), and records through the
  NA that it told the actor (an audit event and ``notified_at``);
* due times are swept: an overdue remediation raises one audit event, a
  waiver's end and an emergency change's end of life re-arm remediation.

A pending review is a flag beside the state, never a state of its own: it
stops no clock (review fixes, Decision A). Every transition goes through
``trust.remediation.next_state``. A state row and the store entry that moves
it are written in one transaction, and an update names the state it expects,
so two instances cannot both make one transition.

Times come from each instance's clock: keep the clocks of several instances
synchronised (NTP), as for the registry (``docs/operations/remediation-and-reviews.md``).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable, NoReturn, Sequence

from ...models.boundary_policy import BoundaryPolicy, PolicyBinding
from ...models.context import BoundaryDecision, ContextRecord
from ...models.evidence_store import EvidenceStoreEntry, canonical_json, payload_digest
from ...models.out_of_band import JudgementRecord
from ...models.remediation import MAX_WAIVER_SECONDS, AdminApproval, RemediationRecord, ReviewRecord
from ...trust.evidence_store import build_entry
from ...trust.remediation import (
    DECISION_FIELDS,
    NOT_EXECUTED,
    OPEN_STATES,
    QUARANTINED_REMEDIATION_CODES,
    QUEUE_FILTERS,
    REQUEST_FIELDS,
    STORED_STATES,
    RemediationPlan,
    TransitionRefused,
    actor_holder,
    change_facts,
    remediation_record_problem,
    due_after_denial,
    decision_plan,
    due_after_waiver,
    entry_index,
    judgement_state,
    next_state,
    remediation_plan,
    remediation_secret_problem,
    request_approval_problem,
    review_approval_problem,
    review_holder_problem,
    review_request_problem,
    rfc3339,
    rotation_problem,
    sign_review,
    steps_problem,
)
from ..db_remediation import stamp
from ..errors import BadRequestError, ConflictError, NotFoundError, ServiceUnavailableError, ValidationError

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService

logger = logging.getLogger(__name__)

#: Most items one page of the due queue returns.
QUEUE_LIMIT = 500

#: Rows one sweep moves per kind of transition, and how often admissions sweep.
SWEEP_BATCH = 200
SWEEP_INTERVAL_SECONDS = 60

#: Most reviews and records ``GET /admin/evidence/remediations/<subject_id>`` returns (the newest).
DETAIL_LIMIT = 100

#: Audit events a decision's evaluating operator key is looked up in when it is repaired.
REQUESTER_LOOKUP = 5000


class _Moved(Exception):
    """The state moved since it was read; raised inside the write transaction."""


class _Refused(Exception):
    """A transition refused inside the write transaction."""

    def __init__(self, refusal: TransitionRefused) -> None:
        super().__init__(refusal.detail)
        self.refusal = refusal


def _parse(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _exact_form_problem(raw: dict[str, Any], record: Any) -> str | None:
    expected = record.to_wire()
    if canonical_json(raw) == canonical_json(expected):
        return None
    extra = sorted(set(raw) - set(expected))
    if extra:
        return "unexpected or null field " + ", ".join(repr(k) for k in extra)
    missing = sorted(set(expected) - set(raw))
    if missing:
        return "missing field " + ", ".join(repr(k) for k in missing)
    return "a field is not in its serialized form"


def _reviewed(policies: Sequence[BoundaryPolicy]) -> bool:
    return any(p.review_required or p.emergency for p in policies)


class RemediationService:
    """NA application logic for remediations, reviews and the due queue."""

    def __init__(self, service: "NetworkAuthorityService") -> None:
        self._na = service
        self._last_sweep = 0.0
        # Store positions the sweep has looked at, per subject kind, on this instance.
        self._repaired: dict[str, int] = {"judgement": 0, "decision": 0}

    # -- shared -------------------------------------------------------------

    @property
    def _db(self) -> Any:
        return self._na.db

    @property
    def _store(self) -> Any:
        return self._na.evidence_store_service

    @property
    def _oob(self) -> Any:
        return self._na.out_of_band_service

    @property
    def enabled(self) -> bool:
        """Stage 3 records are kept: the Stage 2 records are on and ``EVIDENCE_REMEDIATION=on``."""
        return bool(self._oob.enabled and self._na.evidence_remediation == "on")

    def require_enabled(self) -> None:
        self._oob.require_enabled()
        if not self.enabled:
            raise NotFoundError("Remediations and reviews are not recorded (EVIDENCE_REMEDIATION=off)",
                                code="remediation_disabled")

    def _now(self) -> datetime:
        # One clock with the out-of-band service: judging and arming agree on what "now" is.
        now: datetime = self._oob._now()
        return now

    def _audience(self) -> str:
        return str(self._na.genesis_block.network_authority.public_key)

    def _pending(self, kind: str, record: Any, now: datetime) -> tuple[Callable[..., EvidenceStoreEntry],
                                                                     dict[str, Any], dict[str, Any]]:
        payload = record.to_wire()
        index = entry_index(record)

        def build(seq: int, prev: str | None) -> EvidenceStoreEntry:
            return build_entry(store_sequence=seq, entry_kind=kind, recorded_at=now, payload=payload,
                               prev_entry_digest=prev, index=index)

        return build, payload, {}

    def _write(self, make: Callable[[Any], Sequence[Any]], unavailable: str) -> list[EvidenceStoreEntry]:
        try:
            entries: list[EvidenceStoreEntry] = self._db.append_evidence_entries_with(make)
        except (_Moved, _Refused, *self._db.integrity_errors):
            raise
        except self._db.database_errors as exc:
            logger.warning("remediation write failed: %s", exc)
            raise ServiceUnavailableError(unavailable, code="evidence_store_unavailable") from exc
        if entries:
            self._store.maybe_anchor()
        return entries

    # -- policies -------------------------------------------------------------

    def _policies(self, binding: PolicyBinding | None) -> list[BoundaryPolicy]:
        """The stored policy versions a binding names (each checked against its digest)."""
        out: list[BoundaryPolicy] = []
        for applied in (binding.policies if binding is not None else []):
            row = self._db.get_boundary_policy_row(applied.policy_id, applied.version)
            policy = self._db.parse_boundary_policy_row(row) if row is not None else None
            if policy is not None and policy.digest() == applied.policy_digest:
                out.append(policy)
        return out

    def refuse_unreviewable(self, decision: BoundaryDecision) -> None:
        """With the records off, refuse a decision under a policy that requires review (an
        emergency policy): it could not be reviewed (v1.4.0 review fixes)."""
        if self.enabled or not decision.authorized:
            return
        policies = self._policies(decision.policy_binding)
        if _reviewed(policies):
            names = sorted(f"{p.policy_id} v{p.version}" for p in policies if p.review_required or p.emergency)
            raise ConflictError(
                "a policy that requires review applies, and reviews are not recorded (EVIDENCE_REMEDIATION=off): "
                + ", ".join(names), code="policy_remediation_disabled",
            )

    # -- arming -------------------------------------------------------------------

    def on_judgement(self, stored: dict[str, Any], related_subjects: Sequence[str] = ()) -> None:
        """After a judgement is stored: arm its remediation, or open its review. ``related_subjects``
        are the decisions or break-glass judgements of the change the judged record matched: when
        one of them is under remediation or review, the judgement attaches to it instead. A failure
        is logged and repaired by the sweep."""
        if not self.enabled:
            return
        try:
            self._arm_judgement(stored, related_subjects)
        except Exception as exc:  # noqa: BLE001 -- the judgement itself is stored
            logger.warning("arming the remediation of judgement %s failed: %s", stored["entry"].record_id, exc)

    def _attached(self, judgement: JudgementRecord, related: Sequence[str]) -> bool:
        """Whether the judged change is already under remediation or review as a decision or a
        break-glass record (an observation of it attaches; it opens nothing of its own)."""
        candidates = list(related)
        if judgement.matched_decision_id:
            candidates.append(judgement.matched_decision_id)
        if judgement.matched_evidence_id:
            matched = self._db.get_judgement_for("break_glass", judgement.matched_evidence_id)
            if matched is not None:
                candidates.append(str(matched["payload"]["judgement_id"]))
        return any(self._db.get_remediation_state(c) is not None for c in candidates if c)

    def _arm_judgement(self, stored: dict[str, Any], related: Sequence[str] = ()) -> None:
        judgement = JudgementRecord.model_validate(stored["payload"])
        if self._db.get_remediation_state(judgement.judgement_id) is not None:
            return
        if self._attached(judgement, related):
            return
        policies = self._policies(judgement.policy_binding)
        flagged = bool(judgement.flagged_for_review)
        opened_for = "flagged_for_review" if flagged else (
            "review_required" if _reviewed(policies) and judgement.verdict == "allow" else None)
        if judgement.verdict == "allow" and opened_for is None:
            return  # an allowed change nothing asks a person to look at
        change = self._db.get_entry_by_record(judgement.subject_kind, judgement.subject_id)
        if change is None:
            raise RuntimeError(f"the judged record {judgement.subject_id} is not stored")
        action, version, rotatable = change_facts(judgement.subject_kind, change["payload"])
        plan = remediation_plan(
            verdict="indeterminate" if judgement.verdict == "indeterminate" else "deny", policies=policies,
            evaluations=judgement.policy_binding.gate_evaluations if judgement.policy_binding else [],
            action=action, version_id=version, rotatable=rotatable, defaults=self._na.remediation_defaults,
        )
        due = plan.due_at(judgement.judged_at) if judgement.verdict != "allow" else None
        emergency = next((p.emergency for p in policies if p.emergency is not None), None)
        lifetime = (judgement.evaluated_as_of + timedelta(seconds=emergency.max_lifetime_seconds)
                    if emergency is not None and judgement.verdict == "allow" else None)
        actor = change["payload"].get("actor") if judgement.subject_kind == "observation" else None
        self._create(
            subject_kind="judgement", subject_id=judgement.judgement_id, subject_digest=stored["entry"].payload_digest,
            change_kind=judgement.subject_kind, change_id=judgement.subject_id, change_version_id=version,
            change_store_sequence=judgement.subject_store_sequence, changed_at=judgement.evaluated_as_of,
            resource_id=judgement.resource_id, capability=judgement.capability, actor=actor, actor_holder=None,
            state=judgement_state(judgement.verdict, judgement.governed_by), verdict=judgement.verdict, plan=plan,
            due=due, lifetime=lifetime, opened_for=opened_for,
        )

    def on_decision(self, decision: BoundaryDecision, context: ContextRecord, entry: EvidenceStoreEntry,
                    requested_by: str | None) -> None:
        """After an authorized decision is stored: under a policy that requires review (an
        emergency policy always does), open its review. ``requested_by`` is the operator key that
        asked for the decision: the decision's actor. A failure is logged and repaired by the sweep."""
        if not self.enabled or not decision.authorized:
            return
        try:
            self._arm_decision(decision, context, entry.payload_digest, requested_by)
        except Exception as exc:  # noqa: BLE001 -- the decision is stored and returned
            logger.warning("opening the review of decision %s failed: %s", decision.decision_id, exc)

    def _arm_decision(self, decision: BoundaryDecision, context: ContextRecord, digest: str,
                      requested_by: str | None) -> None:
        if self._db.get_remediation_state(decision.decision_id) is not None:
            return
        policies = self._policies(decision.policy_binding)
        if not _reviewed(policies):
            return
        emergency = next((p.emergency for p in policies if p.emergency is not None), None)
        lifetime = (decision.decision_made_at + timedelta(seconds=emergency.max_lifetime_seconds)
                    if emergency is not None else None)
        holder = self._holders().get(requested_by or "", {}).get("holder") if requested_by else None
        self._create(
            subject_kind="decision", subject_id=decision.decision_id, subject_digest=digest,
            change_kind="execution", change_id=None, change_version_id=None, change_store_sequence=None,
            changed_at=None, resource_id=None, capability=context.requested_capability, actor=requested_by,
            actor_holder=holder, state="recorded", verdict="allow", plan=self._decision_plan(policies, None),
            due=None, lifetime=lifetime, opened_for="review_required",
        )

    def on_execution(self, decision_id: str) -> None:
        """After execution evidence under a decision is stored: a decision under review or with a
        lifetime takes its change and plan from it."""
        if not self.enabled:
            return
        try:
            row = self._db.get_remediation_state(decision_id)
            if row is None or row["state"] == "remediated":
                return
            changes = self._replan(row)
            if changes:
                now = stamp(self._now())

                def make(db: Any) -> list[Any]:
                    current = db.get_remediation_state(decision_id)
                    if current is not None and current["state"] != "remediated":
                        db.update_remediation_state(decision_id, current["state"], {**changes, "updated_at": now})
                    return []

                self._write(make, "The remediation state could not be stored")
        except Exception as exc:  # noqa: BLE001 -- the evidence is stored
            logger.warning("updating the remediation of decision %s failed: %s", decision_id, exc)

    def _create(
        self, *, subject_kind: str, subject_id: str, subject_digest: str, change_kind: str, change_id: str | None,
        change_version_id: str | None, change_store_sequence: int | None, changed_at: datetime | None,
        resource_id: str | None, capability: str | None, actor: str | None, actor_holder: str | None,
        state: str, verdict: str, plan: RemediationPlan, due: datetime | None, lifetime: datetime | None,
        opened_for: str | None, requested: dict[str, Any] | None = None, now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Create a subject's state (one transaction): a denied or indeterminate change armed, an
        allowed one in its Stage 2 state; with ``opened_for``, its review pending too. Returns the
        row and whether this call created it (False: another request created it first)."""
        now = now or self._now()
        if state in ("judged_denied", "indeterminate"):
            state = next_state(state, "arm")
        review_id = str(uuid.uuid4()) if opened_for else None
        row = {
            "subject_id": subject_id, "subject_kind": subject_kind, "subject_digest": subject_digest,
            "change_kind": change_kind, "change_id": change_id, "change_version_id": change_version_id,
            "change_store_sequence": change_store_sequence, "changed_at": stamp(changed_at) if changed_at else None,
            "resource_id": resource_id, "capability": capability, "actor": actor, "actor_holder": actor_holder,
            "verdict": verdict, "state": state, "review_pending": 1 if opened_for else 0, "mode": plan.mode,
            "steps": plan.steps, "fallback": plan.fallback, "grace_seconds": plan.grace_seconds,
            "guidance_source": plan.source, "remediation_due_at": stamp(due) if due else None,
            "lifetime_ends_at": stamp(lifetime) if lifetime else None, "review_id": review_id,
            "created_at": stamp(now), "updated_at": stamp(now),
        }

        def make(db: Any) -> list[Any]:
            if db.get_remediation_state(subject_id) is not None:
                raise _Moved()
            db.insert_remediation_state(row)
            if review_id is not None:
                db.insert_remediation_review({
                    "review_id": review_id, "subject_id": subject_id, "opened_for": opened_for,
                    "requested_at": stamp(now), **(requested or {}),
                })
            return []

        try:
            self._write(make, "The remediation state could not be stored")
        except (_Moved, *self._db.integrity_errors):
            existing = self._db.get_remediation_state(subject_id)
            if existing is None:
                raise
            return existing, False
        self._db.add_audit_event("review_opened" if opened_for else "remediation_armed", {
            "subject_kind": subject_kind, "subject_id": subject_id, "state": state, "mode": plan.mode,
            "steps": plan.steps, "remediation_due_at": row["remediation_due_at"], "review_id": review_id,
            "opened_for": opened_for,
        })
        return row, True

    def enabled_since(self) -> datetime:
        """When the records were first turned on (the first ``remediation_enabled`` audit event, written
        now when there is none). Judgements and decisions recorded earlier are not armed by the sweep:
        a store upgraded from 1.3 does not turn its past denials into overdue remediations at once."""
        events = self._db.list_audit_events(event_types=["remediation_enabled"])
        times = [t for t in (_parse((e.get("details") or {}).get("since") or e.get("created_at")) for e in events)
                 if t is not None]
        if times:
            return min(times)
        now = self._now()
        self._db.add_audit_event("remediation_enabled", {"since": stamp(now)})
        return now

    def ensure_states(self) -> None:
        """At start: sweep (arm what an older instance or a failed arming left, move due times).
        Never fails start."""
        if not self.enabled:
            return
        try:
            self.sweep()
        except Exception as exc:  # noqa: BLE001
            logger.error("remediation start checks failed: %s", exc)

    # -- sweeping -------------------------------------------------------------------

    def sweep(self, now: datetime | None = None) -> dict[str, int]:
        """Arm what nothing armed yet, then move what is due: remediations past their due time
        become ``overdue`` (one audit event each), ended waivers and emergency lifetimes re-arm
        remediation. A pending review stops none of it. Returns the counts."""
        if not self.enabled:
            return {}
        self._last_sweep = time.monotonic()
        counts = {"armed": self._repair(), "overdue": 0, "waivers_ended": 0, "lifetimes_ended": 0}
        now = now or self._now()
        for row in self._db.remediation_states_due("remediation_due_at", ["remediation_due"], now, SWEEP_BATCH):
            if self._move(row, "due_passed", {"overdue_since": stamp(now)}):
                counts["overdue"] += 1
                self._db.add_audit_event("remediation_overdue", {
                    "subject_kind": row["subject_kind"], "subject_id": row["subject_id"],
                    "resource_id": row["resource_id"], "actor": row["actor"],
                    "remediation_due_at": row["remediation_due_at"], "notified_at": row["notified_at"],
                    "review_pending": bool(row["review_pending"]),
                })
        for row in self._db.remediation_states_due("waived_until", ["waived"], now, SWEEP_BATCH):
            ended = _parse(row["waived_until"])
            assert ended is not None
            changes = self._replan(row)
            due = due_after_waiver(ended, int(changes.get("grace_seconds", row["grace_seconds"])))
            if self._move(row, "waiver_expired", {"remediation_due_at": stamp(due), **changes}):
                counts["waivers_ended"] += 1
                self._db.add_audit_event("waiver_expired", {
                    "subject_id": row["subject_id"], "waived_until": row["waived_until"],
                    "remediation_due_at": stamp(due), "review_pending": bool(row["review_pending"]),
                })
        for row in self._db.remediation_states_due("lifetime_ends_at", ["judged_allowed", "matched", "recorded",
                                                                        "upheld"], now, SWEEP_BATCH):
            ended = _parse(row["lifetime_ends_at"])
            assert ended is not None
            changes = self._replan(row)
            due = due_after_waiver(ended, int(changes.get("grace_seconds", row["grace_seconds"])))
            if self._move(row, "lifetime_ended", {"remediation_due_at": stamp(due), **changes}):
                counts["lifetimes_ended"] += 1
                self._db.add_audit_event("emergency_lifetime_ended", {
                    "subject_id": row["subject_id"], "lifetime_ends_at": row["lifetime_ends_at"],
                    "remediation_due_at": stamp(due), "review_pending": bool(row["review_pending"]),
                })
        return counts

    def _repair(self) -> int:
        """Arm judgements and authorized decisions recorded since the records were turned on that
        nothing armed (made by an older instance during a rolling upgrade, or whose arming failed),
        each looked at once per instance. Returns how many were armed."""
        since = self.enabled_since()
        armed = 0
        for kind in ("judgement", "decision"):
            for seq, subject_id in self._db.subjects_without_state(
                    kind, recorded_since=since, after_sequence=self._repaired[kind], limit=SWEEP_BATCH):
                self._repaired[kind] = max(self._repaired[kind], seq)
                try:
                    if kind == "judgement":
                        stored = self._db.get_entry_by_record("judgement", subject_id)
                        if stored is not None:
                            self._arm_judgement(stored)
                    else:
                        stored = self._db.get_decision_entry(subject_id)
                        if stored is not None:
                            self._arm_decision(
                                BoundaryDecision.model_validate(stored["payload"]["decision"]),
                                ContextRecord.model_validate(stored["payload"]["context"]),
                                stored["entry"].payload_digest, self._decision_requester(subject_id))
                except Exception as exc:  # noqa: BLE001 -- the next one is armed all the same
                    logger.warning("arming %s %s failed: %s", kind, subject_id, exc)
                    continue
                if self._db.get_remediation_state(subject_id) is not None:
                    armed += 1
        return armed

    def _decision_requester(self, decision_id: str) -> str | None:
        """The operator key that asked for a decision, from its ``decision_stored`` audit event."""
        for event in self._db.list_audit_events(event_types=["decision_stored"], limit=REQUESTER_LOOKUP):
            details = event.get("details") or {}
            if details.get("decision_id") == decision_id:
                requester = details.get("requested_by")
                return str(requester) if requester else None
        return None

    def maybe_sweep(self) -> None:
        """Sweep at most every SWEEP_INTERVAL_SECONDS (after admissions and on reads)."""
        if not self.enabled or time.monotonic() - self._last_sweep < SWEEP_INTERVAL_SECONDS:
            return
        try:
            self.sweep()
        except Exception as exc:  # noqa: BLE001
            logger.warning("sweeping remediation due times failed: %s", exc)

    def _move(self, row: dict[str, Any], event: str, changes: dict[str, Any]) -> bool:
        """Apply one event to a row in the state it was read in; False when another writer moved it."""
        target = next_state(row["state"], event, bool(row["review_pending"]))
        stamp_now = stamp(self._now())

        def make(db: Any) -> list[Any]:
            if not db.update_remediation_state(row["subject_id"], row["state"],
                                               {**changes, "state": target, "updated_at": stamp_now}):
                raise _Moved()
            return []

        try:
            self._write(make, "The remediation state could not be stored")
        except _Moved:
            return False
        return True

    def _decision_plan(self, policies: Sequence[BoundaryPolicy], executed: dict[str, Any] | None) -> RemediationPlan:
        """A decision's plan: from its latest execution evidence, or, never executed, an alert
        (``fallback`` ``not_executed``)."""
        return decision_plan(policies=policies, defaults=self._na.remediation_defaults,
                             executed=change_facts("execution", executed["payload"]) if executed is not None else None)

    def _replan(self, row: dict[str, Any]) -> dict[str, Any]:
        """For a decision's remediation, the plan and change from its latest execution evidence
        (or an alert while it has none); nothing for a judgement's, whose change is fixed."""
        if row["subject_kind"] != "decision":
            return {}
        decision = self._db.get_decision_entry(row["subject_id"])
        binding = BoundaryDecision.model_validate(decision["payload"]["decision"]).policy_binding \
            if decision is not None else None
        stored = self._db.last_execution_for_decision(row["subject_id"])
        plan = self._decision_plan(self._policies(binding), stored)
        out: dict[str, Any] = {"mode": plan.mode, "steps": plan.steps, "fallback": plan.fallback,
                               "grace_seconds": plan.grace_seconds, "guidance_source": plan.source}
        if stored is not None:
            entry: EvidenceStoreEntry = stored["entry"]
            out.update({
                "change_id": entry.evidence_id, "resource_id": entry.resource_id,
                "change_version_id": change_facts("execution", stored["payload"])[1],
                "change_store_sequence": entry.store_sequence,
                "changed_at": stamp(_parse(stored["payload"].get("executed_at")) or entry.recorded_at),
            })
        return out

    # -- the due queue --------------------------------------------------------------

    def item(self, row: dict[str, Any]) -> dict[str, Any]:
        """One remediation state as the routes and the changes view show it."""
        out = {k: row.get(k) for k in (
            "subject_kind", "subject_id", "change_kind", "change_id", "change_version_id", "resource_id",
            "capability", "actor", "actor_holder", "verdict", "state", "mode", "steps", "fallback", "grace_seconds",
            "guidance_source", "remediation_due_at", "lifetime_ends_at", "waived_until", "review_id",
            "remediation_id", "notified_at", "notified_by", "overdue_since", "created_at", "updated_at",
        )}
        out["review_pending"] = bool(row.get("review_pending"))
        if out["review_pending"] and row.get("review_id"):
            review = self._db.get_remediation_review(row["review_id"])
            if review is not None:
                out["review"] = self._review_summary(review)
        return out

    @staticmethod
    def _review_summary(review: dict[str, Any]) -> dict[str, Any]:
        return {k: review[k] for k in ("review_id", "subject_id", "opened_for", "requested_by", "requester_holder",
                                       "justification", "requested_at", "decided_at", "verdict")}

    def queue(self, *, state: str | None, limit: str | None, after: str | None) -> dict[str, Any]:
        """``GET /admin/evidence/remediations``: states in ``state`` (a stored state, or
        ``review_pending`` for a pending review whatever the state; default: due, overdue and
        waived, and any other with a pending review that is not remediated), oldest first."""
        self.require_enabled()
        if state is not None and state not in QUEUE_FILTERS:
            raise BadRequestError(f"state must be one of {', '.join(QUEUE_FILTERS)}", code="invalid_remediation_query")
        try:
            size = int(limit or 100)
        except ValueError:
            raise BadRequestError("limit must be an integer", code="invalid_remediation_query") from None
        if not 1 <= size <= QUEUE_LIMIT:
            raise BadRequestError(f"limit must be 1..{QUEUE_LIMIT}", code="invalid_remediation_query")
        cursor: tuple[str, str] | None = None
        if after:
            created, sep, subject = after.partition("|")
            at = _parse(created)
            if not sep or not subject or at is None:
                raise BadRequestError("after is the next_after value of the previous page",
                                      code="invalid_remediation_query")
            cursor = (stamp(at), subject)
        self.sweep()
        if state is None:
            # v1.5.0: a remediated change is settled, even with its review still pending (the
            # comment at OPEN_STATES); state=review_pending still lists it.
            rows = self._db.list_remediation_states(list(OPEN_STATES), review_pending=True, after=cursor, limit=size,
                                                    open_only=True)
        elif state == "review_pending":
            rows = self._db.list_remediation_states([], review_pending=True, after=cursor, limit=size)
        else:
            rows = self._db.list_remediation_states([state], after=cursor, limit=size)
        last = rows[-1] if len(rows) == size else None
        return {
            "state": state, "count": len(rows),
            "remediations": [self.item(r) for r in rows],
            # The time with Z, so the cursor needs no escaping in a query string.
            "next_after": f"{last['created_at'].replace('+00:00', 'Z')}|{last['subject_id']}" if last else None,
        }

    def get(self, subject_id: str) -> dict[str, Any]:
        """One subject's remediation state, with its newest reviews and stored records (at most
        ``DETAIL_LIMIT`` of each; ``reviews_truncated``/``records_truncated`` when there are more)."""
        self.require_enabled()
        self.maybe_sweep()
        row = self._db.get_remediation_state(subject_id)
        if row is None:
            raise NotFoundError("no remediation or review for this subject", code="remediation_not_found")
        reviews = self._db.remediation_reviews_for(subject_id)
        entries = self._db.remediation_entries_for([subject_id])
        return {
            **self.item(row),
            "reviews": [self._review_summary(r) for r in reviews[-DETAIL_LIMIT:]],
            "reviews_truncated": len(reviews) > DETAIL_LIMIT,
            "records": [{"entry": e["entry"].model_dump(mode="json"), "entry_digest": e["entry_digest"],
                         "payload": e["payload"]} for e in entries[-DETAIL_LIMIT:]],
            "records_truncated": len(entries) > DETAIL_LIMIT,
        }

    def states_for(self, subject_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Remediation states by subject, for the changes view (empty with the records off)."""
        if not self.enabled:
            return {}
        self.maybe_sweep()
        states: dict[str, dict[str, Any]] = self._db.remediation_states_for(list(subject_ids))
        return states

    def counts(self) -> dict[str, Any]:
        """Additive fields for ``/admin/evidence/status``: states by state, and ``review_pending``."""
        self.maybe_sweep()
        by_state = self._db.count_remediation_states()
        return {"remediation": {s: by_state.get(s, 0) for s in (*STORED_STATES, "review_pending")}}

    # -- notices ------------------------------------------------------------------

    def record_notice(self, subject_id: str, data: dict[str, Any], operator: str) -> dict[str, Any]:
        """The controller told the actor: an audit event, and ``notified_at`` (the first notice)."""
        self.require_enabled()
        unknown = sorted(set(data) - {"channel"})
        channel = data.get("channel")
        if unknown or (channel is not None and (not isinstance(channel, str) or not 1 <= len(channel) <= 64)):
            raise BadRequestError("a notice may name its channel (1 to 64 characters), nothing else",
                                  code="invalid_notice")
        row = self._db.get_remediation_state(subject_id)
        if row is None:
            raise NotFoundError("no remediation or review for this subject", code="remediation_not_found")
        now = self._now()
        if row["notified_at"] is None:
            def make(db: Any) -> list[Any]:
                current = db.get_remediation_state(subject_id)
                if current is not None and current["notified_at"] is None:
                    db.update_remediation_state(subject_id, current["state"], {
                        "notified_at": stamp(now), "notified_by": operator, "updated_at": stamp(now)})
                return []

            self._write(make, "The notice could not be recorded")
        due = _parse(row["remediation_due_at"])
        self._db.add_audit_event("remediation_notified", {
            "subject_kind": row["subject_kind"], "subject_id": subject_id, "actor": row["actor"],
            "resource_id": row["resource_id"], "state": row["state"], "channel": channel, "notified_by": operator,
            "notified_at": stamp(now), "remediation_due_at": row["remediation_due_at"],
            "before_due": due is None or now <= due,
        })
        return self.item(self._current(subject_id, row))

    # -- reviews ------------------------------------------------------------------

    def _current(self, subject_id: str, fallback: dict[str, Any]) -> dict[str, Any]:
        """A state as stored after a write, or what the write made of it when it cannot be read back."""
        current: dict[str, Any] | None = self._db.get_remediation_state(subject_id)
        return current if current is not None else fallback

    def _holders(self) -> dict[str, dict[str, Any]]:
        holders: dict[str, dict[str, Any]] = self._oob.operator_holders()
        return holders

    def _named_holder(self, key_id: str, holders: dict[str, dict[str, Any]], who: str) -> str:
        known = holders.get(key_id)
        if known is None or not known.get("holder") or known["holder"] == key_id:
            raise ConflictError(f"the {who}'s operator key {key_id} has no named holder in the store",
                                code="review_needs_named_holder")
        return str(known["holder"])

    def _actor_holder(self, row: dict[str, Any], holders: dict[str, dict[str, Any]]) -> str | None:
        """The holder of a change's actor: recorded for a decision (its evaluating operator key's),
        mapped for an observed actor (``NA_REVIEW_ACTOR_HOLDERS_JSON``, else a holder of that name)."""
        if row.get("actor_holder"):
            return str(row["actor_holder"])
        return actor_holder(row.get("actor"), self._na.review_actor_holders,
                            [str(h["holder"]) for h in holders.values() if h.get("holder")])

    def _subject_entry(self, subject_kind: str, subject_id: str) -> dict[str, Any] | None:
        if subject_kind == "judgement":
            stored: dict[str, Any] | None = self._db.get_entry_by_record("judgement", subject_id)
            return stored
        return self._db.get_decision_entry(subject_id)  # type: ignore[no-any-return]

    def _signed_at(self, approval: dict[str, Any]) -> None:
        if rfc3339(approval.get("timestamp")) is None:
            raise BadRequestError("X-Admin-Timestamp must be an RFC 3339 timestamp (YYYY-MM-DDTHH:MM:SS, an "
                                  "optional fraction, Z or +HH:MM) on the review routes", code="invalid_review")

    def request_review(self, data: dict[str, Any], requester: str, approval: dict[str, Any]) -> dict[str, Any]:
        """An operator asks a second holder to review a judged change or a decision."""
        self.require_enabled()
        if set(data) != REQUEST_FIELDS:
            raise BadRequestError("a review request gives subject_kind, subject_id and justification, nothing else",
                                  code="invalid_review")
        kind, subject_id, justification = data["subject_kind"], data["subject_id"], data["justification"]
        if kind not in ("judgement", "decision") or not isinstance(subject_id, str) or not subject_id \
                or not isinstance(justification, str) or not 1 <= len(justification) <= 1024:
            raise BadRequestError("subject_kind is judgement or decision; justification is 1 to 1024 characters",
                                  code="invalid_review")
        self._signed_at(approval)
        stored = self._subject_entry(kind, subject_id)
        if stored is None:
            raise NotFoundError(f"no {kind} {subject_id!r} is stored", code="review_subject_not_found")
        holders = self._holders()
        holder = self._named_holder(requester, holders, "requester")
        now = self._now()
        signed = AdminApproval.model_validate(approval)
        problem = request_approval_problem(signed, requested_by=requester, subject_kind=kind, subject_id=subject_id,
                                           justification=justification, requested_at=now,
                                           audiences=[self._audience()])
        if problem is not None:
            raise BadRequestError(f"the request would not verify offline: {problem}", code="review_approval_invalid")
        requested = {"requested_by": requester, "requester_holder": holder, "justification": justification,
                     "request_approval_json": json.dumps(signed.model_dump(mode="json"), sort_keys=True,
                                                         separators=(",", ":"))}
        row = self._db.get_remediation_state(subject_id)
        if row is None:
            row = self._create_for_request(kind, subject_id, stored, requested, holders, requester, now)
            review_id = row["review_id"]
        else:
            self._refuse_actor(row, requester, holder, holders)
            review_id = self._open_on(row, requested, now)
        self._db.add_audit_event("review_requested", {
            "review_id": review_id, "subject_kind": kind, "subject_id": subject_id, "requested_by": requester,
            "requester_holder": holder,
        })
        return {**self.item(self._current(subject_id, {**(row or {}), "subject_id": subject_id})),
                "review_id": review_id}

    def _refuse_actor(self, row: dict[str, Any], requester: str, holder: str,
                      holders: dict[str, dict[str, Any]]) -> None:
        problem = review_request_problem(requested_by=requester, requester_holder=holder, actor=row.get("actor"),
                                         actor_holder=self._actor_holder(row, holders))
        if problem is not None:
            self._db.add_audit_event("review_refused", {"subject_id": row["subject_id"], "requested_by": requester,
                                                        "code": problem[0]})
            raise ConflictError(problem[1], code=problem[0])

    def _create_for_request(self, kind: str, subject_id: str, stored: dict[str, Any], requested: dict[str, Any],
                            holders: dict[str, dict[str, Any]], requester: str, now: datetime) -> dict[str, Any]:
        """A review requested on a subject with no remediation state yet."""
        defaults = self._na.remediation_defaults
        if kind == "judgement":
            judgement = JudgementRecord.model_validate(stored["payload"])
            change = self._db.get_entry_by_record(judgement.subject_kind, judgement.subject_id)
            action, version, rotatable = change_facts(judgement.subject_kind, change["payload"] if change else {})
            policies = self._policies(judgement.policy_binding)
            plan = remediation_plan(
                verdict="indeterminate" if judgement.verdict == "indeterminate" else "deny", policies=policies,
                evaluations=judgement.policy_binding.gate_evaluations if judgement.policy_binding else [],
                action=action, version_id=version, rotatable=rotatable, defaults=defaults,
            )
            actor = change["payload"].get("actor") if change and judgement.subject_kind == "observation" else None
            fields: dict[str, Any] = dict(
                subject_kind="judgement", subject_id=subject_id, subject_digest=stored["entry"].payload_digest,
                change_kind=judgement.subject_kind, change_id=judgement.subject_id, change_version_id=version,
                change_store_sequence=judgement.subject_store_sequence, changed_at=judgement.evaluated_as_of,
                resource_id=judgement.resource_id, capability=judgement.capability, actor=actor, actor_holder=None,
                verdict=judgement.verdict, state=judgement_state(judgement.verdict, judgement.governed_by),
                plan=plan, due=plan.due_at(judgement.judged_at) if judgement.verdict != "allow" else None,
                lifetime=None,
            )
        else:
            decision = BoundaryDecision.model_validate(stored["payload"]["decision"])
            if not decision.authorized:
                raise ConflictError("a denied decision changed nothing; there is nothing to review",
                                    code="illegal_transition")
            context = ContextRecord.model_validate(stored["payload"]["context"])
            evaluator = self._decision_requester(subject_id)
            fields = dict(
                subject_kind="decision", subject_id=subject_id, subject_digest=stored["entry"].payload_digest,
                change_kind="execution", change_id=None, change_version_id=None, change_store_sequence=None,
                changed_at=None, resource_id=None, capability=context.requested_capability, actor=evaluator,
                actor_holder=holders.get(evaluator or "", {}).get("holder") if evaluator else None,
                verdict="allow", state="recorded",
                plan=self._decision_plan(self._policies(decision.policy_binding), None), due=None, lifetime=None,
            )
        self._refuse_actor({"subject_id": subject_id, "actor": fields["actor"], "actor_holder": fields["actor_holder"]},
                           requester, str(requested["requester_holder"]), holders)
        try:
            row, created = self._create(**fields, opened_for="requested", requested=requested, now=now)
        except TransitionRefused as exc:
            raise ConflictError(exc.detail, code=exc.code) from None
        if not created:
            # Another request created this subject's state at the same moment: open the review on it.
            return {**row, "review_id": self._open_on(row, requested, now)}
        if kind == "decision":
            self.on_execution(subject_id)
        return row

    def _open_on(self, row: dict[str, Any], requested: dict[str, Any], now: datetime) -> str:
        """Open a requested review on an existing state (one transaction): the flag is set, the
        state and its clocks stay. Returns the review id."""
        try:
            next_state(row["state"], "open_review", bool(row["review_pending"]))
        except TransitionRefused as exc:
            raise ConflictError(exc.detail, code=exc.code) from None
        review_id = str(uuid.uuid4())

        def make(db: Any) -> list[Any]:
            current = db.get_remediation_state(row["subject_id"])
            if current is None:
                raise _Moved()
            try:
                next_state(current["state"], "open_review", bool(current["review_pending"]))
            except TransitionRefused as exc:
                raise _Refused(exc) from None
            if not db.update_remediation_state(row["subject_id"], current["state"], {
                    "review_pending": 1, "review_id": review_id, "updated_at": stamp(now)}):
                raise _Moved()
            db.insert_remediation_review({"review_id": review_id, "subject_id": row["subject_id"],
                                          "opened_for": "requested", "requested_at": stamp(now), **requested})
            return []

        try:
            self._write(make, "The review could not be stored")
        except _Refused as exc:
            raise ConflictError(exc.refusal.detail, code=exc.refusal.code) from None
        except (_Moved, *self._db.integrity_errors):
            raise ConflictError("the subject's state changed while the review was requested; retry",
                                code="review_conflict") from None
        return review_id

    def get_review(self, review_id: str) -> dict[str, Any]:
        self.require_enabled()
        review = self._db.get_remediation_review(review_id)
        if review is None:
            raise NotFoundError("unknown review", code="review_not_found")
        out = self._review_summary(review)
        stored = self._db.get_entry_by_record("review", review_id)
        if stored is not None:
            out["record"] = {"entry": stored["entry"].model_dump(mode="json"), "entry_digest": stored["entry_digest"],
                             "payload": stored["payload"]}
        return out

    def _decision_input(self, data: dict[str, Any], now: datetime) -> tuple[str, datetime | None, str | None]:
        unknown = sorted(set(data) - DECISION_FIELDS)
        verdict = data.get("verdict")
        note = data.get("note")
        if unknown or verdict not in ("uphold", "deny", "waive_until") or (
                note is not None and (not isinstance(note, str) or not 1 <= len(note) <= 1024)):
            raise BadRequestError("a decision gives verdict (uphold, deny or waive_until), waive_until for a "
                                  "waiver and an optional note (1 to 1024 characters)", code="invalid_review")
        raw_until = data.get("waive_until")
        if (verdict == "waive_until") != (raw_until is not None):
            raise BadRequestError("waive_until is given exactly for a waiver", code="invalid_review")
        until: datetime | None = None
        if raw_until is not None:
            parsed = rfc3339(raw_until)
            if parsed is None:
                raise BadRequestError("waive_until is an RFC 3339 timestamp (YYYY-MM-DDTHH:MM:SS, an optional "
                                      "fraction, Z or +HH:MM)", code="invalid_review")
            if parsed <= now:
                raise BadRequestError("waive_until is a time after now", code="invalid_review")
            until = parsed.astimezone(timezone.utc)
            longest = min(self._na.review_max_waiver_seconds, MAX_WAIVER_SECONDS)
            if until > now + timedelta(seconds=longest):
                raise ValidationError(f"a waiver ends within {longest}s (NA_REVIEW_MAX_WAIVER_SECONDS)",
                                      code="review_waiver_too_long")
        return str(verdict), until, note

    def decide_review(self, review_id: str, data: dict[str, Any], decider: str,
                      approval: dict[str, Any]) -> dict[str, Any]:
        """A privileged key of a second holder decides a review; the NA records it, signed."""
        self.require_enabled()
        self._signed_at(approval)
        now = self._now()
        verdict, until, note = self._decision_input(data, now)
        review = self._db.get_remediation_review(review_id)
        if review is None:
            raise NotFoundError("unknown review", code="review_not_found")
        if review["decided_at"] is not None:
            raise ConflictError("this review is already decided", code="review_already_decided")
        row = self._db.get_remediation_state(review["subject_id"])
        assert row is not None
        holders = self._holders()
        decider_holder = self._named_holder(decider, holders, "decider")
        mapped = self._actor_holder(row, holders)
        problem = review_holder_problem(
            decided_by=decider, decider_holder=decider_holder, requested_by=review["requested_by"],
            requester_holder=review["requester_holder"], actor=row["actor"], actor_holder=mapped,
        )
        if problem is not None:
            self._db.add_audit_event("review_refused", {"review_id": review_id, "decided_by": decider,
                                                        "code": problem[0]})
            raise ConflictError(problem[1], code=problem[0])
        lifetime = _parse(row["lifetime_ends_at"])
        if until is not None and lifetime is not None and until > lifetime:
            raise ValidationError(f"an emergency change lives until {row['lifetime_ends_at']}; a waiver cannot "
                                  f"outlast it", code="review_waiver_beyond_lifetime")
        event = {"uphold": "uphold", "deny": "deny", "waive_until": "waive"}[verdict]
        try:
            next_state(row["state"], event, True)
        except TransitionRefused as exc:
            raise ConflictError(exc.detail, code=exc.code) from None

        request_approval = json.loads(review["request_approval_json"]) if review["request_approval_json"] else None
        record = sign_review(ReviewRecord(
            review_id=review_id, subject_kind=row["subject_kind"], subject_id=row["subject_id"],
            subject_digest=row["subject_digest"], resource_id=row["resource_id"], capability=row["capability"],
            opened_for=review["opened_for"], requested_by=review["requested_by"],
            requester_holder=review["requester_holder"], justification=review["justification"],
            request_approval=AdminApproval.model_validate(request_approval) if request_approval else None,
            requested_at=_parse(review["requested_at"]) or now, actor=row["actor"], actor_holder=mapped,
            verdict=verdict,  # type: ignore[arg-type]
            waive_until=until, note=note, decided_by=decider, decider_holder=decider_holder,
            approval=AdminApproval.model_validate(approval), decided_at=now,
            issuer_sovereign_id=self._na.genesis_block.network_name, issued_by=self._na.key_id,
        ), self._na.signer, self._na.key_id)
        # The NA records only what verifies offline: this clock reading, these requests.
        problem_text = review_approval_problem(record, [self._audience()])
        if problem_text is not None:
            raise BadRequestError(f"the decision would not verify offline: {problem_text}",
                                  code="review_approval_invalid")

        outcome: dict[str, Any] = {}

        def make(db: Any) -> list[Any]:
            current = db.get_remediation_state(row["subject_id"])
            if current is None:
                raise _Moved()
            if not db.mark_remediation_review_decided(review_id, verdict, now):
                raise _Moved()
            try:
                target = next_state(current["state"], event, True)
            except TransitionRefused as exc:
                raise _Refused(exc) from None
            changes: dict[str, Any] = {"updated_at": stamp(now), "review_pending": 0}
            if target in ("review_denied", "remediation_due", "overdue") and event == "deny":
                changes.update(self._replan(current))
                due = due_after_denial(_parse(current["remediation_due_at"]), now,
                                       int(changes.get("grace_seconds", current["grace_seconds"])))
                if target == "review_denied":
                    target = next_state(target, "arm")
                changes["remediation_due_at"] = stamp(due)
            elif target == "waived":
                assert until is not None
                changes["waived_until"] = stamp(until)
            if not db.update_remediation_state(current["subject_id"], current["state"], {**changes, "state": target}):
                raise _Moved()
            outcome["state"] = target
            return [self._pending("review", record, now)]

        try:
            entries = self._write(make, "The review could not be stored")
        except _Refused as exc:
            raise ConflictError(exc.refusal.detail, code=exc.refusal.code) from None
        except (_Moved, *self._db.integrity_errors):
            raise ConflictError("the review or its subject changed while it was decided; retry",
                                code="review_conflict") from None
        self._db.add_audit_event("review_decided", {
            "review_id": review_id, "subject_id": row["subject_id"], "verdict": verdict,
            "waive_until": stamp(until) if until else None, "decided_by": decider, "decider_holder": decider_holder,
            "state": outcome["state"], "store_sequence": entries[0].store_sequence,
        })
        current = self._current(row["subject_id"], {**row, "state": outcome["state"], "review_pending": 0})
        return {"review": {"entry": entries[0].model_dump(mode="json"), "entry_digest": entries[0].digest(),
                           "payload": record.to_wire()},
                **self.item(current)}

    # -- remediation records ----------------------------------------------------------

    def _refuse(self, code: str, detail: str, record: RemediationRecord | None, digest: str,
                quarantine_id: str | None = None) -> NoReturn:
        self._db.add_evidence_rejection(
            code, submitted_digest=digest, evidence_id=None, decision_id=None,
            resource_id=record.resource_id if record else None,
            executor_sovereign_id=record.executor_sovereign_id if record else None,
        )
        self._db.add_audit_event("remediation_rejected", {
            "code": code, "submitted_digest": digest, "remediation_id": record.remediation_id if record else None,
            "subject_id": record.subject_id if record else None,
        })
        error = ConflictError if code in ("remediation_conflict", "remediation_already_recorded",
                                          "remediation_not_due") else ValidationError
        raise error(detail, code=code, details={"quarantine_id": quarantine_id} if quarantine_id else None)

    def _quarantine(self, raw: dict[str, Any], record: RemediationRecord, code: str, detail: str) -> str | None:
        """Keep an authentic remediation record refused for good: the cancel it reports happened.
        Never one that may carry secret material."""
        if code not in QUARANTINED_REMEDIATION_CODES or remediation_secret_problem(record) is not None:
            return None
        try:
            stored = self._oob.quarantine("remediation", raw, code, detail, record.resource_id)
        except Exception as exc:  # noqa: BLE001 -- the refusal itself must still be returned
            logger.warning("could not quarantine a refused remediation record: %s", exc)
            return None
        return str(stored["payload"]["quarantine_id"])

    def _refuse_final(self, code: str, detail: str, record: RemediationRecord, raw: dict[str, Any],
                      digest: str) -> NoReturn:
        self._refuse(code, detail, record, digest, self._quarantine(raw, record, code, detail))

    def submit_remediation(self, raw: Any) -> tuple[dict[str, Any], int]:
        """Admit one signed remediation record. Returns (body, HTTP status)."""
        self.require_enabled()
        self.maybe_sweep()
        if not isinstance(raw, dict):
            raise BadRequestError("record must be an object", code="invalid_remediation")
        digest = payload_digest(raw)
        signature = raw.get("signature")
        key_id = signature.get("key_id") if isinstance(signature, dict) else None
        key = self._oob._key(key_id if isinstance(key_id, str) else None)
        # The reference order every verifier follows: the form, then the signature, key and guard.
        check, parsed = remediation_record_problem(raw, key)
        if parsed is None or check.code == "remediation_malformed":
            assert check.code is not None
            if parsed is not None:
                difference = _exact_form_problem(raw, parsed)
                self._refuse(check.code, f"record is not in its exact serialized form: {difference}", parsed, digest)
            self._refuse(check.code, check.detail, None, digest)
        record = parsed
        if not check.accepted:
            assert check.code is not None
            self._refuse(check.code, check.detail, record, digest,
                         self._quarantine(raw, record, check.code, check.detail))
        assert key is not None
        now = self._now()
        if record.remediated_at > now + self._oob.bounds.skew:
            self._refuse("remediation_malformed", "remediated_at is in the future", record, digest)

        existing = self._db.get_entry_by_record("remediation", record.remediation_id)
        if existing is not None:
            if payload_digest(existing["payload"]) != digest:
                self._refuse("remediation_conflict", "another remediation record with this id is stored",
                             record, digest)
            return {"entry": existing["entry"].model_dump(mode="json"), "entry_digest": existing["entry_digest"],
                    "payload": existing["payload"], "status": "duplicate"}, 200

        row = self._db.get_remediation_state(record.subject_id)
        subject_resource = row["resource_id"] if row is not None else self._subject_resource(record)
        # Nothing about a subject outside the key's scope is told, or kept.
        if subject_resource is not None and not key.covers(subject_resource):
            self._refuse("remediation_out_of_scope", "the signing key does not cover the subject's resource",
                         record, digest)
        if row is None:
            if self._subject_entry(record.subject_kind, record.subject_id) is None:
                self._refuse("remediation_subject_not_found",
                             f"no {record.subject_kind} {record.subject_id!r} is stored", record, digest)
            self._refuse_final("remediation_not_due", "nothing is due for this subject", record, raw, digest)
        # A decision's change and plan follow from its latest execution evidence.
        planned = {**row, **self._replan(row)}
        problem = self._subject_problem(record, planned)
        if problem is not None:
            self._refuse_final("remediation_subject_mismatch", problem, record, raw, digest)
        problem = steps_problem(planned["mode"], planned["steps"], record)
        if problem is not None:
            self._refuse_final("remediation_steps_mismatch", problem, record, raw, digest)
        rotation = self._rotation_problem(record, planned)
        if rotation is not None:
            code, detail = rotation
            if code == "remediation_rotation_missing":
                self._refuse(code, detail, record, digest)
            self._refuse_final(code, detail, record, raw, digest)
        try:
            next_state(row["state"], "record_remediation", bool(row["review_pending"]))
        except TransitionRefused as exc:
            self._refuse_final(exc.code, exc.detail, record, raw, digest)

        def make(db: Any) -> list[Any]:
            current = db.get_remediation_state(record.subject_id)
            if current is None:
                raise _Moved()
            try:
                target = next_state(current["state"], "record_remediation", bool(current["review_pending"]))
            except TransitionRefused as exc:
                raise _Refused(exc) from None
            if not db.update_remediation_state(record.subject_id, current["state"], {
                    "state": target, "remediation_id": record.remediation_id, "updated_at": stamp(now)}):
                raise _Moved()
            return [self._pending("remediation", record, now)]

        try:
            entries = self._write(make, "The remediation record could not be stored")
        except _Refused as exc:
            self._refuse_final(exc.refusal.code, exc.refusal.detail, record, raw, digest)
        except (_Moved, *self._db.integrity_errors):
            stored = self._db.get_entry_by_record("remediation", record.remediation_id)
            if stored is not None and payload_digest(stored["payload"]) == digest:
                return {"entry": stored["entry"].model_dump(mode="json"), "entry_digest": stored["entry_digest"],
                        "payload": stored["payload"], "status": "duplicate"}, 200
            self._refuse("remediation_conflict", "another remediation of this subject was recorded first",
                         record, digest)
        due = _parse(row["remediation_due_at"])
        self._db.add_audit_event("remediation_recorded", {
            "remediation_id": record.remediation_id, "subject_kind": record.subject_kind,
            "subject_id": record.subject_id, "outcome": record.outcome, "steps": record.steps,
            "resource_id": record.resource_id, "store_sequence": entries[0].store_sequence,
            "remediation_due_at": row["remediation_due_at"], "late": due is not None and record.remediated_at > due,
        })
        current = self._current(record.subject_id, {**row, "state": "remediated",
                                                     "remediation_id": record.remediation_id})
        return {"entry": entries[0].model_dump(mode="json"), "entry_digest": entries[0].digest(),
                "payload": record.to_wire(), "status": "recorded", "remediation": self.item(current)}, 201

    def _subject_resource(self, record: RemediationRecord) -> str | None:
        """The resource of a subject with no remediation state (a judgement's), for the scope check."""
        if record.subject_kind != "judgement":
            return None
        stored = self._db.get_entry_by_record("judgement", record.subject_id)
        return stored["entry"].resource_id if stored is not None else None

    def _subject_problem(self, record: RemediationRecord, row: dict[str, Any]) -> str | None:
        """Why a remediation record does not name its subject's change, or None. The change's
        version comes from the state (kept when it was armed), not from the record of the change,
        which retention may have removed."""
        if record.subject_kind != row["subject_kind"]:
            return f"{record.subject_id} is a {row['subject_kind']}, not a {record.subject_kind}"
        if row["subject_kind"] == "decision" and row["fallback"] == NOT_EXECUTED:
            if (record.change_kind, record.change_id) != ("execution", record.subject_id):
                return "the decision was never executed: the record names the decision itself as its change"
            return None
        if (record.change_kind, record.change_id) != (row["change_kind"], row["change_id"]):
            return f"the remediation is of {row['change_kind']} {row['change_id']}"
        if record.resource_id != row["resource_id"]:
            return "the change is of another resource"
        version = row.get("change_version_id")
        if record.disabled_version_id is not None and version is not None and record.disabled_version_id != version:
            return f"the change made version {version}; the record disables {record.disabled_version_id}"
        return None

    def _rotation_problem(self, record: RemediationRecord, row: dict[str, Any]) -> tuple[str, str] | None:
        """The forward rotation is governed execution evidence the NA already holds: of the same
        resource, issuing the version the record names, by the same executor sovereign, made after
        the change, and cited by no other remediation."""
        if record.rotation_evidence_id is None:
            return None
        stored = self._db.get_entry_by_evidence_id(record.rotation_evidence_id)
        if stored is None or stored["entry"].entry_kind != "execution":
            return ("remediation_rotation_missing",
                    f"submit the forward rotation's execution evidence {record.rotation_evidence_id} first")
        action, version, _ = change_facts("execution", stored["payload"])
        if stored["entry"].resource_id != record.resource_id or action not in ("rotate", "update") \
                or version != record.version_id:
            return ("remediation_rotation_mismatch",
                    f"execution evidence {record.rotation_evidence_id} is not a rotation of {record.resource_id} "
                    f"to version {record.version_id}")
        executed_at = _parse(stored["payload"].get("executed_at")) or stored["entry"].recorded_at
        return rotation_problem(
            rotation_executor=str(stored["entry"].executor_sovereign_id),
            rotation_sequence=stored["entry"].store_sequence, rotation_executed_at=executed_at,
            record_executor=record.executor_sovereign_id, change_sequence=row.get("change_store_sequence"),
            changed_at=_parse(row.get("changed_at")),
            already_cited=self._db.rotation_cited(record.rotation_evidence_id),
        )
