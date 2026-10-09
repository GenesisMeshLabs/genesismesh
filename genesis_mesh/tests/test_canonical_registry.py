"""The field registry of signed records (v1.2.0).

Verifiers in every SDK refuse a field the registry does not list, so the
registry must describe the Python models exactly: their fields, the nested
models, the free-form fields, and the optional fields each signed form omits
when absent. These tests fail when a model changes and the shared suite
(``conformance/vectors/canonical.json``) was not regenerated, or when a model
omits a field from its signed form that the registry does not say it omits.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from genesis_mesh.models.canonical_registry import _roots, build_registry, unknown_fields

SUITE = Path(__file__).resolve().parents[2] / "conformance" / "vectors" / "canonical.json"


@pytest.fixture(scope="module")
def suite() -> dict:
    return json.loads(SUITE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry() -> dict:
    return build_registry()


def test_the_committed_registry_matches_the_models(suite, registry):
    assert suite["registry"] == registry, (
        "conformance/vectors/canonical.json is stale: run "
        "`python conformance/generate_vectors.py canonical` and copy it to the SDKs"
    )


def test_every_vector_matches_the_reference(suite, registry):
    for v in suite["vectors"]:
        if v["kind"] == "unknown_fields":
            assert sorted(unknown_fields(v["model"], v["record"], registry)) == v["expected"]["unknown_fields"], v["id"]
        else:
            assert (v["entry_kind"] in registry["entry_kinds"]) == v["expected"]["known"], v["id"]


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
    # And present again, every field is signed.
    full = set(json.loads(instance.to_canonical_json()))
    present = {f for f in spec["fields"] if getattr(instance, f) is not None} - {spec["signature_field"]}
    assert full >= (present & expected)


def test_free_form_fields_and_maps_are_walked_correctly(registry):
    record = {
        "checkpoint_id": "c", "resource_heads": {"r1": {"resource_sequence": 1, "record_digest": "d", "x": 1}},
        "signature": {"key_id": "k", "sig": "s"},
    }
    assert unknown_fields("RetentionCheckpoint", record, registry) == ["resource_heads.r1.x"]
    evidence = {"execution_parameters": {"anything": {"nested": True}}, "resource_id": None}
    assert unknown_fields("ExecutionEvidence", evidence, registry) == []
    assert unknown_fields("ExecutionEvidence", {"signature": {"key_id": "k", "sig": "s", "alg": "x"}},
                          registry) == ["signature.alg"]


def test_values_of_the_wrong_type_are_left_to_validation(registry):
    assert unknown_fields("BoundaryDecision", {"policy_binding": "not an object"}, registry) == []
    assert unknown_fields("BoundaryDecision", "not a record", registry) == []


def test_entry_kinds_are_the_models(registry):
    assert registry["entry_kinds"] == ["decision", "execution", "justification", "retention_checkpoint"]


def test_evidence_verification_names_unknown_fields():
    """An export entry carrying a field this release does not know fails by name."""
    from genesis_mesh.trust.evidence_store import parse_export_lines, verify_evidence_events

    from .test_evidence_store import Controller, _client, _decide, _submit
    from .test_na_boundary_policy import _get, _make_service

    service = _make_service(evidence_store="on")
    client = _client(service)
    controller = Controller(client)
    assert _submit(client, controller.record(_decide(client))).status_code == 201
    events = parse_export_lines(_get(client, "/admin/evidence/export").get_data(as_text=True).splitlines())
    execution = next(e for e in events if e.entry.entry_kind == "execution")
    decision = next(e for e in events if e.entry.entry_kind == "decision")
    execution.payload["x_added_field"] = 1
    decision.payload["decision"]["policy_binding"] = {**(decision.payload["decision"]["policy_binding"] or {}),
                                                      "x_nested": 1}
    decision.payload["x_wrapper"] = 1
    result = verify_evidence_events(events, na_public_keys=[service.signer.public_key_b64],
                                    executor_keys=service.evidence_store_service.executor_keys())
    unknown = [f for f in result.failures if f["reason"] == "unknown_field"]
    assert {f["store_sequence"] for f in unknown} == {execution.entry.store_sequence, decision.entry.store_sequence}
    details = " ".join(f["detail"] for f in unknown)
    assert "x_added_field" in details and "decision.policy_binding.x_nested" in details and "x_wrapper" in details
