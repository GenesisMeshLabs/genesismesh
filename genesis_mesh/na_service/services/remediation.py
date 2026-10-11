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
  ``ReviewRecord`` with the decider's signed request embedded;
* the controller submits a ``RemediationRecord`` signed by its executor key
  once it has cancelled the change (or alerted), and records through the
  NA that it told the actor (an audit event and ``notified_at``);
* due times are swept: an overdue remediation raises one audit event, a
  waiver's end and an emergency change's end of life re-arm remediation.

Every transition goes through ``trust.remediation.next_state``. A state row
and the store entry that moves it are written in one transaction, and an
update names the state it expects, so two instances cannot both make one
transition.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable, NoReturn, Sequence

from pydantic import ValidationError as PydanticValidationError

from ...models.boundary_policy import BoundaryPolicy, PolicyBinding
from ...models.context import BoundaryDecision, ContextRecord
from ...models.evidence_store import EvidenceStoreEntry, canonical_json, payload_digest
from ...models.out_of_band import JudgementRecord
from ...models.remediation import MAX_WAIVER_SECONDS, AdminApproval, RemediationRecord, ReviewRecord
from ...trust.evidence_store import EvidenceCheck, build_entry
from ...trust.remediation import (
    DECISION_FIELDS,
    OPEN_STATES,
    QUARANTINED_REMEDIATION_CODES,
    REQUEST_FIELDS,
    STAGE3_STATES,
    RemediationPlan,
    TransitionRefused,
    actor_holder,
    change_facts,
    check_remediation,
    due_after_denial,
    due_after_waiver,
    entry_index,
    guidance,
    judgement_state,
    next_state,
    remediation_plan,
    remediation_secret_problem,
    review_holder_problem,
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

#: Judgements armed at start whose arming failed when they were judged.
ARM_START_LIMIT = 500


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


class RemediationService:
    """NA application logic for remediations, reviews and the due queue."""

    def __init__(self, service: "NetworkAuthorityService") -> None:
        self._na = service
        self._last_sweep = 0.0

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
        return self._oob.enabled and self._na.evidence_remediation == "on"

    def require_enabled(self) -> None:
        self._oob.require_enabled()
        if not self.enabled:
            raise NotFoundError("Remediations and reviews are not recorded (EVIDENCE_REMEDIATION=off)",
                                code="remediation_disabled")

    def _now(self) -> datetime:
        # One clock with the out-of-band service: judging and arming agree on what "now" is.
        now: datetime = self._oob._now()
        return now

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
        except (_Moved, _Refused, self._db.integrity_errors):
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

    def _emergency_policies(self) -> list[BoundaryPolicy]:
        policies = []
        for row in self._db.list_boundary_policy_rows():
            if "emergency" not in str(row.get("policy_json", "")):
                continue
            policy = self._db.parse_boundary_policy_row(row)
            if policy is not None and policy.emergency is not None:
                policies.append(policy)
        return policies

    def emergency_capabilities_for(self, capability: str) -> list[str]:
        """The emergency capabilities that stand for ``capability`` (any stored policy version)."""
        return sorted({p.selector.capabilities[0] for p in self._emergency_policies()
                       if p.emergency is not None and p.emergency.stands_for == capability
                       and len(p.selector.capabilities) == 1})

    def ordinary_capability(self, capability: str) -> str | None:
        """The ordinary capability ``capability`` stands for, when it is an emergency capability."""
        for policy in self._emergency_policies():
            if policy.emergency is not None and policy.selector.capabilities == [capability]:
                return policy.emergency.stands_for
        return None

    # -- arming -------------------------------------------------------------------

    def on_judgement(self, stored: dict[str, Any]) -> None:
        """After a judgement is stored: arm its remediation, or open its review. A failure is
        logged and repaired at the next start (``ensure_states``)."""
        if not self.enabled:
            return
        try:
            self._arm_judgement(stored)
        except Exception as exc:  # noqa: BLE001 -- the judgement itself is stored
            logger.warning("arming the remediation of judgement %s failed: %s", stored["entry"].record_id, exc)

    def _arm_judgement(self, stored: dict[str, Any]) -> None:
        judgement = JudgementRecord.model_validate(stored["payload"])
        if self._db.get_remediation_state(judgement.judgement_id) is not None:
            return
        policies = self._policies(judgement.policy_binding)
        flagged = bool(judgement.flagged_for_review)
        reviewed = any(p.review_required or p.emergency for p in policies)
        opened_for = "flagged_for_review" if flagged else (
            "review_required" if reviewed and judgement.verdict == "allow" else None)
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
        state = judgement_state(judgement.verdict, judgement.governed_by)
        due = plan.due_at(judgement.judged_at) if judgement.verdict != "allow" else None
        emergency = next((p.emergency for p in policies if p.emergency is not None), None)
        lifetime = (judgement.evaluated_as_of + timedelta(seconds=emergency.max_lifetime_seconds)
                    if emergency is not None and judgement.verdict == "allow" else None)
        actor = change["payload"].get("actor") if judgement.subject_kind == "observation" else None
        self._create(
            subject_kind="judgement", subject_id=judgement.judgement_id, subject_digest=stored["entry"].payload_digest,
            change_kind=judgement.subject_kind, change_id=judgement.subject_id, resource_id=judgement.resource_id,
            capability=judgement.capability, actor=actor, verdict=judgement.verdict, state=state, plan=plan,
            due=due, lifetime=lifetime, opened_for=opened_for,
        )

    def on_decision(self, decision: BoundaryDecision, context: ContextRecord, entry: EvidenceStoreEntry) -> None:
        """After an authorized decision is stored: under a policy that requires review (an
        emergency policy always does), open its review. A failure is logged; the decision stands."""
        if not self.enabled or not decision.authorized:
            return
        try:
            policies = self._policies(decision.policy_binding)
            if not any(p.review_required or p.emergency for p in policies):
                return
            emergency = next((p.emergency for p in policies if p.emergency is not None), None)
            lifetime = (decision.decision_made_at + timedelta(seconds=emergency.max_lifetime_seconds)
                        if emergency is not None else None)
            plan = self._decision_plan(policies)
            self._create(
                subject_kind="decision", subject_id=decision.decision_id, subject_digest=entry.payload_digest,
                change_kind="execution", change_id=None, resource_id=None, capability=context.requested_capability,
                actor=context.requester_sovereign_id, verdict="allow", state="recorded", plan=plan, due=None,
                lifetime=lifetime, opened_for="review_required",
            )
        except Exception as exc:  # noqa: BLE001 -- the decision is stored and returned
            logger.warning("opening the review of decision %s failed: %s", decision.decision_id, exc)

    def _create(
        self, *, subject_kind: str, subject_id: str, subject_digest: str, change_kind: str, change_id: str | None,
        resource_id: str | None, capability: str | None, actor: str | None, verdict: str, state: str,
        plan: RemediationPlan, due: datetime | None, lifetime: datetime | None, opened_for: str | None,
        requested: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Create a subject's state: armed, or under review (one transaction). Returns the row and
        whether this call created it (False: another request created the subject's state first)."""
        now = self._now()
        target = next_state(state, "open_review" if opened_for else "arm")
        review_id = str(uuid.uuid4()) if opened_for else None
        row = {
            "subject_id": subject_id, "subject_kind": subject_kind, "subject_digest": subject_digest,
            "change_kind": change_kind, "change_id": change_id, "resource_id": resource_id, "capability": capability,
            "actor": actor, "verdict": verdict, "state": target, "mode": plan.mode, "steps": plan.steps,
            "fallback": plan.fallback, "grace_seconds": plan.grace_seconds, "guidance_source": plan.source,
            "remediation_due_at": stamp(due) if due else None, "lifetime_ends_at": stamp(lifetime) if lifetime else None,
            "review_id": review_id, "created_at": stamp(now), "updated_at": stamp(now),
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
            "subject_kind": subject_kind, "subject_id": subject_id, "state": target, "mode": plan.mode,
            "steps": plan.steps, "remediation_due_at": row["remediation_due_at"], "review_id": review_id,
            "opened_for": opened_for,
        })
        return row, True

    def enabled_since(self) -> datetime:
        """When the records were first turned on (the first ``remediation_enabled`` audit event, written
        now when there is none). Judgements recorded earlier are not armed at start: a store
        upgraded from 1.3 does not turn its past denials into overdue remediations at once."""
        events = self._db.list_audit_events(event_types=["remediation_enabled"])
        times = [t for t in (_parse((e.get("details") or {}).get("since") or e.get("created_at")) for e in events)
                 if t is not None]
        if times:
            return min(times)
        now = self._now()
        self._db.add_audit_event("remediation_enabled", {"since": stamp(now)})
        return now

    def ensure_states(self) -> None:
        """At start: arm judgements whose arming failed, and sweep due times. Never fails start."""
        if not self.enabled:
            return
        try:
            since = self.enabled_since()
            for judgement_id in self._db.judgements_needing_state(ARM_START_LIMIT, recorded_since=since):
                stored = self._db.get_entry_by_record("judgement", judgement_id)
                if stored is not None:
                    self.on_judgement(stored)
            self.sweep()
        except Exception as exc:  # noqa: BLE001
            logger.error("remediation start checks failed: %s", exc)

    # -- sweeping -------------------------------------------------------------------

    def sweep(self, now: datetime | None = None) -> dict[str, int]:
        """Move what is due: remediations past their due time become ``overdue`` (one audit event
        each), ended waivers and emergency lifetimes re-arm remediation. Returns the counts."""
        if not self.enabled:
            return {}
        now = now or self._now()
        self._last_sweep = time.monotonic()
        counts = {"overdue": 0, "waivers_ended": 0, "lifetimes_ended": 0}
        for row in self._db.remediation_states_due("remediation_due_at", "remediation_due", now, SWEEP_BATCH):
            if self._move(row, "due_passed", {"overdue_since": stamp(now)}):
                counts["overdue"] += 1
                self._db.add_audit_event("remediation_overdue", {
                    "subject_kind": row["subject_kind"], "subject_id": row["subject_id"],
                    "resource_id": row["resource_id"], "actor": row["actor"],
                    "remediation_due_at": row["remediation_due_at"], "notified_at": row["notified_at"],
                })
        for row in self._db.remediation_states_due("waived_until", "waived", now, SWEEP_BATCH):
            ended = _parse(row["waived_until"])
            assert ended is not None
            due = due_after_waiver(ended, int(row["grace_seconds"]))
            if self._move(row, "waiver_expired", {"remediation_due_at": stamp(due), **self._replan(row)}):
                counts["waivers_ended"] += 1
                self._db.add_audit_event("waiver_expired", {
                    "subject_id": row["subject_id"], "waived_until": row["waived_until"],
                    "remediation_due_at": stamp(due),
                })
        for row in self._db.remediation_states_due("lifetime_ends_at", "upheld", now, SWEEP_BATCH):
            ended = _parse(row["lifetime_ends_at"])
            assert ended is not None
            due = due_after_waiver(ended, int(row["grace_seconds"]))
            if self._move(row, "lifetime_ended", {"remediation_due_at": stamp(due), **self._replan(row)}):
                counts["lifetimes_ended"] += 1
                self._db.add_audit_event("emergency_lifetime_ended", {
                    "subject_id": row["subject_id"], "lifetime_ends_at": row["lifetime_ends_at"],
                    "remediation_due_at": stamp(due),
                })
        return counts

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
        target = next_state(row["state"], event)
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

    def _decision_plan(self, policies: list[BoundaryPolicy]) -> RemediationPlan:
        """A decision's plan before its execution evidence is known: the guidance only; the steps
        follow from the evidence once a remediation is due (``_replan``)."""
        mode, grace, source = guidance(policies, [], self._na.remediation_defaults)
        return RemediationPlan(mode, "none", None, grace, source)

    def _replan(self, row: dict[str, Any]) -> dict[str, Any]:
        """For a decision's remediation, the plan and change from its latest execution evidence
        (unknown when its review opened); nothing for a judgement's, whose change is fixed."""
        if row["subject_kind"] != "decision":
            return {}
        stored = self._db.last_execution_for_decision(row["subject_id"])
        if stored is None:
            return {}
        decision = self._db.get_decision_entry(row["subject_id"])
        binding = None
        if decision is not None:
            binding = BoundaryDecision.model_validate(decision["payload"]["decision"]).policy_binding
        action, version, rotatable = change_facts("execution", stored["payload"])
        plan = remediation_plan(verdict="deny", policies=self._policies(binding), evaluations=[], action=action,
                                version_id=version, rotatable=rotatable, defaults=self._na.remediation_defaults)
        return {"change_id": stored["entry"].evidence_id, "resource_id": stored["entry"].resource_id,
                "mode": plan.mode, "steps": plan.steps, "fallback": plan.fallback,
                "grace_seconds": plan.grace_seconds, "guidance_source": plan.source}

    # -- the due queue --------------------------------------------------------------

    def item(self, row: dict[str, Any]) -> dict[str, Any]:
        """One remediation state as the routes and the changes view show it."""
        out = {k: row.get(k) for k in (
            "subject_kind", "subject_id", "change_kind", "change_id", "resource_id", "capability", "actor",
            "verdict", "state", "mode", "steps", "fallback", "grace_seconds", "guidance_source",
            "remediation_due_at", "lifetime_ends_at", "waived_until", "review_id", "remediation_id",
            "notified_at", "notified_by", "overdue_since", "created_at", "updated_at",
        )}
        if row["state"] == "review_pending" and row.get("review_id"):
            review = self._db.get_remediation_review(row["review_id"])
            if review is not None:
                out["review"] = self._review_summary(review)
        return out

    @staticmethod
    def _review_summary(review: dict[str, Any]) -> dict[str, Any]:
        return {k: review[k] for k in ("review_id", "subject_id", "opened_for", "requested_by", "requester_holder",
                                       "justification", "requested_at", "decided_at", "verdict")}

    def queue(self, args: dict[str, str]) -> dict[str, Any]:
        """``GET /admin/evidence/remediations``: states in ``state`` (default: the open ones), oldest first."""
        self.require_enabled()
        state = args.get("state")
        if state is not None and state not in STAGE3_STATES:
            raise BadRequestError(f"state must be one of {', '.join(STAGE3_STATES)}", code="invalid_remediation_query")
        try:
            limit = int(args.get("limit") or 100)
        except ValueError:
            raise BadRequestError("limit must be an integer", code="invalid_remediation_query") from None
        if not 1 <= limit <= QUEUE_LIMIT:
            raise BadRequestError(f"limit must be 1..{QUEUE_LIMIT}", code="invalid_remediation_query")
        after_raw = args.get("after")
        after: tuple[str, str] | None = None
        if after_raw:
            created, sep, subject = after_raw.partition("|")
            at = _parse(created)
            if not sep or not subject or at is None:
                raise BadRequestError("after is the next_after value of the previous page",
                                      code="invalid_remediation_query")
            after = (stamp(at), subject)
        self.sweep()
        rows = self._db.list_remediation_states([state] if state else list(OPEN_STATES), after=after, limit=limit)
        last = rows[-1] if len(rows) == limit else None
        return {
            "state": state, "count": len(rows),
            "remediations": [self.item(r) for r in rows],
            # The time with Z, so the cursor needs no escaping in a query string.
            "next_after": f"{last['created_at'].replace('+00:00', 'Z')}|{last['subject_id']}" if last else None,
        }

    def get(self, subject_id: str) -> dict[str, Any]:
        """One subject's remediation state, its reviews and its stored records."""
        self.require_enabled()
        self.maybe_sweep()
        row = self._db.get_remediation_state(subject_id)
        if row is None:
            raise NotFoundError("no remediation or review for this subject", code="remediation_not_found")
        entries = self._db.remediation_entries_for([subject_id])
        return {
            **self.item(row),
            "reviews": [self._review_summary(r) for r in self._db.remediation_reviews_for(subject_id)],
            "records": [{"entry": e["entry"].model_dump(mode="json"), "entry_digest": e["entry_digest"],
                         "payload": e["payload"]} for e in entries],
        }

    def states_for(self, subject_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Remediation states by subject, for the changes view (empty with the records off)."""
        if not self.enabled:
            return {}
        self.maybe_sweep()
        return self._db.remediation_states_for(list(subject_ids))

    def counts(self) -> dict[str, Any]:
        """Additive fields for ``/admin/evidence/status``."""
        self.maybe_sweep()
        by_state = self._db.count_remediation_states()
        return {"remediation": {s: by_state.get(s, 0) for s in STAGE3_STATES if s != "review_denied"}}

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
        current = self._db.get_remediation_state(subject_id)
        assert current is not None
        return self.item(current)

    # -- reviews ------------------------------------------------------------------

    def _holders(self) -> dict[str, dict[str, Any]]:
        holders: dict[str, dict[str, Any]] = self._oob.operator_holders()
        return holders

    def _named_holder(self, key_id: str, holders: dict[str, dict[str, Any]], who: str) -> str:
        known = holders.get(key_id)
        if known is None or not known.get("holder") or known["holder"] == key_id:
            raise ConflictError(f"the {who}'s operator key {key_id} has no named holder in the store",
                                code="review_needs_named_holder")
        return str(known["holder"])

    def _subject_entry(self, subject_kind: str, subject_id: str) -> dict[str, Any] | None:
        if subject_kind == "judgement":
            stored: dict[str, Any] | None = self._db.get_entry_by_record("judgement", subject_id)
            return stored
        return self._db.get_decision_entry(subject_id)  # type: ignore[no-any-return]

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
        stored = self._subject_entry(kind, subject_id)
        if stored is None:
            raise NotFoundError(f"no {kind} {subject_id!r} is stored", code="review_subject_not_found")
        holder = self._named_holder(requester, self._holders(), "requester")
        approval_json = json.dumps(AdminApproval.model_validate(approval).model_dump(mode="json"),
                                   sort_keys=True, separators=(",", ":"))
        requested = {"requested_by": requester, "requester_holder": holder, "justification": justification,
                     "request_approval_json": approval_json}
        row = self._db.get_remediation_state(subject_id)
        if row is None:
            row = self._create_for_request(kind, subject_id, stored, requested)
            review_id = row["review_id"]
        else:
            review_id = self._open_on(row, requested)
        self._db.add_audit_event("review_requested", {
            "review_id": review_id, "subject_kind": kind, "subject_id": subject_id, "requested_by": requester,
            "requester_holder": holder,
        })
        current = self._db.get_remediation_state(subject_id)
        assert current is not None
        return {"review_id": review_id, **self.item(current)}

    def _create_for_request(self, kind: str, subject_id: str, stored: dict[str, Any],
                            requested: dict[str, Any]) -> dict[str, Any]:
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
            due = plan.due_at(judgement.judged_at) if judgement.verdict != "allow" else None
            return self._create_checked(
                subject_kind="judgement", subject_id=subject_id, subject_digest=stored["entry"].payload_digest,
                change_kind=judgement.subject_kind, change_id=judgement.subject_id,
                resource_id=judgement.resource_id, capability=judgement.capability, actor=actor,
                verdict=judgement.verdict, state=judgement_state(judgement.verdict, judgement.governed_by),
                plan=plan, due=due, lifetime=None, opened_for="requested", requested=requested,
            )
        decision = BoundaryDecision.model_validate(stored["payload"]["decision"])
        if not decision.authorized:
            raise ConflictError("a denied decision changed nothing; there is nothing to review",
                                code="illegal_transition")
        context = ContextRecord.model_validate(stored["payload"]["context"])
        plan = self._decision_plan(self._policies(decision.policy_binding))
        return self._create_checked(
            subject_kind="decision", subject_id=subject_id, subject_digest=stored["entry"].payload_digest,
            change_kind="execution", change_id=None, resource_id=None, capability=context.requested_capability,
            actor=context.requester_sovereign_id, verdict="allow", state="recorded", plan=plan, due=None,
            lifetime=None, opened_for="requested", requested=requested,
        )

    def _create_checked(self, **kwargs: Any) -> dict[str, Any]:
        try:
            row, created = self._create(**kwargs)
        except TransitionRefused as exc:
            raise ConflictError(exc.detail, code=exc.code) from None
        if not created:
            # Another request created this subject's state at the same moment: open the review on it.
            review_id = self._open_on(row, kwargs["requested"])
            return {**row, "review_id": review_id}
        return row

    def _open_on(self, row: dict[str, Any], requested: dict[str, Any]) -> str:
        """Open a requested review on an existing state (one transaction). Returns the review id."""
        try:
            target = next_state(row["state"], "open_review")
        except TransitionRefused as exc:
            raise ConflictError(exc.detail, code=exc.code) from None
        review_id = str(uuid.uuid4())
        now = self._now()

        def make(db: Any) -> list[Any]:
            if not db.update_remediation_state(row["subject_id"], row["state"], {
                    "state": target, "review_id": review_id, "updated_at": stamp(now)}):
                raise _Moved()
            db.insert_remediation_review({"review_id": review_id, "subject_id": row["subject_id"],
                                          "opened_for": "requested", "requested_at": stamp(now), **requested})
            return []

        try:
            self._write(make, "The review could not be stored")
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
            parsed = _parse(raw_until) if isinstance(raw_until, str) else None
            if parsed is None or parsed <= now:
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
        mapped = actor_holder(row["actor"], self._na.review_actor_holders,
                              [str(h["holder"]) for h in holders.values() if h.get("holder")])
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
            next_state(row["state"], event)
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

        outcome: dict[str, Any] = {}

        def make(db: Any) -> list[Any]:
            current = db.get_remediation_state(row["subject_id"])
            if current is None or current["state"] != row["state"]:
                raise _Moved()
            if not db.mark_remediation_review_decided(review_id, verdict, now):
                raise _Moved()
            try:
                target = next_state(current["state"], event)
            except TransitionRefused as exc:
                raise _Refused(exc) from None
            changes: dict[str, Any] = {"updated_at": stamp(now)}
            if target == "review_denied":
                changes.update(self._replan(current))
                due = due_after_denial(_parse(current["remediation_due_at"]), now,
                                       int(changes.get("grace_seconds", current["grace_seconds"])))
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
        current = self._db.get_remediation_state(row["subject_id"])
        assert current is not None
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
        try:
            record = RemediationRecord.model_validate(raw)
        except PydanticValidationError as exc:
            self._refuse("remediation_malformed", f"record does not match the RemediationRecord model: "
                         f"{exc.errors()[0].get('msg', '')}", None, digest)
        difference = _exact_form_problem(raw, record)
        if difference is not None:
            self._refuse("remediation_malformed", f"record is not in its exact serialized form: {difference}",
                         record, digest)
        key = self._oob._key(record.signature.key_id if record.signature else None)
        check: EvidenceCheck = check_remediation(record, key)
        if not check.accepted:
            assert check.code is not None
            self._refuse(check.code, check.detail, record, digest,
                         self._quarantine(raw, record, check.code, check.detail))
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
        if row is None:
            if self._subject_entry(record.subject_kind, record.subject_id) is None:
                self._refuse("remediation_subject_not_found",
                             f"no {record.subject_kind} {record.subject_id!r} is stored", record, digest)
            self._refuse_final("remediation_not_due", "nothing is due for this subject", record, raw, digest)
        problem = self._subject_problem(record, row)
        if problem is not None:
            self._refuse_final("remediation_subject_mismatch", problem, record, raw, digest)
        # A decision's steps follow from its latest execution evidence (known once it is stored).
        planned = {**row, **self._replan(row)}
        problem = steps_problem(planned["mode"], planned["steps"], record)
        if problem is not None:
            self._refuse_final("remediation_steps_mismatch", problem, record, raw, digest)
        rotation = self._rotation_problem(record, row)
        if rotation is not None:
            code, detail = rotation
            if code == "remediation_rotation_missing":
                self._refuse(code, detail, record, digest)
            self._refuse_final(code, detail, record, raw, digest)
        try:
            next_state(row["state"], "record_remediation")
        except TransitionRefused as exc:
            self._refuse_final(exc.code, exc.detail, record, raw, digest)

        def make(db: Any) -> list[Any]:
            current = db.get_remediation_state(record.subject_id)
            if current is None:
                raise _Moved()
            try:
                target = next_state(current["state"], "record_remediation")
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
        current = self._db.get_remediation_state(record.subject_id)
        assert current is not None
        return {"entry": entries[0].model_dump(mode="json"), "entry_digest": entries[0].digest(),
                "payload": record.to_wire(), "status": "recorded", "remediation": self.item(current)}, 201

    def _subject_problem(self, record: RemediationRecord, row: dict[str, Any]) -> str | None:
        """Why a remediation record does not name its subject's change, or None."""
        if record.subject_kind != row["subject_kind"]:
            return f"{record.subject_id} is a {row['subject_kind']}, not a {record.subject_kind}"
        if row["subject_kind"] == "judgement":
            if (record.change_kind, record.change_id) != (row["change_kind"], row["change_id"]):
                return f"the judgement is of {row['change_kind']} {row['change_id']}"
            if record.resource_id != row["resource_id"]:
                return f"the judged change is of {row['resource_id']}"
        else:
            if record.change_kind != "execution":
                return "a decision's change is its execution evidence"
            stored = self._db.get_entry_by_evidence_id(record.change_id)
            if stored is None or stored["entry"].decision_id != record.subject_id \
                    or stored["entry"].resource_id != record.resource_id:
                return f"no execution evidence of {record.resource_id} under decision {record.subject_id} " \
                       f"is {record.change_id}"
        version = self._changed_version(record, row)
        if record.disabled_version_id is not None and version is not None and record.disabled_version_id != version:
            return f"the change made version {version}; the record disables {record.disabled_version_id}"
        return None

    def _changed_version(self, record: RemediationRecord, row: dict[str, Any]) -> str | None:
        kind = record.change_kind
        if kind == "execution":
            stored = self._db.get_entry_by_evidence_id(record.change_id)
        else:
            stored = self._db.get_entry_by_record(kind, record.change_id)
        if stored is None:
            return None
        return change_facts(kind, stored["payload"])[1]

    def _rotation_problem(self, record: RemediationRecord, row: dict[str, Any]) -> tuple[str, str] | None:
        """The forward rotation is governed execution evidence the NA already holds, of the same
        resource, issuing the version the record names."""
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
        return None
