"""Changes made outside the controlled path (v1.3.0, Stage 2): the NA side.

Routes in ``routes/out_of_band.py`` parse HTTP and call this service. It
admits observations and break-glass records, quarantines authentic records
it refuses after their action happened, judges each change once, and keeps
the registry of NA state that judgements rest on (policy activations,
executor and observer keys, operator key holders) in the evidence store,
under the anchors.

Every write appends store entries through the evidence store's write lock;
what an append depends on (the next observation position, whether a record
is already judged or a piece of evidence already matched) is read under the
same lock, and unique indexes (migration 015) refuse a duplicate that slips
past.

The registry's trust model (v1.3.1): a policy activation or deactivation
and its registry record commit in one transaction. The audit log, which
nothing signs, is read once, when a store first runs with the records on
(the upgrade backfill, at the times it records). After that a change the
registry lacks (made while the records were off, or by an instance of an
older release) is recorded when the NA finds it, never before what the
store already holds, and judgements of changes made before it are flagged
for review.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable, Literal, NoReturn, Sequence

from pydantic import ValidationError as PydanticValidationError

from ...models.boundary_policy import BoundaryPolicy
from ...models.context import ContextRecord
from ...models.evidence_store import EvidenceStoreEntry, canonical_json, payload_digest
from ...models.execution import ExecutionEvidence
from ...models.out_of_band import (
    BreakGlassRecord,
    JudgementRecord,
    ObservationRecord,
    QuarantineRecord,
    RegistryRecord,
)
from ...trust.context.attestation_basis import AttestationBasis, assess_attestation_basis
from ...trust.context.engine import PolicyVerdict, evaluate_policies_as_of
from ...trust.evidence_store import EvidenceCheck, ExecutorKey, build_entry, check_metadata_only
from ...trust.out_of_band import (
    QUARANTINED_EXECUTION_CODES,
    QUARANTINED_OUT_OF_BAND_CODES,
    JudgementInput,
    PolicyHistory,
    TimeBounds,
    break_glass_secret_problem,
    check_break_glass,
    check_observation,
    combine_window,
    entry_index,
    judgement_from,
    observation_secret_problem,
    sign_na_record,
    stricter,
    time_bounds_problem,
    validity_change_times,
)
from ..errors import BadRequestError, ConflictError, NotFoundError, ServiceUnavailableError, ValidationError

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService

logger = logging.getLogger(__name__)

SubjectKind = Literal["observation", "break_glass"]

#: Most observations one batch may carry.
OBSERVATION_BATCH_LIMIT = 100

#: Most changes ``resource_changes`` returns (the oldest); longer histories report ``truncated``.
CHANGES_LIMIT = 10_000

#: Most stored records of one resource version a match looks through (v1.3.1).
MATCH_CANDIDATES = 500

#: Registry records the NA wrote late (after the upgrade backfill, for a change it had not
#: recorded) carry dedupe keys with this prefix (v1.3.1). Judgements resting on them are flagged.
LATE_PREFIX = "registry:late:"

#: Unjudged records judged at start, and per sweep at most every SWEEP_INTERVAL_SECONDS on
#: admission (v1.3.1): a judgement that failed at admission is retried without an operator.
SWEEP_START_LIMIT = 100
SWEEP_BATCH = 10
SWEEP_INTERVAL_SECONDS = 300

#: How often a store whose policy history has not started tries the backfill again (v1.3.1).
BACKFILL_RETRY_SECONDS = 60


class _AlreadyApproved(Exception):
    """The holder change was approved by another request first."""


class _AlreadyJudged(Exception):
    """Another request judged the record first; raised inside the write transaction."""


class _IdTaken(Exception):
    """A record of the other kind uses this id (v1.3.1); raised inside the write transaction."""


def observation_dedupe_key(observation: ObservationRecord) -> str:
    """One observation per (observer, source, source event)."""
    parts = "\x00".join((observation.observer_sovereign_id, observation.source, observation.source_event_id))
    return "o:" + hashlib.sha256(parts.encode("utf-8")).hexdigest()


def _exact_form_problem(raw: dict[str, Any], record: Any) -> str | None:
    """Why a submitted Stage 2 record differs from its exact serialized form, or None."""
    if canonical_json(raw) == canonical_json(record.to_wire()):
        return None
    expected = record.to_wire()
    extra = sorted(set(raw) - set(expected))
    if extra:
        return "unexpected or null field " + ", ".join(repr(k) for k in extra)
    missing = sorted(set(expected) - set(raw))
    if missing:
        return "missing field " + ", ".join(repr(k) for k in missing)
    for key in sorted(expected):
        if canonical_json(raw[key]) != canonical_json(expected[key]):
            return f"field {key!r} is not in its serialized form"
    return "record differs from its serialized form"


def _version_id(parameters: dict[str, Any]) -> str | None:
    value = parameters.get("version_id")
    return value if isinstance(value, str) and value else None


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass
class _Judging:
    """What one judgement reads more than once (v1.3.1): the policy history, built once, and the
    stored policies and attestations it evaluates against at each point."""

    history: PolicyHistory
    policies: dict[tuple[str, int], BoundaryPolicy | None] = field(default_factory=dict)
    attestations: dict[str, Any] = field(default_factory=dict)
    revoked_since: dict[str, datetime | None] = field(default_factory=dict)


class OutOfBandService:
    """NA application logic for observations, break-glass, judgements, quarantine and registries."""

    def __init__(self, service: "NetworkAuthorityService") -> None:
        self._na = service
        # v1.3.1: what the registry checks at start found, for /admin/evidence/status.
        self._start_problems: list[str] = []
        self._last_sweep = time.monotonic()
        self._next_backfill = 0.0

    # -- shared -------------------------------------------------------------

    @property
    def _store(self) -> Any:
        return self._na.evidence_store_service

    @property
    def enabled(self) -> bool:
        """Stage 2 records are kept: the store is on and ``EVIDENCE_OUT_OF_BAND=on``."""
        return self._store.enabled and self._na.evidence_out_of_band == "on"

    def require_enabled(self) -> None:
        self._store.require_enabled()
        if not self.enabled:
            raise NotFoundError("Changes outside the controlled path are not recorded (EVIDENCE_OUT_OF_BAND=off)",
                                code="out_of_band_disabled")

    @property
    def bounds(self) -> TimeBounds:
        return self._na.observation_time_bounds

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _issuer(self) -> dict[str, Any]:
        return {"issuer_sovereign_id": self._na.genesis_block.network_name, "issued_by": self._na.key_id}

    def _sign(self, record: Any) -> Any:
        return sign_na_record(record, self._na.signer, self._na.key_id)

    def _pending(
        self, kind: str, record: Any, *, now: datetime,
        extra_index: dict[str, Any] | None = None, lookup: dict[str, Any] | None = None,
    ) -> tuple[Callable[[int, str | None], EvidenceStoreEntry], dict[str, Any], dict[str, Any]]:
        payload = record.to_wire()
        index = {**entry_index(kind, record), **(extra_index or {})}

        def build(seq: int, prev: str | None) -> EvidenceStoreEntry:
            return build_entry(store_sequence=seq, entry_kind=kind, recorded_at=now, payload=payload,
                               prev_entry_digest=prev, index=index)

        return build, payload, {k: v for k, v in (lookup or {}).items() if v is not None}

    def _append(self, pending: Sequence[Any], *, anchor: bool = True) -> list[EvidenceStoreEntry]:
        try:
            entries = self._na.db.append_evidence_entries(pending)
        except self._na.db.integrity_errors:
            raise
        except self._na.db.database_errors as exc:
            logger.warning("evidence store write failed: %s", exc)
            raise ServiceUnavailableError("The record could not be stored", code="evidence_store_unavailable") from exc
        if anchor:
            self._store.maybe_anchor()
        return entries

    @staticmethod
    def _body(stored: dict[str, Any], **extra: Any) -> dict[str, Any]:
        entry: EvidenceStoreEntry = stored["entry"]
        return {"entry": entry.model_dump(mode="json"), "entry_digest": stored["entry_digest"],
                "payload": stored["payload"], **extra}

    def _key(self, key_id: str | None) -> ExecutorKey | None:
        row = self._na.db.get_executor_key(key_id) if key_id else None
        return self._store.key_from_row(row) if row is not None else None

    # -- quarantine -----------------------------------------------------------

    def quarantine(
        self, kind: Literal["execution", "observation", "break_glass"], raw: dict[str, Any],
        code: str, detail: str, resource_id: str | None,
    ) -> dict[str, Any]:
        """Keep an authentic record the NA refused after its action happened; idempotent per record."""
        digest = payload_digest(raw)
        dedupe = "q:" + digest
        existing = self._na.db.get_entry_by_dedupe_key(dedupe)
        if existing is not None:
            return existing
        now = self._now()
        record = self._sign(QuarantineRecord(
            record_kind=kind, record=raw, record_digest=digest, rejection_code=code, detail=detail[:1024],
            resource_id=resource_id, quarantined_at=now, **self._issuer(),
        ))
        try:
            entries = self._append([self._pending("quarantine", record, now=now, lookup={"dedupe_key": dedupe})])
        except self._na.db.integrity_errors:
            stored = self._na.db.get_entry_by_dedupe_key(dedupe)
            if stored is None:
                raise
            return stored
        self._na.db.add_audit_event("record_quarantined", {
            "record_kind": kind, "record_digest": digest, "rejection_code": code,
            "quarantine_id": record.quarantine_id, "store_sequence": entries[0].store_sequence,
        })
        return {"entry": entries[0], "entry_digest": entries[0].digest(), "payload": record.to_wire()}

    def quarantine_execution(self, code: str, detail: str, evidence: ExecutionEvidence, raw: dict[str, Any]) -> str | None:
        """Quarantine a refused execution record when it is authentic and the refusal is final.

        Returns the quarantine id, or None when the record is not quarantined.
        """
        if not self.enabled or code not in QUARANTINED_EXECUTION_CODES or evidence.signature is None:
            return None
        key = self._key(evidence.signature.key_id)
        from ...crypto import verify_model_signature

        if key is None or key.executor_sovereign_id != evidence.executor_sovereign_id \
                or not verify_model_signature(evidence, evidence.signature, key.public_key):
            return None
        # A quarantine entry keeps the record as received: one carrying secret
        # material is refused without being stored, whatever it was refused for.
        if check_metadata_only(evidence) is not None:
            return None
        try:
            stored = self.quarantine("execution", raw, code, detail, evidence.resource_id)
        except Exception as exc:  # noqa: BLE001 -- the refusal itself must still be returned
            logger.warning("could not quarantine refused execution record: %s", exc)
            return None
        return str(stored["payload"]["quarantine_id"])

    def _quarantine_refused(
        self, kind: Literal["observation", "break_glass"], raw: dict[str, Any],
        record: ObservationRecord | BreakGlassRecord, check: EvidenceCheck,
    ) -> str | None:
        """Quarantine an observation or break-glass record refused for good after its signature
        verified (v1.3.1: a retired key, or outside its key's role or prefix). Never one that may
        carry secret material. Returns the quarantine id, or None."""
        if check.code not in QUARANTINED_OUT_OF_BAND_CODES:
            return None
        secret = observation_secret_problem(record) if isinstance(record, ObservationRecord) \
            else break_glass_secret_problem(record)
        if secret is not None:
            return None
        assert check.code is not None
        try:
            stored = self.quarantine(kind, raw, check.code, check.detail, record.resource_id)
        except Exception as exc:  # noqa: BLE001 -- the refusal itself must still be returned
            logger.warning("could not quarantine refused %s record: %s", kind, exc)
            return None
        return str(stored["payload"]["quarantine_id"])

    # -- refusals -------------------------------------------------------------

    def _refuse(self, code: str, detail: str, record: Any, digest: str, kind: str,
                quarantine_id: str | None = None) -> NoReturn:
        self._na.db.add_evidence_rejection(
            code, submitted_digest=digest, evidence_id=None, decision_id=None,
            resource_id=getattr(record, "resource_id", None),
            executor_sovereign_id=getattr(record, "observer_sovereign_id", None)
            or getattr(record, "executor_sovereign_id", None),
        )
        self._na.db.add_audit_event(f"{kind}_rejected", {
            "code": code, "submitted_digest": digest,
            "record_id": getattr(record, "observation_id", None) or getattr(record, "break_glass_id", None),
            "resource_id": getattr(record, "resource_id", None),
        })
        error = ConflictError if code.endswith("_conflict") else ValidationError
        raise error(detail, code=code, details={"quarantine_id": quarantine_id} if quarantine_id else None)

    # -- observations -----------------------------------------------------------

    def submit_observation(self, raw: Any) -> tuple[dict[str, Any], int]:
        """Admit one signed observation. Returns (body, HTTP status)."""
        self.require_enabled()
        if not isinstance(raw, dict):
            raise BadRequestError("observation must be an object", code="invalid_observation")
        digest = payload_digest(raw)
        try:
            observation = ObservationRecord.model_validate(raw)
        except PydanticValidationError as exc:
            self._refuse("observation_malformed", f"observation does not match the ObservationRecord model: "
                         f"{exc.errors()[0].get('msg', '')}", None, digest, "observation")
        difference = _exact_form_problem(raw, observation)
        if difference is not None:
            self._refuse("observation_malformed", f"observation is not in its exact serialized form: {difference}",
                         observation, digest, "observation")
        check = check_observation(observation, self._key(observation.signature.key_id if observation.signature else None))
        if not check.accepted:
            assert check.code is not None
            self._refuse(check.code, check.detail, observation, digest, "observation",
                         self._quarantine_refused("observation", raw, observation, check))

        dedupe = observation_dedupe_key(observation)
        duplicate = self._duplicate(dedupe, digest, "observation")
        if duplicate is not None:
            return duplicate, 200
        now = self._now()
        earliest, latest = observation.change_window
        problem = time_bounds_problem(earliest, latest, observation.observed_at, now, self.bounds)
        if problem is not None:
            stored = self.quarantine("observation", raw, "observation_outside_time_bounds", problem,
                                     observation.resource_id)
            return self._body(stored, status="quarantined"), 201

        def make(db: Any) -> list[Any]:
            # v1.3.1: a judgement names its subject by id, so an observation and a break-glass
            # record never share one.
            if db.get_entry_by_record("break_glass", observation.observation_id) is not None:
                raise _IdTaken()
            seq = db.last_observation_sequence(observation.resource_id) + 1
            return [self._pending("observation", observation, now=now,
                                  extra_index={"observation_sequence": seq},
                                  lookup={"dedupe_key": dedupe, "version_id": observation.version_id})]

        try:
            entries = self._na.db.append_evidence_entries_with(make)
        except _IdTaken:
            raise ConflictError("a break-glass record with this observation_id is stored",
                                code="observation_conflict") from None
        except self._na.db.integrity_errors:
            duplicate = self._duplicate(dedupe, digest, "observation")
            if duplicate is not None:
                return duplicate, 200
            if self._na.db.get_entry_by_record("observation", observation.observation_id) is not None:
                raise ConflictError("another observation with this observation_id is stored",
                                    code="observation_conflict")
            raise ConflictError("the observation's position was taken; retry", code="observation_conflict")
        except self._na.db.database_errors as exc:
            raise ServiceUnavailableError("The observation could not be stored",
                                          code="evidence_store_unavailable") from exc
        stored = {"entry": entries[0], "entry_digest": entries[0].digest(), "payload": observation.to_wire()}
        self._na.db.add_audit_event("observation_recorded", {
            "observation_id": observation.observation_id, "resource_id": observation.resource_id,
            "store_sequence": entries[0].store_sequence,
        })
        self._store.maybe_anchor()
        body = self._body(stored, status="recorded")
        if self._na.judge_on_admission:
            body["judgement"] = self._judge_quietly("observation", stored)
            self._maybe_sweep()
        return body, 201

    def submit_observations(self, raw: Any) -> list[dict[str, Any]]:
        """Admit a backlog of observations, in order of their change times; one result per observation."""
        self.require_enabled()
        if not isinstance(raw, list) or not raw:
            raise BadRequestError("observations must be a non-empty list", code="invalid_observation")
        if len(raw) > OBSERVATION_BATCH_LIMIT:
            raise BadRequestError(f"at most {OBSERVATION_BATCH_LIMIT} observations per batch",
                                  code="invalid_observation")

        def order(item: Any) -> tuple[int, datetime]:
            if isinstance(item, dict):
                at = item.get("changed_at") or item.get("changed_not_before")
                if isinstance(at, str):
                    parsed = _parse_time(at)
                    if parsed is not None:
                        return 0, parsed
            return 1, datetime.min.replace(tzinfo=timezone.utc)

        results: list[dict[str, Any]] = []
        for index, item in sorted(enumerate(raw), key=lambda pair: order(pair[1])):
            try:
                body, _ = self.submit_observation(item)
                results.append({"index": index, **body})
            except (BadRequestError, ValidationError, ConflictError) as exc:
                error: dict[str, Any] = {"code": exc.code, "message": exc.message}
                if exc.details:
                    error["details"] = exc.details
                results.append({"index": index, "status": "refused", "error": error})
        return sorted(results, key=lambda r: r["index"])

    def _duplicate(self, dedupe: str, digest: str, kind: str) -> dict[str, Any] | None:
        existing = self._na.db.get_entry_by_dedupe_key(dedupe)
        if existing is None:
            return None
        if payload_digest(existing["payload"]) != digest:
            raise ConflictError(f"a different {kind.replace('_', '-')} record from this source event is stored",
                                code=f"{kind}_conflict")
        return self._body(existing, status="duplicate")

    # -- break-glass --------------------------------------------------------------

    def submit_break_glass(self, raw: Any) -> tuple[dict[str, Any], int]:
        """Admit one signed break-glass record. Returns (body, HTTP status)."""
        self.require_enabled()
        if not isinstance(raw, dict):
            raise BadRequestError("record must be an object", code="invalid_break_glass")
        digest = payload_digest(raw)
        try:
            record = BreakGlassRecord.model_validate(raw)
        except PydanticValidationError as exc:
            self._refuse("break_glass_malformed", f"record does not match the BreakGlassRecord model: "
                         f"{exc.errors()[0].get('msg', '')}", None, digest, "break_glass")
        difference = _exact_form_problem(raw, record)
        if difference is not None:
            self._refuse("break_glass_malformed", f"record is not in its exact serialized form: {difference}",
                         record, digest, "break_glass")
        check = check_break_glass(record, self._key(record.signature.key_id if record.signature else None))
        if not check.accepted:
            assert check.code is not None
            self._refuse(check.code, check.detail, record, digest, "break_glass",
                         self._quarantine_refused("break_glass", raw, record, check))

        dedupe = "b:" + record.break_glass_id
        duplicate = self._duplicate(dedupe, digest, "break_glass")
        if duplicate is not None:
            return duplicate, 200
        now = self._now()
        problem = time_bounds_problem(record.executed_at, record.executed_at, now, now, self.bounds)
        if problem is not None:
            stored = self.quarantine("break_glass", raw, "break_glass_outside_time_bounds", problem, record.resource_id)
            return self._body(stored, status="quarantined"), 201

        def make(db: Any) -> list[Any]:
            if db.get_entry_by_record("observation", record.break_glass_id) is not None:
                raise _IdTaken()
            return [self._pending("break_glass", record, now=now,
                                  lookup={"dedupe_key": dedupe, "version_id": _version_id(record.execution_parameters)})]

        try:
            entries = self._na.db.append_evidence_entries_with(make)
        except _IdTaken:
            raise ConflictError("an observation with this break_glass_id is stored",
                                code="break_glass_conflict") from None
        except self._na.db.integrity_errors:
            duplicate = self._duplicate(dedupe, digest, "break_glass")
            if duplicate is not None:
                return duplicate, 200
            raise ConflictError("a break-glass record with this id is stored", code="break_glass_conflict")
        except self._na.db.database_errors as exc:
            logger.warning("evidence store write failed: %s", exc)
            raise ServiceUnavailableError("The record could not be stored", code="evidence_store_unavailable") from exc
        self._store.maybe_anchor()
        stored = {"entry": entries[0], "entry_digest": entries[0].digest(), "payload": record.to_wire()}
        self._na.db.add_audit_event("break_glass_recorded", {
            "break_glass_id": record.break_glass_id, "resource_id": record.resource_id,
            "executor_sovereign_id": record.executor_sovereign_id, "store_sequence": entries[0].store_sequence,
        })
        body = self._body(stored, status="recorded")
        if self._na.judge_on_admission:
            body["judgement"] = self._judge_quietly("break_glass", stored)
            self._maybe_sweep()
        return body, 201

    # -- judgements -----------------------------------------------------------------

    def judge(self, kind: SubjectKind, record_id: str) -> tuple[dict[str, Any], int]:
        """Judge a stored observation or break-glass record once; idempotent."""
        self.require_enabled()
        stored = self._na.db.get_entry_by_record(kind, record_id)
        if stored is None:
            raise NotFoundError(f"no {kind.replace('_', '-')} record {record_id!r} is stored",
                                code="judgement_subject_not_found")
        existing = self._na.db.get_judgement_for(kind, record_id)
        if existing is not None:
            return self._body(existing, status="existing"), 200
        return self._judge(kind, stored), 201

    def _judge_quietly(self, kind: SubjectKind, stored: dict[str, Any]) -> dict[str, Any] | None:
        """Judge at admission; a failure leaves the record to the sweep or the judge routes."""
        try:
            return self._judge(kind, stored)
        except Exception as exc:  # noqa: BLE001 -- admission already succeeded
            logger.warning("judging %s %s failed: %s", kind, stored["entry"].record_id, exc)
            return None

    def _judge(self, kind: SubjectKind, stored: dict[str, Any]) -> dict[str, Any]:
        entry: EvidenceStoreEntry = stored["entry"]
        record: ObservationRecord | BreakGlassRecord = (
            ObservationRecord.model_validate(stored["payload"]) if kind == "observation"
            else BreakGlassRecord.model_validate(stored["payload"])
        )
        record_id = record.observation_id if isinstance(record, ObservationRecord) else record.break_glass_id
        other_kind = "break_glass" if kind == "observation" else "observation"
        if self._na.db.get_judgement_for(other_kind, record_id) is not None:
            # A 1.3.0 store may hold an observation and a break-glass record with one id; the
            # judgement of the other holds the id's only judgement position.
            raise ConflictError(f"the {other_kind.replace('_', '-')} record with this id is judged; "
                                f"this record cannot be judged as well", code="judgement_conflict")
        action = record.action if isinstance(record, ObservationRecord) else record.resource_action
        subject = JudgementInput(
            subject_kind=kind, subject_id=record_id, subject_digest=entry.payload_digest,
            subject_store_sequence=entry.store_sequence, resource_id=record.resource_id,
            action=action, capability=record.capability,
        )
        if isinstance(record, ObservationRecord):
            earliest, latest = record.change_window
        else:
            earliest = latest = record.executed_at

        # An observation of a break-glass change shares its verdict: judge that record first.
        if isinstance(record, ObservationRecord):
            related = self._match_candidate(record, action, earliest, latest) \
                or self._same_change(record, action, earliest, latest)
            if related is not None and related["entry"].entry_kind == "break_glass" \
                    and self._na.db.get_judgement_for("break_glass", related["entry"].record_id) is None:
                self._judge("break_glass", related)

        ctx = self._judging()
        now = self._now()
        issuer = self._issuer()
        verdict, history_reason = self._evaluate(record, latest, ctx)
        if verdict is not None and earliest != latest:
            # Known only within a window: the verdict at its start and after every
            # policy change inside it must agree; before the history starts it cannot.
            points: list[tuple[datetime, PolicyVerdict]] = []
            for at in [earliest, *self._change_points(ctx, earliest, latest)]:
                if at == latest:
                    continue
                other, why = self._evaluate(record, at, ctx)
                if other is None:
                    verdict, history_reason = None, why
                    break
                points.append((at, other))
            if verdict is not None:
                verdict = combine_window([*points, (latest, verdict)])
        current, _ = self._evaluate(record, now, ctx, current=True)
        notes = self._review_notes(record, entry, ctx, earliest, verdict)
        hint = self._hint(record, action, earliest, latest) if isinstance(record, ObservationRecord) \
            and record.version_id is None else None
        after_the_fact = self._sign(judgement_from(
            subject, judged_at=now, evaluated_as_of=latest, evaluated_from=earliest,
            verdict=verdict, current=current, history_reason=history_reason,
            possible_match_evidence_id=hint, review_notes=notes, **issuer,
        ))

        def make(db: Any) -> list[Any]:
            if db.get_judgement_for(kind, record_id) is not None:
                raise _AlreadyJudged()
            judgement = after_the_fact
            if isinstance(record, ObservationRecord) and record.version_id is not None:
                matched = self._match_candidate(record, action, earliest, latest, db=db)
                if matched is not None:
                    judgement = self._matched_judgement(subject, matched, latest, earliest, now, db, verdict, notes)
                else:
                    # A further observation of a recorded change (another observer, the same
                    # version, at the same time): the same change, not a new one.
                    seen = self._same_change(record, action, earliest, latest, db=db)
                    if seen is not None and seen["entry"].entry_kind == "execution":
                        prior: EvidenceStoreEntry = seen["entry"]
                        judgement = self._sign(judgement_from(
                            subject, judged_at=now, evaluated_as_of=latest, evaluated_from=earliest,
                            verdict=verdict, same_change_as=prior.evidence_id,
                            matched_decision_id=prior.decision_id, review_notes=notes, **issuer,
                        ))
                    elif seen is not None:
                        judgement = self._matched_judgement(subject, seen, latest, earliest, now, db, verdict,
                                                            notes, same_change=True)
            return [self._pending("judgement", judgement, now=now)]

        try:
            entries = self._na.db.append_evidence_entries_with(make)
        except _AlreadyJudged:
            existing = self._na.db.get_judgement_for(kind, record_id)
            assert existing is not None
            return self._body(existing, status="existing")
        except self._na.db.integrity_errors:
            existing = self._na.db.get_judgement_for(kind, record_id)
            if existing is not None:
                return self._body(existing, status="existing")
            raise ConflictError("the matched evidence was claimed by another judgement; retry",
                                code="judgement_conflict")
        except self._na.db.database_errors as exc:
            raise ServiceUnavailableError("The judgement could not be stored",
                                          code="evidence_store_unavailable") from exc
        stored_judgement = self._na.db.get_judgement_for(kind, record_id)
        assert stored_judgement is not None
        payload = stored_judgement["payload"]
        self._na.db.add_audit_event("change_judged", {
            "subject_kind": kind, "subject_id": record_id, "verdict": payload["verdict"],
            "governed_by": payload["governed_by"], "flagged_for_review": bool(payload.get("flagged_for_review")),
            "store_sequence": entries[0].store_sequence,
        })
        self._store.maybe_anchor()
        return self._body(stored_judgement, status="judged")

    def _review_notes(
        self, record: ObservationRecord | BreakGlassRecord, entry: EvidenceStoreEntry, ctx: _Judging,
        earliest: datetime, verdict: PolicyVerdict | None,
    ) -> list[str]:
        """Why a verdict on a change's own facts needs a person to look at it (v1.3.1)."""
        notes: list[str] = []
        late = ctx.history.late_after(earliest)
        if late:
            first = late[0]
            notes.append(
                f"rests on policy history the NA recorded after the change: {first.policy_id} v{first.version} "
                f"{'activated' if first.event == 'policy_activated' else 'deactivated'} as of "
                f"{first.effective_at.isoformat()}, found later than it happened"
                + (f" ({len(late)} such records)" if len(late) > 1 else "")
            )
        if isinstance(record, BreakGlassRecord) and verdict is not None and verdict.verdict == "allow" \
                and record.attestation_id is not None:
            row = self._attestation_row(ctx, record.attestation_id)
            attestation = row["attestation"] if row else None
            subject = attestation.subject_id if attestation is not None else None
            if subject != record.executor_sovereign_id and not self._na.db.executed_for_attestation(
                    record.executor_sovereign_id, record.attestation_id, entry.store_sequence):
                notes.append(
                    f"judged as attestation {record.attestation_id} (subject {subject}) would have been; nothing "
                    f"the NA holds ties executor {record.executor_sovereign_id} to it (no execution evidence of "
                    f"its under a decision for that attestation)"
                )
        return notes

    def _executed_within(self, stored: dict[str, Any], earliest: datetime, latest: datetime) -> bool:
        """Whether a stored execution or break-glass record was made within a change's window,
        give or take the clock skew (v1.3.1): a version alone does not make two records one change."""
        at = _parse_time(stored["payload"].get("executed_at"))
        skew = self.bounds.skew
        return at is not None and earliest - skew <= at <= latest + skew

    def _candidates_since(self, earliest: datetime) -> datetime:
        # Execution evidence is stored within its decision's validity of being made, and a
        # break-glass record within the backlog: nothing stored earlier was made in the window.
        return earliest - self.bounds.max_backlog - self.bounds.skew

    def _match_candidate(
        self, record: ObservationRecord, action: str, earliest: datetime, latest: datetime, db: Any = None,
    ) -> dict[str, Any] | None:
        """The oldest unmatched execution or break-glass record of this change: same resource,
        action, version and capability (a decision for another capability governs nothing here),
        made within the change's window (v1.3.1)."""
        if record.version_id is None:
            return None
        db = db or self._na.db
        for stored in db.unmatched_executions(record.resource_id, action, record.version_id, record.capability,
                                              limit=MATCH_CANDIDATES, recorded_since=self._candidates_since(earliest)):
            if self._executed_within(stored, earliest, latest):
                return stored
        return None

    def _same_change(
        self, record: ObservationRecord, action: str, earliest: datetime, latest: datetime, db: Any = None,
    ) -> dict[str, Any] | None:
        """An execution or break-glass record of this change another observation already matched."""
        if record.version_id is None:
            return None
        db = db or self._na.db
        for stored in db.matched_executions(record.resource_id, action, record.version_id, record.capability,
                                            limit=MATCH_CANDIDATES, recorded_since=self._candidates_since(earliest)):
            if self._executed_within(stored, earliest, latest):
                return stored
        return None

    def _matched_judgement(
        self, subject: JudgementInput, matched: dict[str, Any], latest: datetime, earliest: datetime,
        now: datetime, db: Any, own: PolicyVerdict | None, notes: Sequence[str] = (), *, same_change: bool = False,
    ) -> JudgementRecord:
        """The judgement of an observation matched to recorded evidence. ``own`` is the verdict on the
        observer's own facts, which the matched record cannot vouch for: a deny always stands.
        ``same_change`` (v1.3.1): another observation already matched the record."""
        entry: EvidenceStoreEntry = matched["entry"]
        issuer = self._issuer()
        if entry.entry_kind == "execution":
            return self._sign(judgement_from(
                subject, judged_at=now, evaluated_as_of=latest, evaluated_from=earliest, verdict=own,
                matched_evidence_id=entry.evidence_id, matched_decision_id=entry.decision_id,
                review_notes=notes, **issuer,
            ))
        # A break-glass record of the same change is the controller's own account: the
        # observation takes the stricter of its verdict and the observer's facts.
        assert entry.record_id is not None
        prior = db.get_judgement_for("break_glass", entry.record_id)
        prior_record = JudgementRecord.model_validate(prior["payload"]) if prior is not None else None
        theirs = prior_record.verdict if prior_record is not None else "indeterminate"
        mine = own.verdict if own is not None else "indeterminate"
        verdict = stricter(theirs, mine)
        reason = (f"the same change as break-glass record {entry.record_id}, already matched ({theirs})"
                  if same_change else f"matched break-glass record {entry.record_id} ({theirs})")
        if mine != theirs:
            reason += f"; on the observer's facts {mine}" + (f": {own.reason}" if own is not None and own.reason else "")
        elif prior_record is not None and prior_record.reason:
            reason += f": {prior_record.reason}"
        if notes:
            reason += "; " + "; ".join(notes)
        judgement = JudgementRecord(
            subject_kind=subject.subject_kind, subject_id=subject.subject_id, subject_digest=subject.subject_digest,
            subject_store_sequence=subject.subject_store_sequence, resource_id=subject.resource_id,
            action=subject.action, capability=subject.capability,  # type: ignore[arg-type]
            governed_by="after_the_fact", verdict=verdict, reason=reason[:1024],  # type: ignore[arg-type]
            evaluated_as_of=latest, evaluated_from=earliest if earliest != latest else None,
            policy_binding=own.binding if own is not None and verdict == mine else None,
            gate_results=list(own.gate_results) if own is not None and verdict == mine else [],
            current_verdict=prior_record.current_verdict if prior_record is not None else None,
            flagged_for_review=True if mine != theirs or notes
            or (prior_record is not None and prior_record.flagged_for_review) else None,
            matched_evidence_id=None if same_change else entry.record_id, judged_at=now, **issuer,
        )
        return self._sign(judgement)

    def _hint(self, record: ObservationRecord, action: str, earliest: datetime, latest: datetime) -> str | None:
        """Unmatched execution evidence that may be this change: no version ID to confirm it."""
        skew = self.bounds.skew
        best: tuple[timedelta, str] | None = None
        for stored in self._na.db.unmatched_executions(record.resource_id, action, None, record.capability, limit=50):
            entry: EvidenceStoreEntry = stored["entry"]
            at = _parse_time(stored["payload"].get("executed_at"))
            if at is None:
                continue
            if earliest - skew <= at <= latest + skew:
                gap = abs(at - latest)
                ident = entry.evidence_id or entry.record_id
                if ident is not None and (best is None or gap < best[0]):
                    best = (gap, ident)
        return best[1] if best else None

    # -- evaluation as of a time --------------------------------------------------

    def _judging(self) -> _Judging:
        """The policy history one judgement replays (v1.3.1: built once, not per point). When the
        registry's active policies differ from the policy table (an activation it has not
        recorded: another instance of an older release, a period with the records off), the NA
        records what it finds first, late."""
        history = self.policy_history()
        if history.started_at is None:
            if time.monotonic() >= self._next_backfill:
                self._next_backfill = time.monotonic() + BACKFILL_RETRY_SECONDS
                try:
                    self._backfill()
                except Exception as exc:  # noqa: BLE001 -- judged indeterminate; status reports it
                    logger.warning("policy history backfill failed: %s", exc)
                history = self.policy_history()
        elif self._drifted(history):
            try:
                self._reconcile_registry()
                self._repair_policy_drift()
            except Exception as exc:  # noqa: BLE001 -- judge with what the store holds
                logger.warning("registry catch-up before judging failed: %s", exc)
            history = self.policy_history()
        return _Judging(history)

    def _drifted(self, history: PolicyHistory) -> bool:
        recorded = {policy_id: version for policy_id, (version, _) in history.latest().items()}
        actual = {policy_id: version for policy_id, (version, _) in self._na.db.active_boundary_policy_versions().items()}
        return recorded != actual

    def _policy(self, ctx: _Judging, policy_id: str, version: int) -> BoundaryPolicy | None:
        key = (policy_id, version)
        if key not in ctx.policies:
            row = self._na.db.get_boundary_policy_row(policy_id, version)
            ctx.policies[key] = self._na.db.parse_boundary_policy_row(row) if row is not None else None
        return ctx.policies[key]

    def _attestation_row(self, ctx: _Judging, attestation_id: str) -> Any:
        if attestation_id not in ctx.attestations:
            ctx.attestations[attestation_id] = self._na.db.get_membership_attestation(attestation_id)
        return ctx.attestations[attestation_id]

    def _change_points(self, ctx: _Judging, earliest: datetime, latest: datetime) -> list[datetime]:
        """When what applies to a change may differ inside its window: a policy activated or
        deactivated, and (v1.3.1) a policy active then reaching its ``valid_from`` or ``valid_until``."""
        times = set(ctx.history.change_times(earliest, latest))
        bounds: list[tuple[datetime, datetime]] = []
        for at in [earliest, *sorted(times)]:
            for policy_id, (version, _) in sorted((ctx.history.active_at(at) or {}).items()):
                policy = self._policy(ctx, policy_id, version)
                if policy is not None:
                    bounds.append((policy.valid_from, policy.valid_until))
        times.update(validity_change_times(bounds, earliest, latest))
        return sorted(times)

    def _context(self, record: ObservationRecord | BreakGlassRecord, at: datetime, requester: str) -> ContextRecord:
        own = self._na.genesis_block.network_name
        if isinstance(record, ObservationRecord):
            attributes: dict[str, Any] = {"resource_id": record.resource_id, "action": record.action,
                                          "source": record.source}
            if record.actor is not None:
                attributes["actor"] = record.actor
            if record.version_id is not None:
                attributes["version_id"] = record.version_id
            return ContextRecord(
                context_id=f"observation:{record.observation_id}", agreement_id=record.observation_id,
                parent_kind="observation", requester_sovereign_id=requester, provider_sovereign_id=own,
                requested_capability=record.capability, request_parameters=dict(record.metadata),
                attributes=attributes, requested_at=at,
            )
        # The attestation reaches the gates through the basis the engine binds;
        # parent_kind stays "break_glass" so a policy can single such changes out.
        return ContextRecord(
            context_id=f"break_glass:{record.break_glass_id}",
            agreement_id=record.attestation_id or record.break_glass_id,
            parent_kind="break_glass", requester_sovereign_id=requester, provider_sovereign_id=own,
            requested_capability=record.capability, request_parameters=dict(record.request_parameters),
            attributes=dict(record.attributes), requested_at=at,
        )

    def _feed_revoked_since(self, ctx: _Judging, issuer_sovereign_id: str, attestation_id: str) -> datetime | None:
        """When an imported feed first revoked the attestation, or None (v1.3.1: a later cumulative
        feed that lists it again does not move this; a row 1.3.0 moved is read from the feeds)."""
        if attestation_id not in ctx.revoked_since:
            imported = self._na.db.get_imported_sovereign_revocation(issuer_sovereign_id, attestation_id)
            since = _parse_time(imported["imported_at"]) if imported is not None else None
            if since is not None:
                first = _parse_time(self._na.db.first_feed_import(issuer_sovereign_id, attestation_id))
                if first is not None and first < since:
                    since = first
            ctx.revoked_since[attestation_id] = since
        return ctx.revoked_since[attestation_id]

    def _basis_at(self, record: BreakGlassRecord, at: datetime, ctx: _Judging, *, current: bool) -> AttestationBasis | None:
        """The attestation's state at ``at``: issuer revocation and imported feeds as recorded then."""
        if record.attestation_id is None:
            return None
        row = self._attestation_row(ctx, record.attestation_id)
        attestation = row["attestation"] if row else None
        stored_status: str | None = None
        feed_revoked = False
        if row is not None:
            revoked_at = row.get("revoked_at")
            revoked = row["status"] == "revoked" and (
                current or (revoked_at is not None and datetime.fromisoformat(str(revoked_at)) <= at)
            )
            stored_status = "revoked" if revoked else "active"
            if attestation is not None:
                since = self._feed_revoked_since(ctx, attestation.issuer_sovereign_id, record.attestation_id)
                feed_revoked = since is not None and (current or since <= at)
        return assess_attestation_basis(
            record.attestation_id, attestation,
            issuer_public_keys=self._na.boundary_policies.policy_public_keys(),
            stored_status=stored_status, feed_revoked=feed_revoked, revocation_seq_checked=0,
            requester_id=attestation.subject_id if attestation is not None else record.executor_sovereign_id,
        )

    def _evaluate(
        self, record: ObservationRecord | BreakGlassRecord, at: datetime, ctx: _Judging, *, current: bool = False
    ) -> tuple[PolicyVerdict | None, str | None]:
        """The verdict on a change at ``at`` (or under today's policies), or (None, why it cannot be told)."""
        policies_service = self._na.boundary_policies
        if isinstance(record, BreakGlassRecord) and record.attestation_id is None:
            # An agreement-based evaluation rests on the agreement, its signers and its
            # term, none of which the record carries: nothing the NA holds can say.
            return None, "the break-glass record names no attestation; the NA cannot judge the evaluation it skipped"
        integrity: list[str] = []
        if current:
            loaded = self._na.db.load_active_boundary_policies()
            policies: list[BoundaryPolicy] = list(loaded.policies)
            integrity = list(loaded.integrity_failures)
        else:
            active = ctx.history.active_at(at)
            if active is None:
                started = ctx.history.started_at.isoformat() if ctx.history.started_at else "no time recorded"
                return None, f"the store's policy history starts at {started}, after this change"
            policies = []
            for policy_id, (version, digest) in sorted(active.items()):
                policy = self._policy(ctx, policy_id, version)
                if policy is None or (digest is not None and policy.digest() != digest):
                    integrity.append(f"{policy_id}@{version}")
                    continue
                policies.append(policy)
        basis = self._basis_at(record, at, ctx, current=current) if isinstance(record, BreakGlassRecord) else None
        if isinstance(record, BreakGlassRecord):
            requester = basis.attestation.subject_id if basis is not None and basis.attestation is not None \
                else record.executor_sovereign_id
        else:
            requester = record.observer_sovereign_id
        verdict = evaluate_policies_as_of(
            self._context(record, at, requester), policies=policies, registry=policies_service.registry,
            policy_public_keys=policies_service.policy_public_keys(), as_of=at, basis=basis,
            policy_integrity_failures=integrity,
        )
        return verdict, None

    # -- sweep ----------------------------------------------------------------------

    def sweep_unjudged(self, limit: int) -> int:
        """Judge up to ``limit`` of the oldest records no judgement covers (v1.3.1): one whose
        judgement failed at admission is judged again without an operator. Returns how many."""
        judged = 0
        for kind, record_id in self._na.db.unjudged_records(limit):
            subject: SubjectKind = "observation" if kind == "observation" else "break_glass"
            stored = self._na.db.get_entry_by_record(subject, record_id)
            if stored is not None and self._judge_quietly(subject, stored) is not None:
                judged += 1
        return judged

    def _maybe_sweep(self) -> None:
        """After an admission: sweep a few unjudged records, at most every SWEEP_INTERVAL_SECONDS."""
        if time.monotonic() - self._last_sweep < SWEEP_INTERVAL_SECONDS:
            return
        self._last_sweep = time.monotonic()
        try:
            self.sweep_unjudged(SWEEP_BATCH)
        except Exception as exc:  # noqa: BLE001 -- admission already succeeded
            logger.warning("sweeping unjudged records failed: %s", exc)

    # -- registry -----------------------------------------------------------------

    def _registry_rows(self, db: Any = None) -> list[tuple[int, RegistryRecord, str | None]]:
        """Registry records with their store positions and dedupe keys, in effect order (v1.3.1):
        retention carries removed records forward after newer ones, so store order is not history."""
        out = []
        for stored in (db or self._na.db).registry_entries():
            try:
                record = RegistryRecord.model_validate(stored["payload"])
            except PydanticValidationError:
                logger.warning("registry entry %s does not parse", stored["entry"].store_sequence)
                continue
            out.append((stored["entry"].store_sequence, record, stored.get("dedupe_key")))
        out.sort(key=lambda r: (r[1].effective_at, r[0]))
        return out

    def _registry_records(self) -> list[tuple[int, RegistryRecord]]:
        return [(seq, record) for seq, record, _ in self._registry_rows()]

    @staticmethod
    def _history_of(rows: Sequence[tuple[int, RegistryRecord, str | None]]) -> PolicyHistory:
        late = {record.registry_record_id for _, record, dedupe in rows if dedupe and dedupe.startswith(LATE_PREFIX)}
        return PolicyHistory.from_records(((seq, record) for seq, record, _ in rows), late=late)

    def policy_history(self) -> PolicyHistory:
        return self._history_of(self._registry_rows())

    def _floor(self, rows: Sequence[tuple[int, RegistryRecord, str | None]], db: Any = None) -> datetime | None:
        """The latest time the store already holds: its registry records, newest entry and latest
        anchor (v1.3.1). A record the NA reconstructs after the backfill takes effect no earlier."""
        times = [record.effective_at for _, record, _ in rows]
        held = (db or self._na.db).registry_floor()
        if held is not None:
            times.append(held)
        return max(times) if times else None

    def _late_time(self, rows: Sequence[tuple[int, RegistryRecord, str | None]], db: Any = None) -> datetime:
        """When a policy change found late takes effect: now, and never before what the store holds."""
        floor = self._floor(rows, db)
        now = self._now()
        return max(now, floor) if floor is not None else now

    def _record(
        self, records: Sequence[tuple[RegistryRecord, str | None]], *, anchor: bool = True
    ) -> list[EvidenceStoreEntry]:
        now = self._now()
        pending = [self._pending("registry", self._sign(r), now=now, lookup={"dedupe_key": d}) for r, d in records]
        return self._append(pending, anchor=anchor)

    # Each registry record names its source in its dedupe key (an audit event, a
    # key row), so reconciliation adds exactly the records the store is missing.

    def activate_policy(self, policy: BoundaryPolicy, recorded_by: str | None, audit_event_id: str | None) -> int | None:
        """Activate a policy version (v1.3.1: with the records on, it and its registry records, the
        version it replaced deactivated, commit in one transaction). Returns the replaced version."""
        if not self.enabled:
            return self._na.db.activate_boundary_policy(policy.policy_id, policy.version)
        event_id = audit_event_id or str(uuid.uuid4())
        now = self._now()
        replaced: dict[str, int | None] = {}

        def make(db: Any) -> list[Any]:
            previous = db.activate_boundary_policy_rows(policy.policy_id, policy.version)
            replaced["previous"] = previous
            records: list[tuple[RegistryRecord, str]] = []
            if previous is not None and previous != policy.version:
                records.append((RegistryRecord(
                    event="policy_deactivated", effective_at=now, policy_id=policy.policy_id,
                    policy_version=previous, recorded_by=recorded_by, **self._issuer(),
                ), f"registry:audit:{event_id}:previous"))
            records.append((RegistryRecord(
                event="policy_activated", effective_at=now, policy_id=policy.policy_id, policy_version=policy.version,
                policy_digest=policy.digest(), recorded_by=recorded_by, **self._issuer(),
            ), f"registry:audit:{event_id}"))
            return [self._pending("registry", self._sign(r), now=now, lookup={"dedupe_key": d}) for r, d in records]

        self._write_with(make, "The activation could not be stored")
        return replaced["previous"]

    def deactivate_policy(self, policy_id: str, version: int, recorded_by: str | None,
                          audit_event_id: str | None) -> bool:
        """Deactivate an active version (v1.3.1: with its registry record, in one transaction).
        Returns False when it was not active."""
        if not self.enabled:
            return self._na.db.deactivate_boundary_policy(policy_id, version)
        event_id = audit_event_id or str(uuid.uuid4())
        now = self._now()
        done: dict[str, bool] = {}

        def make(db: Any) -> list[Any]:
            done["deactivated"] = db.deactivate_boundary_policy_rows(policy_id, version)
            if not done["deactivated"]:
                return []
            record = RegistryRecord(event="policy_deactivated", effective_at=now, policy_id=policy_id,
                                    policy_version=version, recorded_by=recorded_by, **self._issuer())
            return [self._pending("registry", self._sign(record), now=now,
                                  lookup={"dedupe_key": f"registry:audit:{event_id}"})]

        self._write_with(make, "The deactivation could not be stored")
        return done["deactivated"]

    def _write_with(self, make: Callable[[Any], Sequence[Any]], unavailable: str) -> None:
        try:
            self._na.db.append_evidence_entries_with(make)
        except self._na.db.integrity_errors:
            raise
        except self._na.db.database_errors as exc:
            logger.warning("evidence store write failed: %s", exc)
            raise ServiceUnavailableError(unavailable, code="evidence_store_unavailable") from exc
        self._store.maybe_anchor()

    def key_registered(self, key: ExecutorKey, registered_at: str, recorded_by: str | None) -> None:
        if not self.enabled:
            return
        self._record_safely([(RegistryRecord(
            event="executor_key_registered", effective_at=datetime.fromisoformat(registered_at),
            key_id=key.key_id, public_key=key.public_key, executor_sovereign_id=key.executor_sovereign_id,
            key_role=key.role, resource_prefix=key.resource_prefix,  # type: ignore[arg-type]
            recorded_by=recorded_by, **self._issuer(),
        ), f"registry:key:{key.key_id}:registered")], "key registration")

    def key_retired(self, key_id: str, retired_at: str, recorded_by: str | None) -> None:
        if not self.enabled:
            return
        self._record_safely([(RegistryRecord(event="executor_key_retired", effective_at=datetime.fromisoformat(retired_at),
                                             key_id=key_id, recorded_by=recorded_by, **self._issuer()),
                              f"registry:key:{key_id}:retired")], "key retirement")

    def _record_safely(self, records: Sequence[tuple[RegistryRecord, str | None]], what: str) -> None:
        """Record registry history after a change already made; a failure is logged and repaired at start."""
        try:
            self._record(records)
        except Exception as exc:  # noqa: BLE001 -- the change itself has been made
            logger.error("could not record the %s in the evidence store: %s", what, exc)
            try:
                self._na.db.add_audit_event("registry_record_failed", {"what": what, "error": type(exc).__name__})
            except Exception:  # noqa: BLE001
                pass

    def ensure_registry(self) -> None:
        """At start: backfill a store upgraded to 1.3, add what the registry is missing (late),
        repair drift, record operator keys and judge records left unjudged. Each step runs on its
        own; none fails start, and a failure is reported in ``/admin/evidence/status``."""
        if not self.enabled:
            return
        self._start_problems = []
        steps: tuple[tuple[str, Callable[[], Any]], ...] = (
            ("the policy history backfill", self._backfill),
            ("registry reconciliation", self._reconcile_registry),
            ("policy drift repair", self._repair_policy_drift),
            ("recording operator key holders", self._record_operator_keys),
        )
        for name, step in steps:
            try:
                step()
            except Exception as exc:  # noqa: BLE001
                logger.error("evidence store registry check (%s) failed: %s", name, exc)
                self._start_problems.append(f"{name} failed at start ({type(exc).__name__})")
        if self._na.judge_on_admission:
            try:
                self.sweep_unjudged(SWEEP_START_LIMIT)
            except Exception as exc:  # noqa: BLE001
                logger.error("judging unjudged records at start failed: %s", exc)

    _POLICY_AUDIT_EVENTS = ("boundary_policy_activated", "boundary_policy_deactivated")

    def _backfill(self) -> None:
        """Once, when a store first runs with the records on: the policy history from the audit
        log, at the times it records, marked ``reconstructed``, and the key history from the key
        table, in the same append as the ``policy_history_started`` record that marks how far back
        the history reaches. It rests on the audit log as it stood then; nothing later reads the
        audit log for times (v1.3.1)."""
        if self._na.db.get_entry_by_dedupe_key("registry:policy_history_started") is not None:
            return
        issuer = self._issuer()
        audit: list[tuple[RegistryRecord, str | None]] = []
        explained: set[tuple[str, int]] = set()
        for event in self._na.db.list_audit_events(event_types=list(self._POLICY_AUDIT_EVENTS)):
            record = self._policy_record_from_audit(event, issuer)
            if record is not None:
                audit.append((record, f"registry:audit:{event.get('event_id')}"))
                if record.event == "policy_activated" and record.policy_id is not None \
                        and record.policy_version is not None:
                    explained.add((record.policy_id, record.policy_version))
        audit.sort(key=lambda r: r[0].effective_at)
        # Active versions no audit event explains (an older audit log): their activation columns.
        reconstructed: list[tuple[RegistryRecord, str | None]] = []
        for row in self._na.db.list_boundary_policy_rows():
            if not row.get("active") or (row["policy_id"], int(row["version"])) in explained:
                continue
            policy = self._na.db.parse_boundary_policy_row(row)
            at = datetime.fromisoformat(str(row.get("activated_at") or row.get("created_at")))
            reconstructed.append((RegistryRecord(
                event="policy_activated", effective_at=at, reconstructed=True, policy_id=row["policy_id"],
                policy_version=int(row["version"]), policy_digest=policy.digest() if policy is not None else None,
                **issuer,
            ), f"registry:active:{row['policy_id']}:{row['version']}"))
        keys = self._key_records(set(), None)
        times = [r.effective_at for r, _ in (*audit, *reconstructed)]
        started = RegistryRecord(event="policy_history_started", effective_at=min(times) if times else self._now(),
                                 **issuer)
        try:
            self._record([(started, "registry:policy_history_started"), *audit, *reconstructed, *keys], anchor=False)
        except self._na.db.integrity_errors:
            return  # another instance backfilled first
        self._na.db.add_audit_event("registry_backfilled", {
            "reconstructed_records": len(audit) + len(reconstructed), "key_records": len(keys),
        })

    @classmethod
    def _policy_record_from_audit(cls, event: dict[str, Any], issuer: dict[str, Any]) -> RegistryRecord | None:
        details = event.get("details") or {}
        if event.get("event_type") not in cls._POLICY_AUDIT_EVENTS:
            return None  # v1.3.1: only an activation or a deactivation, matched exactly
        try:
            at = datetime.fromisoformat(str(event["created_at"]))
            version = int(details["version"])
            policy_id = str(details["policy_id"])
        except (KeyError, TypeError, ValueError):
            return None
        activated = event["event_type"] == "boundary_policy_activated"
        return RegistryRecord(
            event="policy_activated" if activated else "policy_deactivated", effective_at=at,
            reconstructed=True, policy_id=policy_id, policy_version=version,
            policy_digest=details.get("policy_digest") if activated else None, **issuer,
        )

    def _key_records(self, have: set[str], floor: datetime | None) -> list[tuple[RegistryRecord, str | None]]:
        """Executor and observer key registrations and retirements the registry lacks, from the key
        table; after the backfill (``floor``) never effective before what the store holds."""
        issuer = self._issuer()
        out: list[tuple[RegistryRecord, str | None]] = []

        def at(value: Any) -> datetime:
            when = datetime.fromisoformat(str(value))
            return max(when, floor) if floor is not None else when

        for row in self._na.db.list_executor_keys():
            key = self._store.key_from_row(row)
            if f"registry:key:{key.key_id}:registered" not in have:
                out.append((RegistryRecord(
                    event="executor_key_registered", effective_at=at(row["registered_at"]),
                    reconstructed=True, key_id=key.key_id, public_key=key.public_key,
                    executor_sovereign_id=key.executor_sovereign_id, key_role=key.role,  # type: ignore[arg-type]
                    resource_prefix=key.resource_prefix, **issuer,
                ), f"registry:key:{key.key_id}:registered"))
            if row["retired_at"] and f"registry:key:{key.key_id}:retired" not in have:
                out.append((RegistryRecord(
                    event="executor_key_retired", effective_at=at(row["retired_at"]),
                    reconstructed=True, key_id=key.key_id, **issuer,
                ), f"registry:key:{key.key_id}:retired"))
        return out

    def _reconcile_registry(self) -> int:
        """After the backfill: record every policy activation or deactivation the audit log holds
        and the registry does not (made while the records were off, or by an instance of an older
        release), and every key change the key table holds. Idempotent; returns how many records
        it added.

        v1.3.1: nothing signs the audit log, so its times are not trusted. A policy change found
        here takes effect now, never before what the store already holds, and its dedupe key marks
        it late: judgements of changes made before it are flagged for review."""
        if self._na.db.get_entry_by_dedupe_key("registry:policy_history_started") is None:
            return 0  # nothing to reconcile before the history starts
        have = self._na.db.dedupe_keys("registry:")
        rows = self._registry_rows()
        effective = self._late_time(rows)
        missing: list[tuple[RegistryRecord, str | None]] = []
        found: list[tuple[datetime, RegistryRecord, str]] = []
        for event in self._na.db.list_audit_events(event_types=list(self._POLICY_AUDIT_EVENTS)):
            event_id = event.get("event_id")
            if f"registry:audit:{event_id}" in have or f"{LATE_PREFIX}audit:{event_id}" in have:
                continue
            record = self._policy_record_from_audit(event, self._issuer())
            if record is not None:
                found.append((record.effective_at, record.model_copy(update={"effective_at": effective}),
                              f"{LATE_PREFIX}audit:{event_id}"))
        # In the order the audit log gives them: replayed at one time, the last one stands.
        missing.extend((record, dedupe) for _, record, dedupe in sorted(found, key=lambda f: f[0]))
        missing.extend(self._key_records(have, self._floor(rows)))
        if not missing:
            return 0
        try:
            self._record(missing, anchor=False)
        except self._na.db.integrity_errors:
            return 0  # another instance reconciled at the same time
        self._na.db.add_audit_event("registry_reconciled", {
            "records": len(missing), "policy_records": len(found),
            "claimed_times": [at.isoformat() for at, _, _ in sorted(found, key=lambda f: f[0])][:100],
            "effective_at": effective.isoformat(),
        })
        return len(missing)

    def _repair_policy_drift(self) -> None:
        """Record activations the registry missed, as the policy table has them now, marked
        reconstructed and late (v1.3.1: compared and written under the store's write lock, which
        activations take too, so a concurrent activation is never mistaken for drift)."""
        issuer = self._issuer()
        added: list[RegistryRecord] = []

        def make(db: Any) -> list[Any]:
            rows = self._registry_rows(db)
            recorded = self._history_of(rows).latest()
            actual = db.active_boundary_policy_versions()
            now = self._late_time(rows, db)
            records: list[RegistryRecord] = []
            for policy_id, (version, digest) in sorted(actual.items()):
                if recorded.get(policy_id, (None, None))[0] != version:
                    records.append(RegistryRecord(event="policy_activated", effective_at=now, reconstructed=True,
                                                  policy_id=policy_id, policy_version=version, policy_digest=digest,
                                                  **issuer))
            for policy_id, (version, _) in sorted(recorded.items()):
                if policy_id not in actual:
                    records.append(RegistryRecord(event="policy_deactivated", effective_at=now, reconstructed=True,
                                                  policy_id=policy_id, policy_version=version, **issuer))
            added.extend(records)
            return [self._pending("registry", self._sign(r), now=now,
                                  lookup={"dedupe_key": f"{LATE_PREFIX}drift:{r.registry_record_id}"}) for r in records]

        self._na.db.append_evidence_entries_with(make)
        if added:
            self._na.db.add_audit_event("registry_repaired", {"records": len(added)})

    # -- status -------------------------------------------------------------------

    def registry_status(self) -> dict[str, Any]:
        """Additive fields for ``/admin/evidence/status`` (v1.3.1): how far back the policy history
        reaches, and whether the registry can be judged on."""
        problems = list(self._start_problems)
        history = self.policy_history()
        if history.started_at is None:
            problems.append("the policy history has not started: every change is judged indeterminate")
        elif self._drifted(history):
            problems.append("the registry's active policies differ from the policy table: an activation "
                            "it has not recorded (recorded, late, before the next judgement)")
        return {
            "policy_history_started": history.started_at.isoformat() if history.started_at else None,
            "registry_healthy": not problems,
            "registry_problems": problems,
        }

    # -- operator key holders ---------------------------------------------------

    def operator_holders(self) -> dict[str, dict[str, Any]]:
        """key_id -> the holder the store records for it, with its key, tier and approval.

        v1.3.1: the latest record by ``effective_at`` (store order breaks ties), so a record
        retention carried forward never stands over a newer one."""
        out: dict[str, dict[str, Any]] = {}
        for _, record in self._registry_records():
            if record.event == "operator_key_holder" and record.key_id is not None:
                out[record.key_id] = {
                    "key_id": record.key_id, "holder": record.holder, "public_key": record.public_key,
                    "operator_tier": record.operator_tier, "since": record.effective_at.isoformat(),
                    "approved_by": record.approved_by, "registry_record_id": record.registry_record_id,
                }
        return out

    def _record_operator_keys(self) -> None:
        """Record configured operator keys the store does not hold, or holds with another public key
        or tier, one key at a time.

        ``OPERATOR_KEY_HOLDERS_JSON`` names holders at the first start only, when the store
        records no holder yet (v1.3.1). After that a new key, and a key whose public key changed,
        is recorded as its own holder (unnamed) until a holder change names one: a second holder
        approves it. A tier change keeps the holder."""
        recorded = self.operator_holders()
        first_start = not recorded
        for key_id, public_key in sorted(self._na.operator_public_keys.items()):
            tier = self._na.operator_key_tiers.get(key_id)
            configured = self._na.operator_key_holders.get(key_id)
            known = recorded.get(key_id)
            if known is None:
                holder = configured if first_start and configured else key_id
                if configured and not first_start:
                    logger.warning("operator key %s is new: recorded without a holder; name %r with a holder "
                                   "change, which a second holder approves", key_id, configured)
                dedupe = f"holder:{key_id}:first"
            else:
                rekeyed = known["public_key"] != public_key
                if rekeyed:
                    holder = key_id
                    if known["holder"] != key_id:
                        logger.warning("operator key %s has a new public key: its holder %r is not carried over; "
                                       "name one with a holder change", key_id, known["holder"])
                else:
                    holder = known["holder"]
                    if configured is not None and configured != holder:
                        logger.warning("operator key %s: the store records holder %r; the configured %r is ignored "
                                       "(a holder changes only with a second holder's approval)",
                                       key_id, holder, configured)
                    if known["operator_tier"] == tier:
                        continue
                # Keyed on the record it replaces, so two instances cannot both record this change.
                dedupe = f"holder:{key_id}:after:{known['registry_record_id']}"
            record = RegistryRecord(event="operator_key_holder", effective_at=self._now(), key_id=key_id,
                                    public_key=public_key, operator_tier=tier, holder=holder, **self._issuer())
            try:
                self._record([(record, dedupe)], anchor=False)
            except self._na.db.integrity_errors:
                continue  # another instance recorded it

    def propose_holder(self, key_id: str, holder: Any, proposed_by: str) -> dict[str, Any]:
        self.require_enabled()
        if key_id not in self._na.operator_public_keys:
            raise NotFoundError("unknown operator key", code="unknown_operator_key")
        if not isinstance(holder, str) or not 1 <= len(holder) <= 128:
            raise BadRequestError("holder must be a string of 1 to 128 characters", code="invalid_holder")
        proposal_id = str(uuid.uuid4())
        self._na.db.add_holder_proposal(proposal_id, key_id, holder, proposed_by)
        self._na.db.add_audit_event("operator_holder_proposed", {
            "proposal_id": proposal_id, "key_id": key_id, "holder": holder, "proposed_by": proposed_by,
        })
        return {"proposal_id": proposal_id, "key_id": key_id, "holder": holder, "proposed_by": proposed_by,
                "approved": False}

    def _proposer_key_at(self, key_id: str, at: datetime) -> str | None:
        """The public key the store recorded for an operator key at a time (its first record when
        none is that old)."""
        found: str | None = None
        for _, record in self._registry_records():
            if record.event == "operator_key_holder" and record.key_id == key_id:
                if found is not None and record.effective_at > at:
                    break
                found = record.public_key
        return found

    def approve_holder(self, proposal_id: str, approved_by: str) -> dict[str, Any]:
        """Approve a holder change with a privileged key of another holder; the change is recorded in the store."""
        self.require_enabled()
        row = self._na.db.get_holder_proposal(proposal_id)
        if row is None:
            raise NotFoundError("unknown holder change", code="holder_change_not_found")
        if row["approved_by"] is not None:
            raise ConflictError("this holder change is already approved", code="holder_change_already_approved")
        proposed_by = row["proposed_by"]
        # v1.3.1: the key that proposed the change must still stand: not revoked, still
        # configured, and with the public key it had when it proposed.
        proposed_at = _parse_time(row["proposed_at"])
        current_key = self._na.operator_public_keys.get(proposed_by)
        if self._na.db.is_operator_key_revoked(proposed_by) or current_key is None or (
                proposed_at is not None and self._proposer_key_at(proposed_by, proposed_at) not in (None, current_key)):
            raise ConflictError("the operator key that proposed this holder change was revoked, removed or "
                                "re-keyed since; propose it again", code="holder_change_proposer_revoked")
        holders = self.operator_holders()
        # Two holders means two named holders: a key the store does not record, or whose holder
        # was never named (it is its own holder), cannot stand for a second person.
        for key in (proposed_by, approved_by):
            known = holders.get(key)
            if known is None or known["holder"] == key:
                raise ConflictError(f"operator key {key} has no named holder in the store",
                                    code="holder_change_needs_named_holders")
        proposer = holders[proposed_by]["holder"]
        approver = holders[approved_by]["holder"]
        if approved_by == proposed_by or approver == proposer:
            raise ConflictError("a holder change needs the approval of a different holder",
                                code="holder_change_needs_second_holder")
        record = RegistryRecord(
            event="operator_key_holder", effective_at=self._now(), key_id=row["key_id"],
            public_key=self._na.operator_public_keys.get(row["key_id"]),
            operator_tier=self._na.operator_key_tiers.get(row["key_id"]), holder=row["holder"],
            approved_by=approved_by, recorded_by=proposed_by, **self._issuer(),
        )
        signed = self._sign(record)
        now = self._now()

        def make(db: Any) -> list[Any]:
            # The approval and its record land together, or neither does.
            if not db.mark_holder_proposal_approved(proposal_id, approved_by, record.registry_record_id):
                raise _AlreadyApproved()
            return [self._pending("registry", signed, now=now)]

        try:
            entries = self._na.db.append_evidence_entries_with(make)
        except _AlreadyApproved:
            raise ConflictError("this holder change is already approved",
                                code="holder_change_already_approved") from None
        except self._na.db.database_errors as exc:
            raise ServiceUnavailableError("The holder change could not be stored",
                                          code="evidence_store_unavailable") from exc
        self._store.maybe_anchor()
        self._na.db.add_audit_event("operator_holder_changed", {
            "proposal_id": proposal_id, "key_id": row["key_id"], "holder": row["holder"],
            "proposed_by": proposed_by, "approved_by": approved_by,
            "store_sequence": entries[0].store_sequence,
        })
        return {"proposal_id": proposal_id, "key_id": row["key_id"], "holder": row["holder"],
                "approved": True, "approved_by": approved_by, "registry_record_id": record.registry_record_id}

    # -- state ------------------------------------------------------------------

    def resource_changes(self, resource_id: str) -> dict[str, Any]:
        """Every change to a resource, with how it was governed and its state (oldest first)."""
        self.require_enabled()
        rows = self._na.db.resource_changes(resource_id, CHANGES_LIMIT + 1)
        truncated = len(rows) > CHANGES_LIMIT
        rows = rows[:CHANGES_LIMIT]
        judgements: dict[tuple[str, str], dict[str, Any]] = {}
        matched: dict[str, str] = {}
        for stored in rows:
            entry: EvidenceStoreEntry = stored["entry"]
            if entry.entry_kind == "judgement" and entry.subject_id is not None:
                judgements[(stored["payload"].get("subject_kind"), entry.subject_id)] = stored["payload"]
                if entry.matched_evidence_id:
                    matched[entry.matched_evidence_id] = entry.subject_id
        changes: list[dict[str, Any]] = []
        for stored in rows:
            entry = stored["entry"]
            payload = stored["payload"]
            kind = entry.entry_kind
            base = {"store_sequence": entry.store_sequence, "kind": kind, "recorded_at": entry.recorded_at.isoformat()}
            if kind == "execution":
                changes.append({**base, "record_id": entry.evidence_id, "action": entry.resource_action,
                                "at": payload.get("executed_at"), "governed_by": "prior_decision",
                                "state": "recorded", "decision_id": entry.decision_id,
                                "observed_by": matched.get(entry.evidence_id or "")})
            elif kind in ("observation", "break_glass"):
                judgement = judgements.get((kind, entry.record_id or ""))
                at = payload.get("changed_at") or payload.get("changed_not_after") or payload.get("executed_at")
                change = {**base, "record_id": entry.record_id, "action": entry.resource_action, "at": at,
                          "governed_by": judgement["governed_by"] if judgement else None,
                          "state": self._state(judgement)}
                if judgement:
                    change["verdict"] = judgement["verdict"]
                    if judgement.get("flagged_for_review"):
                        change["flagged_for_review"] = True
                    if judgement.get("possible_match_evidence_id"):
                        change["possible_match_evidence_id"] = judgement["possible_match_evidence_id"]
                if kind == "break_glass":
                    change["justification"] = payload.get("justification")
                    change["observed_by"] = matched.get(entry.record_id or "")
                changes.append(change)
            elif kind == "quarantine":
                changes.append({**base, "record_id": entry.record_id, "action": None,
                                "at": payload.get("quarantined_at"), "governed_by": None, "state": "quarantined",
                                "record_kind": payload.get("record_kind"), "rejection_code": payload.get("rejection_code")})
        return {"resource_id": resource_id, "truncated": truncated, "changes": changes}

    @staticmethod
    def _state(judgement: dict[str, Any] | None) -> str:
        """The state table (Stage 2): observed, matched, judged_allowed, judged_denied, indeterminate."""
        if judgement is None:
            return "observed"
        if judgement["governed_by"] == "prior_decision":
            # Matched, unless the observer's own facts deny what the decision allowed.
            return "judged_denied" if judgement["verdict"] == "deny" else "matched"
        return {"allow": "judged_allowed", "deny": "judged_denied"}.get(judgement["verdict"], "indeterminate")
