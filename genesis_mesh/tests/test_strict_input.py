"""Strict JSON input and the canonical form of records (v1.2.0).

The cases every implementation shares are the conformance suite
``canonical`` (``test_conformance``); these tests cover where the reference
applies them: the NA's request bodies, its verify routes, the CLI and the
export parser.
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime
from pathlib import Path

import pytest
from click.testing import CliRunner
from pydantic import BaseModel

from genesis_mesh import strict_json
from genesis_mesh.cli.context_ops import context
from genesis_mesh.models.canonical_registry import build_registry, canonical_timestamp
from genesis_mesh.trust.evidence_store import parse_export_lines

SUITE = json.loads(
    (Path(__file__).resolve().parents[2] / "conformance" / "vectors" / "canonical.json").read_text(encoding="utf-8")
)
VECTORS = {v["id"]: v for v in SUITE["vectors"]}


@pytest.mark.parametrize("text, reason", [
    ('{"a":1,"a":2}', "duplicate_key"),
    ('{"x":NaN}', "invalid_json"),
    ('[1e400]', "non_finite_number"),
    ('[18446744073709551616]', "integer_out_of_range"),
    ('[-0]', "negative_zero"),
    ('["\\ud800"]', "lone_surrogate"),
    ('{', "invalid_json"),
])
def test_each_reason(text, reason):
    with pytest.raises(strict_json.StrictJSONError) as caught:
        strict_json.loads(text)
    assert caught.value.reason == reason


def test_bytes_must_be_utf8():
    assert strict_json.loads('{"x":"é"}'.encode()) == {"x": "é"}
    with pytest.raises(strict_json.StrictJSONError) as caught:
        strict_json.loads(b'{"x":"\xff"}')
    assert caught.value.reason == "invalid_json"


def test_timestamp_fields_are_the_models_datetimes():
    registry = build_registry()
    timestamps = {(m, f) for m, spec in registry["models"].items() for f, k in spec["fields"].items() if k == "timestamp"}
    assert ("BoundaryDecision", "decision_valid_until") in timestamps
    assert ("AgreementTerms", "valid_from") in timestamps
    assert registry["version"] == 2


def test_canonical_timestamps_are_what_the_reference_writes_back():
    class M(BaseModel):
        t: datetime

    dates = ["2026-01-01", "2024-02-29", "2026-02-29", "0001-01-01", "9999-12-31"]
    times = ["00:00:00", "23:59:59", "24:00:00"]
    fractions = ["", ".000000", ".123456", ".1", ".000", ".1234567"]
    zones = ["", "Z", "+00:00", "-00:00", "+02:00", "-05:30", "z", "+0200"]
    for d, t, f, z in itertools.product(dates, times, fractions, zones):
        value = f"{d}T{t}{f}{z}"
        try:
            fixed = M(t=value).model_dump(mode="json")["t"] == value
        except ValueError:
            fixed = False
        assert canonical_timestamp(value) is fixed, value


def _client():
    from .test_na_boundary_policy import _make_service

    service = _make_service()
    service.app.config["TESTING"] = True
    return service.app.test_client()


@pytest.mark.parametrize("body, reason", [
    ('{"decision":{},"decision":{}}', "duplicate_key"),
    ('{"decision":{"x":"\\udc00"}}', "lone_surrogate"),
    ('{"decision":{"version":123456789012345678901234}}', "integer_out_of_range"),
])
def test_request_bodies_are_read_strictly(body, reason):
    resp = _client().post("/boundary/verify", data=body, content_type="application/json")
    assert resp.status_code == 400
    error = resp.get_json()["error"]
    assert (error["code"], error["details"]["reason"]) == ("invalid_json", reason)


def test_a_body_that_is_not_json_by_content_type_is_still_no_body():
    resp = _client().post("/boundary/verify", data="{oops", content_type="text/plain")
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] != "invalid_json"


def test_the_verify_routes_refuse_records_not_in_canonical_form():
    client = _client()
    signed = VECTORS["verify-decision-signed-non-canonical-timestamp"]["input"]
    resp = client.post("/boundary/verify", json={"decision": signed["decision"],
                                                 "operator_public_keys": signed["operator_public_keys"]})
    assert resp.get_json()["reason"] == "non_canonical_form"
    rewritten = VECTORS["verify-decision-received-non-canonical-timestamp"]["input"]
    resp = client.post("/boundary/verify", json={"decision": rewritten["decision"],
                                                 "operator_public_keys": rewritten["operator_public_keys"]})
    assert resp.get_json()["reason"] == "invalid_signature"
    agreement = VECTORS["verify-agreement-signed-non-canonical-timestamp"]["input"]
    resp = client.post("/agreements/verify", json=agreement)
    assert resp.get_json()["reason"] == "non_canonical_form"


def test_the_cli_refuses_a_decision_file_with_a_duplicate_key(tmp_path):
    path = tmp_path / "decision.json"
    path.write_text('{"decision_id":"a","decision_id":"b"}', encoding="utf-8")
    result = CliRunner().invoke(context, ["verify", "--decision", str(path),
                                          "--operator-public-key", "A" * 43 + "="])
    assert result.exit_code != 0
    assert "duplicate_key" in result.output


def test_export_lines_are_read_strictly():
    with pytest.raises(strict_json.StrictJSONError) as caught:
        parse_export_lines(['{"schema":"gm.evidence.event","schema":"x"}'])
    assert caught.value.reason == "duplicate_key"
