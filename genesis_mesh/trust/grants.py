"""Pre-issued capability grants (v1.6.0, Stage 5): issuance, envelopes and uses.

Pure functions only. The Network Authority loads stored state, passes it in
with the clock, and appends what these return; nothing here performs I/O.

Issuance (``check_grant``)
    The NA evaluates the active policies over the grant's whole parameter
    envelope and validity, and refuses when any enforce-mode gate could deny
    or cannot be decided. Decidable over a range: ``max_value.v1`` and
    ``min_value.v1`` over typed numeric ranges (booleans are never numbers,
    exclusive bounds are respected, comparisons are exact), ``allowlist.v1``
    and ``denylist.v1`` over finite, type-strict sets, ``scope_membership.v1``
    when the envelope's set is a subset, ``required_parameter.v1`` when the
    parameter is required and never null, ``boolean_required.v1`` when the
    parameter is pinned, ``time_window.v1`` when the whole validity lies in
    the window, and ``attestation_claim.v1`` under the pinned attestation of
    the grant's basis. A gate or selector reading ``attributes.*``,
    ``context_freshness_seq`` or (outside ``time_window.v1``) ``requested_at``,
    and a gate type outside these nine, cannot be decided. A gate on a fact
    the grant fixes (the capability, the parties, the basis, the parent kind
    ``grant``, the attestation's facts) is evaluated on that one value.
    The grant's validity must lie within every applied policy's validity,
    with no policy scheduled to start inside it; a policy that requires
    review applies to no grant. Observe-mode gates never refuse a grant:
    their outcomes are recorded in it.
Uses (``use_problem``)
    A use is checked against its grant, the use chain, its time token and
    the grant's revocation, in one order every implementation follows; the
    NA and the export verifier run the same checks with what each holds.

A grant evaluates as ``parent_kind`` ``grant``: a gate on ``parent_kind``
sees ``grant``, and a policy selects grants with ``parent_kinds: ["grant"]``.
A selector naming the kind of the grant's basis (``attestation``, or
``agreement`` and ``direct`` for an agreement) also applies to it, so a
policy written for requests under that basis covers the grants under it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from typing import Any, Iterable, Literal, Sequence

from ..crypto import sign_model, verify_model_signature
from ..models.agreement import AgreementRecord
from ..models.boundary_policy import AppliedPolicy, BoundaryPolicy, GateSpec, PolicySelector, policy_set_digest
from ..models.context import ContextRecord, GateResult
from ..models.grants import (
    GRANT_CLOCK_SKEW,
    CapabilityGrant,
    EnvelopeParameter,
    GrantExecutionEvidence,
    GrantGateOutcome,
    GrantPolicyBinding,
    GrantRevocationRecord,
    NumericRange,
    TimeToken,
    scalar_key,
)
from .context.attestation_basis import (
    AttestationBasis,
    attestation_capability_gate,
    attestation_freshness_gate,
)
from .context.gates import capability_gate, freshness_gate
from .context.policy import check_active_policy
from .context.registry import MISSING, GateRegistry, resolve_fact, scalar_equals
from genesis_mesh.crypto.signing import SigningKeyLike

#: The gate types a grant's envelope can be decided over (every other gate type cannot).
DECIDABLE_GATE_TYPES: frozenset[str] = frozenset({
    "required_parameter.v1", "max_value.v1", "min_value.v1", "allowlist.v1", "denylist.v1",
    "boolean_required.v1", "scope_membership.v1", "time_window.v1", "attestation_claim.v1",
})

#: The parent kind a grant evaluates as.
GRANT_PARENT_KIND = "grant"

#: Selector parent kinds that stand for a grant's basis (a policy written for them covers the grant).
BASIS_PARENT_KINDS: dict[str, frozenset[str]] = {
    "attestation": frozenset({"attestation"}),
    "agreement": frozenset({"agreement", "direct"}),
}

#: Why the NA refuses to issue a grant, in the order it checks (the first is the refusal's code).
GrantIssuanceRefusal = Literal[
    "grant_basis_invalid",
    "grant_outlives_basis",
    "grant_capability_out_of_scope",
    "grant_basis_not_fresh",
    "grant_policy_resolution_failed",
    "grant_review_required",
    "grant_policy_scheduled",
    "grant_outlives_policy",
    "grant_undecidable_attributes",
    "grant_undecidable_freshness",
    "grant_undecidable_time",
    "grant_undecidable_gate_type",
    "grant_gate_may_deny",
]

#: Why a use is refused at admission, in the order the NA checks (``use_problem`` and the checks
#: before it). Codes marked final in ``QUARANTINED_USE_CODES`` keep an authentic use as a quarantine
#: entry; the rest are refused outright (the holder retries, or the record is not authentic).
GrantUseRejectionCode = Literal[
    "grant_use_malformed",
    "grant_not_found",
    "grant_use_invalid_signature",
    "grant_bearer_mismatch",
    "grant_use_secret_material",
    "grant_bearer_key_retired",
    "grant_mismatch",
    "grant_use_conflict",
    "grant_use_chain_gap",
    "grant_use_chain_mismatch",
    "grant_capability_mismatch",
    "grant_envelope_mismatch",
    "grant_budget_exhausted",
    "grant_time_token_invalid",
    "grant_time_token_mismatch",
    "grant_time_token_regressed",
    "grant_time_token_exhausted",
    "grant_use_before_time_token",
    "grant_use_out_of_order",
    "grant_use_outside_validity",
    "grant_use_in_future",
    "grant_use_uploaded_late",
    "grant_revoked",
]

#: Refusals of an authentic use (its signature verifies with the grant's bearer key) that no later
#: attempt can overcome: the use already happened, so it is kept as a quarantine entry. Left out: a
#: use the chain does not reach yet (``grant_use_chain_gap``: the holder uploads the earlier ones
#: first) and one carrying secret material (never stored).
QUARANTINED_USE_CODES: frozenset[str] = frozenset({
    "grant_bearer_mismatch", "grant_bearer_key_retired", "grant_mismatch", "grant_use_conflict",
    "grant_use_chain_mismatch", "grant_capability_mismatch", "grant_envelope_mismatch", "grant_budget_exhausted",
    "grant_time_token_invalid", "grant_time_token_mismatch", "grant_time_token_regressed",
    "grant_time_token_exhausted", "grant_use_before_time_token", "grant_use_out_of_order",
    "grant_use_outside_validity", "grant_use_in_future", "grant_use_uploaded_late", "grant_revoked",
})


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Envelopes
# ---------------------------------------------------------------------------


def _is_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return not isinstance(value, float) or value == value and value not in (float("inf"), float("-inf"))


def _bounds(r: NumericRange) -> tuple[Fraction, bool, Fraction, bool]:
    """(lowest value, attained, highest value, attained) of a range; an integer range's ends are integers."""
    low, high = Fraction(r.minimum), Fraction(r.maximum)
    if r.number_type == "integer":
        first = low + 1 if r.exclusive_minimum else low
        last = high - 1 if r.exclusive_maximum else high
        return first, True, last, True
    return low, not r.exclusive_minimum, high, not r.exclusive_maximum


def in_range(value: Any, r: NumericRange) -> bool:
    """Whether a value is within a range: a number (never a boolean), integral for an integer range."""
    if not _is_number(value):
        return False
    v = Fraction(value)
    if r.number_type == "integer" and v.denominator != 1:
        return False
    low, low_in, high, high_in = _bounds(r)
    above = v > low or (v == low and low_in)
    below = v < high or (v == high and high_in)
    return above and below


def _range_values(r: NumericRange, limit: int) -> list[Fraction] | None:
    """Every value of a range when it holds at most ``limit`` (an integer range, or a single number)."""
    low, low_in, high, high_in = _bounds(r)
    if r.number_type == "integer":
        count = int(high - low) + 1
        return [low + i for i in range(count)] if count <= limit else None
    if low == high and low_in and high_in:
        return [low]
    return None


def parameter_value_problem(name: str, value: Any, spec: EnvelopeParameter) -> str | None:
    """Why one parameter value is outside its envelope parameter, or None."""
    if spec.one_of is not None:
        if value is not None and not isinstance(value, (str, bool)) and not _is_number(value):
            return f"request_parameters.{name} is not a scalar"
        keys = {scalar_key(v) for v in spec.one_of}
        return None if scalar_key(value) in keys else f"request_parameters.{name} is not one of its values"
    if spec.subset_of is not None:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return f"request_parameters.{name} is not a list of strings"
        allowed = set(spec.subset_of)
        return None if all(v in allowed for v in value) else f"request_parameters.{name} has an item outside its set"
    assert spec.number_range is not None
    if not in_range(value, spec.number_range):
        return f"request_parameters.{name} is outside its range"
    return None


def envelope_problem(envelope: dict[str, EnvelopeParameter], parameters: Any) -> str | None:
    """Why a use's ``request_parameters`` are outside the grant's closed envelope, or None.

    The envelope is closed: a parameter it does not name is refused. A required
    parameter must be present; a present one must be inside its parameter.
    """
    if not isinstance(parameters, dict):
        return "request_parameters is not an object"
    outside = sorted(k for k in parameters if k not in envelope)
    if outside:
        return "request_parameters." + outside[0] + " is not in the envelope"
    for name in sorted(envelope):
        spec = envelope[name]
        if name not in parameters:
            if spec.required:
                return f"request_parameters.{name} is required"
            continue
        problem = parameter_value_problem(name, parameters[name], spec)
        if problem is not None:
            return problem
    return None


# ---------------------------------------------------------------------------
# Deciding gates over an envelope
# ---------------------------------------------------------------------------

#: A gate's decision over a grant: (decision, undecidable reason or None, detail).
Decision = tuple[Literal["pass", "may_fail", "undecidable"], str | None, str]


def _undecidable_path(path: str) -> tuple[str, str] | None:
    """(reason, detail) when a fact path cannot be decided over a grant, or None."""
    root = path.split(".")[0]
    if root == "attributes":
        return ("grant_undecidable_attributes",
                f"{path}: a grant fixes no attributes; the facts and identifiers an external system supplies "
                "per request cannot be decided in advance")
    if root == "context_freshness_seq":
        return ("grant_undecidable_freshness",
                f"{path}: the holder's revocation snapshot changes over the grant's life")
    if root == "requested_at":
        return "grant_undecidable_time", f"{path}: each use has its own time; only time_window.v1 reads it"
    return None


def _envelope_parameter(path: str, envelope: dict[str, EnvelopeParameter]) -> tuple[str, EnvelopeParameter] | None:
    """The envelope parameter a path names directly (``request_parameters.<name>``), or None."""
    segments = path.split(".")
    if len(segments) == 2 and segments[0] == "request_parameters" and segments[1] in envelope:
        return segments[1], envelope[segments[1]]
    return None


def _numbers_only(spec: EnvelopeParameter) -> bool:
    return spec.number_range is not None or (spec.one_of is not None and all(_is_number(v) for v in spec.one_of))


def _values(spec: EnvelopeParameter, limit: int) -> list[Any] | None:
    """Every value a parameter may take when they are finitely many (at most ``limit`` for a range)."""
    if spec.one_of is not None:
        return list(spec.one_of)
    if spec.number_range is not None:
        found = _range_values(spec.number_range, limit)
        return [int(v) if v.denominator == 1 else v for v in found] if found is not None else None
    return None


def _bound_decision(spec: EnvelopeParameter, bound: Fraction, upper: bool, inclusive: bool) -> bool:
    """Whether every value of a numeric parameter satisfies ``value <= bound`` (``upper``) or ``>=``,
    strict when not ``inclusive``."""
    if spec.one_of is not None:
        values = [Fraction(v) for v in spec.one_of if isinstance(v, (int, float))]
        if upper:
            return all(v <= bound if inclusive else v < bound for v in values)
        return all(v >= bound if inclusive else v > bound for v in values)
    assert spec.number_range is not None
    low, low_in, high, high_in = _bounds(spec.number_range)
    if upper:
        return high < bound or (high == bound and (inclusive or not high_in))
    return low > bound or (low == bound and (inclusive or not low_in))


def _decide_parameter(gate_type: str, config: Any, name: str, spec: EnvelopeParameter,
                      facts: dict[str, Any] | None) -> tuple[bool, str]:
    """(passes for every value, detail) for a gate on ``request_parameters.<name>`` inside the envelope."""
    path = f"request_parameters.{name}"
    optional = not spec.required
    if gate_type == "required_parameter.v1":
        ok = not optional and not (spec.one_of is not None and any(v is None for v in spec.one_of))
        return ok, f"{path} is {'required and never null' if ok else 'optional or may be null'}"
    if optional:
        return False, f"{path} may be left out"
    if gate_type in ("max_value.v1", "min_value.v1"):
        if not _numbers_only(spec):
            return False, f"{path} may be something other than a number"
        upper = gate_type == "max_value.v1"
        bound = Fraction(config.max if upper else config.min)
        ok = _bound_decision(spec, bound, upper, config.inclusive)
        op = ("<=" if config.inclusive else "<") if upper else (">=" if config.inclusive else ">")
        return ok, f"every value of {path} {'satisfies' if ok else 'may violate'} {op} {config.max if upper else config.min}"
    if gate_type == "boolean_required.v1":
        ok = spec.one_of is not None and all(isinstance(v, bool) and v is config.expected for v in spec.one_of)
        return ok, f"{path} is {'pinned to' if ok else 'not pinned to'} {str(config.expected).lower()}"
    if gate_type == "scope_membership.v1":
        ok = spec.subset_of is not None and set(spec.subset_of) <= set(config.allowed)
        return ok, f"every item of {path} {'is' if ok else 'may not be'} within the allowed scope"
    if gate_type in ("allowlist.v1", "denylist.v1", "attestation_claim.v1"):
        if gate_type == "attestation_claim.v1":
            claims = (facts or {}).get("claims") if facts is not None else None
            allowed = claims.get(config.claim, MISSING) if isinstance(claims, dict) else MISSING
            if facts is None:
                return False, "the grant has no attestation basis"
            if allowed is MISSING or not isinstance(allowed, list):
                return False, f"the attestation has no list claim {config.claim!r}"
            listed = list(allowed)
        else:
            listed = list(config.values)
        if spec.subset_of is not None:
            return False, f"{path} is a list, not a scalar"
        keys = {scalar_key(v) for v in listed if v is None or isinstance(v, (str, bool)) or _is_number(v)}
        if gate_type == "denylist.v1":
            if spec.one_of is not None:
                ok = not any(scalar_key(v) in keys for v in spec.one_of)
            else:
                assert spec.number_range is not None
                ok = not any(in_range(v, spec.number_range) for v in listed)
            return ok, f"{path} {'never takes' if ok else 'may take'} a denied value"
        values = _values(spec, len(keys))
        ok = values is not None and all(scalar_key(v) in keys for v in values)
        where = f"attestation claim {config.claim!r}" if gate_type == "attestation_claim.v1" else "the allowlist"
        return ok, f"every value of {path} {'is' if ok else 'may not be'} in {where}"
    return False, f"{gate_type} is not decided over a parameter"


def _decide_time_window(config: Any, valid_from: datetime, valid_until: datetime) -> tuple[bool, str]:
    """Whether every instant of ``[valid_from, valid_until]`` lies inside a time window."""
    start, end = _utc(valid_from).astimezone(timezone.utc), _utc(valid_until).astimezone(timezone.utc)
    failures: list[str] = []
    if config.not_before is not None and start < config.not_before:
        failures.append("starts before not_before")
    if config.not_after is not None and end > config.not_after:
        failures.append("ends after not_after")
    if config.weekdays is not None or config.utc_hour_start is not None:
        day = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while day <= end:
            seg_start = max(start, day)
            seg_end = min(end, day + timedelta(days=1) - timedelta(microseconds=1))
            if config.weekdays is not None and day.isoweekday() not in config.weekdays:
                failures.append(f"{day.date().isoformat()} is not a permitted weekday")
                break
            if config.utc_hour_start is not None and config.utc_hour_end is not None and (
                    seg_start.hour < config.utc_hour_start or seg_end.hour >= config.utc_hour_end):
                failures.append(f"{day.date().isoformat()} reaches outside the permitted hours")
                break
            day += timedelta(days=1)
    window = f"[{_iso(valid_from)}, {_iso(valid_until)}]"
    if failures:
        return False, f"the validity {window} {', '.join(failures)}"
    return True, f"the validity {window} lies inside the window"


def decide_gate(
    gate: GateSpec, registry: GateRegistry, context: ContextRecord, envelope: dict[str, EnvelopeParameter],
    valid_from: datetime, valid_until: datetime,
) -> Decision:
    """How one gate is decided over a grant: for every request the envelope permits, at every time
    of its validity."""
    from .context.policy import _evaluate_one

    gate_type = registry.get(gate.gate_type)
    if gate.gate_type not in DECIDABLE_GATE_TYPES or gate_type is None:
        return ("undecidable", "grant_undecidable_gate_type",
                f"{gate.gate_type} is not decided over a range of requests")
    try:
        config = gate_type.config_model.model_validate(gate.config)
    except ValueError:
        return "may_fail", None, "the gate's configuration is invalid"
    if gate.gate_type == "time_window.v1":
        ok, detail = _decide_time_window(config, valid_from, valid_until)
        return ("pass" if ok else "may_fail"), None, detail
    path: str = getattr(config, "path")
    undecidable = _undecidable_path(path)
    if undecidable is not None:
        return "undecidable", undecidable[0], undecidable[1]
    parameter = _envelope_parameter(path, envelope)
    if parameter is not None:
        ok, detail = _decide_parameter(gate.gate_type, config, parameter[0], parameter[1],
                                       context.attestation_facts)
        return ("pass" if ok else "may_fail"), None, detail
    # A fact the grant fixes (or one no use can carry): the gate has one outcome for every use.
    outcome = _evaluate_one(gate, context, registry)
    if outcome.passed:
        return "pass", None, outcome.detail
    return "may_fail", None, f"fails for every use: {outcome.detail}"


# ---------------------------------------------------------------------------
# Selectors over an envelope
# ---------------------------------------------------------------------------


def capability_matches(pattern: str, capability: str) -> bool:
    """Whether a selector's capability pattern (an exact ID, or ``prefix.*``) names a capability."""
    if pattern.endswith(".*"):
        return capability.startswith(pattern[:-1])
    return capability == pattern


def _restrict(spec: EnvelopeParameter, allowed: Sequence[Any]) -> EnvelopeParameter | None:
    """The part of a parameter a selector's values select (a required one_of), or None for none."""
    keys = {scalar_key(a) for a in allowed if a is None or isinstance(a, (str, bool)) or _is_number(a)}
    if spec.one_of is not None:
        kept = [v for v in spec.one_of if scalar_key(v) in keys]
    elif spec.number_range is not None:
        kept = []
        for a in allowed:
            if in_range(a, spec.number_range):
                value = Fraction(a)
                kept.append(int(value) if value.denominator == 1 else a)
        kept = [v for i, v in enumerate(kept) if scalar_key(v) not in {scalar_key(k) for k in kept[:i]}]
    else:
        return None  # a list never equals a scalar
    if not kept:
        return None
    return EnvelopeParameter(required=True, one_of=kept)


def selector_scope(
    selector: PolicySelector, capability: str, context: ContextRecord, envelope: dict[str, EnvelopeParameter],
    basis_kind: str,
) -> tuple[Literal["none", "applies", "undecidable"], dict[str, EnvelopeParameter] | None, tuple[str, str] | None]:
    """Whether a policy's selector applies to a grant's requests for one capability.

    ``("applies", envelope)``: it applies to the part of the envelope its
    ``parameter_equals`` selects; ``("none", ...)``: to no request the grant
    permits; ``("undecidable", None, (reason, detail))``: it reads a fact the
    grant cannot fix.
    """
    if selector.capabilities and not any(capability_matches(p, capability) for p in selector.capabilities):
        return "none", None, None
    for listed, value in ((selector.requester_sovereign_ids, context.requester_sovereign_id),
                          (selector.provider_sovereign_ids, context.provider_sovereign_id),
                          (selector.agreement_ids, context.agreement_id)):
        if listed and value not in listed:
            return "none", None, None
    if selector.parent_kinds and not ({GRANT_PARENT_KIND, *BASIS_PARENT_KINDS.get(basis_kind, ())}
                                      & set(selector.parent_kinds)):
        return "none", None, None
    restricted = dict(envelope)
    for path, allowed in sorted(selector.parameter_equals.items()):
        undecidable = _undecidable_path(path)
        if undecidable is not None:
            return "undecidable", None, undecidable
        parameter = _envelope_parameter(path, restricted)
        if parameter is not None:
            narrowed = _restrict(parameter[1], allowed)
            if narrowed is None:
                return "none", None, None
            restricted[parameter[0]] = narrowed
            continue
        value = resolve_fact(context, path)
        if value is MISSING or not any(scalar_equals(value, a) for a in allowed):
            return "none", None, None
    return "applies", restricted, None


# ---------------------------------------------------------------------------
# Issuance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GrantBasis:
    """What a grant rests on, as the NA checked it: an agreement it trusts, or an attestation it issued."""

    kind: Literal["agreement", "attestation"]
    basis_id: str
    digest: str
    requester_sovereign_id: str
    provider_sovereign_id: str
    agreement: AgreementRecord | None = None
    attestation: AttestationBasis | None = None
    context_freshness_seq: int = 0

    @classmethod
    def of_agreement(cls, agreement: AgreementRecord, *, context_freshness_seq: int = 0) -> "GrantBasis":
        digest = hashlib.sha256(agreement.to_canonical_json().encode("utf-8")).hexdigest()
        return cls("agreement", agreement.agreement_id, digest, agreement.responder_sovereign_id,
                   agreement.offerer_sovereign_id, agreement=agreement, context_freshness_seq=context_freshness_seq)

    @classmethod
    def of_attestation(cls, basis: AttestationBasis, provider_sovereign_id: str) -> "GrantBasis":
        att = basis.attestation
        digest = att.digest() if att is not None else "0" * 64
        subject = att.subject_id if att is not None else basis.attestation_id
        return cls("attestation", basis.attestation_id, digest, subject, provider_sovereign_id, attestation=basis)

    def context(self, capability: str, at: datetime) -> ContextRecord:
        """The fixed facts of a grant's requests for one capability (``requested_at`` is ``at``)."""
        context = ContextRecord(
            context_id=f"grant:{self.basis_id}:{capability}", agreement_id=self.basis_id,
            parent_kind=GRANT_PARENT_KIND, requester_sovereign_id=self.requester_sovereign_id,
            provider_sovereign_id=self.provider_sovereign_id, requested_capability=capability,
            request_parameters={}, attributes={}, requested_at=at,
            context_freshness_seq=self.context_freshness_seq,
        )
        if self.attestation is not None:
            context = context.with_attestation_facts(self.attestation.facts())
        return context


@dataclass(frozen=True)
class GrantProblem:
    """One reason a grant cannot be issued (or must be revoked)."""

    reason: str
    detail: str
    capability: str | None = None
    policy_id: str | None = None
    policy_version: int | None = None
    gate_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"reason": self.reason, "detail": self.detail}
        for name in ("capability", "policy_id", "policy_version", "gate_id"):
            if getattr(self, name) is not None:
                out[name] = getattr(self, name)
        return out


@dataclass
class GrantCheck:
    """The outcome of checking a grant: problems (first is the refusal), and what it binds."""

    problems: list[GrantProblem] = field(default_factory=list)
    basis_checks: list[GateResult] = field(default_factory=list)
    applied: list[BoundaryPolicy] = field(default_factory=list)
    gate_outcomes: list[GrantGateOutcome] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return not self.problems

    @property
    def reason(self) -> str | None:
        return self.problems[0].reason if self.problems else None

    def binding(self) -> GrantPolicyBinding:
        applied = [AppliedPolicy(policy_id=p.policy_id, version=p.version, policy_digest=p.digest(),
                                 signed_by=p.signature.key_id if p.signature else "") for p in self.applied]
        return GrantPolicyBinding(
            policies=applied, policy_set_digest=policy_set_digest(applied), gate_outcomes=list(self.gate_outcomes),
            registry_gate_types=sorted({g.gate_type for p in self.applied for g in p.gates}),
        )


def _basis_checks(basis: GrantBasis, capabilities: Sequence[str], valid_from: datetime, valid_until: datetime,
                  check: GrantCheck) -> None:
    """The built-in checks at issuance, in the engine's order: the basis's status, its validity
    over the grant's whole validity, each capability, and freshness."""
    window = f"[{_iso(valid_from)}, {_iso(valid_until)}]"
    first = basis.context(capabilities[0], valid_from)
    if basis.attestation is not None:
        att_basis = basis.attestation
        ok = att_basis.status_failure is None
        check.basis_checks.append(GateResult(
            gate_name="attestation_status", passed=ok,
            detail=att_basis.status_detail if ok else f"{att_basis.status_failure}: {att_basis.status_detail}"))
        if not ok:
            check.problems.append(GrantProblem("grant_basis_invalid",
                                               f"{att_basis.status_failure}: {att_basis.status_detail}"))
        att = att_basis.attestation
        inside = att is not None and att.valid_from <= valid_from and valid_until <= att.expires_at
        span = f"[{_iso(att.valid_from)}, {_iso(att.expires_at)}]" if att is not None else "(no attestation)"
        check.basis_checks.append(GateResult(
            gate_name="attestation_validity", passed=inside,
            detail=f"the grant's validity {window} {'lies' if inside else 'does not lie'} within {span}"))
        if not inside:
            check.problems.append(GrantProblem("grant_outlives_basis",
                                               f"the grant's validity {window} is not within the attestation's {span}"))
        for capability in capabilities:
            result = attestation_capability_gate(att_basis, basis.context(capability, valid_from))
            check.basis_checks.append(result)
            if not result.passed:
                check.problems.append(GrantProblem("grant_capability_out_of_scope", result.detail, capability))
        check.basis_checks.append(attestation_freshness_gate(first))
        return
    assert basis.agreement is not None
    terms = basis.agreement.agreed_terms
    inside = terms.valid_from <= valid_from and valid_until <= terms.valid_until
    span = f"[{_iso(terms.valid_from)}, {_iso(terms.valid_until)}]"
    check.basis_checks.append(GateResult(
        gate_name="validity_window", passed=inside,
        detail=f"the grant's validity {window} {'lies' if inside else 'does not lie'} within the agreement's {span}"))
    if not inside:
        check.problems.append(GrantProblem("grant_outlives_basis",
                                           f"the grant's validity {window} is not within the agreement's {span}"))
    for capability in capabilities:
        result = capability_gate(basis.context(capability, valid_from), terms)
        check.basis_checks.append(result)
        if not result.passed:
            check.problems.append(GrantProblem("grant_capability_out_of_scope", result.detail, capability))
    fresh = freshness_gate(first, terms)
    check.basis_checks.append(fresh)
    if not fresh.passed:
        check.problems.append(GrantProblem("grant_basis_not_fresh", fresh.detail))


def check_grant(
    *,
    capabilities: Sequence[str],
    envelope: dict[str, EnvelopeParameter],
    valid_from: datetime,
    valid_until: datetime,
    basis: GrantBasis,
    policies: Sequence[BoundaryPolicy],
    registry: GateRegistry,
    policy_public_keys: Sequence[str],
    integrity_failures: Sequence[str] = (),
    check_basis: bool = True,
) -> GrantCheck:
    """Check a grant against its basis and the active policies (the module docstring lists the rules).

    ``policies`` is the full active set. Every problem is reported, in the
    order the reasons are listed in ``GrantIssuanceRefusal`` within each
    capability and policy; the first is the refusal's code. The NA runs the
    same check to re-check a grant when a policy is activated, over the rest
    of its validity, without the basis checks (``check_basis=False``: a
    revoked basis attestation revokes the grant by itself).
    """
    check = GrantCheck()
    if check_basis:
        _basis_checks(basis, capabilities, valid_from, valid_until, check)

    # The active set must be trustworthy before any selector is read (as in resolve_policies).
    ordered = sorted(policies, key=lambda p: (p.policy_id, p.version))
    failure: tuple[str, str] | None = None
    if integrity_failures:
        failure = ("policy_store_integrity_failed", ", ".join(integrity_failures))
    ids = [p.policy_id for p in ordered]
    for policy in ordered:
        if failure is not None:
            break
        if ids.count(policy.policy_id) > 1:
            failure = ("ambiguous_resolution", f"{policy.policy_id} v{policy.version}")
            break
        code = check_active_policy(policy, registry, policy_public_keys)
        if code is not None:
            failure = (code, f"{policy.policy_id} v{policy.version}")
    if failure is not None:
        check.problems.append(GrantProblem("grant_policy_resolution_failed",
                                           f"policy resolution failed: {failure[0]} ({failure[1]})"))
        return check

    applied: dict[tuple[str, int], BoundaryPolicy] = {}
    for capability in capabilities:
        context = basis.context(capability, valid_from)
        for policy in ordered:
            scope, restricted, why = selector_scope(policy.selector, capability, context, envelope, basis.kind)
            where: dict[str, Any] = {"capability": capability, "policy_id": policy.policy_id,
                                     "policy_version": policy.version}
            if scope == "none":
                continue
            if scope == "undecidable":
                assert why is not None
                check.problems.append(GrantProblem(why[0], f"the selector of {policy.policy_id} v{policy.version} "
                                                           f"reads {why[1]}", **where))
                continue
            if policy.valid_from > valid_from and policy.valid_from > valid_until:
                continue  # it starts after the grant ends
            assert restricted is not None
            applied[(policy.policy_id, policy.version)] = policy
            if policy.review_required or policy.emergency is not None:
                check.problems.append(GrantProblem(
                    "grant_review_required",
                    f"{policy.policy_id} v{policy.version} requires every change it allows to be reviewed", **where))
            if policy.valid_from > valid_from:
                check.problems.append(GrantProblem(
                    "grant_policy_scheduled",
                    f"{policy.policy_id} v{policy.version} starts at {_iso(policy.valid_from)}, inside the grant's "
                    f"validity", **where))
            elif policy.valid_until < valid_until:
                check.problems.append(GrantProblem(
                    "grant_outlives_policy",
                    f"{policy.policy_id} v{policy.version} is valid until {_iso(policy.valid_until)}, before the grant "
                    f"ends at {_iso(valid_until)}", **where))
            for gate in sorted(policy.gates, key=lambda g: g.order):
                decision, reason, detail = decide_gate(gate, registry, context, restricted, valid_from, valid_until)
                check.gate_outcomes.append(GrantGateOutcome(
                    capability=capability, policy_id=policy.policy_id, policy_version=policy.version,
                    gate_id=gate.gate_id, gate_type=gate.gate_type, mode=gate.mode, outcome=decision,
                    detail=detail[:1024]))
                if gate.mode != "enforce" or decision == "pass":
                    continue
                check.problems.append(GrantProblem(
                    reason or "grant_gate_may_deny", f"{policy.policy_id}/{gate.gate_id}: {detail}"[:1024],
                    gate_id=gate.gate_id, **where))
    check.applied = [applied[k] for k in sorted(applied)]
    return check


# ---------------------------------------------------------------------------
# Uses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PreviousUse:
    """The use before this one in the grant's chain, as the NA or a verifier holds it."""

    digest: str
    executed_at: datetime
    time_token_id: str
    time_token_issued_at: datetime
    #: How many uses up to and including this one cite its time token (they are consecutive).
    token_uses: int


def token_signature_valid(raw_token: Any, keys: Iterable[str]) -> bool:
    """Whether a time token, as received inside a use, carries a signature by one of ``keys``."""
    from ..models.canonical_registry import signed_as_received

    return isinstance(raw_token, dict) and signed_as_received("TimeToken", raw_token, list(keys))


def use_problem(
    use: GrantExecutionEvidence,
    *,
    grant: CapabilityGrant | None,
    previous: PreviousUse | None,
    token_head: tuple[str, datetime] | None,
    token_keys: Sequence[str],
    raw_token: Any,
    revoked_at: datetime | None,
    recorded_at: datetime | None,
) -> tuple[str, str] | None:
    """(code, detail) for the first rule a use breaks, or None (``GrantUseRejectionCode`` order).

    Run after the use's signature, bearer key, grant digest and chain position
    are checked. Each argument is what the caller holds: ``grant`` (None: the
    checks that need it are skipped), ``previous`` (the use before it in the
    chain, None for the first use or when it is not held), ``token_head`` (the
    digest and time of the use the time token names, when held),
    ``token_keys`` (the NA keys valid at the token's ``issued_at``),
    ``raw_token`` (the token as received), ``revoked_at`` (the grant's
    revocation recorded before the use) and ``recorded_at`` (the use's time in
    the store; None before it is stored).
    """
    token = use.time_token
    executed = _utc(use.executed_at)
    if grant is not None:
        if use.capability not in grant.capabilities:
            return "grant_capability_mismatch", f"{use.capability} is not one of the grant's capabilities"
        problem = envelope_problem(grant.parameter_envelope, use.request_parameters)
        if problem is not None:
            return "grant_envelope_mismatch", problem
        if use.use_sequence > grant.max_uses:
            return "grant_budget_exhausted", f"use {use.use_sequence} of a budget of {grant.max_uses}"
    if token.grant_id != use.grant_id or not token_signature_valid(raw_token, token_keys):
        return "grant_time_token_invalid", "the time token is not the NA's for this grant"
    if token.use_sequence >= use.use_sequence:
        return "grant_time_token_mismatch", (f"the time token was issued after use {token.use_sequence}, "
                                             f"not before use {use.use_sequence}")
    if token_head is not None and (token_head[0] != token.use_head_digest
                                   or _utc(token_head[1]) > _utc(token.issued_at) + GRANT_CLOCK_SKEW):
        return "grant_time_token_mismatch", f"use {token.use_sequence} is not the one the time token names"
    if previous is not None:
        if _utc(token.issued_at) < _utc(previous.time_token_issued_at):
            return "grant_time_token_regressed", "the time token is older than the previous use's"
        if grant is not None and previous.time_token_id == token.time_token_id \
                and previous.token_uses >= grant.max_uses_per_time_token:
            return "grant_time_token_exhausted", (f"{grant.max_uses_per_time_token} uses already cite time token "
                                                  f"{token.time_token_id}")
    if executed < _utc(token.issued_at):
        return "grant_use_before_time_token", (f"executed at {_iso(executed)}, before the time token's "
                                               f"{_iso(token.issued_at)}")
    if previous is not None and executed < _utc(previous.executed_at):
        return "grant_use_out_of_order", f"executed at {_iso(executed)}, before the previous use"
    if grant is not None and not (_utc(grant.valid_from) <= executed <= _utc(grant.valid_until)):
        return "grant_use_outside_validity", (f"executed at {_iso(executed)}, outside "
                                              f"[{_iso(grant.valid_from)}, {_iso(grant.valid_until)}]")
    if recorded_at is not None:
        recorded = _utc(recorded_at)
        if executed > recorded + GRANT_CLOCK_SKEW:
            return "grant_use_in_future", f"executed at {_iso(executed)}, after it was recorded at {_iso(recorded)}"
        if grant is not None and recorded - executed > grant.validity:
            return "grant_use_uploaded_late", (f"recorded at {_iso(recorded)}, longer after it was executed than "
                                               f"the grant's validity ({int(grant.validity.total_seconds())} s)")
    if revoked_at is not None and executed >= _utc(revoked_at):
        return "grant_revoked", f"the grant was revoked at {_iso(revoked_at)}"
    return None


def next_previous(use: GrantExecutionEvidence, digest: str, previous: PreviousUse | None) -> PreviousUse:
    """The chain's state after a use: what the next use is checked against."""
    token = use.time_token
    same = previous is not None and previous.time_token_id == token.time_token_id
    return PreviousUse(digest=digest, executed_at=_utc(use.executed_at), time_token_id=token.time_token_id,
                       time_token_issued_at=_utc(token.issued_at),
                       token_uses=(previous.token_uses + 1) if same and previous is not None else 1)


def use_secret_problem(use: GrantExecutionEvidence) -> str | None:
    """Why a use may carry secret material, or None (the metadata guard on its own values)."""
    from .out_of_band import metadata_problem

    return metadata_problem({
        "execution_parameters": use.execution_parameters,
        "request_parameters": use.request_parameters,
        "outcome_detail": use.outcome_detail or "",
    })


# ---------------------------------------------------------------------------
# Signing and the store
# ---------------------------------------------------------------------------

NaSigned = CapabilityGrant | TimeToken | GrantRevocationRecord


def sign_grant_record(record: NaSigned, signing_key: SigningKeyLike, key_id: str) -> Any:
    """Return a grant, time token or grant revocation signed by the NA."""
    return record.model_copy(update={"signature": sign_model(record, signing_key, key_id)})


def verify_signed(record: Any, public_keys: Iterable[str]) -> bool:
    sig = record.signature
    return sig is not None and any(verify_model_signature(record, sig, k) for k in public_keys)


def entry_index(record: Any) -> dict[str, Any]:
    """Search fields of a Stage 5 entry's envelope, from its record (``_ENVELOPE_FIELDS`` in
    ``trust.evidence_store``). A use's ``resource_sequence`` is not among them: the NA assigns it."""
    if isinstance(record, CapabilityGrant):
        return {"record_id": record.grant_id, "executor_sovereign_id": record.bearer_sovereign_id}
    if isinstance(record, GrantExecutionEvidence):
        return {"record_id": record.use_id, "subject_id": record.grant_id, "resource_id": record.resource_id,
                "resource_action": record.resource_action, "capability": record.capability, "executor_sovereign_id": record.executor_sovereign_id,
                "outcome": record.outcome, "exec_sequence_no": record.use_sequence}
    if isinstance(record, GrantRevocationRecord):
        return {"record_id": record.revocation_id, "subject_id": record.grant_id, "outcome": record.reason}
    raise TypeError("not a Stage 5 record")


def grant_horizon(grant: CapabilityGrant) -> datetime:
    """The last time a use of the grant may still be admitted: its end, plus the late-upload window
    (its validity), plus the clock skew. Retention keeps a grant and its uses until then."""
    return _utc(grant.valid_until) + grant.validity + GRANT_CLOCK_SKEW
