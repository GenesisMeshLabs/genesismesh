"""Changes made outside the controlled path (v1.3.0, Stage 2): checks and judgements.

Pure functions only. The Network Authority loads stored state, passes it in
with the clock, and appends what these return; nothing here performs I/O.

* ``check_observation`` and ``check_break_glass`` decide whether a record is
  authentic and in scope. A record that is not is refused outright; an
  authentic record outside its time bounds is kept, quarantined.
* ``time_bounds_problem`` applies
  ``recorded_at - max_backlog <= changed <= observed_at + skew <= recorded_at + skew``.
* ``PolicyHistory`` replays the signed registry of policy activations, so
  the policies active at any time since the history started are known.
* ``judgement_from`` assembles the NA's verdict on one change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Collection, Iterable, Literal, Sequence

from ..crypto import sign_model, verify_model_signature
from ..models.boundary_policy import PolicyBinding
from ..models.out_of_band import (
    BreakGlassRecord,
    JudgementRecord,
    ObservationRecord,
    QuarantineRecord,
    RegistryRecord,
)
from .context.engine import PolicyVerdict
from .evidence_store import MAX_METADATA_BYTES, EvidenceCheck, ExecutorKey, _secret_material
from genesis_mesh.crypto.signing import SigningKeyLike

#: Codes a refused observation or break-glass record is answered with
#: (``422``, ``409`` for a conflict). An authentic record outside its time
#: bounds is not refused but quarantined (``observation_outside_time_bounds``,
#: ``break_glass_outside_time_bounds``).
OutOfBandRejectionCode = Literal[
    "observation_malformed",
    "observation_invalid_signature",
    "observation_unknown_key",
    "observation_key_retired",
    "observation_out_of_scope",
    "observation_secret_material",
    "observation_conflict",
    "break_glass_malformed",
    "break_glass_invalid_signature",
    "break_glass_unknown_key",
    "break_glass_key_retired",
    "break_glass_out_of_scope",
    "break_glass_secret_material",
    "break_glass_conflict",
]

#: Refusals of an authentic execution record that no later attempt can
#: overcome: the SDKs' permanent refusals. The record is then kept as a
#: quarantine entry, since the action it describes already happened. Left
#: out: chain gaps and an unknown decision (the SDKs retry them). A record
#: carrying secret material is never stored, whatever it was refused for.
QUARANTINED_EXECUTION_CODES: frozenset[str] = frozenset({
    "evidence_executor_key_retired",
    "evidence_out_of_scope",
    "evidence_decision_denied",
    "evidence_decision_mismatch",
    "evidence_outside_decision_window",
    "evidence_capability_mismatch",
    "evidence_chain_mismatch",
    "resource_chain_mismatch",
    "evidence_conflict",
})

#: Refusals of an authentic observation or break-glass record (its signature
#: verifies) that are final, so the record is kept as a quarantine entry
#: (v1.3.1): the change it reports already happened. A record carrying secret
#: material is never stored.
QUARANTINED_OUT_OF_BAND_CODES: frozenset[str] = frozenset({
    "observation_key_retired",
    "observation_out_of_scope",
    "break_glass_key_retired",
    "break_glass_out_of_scope",
})


@dataclass(frozen=True)
class TimeBounds:
    """How far back a change may be reported, and the clock skew tolerated."""

    max_backlog: timedelta = timedelta(days=7)
    skew: timedelta = timedelta(minutes=5)


def time_bounds_problem(
    earliest: datetime, latest: datetime, observed_at: datetime, recorded_at: datetime, bounds: TimeBounds
) -> str | None:
    """Why a change's times fall outside the bounds, or None.

    ``recorded_at - max_backlog <= earliest``, ``latest <= observed_at + skew``
    and ``observed_at <= recorded_at + skew``: a change cannot be reported
    later than the backlog window, after it was seen, or seen in the future.
    """
    if earliest < recorded_at - bounds.max_backlog:
        return (f"changed at {earliest.isoformat()}, more than {int(bounds.max_backlog.total_seconds())}s "
                f"before it was recorded at {recorded_at.isoformat()}")
    if latest > observed_at + bounds.skew:
        return f"changed at {latest.isoformat()}, after it was observed at {observed_at.isoformat()}"
    if observed_at > recorded_at + bounds.skew:
        return f"observed at {observed_at.isoformat()}, after it was recorded at {recorded_at.isoformat()}"
    return None


def metadata_problem(values: dict[str, Any]) -> str | None:
    """Why record metadata may carry secret material, or None.

    The guard execution evidence uses since v0.59, for any set of named
    values: a size limit, no field named like a secret, no PEM block, key or
    token. A guard, not a guarantee: send identifiers, versions and times.
    """
    size = len(json.dumps(values, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"))
    if size > MAX_METADATA_BYTES:
        return f"metadata is {size} bytes, over the {MAX_METADATA_BYTES}-byte limit"
    for name, value in values.items():
        found = _secret_material(value if isinstance(value, (dict, list)) else {name: value},
                                 f"{name}." if isinstance(value, (dict, list)) else "")
        if found:
            return found
    return None


def _key_permits(key: ExecutorKey, role: str, resource_id: str, kind: str) -> tuple[str, str] | None:
    """After the signature verifies: whether the key may sign this record. Retired keys and
    records outside a key's role or scope are refused for good, so the SDKs stop retrying."""
    if key.retired:
        return f"{kind}_key_retired", "signing key is retired"
    if key.role != role:
        return f"{kind}_out_of_scope", f"signing key is an {key.role} key, not an {role} key"
    if not key.covers(resource_id):
        return f"{kind}_out_of_scope", f"signing key covers only resources starting with {key.resource_prefix!r}"
    return None


def check_observation(observation: ObservationRecord, key: ExecutorKey | None) -> EvidenceCheck:
    """Whether an observation is authentic, in its key's scope and free of secret material.

    The key's role and scope are checked only once the signature verifies, so
    a caller without the key learns nothing about it.
    """
    if observation.signature is None:
        return EvidenceCheck("observation_invalid_signature", "observation is not signed")  # type: ignore[arg-type]
    if key is None or key.executor_sovereign_id != observation.observer_sovereign_id:
        return EvidenceCheck("observation_unknown_key",  # type: ignore[arg-type]
                             f"signing key is not registered for {observation.observer_sovereign_id!r}")
    if not verify_model_signature(observation, observation.signature, key.public_key):
        return EvidenceCheck("observation_invalid_signature", "signature does not verify")  # type: ignore[arg-type]
    problem = _key_permits(key, "observer", observation.resource_id, "observation")
    if problem is not None:
        return EvidenceCheck(*problem)  # type: ignore[arg-type]
    secret = observation_secret_problem(observation)
    if secret:
        return EvidenceCheck("observation_secret_material", secret)  # type: ignore[arg-type]
    return EvidenceCheck(None, "accepted")


def observation_secret_problem(observation: ObservationRecord) -> str | None:
    """Why an observation may carry secret material, or None.

    The source's own strings pass the guard too: an actor is a pseudonym, never a credential.
    """
    return metadata_problem({k: v for k, v in {
        "metadata": observation.metadata, "actor": observation.actor,
        "source_event_id": observation.source_event_id, "version_id": observation.version_id,
    }.items() if v is not None})


def break_glass_secret_problem(record: BreakGlassRecord) -> str | None:
    """Why a break-glass record may carry secret material, or None."""
    return metadata_problem({
        "execution_parameters": record.execution_parameters,
        "request_parameters": record.request_parameters,
        "attributes": record.attributes,
        "outcome_detail": record.outcome_detail or "",
        "justification": record.justification,
    })


def check_break_glass(record: BreakGlassRecord, key: ExecutorKey | None) -> EvidenceCheck:
    """Whether a break-glass record is authentic, in its key's scope and free of secret material."""
    if record.signature is None:
        return EvidenceCheck("break_glass_invalid_signature", "record is not signed")  # type: ignore[arg-type]
    if key is None or key.executor_sovereign_id != record.executor_sovereign_id:
        return EvidenceCheck("break_glass_unknown_key",  # type: ignore[arg-type]
                             f"signing key is not registered for {record.executor_sovereign_id!r}")
    if not verify_model_signature(record, record.signature, key.public_key):
        return EvidenceCheck("break_glass_invalid_signature", "signature does not verify")  # type: ignore[arg-type]
    problem = _key_permits(key, "executor", record.resource_id, "break_glass")
    if problem is not None:
        return EvidenceCheck(*problem)  # type: ignore[arg-type]
    secret = break_glass_secret_problem(record)
    if secret:
        return EvidenceCheck("break_glass_secret_material", secret)  # type: ignore[arg-type]
    return EvidenceCheck(None, "accepted")


# ---------------------------------------------------------------------------
# Policy history (registry records)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyEvent:
    effective_at: datetime
    store_sequence: int
    event: str
    policy_id: str
    version: int
    digest: str | None
    #: v1.3.1: the registry record's id, and whether the NA recorded it late (after the upgrade
    #: backfill, from its audit log or its policy table, for a change it had not recorded).
    record_id: str | None = None
    late: bool = False


@dataclass(frozen=True)
class PolicyHistory:
    """The policy activations the store records, replayable as of any time.

    ``started_at`` is the ``policy_history_started`` record's time: before
    it the store cannot say which policies were active, and a change made
    then is judged ``indeterminate``.
    """

    started_at: datetime | None
    events: tuple[PolicyEvent, ...]

    @classmethod
    def from_records(
        cls, records: Iterable[tuple[int, RegistryRecord]], late: Collection[str] = ()
    ) -> "PolicyHistory":
        """Replay registry records; ``late`` names the records the NA recorded late (v1.3.1)."""
        started: datetime | None = None
        events: list[PolicyEvent] = []
        for seq, record in records:
            if record.event == "policy_history_started":
                started = record.effective_at if started is None else min(started, record.effective_at)
            elif record.event in ("policy_activated", "policy_deactivated") and record.policy_id is not None \
                    and record.policy_version is not None:
                events.append(PolicyEvent(record.effective_at, seq, record.event, record.policy_id,
                                          record.policy_version, record.policy_digest,
                                          record.registry_record_id, record.registry_record_id in late))
        events.sort(key=lambda e: (e.effective_at, e.store_sequence))
        return cls(started, tuple(events))

    def change_times(self, start: datetime, end: datetime) -> list[datetime]:
        """When the active policies may have changed strictly after ``start`` and up to ``end``."""
        return sorted({e.effective_at for e in self.events if start < e.effective_at <= end})

    def active_at(self, at: datetime) -> dict[str, tuple[int, str | None]] | None:
        """policy_id -> (version, digest) active at ``at``; None before the history starts."""
        if self.started_at is None or at < self.started_at:
            return None
        return self._replay(e for e in self.events if e.effective_at <= at)

    def latest(self) -> dict[str, tuple[int, str | None]]:
        """policy_id -> (version, digest) after every recorded event, whatever its time (v1.3.1)."""
        return self._replay(self.events)

    def late_after(self, at: datetime) -> list[PolicyEvent]:
        """Events recorded late that take effect after ``at`` (v1.3.1).

        A late record takes effect when the NA recorded it, not when its
        source says the change happened, so a change made before it may
        have been made under it: a judgement of that change rests on it.
        """
        return [e for e in self.events if e.late and e.effective_at > at]

    @staticmethod
    def _replay(events: Iterable[PolicyEvent]) -> dict[str, tuple[int, str | None]]:
        active: dict[str, tuple[int, str | None]] = {}
        for event in events:
            if event.event == "policy_activated":
                active[event.policy_id] = (event.version, event.digest)
            elif active.get(event.policy_id, (None, None))[0] == event.version:
                del active[event.policy_id]
        return active


#: How long after ``valid_until`` a policy is first evaluated as expired (it applies up to and at ``valid_until``).
_JUST_AFTER = timedelta(microseconds=1)


def validity_change_times(bounds: Iterable[tuple[datetime, datetime]], start: datetime, end: datetime) -> list[datetime]:
    """When a policy's own validity window changes what applies, strictly after ``start`` and up to ``end`` (v1.3.1).

    ``bounds`` are the ``(valid_from, valid_until)`` of the policies active in
    the window: a scheduled policy starts to apply at ``valid_from``, and one
    past ``valid_until`` denies as expired from just after it.
    """
    times: set[datetime] = set()
    for valid_from, valid_until in bounds:
        for at in (valid_from, valid_until + _JUST_AFTER):
            if start < at <= end:
                times.add(at)
    return sorted(times)


# ---------------------------------------------------------------------------
# Judgements
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JudgementInput:
    """What a judgement is about."""

    subject_kind: Literal["observation", "break_glass"]
    subject_id: str
    subject_digest: str
    subject_store_sequence: int
    resource_id: str
    action: str
    capability: str


def combine_window(points: list[tuple[datetime, PolicyVerdict]]) -> PolicyVerdict:
    """One verdict for a change known only within a window, from its verdict at the window's
    start and after every policy change inside it (the last point is the window's end): they
    must all agree, or the NA cannot tell which applied."""
    end = points[-1][1]
    differing = [(at, v) for at, v in points if v.verdict != end.verdict]
    if not differing:
        return end
    at, other = differing[0]
    return PolicyVerdict(
        "indeterminate",
        f"the verdict changes within the change window ({other.verdict} at {at.isoformat()}, "
        f"{end.verdict} at its end)",
        end.binding,
        end.gate_results,
    )


_STRICTNESS = {"allow": 0, "indeterminate": 1, "deny": 2}


def stricter(a: str, b: str) -> str:
    """The stricter of two verdicts: deny over indeterminate over allow."""
    return a if _STRICTNESS[a] >= _STRICTNESS[b] else b


def judgement_from(
    subject: JudgementInput,
    *,
    judged_at: datetime,
    issuer_sovereign_id: str,
    issued_by: str,
    evaluated_as_of: datetime,
    evaluated_from: datetime | None = None,
    verdict: PolicyVerdict | None = None,
    current: PolicyVerdict | None = None,
    history_reason: str | None = None,
    matched_evidence_id: str | None = None,
    matched_decision_id: str | None = None,
    possible_match_evidence_id: str | None = None,
    same_change_as: str | None = None,
    review_notes: Sequence[str] = (),
) -> JudgementRecord:
    """Assemble the NA's verdict on one change (unsigned).

    A change matched to execution evidence (``matched_evidence_id``, or
    ``same_change_as`` for a further observation of evidence already
    matched) is ``governed_by: prior_decision`` and allowed: the decision
    that evidence rests on authorized it, unless the observed change is
    denied on its own facts (``verdict``), which the decision could not see:
    then it is denied and flagged for review. Otherwise it is judged after
    the fact: ``verdict`` as of the change, ``current`` under today's
    policies, flagged when they differ. ``history_reason`` (no verdict)
    makes it ``indeterminate``.

    ``review_notes`` (v1.3.1) are reasons the verdict on the change's own
    facts needs a person to look at it (history the NA recorded late, a
    break-glass executor the NA cannot tie to its attestation): each is
    added to the reason and flags the judgement, unless a decision governs it.
    """
    notes = "; ".join(review_notes)
    base: dict[str, Any] = dict(
        subject_kind=subject.subject_kind,
        subject_id=subject.subject_id,
        subject_digest=subject.subject_digest,
        subject_store_sequence=subject.subject_store_sequence,
        resource_id=subject.resource_id,
        action=subject.action,
        capability=subject.capability,
        evaluated_as_of=evaluated_as_of,
        evaluated_from=evaluated_from if evaluated_from != evaluated_as_of else None,
        judged_at=judged_at,
        issuer_sovereign_id=issuer_sovereign_id,
        issued_by=issued_by,
    )
    if matched_evidence_id is not None or same_change_as is not None:
        matched = ("matched recorded execution evidence" if same_change_as is None
                   else f"the same change as recorded execution evidence {same_change_as}, already matched")
        if verdict is not None and verdict.verdict == "deny":
            denied = f"{matched}, but the observed change is denied on its own facts: {verdict.reason}"
            return JudgementRecord(
                **base, governed_by="prior_decision", verdict="deny",
                reason=(denied + (f"; {notes}" if notes else ""))[:1024],
                policy_binding=verdict.binding, gate_results=list(verdict.gate_results), flagged_for_review=True,
                matched_evidence_id=matched_evidence_id, matched_decision_id=matched_decision_id,
            )
        return JudgementRecord(
            **base, governed_by="prior_decision", verdict="allow", reason=matched,
            matched_evidence_id=matched_evidence_id, matched_decision_id=matched_decision_id,
        )
    binding: PolicyBinding | None = verdict.binding if verdict is not None else None
    outcome = verdict.verdict if verdict is not None else "indeterminate"
    reason = verdict.reason if verdict is not None else history_reason
    if notes:
        reason = (f"{reason}; {notes}" if reason else notes)[:1024]
    current_verdict = current.verdict if current is not None else None
    flagged = bool(notes) or (current_verdict is not None and current_verdict != outcome)
    return JudgementRecord(
        **base,
        governed_by="after_the_fact",
        verdict=outcome,  # type: ignore[arg-type]
        reason=reason,
        policy_binding=binding,
        gate_results=list(verdict.gate_results) if verdict is not None else [],
        current_verdict=current_verdict,  # type: ignore[arg-type]
        current_policy_set_digest=current.binding.policy_set_digest if current is not None else None,
        flagged_for_review=True if flagged else None,
        possible_match_evidence_id=possible_match_evidence_id,
    )


# ---------------------------------------------------------------------------
# Signing and verification
# ---------------------------------------------------------------------------

NaSigned = JudgementRecord | QuarantineRecord | RegistryRecord


def sign_na_record(record: NaSigned, signing_key: SigningKeyLike, key_id: str) -> NaSigned:
    """Return a judgement, quarantine or registry record signed by the NA."""
    return record.model_copy(update={"signature": sign_model(record, signing_key, key_id)})


def verify_na_record(record: NaSigned, na_public_keys: Iterable[str]) -> bool:
    sig = record.signature
    return sig is not None and any(verify_model_signature(record, sig, k) for k in na_public_keys)


def entry_index(kind: str, record: Any) -> dict[str, Any]:
    """Search fields of a Stage 2 entry's envelope."""
    if isinstance(record, ObservationRecord):
        return {"record_id": record.observation_id, "resource_id": record.resource_id,
                "resource_action": record.action, "capability": record.capability,
                "executor_sovereign_id": record.observer_sovereign_id}
    if isinstance(record, BreakGlassRecord):
        return {"record_id": record.break_glass_id, "resource_id": record.resource_id,
                "resource_action": record.resource_action, "capability": record.capability,
                "executor_sovereign_id": record.executor_sovereign_id, "attestation_id": record.attestation_id,
                "outcome": record.outcome}
    if isinstance(record, JudgementRecord):
        return {"record_id": record.judgement_id, "subject_id": record.subject_id,
                "resource_id": record.resource_id, "resource_action": record.action,
                "capability": record.capability, "outcome": record.verdict,
                "matched_evidence_id": record.matched_evidence_id}
    if isinstance(record, QuarantineRecord):
        return {"record_id": record.quarantine_id, "resource_id": record.resource_id,
                "outcome": record.rejection_code}
    if isinstance(record, RegistryRecord):
        return {"record_id": record.registry_record_id, "outcome": record.event}
    raise TypeError(f"not a Stage 2 record: {kind}")
