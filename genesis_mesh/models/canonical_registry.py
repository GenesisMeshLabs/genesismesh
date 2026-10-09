"""The field registry of signed records (v1.2.0).

A verifier that copies every field of a record into the signed form accepts a
field it does not understand whenever the signer covered it, so a field added
in a later release can change what a record means for older verifiers. Since
1.2.0 verifiers know every field: a record carrying a field the registry does
not list is refused (``unknown_field``), and a new field reaches every
verifier before the Network Authority emits it.

The registry is generated from the Python models, which define the canonical
forms. Each model lists its fields; a field is

* ``null``: a value (string, number, boolean, timestamp, or a list of them);
* ``"open"``: free-form JSON chosen by the signer (``claims``, ``scope``,
  ``execution_parameters``...), whose keys are not checked;
* ``{"object": M}``, ``{"list": M}`` or ``{"map": M}``: one, a list, or a
  string-keyed map of model ``M``, checked in turn.

Roots also carry their canonical rules: the signature field (excluded from
the signed form), the optional fields omitted from it when absent, and for
agreements the fixed list of signed fields. Every other optional field is
signed as present, null included.

``conformance/vectors/canonical.json`` carries the registry to the SDKs; a
test fails when it differs from the models.
"""

from __future__ import annotations

import enum
import types
import typing
from datetime import date, datetime
from typing import Any, Union

from pydantic import BaseModel

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

REGISTRY_VERSION = 1


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


def _is_model(tp: Any) -> bool:
    return isinstance(tp, type) and issubclass(tp, BaseModel)


def _kind(tp: Any, models: dict[str, type[BaseModel]]) -> Any:
    """The registry entry for one annotation (see the module docstring)."""
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is typing.Annotated:
        return _kind(args[0], models)
    if origin in (Union, types.UnionType):
        kinds = [_kind(a, models) for a in args if a is not type(None)]
        distinct = [k for i, k in enumerate(kinds) if k not in kinds[:i]]
        if len(distinct) == 1:
            return distinct[0]
        if "open" in distinct:
            return "open"
        structured = [k for k in distinct if k is not None]
        return structured[0] if len(structured) == 1 else "open"
    if _is_model(tp):
        models[tp.__name__] = tp
        return {"object": tp.__name__}
    if origin in (list, tuple, set, frozenset) or tp in (list, tuple, set, frozenset):
        inner = [_kind(a, models) for a in args if a is not Ellipsis]
        inner_kind = inner[0] if inner else "open"
        if isinstance(inner_kind, dict) and "object" in inner_kind:
            return {"list": inner_kind["object"]}
        return "open" if inner_kind == "open" or isinstance(inner_kind, dict) else None
    if origin is dict or tp is dict:
        value = _kind(args[1], models) if len(args) == 2 else "open"
        if isinstance(value, dict) and "object" in value:
            return {"map": value["object"]}
        return "open"
    if tp is Any or tp is object:
        return "open"
    if origin is typing.Literal or isinstance(tp, type) and issubclass(tp, (str, int, float, bool, enum.Enum, datetime, date)):
        return None
    return "open"


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


def unknown_fields(model: str, data: Any, registry: dict[str, Any] | None = None, path: str = "") -> list[str]:
    """Dotted paths of the fields in ``data`` that ``model`` does not define.

    Free-form fields are not inspected; values of the wrong type are left to
    model validation.
    """
    registry = registry or _registry()
    spec = registry["models"].get(model)
    if spec is None or not isinstance(data, dict):
        return []
    found: list[str] = []
    for key, value in data.items():
        if key not in spec["fields"]:
            found.append(f"{path}{key}")
            continue
        kind = spec["fields"][key]
        if value is None or not isinstance(kind, dict):
            continue
        if "object" in kind:
            found += unknown_fields(kind["object"], value, registry, f"{path}{key}.")
        elif "list" in kind and isinstance(value, list):
            for i, item in enumerate(value):
                found += unknown_fields(kind["list"], item, registry, f"{path}{key}.{i}.")
        elif "map" in kind and isinstance(value, dict):
            for k, item in value.items():
                found += unknown_fields(kind["map"], item, registry, f"{path}{key}.{k}.")
    return found


_CACHE: dict[str, Any] = {}


def _registry() -> dict[str, Any]:
    if "registry" not in _CACHE:
        _CACHE["registry"] = build_registry()
    return _CACHE["registry"]
