"""The field registry of signed records (v1.2.0).

Verifiers in every SDK refuse a signed field the registry does not list, so
the registry must describe the Python models exactly: their fields, the
nested models, the free-form fields, and the optional fields each signed form
omits when absent. These tests fail when a model changes and the shared suite
(``conformance/vectors/field_registry.json``) was not regenerated, when a
model omits a field from its signed form that the registry does not say it
omits, or when a field becomes free-form without being listed below.
"""

from __future__ import annotations

import json
import typing
from pathlib import Path

import pytest
from pydantic import BaseModel

from genesis_mesh.models.canonical_registry import (
    _kind,
    _roots,
    build_registry,
    intent_refusal_detail,
    strict_refusal,
    unknown_fields,
)

SUITE = Path(__file__).resolve().parents[2] / "conformance" / "vectors" / "field_registry.json"

#: Every free-form field: keys inside are chosen by the signer and never checked.
#: Adding one is a protocol decision, made here on purpose.
FREE_FORM = {
    ("AgreementRecord", "offerer_evidence"), ("AgreementRecord", "responder_evidence"),
    ("AgreementTerms", "scope"), ("ContextRecord", "attributes"), ("ContextRecord", "request_parameters"),
    ("ExecutionEvidence", "execution_parameters"), ("GateSpec", "config"), ("GateTraceEntry", "inputs"),
    ("GateTraceEntry", "metadata"), ("MembershipAttestation", "claims"), ("PolicySelector", "parameter_equals"),
    ("SovereignRevocationFeed", "revocation_reasons"),
}


@pytest.fixture(scope="module")
def suite() -> dict:
    return json.loads(SUITE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry() -> dict:
    return build_registry()


def test_the_committed_registry_matches_the_models(suite, registry):
    assert suite["registry"] == registry, (
        "conformance/vectors/field_registry.json is stale: run "
        "`python conformance/generate_vectors.py field_registry` and copy it to the SDKs"
    )


def test_free_form_fields_are_exactly_the_listed_ones(registry):
    found = {(m, f) for m, spec in registry["models"].items() for f, k in spec["fields"].items() if k == "open"}
    assert found == FREE_FORM


def test_shapes_the_registry_cannot_describe_are_refused():
    class A(BaseModel):
        a: int

    class B(BaseModel):
        b: int

    for shape in (A | B, A | list[A], list[A | B], list[list[A]], dict[str, list[A]], list[dict[str, A]],
                  tuple[A, B], tuple[str, A]):
        with pytest.raises(TypeError):
            _kind(shape, {})
    assert _kind(typing.Optional[A], {}) == {"object": "A"}
    assert _kind(list[dict[str, typing.Any]], {}) == "open"
    assert _kind(tuple[str, int], {}) is None


def test_every_vector_matches_the_reference(suite):
    import sys

    sys.path.insert(0, str(SUITE.parents[1]))
    try:
        from runner import run_field_registry  # conformance/runner.py
    finally:
        sys.path.pop(0)
    assert run_field_registry(suite["vectors"]) == []


def _samples(suite) -> dict[str, dict]:
    return {v["model"]: v["record"] for v in suite["vectors"] if v["id"].endswith("-clean")}


@pytest.mark.parametrize("model", [m for m in _roots() if hasattr(m, "to_canonical_json")], ids=lambda m: m.__name__)
def test_the_signed_form_omits_exactly_what_the_registry_says(model, suite, registry):
    spec = registry["models"][model.__name__]
    instance = model.model_validate(_samples(suite)[model.__name__])
    optional = {name for name, info in model.model_fields.items() if info.default is None}
    # Every optional field absent: a field the signed form drops must be listed.
    bare = instance.model_copy(update={name: None for name in optional})
    signed = set(json.loads(bare.to_canonical_json()))
    if "canonical_fields" in spec:
        expected = set(spec["canonical_fields"])
    else:
        expected = set(spec["fields"]) - {spec["signature_field"]} - set(spec.get("omit_when_none", []))
    assert signed == expected


def test_the_entry_digest_covers_every_envelope_field(suite, registry):
    from genesis_mesh.models.evidence_store import EvidenceStoreEntry

    entry = EvidenceStoreEntry.model_validate(_samples(suite)["EvidenceStoreEntry"])
    assert set(entry.model_dump(mode="json")) == set(registry["models"]["EvidenceStoreEntry"]["fields"])


def test_only_the_signed_projection_is_checked(registry):
    record = {
        "checkpoint_id": "c", "resource_heads": {"r1": {"resource_sequence": 1, "record_digest": "d", "x": 1}},
        "signature": {"key_id": "k", "sig": "s", "alg": "x"},
    }
    assert unknown_fields("RetentionCheckpoint", record, registry) == ["resource_heads.r1.x"]
    assert unknown_fields("AgreementRecord", {"note": 1, "agreed_terms": {"x": 1}}, registry) == ["agreed_terms.x"]
    nested = {"freshness_proof": {"signature": {"key_id": "k", "sig": "s", "alg": "x"}}}
    assert unknown_fields("BoundaryDecision", nested, registry) == ["freshness_proof.signature.alg"]


def test_values_of_the_wrong_type_are_left_to_validation(registry):
    assert unknown_fields("BoundaryDecision", {"policy_binding": "not an object"}, registry) == []
    assert unknown_fields("BoundaryDecision", "not a record", registry) == []


def test_entry_kinds_are_the_models(registry):
    assert registry["entry_kinds"] == ["decision", "execution", "justification", "retention_checkpoint"]


def test_strict_refusal_tells_a_newer_signer_from_a_forgery(suite):
    by_id = {v["id"]: v for v in suite["vectors"]}
    newer = by_id["verify-decision-newer-signed-field"]["input"]
    unsigned = by_id["verify-decision-unsigned-field"]["input"]
    assert strict_refusal("BoundaryDecision", newer["decision"], newer["operator_public_keys"]) == "unknown_field"
    assert strict_refusal("BoundaryDecision", unsigned["decision"], unsigned["operator_public_keys"]) == "invalid_signature"
    assert strict_refusal("BoundaryDecision", _samples(suite)["BoundaryDecision"], []) is None


def test_intent_refusals_name_the_problem(suite):
    intent, policy = _samples(suite)["DataAccessIntent"], _samples(suite)["DataLicensePolicy"]
    assert intent_refusal_detail(intent, policy, []) is None
    assert intent_refusal_detail(intent, {**policy, "x": 1}, []) == "Unknown field: policy.x"
    assert intent_refusal_detail({**intent, "x": 1}, policy, []) == "Invalid intent signature"


def test_evidence_verification_refuses_signed_and_warns_on_unsigned_fields():
    """A field outside the signature (stored before 1.1.1) is reported, not refused."""
    from genesis_mesh.crypto import sign_data
    from genesis_mesh.models.canonical_registry import received_canonical
    from genesis_mesh.trust.evidence_store import parse_export_lines, verify_evidence_events

    from .test_evidence_store import Controller, _client, _decide, _submit
    from .test_na_boundary_policy import _get, _make_service

    service = _make_service(evidence_store="on")
    client = _client(service)
    controller = Controller(client)
    assert _submit(client, controller.record(_decide(client))).status_code == 201
    keys = service.evidence_store_service.executor_keys()
    na = [service.signer.public_key_b64]

    def export():
        return parse_export_lines(_get(client, "/admin/evidence/export").get_data(as_text=True).splitlines())

    events = export()
    execution = next(e for e in events if e.entry.entry_kind == "execution")
    decision = next(e for e in events if e.entry.entry_kind == "decision")
    execution.payload["client_note"] = "stored before 1.1.1"
    decision.payload["x_wrapper"] = 1
    result = verify_evidence_events(events, na_public_keys=na, executor_keys=keys)
    assert not any(f["reason"] in ("unknown_field", "invalid_signature") for f in result.failures)
    warned = {w["store_sequence"] for w in result.warnings if w["reason"] == "unsigned_field"}
    assert warned == {execution.entry.store_sequence, decision.entry.store_sequence}

    events = export()
    execution = next(e for e in events if e.entry.entry_kind == "execution")
    execution.payload["risk_tier"] = "high"
    body = received_canonical("ExecutionEvidence", execution.payload).encode()
    execution.payload["signature"]["sig"] = sign_data(body, controller.key)
    result = verify_evidence_events(events, na_public_keys=na, executor_keys=keys)
    assert [f["store_sequence"] for f in result.failures if f["reason"] == "unknown_field"] == [
        execution.entry.store_sequence
    ]


def test_an_unknown_entry_kind_is_named_and_still_chains(suite):
    from genesis_mesh.trust.evidence_store import parse_export_lines, verify_evidence_events

    line = next(v for v in suite["vectors"] if v["kind"] == "export")["input"]["lines"]
    events = parse_export_lines([line])
    follower = events[0].model_copy(deep=True)
    follower.entry = follower.entry.model_copy(update={
        "store_sequence": 2, "entry_kind": "x-unknown-kind", "prev_entry_digest": events[0].entry.digest(),
    })
    follower.entry_digest = follower.entry.digest()
    result = verify_evidence_events([events[0], follower], na_public_keys=[], executor_keys={})
    assert [(f["store_sequence"], f["reason"]) for f in result.failures] == [
        (1, "unknown_entry_kind"), (2, "unknown_entry_kind"),
    ]


def test_the_verify_routes_refuse_unknown_fields(suite, monkeypatch):
    from genesis_mesh.na_service.routes import boundary
    from .test_na_boundary_policy import _make_service
    from .test_strict_input import _AtVectorTime

    monkeypatch.setattr(boundary, "datetime", _AtVectorTime)  # before the suite's decisions expire
    service = _make_service()
    client = service.app.test_client()
    by_id = {v["id"]: v["input"] for v in suite["vectors"] if v["kind"].startswith("verify_")}
    newer = by_id["verify-decision-newer-signed-field"]
    resp = client.post("/boundary/verify", json={"decision": newer["decision"],
                                                 "operator_public_keys": newer["operator_public_keys"]})
    assert resp.status_code == 200 and resp.get_json()["reason"] == "unknown_field"
    unsigned = by_id["verify-decision-unsigned-field"]
    resp = client.post("/boundary/verify", json={"decision": unsigned["decision"],
                                                 "operator_public_keys": unsigned["operator_public_keys"]})
    assert resp.get_json()["reason"] == "invalid_signature"
    agr = by_id["verify-agreement-unsigned-field"]
    resp = client.post("/agreements/verify", json={"agreement": agr["agreement"],
                                                   "offerer_public_keys": agr["offerer_public_keys"],
                                                   "responder_public_keys": agr["responder_public_keys"]})
    assert resp.get_json()["accepted"] is True
