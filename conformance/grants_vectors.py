"""The ``grants`` conformance suite (v1.6.0, Stage 5): pre-issued grants.

``grants_vectors()`` builds every vector deterministically (fixed seeds,
times and identifiers; Ed25519 signatures are deterministic) and fills
``expected`` with ``evaluate``, the Python reference's verdict; the runner
calls ``evaluate`` again on each vector's input and compares. Reason codes
are the contract: every verifier must name the same ones for the same input.

Kinds:

``canonical_form`` / ``verify_record``
    The signed forms of the new records and their signatures (also a
    revocation feed listing revoked grants, and one in its 1.5 form).
``envelope_parameter``
    Envelope parameters as the reference reads them: valid or refused, and
    their normalized form (an integral number is an integer; sets are
    type-strict).
``envelope``
    Whether a use's ``request_parameters`` are inside a grant's closed
    envelope (``grant_envelope_mismatch`` otherwise).
``issuance``
    The NA's issuance check (``trust.grants.check_grant``): per gate type,
    decided over the envelope (``pass``, ``may_fail``), every undecidable
    case by name, selectors, policy validity, the basis checks. The NA runs
    it; an SDK may skip these vectors.
``use``
    The rules a use is checked by (``trust.grants.use_problem``), in order,
    with what a holder or verifier holds of its chain.
``verify_export``
    Stores holding grants, their uses (with the NA's resource positions),
    revocations, quarantined uses and observations governed by a grant:
    which verify, and variants refused by named reason.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import nacl.signing

SEEDS = {
    "a": bytes(range(32)),       # an observer
    "b": bytes(range(32, 64)),   # the holder (a registered executor key)
    "c": bytes(range(64, 96)),   # the NA
    "d": bytes(range(96, 128)),  # another executor key
}
KEYS = {k: nacl.signing.SigningKey(v) for k, v in SEEDS.items()}

#: A Monday, 08:00 UTC.
T0 = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
NA_SOVEREIGN = "sovereign-c"
DEVICE = "device-b"
VENDOR = "vendor-acme"
RESOURCE = "kv:vault/api-key"
CAPABILITY = "secret.rotate"


def pub(key: str) -> str:
    import base64

    return base64.b64encode(bytes(KEYS[key].verify_key)).decode()


def uid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def _iso(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _signed(record: Any, key: str, key_id: str) -> Any:
    from genesis_mesh.crypto import sign_model

    return record.model_copy(update={"signature": sign_model(record.model_copy(update={"signature": None}),
                                                             KEYS[key], key_id)})


def _registry(extra: list[str]) -> Any:
    """The built-in gate types, and (for the undecidable cases) operator gate types that always pass."""
    from pydantic import BaseModel, ConfigDict

    from genesis_mesh.trust.context import GateRegistry
    from genesis_mesh.trust.context.registry import ConfiguredGateOutcome

    class Empty(BaseModel):
        model_config = ConfigDict(extra="forbid")

    registry = GateRegistry.builtin()
    for name in extra:
        gate = type("OperatorGate", (), {
            "gate_type": name, "config_model": Empty,
            "evaluate": lambda self, context, config, *, disclose_input: ConfiguredGateOutcome(
                passed=True, outcome="pass", detail="ok"),
        })()
        registry.register(gate)
    return registry.freeze()


def evaluate(vector: dict[str, Any]) -> dict[str, Any]:
    """What the Python reference makes of one vector's input (the runner compares it with ``expected``)."""
    from pydantic import ValidationError

    from genesis_mesh.models.boundary_policy import BoundaryPolicy
    from genesis_mesh.models.canonical_registry import received_canonical, signed_as_received
    from genesis_mesh.models.grants import CapabilityGrant, EnvelopeParameter, GrantExecutionEvidence
    from genesis_mesh.trust.evidence_store import ExecutorKey, parse_export_lines, verify_evidence_events
    from genesis_mesh.trust.grants import GrantBasis, PreviousUse, check_grant, envelope_problem, use_problem

    kind, inp = vector["kind"], vector.get("input", {})

    def when(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None

    if kind == "canonical_form":
        body = received_canonical(vector["model"], vector["record"])
        return {"canonical": body, "digest": hashlib.sha256(body.encode()).hexdigest()}
    if kind == "verify_record":
        return {"valid": signed_as_received(vector["model"], vector["record"], [vector["public_key"]])}
    if kind == "envelope_parameter":
        try:
            spec = EnvelopeParameter.model_validate(inp["parameter"])
        except (ValidationError, ValueError):
            return {"valid": False}
        return {"valid": True, "normalized": spec.model_dump(mode="json")}
    if kind == "envelope":
        envelope = {k: EnvelopeParameter.model_validate(v) for k, v in inp["envelope"].items()}
        return {"within": envelope_problem(envelope, inp["request_parameters"]) is None}
    if kind == "issuance":
        from genesis_mesh.models.agreement import AgreementRecord
        from genesis_mesh.models.sovereign import MembershipAttestation
        from genesis_mesh.trust.context import assess_attestation_basis

        basis_in = inp["basis"]
        if basis_in["kind"] == "attestation":
            att = MembershipAttestation.model_validate(basis_in["attestation"])
            assessed = assess_attestation_basis(
                att.attestation_id, att, issuer_public_keys=inp["policy_public_keys"],
                stored_status=basis_in.get("stored_status", "active"), feed_revoked=False, revocation_seq_checked=0,
                requester_id=att.subject_id)
            basis = GrantBasis.of_attestation(assessed, basis_in["provider_sovereign_id"])
        else:
            basis = GrantBasis.of_agreement(AgreementRecord.model_validate(basis_in["agreement"]),
                                            context_freshness_seq=basis_in.get("context_freshness_seq", 0))
        check = check_grant(
            capabilities=inp["capabilities"],
            envelope={k: EnvelopeParameter.model_validate(v) for k, v in inp["envelope"].items()},
            valid_from=when(inp["valid_from"]), valid_until=when(inp["valid_until"]), basis=basis,  # type: ignore[arg-type]
            policies=[BoundaryPolicy.model_validate(p) for p in inp["policies"]],
            registry=_registry(inp.get("operator_gate_types", [])), policy_public_keys=inp["policy_public_keys"],
            integrity_failures=inp.get("integrity_failures", []),
        )
        return {
            "allowed": check.allowed, "reason": check.reason, "reasons": [p.reason for p in check.problems],
            "gate_outcomes": [[o.capability, o.policy_id, o.gate_id, o.mode, o.outcome] for o in check.gate_outcomes],
            "policies": [[p.policy_id, p.version] for p in check.applied],
        }
    if kind == "use":
        grant = CapabilityGrant.model_validate(inp["grant"]) if inp.get("grant") else None
        use = GrantExecutionEvidence.model_validate(inp["use"])
        prev = inp.get("previous")
        previous = PreviousUse(
            digest=prev["digest"], executed_at=when(prev["executed_at"]), time_token_id=prev["time_token_id"],  # type: ignore[arg-type]
            time_token_issued_at=when(prev["time_token_issued_at"]), token_uses=prev["token_uses"],  # type: ignore[arg-type]
        ) if prev else None
        head = inp.get("token_head")
        found = use_problem(
            use, grant=grant, previous=previous,
            token_head=(head["digest"], when(head["executed_at"])) if head else None,  # type: ignore[arg-type]
            token_keys=inp["na_public_keys"], raw_token=inp["use"].get("time_token"),
            revoked_at=when(inp.get("revoked_at")), recorded_at=when(inp.get("recorded_at")),
        )
        return {"code": found[0] if found else None}
    if kind == "verify_export":
        keys = {r["key_id"]: ExecutorKey(key_id=r["key_id"], public_key=r["public_key"],
                                         executor_sovereign_id=r["executor_sovereign_id"], role=r["role"])
                for r in inp["executor_keys"]}
        result = verify_evidence_events(parse_export_lines(inp["lines"].split("\n")),
                                        na_public_keys=inp["na_public_keys"], executor_keys=keys,
                                        contiguous=inp.get("contiguous", True))
        found = sorted({(f["store_sequence"], f["reason"]) for f in result.failures}, key=lambda f: (f[0] or 0, f[1]))
        counts = {k: v for k, v in result.to_dict().items() if k in (
            "executions", "observations", "judgements", "quarantined", "grants", "grant_executions",
            "grant_revocations")}
        return {"verified": result.verified, "failures": [{"store_sequence": s, "reason": r} for s, r in found],
                "counts": counts}
    raise ValueError(f"unknown kind {kind}")


# ---------------------------------------------------------------------------
# The vectors
# ---------------------------------------------------------------------------


def _attestation(**claims: Any) -> dict[str, Any]:
    from genesis_mesh.models.sovereign import MembershipAttestation
    from genesis_mesh.crypto import sign_model

    att = MembershipAttestation(
        attestation_id=uid(1), issuer_sovereign_id=NA_SOVEREIGN, subject_id=VENDOR, roles=["role:client"],
        status="active", issued_at=T0 - timedelta(days=1), valid_from=T0 - timedelta(days=1),
        expires_at=T0 + timedelta(days=7), issued_by="na-key",
        claims={"capabilities": [CAPABILITY], **claims},
    )
    att.signatures.append(sign_model(att, KEYS["c"], "na-key"))
    return att.model_dump(mode="json")


def _policy(gates: list[dict], *, policy_id: str = "secret-limits", version: int = 1, selector: dict | None = None,
            valid_from: datetime = T0 - timedelta(days=1), valid_until: datetime = T0 + timedelta(days=30),
            **sections: Any) -> dict[str, Any]:
    from genesis_mesh.models.boundary_policy import BoundaryPolicy
    from genesis_mesh.trust.context import sign_boundary_policy

    policy = BoundaryPolicy(
        policy_id=policy_id, version=version, description="grant conformance", valid_from=valid_from,
        valid_until=valid_until, selector=selector if selector is not None else {"capabilities": [CAPABILITY]},
        gates=[{"gate_id": f"gate-{i}", "order": i, **g} for i, g in enumerate(gates)],
        issued_at=T0 - timedelta(days=1), issued_by="na-key", issuer_sovereign_id=NA_SOVEREIGN, **sections,
    )
    return sign_boundary_policy(policy, KEYS["c"], "na-key").model_dump(mode="json")


def _int_range(low: int, high: int, **flags: bool) -> dict[str, Any]:
    return {"number_range": {"number_type": "integer", "minimum": low, "maximum": high, **flags}}


def _issuance_vectors() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    attestation = _attestation(apps=["billing", "payroll"])

    def case(vid: str, desc: str, envelope: dict, policies: list[dict], *, hours: float = 4,
             start: datetime = T0, capabilities: list[str] | None = None, basis: dict | None = None,
             expect_reason: str | None | bool = False, **extra: Any) -> None:
        inp = {
            "capabilities": capabilities or [CAPABILITY], "envelope": envelope,
            "valid_from": _iso(start), "valid_until": _iso(start + timedelta(hours=hours)),
            "basis": basis or {"kind": "attestation", "attestation": attestation,
                               "provider_sovereign_id": NA_SOVEREIGN},
            "policies": policies, "policy_public_keys": [pub("c")], **extra,
        }
        vector = {"id": f"issuance-{vid}", "kind": "issuance", "description": desc, "input": inp}
        vector["expected"] = evaluate(vector)
        if expect_reason is not False:
            assert vector["expected"]["reason"] == expect_reason, (vid, vector["expected"])
        out.append(vector)

    path = "request_parameters.n"

    def gate(gate_type: str, **config: Any) -> dict[str, Any]:
        return {"gate_type": gate_type, "config": config}

    # Per gate type: an envelope every value of which passes, and one with a value that may fail.
    per_type = [
        ("max-value", gate("max_value.v1", path=path, max=90), {"n": _int_range(1, 90)}, {"n": _int_range(1, 91)}),
        ("max-value-exclusive", gate("max_value.v1", path=path, max=90, inclusive=False),
         {"n": _int_range(1, 90, exclusive_maximum=True)}, {"n": _int_range(1, 90)}),
        ("max-value-number-range", gate("max_value.v1", path=path, max=90),
         {"n": {"number_range": {"number_type": "number", "minimum": 0, "maximum": 90}}},
         {"n": {"number_range": {"number_type": "number", "minimum": 0, "maximum": 90.5}}}),
        ("max-value-exact-integers", gate("max_value.v1", path=path, max=float(2**53)),
         {"n": _int_range(1, 2**53)}, {"n": _int_range(1, 2**53 + 1)}),
        ("max-value-boolean", gate("max_value.v1", path=path, max=90), {"n": {"one_of": [1, 2.5]}},
         {"n": {"one_of": [1, True]}}),
        ("min-value", gate("min_value.v1", path=path, min=10), {"n": _int_range(10, 20)},
         {"n": _int_range(9, 20)}),
        ("min-value-exclusive", gate("min_value.v1", path=path, min=10, inclusive=False),
         {"n": _int_range(10, 20, exclusive_minimum=True)}, {"n": _int_range(10, 20)}),
        ("allowlist", gate("allowlist.v1", path="request_parameters.region", values=["eu-west", "eu-north", 1]),
         {"region": {"one_of": ["eu-west", 1.0]}}, {"region": {"one_of": ["eu-west", "us-east"]}}),
        ("allowlist-type-strict", gate("allowlist.v1", path="request_parameters.region", values=[1, "1"]),
         {"region": {"one_of": [1, "1"]}}, {"region": {"one_of": [True]}}),
        ("allowlist-integer-range", gate("allowlist.v1", path=path, values=[1, 2, 3]), {"n": _int_range(1, 3)},
         {"n": _int_range(1, 4)}),
        ("denylist", gate("denylist.v1", path="request_parameters.region", values=["us-east", 0]),
         {"region": {"one_of": ["eu-west", False]}}, {"region": {"one_of": ["eu-west", "us-east"]}}),
        ("denylist-range", gate("denylist.v1", path=path, values=[0, 5.0]),
         {"n": _int_range(5, 9, exclusive_minimum=True)}, {"n": _int_range(1, 9)}),
        ("scope-membership", gate("scope_membership.v1", path="request_parameters.scopes",
                                  allowed=["read", "write", "admin"]),
         {"scopes": {"subset_of": ["read", "write"]}}, {"scopes": {"subset_of": ["read", "delete"]}}),
        ("required-parameter", gate("required_parameter.v1", path="request_parameters.owner"),
         {"owner": {"one_of": ["team-a"]}}, {"owner": {"one_of": ["team-a", None]}}),
        ("required-parameter-optional", gate("required_parameter.v1", path="request_parameters.owner"),
         {"owner": {"one_of": ["team-a"]}}, {"owner": {"one_of": ["team-a"], "required": False}}),
        ("boolean-required", gate("boolean_required.v1", path="request_parameters.reviewed", expected=True),
         {"reviewed": {"one_of": [True]}}, {"reviewed": {"one_of": [True, False]}}),
        ("attestation-claim", gate("attestation_claim.v1", path="request_parameters.app", claim="apps"),
         {"app": {"one_of": ["billing", "payroll"]}}, {"app": {"one_of": ["billing", "hr"]}}),
        ("parent-kind-grant", gate("denylist.v1", path="parent_kind", values=["break_glass"]), {},
         None),
    ]
    for vid, g, passing, failing in per_type:
        case(f"{vid}-pass", f"{g['gate_type']}: every value of the envelope passes", passing, [_policy([g])],
             expect_reason=None)
        if failing is not None:
            case(f"{vid}-may-deny", f"{g['gate_type']}: a value of the envelope may fail", failing, [_policy([g])],
                 expect_reason="grant_gate_may_deny")
    case("parent-kind-denied", "A policy forbidding grants (denylist on parent_kind grant)", {},
         [_policy([gate("denylist.v1", path="parent_kind", values=["grant"])])], expect_reason="grant_gate_may_deny")
    office = gate("time_window.v1", weekdays=[1, 2, 3, 4, 5], utc_hour_start=7, utc_hour_end=19)
    case("time-window-pass", "time_window.v1: the whole validity (Monday 08:00 to 12:00) lies inside the window",
         {}, [_policy([office])], expect_reason=None)
    case("time-window-may-deny", "time_window.v1: the validity reaches 20:00", {}, [_policy([office])], hours=12,
         expect_reason="grant_gate_may_deny")
    case("time-window-weekend", "time_window.v1: a Saturday", {}, [_policy([office])],
         start=T0 + timedelta(days=5), hours=1, expect_reason="grant_gate_may_deny")
    # What cannot be decided, by name.
    for vid, g, reason in (
        ("attributes", gate("allowlist.v1", path="attributes.owner", values=["a"]), "grant_undecidable_attributes"),
        ("freshness", gate("min_value.v1", path="context_freshness_seq", min=1), "grant_undecidable_freshness"),
        ("time", gate("required_parameter.v1", path="requested_at"), "grant_undecidable_time"),
        ("gate-type", gate("risk_score.v1"), "grant_undecidable_gate_type"),
    ):
        case(f"undecidable-{vid}", f"A gate that cannot be decided over a grant: {reason}", {}, [_policy([g])],
             operator_gate_types=["risk_score.v1"], expect_reason=reason)
    case("undecidable-selector", "A selector reading attributes cannot be decided", {"n": _int_range(1, 2)},
         [_policy([gate("required_parameter.v1", path=path)],
                  selector={"capabilities": [CAPABILITY], "parameter_equals": {"attributes.tier": ["high"]}})],
         expect_reason="grant_undecidable_attributes")
    case("observe-mode", "An observe-mode gate never refuses; its outcome is recorded", {"n": _int_range(1, 9)},
         [_policy([{**gate("max_value.v1", path=path, max=5), "mode": "observe"}])], expect_reason=None)
    # Selectors: the part of the envelope a policy selects.
    regional = _policy([gate("max_value.v1", path=path, max=5)],
                       selector={"capabilities": [CAPABILITY],
                                 "parameter_equals": {"request_parameters.region": ["eu-west"]}})
    case("selector-other-part", "A policy for another region does not apply",
         {"region": {"one_of": ["us-east"]}, "n": _int_range(1, 50)}, [regional], expect_reason=None)
    case("selector-selected-part", "A policy applies to the part of the envelope it selects",
         {"region": {"one_of": ["us-east", "eu-west"]}, "n": _int_range(1, 50)}, [regional],
         expect_reason="grant_gate_may_deny")
    for kinds, reason in ((["attestation"], "grant_gate_may_deny"), (["grant"], "grant_gate_may_deny"),
                          (["direct"], None)):
        case(f"selector-parent-kinds-{kinds[0]}", f"A selector naming parent kinds {kinds}", {"n": _int_range(1, 50)},
             [_policy([gate("max_value.v1", path=path, max=5)],
                      selector={"capabilities": [CAPABILITY], "parent_kinds": kinds})], expect_reason=reason)
    # Validity, review and resolution.
    limit = [gate("max_value.v1", path=path, max=90)]
    case("outlives-policy", "The grant ends after a policy that applies", {"n": _int_range(1, 9)},
         [_policy(limit, valid_until=T0 + timedelta(hours=2))], expect_reason="grant_outlives_policy")
    case("policy-scheduled", "A policy that applies starts inside the grant's validity", {"n": _int_range(1, 9)},
         [_policy(limit, valid_from=T0 + timedelta(hours=1))], expect_reason="grant_policy_scheduled")
    case("policy-after", "A policy that starts after the grant ends does not apply", {"n": _int_range(1, 9)},
         [_policy(limit, valid_from=T0 + timedelta(hours=5))], expect_reason=None)
    case("review-required", "A policy that requires review applies to no grant", {"n": _int_range(1, 9)},
         [_policy(limit, review_required=True)], expect_reason="grant_review_required")
    unsigned = {k: v for k, v in _policy(limit).items() if k != "signature"}
    case("unsigned-policy", "An active policy the NA did not sign refuses every grant", {"n": _int_range(1, 9)},
         [unsigned], expect_reason="grant_policy_resolution_failed")
    # The basis.
    case("basis-revoked", "The basis attestation is revoked", {}, [], expect_reason="grant_basis_invalid",
         basis={"kind": "attestation", "attestation": attestation, "provider_sovereign_id": NA_SOVEREIGN,
                "stored_status": "revoked"})
    case("outlives-basis", "The grant ends after its attestation", {}, [], hours=24,
         start=T0 + timedelta(days=6, hours=12), expect_reason="grant_outlives_basis")
    case("capability-out-of-scope", "A capability the attestation does not grant", {}, [],
         capabilities=["secret.delete"], expect_reason="grant_capability_out_of_scope")
    return out


def _envelope_vectors() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for vid, desc, parameter in (
        ("integer-range", "An integer range", _int_range(1, 90)),
        ("integral-float-bounds", "An integer range with bounds written 1.0: read as integers", {
            "number_range": {"number_type": "integer", "minimum": 1.0, "maximum": 90}}),
        ("number-range-exclusive", "A number range with an exclusive bound", {
            "number_range": {"number_type": "number", "minimum": 0, "maximum": 1.5, "exclusive_maximum": True}}),
        ("one-of", "A set of scalars, an integral float read as an integer", {"one_of": ["a", 5.0, True, None]}),
        ("subset-of", "A set of strings a list draws from, optional", {"subset_of": ["read", "write"],
                                                                        "required": False}),
        ("one-of-repeats", "1 and 1.0 are one value: refused", {"one_of": [1, 1.0]}),
        ("one-of-true-and-one", "true and 1 are two values", {"one_of": [1, True]}),
        ("two-kinds", "one_of and subset_of together: refused", {"one_of": ["a"], "subset_of": ["a"]}),
        ("no-kind", "No kind: refused", {}),
        ("integer-range-fraction", "An integer range with a fractional bound: refused", {
            "number_range": {"number_type": "integer", "minimum": 1.5, "maximum": 3}}),
        ("empty-integer-range", "An integer range holding no integer: refused", _int_range(3, 3, exclusive_minimum=True)),
        ("boolean-bound", "A boolean bound: refused", {"number_range": {"number_type": "number", "minimum": True,
                                                                         "maximum": 3}}),
        ("bound-beyond-64-bits", "An integer bound beyond 64 bits: refused", _int_range(0, 2**64)),
        ("object-value", "An object in one_of: refused", {"one_of": [{"a": 1}]}),
    ):
        vector = {"id": f"parameter-{vid}", "kind": "envelope_parameter", "description": desc,
                  "input": {"parameter": parameter}}
        vector["expected"] = evaluate(vector)
        out.append(vector)
    envelope = {"n": _int_range(1, 9), "region": {"one_of": ["eu-west", 1]},
                "tags": {"subset_of": ["a", "b"], "required": False}}
    for vid, params, within in (
        ("inside", {"n": 9, "region": "eu-west"}, True),
        ("integral-float", {"n": 9.0, "region": 1.0, "tags": []}, True),
        ("above-range", {"n": 10, "region": "eu-west"}, False),
        ("fraction-in-integer-range", {"n": 2.5, "region": "eu-west"}, False),
        ("boolean-as-number", {"n": True, "region": "eu-west"}, False),
        ("boolean-as-one", {"n": 1, "region": True}, False),
        ("string-as-number", {"n": 1, "region": "1"}, False),
        ("missing-required", {"region": "eu-west"}, False),
        ("outside-closed-envelope", {"n": 1, "region": "eu-west", "x": 1}, False),
        ("list-item-outside", {"n": 1, "region": "eu-west", "tags": ["c"]}, False),
        ("list-expected", {"n": 1, "region": "eu-west", "tags": "a"}, False),
    ):
        vector = {"id": f"envelope-{vid}", "kind": "envelope", "description": f"request_parameters {params}",
                  "input": {"envelope": envelope, "request_parameters": params}}
        vector["expected"] = evaluate(vector)
        assert vector["expected"]["within"] is within, vid
        out.append(vector)
    return out


def _grant(**overrides: Any) -> Any:
    from genesis_mesh.models.boundary_policy import AppliedPolicy, policy_set_digest
    from genesis_mesh.models.grants import CapabilityGrant, EnvelopeParameter

    applied = [AppliedPolicy(policy_id="secret-limits", version=1, policy_digest="d" * 64, signed_by="na-key")]
    fields: dict[str, Any] = dict(
        grant_id=uid(10), bearer_key_id="executor-b", bearer_public_key=pub("b"), bearer_sovereign_id=DEVICE,
        capabilities=[CAPABILITY], basis_kind="attestation", basis_id=uid(1), basis_digest="e" * 64,
        requester_sovereign_id=VENDOR, provider_sovereign_id=NA_SOVEREIGN, valid_from=T0,
        valid_until=T0 + timedelta(hours=4), max_uses=3, max_uses_per_time_token=2,
        parameter_envelope={"lifetime_days": EnvelopeParameter.model_validate(_int_range(1, 90))},
        policy_binding={"policies": [a.model_dump() for a in applied], "policy_set_digest": policy_set_digest(applied)},
        issued_at=T0, issuer_sovereign_id=NA_SOVEREIGN, issued_by="na-key",
    )
    fields.update(overrides)
    return _signed(CapabilityGrant(**fields), "c", "na-key")


def _token(at: datetime, sequence: int = 0, head: str | None = None, n: int = 30, key: str = "c") -> Any:
    from genesis_mesh.models.grants import TimeToken

    return _signed(TimeToken(time_token_id=uid(n), grant_id=uid(10), use_sequence=sequence, use_head_digest=head,
                             issued_at=at, issuer_sovereign_id=NA_SOVEREIGN, issued_by="na-key"), key, "na-key")


def _use(grant: Any, n: int, at: datetime, token: Any, prev: str | None, key: str = "b", key_id: str = "executor-b",
         **overrides: Any) -> Any:
    from genesis_mesh.models.grants import GrantExecutionEvidence

    fields: dict[str, Any] = dict(
        use_id=uid(100 + n), grant_id=grant.grant_id, grant_digest=grant.digest(), use_sequence=n,
        prev_use_digest=prev, executor_sovereign_id=DEVICE, capability=CAPABILITY,
        request_parameters={"lifetime_days": 30}, resource_id=RESOURCE, resource_action="rotate", executed_at=at,
        time_token=token, outcome="success", execution_parameters={"version_id": f"v{n}"},
    )
    fields.update(overrides)
    return _signed(GrantExecutionEvidence(**fields), key, key_id)


def _use_vectors() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    grant = _grant()
    token = _token(T0)
    at = T0 + timedelta(minutes=5)
    first = _use(grant, 1, at, token, None)

    def case(vid: str, desc: str, use: Any, *, expect: str | None, with_grant: bool = True, previous: dict | None = None,
             token_head: dict | None = None, revoked_at: datetime | None = None,
             recorded_at: datetime | None = None) -> None:
        inp = {"grant": grant.to_wire() if with_grant else None, "use": use.to_wire(), "previous": previous,
               "token_head": token_head, "revoked_at": _iso(revoked_at) if revoked_at else None,
               "recorded_at": _iso(recorded_at or use.executed_at), "na_public_keys": [pub("c")]}
        vector = {"id": f"use-{vid}", "kind": "use", "description": desc, "input": inp}
        vector["expected"] = evaluate(vector)
        assert vector["expected"]["code"] == expect, (vid, vector["expected"])
        out.append(vector)

    previous = {"digest": first.digest(), "executed_at": _iso(at), "time_token_id": token.time_token_id,
                "time_token_issued_at": _iso(token.issued_at), "token_uses": 2}
    fresh = _token(T0 + timedelta(minutes=6), 1, first.digest(), n=31)
    case("admitted", "A use inside its grant", first, expect=None)
    case("capability", "A capability the grant does not name", _use(grant, 1, at, token, None,
                                                                   capability="secret.delete"),
         expect="grant_capability_mismatch")
    case("envelope", "A parameter outside the envelope", _use(grant, 1, at, token, None,
                                                             request_parameters={"lifetime_days": 400}),
         expect="grant_envelope_mismatch")
    case("budget", "A use past the budget", _use(grant, 4, at, fresh, "1" * 64), expect="grant_budget_exhausted")
    case("token-other-grant", "A time token of another grant", _use(grant, 1, at, _token(T0).model_copy(
        update={"grant_id": uid(11)}), None), expect="grant_time_token_invalid")
    case("token-other-key", "A time token signed by another key", _use(grant, 1, at, _token(T0, key="d"), None),
         expect="grant_time_token_invalid")
    case("token-after-use", "A time token issued after a later use than this one",
         _use(grant, 1, at, _token(T0, 1, "2" * 64, n=32), None), expect="grant_time_token_mismatch")
    case("token-head", "A time token naming another use than the store holds",
         _use(grant, 2, at + timedelta(minutes=2), fresh, first.digest()), previous=previous,
         token_head={"digest": "9" * 64, "executed_at": _iso(at)}, expect="grant_time_token_mismatch")
    case("token-head-later", "The use a time token names is dated after the token",
         _use(grant, 2, at + timedelta(minutes=12), fresh, first.digest()), previous=previous,
         token_head={"digest": first.digest(), "executed_at": _iso(fresh.issued_at + timedelta(minutes=6))},
         expect="grant_time_token_mismatch")
    case("token-regressed", "A time token older than the previous use's",
         _use(grant, 2, at + timedelta(minutes=2), _token(T0 - timedelta(minutes=1), n=33), first.digest()),
         previous=previous, expect="grant_time_token_regressed")
    case("token-exhausted", "A third use citing one time token (two allowed)",
         _use(grant, 2, at + timedelta(minutes=2), token, first.digest()), previous=previous,
         expect="grant_time_token_exhausted")
    case("before-token", "A use dated before its time token", _use(grant, 1, T0 - timedelta(seconds=1), token, None),
         expect="grant_use_before_time_token")
    case("out-of-order", "A use dated before the previous use",
         _use(grant, 2, at - timedelta(minutes=1), _token(T0 + timedelta(minutes=1), 1, first.digest(), n=34),
              first.digest()), previous=previous, expect="grant_use_out_of_order")
    case("outside-validity", "A use after the grant ends",
         _use(grant, 1, T0 + timedelta(hours=4, seconds=1), token, None), expect="grant_use_outside_validity")
    case("in-future", "A use dated more than 300 s after it is recorded", first,
         recorded_at=at - timedelta(seconds=301), expect="grant_use_in_future")
    case("skew", "A use dated up to 300 s after it is recorded", first, recorded_at=at - timedelta(seconds=300),
         expect=None)
    case("uploaded-late", "A use recorded longer after it was made than the grant's validity", first,
         recorded_at=at + timedelta(hours=4, seconds=1), expect="grant_use_uploaded_late")
    case("revoked", "A use made at or after the grant's revocation", first, revoked_at=at, expect="grant_revoked")
    case("before-revocation", "A use made before the grant's revocation", first,
         revoked_at=at + timedelta(seconds=1), expect=None)
    case("without-grant", "A verifier without the grant checks what it can",
         _use(grant, 4, at, _token(T0, 3, "1" * 64, n=35), "1" * 64, request_parameters={"lifetime_days": 400}),
         with_grant=False, expect=None)
    return out


def _records() -> dict[str, Any]:
    """Signed samples of the new records (the field registry's), for canonical forms and signatures."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from generate_vectors import grant_sample_records
    finally:
        sys.path.pop(0)
    return grant_sample_records()


def _record_vectors() -> list[dict[str, Any]]:
    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models.sovereign import SovereignRevocationFeed

    out: list[dict[str, Any]] = []
    records = _records()
    for model, record in sorted(records.items()):
        wire = record.to_wire()
        vector = {"id": f"canonical-{model}", "kind": "canonical_form", "description": f"The signed form of a {model}",
                  "model": model, "record": wire}
        vector["expected"] = evaluate(vector)
        assert vector["expected"]["canonical"] == record.to_canonical_json(), model
        out.append(vector)
        signer = pub("b") if model in ("GrantExecutionEvidence", "TimeTokenRequest") else pub("c")
        for vid, key, valid in (("signer", signer, True), ("other-key", pub("d"), False)):
            vector = {"id": f"signature-{model}-{vid}", "kind": "verify_record", "description": f"{model} signature",
                      "model": model, "record": wire, "public_key": key}
            vector["expected"] = evaluate(vector)
            assert vector["expected"]["valid"] is valid, (model, vid)
            out.append(vector)
    # A use's time token as received: no use_head_digest before the first use.
    token = _token(T0)
    vector = {"id": "canonical-TimeToken-first", "kind": "canonical_form", "model": "TimeToken",
              "description": "A time token before the first use: use_head_digest left out", "record": token.to_wire()}
    vector["expected"] = evaluate(vector)
    assert "use_head_digest" not in vector["expected"]["canonical"]
    out.append(vector)
    # The revocation feed: revoked grants listed (EVIDENCE_GRANTS=on), and the 1.5 form without the field.
    for vid, grants in (("with-grants", [uid(12), uid(10)]), ("without-grants", None)):
        feed = SovereignRevocationFeed(
            feed_id=uid(40), issuer_sovereign_id=NA_SOVEREIGN, sequence=3 if grants else 1, issued_at=T0,
            revoked_attestation_ids=[uid(1)], revocation_reasons={uid(1): "offboarded"},
            revoked_grant_ids=grants, issued_by="na-key",
        )
        feed.signatures.append(sign_model(feed, KEYS["c"], "na-key"))
        wire = feed.model_dump(mode="json")
        vector = {"id": f"canonical-feed-{vid}", "kind": "canonical_form", "model": "SovereignRevocationFeed",
                  "description": f"A revocation feed {vid.replace('-', ' ')}", "record": wire}
        vector["expected"] = evaluate(vector)
        out.append(vector)
        vector = {"id": f"signature-feed-{vid}", "kind": "verify_record", "model": "SovereignRevocationFeed",
                  "description": f"A revocation feed {vid.replace('-', ' ')}: signed as received", "record": wire,
                  "public_key": pub("c")}
        vector["expected"] = evaluate(vector)
        assert vector["expected"]["valid"]
        out.append(vector)
    return out


def _export_vectors() -> list[dict[str, Any]]:
    from genesis_mesh.models.evidence_store import EvidenceEvent, payload_digest
    from genesis_mesh.models.execution import ExecutionEvidence
    from genesis_mesh.models.grants import GrantRevocationRecord
    from genesis_mesh.models.out_of_band import JudgementRecord, ObservationRecord, QuarantineRecord
    from genesis_mesh.trust.evidence_store import build_entry, execution_index
    from genesis_mesh.trust.out_of_band import entry_index

    out: list[dict[str, Any]] = []
    keys = [
        {"key_id": "executor-b", "public_key": pub("b"), "executor_sovereign_id": DEVICE, "role": "executor"},
        {"key_id": "executor-d", "public_key": pub("d"), "executor_sovereign_id": DEVICE, "role": "executor"},
        {"key_id": "observer-a", "public_key": pub("a"), "executor_sovereign_id": "cloud-observer", "role": "observer"},
    ]
    grant = _grant()
    t = [T0 + timedelta(minutes=i) for i in range(400)]
    token0 = _token(t[0])
    use1 = _use(grant, 1, t[2], token0, None)
    token1 = _token(t[3], 1, use1.digest(), n=31)
    use2 = _use(grant, 2, t[4], token1, use1.digest())
    execution = _signed(ExecutionEvidence(
        evidence_id=uid(200), sequence_no=1, decision_id=uid(201), context_id=uid(202), agreement_id=uid(203),
        executor_sovereign_id=DEVICE, executed_capability=CAPABILITY, outcome="success",
        execution_parameters={"version_id": "v9"}, executed_at=t[6], resource_id=RESOURCE, resource_action="rotate",
        resource_sequence=3, prev_resource_digest=use2.digest(),
    ), "b", "executor-b")
    revocation = _signed(GrantRevocationRecord(
        revocation_id=uid(300), grant_id=grant.grant_id, grant_digest=grant.digest(), reason="operator",
        detail="the device was lost", revoked_by="operator-1", revoked_at=t[8], issuer_sovereign_id=NA_SOVEREIGN,
        issued_by="na-key",
    ), "c", "na-key")

    def item(kind: str, record: Any, at: datetime, **extra: Any) -> tuple[str, dict, dict, datetime]:
        if kind == "execution":
            index = execution_index(record, {})
        else:
            index = entry_index(kind, record)
        index.update(extra)
        payload = record.to_wire() if hasattr(record, "to_wire") else record.model_dump(mode="json")
        if kind == "execution":
            payload = {k: v for k, v in record.model_dump(mode="json").items() if v is not None or k not in (
                "resource_id", "resource_action", "resource_sequence", "prev_resource_digest")}
        return kind, payload, index, at

    base = [
        item("grant", grant, t[1]),
        item("grant_execution", use1, t[5], resource_sequence=1),
        item("grant_execution", use2, t[5] + timedelta(seconds=1), resource_sequence=2),
        item("execution", execution, t[7]),
        item("grant_revocation", revocation, t[8]),
    ]

    def lines(items: list[tuple[str, dict, dict, datetime]], first: int = 1, prev: str | None = None) -> str:
        out_lines, digest = [], prev
        for seq, (kind, payload, index, at) in enumerate(items, start=first):
            entry = build_entry(store_sequence=seq, entry_kind=kind, recorded_at=at, payload=payload,
                                prev_entry_digest=digest, index=index)
            digest = entry.digest()
            out_lines.append(EvidenceEvent(entry=entry, entry_digest=digest, payload=payload).to_json_line())
        return "\n".join(out_lines)

    def case(vid: str, desc: str, items: list, *, expect: list[dict] | None = None, first: int = 1,
             prev: str | None = None) -> None:
        inp = {"lines": lines(items, first, prev), "na_public_keys": [pub("c")], "executor_keys": keys,
               "contiguous": True}
        vector = {"id": f"export-{vid}", "kind": "verify_export", "description": desc, "input": inp}
        vector["expected"] = evaluate(vector)
        if expect is not None:
            assert vector["expected"]["failures"] == expect, (vid, vector["expected"])
        out.append(vector)

    case("valid", "A grant, two uses at the NA's resource positions, execution evidence after them, a revocation",
         copy.deepcopy(base), expect=[])
    case("grant-missing", "Uses and a revocation of a grant the store does not hold", copy.deepcopy(base[1:]),
         expect=[{"store_sequence": 1, "reason": "grant_missing"}, {"store_sequence": 2, "reason": "grant_missing"},
                 {"store_sequence": 4, "reason": "grant_missing"}])
    other = _grant(grant_id=uid(10), max_uses=4)
    case("grant-mismatch", "A use naming another version of its grant (grant_digest)",
         [item("grant", other, t[1]), *copy.deepcopy(base[1:3])],
         expect=[{"store_sequence": 2, "reason": "grant_mismatch"}, {"store_sequence": 3, "reason": "grant_mismatch"}])
    stolen = _use(grant, 1, t[2], token0, None, key="d", key_id="executor-d")
    case("bearer-mismatch", "A use signed by a registered key that is not the grant's bearer",
         [base[0], item("grant_execution", stolen, t[5], resource_sequence=1)],
         expect=[{"store_sequence": 2, "reason": "grant_bearer_mismatch"}])
    case("use-chain-break", "The second use does not link to the first",
         [base[0], item("grant_execution", _use(grant, 2, t[4], token1, "0" * 64), t[5], resource_sequence=1)],
         expect=[{"store_sequence": 2, "reason": "grant_use_chain_break"}])
    case("resource-position-skipped", "A use at a resource position its chain does not reach",
         [base[0], item("grant_execution", use1, t[5], resource_sequence=2)],
         expect=[{"store_sequence": 2, "reason": "resource_chain_break"}])
    bad_execution = _signed(execution.model_copy(update={"prev_resource_digest": use1.digest(), "signature": None}),
                            "b", "executor-b")
    case("execution-after-use", "Execution evidence that does not link to the last use of its resource",
         [*copy.deepcopy(base[:3]), item("execution", bad_execution, t[7])],
         expect=[{"store_sequence": 4, "reason": "resource_chain_break"}])
    wrong_index = item("grant_execution", use1, t[5], resource_sequence=1, record_id=uid(999))
    case("envelope-record-id", "An envelope naming another use than its record", [base[0], wrong_index],
         expect=[{"store_sequence": 2, "reason": "envelope_mismatch"}])
    case("envelope-position-without-resource", "A use without a resource given a resource position",
         [base[0], item("grant_execution", _use(grant, 1, t[2], token0, None, resource_id=None, resource_action=None),
                        t[5], resource_sequence=1)],
         expect=[{"store_sequence": 2, "reason": "envelope_mismatch"}])
    case("duplicate-use", "A use stored twice", [*copy.deepcopy(base[:2]), copy.deepcopy(base[1])],
         expect=[{"store_sequence": 3, "reason": "duplicate_record"},
                 {"store_sequence": 3, "reason": "grant_use_chain_break"},
                 {"store_sequence": 3, "reason": "resource_chain_break"}])
    again = _signed(revocation.model_copy(update={"revocation_id": uid(301), "signature": None}), "c", "na-key")
    case("duplicate-revocation", "A grant revoked twice",
         [*copy.deepcopy(base), item("grant_revocation", again, t[9])],
         expect=[{"store_sequence": 6, "reason": "duplicate_grant_revocation"}])
    token2 = _token(t[9], 2, use2.digest(), n=32)
    after = _use(grant, 3, t[10], token2, use2.digest())
    case("use-after-revocation", "A use made after the grant's revocation, recorded after it",
         [*copy.deepcopy(base), item("grant_execution", after, t[11], resource_sequence=4)],
         expect=[{"store_sequence": 6, "reason": "grant_revoked"}])
    late = _use(grant, 3, t[10], token2, use2.digest())
    case("use-before-revocation-uploaded-after", "A use made before the revocation, recorded after it: it stands",
         [*copy.deepcopy(base[:4]), item("grant_execution", late, t[11], resource_sequence=4),
          item("grant_revocation", _signed(revocation.model_copy(update={"revoked_at": t[12], "signature": None}),
                                           "c", "na-key"), t[12])], expect=[])
    outside = _use(grant, 1, t[2], token0, None, request_parameters={"lifetime_days": 400})
    case("use-outside-envelope", "A stored use outside its grant's envelope",
         [base[0], item("grant_execution", outside, t[5], resource_sequence=1)],
         expect=[{"store_sequence": 2, "reason": "grant_envelope_mismatch"}])
    case("use-uploaded-late", "A use recorded longer after it was made than the grant's validity",
         [base[0], item("grant_execution", use1, t[2] + timedelta(hours=4, seconds=1), resource_sequence=1)],
         expect=[{"store_sequence": 2, "reason": "grant_use_uploaded_late"}])
    case("use-in-future", "A use dated more than 300 s after it was recorded",
         [base[0], item("grant_execution", use1, t[2] - timedelta(seconds=301), resource_sequence=1)],
         expect=[{"store_sequence": 2, "reason": "grant_use_in_future"}])
    forged = _use(grant, 1, t[2], _token(t[0], key="d"), None)
    case("time-token-not-the-nas", "A use whose time token another key signed",
         [base[0], item("grant_execution", forged, t[5], resource_sequence=1)],
         expect=[{"store_sequence": 2, "reason": "grant_time_token_invalid"}])
    # A refused use kept, quarantined; an observation of a use, governed by the grant.
    quarantine = _signed(QuarantineRecord(
        quarantine_id=uid(400), record_kind="grant_execution", record=outside.to_wire(),
        record_digest=payload_digest(outside.to_wire()), rejection_code="grant_envelope_mismatch",
        detail="request_parameters.lifetime_days is outside its range", resource_id=RESOURCE, quarantined_at=t[5],
        issuer_sovereign_id=NA_SOVEREIGN, issued_by="na-key",
    ), "c", "na-key")
    observation = _signed(ObservationRecord(
        observation_id=uid(500), observer_sovereign_id="cloud-observer", resource_id=RESOURCE, action="rotate",
        capability=CAPABILITY, changed_at=t[2], observed_at=t[5], actor="principal-7f3a", source="cloud-activity-log",
        source_event_id="event-1", version_id="v1", metadata={"lifetime_days": 30},
    ), "a", "observer-a")
    obs_entry = item("observation", observation, t[6], observation_sequence=1)

    def judgement(matched: str) -> Any:
        return _signed(JudgementRecord(
            judgement_id=uid(501), subject_kind="observation", subject_id=observation.observation_id,
            subject_digest=payload_digest(observation.to_wire()), subject_store_sequence=5, resource_id=RESOURCE,
            action="rotate", capability=CAPABILITY, governed_by="grant", verdict="allow",
            reason="matched a recorded grant use", evaluated_as_of=t[2], matched_evidence_id=matched, judged_at=t[6],
            issuer_sovereign_id=NA_SOVEREIGN, issued_by="na-key",
        ), "c", "na-key")

    case("quarantine-and-governed-observation",
         "A quarantined use, and an observation matched to a use (governed_by grant)",
         [*copy.deepcopy(base[:3]), item("quarantine", quarantine, t[5] + timedelta(seconds=2)), obs_entry,
          item("judgement", judgement(use1.use_id), t[6])], expect=[])
    case("governed-observation-match-missing", "A judgement matching a use the store does not hold",
         [*copy.deepcopy(base[:3]), item("quarantine", quarantine, t[5] + timedelta(seconds=2)), obs_entry,
          item("judgement", judgement(uid(998)), t[6])],
         expect=[{"store_sequence": 6, "reason": "judgement_match_missing"}])
    # A run that starts after the grant (an export page): the uses are checked by their key and time token.
    case("page-after-grant", "An export page starting at a use: the grant is not held", copy.deepcopy(base[2:4]),
         first=3, prev="0" * 64, expect=[])
    return out


def grants_vectors() -> list[dict[str, Any]]:
    """Every vector of the suite, ``expected`` filled with the reference's verdicts."""
    return [*_record_vectors(), *_envelope_vectors(), *_issuance_vectors(), *_use_vectors(), *_export_vectors()]


def dump(vectors: list[dict[str, Any]]) -> str:
    return json.dumps({"suite": "grants", "version": "1.6.0", "vectors": vectors}, indent=2) + "\n"
