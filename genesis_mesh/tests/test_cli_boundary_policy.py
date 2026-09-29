"""CLI tests for ``genesis-mesh trust boundary-policy`` (v0.58)."""

from __future__ import annotations

import json
from datetime import timedelta

from click.testing import CliRunner
import pytest

from genesis_mesh.cli.boundary_policy_ops import boundary_policy

from .test_boundary_policy import _PUB, _agreement, _context, _evaluate, _now, _policy


def _intent(**overrides) -> dict:
    now = _now()
    body = {
        "policy_id": "cli-policy",
        "valid_from": now.isoformat(),
        "valid_until": (now + timedelta(days=1)).isoformat(),
        "selector": {"capabilities": ["payments.*"]},
        "gates": [{"gate_id": "cap", "gate_type": "max_value.v1", "order": 0,
                   "config": {"path": "request_parameters.amount", "max": 10}}],
    }
    body.update(overrides)
    return body


def _write(tmp_path, name: str, data) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_validate_accepts_valid_intent(tmp_path):
    result = CliRunner().invoke(boundary_policy, ["validate", "--file", _write(tmp_path, "p.json", _intent())])
    assert result.exit_code == 0, result.output
    assert "Valid   : yes" in result.output


@pytest.mark.parametrize("field", ["selectorr", "issued_at", "issued_by", "issuer_sovereign_id"])
def test_validate_rejects_unknown_or_partial_issuer_fields(tmp_path, field):
    intent = _intent(**{field: "unexpected"})
    result = CliRunner().invoke(boundary_policy, ["validate", "--file", _write(tmp_path, "p.json", intent)])
    assert result.exit_code == 1
    assert "Policy is malformed" in result.output


def test_validate_accepts_complete_signed_policy(tmp_path):
    path = _write(tmp_path, "p.json", _policy().model_dump(mode="json"))
    result = CliRunner().invoke(boundary_policy, ["validate", "--file", path, "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["valid"] is True


def test_validate_reports_unknown_gate_type(tmp_path):
    intent = _intent(gates=[{"gate_id": "x", "gate_type": "eval.v1", "order": 0, "config": {}}])
    result = CliRunner().invoke(
        boundary_policy, ["validate", "--file", _write(tmp_path, "p.json", intent), "--format", "json"]
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["issues"][0]["code"] == "unknown_gate_type"


def test_validate_rejects_malformed_file(tmp_path):
    result = CliRunner().invoke(boundary_policy, ["validate", "--file", _write(tmp_path, "p.json", [1])])
    assert result.exit_code != 0


def test_verify_signed_policy(tmp_path):
    path = _write(tmp_path, "p.json", _policy().model_dump(mode="json"))
    result = CliRunner().invoke(boundary_policy, ["verify", "--file", path, "--public-key", _PUB])
    assert result.exit_code == 0, result.output
    assert "VALID" in result.output


def test_verify_rejects_tampered_policy(tmp_path):
    data = _policy().model_dump(mode="json")
    data["description"] = "tampered"
    path = _write(tmp_path, "p.json", data)
    result = CliRunner().invoke(boundary_policy, ["verify", "--file", path, "--public-key", _PUB])
    assert result.exit_code == 1
    assert "invalid_signature" in result.output


def test_explain_policy_bound_decision(tmp_path):
    agreement = _agreement()
    decision, _ = _evaluate([_policy()], _context(agreement, params={"amount": 5000}), agreement)
    path = _write(tmp_path, "d.json", {"decision": decision.model_dump(mode="json")})
    result = CliRunner().invoke(boundary_policy, ["explain", "--decision", path])
    assert result.exit_code == 0, result.output
    assert "FAIL payments-limits/amount-cap" in result.output
    assert "Authorized : False" in result.output


def test_explain_json_contains_binding(tmp_path):
    decision, _ = _evaluate([_policy()])
    path = _write(tmp_path, "d.json", decision.model_dump(mode="json"))
    result = CliRunner().invoke(boundary_policy, ["explain", "--decision", path, "--format", "json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["policy_binding"]["resolution_status"] == "resolved"


def test_explain_rejects_legacy_decision(tmp_path):
    agreement = _agreement()
    from genesis_mesh.trust.context import BoundaryEngine

    from .test_boundary_policy import _SK

    legacy = BoundaryEngine("bank-a").evaluate(_context(agreement), agreement, _SK, issued_by="k")
    path = _write(tmp_path, "d.json", legacy.model_dump(mode="json"))
    result = CliRunner().invoke(boundary_policy, ["explain", "--decision", path])
    assert result.exit_code != 0
    assert "no policy_binding" in result.output


def test_gate_types_lists_builtins():
    result = CliRunner().invoke(boundary_policy, ["gate-types", "--format", "json"])
    assert result.exit_code == 0
    types = [t["gate_type"] for t in json.loads(result.output)]
    assert "max_value.v1" in types and "attestation_claim.v1" in types and len(types) == 9


def test_group_is_registered_under_trust():
    from genesis_mesh.cli.decision_ops import trust

    assert "boundary-policy" in trust.commands
