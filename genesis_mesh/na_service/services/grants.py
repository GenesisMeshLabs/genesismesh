"""Pre-issued grants (v1.6.0, Stage 5): the NA side.

Routes in ``routes/grants.py`` parse HTTP and call this service. The NA signs
a grant only after ``trust.grants.check_grant`` finds that every policy that
applies allows every request the grant permits; a refusal names its reason
(``GrantIssuanceRefusal``). The grant, each admitted use and each revocation
are store entries, under the anchors.

A holder asks for a time token with a request signed by the grant's bearer key
and uploads each use; the NA admits a use only in its chain's order, inside the
envelope, the budget and the time rules (``trust.grants.use_problem``), assigns
it the next position of its resource's chain, and keeps a use it refuses for
good as a quarantine entry.

Grants are revoked by an operator, and automatically when their basis
attestation is revoked, a policy version they are bound to is deactivated, a
policy activated since may deny within their envelope (the NA re-checks every
usable grant the policy may cover), or their bearer key is retired. A
revocation that follows another change (an activation, a key retirement) runs
after that change commits; ``ensure_grants`` repeats the checks at start, so a
revocation an interrupted request missed is made then.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, NoReturn

from pydantic import ValidationError as PydanticValidationError

from ...crypto import verify_model_signature
from ...models.agreement import AgreementRecord
from ...models.boundary_policy import BoundaryPolicy
from ...models.evidence_store import EvidenceStoreEntry, canonical_json, payload_digest
from ...models.grants import (
    GRANT_CLOCK_SKEW,
    GRANT_MAX_USES,
    GRANT_MAX_USES_PER_TIME_TOKEN,
    GRANT_MAX_VALIDITY,
    CapabilityGrant,
    EnvelopeParameter,
    GrantExecutionEvidence,
    GrantRevocationRecord,
    TimeToken,
    TimeTokenRequest,
)
from ...models.key_succession import na_keys_at
from ...trust.evidence_store import build_entry
from ...trust.grants import (
    QUARANTINED_USE_CODES,
    GrantBasis,
    GrantCheck,
    PreviousUse,
    check_grant,
    entry_index,
    grant_horizon,
    next_previous,
    sign_grant_record,
    use_problem,
    use_secret_problem,
)
from ...trust.remediation import rfc3339
from ..db_remediation import stamp
from ..errors import BadRequestError, ConflictError, NotFoundError, ServiceUnavailableError, ValidationError

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService

logger = logging.getLogger(__name__)

#: Fields an issuance request may carry.
REQUEST_FIELDS: frozenset[str] = frozenset({
    "bearer_key_id", "capabilities", "agreement", "attestation_id", "valid_from", "valid_until", "max_uses",
    "max_uses_per_time_token", "parameter_envelope", "context_freshness_seq",
})

#: Most grants one page of ``GET /admin/grants`` returns.
LIST_LIMIT = 500


@dataclass(frozen=True)
class GrantLimits:
    """The NA's grant limits (``NA_GRANT_*``), each within the bounds every verifier applies."""

    max_validity_seconds: int = int(GRANT_MAX_VALIDITY.total_seconds())
    max_uses: int = 100
    max_uses_per_time_token: int = 10

    def __post_init__(self) -> None:
        for name, value, low, high in (
            ("NA_GRANT_MAX_VALIDITY_SECONDS", self.max_validity_seconds, 60, int(GRANT_MAX_VALIDITY.total_seconds())),
            ("NA_GRANT_MAX_USES", self.max_uses, 1, GRANT_MAX_USES),
            ("NA_GRANT_MAX_USES_PER_TIME_TOKEN", self.max_uses_per_time_token, 1, GRANT_MAX_USES_PER_TIME_TOKEN),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"{name} must be {low} to {high}")


class _Refused(Exception):
    """A use refused inside the write transaction."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class _AlreadyRevoked(Exception):
    """Another request revoked the grant first; raised inside the write transaction."""


def _summarise(exc: PydanticValidationError) -> list[dict[str, str]]:
    """Field locations and messages only: never echo input values."""
    return [{"field": ".".join(str(p) for p in err.get("loc", ())), "message": str(err.get("msg", "invalid"))}
            for err in exc.errors(include_input=False, include_url=False)[:16]]


def _exact_form_problem(raw: dict[str, Any], record: Any) -> str | None:
    if canonical_json(raw) == canonical_json(record.to_wire()):
        return None
    expected = record.to_wire()
    extra = sorted(set(raw) - set(expected))
    if extra:
        return "unexpected or null field " + ", ".join(repr(k) for k in extra)
    missing = sorted(set(expected) - set(raw))
    if missing:
        return "missing field " + ", ".join(repr(k) for k in missing)
    return "a field is not in its serialized form"


def _parse(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class GrantService:
    """NA application logic for pre-issued grants, time tokens, uses and revocations."""

    def __init__(self, service: "NetworkAuthorityService") -> None:
        self._na = service

    # -- shared -------------------------------------------------------------------

    @property
    def _db(self) -> Any:
        return self._na.db

    @property
    def _store(self) -> Any:
        return self._na.evidence_store_service

    @property
    def enabled(self) -> bool:
        """Stage 5 records are kept: the Stage 2 records are on and ``EVIDENCE_GRANTS=on``."""
        return bool(self._na.out_of_band_service.enabled and self._na.evidence_grants == "on")

    def require_enabled(self) -> None:
        self._store.require_enabled()
        if not self.enabled:
            raise NotFoundError("Grants are not issued (EVIDENCE_GRANTS=off)", code="grants_disabled")

    @property
    def limits(self) -> GrantLimits:
        limits: GrantLimits = self._na.grant_limits
        return limits

    def _now(self) -> datetime:
        # One clock with the out-of-band service: admission, judging and revocation agree on "now".
        now: datetime = self._na.out_of_band_service._now()
        return now

    def _issuer(self) -> dict[str, Any]:
        return {"issuer_sovereign_id": self._na.genesis_block.network_name, "issued_by": self._na.key_id}

    def _sign(self, record: Any) -> Any:
        return sign_grant_record(record, self._na.signer, self._na.key_id)

    @staticmethod
    def _grant(row: dict[str, Any]) -> CapabilityGrant:
        return CapabilityGrant.model_validate_json(row["grant_json"])

    def _pending(self, kind: str, record: Any, now: datetime, *, resource_sequence: int | None = None,
                 lookup: dict[str, Any] | None = None) -> tuple[Any, dict[str, Any], dict[str, Any]]:
        payload = record.to_wire()
        index = entry_index(record)
        if resource_sequence is not None:
            index["resource_sequence"] = resource_sequence

        def build(seq: int, prev: str | None) -> EvidenceStoreEntry:
            return build_entry(store_sequence=seq, entry_kind=kind, recorded_at=now, payload=payload,
                               prev_entry_digest=prev, index=index)

        return build, payload, {k: v for k, v in (lookup or {}).items() if v is not None}

    @staticmethod
    def _body(entry: EvidenceStoreEntry, payload: dict[str, Any], **extra: Any) -> dict[str, Any]:
        return {"entry": entry.model_dump(mode="json"), "entry_digest": entry.digest(), "payload": payload, **extra}

    def status_of(self, row: dict[str, Any], now: datetime | None = None) -> str:
        """``revoked``, ``expired``, ``exhausted``, ``scheduled`` (not valid yet) or ``active``."""
        now = now or self._now()
        if row["revoked_at"]:
            return "revoked"
        grant = self._grant(row)
        if now > grant.valid_until:
            return "expired"
        if int(row["uses"]) >= grant.max_uses:
            return "exhausted"
        if now < grant.valid_from:
            return "scheduled"
        return "active"

    def summary(self, row: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
        grant = self._grant(row)
        return {
            "grant_id": grant.grant_id, "status": self.status_of(row, now), "bearer_key_id": grant.bearer_key_id,
            "bearer_sovereign_id": grant.bearer_sovereign_id, "capabilities": list(grant.capabilities),
            "basis_kind": grant.basis_kind, "basis_id": grant.basis_id, "valid_from": _iso(grant.valid_from),
            "valid_until": _iso(grant.valid_until), "max_uses": grant.max_uses, "uses": int(row["uses"]),
            "issued_at": _iso(grant.issued_at), "issued_by_operator": row["issued_by_operator"],
            "store_sequence": int(row["store_sequence"]),
            "revoked_at": _iso(_parse(row["revoked_at"])) if row["revoked_at"] else None,  # type: ignore[arg-type]
            "revocation_reason": row["revocation_reason"],
        }

    # -- issuance -------------------------------------------------------------------

    def _request(self, data: dict[str, Any], now: datetime) -> dict[str, Any]:
        """The issuance request, checked for its shape and the NA's limits (400 refusals)."""
        unknown = sorted(set(data) - REQUEST_FIELDS)
        if unknown:
            raise BadRequestError("unknown grant request fields", code="unexpected_field", details={"fields": unknown})

        def bad(message: str, code: str = "invalid_grant_request", **details: Any) -> NoReturn:
            raise BadRequestError(message, code=code, details=details or None)

        bearer = data.get("bearer_key_id")
        if not isinstance(bearer, str) or not bearer:
            bad("bearer_key_id is required")
        capabilities = data.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities or not all(isinstance(c, str) for c in capabilities):
            bad("capabilities must be a non-empty list of capability IDs")
        if (data.get("agreement") is None) == (data.get("attestation_id") is None):
            bad("provide exactly one of agreement or attestation_id", code="ambiguous_basis")
        attestation_id = data.get("attestation_id")
        if attestation_id is not None and (not isinstance(attestation_id, str) or not attestation_id):
            bad("attestation_id must be a non-empty string")
        freshness = data.get("context_freshness_seq", 0)
        if isinstance(freshness, bool) or not isinstance(freshness, int) or freshness < 0:
            bad("context_freshness_seq must be an integer of 0 or more")
        if freshness and attestation_id is not None:
            bad("context_freshness_seq applies to an agreement basis only")
        valid_until = rfc3339(data.get("valid_until"))
        if valid_until is None:
            bad("valid_until is required, as an RFC 3339 time with an offset (Z for UTC)", code="invalid_grant_validity")
        valid_from = now if data.get("valid_from") is None else rfc3339(data.get("valid_from"))
        if valid_from is None:
            bad("valid_from must be an RFC 3339 time with an offset (Z for UTC)", code="invalid_grant_validity")
        valid_from, valid_until = valid_from.astimezone(timezone.utc), valid_until.astimezone(timezone.utc)
        if valid_from >= valid_until:
            bad("valid_from must be earlier than valid_until", code="invalid_grant_validity")
        if valid_from < now - GRANT_CLOCK_SKEW or valid_from > now + GRANT_MAX_VALIDITY:
            bad("valid_from must lie between now (within the clock skew) and 24 hours from now",
                code="invalid_grant_validity")
        max_uses = data.get("max_uses")
        if isinstance(max_uses, bool) or not isinstance(max_uses, int) or max_uses < 1:
            bad("max_uses (the grant's budget) is required: a positive integer")
        per_token = data.get("max_uses_per_time_token", min(self.limits.max_uses_per_time_token, max_uses))
        if isinstance(per_token, bool) or not isinstance(per_token, int) or per_token < 1:
            bad("max_uses_per_time_token must be a positive integer")
        validity = int((valid_until - valid_from).total_seconds())
        for name, value, limit, setting in (
            ("validity", validity, self.limits.max_validity_seconds, "NA_GRANT_MAX_VALIDITY_SECONDS"),
            ("max_uses", max_uses, self.limits.max_uses, "NA_GRANT_MAX_USES"),
            ("max_uses_per_time_token", per_token, self.limits.max_uses_per_time_token,
             "NA_GRANT_MAX_USES_PER_TIME_TOKEN"),
        ):
            if value > limit:
                raise BadRequestError(f"{name} {value} is over this NA's limit of {limit} ({setting})",
                                      code="grant_limit_exceeded", details={"limit": name, "maximum": limit})
        raw_envelope = data.get("parameter_envelope", {})
        if not isinstance(raw_envelope, dict):
            bad("parameter_envelope must be an object of parameter names", code="invalid_grant_envelope")
        try:
            envelope = {str(name): EnvelopeParameter.model_validate(spec) for name, spec in raw_envelope.items()}
        except PydanticValidationError as exc:
            raise BadRequestError("invalid parameter envelope", code="invalid_grant_envelope",
                                  details={"errors": _summarise(exc)}) from exc
        return {"bearer_key_id": bearer, "capabilities": list(capabilities), "attestation_id": attestation_id,
                "agreement": data.get("agreement"), "context_freshness_seq": freshness, "valid_from": valid_from,
                "valid_until": valid_until, "max_uses": max_uses, "max_uses_per_time_token": per_token,
                "parameter_envelope": envelope}

    def _bearer(self, key_id: str) -> Any:
        row = self._db.get_executor_key(key_id)
        if row is None:
            raise ValidationError("the bearer key is not a registered executor key", code="grant_bearer_key_unknown")
        key = self._store.key_from_row(row)
        if key.role != "executor":
            raise ValidationError(f"the bearer key is an {key.role} key, not an executor key",
                                  code="grant_bearer_key_not_executor")
        if key.retired:
            raise ValidationError("the bearer key is retired", code="grant_bearer_key_retired")
        return key

    def _basis(self, request: dict[str, Any]) -> GrantBasis:
        own = self._na.genesis_block.network_name
        if request["attestation_id"] is not None:
            assessed, _ = self._na.boundary_policies.assess_attestation(request["attestation_id"], None)
            return GrantBasis.of_attestation(assessed, own)
        raw = request["agreement"]
        try:
            agreement = AgreementRecord.model_validate(raw)
        except PydanticValidationError as exc:
            raise BadRequestError("Invalid agreement object", code="invalid_agreement") from exc
        self._na.agreements.require_trusted(agreement, route="/admin/grants", raw=raw)
        return GrantBasis.of_agreement(agreement, context_freshness_seq=request["context_freshness_seq"])

    def _check(self, *, capabilities: list[str], envelope: dict[str, EnvelopeParameter], valid_from: datetime,
               valid_until: datetime, basis: GrantBasis, check_basis: bool = True) -> GrantCheck:
        loaded = self._db.load_active_boundary_policies()
        return check_grant(
            capabilities=capabilities, envelope=envelope, valid_from=valid_from, valid_until=valid_until, basis=basis,
            policies=loaded.policies, registry=self._na.gate_registry,
            policy_public_keys=self._na.boundary_policies.policy_public_keys(),
            integrity_failures=loaded.integrity_failures, check_basis=check_basis,
        )

    def issue(self, data: dict[str, Any], issued_by: str) -> dict[str, Any]:
        """``POST /admin/grants``: check and sign a grant, store it, and give its first time token."""
        self.require_enabled()
        now = self._now()
        request = self._request(data, now)
        bearer = self._bearer(request["bearer_key_id"])
        basis = self._basis(request)
        check = self._check(capabilities=request["capabilities"], envelope=request["parameter_envelope"],
                            valid_from=request["valid_from"], valid_until=request["valid_until"], basis=basis)
        if not check.allowed:
            problems = [p.to_dict() for p in check.problems]
            self._db.add_audit_event("grant_refused", {
                "bearer_key_id": bearer.key_id, "capabilities": request["capabilities"], "reason": check.reason,
                "problems": problems[:20], "requested_by": issued_by,
            })
            raise ValidationError(f"the grant cannot be issued: {check.problems[0].detail}"[:1024],
                                  code=check.reason or "grant_gate_may_deny", details={"problems": problems})
        try:
            grant = self._sign(CapabilityGrant(
                bearer_key_id=bearer.key_id, bearer_public_key=bearer.public_key,
                bearer_sovereign_id=bearer.executor_sovereign_id, capabilities=request["capabilities"],
                basis_kind=basis.kind, basis_id=basis.basis_id, basis_digest=basis.digest,
                requester_sovereign_id=basis.requester_sovereign_id, provider_sovereign_id=basis.provider_sovereign_id,
                valid_from=request["valid_from"], valid_until=request["valid_until"], max_uses=request["max_uses"],
                max_uses_per_time_token=request["max_uses_per_time_token"],
                parameter_envelope=request["parameter_envelope"], basis_checks=check.basis_checks,
                policy_binding=check.binding(), issued_at=now, **self._issuer(),
            ))
        except PydanticValidationError as exc:
            raise BadRequestError("invalid grant", code="invalid_grant_request",
                                  details={"errors": _summarise(exc)}) from exc
        token = self._sign(TimeToken(grant_id=grant.grant_id, use_sequence=0, issued_at=now, **self._issuer()))
        policies = [(p.policy_id, p.version) for p in grant.policy_binding.policies]

        def make(db: Any) -> list[Any]:
            head, _ = db.store_head()
            db.insert_grant({
                "grant_id": grant.grant_id, "grant_json": json.dumps(grant.to_wire(), sort_keys=True,
                                                                     separators=(",", ":")),
                "grant_digest": grant.digest(), "bearer_key_id": grant.bearer_key_id,
                "bearer_sovereign_id": grant.bearer_sovereign_id, "basis_kind": grant.basis_kind,
                "basis_id": grant.basis_id, "valid_from": stamp(grant.valid_from),
                "valid_until": stamp(grant.valid_until), "issued_at": stamp(grant.issued_at),
                "issued_by_operator": issued_by, "store_sequence": head + 1,
            }, policies)
            return [self._pending("grant", grant, now)]

        entries = self._write(make, "The grant could not be stored")
        self._db.add_audit_event("grant_issued", {
            "grant_id": grant.grant_id, "bearer_key_id": grant.bearer_key_id, "capabilities": grant.capabilities,
            "basis_kind": grant.basis_kind, "basis_id": grant.basis_id, "valid_from": _iso(grant.valid_from),
            "valid_until": _iso(grant.valid_until), "max_uses": grant.max_uses,
            "policies": [f"{p}@{v}" for p, v in policies], "store_sequence": entries[0].store_sequence,
            "issued_by": issued_by,
        })
        return {"grant": grant.to_wire(), "time_token": token.to_wire(),
                "entry": entries[0].model_dump(mode="json"), "entry_digest": entries[0].digest()}

    def _write(self, make: Any, unavailable: str) -> list[EvidenceStoreEntry]:
        try:
            entries: list[EvidenceStoreEntry] = self._db.append_evidence_entries_with(make)
        except (_Refused, _AlreadyRevoked, *self._db.integrity_errors):
            raise
        except self._db.database_errors as exc:
            logger.warning("grant store write failed: %s", exc)
            raise ServiceUnavailableError(unavailable, code="evidence_store_unavailable") from exc
        self._store.maybe_anchor()
        return entries

    # -- reading ---------------------------------------------------------------------

    def _row(self, grant_id: str) -> dict[str, Any]:
        row = self._db.get_grant_row(grant_id)
        if row is None:
            raise NotFoundError("unknown grant", code="grant_not_found")
        return dict(row)

    def get(self, grant_id: str) -> dict[str, Any]:
        """``GET /admin/grants/<id>``: the grant, its state, and its revocation."""
        self.require_enabled()
        row = self._row(grant_id)
        grant = self._grant(row)
        revocation = self._db.grant_revocation_entry(grant_id)
        return {**self.summary(row), "remaining_uses": max(0, grant.max_uses - int(row["uses"])),
                "grant": grant.to_wire(),
                "policy_versions": [{"policy_id": p, "version": v} for p, v in self._db.grant_policy_versions(grant_id)],
                "revocation": revocation["payload"] if revocation is not None else None}

    def list_grants(self, args: dict[str, str]) -> dict[str, Any]:
        """``GET /admin/grants``: grants, newest first (``status``, ``bearer_key_id``, ``limit``, ``before``)."""
        self.require_enabled()
        status = args.get("status") or None
        if status not in (None, "active", "expired", "revoked"):
            raise BadRequestError("status must be active, expired or revoked", code="invalid_grant_filter")
        try:
            limit = int(args.get("limit") or 100)
        except ValueError:
            raise BadRequestError("limit must be an integer", code="invalid_page") from None
        if not 1 <= limit <= LIST_LIMIT:
            raise BadRequestError(f"limit must be 1..{LIST_LIMIT}", code="invalid_page")
        before = args.get("before") or None
        now = self._now()
        rows = self._db.list_grant_rows(status=status, bearer_key_id=args.get("bearer_key_id") or None, now=now,
                                        after_issued_at=before, limit=limit)
        return {"grants": [self.summary(r, now) for r in rows],
                "next_before": rows[-1]["issued_at"] if len(rows) == limit else None}

    # -- revocation ------------------------------------------------------------------

    def revoke(self, grant_id: str, detail: Any, revoked_by: str) -> dict[str, Any]:
        """``POST /admin/grants/<id>/revoke``: an operator's revocation."""
        self.require_enabled()
        if detail is not None and (not isinstance(detail, str) or not 1 <= len(detail) <= 1024):
            raise BadRequestError("reason must be a string of 1 to 1024 characters", code="invalid_grant_revocation")
        row = self._row(grant_id)
        if row["revoked_at"]:
            raise ConflictError("the grant is already revoked", code="grant_already_revoked")
        try:
            body = self._revoke(row, "operator", detail, revoked_by)
        except _AlreadyRevoked:
            raise ConflictError("the grant is already revoked", code="grant_already_revoked") from None
        return {"grant_id": grant_id, "status": "revoked", "revocation": body["payload"], "entry": body["entry"],
                "entry_digest": body["entry_digest"]}

    def _revoke(self, row: dict[str, Any], reason: str, detail: str | None, revoked_by: str | None) -> dict[str, Any]:
        now = self._now()
        record = self._sign(GrantRevocationRecord(
            grant_id=row["grant_id"], grant_digest=row["grant_digest"], reason=reason,  # type: ignore[arg-type]
            detail=detail[:1024] if detail else None, revoked_by=revoked_by, revoked_at=now, **self._issuer(),
        ))

        def make(db: Any) -> list[Any]:
            if not db.mark_grant_revoked(row["grant_id"], now, reason, record.revocation_id):
                raise _AlreadyRevoked()
            return [self._pending("grant_revocation", record, now)]

        entries = self._write(make, "The revocation could not be stored")
        self._db.add_audit_event("grant_revoked", {
            "grant_id": row["grant_id"], "reason": reason, "detail": detail, "revoked_by": revoked_by,
            "revocation_id": record.revocation_id, "store_sequence": entries[0].store_sequence,
        })
        return self._body(entries[0], record.to_wire())

    def _revoke_quietly(self, row: dict[str, Any], reason: str, detail: str) -> bool:
        """An automatic revocation; a failure is logged (``ensure_grants`` repeats it at start)."""
        try:
            self._revoke(row, reason, detail, None)
            return True
        except _AlreadyRevoked:
            return False
        except Exception as exc:  # noqa: BLE001 -- the change that caused it is already made
            logger.error("could not revoke grant %s (%s): %s", row["grant_id"], reason, exc)
            return False

    def on_attestation_revoked(self, attestation_id: str) -> int:
        """Revoke the usable grants resting on a revoked attestation. Returns how many."""
        if not self.enabled:
            return 0
        rows = [r for r in self._db.usable_grant_rows(self._now())
                if r["basis_kind"] == "attestation" and r["basis_id"] == attestation_id]
        return sum(self._revoke_quietly(r, "attestation_revoked", f"attestation {attestation_id} was revoked")
                   for r in rows)

    def on_key_retired(self, key_id: str) -> int:
        """Revoke the usable grants a retired key bears."""
        if not self.enabled:
            return 0
        rows = [r for r in self._db.usable_grant_rows(self._now()) if r["bearer_key_id"] == key_id]
        return sum(self._revoke_quietly(r, "bearer_key_retired", f"bearer key {key_id} was retired") for r in rows)

    def on_policy_deactivated(self, policy_id: str, version: int) -> int:
        """Revoke the usable grants bound to a policy version that is no longer active."""
        if not self.enabled:
            return 0
        rows = self._db.grants_bound_to(policy_id, version, self._now())
        return sum(self._revoke_quietly(r, "policy_deactivated", f"{policy_id} v{version} was deactivated")
                   for r in rows)

    def on_policy_activated(self, policy: BoundaryPolicy, previous_version: int | None) -> int:
        """After an activation: the version it replaced is deactivated, and every usable grant the policy
        may cover is checked again over the rest of its validity; a grant it may deny is revoked."""
        if not self.enabled:
            return 0
        revoked = 0
        if previous_version is not None and previous_version != policy.version:
            revoked += self.on_policy_deactivated(policy.policy_id, previous_version)
        from ...trust.grants import capability_matches

        for row in self._db.usable_grant_rows(self._now()):
            grant = self._grant(row)
            if policy.selector.capabilities and not any(
                    capability_matches(p, c) for p in policy.selector.capabilities for c in grant.capabilities):
                continue
            revoked += self._recheck(row, grant, "policy_activated",
                                     f"activating {policy.policy_id} v{policy.version}")
        return revoked

    def _recheck(self, row: dict[str, Any], grant: CapabilityGrant, reason: str, cause: str) -> int:
        """Check a usable grant again under the active policies, over the rest of its validity."""
        now = self._now()
        attestation = None
        if grant.basis_kind == "attestation":
            attestation, _ = self._na.boundary_policies.assess_attestation(grant.basis_id, None)
        basis = GrantBasis(grant.basis_kind, grant.basis_id, grant.basis_digest, grant.requester_sovereign_id,
                           grant.provider_sovereign_id, attestation=attestation)
        start = max(now, grant.valid_from)
        if start >= grant.valid_until:
            return 0
        check = self._check(capabilities=list(grant.capabilities), envelope=dict(grant.parameter_envelope),
                            valid_from=start, valid_until=grant.valid_until, basis=basis, check_basis=False)
        if check.allowed:
            return 0
        return int(self._revoke_quietly(row, reason, f"{cause}: {check.problems[0].reason}: "
                                                     f"{check.problems[0].detail}"))

    def ensure_grants(self) -> None:
        """At start: revoke usable grants whose bound policy versions are no longer active, whose basis
        attestation is revoked or whose bearer key is retired, and check the rest again under the
        active policies (a revocation an interrupted request missed is made now)."""
        if not self.enabled:
            return
        try:
            active = self._db.active_boundary_policy_versions()
            for row in self._db.usable_grant_rows(self._now()):
                grant = self._grant(row)
                key = self._db.get_executor_key(grant.bearer_key_id)
                if key is None or key["retired_at"] is not None:
                    self._revoke_quietly(row, "bearer_key_retired", f"bearer key {grant.bearer_key_id} was retired")
                    continue
                stale = [(p.policy_id, p.version) for p in grant.policy_binding.policies
                         if active.get(p.policy_id, (None, None))[0] != p.version]
                if stale:
                    self._revoke_quietly(row, "policy_deactivated",
                                         f"{stale[0][0]} v{stale[0][1]} is no longer active")
                    continue
                if grant.basis_kind == "attestation":
                    stored = self._db.get_membership_attestation(grant.basis_id)
                    if stored is None or stored["status"] != "active":
                        self._revoke_quietly(row, "attestation_revoked", f"attestation {grant.basis_id} was revoked")
                        continue
                self._recheck(row, grant, "policy_activated", "the policies active at start")
        except Exception as exc:  # noqa: BLE001 -- start must not fail on this; it runs again next start
            logger.error("checking grants at start failed: %s", exc)

    # -- the revocation feed ------------------------------------------------------------

    def feed_revocations(self) -> tuple[list[str], int] | None:
        """(revoked grants not yet past their end, revocations ever made) for the revocation feed, or None
        with the records off (the feed keeps its 1.5 form)."""
        if not self.enabled:
            return None
        return self._db.revoked_grant_ids(self._now()), self._db.grant_revocation_count()

    # -- time tokens ------------------------------------------------------------------

    def issue_time_token(self, raw: Any) -> dict[str, Any]:
        """``POST /grants/time-tokens``: a time token for a request signed by the grant's bearer key."""
        self.require_enabled()
        if not isinstance(raw, dict):
            raise BadRequestError("request must be an object", code="invalid_time_token_request")
        try:
            request = TimeTokenRequest.model_validate(raw)
        except PydanticValidationError as exc:
            raise ValidationError("the request does not match the TimeTokenRequest model",
                                  code="time_token_request_malformed", details={"errors": _summarise(exc)}) from exc
        difference = _exact_form_problem(raw, request)
        if difference is not None:
            raise ValidationError(f"the request is not in its exact serialized form: {difference}",
                                  code="time_token_request_malformed")
        row = self._row(request.grant_id)
        grant = self._grant(row)
        sig = request.signature
        if sig is None or sig.key_id != grant.bearer_key_id \
                or not verify_model_signature(request, sig, grant.bearer_public_key):
            raise ValidationError("the request is not signed by the grant's bearer key",
                                  code="time_token_request_invalid_signature")
        now = self._now()
        if abs(request.requested_at - now) > GRANT_CLOCK_SKEW:
            raise ValidationError("requested_at is not within the clock skew of the NA's clock",
                                  code="time_token_request_stale")
        key = self._db.get_executor_key(grant.bearer_key_id)
        if key is None or key["retired_at"] is not None:
            raise ConflictError("the grant's bearer key is retired", code="grant_bearer_key_retired")
        state = self.status_of(row, now)
        if state == "revoked":
            raise ConflictError("the grant is revoked", code="grant_revoked")
        if state == "expired":
            raise ConflictError("the grant has ended: a holder falls back to break-glass", code="grant_expired")
        if state == "exhausted":
            raise ConflictError("the grant's budget is spent", code="grant_budget_exhausted")
        admitted = int(row["uses"])
        if request.use_sequence < admitted:
            raise ConflictError(f"the NA admitted {admitted} uses of this grant; the request reports "
                                f"{request.use_sequence}", code="time_token_request_behind")
        if 1 <= request.use_sequence <= admitted:
            stored = self._db.grant_use_entry(request.grant_id, request.use_sequence)
            digest = GrantExecutionEvidence.model_validate(stored["payload"]).digest() if stored else None
            if digest != request.use_head_digest:
                raise ConflictError(f"use {request.use_sequence} the NA admitted is not the one the request names",
                                    code="time_token_request_mismatch")
        token = self._sign(TimeToken(grant_id=grant.grant_id, use_sequence=request.use_sequence,
                                     use_head_digest=request.use_head_digest, issued_at=now, **self._issuer()))
        self._db.add_audit_event("grant_time_token_issued", {
            "grant_id": grant.grant_id, "time_token_id": token.time_token_id, "use_sequence": request.use_sequence,
        })
        return {"time_token": token.to_wire()}

    # -- uses ---------------------------------------------------------------------------

    def _refuse(self, code: str, detail: str, use: GrantExecutionEvidence | None, digest: str,
                raw: dict[str, Any] | None = None) -> NoReturn:
        quarantine_id: str | None = None
        if raw is not None and use is not None and code in QUARANTINED_USE_CODES:
            try:
                stored = self._na.out_of_band_service.quarantine("grant_execution", raw, code, detail, use.resource_id)
                quarantine_id = str(stored["payload"]["quarantine_id"])
            except Exception as exc:  # noqa: BLE001 -- the refusal itself must still be returned
                logger.warning("could not quarantine refused grant use: %s", exc)
        self._db.add_evidence_rejection(
            code, submitted_digest=digest, evidence_id=use.use_id if use else None, decision_id=None,
            resource_id=use.resource_id if use else None,
            executor_sovereign_id=use.executor_sovereign_id if use else None,
        )
        self._db.add_audit_event("grant_use_rejected", {
            "code": code, "submitted_digest": digest, "use_id": use.use_id if use else None,
            "grant_id": use.grant_id if use else None, "quarantine_id": quarantine_id,
        })
        error = ConflictError if code == "grant_use_conflict" else ValidationError
        raise error(detail, code=code, details={"quarantine_id": quarantine_id} if quarantine_id else None)

    def submit_use(self, raw: Any) -> tuple[dict[str, Any], int]:
        """``POST /evidence/grant-executions``: admit one use. Returns (body, HTTP status)."""
        self.require_enabled()
        if not isinstance(raw, dict):
            raise BadRequestError("evidence must be an object", code="invalid_grant_use")
        digest = payload_digest(raw)
        try:
            use = GrantExecutionEvidence.model_validate(raw)
        except PydanticValidationError as exc:
            self._refuse("grant_use_malformed", "the use does not match the GrantExecutionEvidence model: "
                         f"{exc.errors()[0].get('msg', '')}", None, digest)
        difference = _exact_form_problem(raw, use)
        if difference is not None:
            self._refuse("grant_use_malformed", f"the use is not in its exact serialized form: {difference}", use,
                         digest)
        row = self._db.get_grant_row(use.grant_id)
        if row is None:
            self._refuse("grant_not_found", f"grant {use.grant_id!r} is not stored", use, digest)
        grant = self._grant(row)
        sig = use.signature
        if sig is None or sig.key_id != grant.bearer_key_id \
                or not verify_model_signature(use, sig, grant.bearer_public_key):
            self._refuse("grant_use_invalid_signature", "the use is not signed by the grant's bearer key", use, digest)
        # Authentic from here: a refusal no retry overcomes keeps the use as a quarantine entry.
        if use.executor_sovereign_id != grant.bearer_sovereign_id:
            self._refuse("grant_bearer_mismatch", f"executor {use.executor_sovereign_id!r} is not the grant's "
                         f"bearer {grant.bearer_sovereign_id!r}", use, digest, raw)
        secret = use_secret_problem(use)
        if secret is not None:
            self._refuse("grant_use_secret_material", secret, use, digest)
        key = self._db.get_executor_key(grant.bearer_key_id)
        if key is None or key["retired_at"] is not None:
            self._refuse("grant_bearer_key_retired", "the grant's bearer key is retired", use, digest, raw)
        if use.grant_digest != row["grant_digest"]:
            self._refuse("grant_mismatch", "grant_digest is not the stored grant's digest", use, digest, raw)
        existing = self._db.get_entry_by_record("grant_execution", use.use_id)
        if existing is not None:
            if existing["entry"].payload_digest != digest:
                self._refuse("grant_use_conflict", "a different use with this use_id is stored", use, digest, raw)
            return {**self._body(existing["entry"], existing["payload"]), "status": "duplicate"}, 200
        now = self._now()
        history = self._na.key_history.history()
        position: dict[str, int | None] = {"resource_sequence": None}

        def make(db: Any) -> list[Any]:
            current = db.get_grant_row(use.grant_id)
            admitted = int(current["uses"])
            if use.use_sequence > admitted + 1:
                raise _Refused("grant_use_chain_gap", f"use {use.use_sequence}, expected {admitted + 1}: upload the "
                                                      f"earlier uses first")
            if use.use_sequence < admitted + 1:
                raise _Refused("grant_use_conflict", f"use {use.use_sequence} of this grant is already recorded")
            if use.prev_use_digest != current["last_use_digest"]:
                raise _Refused("grant_use_chain_mismatch", "prev_use_digest is not the previous use's digest")
            previous = None
            if admitted:
                previous = PreviousUse(
                    digest=current["last_use_digest"], executed_at=_parse(current["last_use_executed_at"]),  # type: ignore[arg-type]
                    time_token_id=current["last_token_id"],
                    time_token_issued_at=_parse(current["last_token_issued_at"]),  # type: ignore[arg-type]
                    token_uses=int(current["last_token_uses"]))
            token = use.time_token
            head = None
            if 1 <= token.use_sequence <= admitted:
                stored = db.grant_use_entry(use.grant_id, token.use_sequence)
                if stored is not None:
                    held = GrantExecutionEvidence.model_validate(stored["payload"])
                    head = (held.digest(), held.executed_at)
            problem = use_problem(
                use, grant=grant, previous=previous, token_head=head,
                token_keys=na_keys_at(history, token.issued_at), raw_token=raw.get("time_token"),
                revoked_at=_parse(current["revoked_at"]), recorded_at=now)
            if problem is not None:
                raise _Refused(*problem)
            if use.resource_id is not None:
                head_state = self._store._resource_head(use.resource_id)
                position["resource_sequence"] = (head_state.resource_sequence + 1) if head_state else 1
            after = next_previous(use, use.digest(), previous)
            if not db.advance_grant_use(use.grant_id, admitted, {
                "uses": admitted + 1, "last_use_digest": after.digest, "last_use_executed_at": stamp(after.executed_at),
                "last_token_id": after.time_token_id, "last_token_issued_at": stamp(after.time_token_issued_at),
                "last_token_uses": after.token_uses,
            }):
                raise _Refused("grant_use_conflict", f"use {use.use_sequence} of this grant was recorded concurrently")
            version = use.execution_parameters.get("version_id")
            return [self._pending("grant_execution", use, now, resource_sequence=position["resource_sequence"],
                                  lookup={"version_id": version if isinstance(version, str) and version else None})]

        try:
            entries = self._write(make, "The use could not be stored")
        except _Refused as exc:
            self._refuse(exc.code, exc.detail, use, digest, raw if exc.code != "grant_use_chain_gap" else None)
        except self._db.integrity_errors:
            existing = self._db.get_entry_by_record("grant_execution", use.use_id)
            if existing is not None and existing["entry"].payload_digest == digest:
                return {**self._body(existing["entry"], existing["payload"]), "status": "duplicate"}, 200
            self._refuse("grant_use_conflict", "the use's position was taken by another record", use, digest, raw)
        self._db.add_audit_event("grant_use_recorded", {
            "use_id": use.use_id, "grant_id": use.grant_id, "use_sequence": use.use_sequence,
            "resource_id": use.resource_id, "resource_sequence": position["resource_sequence"],
            "store_sequence": entries[0].store_sequence,
        })
        return {**self._body(entries[0], use.to_wire()), "status": "recorded",
                "resource_sequence": position["resource_sequence"]}, 201

    # -- status -------------------------------------------------------------------------

    def counts(self) -> dict[str, Any]:
        """Additive fields for ``/admin/evidence/status``."""
        return self._db.grant_counts(self._now())

    @staticmethod
    def retention_horizon(grant_payload: dict[str, Any]) -> datetime:
        """The last time a use of a stored grant may still be admitted (retention keeps it until then)."""
        return grant_horizon(CapabilityGrant.model_validate(grant_payload))
