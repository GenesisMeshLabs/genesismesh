"""Remediation, reviews and emergency changes (v1.4.0, Stage 3): the rules.

Pure functions only. The Network Authority loads stored state, passes it in
with the clock and appends what these return; verifiers run the same checks
on an export.

* ``remediation_plan`` states what a judged change leads to: ``cancel`` (a
  forward rotation then a disable, or a disable) or ``alert_only``, and the
  grace before it is due (``remediation_due_at = judged_at + grace``).
* ``next_state`` is the state table; every transition the NA makes goes
  through it, and a refused one is named by a stable code.
* ``check_remediation`` decides whether a controller's remediation record is
  authentic, in its key's scope and free of secret material.
* ``review_holder_problem`` and ``review_approval_problem`` are the review
  rules: a second holder decides, and the decider's signed admin request,
  embedded in the review, verifies offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal, Mapping, Sequence

from ..crypto import sign_model, verify_model_signature
from ..crypto.admin_auth import admin_signing_payload
from ..crypto.signing import SigningKeyLike, verify_signature
from ..models.boundary_policy import ANY_GATE, BoundaryPolicy, GateRemediation, PolicyGateEvaluation
from ..models.remediation import AdminApproval, RemediationRecord, ReviewRecord
from .evidence_store import EvidenceCheck, ExecutorKey
from .out_of_band import _key_permits, metadata_problem

# ---------------------------------------------------------------------------
# The state table
# ---------------------------------------------------------------------------

#: States of a change (Stage 2 states first, then Stage 3). A change enters
#: Stage 3 from its Stage 2 state: ``judged_denied``, ``indeterminate``,
#: ``judged_allowed`` or ``matched`` for a judged change, ``recorded`` for a
#: governed change under a decision that requires review.
RemediationState = Literal[
    "judged_denied", "judged_allowed", "indeterminate", "matched", "recorded",
    "remediation_due", "overdue", "remediated", "review_pending", "upheld", "waived", "review_denied",
]

#: What moves a change from one state to the next.
TransitionEvent = Literal[
    "arm",                 # remediation becomes due (a denied or indeterminate judgement, a review denial)
    "open_review",         # a review is requested or opened by the NA
    "due_passed",          # the due time passed without a remediation
    "record_remediation",  # a controller's remediation record is admitted
    "uphold", "deny", "waive",  # a review is decided
    "waiver_expired",      # a waiver's time passed
    "lifetime_ended",      # an upheld emergency change reached its maximum lifetime
]

_TRANSITIONS: dict[tuple[str, str], str] = {
    ("judged_denied", "arm"): "remediation_due",
    ("indeterminate", "arm"): "remediation_due",
    ("review_denied", "arm"): "remediation_due",
    ("judged_denied", "open_review"): "review_pending",
    ("indeterminate", "open_review"): "review_pending",
    ("judged_allowed", "open_review"): "review_pending",
    ("matched", "open_review"): "review_pending",
    ("recorded", "open_review"): "review_pending",
    ("remediation_due", "open_review"): "review_pending",
    ("overdue", "open_review"): "review_pending",
    ("upheld", "open_review"): "review_pending",
    ("waived", "open_review"): "review_pending",
    ("remediation_due", "due_passed"): "overdue",
    ("remediation_due", "record_remediation"): "remediated",
    ("overdue", "record_remediation"): "remediated",
    ("review_pending", "record_remediation"): "remediated",
    ("waived", "record_remediation"): "remediated",
    ("review_denied", "record_remediation"): "remediated",
    ("review_pending", "uphold"): "upheld",
    ("review_pending", "deny"): "review_denied",
    ("review_pending", "waive"): "waived",
    # A review pending when the remediation was recorded is still decided; it changes nothing.
    ("remediated", "uphold"): "remediated",
    ("remediated", "deny"): "remediated",
    ("waived", "waiver_expired"): "remediation_due",
    ("upheld", "lifetime_ended"): "remediation_due",
}

#: States in which something is still to happen (the default due queue).
OPEN_STATES: tuple[str, ...] = ("remediation_due", "overdue", "review_pending", "waived")

#: Stage 3 states (those a remediation state row can hold).
STAGE3_STATES: tuple[str, ...] = (
    "remediation_due", "overdue", "remediated", "review_pending", "upheld", "waived", "review_denied",
)

#: Codes a refused transition is answered with.
TransitionRefusal = Literal[
    "review_waiver_after_remediation",
    "review_after_remediation",
    "remediation_already_recorded",
    "review_not_pending",
    "review_already_pending",
    "remediation_not_due",
    "illegal_transition",
]


class TransitionRefused(Exception):
    """A transition the state table does not allow, named by a stable code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def next_state(state: str, event: str) -> str:
    """The state after ``event``; raises ``TransitionRefused`` when the table does not allow it."""
    target = _TRANSITIONS.get((state, event))
    if target is not None:
        return target
    raise TransitionRefused(_refusal(state, event), f"{event} is not allowed in state {state}")


def _refusal(state: str, event: str) -> str:
    if state == "remediated":
        if event == "waive":
            return "review_waiver_after_remediation"
        if event == "open_review":
            return "review_after_remediation"
        if event == "record_remediation":
            return "remediation_already_recorded"
    if event in ("uphold", "deny", "waive"):
        return "review_not_pending"
    if event == "open_review" and state == "review_pending":
        return "review_already_pending"
    if event == "record_remediation":
        return "remediation_not_due"
    return "illegal_transition"


def judgement_state(verdict: str, governed_by: str) -> str:
    """A judged change's Stage 2 state (the state table's entry point)."""
    if governed_by == "prior_decision":
        return "judged_denied" if verdict == "deny" else "matched"
    return {"allow": "judged_allowed", "deny": "judged_denied"}.get(verdict, "indeterminate")


# ---------------------------------------------------------------------------
# Remediation plans
# ---------------------------------------------------------------------------

#: Steps the NA states for a cancel (the controller reports ``disable`` or ``delete`` for ``disable``).
PlannedSteps = Literal["rotate_forward_then_disable", "disable", "none"]

#: Why a ``cancel`` fell back to ``alert_only``.
Fallback = Literal["not_versioned", "not_rotatable", "not_reversible", "indeterminate"]


@dataclass(frozen=True)
class RemediationDefaults:
    """What applies when no policy gives guidance (``NA_REMEDIATION_*`` settings)."""

    grace_seconds: int = 24 * 3600
    mode: str = "alert_only"


@dataclass(frozen=True)
class RemediationPlan:
    """What a judged change leads to, as the NA states it."""

    mode: str              # "cancel" or "alert_only"
    steps: str             # PlannedSteps
    fallback: str | None   # Fallback, when a cancel could not apply
    grace_seconds: int
    source: str            # "gate", "policy" or "default": where the guidance came from

    def due_at(self, at: datetime) -> datetime:
        """``remediation_due_at``: ``at`` (the judgement or review time) plus the grace."""
        return at + timedelta(seconds=self.grace_seconds)

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "steps": self.steps, "fallback": self.fallback,
                "grace_seconds": self.grace_seconds, "source": self.source}


def guidance(
    policies: Iterable[BoundaryPolicy], evaluations: Sequence[PolicyGateEvaluation], defaults: RemediationDefaults,
) -> tuple[str, int, str]:
    """(mode, grace_seconds, source) for a judged change.

    The guidance of each enforce-mode gate that failed (its own entry, or the
    policy's ``"*"``); without one, the ``"*"`` guidance of the policies that
    applied; without that, the defaults. Among several, ``cancel`` wins over
    ``alert_only``, and the shortest grace of the winning mode applies.
    """
    by_key = {(p.policy_id, p.version): p for p in policies}
    found: list[GateRemediation] = []
    for evaluation in evaluations:
        if evaluation.mode != "enforce" or evaluation.passed:
            continue
        policy = by_key.get((evaluation.policy_id, evaluation.policy_version))
        if policy is None or not policy.remediation:
            continue
        entry = policy.remediation.get(evaluation.gate_id) or policy.remediation.get(ANY_GATE)
        if entry is not None:
            found.append(entry)
    source = "gate"
    if not found:
        source = "policy"
        found = [p.remediation[ANY_GATE] for _, p in sorted(by_key.items())
                 if p.remediation and ANY_GATE in p.remediation]
    if not found:
        return defaults.mode, defaults.grace_seconds, "default"
    mode = "cancel" if any(g.mode == "cancel" for g in found) else "alert_only"
    return mode, min(g.grace_seconds for g in found if g.mode == mode), source


def cancel_steps(action: str, version_id: str | None, rotatable: bool) -> tuple[str, str | None]:
    """(steps, fallback) for cancelling a change, from what the change record says.

    A created resource nothing reads yet is disabled (or deleted). A rotated or
    updated resource with a version is rotated forward to a governed new
    version, then the denied version is disabled, unless the record says it
    cannot be rotated (``rotatable: false``). Without a version, or for a
    revocation or deletion (cancelling it would restore something), the
    cancel falls back to ``alert_only``.
    """
    if action == "create":
        return "disable", None
    if action in ("rotate", "update"):
        if version_id is None:
            return "none", "not_versioned"
        if not rotatable:
            return "none", "not_rotatable"
        return "rotate_forward_then_disable", None
    return "none", "not_reversible"


def remediation_plan(
    *,
    verdict: str,
    policies: Iterable[BoundaryPolicy],
    evaluations: Sequence[PolicyGateEvaluation],
    action: str,
    version_id: str | None,
    rotatable: bool,
    defaults: RemediationDefaults,
) -> RemediationPlan:
    """What a change judged ``verdict`` leads to. An ``indeterminate`` judgement always alerts."""
    mode, grace, source = guidance(policies, evaluations, defaults)
    if verdict == "indeterminate":
        return RemediationPlan("alert_only", "none", "indeterminate" if mode == "cancel" else None, grace, source)
    if mode != "cancel":
        return RemediationPlan("alert_only", "none", None, grace, source)
    steps, fallback = cancel_steps(action, version_id, rotatable)
    return RemediationPlan("alert_only" if fallback else "cancel", steps, fallback, grace, source)


def change_facts(kind: str, payload: Mapping[str, Any]) -> tuple[str, str | None, bool]:
    """(action, version_id, rotatable) of the record of a change.

    ``rotatable`` is false only when the record says so: an observation's
    ``metadata.rotatable`` or a controller's ``execution_parameters.rotatable``
    set to ``false``.
    """
    if kind == "observation":
        extra = payload.get("metadata") or {}
        version = payload.get("version_id")
        action = payload.get("action")
    else:
        extra = payload.get("execution_parameters") or {}
        version = extra.get("version_id")
        action = payload.get("resource_action")
    version = version if isinstance(version, str) and version else None
    return str(action or ""), version, extra.get("rotatable") is not False


def due_after_denial(current_due: datetime | None, decided_at: datetime, grace_seconds: int) -> datetime:
    """When a remediation a review denied is due: the grace from the decision, never later than
    the time it was already due (a review holds a remediation, it does not extend it)."""
    due = decided_at + timedelta(seconds=grace_seconds)
    return min(current_due, due) if current_due is not None else due


def due_after_waiver(waived_until: datetime, grace_seconds: int) -> datetime:
    """When a remediation is due once a waiver ends: its grace again, from the waiver's end."""
    return waived_until + timedelta(seconds=grace_seconds)


def steps_problem(plan_mode: str, plan_steps: str, record: RemediationRecord) -> str | None:
    """Why a remediation record does not carry out the plan the NA stated, or None."""
    if plan_mode == "alert_only":
        return None if record.outcome == "alerted" else (
            f"the remediation is alert_only; the record says {record.outcome} ({record.steps})")
    if record.outcome != "cancelled":
        return f"the remediation is a cancel ({plan_steps}); the record only alerted"
    if plan_steps == "disable" and record.steps in ("disable", "delete"):
        return None
    if record.steps == plan_steps:
        return None
    return f"the remediation is {plan_steps}; the record says {record.steps}"


# ---------------------------------------------------------------------------
# Remediation records
# ---------------------------------------------------------------------------

#: Codes a refused remediation record is answered with (``422``, ``409`` for a
#: conflict or a state that does not allow it).
RemediationRejectionCode = Literal[
    "remediation_malformed",
    "remediation_invalid_signature",
    "remediation_unknown_key",
    "remediation_key_retired",
    "remediation_out_of_scope",
    "remediation_secret_material",
    "remediation_conflict",
    "remediation_subject_not_found",
    "remediation_subject_mismatch",
    "remediation_steps_mismatch",
    "remediation_rotation_missing",
    "remediation_rotation_mismatch",
    "remediation_not_due",
    "remediation_already_recorded",
]

#: Refusals of an authentic remediation record (its signature verifies) that
#: no later attempt can overcome: the record is kept as a quarantine entry,
#: since what it describes already happened. Left out: a subject or rotation
#: evidence the NA does not hold yet (the controller retries).
QUARANTINED_REMEDIATION_CODES: frozenset[str] = frozenset({
    "remediation_key_retired",
    "remediation_out_of_scope",
    "remediation_subject_mismatch",
    "remediation_steps_mismatch",
    "remediation_rotation_mismatch",
    "remediation_not_due",
    "remediation_already_recorded",
})


def remediation_secret_problem(record: RemediationRecord) -> str | None:
    """Why a remediation record may carry secret material, or None: versions and a note only."""
    return metadata_problem({k: v for k, v in {
        "version_id": record.version_id, "disabled_version_id": record.disabled_version_id,
        "detail": record.detail,
    }.items() if v is not None})


def check_remediation(record: RemediationRecord, key: ExecutorKey | None) -> EvidenceCheck:
    """Whether a remediation record is authentic, signed by an executor key covering its
    resource, and free of secret material (the 1.3.1 guards)."""
    if record.signature is None:
        return EvidenceCheck("remediation_invalid_signature", "record is not signed")  # type: ignore[arg-type]
    if key is None or key.executor_sovereign_id != record.executor_sovereign_id:
        return EvidenceCheck("remediation_unknown_key",  # type: ignore[arg-type]
                             f"signing key is not registered for {record.executor_sovereign_id!r}")
    if not verify_model_signature(record, record.signature, key.public_key):
        return EvidenceCheck("remediation_invalid_signature", "signature does not verify")  # type: ignore[arg-type]
    problem = _key_permits(key, "executor", record.resource_id, "remediation")
    if problem is not None:
        return EvidenceCheck(*problem)  # type: ignore[arg-type]
    secret = remediation_secret_problem(record)
    if secret:
        return EvidenceCheck("remediation_secret_material", secret)  # type: ignore[arg-type]
    return EvidenceCheck(None, "accepted")


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

#: The route an operator requests a review on, and the one a decider decides it on.
REVIEW_REQUEST_PATH = "/admin/evidence/reviews"

#: How far an embedded approval's timestamp may be from the time the NA recorded
#: (the NA refuses admin requests older than this when they arrive).
APPROVAL_MAX_AGE = timedelta(seconds=300)

#: Fields a decision's body may carry, and a request's.
DECISION_FIELDS = frozenset({"verdict", "waive_until", "note"})
REQUEST_FIELDS = frozenset({"subject_kind", "subject_id", "justification"})

ReviewRejectionCode = Literal[
    "invalid_review",
    "review_not_found",
    "review_subject_not_found",
    "review_needs_named_holder",
    "review_same_holder_as_requester",
    "review_same_holder_as_actor",
    "review_already_decided",
    "review_waiver_too_long",
    "review_waiver_beyond_lifetime",
]


def review_decision_path(review_id: str) -> str:
    return f"{REVIEW_REQUEST_PATH}/{review_id}/decide"


def actor_holder(actor: str | None, mapping: Mapping[str, str], holders: Iterable[str]) -> str | None:
    """The holder an observed actor maps to: ``NA_REVIEW_ACTOR_HOLDERS_JSON``, else a holder
    of that very name, else None. The actor is what the source reported, not authenticated."""
    if actor is None:
        return None
    if actor in mapping:
        return mapping[actor]
    return actor if actor in set(holders) else None


def review_holder_problem(
    *,
    decided_by: str,
    decider_holder: str,
    requested_by: str | None,
    requester_holder: str | None,
    actor: str | None,
    actor_holder: str | None,
) -> tuple[str, str] | None:
    """(code, detail) when the decider is not a second holder, or None.

    The decider's key and holder must differ from the requester's, and its
    holder from the observed actor's (an actor named like the decider's key
    or holder counts as the decider).
    """
    if requested_by is not None and (decided_by == requested_by or decider_holder == requester_holder):
        return ("review_same_holder_as_requester",
                f"holder {decider_holder!r} requested this review; another holder decides it")
    if actor is not None and (decider_holder == actor_holder or actor in (decided_by, decider_holder)):
        return ("review_same_holder_as_actor",
                f"holder {decider_holder!r} is the observed actor ({actor!r}); another holder decides")
    return None


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def admin_approval_valid(approval: AdminApproval) -> bool:
    """Whether the operator's signature verifies over the request it kept (signature version 2)."""
    try:
        payload = admin_signing_payload(
            method=approval.method, path=approval.path, query=approval.query, audience=approval.audience,
            body=approval.body, key_id=approval.key_id, timestamp=approval.timestamp, nonce=approval.nonce,
        )
        return verify_signature(payload, approval.admin_signature, approval.public_key)
    except (ValueError, TypeError):
        return False


def _approval_problem(
    approval: AdminApproval, *, who: str, key_id: str, path: str, audiences: Sequence[str], at: datetime,
) -> str | None:
    if not admin_approval_valid(approval):
        return f"the {who}'s signature does not verify over its request"
    if approval.key_id != key_id:
        return f"the {who}'s request is signed by {approval.key_id}, not {key_id}"
    if approval.method != "POST" or approval.path != path or approval.query:
        return f"the {who}'s request is {approval.method} {approval.path}, not POST {path}"
    if approval.audience not in audiences:
        return f"the {who}'s request is for another Network Authority"
    signed_at = _instant(approval.timestamp)
    if signed_at is None or abs(signed_at - at) > APPROVAL_MAX_AGE:
        return f"the {who}'s request was signed more than {int(APPROVAL_MAX_AGE.total_seconds())}s from when it was recorded"
    return None


def review_approval_problem(review: ReviewRecord, audiences: Sequence[str]) -> str | None:
    """Why the requests embedded in a review do not prove it, or None.

    Offline, with the review alone and the NA's public key (the audience): the
    decider signed ``POST /admin/evidence/reviews/<review_id>/decide`` with
    exactly the verdict, waiver time and note the review records, within
    ``APPROVAL_MAX_AGE`` of ``decided_at``; a requester signed
    ``POST /admin/evidence/reviews`` with exactly the subject and
    justification it records, within that of ``requested_at``. Whether each
    public key is the operator key's is checked against the holder registry.
    """
    problem = _approval_problem(review.approval, who="decider", key_id=review.decided_by,
                                path=review_decision_path(review.review_id), audiences=audiences, at=review.decided_at)
    if problem:
        return problem
    body = review.approval.body
    if set(body) - DECISION_FIELDS:
        return "the decider's request carries fields the review does not record"
    if body.get("verdict") != review.verdict or body.get("note") != review.note:
        return "the decider's request gives another verdict or note"
    waiver = _instant(body.get("waive_until")) if body.get("waive_until") is not None else None
    if (body.get("waive_until") is None) != (review.waive_until is None) or waiver != review.waive_until:
        return "the decider's request gives another waiver time"
    if review.request_approval is not None:
        assert review.requested_by is not None
        problem = _approval_problem(review.request_approval, who="requester", key_id=review.requested_by,
                                    path=REVIEW_REQUEST_PATH, audiences=audiences, at=review.requested_at)
        if problem:
            return problem
        expected = {"subject_kind": review.subject_kind, "subject_id": review.subject_id,
                    "justification": review.justification}
        if review.request_approval.body != expected:
            return "the requester's request names another subject or justification"
    return None


def sign_review(record: ReviewRecord, signing_key: SigningKeyLike, key_id: str) -> ReviewRecord:
    """Return a review signed by the NA."""
    return record.model_copy(update={"signature": sign_model(record, signing_key, key_id)})


def entry_index(record: RemediationRecord | ReviewRecord) -> dict[str, Any]:
    """Search fields of a Stage 3 entry's envelope."""
    if isinstance(record, RemediationRecord):
        return {"record_id": record.remediation_id, "subject_id": record.subject_id,
                "resource_id": record.resource_id, "executor_sovereign_id": record.executor_sovereign_id,
                "outcome": record.outcome}
    return {"record_id": record.review_id, "subject_id": record.subject_id, "resource_id": record.resource_id,
            "capability": record.capability, "outcome": record.verdict}
