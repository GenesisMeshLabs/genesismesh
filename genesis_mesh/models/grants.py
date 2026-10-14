"""Pre-issued capability grants (v1.6.0, Stage 5).

Break-glass (Stage 2) records a change made while the Network Authority (NA)
cannot be reached and judges it afterwards. A grant authorises it beforehand:
the NA signs, in advance, a bounded authorisation one holder may use while the
NA is unreachable, after checking that every policy that applies allows every
request the grant permits. This module holds the records:

``CapabilityGrant`` (entry kind ``grant``)
    The authorisation, signed by the NA: one bearer key, the capabilities, a
    basis (a trusted agreement or an attestation the NA issued), a validity of
    at most 24 hours, a budget of uses, and a closed parameter envelope (no
    parameter outside it is allowed). It binds the policy versions it was
    checked against and records how each of their gates was decided.
``TimeToken``
    A time the NA signed for one grant's holder, bound to the head of the
    holder's use chain when it asked (``use_sequence``, ``use_head_digest``).
    Each use carries the latest one the holder saw: a use is never dated
    before it, and only so many uses may cite one token.
``TimeTokenRequest``
    The holder's request for a time token, signed by the grant's bearer key.
``GrantExecutionEvidence`` (entry kind ``grant_execution``)
    One use of a grant, signed by the bearer key: the capability, the request
    parameters (inside the envelope), what was done to which resource, and a
    per-grant use chain (``use_sequence``, ``prev_use_digest``). It takes no
    resource position of its own: the NA assigns one when it admits the use
    (the envelope's ``resource_sequence``), so offline uses never fork a
    resource chain.
``GrantRevocationRecord`` (entry kind ``grant_revocation``)
    The NA's statement that a grant is revoked from ``revoked_at``: by an
    operator, or because its basis attestation was revoked, a policy version
    it is bound to was deactivated, a policy activated since denies within
    its envelope, or its bearer key was retired.

Canonical forms follow the Stage 2 records: every field but ``signature``,
absent optional top-level fields omitted; nested models keep their usual
form, except a time token's ``use_head_digest``, which is left out of every
form when absent (so a token nested in a use is the token as signed).
Numbers in an envelope are written as integers when their value is integral
(``5``, never ``5.0``), as every SDK writes them. Frozen from 1.6.0 on.
Timestamps are UTC.
"""

from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .boundary_policy import MAX_LIST_VALUES, AppliedPolicy, GateMode, JsonScalar
from .context import GateResult
from .execution import ResourceAction
from .genesis import Signature
from .out_of_band import _SignedRecord

#: The longest a grant may be valid, whatever the NA's configuration (Decision 3 of the 1.6.0 plan).
GRANT_MAX_VALIDITY = timedelta(hours=24)

#: The largest budget a grant may carry, and the most uses one time token may anchor, whatever the
#: NA's configuration.
GRANT_MAX_USES = 10_000
GRANT_MAX_USES_PER_TIME_TOKEN = 1_000

#: How far a use may be dated after the time its entry is recorded (clock skew between a holder and
#: the NA): a later time is in the future. A fixed value, so every verifier applies the same rule.
GRANT_CLOCK_SKEW = timedelta(seconds=300)

#: Most capabilities and envelope parameters one grant may name.
MAX_GRANT_CAPABILITIES = 16
MAX_ENVELOPE_PARAMETERS = 64

#: What a grant rests on: an agreement the NA trusts, or a membership attestation it issued.
GrantBasisKind = Literal["agreement", "attestation"]

#: How a gate was decided over a grant's whole envelope and validity: it passes for every request
#: the grant permits, it may fail for one, or it cannot be decided over a range.
GrantGateDecision = Literal["pass", "may_fail", "undecidable"]

#: Why a grant was revoked.
GrantRevocationReason = Literal[
    "operator", "attestation_revoked", "policy_deactivated", "policy_activated", "bearer_key_retired",
]

#: Outcomes of a use, as execution evidence records them.
GrantUseOutcome = Literal["success", "failure", "partial"]

#: An envelope parameter's name: one segment of ``request_parameters``.
PARAMETER_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: Input limits (Decision 12 of the 1.2.0 plan): integers every implementation reads exactly.
_MIN_INTEGER = -(2**63)
_MAX_INTEGER = 2**64 - 1


def _absent(value: Any) -> bool:
    return value is None


def normalize_number(value: Any) -> Any:
    """A number as an envelope holds it: an integral float as an integer (``5.0`` is ``5``), within
    64 bits. Raises ``ValueError`` for a boolean, a non-finite float or an integer beyond 64 bits."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("a number is expected")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("numbers must be finite")
        if not value.is_integer():
            return value
        value = int(value)
    if not _MIN_INTEGER <= value <= _MAX_INTEGER:
        raise ValueError("integers must fit in 64 bits")
    return value


def _normalize_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    return normalize_number(value)


def scalar_key(value: Any) -> tuple[str, Any]:
    """A type-strict identity for a scalar (``True`` is not ``1``, ``"1"`` is not ``1``, ``1`` is ``1.0``)."""
    if value is None:
        return ("null", None)
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, str):
        return ("string", value)
    from fractions import Fraction

    return ("number", Fraction(value))


class NumericRange(BaseModel):
    """A typed numeric range of an envelope parameter (v1.6.0).

    ``integer``: integral numbers (``5`` and ``5.0`` alike) within the bounds;
    ``number``: any finite number within them. Booleans are never numbers.
    ``exclusive_minimum`` / ``exclusive_maximum`` leave a bound out. Bounds of
    an integer range are integers; a range holds at least one value.
    """

    model_config = ConfigDict(extra="forbid")

    number_type: Literal["integer", "number"]
    minimum: Union[int, float]
    maximum: Union[int, float]
    exclusive_minimum: bool = False
    exclusive_maximum: bool = False

    @field_validator("minimum", "maximum", mode="before")
    @classmethod
    def _number(cls, value: Any) -> Any:
        return normalize_number(value)

    @model_validator(mode="after")
    def _non_empty(self) -> "NumericRange":
        from fractions import Fraction

        if self.number_type == "integer" and not (isinstance(self.minimum, int) and isinstance(self.maximum, int)):
            raise ValueError("an integer range has integer bounds")
        low, high = Fraction(self.minimum), Fraction(self.maximum)
        if self.number_type == "integer":
            first = low + 1 if self.exclusive_minimum else low
            last = high - 1 if self.exclusive_maximum else high
            if first > last:
                raise ValueError("the range holds no integer")
        elif low > high or (low == high and (self.exclusive_minimum or self.exclusive_maximum)):
            raise ValueError("the range holds no number")
        return self


class EnvelopeParameter(BaseModel):
    """One parameter a grant's uses may carry in ``request_parameters`` (v1.6.0).

    Exactly one of ``one_of`` (a finite set of scalars, compared type-strictly:
    ``true`` is not ``1``, ``"1"`` is not ``1``), ``subset_of`` (a list of
    strings, every one of them in the set) or ``number_range``. ``required``:
    every use carries the parameter; otherwise a use may leave it out.
    """

    model_config = ConfigDict(extra="forbid")

    required: bool = True
    one_of: list[JsonScalar] | None = Field(default=None, min_length=1, max_length=MAX_LIST_VALUES)
    subset_of: list[str] | None = Field(default=None, min_length=1, max_length=MAX_LIST_VALUES)
    number_range: NumericRange | None = None

    @field_validator("one_of", mode="before")
    @classmethod
    def _scalars(cls, values: Any) -> Any:
        if not isinstance(values, list):
            return values
        out = []
        for value in values:
            if value is not None and not isinstance(value, (str, bool, int, float)):
                raise ValueError("one_of holds scalars only")
            out.append(_normalize_scalar(value))
        return out

    @model_validator(mode="after")
    def _one_kind(self) -> "EnvelopeParameter":
        given = [v for v in (self.one_of, self.subset_of, self.number_range) if v is not None]
        if len(given) != 1:
            raise ValueError("give exactly one of one_of, subset_of and number_range")
        if self.one_of is not None and len({scalar_key(v) for v in self.one_of}) != len(self.one_of):
            raise ValueError("one_of repeats a value")
        if self.subset_of is not None and len(set(self.subset_of)) != len(self.subset_of):
            raise ValueError("subset_of repeats a value")
        return self


class GrantGateOutcome(BaseModel):
    """How one gate of an applied policy was decided over a grant's envelope (v1.6.0).

    An issued grant's enforce-mode gates all ``pass``; observe-mode gates are
    recorded as they were decided and never refuse a grant.
    """

    model_config = ConfigDict(extra="forbid")

    capability: str
    policy_id: str
    policy_version: int
    gate_id: str
    gate_type: str
    mode: GateMode
    outcome: GrantGateDecision
    detail: str = Field(..., max_length=1024)


class GrantPolicyBinding(BaseModel):
    """The policy versions a grant was checked against, in resolution order (v1.6.0).

    ``policy_set_digest`` is ``policy_set_digest(policies)``; deactivating any
    of these versions revokes the grant.
    """

    model_config = ConfigDict(extra="forbid")

    policies: list[AppliedPolicy] = Field(default_factory=list)
    policy_set_digest: str
    gate_outcomes: list[GrantGateOutcome] = Field(default_factory=list)
    registry_gate_types: list[str] = Field(default_factory=list)


def _envelope_names(envelope: dict[str, Any]) -> dict[str, Any]:
    if len(envelope) > MAX_ENVELOPE_PARAMETERS:
        raise ValueError(f"at most {MAX_ENVELOPE_PARAMETERS} envelope parameters")
    for name in envelope:
        if not PARAMETER_NAME.match(name):
            raise ValueError("envelope parameter names match [A-Za-z0-9_-]{1,64}")
    return envelope


class CapabilityGrant(_SignedRecord):
    """A bounded authorisation the NA signs in advance for one bearer key (v1.6.0).

    The bearer is a registered executor key (``bearer_key_id``,
    ``bearer_public_key``, ``bearer_sovereign_id``). ``basis_kind`` and
    ``basis_id`` name the agreement or attestation it rests on and
    ``basis_digest`` its signed form's SHA-256; ``requester_sovereign_id`` and
    ``provider_sovereign_id`` are the parties it was evaluated for.
    ``basis_checks`` are the built-in capability, validity and freshness checks
    run at issuance. A use is admitted within ``[valid_from, valid_until]``,
    at most ``max_uses`` times, at most ``max_uses_per_time_token`` times per
    time token, with ``request_parameters`` inside ``parameter_envelope``.
    """

    grant_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    bearer_key_id: str = Field(..., min_length=1, max_length=256)
    bearer_public_key: str = Field(..., min_length=1, max_length=256)
    bearer_sovereign_id: str = Field(..., min_length=1, max_length=256)
    capabilities: list[str] = Field(..., min_length=1, max_length=MAX_GRANT_CAPABILITIES)
    basis_kind: GrantBasisKind
    basis_id: str = Field(..., min_length=1, max_length=128)
    basis_digest: str = Field(..., min_length=64, max_length=64)
    requester_sovereign_id: str = Field(..., min_length=1, max_length=256)
    provider_sovereign_id: str = Field(..., min_length=1, max_length=256)
    valid_from: datetime
    valid_until: datetime
    max_uses: int = Field(..., ge=1, le=GRANT_MAX_USES)
    max_uses_per_time_token: int = Field(..., ge=1, le=GRANT_MAX_USES_PER_TIME_TOKEN)
    parameter_envelope: dict[str, EnvelopeParameter] = Field(default_factory=dict)
    basis_checks: list[GateResult] = Field(default_factory=list)
    policy_binding: GrantPolicyBinding
    issued_at: datetime
    issuer_sovereign_id: str
    issued_by: str
    signature: Signature | None = None

    @field_validator("parameter_envelope")
    @classmethod
    def _names(cls, value: dict[str, EnvelopeParameter]) -> dict[str, EnvelopeParameter]:
        return _envelope_names(value)

    @field_validator("capabilities")
    @classmethod
    def _capabilities(cls, value: list[str]) -> list[str]:
        if any(not c or len(c) > 256 or "*" in c for c in value):
            raise ValueError("capabilities are exact capability IDs of 1 to 256 characters")
        if len(set(value)) != len(value):
            raise ValueError("capabilities repeat a value")
        return value

    @model_validator(mode="after")
    def _validity(self) -> "CapabilityGrant":
        if self.valid_from >= self.valid_until:
            raise ValueError("valid_from must be earlier than valid_until")
        if self.valid_until - self.valid_from > GRANT_MAX_VALIDITY:
            raise ValueError("a grant is valid for at most 24 hours")
        return self

    @property
    def validity(self) -> timedelta:
        """How long the grant is valid: also the longest a use may wait to be uploaded."""
        return self.valid_until - self.valid_from


class TimeToken(_SignedRecord):
    """A time the NA signed for one grant's holder (v1.6.0).

    ``use_sequence`` is how many uses the holder had made when it asked, and
    ``use_head_digest`` the digest of the last of them (absent for none): a
    use citing the token comes after them in the chain, and is not dated
    before ``issued_at``.
    """

    time_token_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    grant_id: str = Field(..., min_length=1, max_length=128)
    use_sequence: int = Field(..., ge=0, le=GRANT_MAX_USES)
    use_head_digest: str | None = Field(default=None, min_length=64, max_length=64, exclude_if=_absent)
    issued_at: datetime
    issuer_sovereign_id: str
    issued_by: str
    signature: Signature | None = None

    @model_validator(mode="after")
    def _head(self) -> "TimeToken":
        if (self.use_sequence == 0) != (self.use_head_digest is None):
            raise ValueError("use_head_digest is given exactly when use_sequence is 1 or more")
        return self


class TimeTokenRequest(_SignedRecord):
    """A holder's request for a time token, signed by the grant's bearer key (v1.6.0).

    ``use_sequence`` and ``use_head_digest`` are the head of the holder's use
    chain (0 and absent before its first use); ``requested_at`` must be within
    the NA's clock skew of its clock.
    """

    grant_id: str = Field(..., min_length=1, max_length=128)
    use_sequence: int = Field(..., ge=0, le=GRANT_MAX_USES)
    use_head_digest: str | None = Field(default=None, min_length=64, max_length=64)
    requested_at: datetime
    signature: Signature | None = None

    @model_validator(mode="after")
    def _head(self) -> "TimeTokenRequest":
        if (self.use_sequence == 0) != (self.use_head_digest is None):
            raise ValueError("use_head_digest is given exactly when use_sequence is 1 or more")
        return self


class GrantExecutionEvidence(_SignedRecord):
    """One use of a grant, signed by its bearer key (v1.6.0).

    ``grant_digest`` is the grant's SHA-256 (its canonical form); the uses of
    one grant form a chain (``use_sequence`` from 1, ``prev_use_digest`` the
    previous use's digest). ``time_token`` is the latest time token the holder
    saw. ``resource_id`` and ``resource_action`` go together; the NA assigns
    the use its place in the resource's chain when it admits it.
    ``execution_parameters`` and ``outcome_detail`` pass the metadata guard
    (identifiers, versions and times, never values).
    """

    use_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    grant_id: str = Field(..., min_length=1, max_length=128)
    grant_digest: str = Field(..., min_length=64, max_length=64)
    use_sequence: int = Field(..., ge=1, le=GRANT_MAX_USES)
    prev_use_digest: str | None = Field(default=None, min_length=64, max_length=64)
    executor_sovereign_id: str = Field(..., min_length=1, max_length=256)
    capability: str = Field(..., min_length=1, max_length=256)
    request_parameters: dict[str, Any] = Field(default_factory=dict)
    resource_id: str | None = Field(default=None, min_length=1, max_length=256)
    resource_action: ResourceAction | None = None
    executed_at: datetime
    time_token: TimeToken
    outcome: GrantUseOutcome
    outcome_detail: str | None = Field(default=None, max_length=1024)
    execution_parameters: dict[str, Any] = Field(default_factory=dict)
    signature: Signature | None = None

    @model_validator(mode="after")
    def _shape(self) -> "GrantExecutionEvidence":
        if (self.resource_id is None) != (self.resource_action is None):
            raise ValueError("resource_id and resource_action go together")
        if (self.use_sequence == 1) != (self.prev_use_digest is None):
            raise ValueError("prev_use_digest is given exactly when use_sequence is 2 or more")
        return self


class GrantRevocationRecord(_SignedRecord):
    """The NA's revocation of a grant from ``revoked_at`` (v1.6.0).

    A use executed before ``revoked_at`` stands; one executed at or after it is
    refused (and quarantined). ``revoked_by`` names the operator key for an
    operator's revocation.
    """

    revocation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    grant_id: str = Field(..., min_length=1, max_length=128)
    grant_digest: str = Field(..., min_length=64, max_length=64)
    reason: GrantRevocationReason
    detail: str | None = Field(default=None, min_length=1, max_length=1024)
    revoked_by: str | None = Field(default=None, min_length=1, max_length=256)
    revoked_at: datetime
    issuer_sovereign_id: str
    issued_by: str
    signature: Signature | None = None


#: Optional fields each Stage 5 record omits from its signed form when absent.
GRANTS_OMIT_WHEN_NONE: dict[str, tuple[str, ...]] = {
    model.__name__: tuple(
        name for name, info in model.model_fields.items()
        if name != "signature" and not info.is_required() and info.default is None
    )
    for model in (CapabilityGrant, TimeToken, TimeTokenRequest, GrantExecutionEvidence, GrantRevocationRecord)
}
