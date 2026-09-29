"""Trusted gate registry and built-in configurable gate types (v0.57).

A BoundaryPolicy references gates by ``gate_type`` -- a key into a
``GateRegistry`` populated in code by the process that runs the
BoundaryEngine.  Policy content can select and configure an installed gate
type; it can never supply, import or execute code.

Every configurable gate is pure: it reads normalized facts from the
ContextRecord, never performs I/O, and never reads the clock (time comes from
``context.requested_at``).  The same context and configuration always yield
the same outcome.

Adding a domain rule: implement ``ConfiguredGateType`` (a ``gate_type`` key,
a Pydantic ``config_model`` with ``extra="forbid"``, and ``evaluate``),
register it, and reference it from a policy.  Nothing else changes.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...models.boundary_policy import MAX_LIST_VALUES, GateOutcome, JsonScalar
from ...models.context import ContextRecord

# ---------------------------------------------------------------------------
# Fact paths
# ---------------------------------------------------------------------------

#: Top-level ContextRecord fields a policy may address directly.
SCALAR_FACT_ROOTS: frozenset[str] = frozenset(
    {
        "requested_capability",
        "requester_sovereign_id",
        "provider_sovereign_id",
        "agreement_id",
        "parent_kind",
        "requested_at",
        "context_freshness_seq",
    }
)

#: ContextRecord mappings a policy may descend into with dotted paths.
NESTED_FACT_ROOTS: frozenset[str] = frozenset({"request_parameters", "attributes"})

MAX_FACT_PATH_DEPTH = 8
_SEGMENT = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class _Missing:
    """Sentinel for an absent fact (distinct from an explicit JSON null)."""

    _instance: ClassVar["_Missing | None"] = None

    def __new__(cls) -> "_Missing":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"


MISSING: Any = _Missing()


def fact_path_error(path: str) -> str | None:
    """Return why ``path`` is not an addressable fact path, or None if it is."""
    if not isinstance(path, str) or not path:
        return "fact path must be a non-empty string"
    segments = path.split(".")
    if len(segments) > MAX_FACT_PATH_DEPTH:
        return f"fact path deeper than {MAX_FACT_PATH_DEPTH} segments"
    if any(not _SEGMENT.match(seg) for seg in segments):
        return "fact path segments must match [A-Za-z0-9_-]{1,64}"
    root = segments[0]
    if root in SCALAR_FACT_ROOTS:
        if len(segments) != 1:
            return f"fact root {root!r} has no nested fields"
        return None
    if root in NESTED_FACT_ROOTS:
        if len(segments) < 2:
            return f"fact root {root!r} requires a key, e.g. {root}.<name>"
        return None
    return f"unknown fact root {root!r}"


def resolve_fact(context: ContextRecord, path: str) -> Any:
    """Return the fact at ``path`` or ``MISSING``.  ``path`` must be valid."""
    segments = path.split(".")
    root = segments[0]
    if root in SCALAR_FACT_ROOTS:
        return getattr(context, root)
    current: Any = getattr(context, root)
    for seg in segments[1:]:
        if not isinstance(current, dict) or seg not in current:
            return MISSING
        current = current[seg]
    return current


def _value_type(value: Any) -> str:
    if value is MISSING:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, datetime):
        return "timestamp"
    return "other"


def _is_number(value: Any) -> bool:
    # Python integers are always finite. Converting a large integer to float
    # inside isfinite() can overflow during selector matching.
    if isinstance(value, bool):
        return False
    return isinstance(value, int) or (isinstance(value, float) and math.isfinite(value))


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, bool)) or _is_number(value)


def scalar_equals(a: Any, b: Any) -> bool:
    """Type-strict scalar equality: True != 1, "1" != 1, 1 == 1.0."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if a is None or b is None:
        return a is None and b is None
    if _is_number(a) and _is_number(b):
        return bool(a == b)
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    return False


def _disclosed(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def fact_inputs(path: str, value: Any, disclose_input: bool) -> dict[str, Any]:
    """Proof inputs for one fact: presence and type always, value only if disclosed."""
    inputs: dict[str, Any] = {
        "path": path,
        "present": value is not MISSING,
        "value_type": _value_type(value),
    }
    if disclose_input and value is not MISSING:
        inputs["value"] = _disclosed(value)
    return inputs


# ---------------------------------------------------------------------------
# Gate protocol and registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfiguredGateOutcome:
    """Result of one configured gate evaluation.

    ``inputs`` must already respect ``disclose_input`` and ``detail`` must not
    contain raw fact values unless disclosed -- both are copied verbatim into
    the signed JustificationProof and BoundaryDecision.
    """

    passed: bool
    outcome: GateOutcome
    detail: str
    inputs: dict[str, Any] = field(default_factory=dict)
    condition: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ConfiguredGateType(Protocol):
    """A trusted, installed gate implementation that policies may configure."""

    gate_type: str
    config_model: type[BaseModel]

    def evaluate(
        self, context: ContextRecord, config: Any, *, disclose_input: bool
    ) -> ConfiguredGateOutcome: ...


_GATE_TYPE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}\.v[0-9]{1,3}$")


class GateRegistry:
    """Code-populated map of gate_type -> trusted gate implementation.

    Freeze the registry once the process has registered its gate types; a
    frozen registry rejects further registration.
    """

    def __init__(self) -> None:
        self._types: dict[str, ConfiguredGateType] = {}
        self._frozen = False

    @classmethod
    def builtin(cls) -> "GateRegistry":
        """Return an unfrozen registry holding the built-in gate types."""
        registry = cls()
        for gate in BUILTIN_GATE_TYPES:
            registry.register(gate)
        return registry

    @classmethod
    def default(cls) -> "GateRegistry":
        """Return a frozen registry holding the built-in gate types."""
        return cls.builtin().freeze()

    def register(self, gate: ConfiguredGateType) -> None:
        if self._frozen:
            raise RuntimeError("gate registry is frozen")
        if not isinstance(gate, ConfiguredGateType):
            raise TypeError("gate must implement ConfiguredGateType")
        if not _GATE_TYPE_KEY.match(gate.gate_type):
            raise ValueError(f"invalid gate_type key {gate.gate_type!r} (expected name.vN)")
        if gate.gate_type in self._types:
            raise ValueError(f"gate_type {gate.gate_type!r} already registered")
        if gate.config_model.model_config.get("extra") != "forbid":
            raise ValueError(f"config_model for {gate.gate_type!r} must set extra='forbid'")
        self._types[gate.gate_type] = gate

    def freeze(self) -> "GateRegistry":
        self._frozen = True
        return self

    @property
    def frozen(self) -> bool:
        return self._frozen

    def get(self, gate_type: str) -> ConfiguredGateType | None:
        return self._types.get(gate_type)

    def gate_types(self) -> list[str]:
        return sorted(self._types)

    def describe(self) -> list[dict[str, Any]]:
        """Return gate types and their config fields (for CLI / operator display)."""
        out = []
        for key in self.gate_types():
            gate = self._types[key]
            fields = {
                name: {
                    "required": info.is_required(),
                    "description": info.description or "",
                }
                for name, info in gate.config_model.model_fields.items()
            }
            out.append({"gate_type": key, "config": fields, "doc": (gate.__doc__ or "").strip()})
        return out


# ---------------------------------------------------------------------------
# Built-in config models
# ---------------------------------------------------------------------------


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PathConfig(_Config):
    path: str = Field(..., description="Fact path, e.g. request_parameters.amount")

    @field_validator("path")
    @classmethod
    def _valid_path(cls, value: str) -> str:
        err = fact_path_error(value)
        if err:
            raise ValueError(err)
        return value


class MaxValueConfig(PathConfig):
    max: float = Field(..., description="Upper bound")
    inclusive: bool = Field(default=True, description="Allow value == max")

    @field_validator("max")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("max must be finite")
        return value


class MinValueConfig(PathConfig):
    min: float = Field(..., description="Lower bound")
    inclusive: bool = Field(default=True, description="Allow value == min")

    @field_validator("min")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("min must be finite")
        return value


class ValueListConfig(PathConfig):
    values: list[JsonScalar] = Field(
        ..., min_length=1, max_length=MAX_LIST_VALUES, description="Scalar values"
    )

    @field_validator("values")
    @classmethod
    def _scalars(cls, values: list[Any]) -> list[Any]:
        if not all(_is_scalar(v) for v in values):
            raise ValueError("values must be finite JSON scalars")
        return values


class BooleanRequiredConfig(PathConfig):
    expected: bool = Field(default=True, description="Required boolean value")


class ScopeMembershipConfig(PathConfig):
    allowed: list[str] = Field(
        ..., min_length=1, max_length=MAX_LIST_VALUES, description="Permitted scope items"
    )


class TimeWindowConfig(_Config):
    not_before: datetime | None = Field(default=None, description="Earliest requested_at (UTC)")
    not_after: datetime | None = Field(default=None, description="Latest requested_at (UTC)")
    weekdays: list[int] | None = Field(
        default=None, max_length=MAX_LIST_VALUES,
        description="Permitted ISO weekdays in UTC, 1=Mon .. 7=Sun"
    )
    utc_hour_start: int | None = Field(default=None, ge=0, le=23, description="First permitted UTC hour")
    utc_hour_end: int | None = Field(default=None, ge=1, le=24, description="Hour after the last permitted UTC hour")

    @model_validator(mode="after")
    def _coherent(self) -> "TimeWindowConfig":
        if all(
            v is None
            for v in (self.not_before, self.not_after, self.weekdays, self.utc_hour_start, self.utc_hour_end)
        ):
            raise ValueError("time_window requires at least one constraint")
        for ts in (self.not_before, self.not_after):
            if ts is not None and ts.tzinfo is None:
                raise ValueError("time bounds must be timezone-aware")
        if self.not_before and self.not_after and self.not_before >= self.not_after:
            raise ValueError("not_before must be earlier than not_after")
        if self.weekdays is not None:
            if not self.weekdays or any(d < 1 or d > 7 for d in self.weekdays):
                raise ValueError("weekdays must be a non-empty list of 1..7")
        if (self.utc_hour_start is None) != (self.utc_hour_end is None):
            raise ValueError("utc_hour_start and utc_hour_end must be set together")
        if self.utc_hour_start is not None and self.utc_hour_end is not None:
            if self.utc_hour_start >= self.utc_hour_end:
                raise ValueError("utc_hour_start must be less than utc_hour_end")
        return self


# ---------------------------------------------------------------------------
# Built-in gate types
# ---------------------------------------------------------------------------


def _missing(path: str, value: Any, disclose: bool, condition: dict[str, Any]) -> ConfiguredGateOutcome:
    return ConfiguredGateOutcome(
        passed=False,
        outcome="missing_context",
        detail=f"required fact {path!r} is missing",
        inputs=fact_inputs(path, value, disclose),
        condition=condition,
    )


def _wrong_type(
    path: str, value: Any, disclose: bool, condition: dict[str, Any], expected: str
) -> ConfiguredGateOutcome:
    return ConfiguredGateOutcome(
        passed=False,
        outcome="invalid_context",
        detail=f"fact {path!r} is {_value_type(value)}, expected {expected}",
        inputs=fact_inputs(path, value, disclose),
        condition=condition,
    )


def _result(
    passed: bool, path: str, value: Any, disclose: bool, condition: dict[str, Any], detail: str
) -> ConfiguredGateOutcome:
    return ConfiguredGateOutcome(
        passed=passed,
        outcome="pass" if passed else "fail",
        detail=detail,
        inputs=fact_inputs(path, value, disclose),
        condition=condition,
    )


def _shown(path: str, value: Any, disclose: bool) -> str:
    return f"{path}={value!r}" if disclose else path


class RequiredParameterGate:
    """Passes when the fact is present and not null."""

    gate_type = "required_parameter.v1"
    config_model: type[BaseModel] = PathConfig

    def evaluate(self, context: ContextRecord, config: PathConfig, *, disclose_input: bool) -> ConfiguredGateOutcome:
        value = resolve_fact(context, config.path)
        condition = {"required": config.path}
        if value is MISSING or value is None:
            return _missing(config.path, value, disclose_input, condition)
        return _result(True, config.path, value, disclose_input, condition, f"fact {config.path!r} is present")


class MaxValueGate:
    """Passes when the numeric fact is at most ``max``."""

    gate_type = "max_value.v1"
    config_model: type[BaseModel] = MaxValueConfig

    def evaluate(self, context: ContextRecord, config: MaxValueConfig, *, disclose_input: bool) -> ConfiguredGateOutcome:
        value = resolve_fact(context, config.path)
        op = "<=" if config.inclusive else "<"
        condition = {"operator": op, "max": config.max}
        if value is MISSING or value is None:
            return _missing(config.path, value, disclose_input, condition)
        if not _is_number(value):
            return _wrong_type(config.path, value, disclose_input, condition, "finite number")
        passed = value <= config.max if config.inclusive else value < config.max
        verdict = "satisfies" if passed else "violates"
        shown = _shown(config.path, value, disclose_input)
        return _result(passed, config.path, value, disclose_input, condition, f"{shown} {verdict} {op} {config.max}")


class MinValueGate:
    """Passes when the numeric fact is at least ``min``."""

    gate_type = "min_value.v1"
    config_model: type[BaseModel] = MinValueConfig

    def evaluate(self, context: ContextRecord, config: MinValueConfig, *, disclose_input: bool) -> ConfiguredGateOutcome:
        value = resolve_fact(context, config.path)
        op = ">=" if config.inclusive else ">"
        condition = {"operator": op, "min": config.min}
        if value is MISSING or value is None:
            return _missing(config.path, value, disclose_input, condition)
        if not _is_number(value):
            return _wrong_type(config.path, value, disclose_input, condition, "finite number")
        passed = value >= config.min if config.inclusive else value > config.min
        verdict = "satisfies" if passed else "violates"
        shown = _shown(config.path, value, disclose_input)
        return _result(passed, config.path, value, disclose_input, condition, f"{shown} {verdict} {op} {config.min}")


class AllowlistGate:
    """Passes when the scalar fact equals one of ``values``."""

    gate_type = "allowlist.v1"
    config_model: type[BaseModel] = ValueListConfig

    def evaluate(self, context: ContextRecord, config: ValueListConfig, *, disclose_input: bool) -> ConfiguredGateOutcome:
        value = resolve_fact(context, config.path)
        condition = {"allowed": list(config.values)}
        if value is MISSING:
            return _missing(config.path, value, disclose_input, condition)
        if not _is_scalar(value):
            return _wrong_type(config.path, value, disclose_input, condition, "scalar")
        passed = any(scalar_equals(value, v) for v in config.values)
        shown = _shown(config.path, value, disclose_input)
        detail = f"{shown} is in the allowlist" if passed else f"{shown} is not in the allowlist"
        return _result(passed, config.path, value, disclose_input, condition, detail)


class DenylistGate:
    """Passes when the scalar fact equals none of ``values``."""

    gate_type = "denylist.v1"
    config_model: type[BaseModel] = ValueListConfig

    def evaluate(self, context: ContextRecord, config: ValueListConfig, *, disclose_input: bool) -> ConfiguredGateOutcome:
        value = resolve_fact(context, config.path)
        condition = {"denied": list(config.values)}
        if value is MISSING:
            return _missing(config.path, value, disclose_input, condition)
        if not _is_scalar(value):
            return _wrong_type(config.path, value, disclose_input, condition, "scalar")
        passed = not any(scalar_equals(value, v) for v in config.values)
        shown = _shown(config.path, value, disclose_input)
        detail = f"{shown} is not denylisted" if passed else f"{shown} is denylisted"
        return _result(passed, config.path, value, disclose_input, condition, detail)


class BooleanRequiredGate:
    """Passes when the fact is a boolean equal to ``expected``."""

    gate_type = "boolean_required.v1"
    config_model: type[BaseModel] = BooleanRequiredConfig

    def evaluate(
        self, context: ContextRecord, config: BooleanRequiredConfig, *, disclose_input: bool
    ) -> ConfiguredGateOutcome:
        value = resolve_fact(context, config.path)
        condition = {"expected": config.expected}
        if value is MISSING or value is None:
            return _missing(config.path, value, disclose_input, condition)
        if not isinstance(value, bool):
            return _wrong_type(config.path, value, disclose_input, condition, "boolean")
        passed = value is config.expected
        detail = f"{config.path} is {value}" if passed or disclose_input else f"{config.path} is not {config.expected}"
        return _result(passed, config.path, value, disclose_input, condition, detail)


class ScopeMembershipGate:
    """Passes when the fact is a list of strings, every one of them in ``allowed``."""

    gate_type = "scope_membership.v1"
    config_model: type[BaseModel] = ScopeMembershipConfig

    def evaluate(
        self, context: ContextRecord, config: ScopeMembershipConfig, *, disclose_input: bool
    ) -> ConfiguredGateOutcome:
        value = resolve_fact(context, config.path)
        condition = {"allowed": list(config.allowed)}
        if value is MISSING or value is None:
            return _missing(config.path, value, disclose_input, condition)
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return _wrong_type(config.path, value, disclose_input, condition, "list of strings")
        allowed = set(config.allowed)
        outside = [v for v in value if v not in allowed]
        passed = not outside
        if passed:
            detail = f"all {len(value)} item(s) of {config.path} are within the allowed scope"
        elif disclose_input:
            detail = f"{config.path} items outside the allowed scope: {sorted(set(outside))!r}"
        else:
            detail = f"{len(outside)} item(s) of {config.path} are outside the allowed scope"
        return _result(passed, config.path, value, disclose_input, condition, detail)


class TimeWindowGate:
    """Passes when ``requested_at`` falls inside the configured UTC window."""

    gate_type = "time_window.v1"
    config_model: type[BaseModel] = TimeWindowConfig

    def evaluate(self, context: ContextRecord, config: TimeWindowConfig, *, disclose_input: bool) -> ConfiguredGateOutcome:
        path = "requested_at"
        at = context.requested_at
        condition = config.model_dump(mode="json", exclude_none=True)
        if at.tzinfo is None:
            return _wrong_type(path, at, disclose_input, condition, "timezone-aware timestamp")
        failures: list[str] = []
        if config.not_before is not None and at < config.not_before:
            failures.append("before not_before")
        if config.not_after is not None and at > config.not_after:
            failures.append("after not_after")
        utc = at.astimezone(timezone.utc)
        if config.weekdays is not None and utc.isoweekday() not in config.weekdays:
            failures.append("weekday not permitted")
        if config.utc_hour_start is not None and config.utc_hour_end is not None:
            if not (config.utc_hour_start <= utc.hour < config.utc_hour_end):
                failures.append("hour not permitted")
        passed = not failures
        # requested_at is not sensitive: it is already carried in the decision.
        detail = (
            f"requested_at {at.isoformat()} is inside the window"
            if passed
            else f"requested_at {at.isoformat()} is outside the window: {', '.join(failures)}"
        )
        return _result(passed, path, at, True, condition, detail)


BUILTIN_GATE_TYPES: tuple[ConfiguredGateType, ...] = (
    RequiredParameterGate(),
    MaxValueGate(),
    MinValueGate(),
    AllowlistGate(),
    DenylistGate(),
    BooleanRequiredGate(),
    ScopeMembershipGate(),
    TimeWindowGate(),
)
