"""The field registry of signed records (v1.2.0).

A verifier that copies every field of a record into the signed form accepts a
field it does not understand whenever the signer covered it, so a field added
in a later release can change what a record means for older verifiers. Since
1.2.0 verifiers know every signed field. A record whose signature verifies
over a field the registry does not list is refused as ``unknown_field``: an
authentic record from a newer signer, which this release cannot read.

The registry is generated from the Python models, the reference
implementation of the canonical forms (the rules are written down in
``docs/reference/canonical-form.md``). Each model lists its fields; a field is

* ``null``: a value (string, number, boolean, or a list of them);
* ``"timestamp"``: a timestamp (or a list of them), which must be written in
  its canonical form (``canonical_timestamp``, v1.2.0);
* ``"open"``: free-form JSON chosen by the signer (``claims``, ``scope``,
  ``execution_parameters``...), whose keys are not checked;
* ``{"object": M}``, ``{"list": M}`` or ``{"map": M}``: one, a list, or a
  string-keyed map of model ``M``, checked in turn.

Roots also carry their canonical rules: the signature field (outside the
signed form), the optional fields omitted from it when absent, and for
agreements the fixed list of signed fields. Only the signed projection of a
record is checked: the signature itself, and an agreement's fields outside
its signed list, carry no meaning a verifier could misread.

``conformance/vectors/field_registry.json`` carries the registry to the SDKs;
a test fails when it differs from the models.

A record is valid only in its canonical form (v1.2.0): what the reference
writes back after reading it. A record whose signature verifies over another
form (a timestamp written ``+00:00`` rather than ``Z``, a fraction ``.000``)
is refused as ``non_canonical_form``; one whose signature covers only the
canonical form, received in another, is refused as ``invalid_signature``.
"""

from __future__ import annotations

import enum
import json
import re
import types
import typing
from datetime import date, datetime, timezone
from typing import Any, Sequence, Union

from pydantic import BaseModel, TypeAdapter, ValidationError

#: Optional fields each root omits from its signed form when absent (None).
OMIT_WHEN_NONE: dict[str, tuple[str, ...]] = {
    "BoundaryDecision": ("policy_binding", "attestation_binding"),
    "ContextRecord": ("attestation_id",),
    "ExecutionEvidence": ("resource_id", "resource_action", "resource_sequence", "prev_resource_digest"),
    "StoreAnchor": ("previous_anchor_digest",),
}

#: Roots signed over a fixed list of fields rather than all of them.
CANONICAL_FIELDS: dict[str, tuple[str, ...]] = {
    "AgreementRecord": (
        "agreed_terms", "graph_digest", "offer_id", "offerer_evidence",
        "offerer_sovereign_id", "responder_evidence", "responder_sovereign_id",
    ),
}

#: Bumped when the registry's own format changes (not when models gain fields).
#: 2 (v1.2.0): the ``"timestamp"`` kind.
REGISTRY_VERSION = 2

_TIMESTAMP = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{6}))?(Z|[+-]([0-9]{2}):([0-9]{2}))?"
)


def canonical_timestamp(value: str) -> bool:
    """True when ``value`` is a timestamp in canonical form (v1.2.0).

    The form the reference writes: ``YYYY-MM-DDTHH:MM:SS``, then six digits of
    microseconds when they are not all zero, then ``Z`` for UTC or ``+HH:MM``
    / ``-HH:MM`` for another offset (none for a timestamp without one). The
    date and time must exist; a year starts at 0001, an offset is under 24h.
    """
    match = _TIMESTAMP.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return False
    year, month, day, hour, minute, second, fraction, zone, zone_h, zone_m = match.groups()
    if fraction == "000000" or zone in ("+00:00", "-00:00"):
        return False
    if zone_h is not None and (int(zone_h) > 23 or int(zone_m) > 59):
        return False
    try:
        datetime(int(year), int(month), int(day), int(hour), int(minute), int(second))
    except ValueError:
        return False
    return True


def _roots() -> list[type[BaseModel]]:
    from .agreement import AgreementRecord
    from .boundary_policy import BoundaryPolicy
    from .context import BoundaryDecision, ContextRecord
    from .data_usage import DataAccessIntent, DataLicensePolicy
    from .evidence_store import EvidenceStoreEntry, RetentionCheckpoint, StoreAnchor
    from .execution import ExecutionEvidence
    from .justification import JustificationProof
    from .sovereign import MembershipAttestation, SovereignRevocationFeed

    return [
        AgreementRecord, BoundaryDecision, BoundaryPolicy, ContextRecord, DataAccessIntent,
        DataLicensePolicy, EvidenceStoreEntry, ExecutionEvidence, JustificationProof,
        MembershipAttestation, RetentionCheckpoint, SovereignRevocationFeed, StoreAnchor,
    ]


def _classes() -> dict[str, type[BaseModel]]:
    """Every root model class by name."""
    if "classes" not in _CACHE:
        _CACHE["classes"] = {m.__name__: m for m in _roots()}
    return _CACHE["classes"]


def _is_model(tp: Any) -> bool:
    return isinstance(tp, type) and issubclass(tp, BaseModel)


def _is_scalar(tp: Any) -> bool:
    return typing.get_origin(tp) is typing.Literal or (
        isinstance(tp, type) and issubclass(tp, (str, int, float, bool, enum.Enum, datetime, date))
    )


def _kind(tp: Any, models: dict[str, type[BaseModel]]) -> Any:
    """The registry entry for one annotation (see the module docstring).

    Raises ``TypeError`` for a shape the registry cannot describe (a union of
    two models, a tuple of models, nested containers of models): describing it
    as free-form would silently stop checking the models inside.
    """
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is typing.Annotated:
        return _kind(args[0], models)
    if origin in (Union, types.UnionType):
        kinds = [_kind(a, models) for a in args if a is not type(None)]
        distinct = [k for i, k in enumerate(kinds) if k not in kinds[:i]]
        structured = [k for k in distinct if isinstance(k, dict)]
        if len(structured) > 1 or (structured and "open" in distinct):
            raise TypeError(f"cannot describe the union {tp!r}")
        if structured:
            return structured[0]
        if "open" in distinct:
            return "open"
        return "timestamp" if distinct == ["timestamp"] else None
    if _is_model(tp):
        models[tp.__name__] = tp
        return {"object": tp.__name__}
    if origin in (tuple,) or tp is tuple:
        if all(_is_scalar(a) for a in args if a is not Ellipsis):
            return None
        raise TypeError(f"cannot describe the tuple {tp!r}")
    if origin in (list, set, frozenset) or tp in (list, set, frozenset):
        inner = _kind(args[0], models) if args else "open"
        if isinstance(inner, dict):
            if "object" in inner:
                return {"list": inner["object"]}
            raise TypeError(f"cannot describe a list of containers {tp!r}")
        return inner
    if origin is dict or tp is dict:
        value = _kind(args[1], models) if len(args) == 2 else "open"
        if isinstance(value, dict):
            if "object" in value:
                return {"map": value["object"]}
            raise TypeError(f"cannot describe a map of containers {tp!r}")
        if value == "timestamp":
            raise TypeError(f"cannot describe a map of timestamps {tp!r}")
        return "open"
    if tp is Any or tp is object:
        return "open"
    if isinstance(tp, type) and issubclass(tp, datetime):
        return "timestamp"
    if _is_scalar(tp):
        return None
    raise TypeError(f"cannot describe the annotation {tp!r}")


def build_registry() -> dict[str, Any]:
    """The registry of every root and every model nested in one, from the Python models."""
    roots = _roots()
    pending: dict[str, type[BaseModel]] = {m.__name__: m for m in roots}
    done: dict[str, dict[str, Any]] = {}
    while pending:
        name, model = sorted(pending.items())[0]
        del pending[name]
        if name in done:
            continue
        nested: dict[str, type[BaseModel]] = {}
        fields = {f: _kind(info.annotation, nested) for f, info in model.model_fields.items()}
        done[name] = {"fields": dict(sorted(fields.items()))}
        pending.update({n: m for n, m in nested.items() if n not in done})
    for model in roots:
        spec = done[model.__name__]
        spec["root"] = True
        spec["signature_field"] = next((f for f in ("signature", "signatures") if f in spec["fields"]), None)
        if model.__name__ in OMIT_WHEN_NONE:
            spec["omit_when_none"] = list(OMIT_WHEN_NONE[model.__name__])
        if model.__name__ in CANONICAL_FIELDS:
            spec["canonical_fields"] = list(CANONICAL_FIELDS[model.__name__])
    from .evidence_store import EntryKind

    return {
        "version": REGISTRY_VERSION,
        "entry_kinds": sorted(typing.get_args(EntryKind)),
        "models": dict(sorted(done.items())),
    }


def unknown_fields(
    model: str, data: Any, registry: dict[str, Any] | None = None, path: str = "", *, projection: bool = True,
) -> list[str]:
    """Dotted paths of the signed fields in ``data`` that ``model`` does not define.

    With ``projection`` (the default, for a root record) only the signed
    projection is checked: the signature field is skipped, and a root signed
    over a fixed field list is checked on those fields only. Free-form fields
    are not inspected; values of the wrong type are left to validation.
    """
    registry = registry or _registry()
    spec = registry["models"].get(model)
    if spec is None or not isinstance(data, dict):
        return []
    found: list[str] = []
    for key, value in data.items():
        if projection and (key == spec.get("signature_field")
                           or ("canonical_fields" in spec and key not in spec["canonical_fields"])):
            continue
        if key not in spec["fields"]:
            found.append(f"{path}{key}")
            continue
        kind = spec["fields"][key]
        if value is None or not isinstance(kind, dict):
            continue
        if "object" in kind:
            found += unknown_fields(kind["object"], value, registry, f"{path}{key}.", projection=False)
        elif "list" in kind and isinstance(value, list):
            for i, item in enumerate(value):
                found += unknown_fields(kind["list"], item, registry, f"{path}{key}.{i}.", projection=False)
        elif "map" in kind and isinstance(value, dict):
            for k, item in value.items():
                found += unknown_fields(kind["map"], item, registry, f"{path}{key}.{k}.", projection=False)
    return found


def non_canonical_timestamps(
    model: str, data: Any, registry: dict[str, Any] | None = None, path: str = "", *, projection: bool = True,
) -> list[str]:
    """Dotted paths of the timestamps in ``data``'s signed projection not in canonical form (v1.2.0).

    Walks the registry as ``unknown_fields`` does; a value that is not a
    string (or, for a list, a list of strings) is left to validation.
    """
    registry = registry or _registry()
    spec = registry["models"].get(model)
    if spec is None or not isinstance(data, dict):
        return []
    found: list[str] = []
    for key, value in data.items():
        if projection and (key == spec.get("signature_field")
                           or ("canonical_fields" in spec and key not in spec["canonical_fields"])):
            continue
        kind = spec["fields"].get(key)
        if value is None or kind is None:
            continue
        if kind == "timestamp":
            items = value if isinstance(value, list) else [value]
            found += [f"{path}{key}" for item in items if isinstance(item, str) and not canonical_timestamp(item)][:1]
        elif isinstance(kind, dict) and "object" in kind:
            found += non_canonical_timestamps(kind["object"], value, registry, f"{path}{key}.", projection=False)
        elif isinstance(kind, dict) and "list" in kind and isinstance(value, list):
            for i, item in enumerate(value):
                found += non_canonical_timestamps(kind["list"], item, registry, f"{path}{key}.{i}.", projection=False)
        elif isinstance(kind, dict) and "map" in kind and isinstance(value, dict):
            for k, item in value.items():
                found += non_canonical_timestamps(kind["map"], item, registry, f"{path}{key}.{k}.", projection=False)
    return found


def _non_canonical(model: str, record: dict[str, Any]) -> bool:
    """True when ``record`` differs from what the reference writes back after reading it."""
    from pydantic import ValidationError

    cls = _classes().get(model)
    if cls is None:
        return False
    try:
        written = cls.model_validate(record).model_dump(mode="json", by_alias=True)
    except ValidationError:
        return False  # left to validation
    return received_canonical(model, record) != received_canonical(model, written)


def received_canonical(model: str, record: dict[str, Any], registry: dict[str, Any] | None = None) -> str:
    """The signed form of a record as received, as every SDK verifier rebuilds it.

    Unlike the models' ``to_canonical_json``, nothing unknown is dropped: a
    signature over a field this release does not know still verifies here.
    """
    registry = registry or _registry()
    spec = registry["models"][model]
    if "canonical_fields" in spec:
        body = {k: record.get(k) for k in spec["canonical_fields"]}
    else:
        omit = set(spec.get("omit_when_none", []))
        body = {k: v for k, v in record.items()
                if k != spec.get("signature_field") and not (k in omit and v is None)}
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def _signature_values(model: str, record: dict[str, Any], registry: dict[str, Any]) -> list[str]:
    field = registry["models"][model].get("signature_field")
    raw = record.get(field) if field else None
    sigs = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    return [s["sig"] for s in sigs if isinstance(s, dict) and isinstance(s.get("sig"), str)]


def signed_as_received(model: str, record: dict[str, Any], public_keys: Sequence[str]) -> bool:
    """True when a signature on ``record`` verifies over its received form."""
    from ..crypto import verify_signature

    registry = _registry()
    data = received_canonical(model, record, registry).encode("utf-8")
    return any(
        verify_signature(data, sig, key)
        for sig in _signature_values(model, record, registry) for key in public_keys
    )


def strict_refusal(model: str, record: Any, public_keys: Sequence[str]) -> str | None:
    """Why a raw record must be refused for its form, or None.

    When it has a field this release does not know, or is not in canonical
    form (v1.2.0): ``unknown_field`` or ``non_canonical_form`` when its
    signature verifies over the record as received (an authentic record from
    a newer signer, or one signed over a form the reference does not write);
    ``invalid_signature`` when the signature does not cover what was
    received. The reference checks the whole record against what it writes
    back; the SDKs check its timestamps (``non_canonical_timestamps``).
    """
    if not isinstance(record, dict):
        return None
    unknown = bool(unknown_fields(model, record))
    if not unknown and not _non_canonical(model, record):
        return None
    if not signed_as_received(model, record, public_keys):
        return "invalid_signature"
    return "unknown_field" if unknown else "non_canonical_form"


def decision_refusal(record: Any, operator_public_keys: Sequence[str], now: datetime | None = None) -> str | None:
    """Why a raw decision fails before its other checks, in the SDKs' order, or None (v1.2.0).

    ``missing_signature`` and ``decision_expired``, which every verifier
    checks before the signature, then ``strict_refusal``.
    """
    if not isinstance(record, dict):
        return None
    if record.get("signature") is None:
        return "missing_signature"
    try:
        expired = (now or datetime.now(timezone.utc)) > _DATETIME.validate_python(record.get("decision_valid_until"))
    except (ValidationError, TypeError):
        expired = False  # left to validation
    if expired:
        return "decision_expired"
    return strict_refusal("BoundaryDecision", record, operator_public_keys)


_DATETIME: TypeAdapter[datetime] = TypeAdapter(datetime)


def agreement_refusal(
    record: Any,
    offerer_public_keys: Sequence[str],
    responder_public_keys: Sequence[str],
    expected_graph_digest: str | None = None,
) -> str | None:
    """Why a raw agreement fails before its terms are checked, in the SDKs' order, or None (v1.2.0).

    The signatures over the agreement as received (an offerer's, then a
    responder's), the graph digest, then unknown fields and the canonical
    form: ``missing_offerer_signature``, ``invalid_offerer_signature``,
    ``missing_responder_signature``, ``invalid_responder_signature``,
    ``graph_digest_mismatch``, ``unknown_field``, ``non_canonical_form``.
    """
    from ..crypto import verify_signature

    if not isinstance(record, dict):
        return None
    registry = _registry()
    sigs = _signature_values("AgreementRecord", record, registry)
    if not sigs:
        return "missing_offerer_signature"
    body = received_canonical("AgreementRecord", record, registry).encode("utf-8")

    def signed(keys: Sequence[str]) -> bool:
        return any(verify_signature(body, sig, key) for sig in sigs for key in keys)

    if not signed(offerer_public_keys):
        return "invalid_offerer_signature"
    if not signed(responder_public_keys):
        return "missing_responder_signature" if len(sigs) < 2 else "invalid_responder_signature"
    if expected_graph_digest is not None and record.get("graph_digest") != expected_graph_digest:
        return "graph_digest_mismatch"
    if unknown_fields("AgreementRecord", record):
        return "unknown_field"
    if _non_canonical("AgreementRecord", record):
        return "non_canonical_form"
    return None


def intent_refusal_detail(intent: Any, policy: Any, agent_public_keys: Sequence[str]) -> str | None:
    """Why a data access intent check must refuse its inputs for their form, or None.

    Data-usage results have no reason code of their own for this; the detail
    goes into an ``intent_exceeds_license`` violation, as in every SDK, in
    this order: ``Invalid intent signature``, ``Unknown field: <paths>``,
    ``Not in canonical form: intent``, ``Not in canonical form: policy``
    (the policy's timestamps, v1.2.0).
    """
    refusal = strict_refusal("DataAccessIntent", intent, agent_public_keys)
    if refusal == "invalid_signature":
        return "Invalid intent signature"
    unknown = unknown_fields("DataAccessIntent", intent) if refusal == "unknown_field" else []
    unknown += unknown_fields("DataLicensePolicy", policy, path="policy.")
    if unknown:
        return "Unknown field: " + ", ".join(sorted(unknown))
    if refusal == "non_canonical_form":
        return "Not in canonical form: intent"
    if non_canonical_timestamps("DataLicensePolicy", policy):
        return "Not in canonical form: policy"
    return None


_CACHE: dict[str, Any] = {}


def _registry() -> dict[str, Any]:
    if "registry" not in _CACHE:
        _CACHE["registry"] = build_registry()
    return _CACHE["registry"]
