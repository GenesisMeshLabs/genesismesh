"""Tests for Verifiable Logic Attestation (v0.40).

Covers:
- ToolManifest: hash computed on construction, order-independent
- create_model_attestation(): prompt hashed, tool_ids hashed, signature valid
- verify_model_attestation(): valid / each of 7 reason codes
- Empty allowlists permit any value (open policy)
- AttestationPolicy with require_bound_token
- LogicAttestationGate: passes on valid, blocks on each reason
- Two agents: same model, different prompts -> different hashes
- CLI: attest create / verify / policy exit codes and output
"""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nacl.signing
import pytest
from click.testing import CliRunner

from genesis_mesh.cli.decision_ops import trust
from genesis_mesh.models.attestation import AttestationPolicy, ModelAttestation, ToolManifest
from genesis_mesh.trust.logic_attestation import (
    LogicAttestationGate,
    create_model_attestation,
    verify_model_attestation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
_FUTURE = _NOW + timedelta(days=365)
_MODEL_ID = "claude-sonnet-4-6"
_VERSION = "20251001"
_PROMPT = "You are a helpful assistant."
_TOOLS = ["tool_read", "tool_write"]


def _sk() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()


def _pub_b64(sk: nacl.signing.SigningKey) -> str:
    return base64.b64encode(bytes(sk.verify_key)).decode()


def _make_attestation(
    sk: nacl.signing.SigningKey,
    model_id: str = _MODEL_ID,
    prompt: str = _PROMPT,
    tool_ids: list[str] | None = None,
    agent_sov: str = "agent-a",
    token_id: str | None = None,
    valid_for: int = 300,
    now: datetime = _NOW,
) -> ModelAttestation:
    return create_model_attestation(
        agent_sov, model_id, _VERSION, prompt,
        tool_ids or _TOOLS, sk,
        token_id=token_id, valid_for_seconds=valid_for, now=now,
    )


def _make_policy(
    allow_models: list[str] | None = None,
    allow_prompts: list[str] | None = None,
    allow_tools: list[str] | None = None,
    require_token: bool = False,
    operator_sov: str = "operator-x",
) -> AttestationPolicy:
    return AttestationPolicy(
        operator_sovereign_id=operator_sov,
        allowed_model_ids=allow_models or [],
        allowed_system_prompt_hashes=allow_prompts or [],
        allowed_tool_manifest_hashes=allow_tools or [],
        require_bound_token=require_token,
        valid_until=_FUTURE,
    )


# ---------------------------------------------------------------------------
# ToolManifest
# ---------------------------------------------------------------------------


def test_tool_manifest_hash_computed_on_construction() -> None:
    manifest = ToolManifest(tool_ids=["tool_a", "tool_b"])
    assert manifest.manifest_hash != ""
    assert len(manifest.manifest_hash) == 64  # SHA-256 hex


def test_tool_manifest_hash_order_independent() -> None:
    m1 = ToolManifest(tool_ids=["tool_a", "tool_b"])
    m2 = ToolManifest(tool_ids=["tool_b", "tool_a"])
    assert m1.manifest_hash == m2.manifest_hash


def test_tool_manifest_hash_differs_for_different_tools() -> None:
    m1 = ToolManifest(tool_ids=["tool_a"])
    m2 = ToolManifest(tool_ids=["tool_b"])
    assert m1.manifest_hash != m2.manifest_hash


def test_tool_manifest_empty_tools() -> None:
    manifest = ToolManifest(tool_ids=[])
    assert manifest.manifest_hash != ""
    assert len(manifest.manifest_hash) == 64


def test_tool_manifest_preset_hash_not_overwritten() -> None:
    custom_hash = "a" * 64
    manifest = ToolManifest(tool_ids=["tool_a"], manifest_hash=custom_hash)
    assert manifest.manifest_hash == custom_hash


# ---------------------------------------------------------------------------
# create_model_attestation
# ---------------------------------------------------------------------------


def test_create_attestation_signature_present() -> None:
    sk = _sk()
    attestation = _make_attestation(sk)
    assert attestation.signature is not None


def test_create_attestation_hashes_system_prompt() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, prompt=_PROMPT)
    expected = hashlib.sha256(_PROMPT.encode()).hexdigest()
    assert attestation.system_prompt_hash == expected


def test_create_attestation_hashes_tool_ids() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, tool_ids=["tool_a", "tool_b"])
    expected = ToolManifest(tool_ids=["tool_a", "tool_b"]).manifest_hash
    assert attestation.tool_manifest_hash == expected


def test_create_attestation_sets_timestamps() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, valid_for=600, now=_NOW)
    assert attestation.attested_at == _NOW
    assert attestation.expires_at == _NOW + timedelta(seconds=600)


def test_create_attestation_with_token_id() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, token_id="tok-abc-123")
    assert attestation.token_id == "tok-abc-123"


def test_create_attestation_without_token_id() -> None:
    sk = _sk()
    attestation = _make_attestation(sk)
    assert attestation.token_id is None


def test_create_attestation_model_fields() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, model_id="claude-haiku-4-5", agent_sov="agent-b")
    assert attestation.model_id == "claude-haiku-4-5"
    assert attestation.agent_sovereign_id == "agent-b"
    assert attestation.model_version_tag == _VERSION


# ---------------------------------------------------------------------------
# verify_model_attestation — valid
# ---------------------------------------------------------------------------


def test_verify_valid_attestation() -> None:
    sk = _sk()
    attestation = _make_attestation(sk)
    prompt_hash = attestation.system_prompt_hash
    tool_hash = attestation.tool_manifest_hash
    policy = _make_policy(
        allow_models=[_MODEL_ID],
        allow_prompts=[prompt_hash],
        allow_tools=[tool_hash],
    )
    passed, reason = verify_model_attestation(
        attestation, policy, [_pub_b64(sk)], at_time=_NOW
    )
    assert passed is True
    assert reason == "valid"


def test_verify_empty_policy_permits_all() -> None:
    sk = _sk()
    attestation = _make_attestation(sk)
    policy = _make_policy()  # no restrictions
    passed, reason = verify_model_attestation(
        attestation, policy, [_pub_b64(sk)], at_time=_NOW
    )
    assert passed is True
    assert reason == "valid"


# ---------------------------------------------------------------------------
# verify_model_attestation — each failure reason
# ---------------------------------------------------------------------------


def test_verify_missing_signature() -> None:
    sk = _sk()
    attestation = _make_attestation(sk).model_copy(update={"signature": None})
    policy = _make_policy()
    passed, reason = verify_model_attestation(attestation, policy, [_pub_b64(sk)])
    assert passed is False
    assert reason == "missing_signature"


def test_verify_invalid_signature() -> None:
    sk = _sk()
    wrong_sk = _sk()
    attestation = _make_attestation(sk)
    policy = _make_policy()
    passed, reason = verify_model_attestation(
        attestation, policy, [_pub_b64(wrong_sk)], at_time=_NOW
    )
    assert passed is False
    assert reason == "invalid_signature"


def test_verify_expired_attestation() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, valid_for=60, now=_NOW)
    policy = _make_policy()
    at_time = _NOW + timedelta(seconds=61)
    passed, reason = verify_model_attestation(
        attestation, policy, [_pub_b64(sk)], at_time=at_time
    )
    assert passed is False
    assert reason == "expired"


def test_verify_model_not_permitted() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, model_id="unknown-model")
    policy = _make_policy(allow_models=[_MODEL_ID])
    passed, reason = verify_model_attestation(
        attestation, policy, [_pub_b64(sk)], at_time=_NOW
    )
    assert passed is False
    assert reason == "model_not_permitted"


def test_verify_system_prompt_not_permitted() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, prompt="An altered system prompt.")
    policy = _make_policy(allow_prompts=[hashlib.sha256(_PROMPT.encode()).hexdigest()])
    passed, reason = verify_model_attestation(
        attestation, policy, [_pub_b64(sk)], at_time=_NOW
    )
    assert passed is False
    assert reason == "system_prompt_not_permitted"


def test_verify_tool_manifest_not_permitted() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, tool_ids=["undeclared_tool"])
    allowed_hash = ToolManifest(tool_ids=_TOOLS).manifest_hash
    policy = _make_policy(allow_tools=[allowed_hash])
    passed, reason = verify_model_attestation(
        attestation, policy, [_pub_b64(sk)], at_time=_NOW
    )
    assert passed is False
    assert reason == "tool_manifest_not_permitted"


def test_verify_token_binding_required_without_token() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, token_id=None)
    policy = _make_policy(require_token=True)
    passed, reason = verify_model_attestation(
        attestation, policy, [_pub_b64(sk)], at_time=_NOW
    )
    assert passed is False
    assert reason == "token_binding_required"


def test_verify_token_binding_required_with_token() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, token_id="tok-xyz")
    policy = _make_policy(require_token=True)
    passed, reason = verify_model_attestation(
        attestation, policy, [_pub_b64(sk)], at_time=_NOW
    )
    assert passed is True
    assert reason == "valid"


# ---------------------------------------------------------------------------
# Empty allowlist semantics
# ---------------------------------------------------------------------------


def test_empty_model_allowlist_permits_any_model() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, model_id="any-model-id")
    policy = _make_policy(allow_models=[])
    passed, _ = verify_model_attestation(
        attestation, policy, [_pub_b64(sk)], at_time=_NOW
    )
    assert passed is True


def test_empty_prompt_allowlist_permits_any_prompt() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, prompt="Any system prompt here.")
    policy = _make_policy(allow_prompts=[])
    passed, _ = verify_model_attestation(
        attestation, policy, [_pub_b64(sk)], at_time=_NOW
    )
    assert passed is True


def test_empty_tool_allowlist_permits_any_tools() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, tool_ids=["any_tool", "another_tool"])
    policy = _make_policy(allow_tools=[])
    passed, _ = verify_model_attestation(
        attestation, policy, [_pub_b64(sk)], at_time=_NOW
    )
    assert passed is True


# ---------------------------------------------------------------------------
# Two agents — independent hashes
# ---------------------------------------------------------------------------


def test_two_agents_same_model_different_prompts() -> None:
    sk_a = _sk()
    sk_b = _sk()
    att_a = _make_attestation(sk_a, prompt="Prompt for agent A.")
    att_b = _make_attestation(sk_b, prompt="Prompt for agent B.")
    assert att_a.system_prompt_hash != att_b.system_prompt_hash


def test_two_agents_same_tools_same_hash() -> None:
    sk_a = _sk()
    sk_b = _sk()
    att_a = _make_attestation(sk_a, tool_ids=["tool_x", "tool_y"])
    att_b = _make_attestation(sk_b, tool_ids=["tool_y", "tool_x"])  # different order
    assert att_a.tool_manifest_hash == att_b.tool_manifest_hash


# ---------------------------------------------------------------------------
# LogicAttestationGate
# ---------------------------------------------------------------------------


def test_gate_passes_on_valid() -> None:
    sk = _sk()
    attestation = _make_attestation(sk)
    policy = _make_policy()
    gate = LogicAttestationGate(attestation, policy, [_pub_b64(sk)])
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is True  # type: ignore[attr-defined]
    assert result.gate_name == "logic_attestation"  # type: ignore[attr-defined]


def test_gate_blocks_model_not_permitted() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, model_id="other-model")
    policy = _make_policy(allow_models=[_MODEL_ID])
    gate = LogicAttestationGate(attestation, policy, [_pub_b64(sk)])
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is False  # type: ignore[attr-defined]
    assert result.detail == "model_not_permitted"  # type: ignore[attr-defined]


def test_gate_blocks_prompt_not_permitted() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, prompt="Unauthorized prompt.")
    policy = _make_policy(allow_prompts=[hashlib.sha256(_PROMPT.encode()).hexdigest()])
    gate = LogicAttestationGate(attestation, policy, [_pub_b64(sk)])
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is False  # type: ignore[attr-defined]
    assert result.detail == "system_prompt_not_permitted"  # type: ignore[attr-defined]


def test_gate_blocks_tool_manifest_not_permitted() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, tool_ids=["extra_tool"])
    policy = _make_policy(allow_tools=[ToolManifest(tool_ids=_TOOLS).manifest_hash])
    gate = LogicAttestationGate(attestation, policy, [_pub_b64(sk)])
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is False  # type: ignore[attr-defined]
    assert result.detail == "tool_manifest_not_permitted"  # type: ignore[attr-defined]


def test_gate_blocks_expired() -> None:
    sk = _sk()
    # Create attestation that expired before real test runtime (2024-01-01 + 10s)
    very_past = datetime(2024, 1, 1, tzinfo=timezone.utc)
    attestation = create_model_attestation(
        "agent-a", _MODEL_ID, _VERSION, _PROMPT, _TOOLS, sk,
        valid_for_seconds=10, now=very_past,
    )
    policy = _make_policy()
    gate = LogicAttestationGate(attestation, policy, [_pub_b64(sk)])
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is False  # type: ignore[attr-defined]
    assert result.detail == "expired"  # type: ignore[attr-defined]


def test_gate_blocks_missing_signature() -> None:
    sk = _sk()
    attestation = _make_attestation(sk).model_copy(update={"signature": None})
    policy = _make_policy()
    gate = LogicAttestationGate(attestation, policy, [_pub_b64(sk)])
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is False  # type: ignore[attr-defined]
    assert result.detail == "missing_signature"  # type: ignore[attr-defined]


def test_gate_blocks_invalid_signature() -> None:
    sk = _sk()
    wrong_sk = _sk()
    attestation = _make_attestation(sk)
    policy = _make_policy()
    gate = LogicAttestationGate(attestation, policy, [_pub_b64(wrong_sk)])
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is False  # type: ignore[attr-defined]
    assert result.detail == "invalid_signature"  # type: ignore[attr-defined]


def test_gate_blocks_token_binding_required() -> None:
    sk = _sk()
    attestation = _make_attestation(sk, token_id=None)
    policy = _make_policy(require_token=True)
    gate = LogicAttestationGate(attestation, policy, [_pub_b64(sk)])
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is False  # type: ignore[attr-defined]
    assert result.detail == "token_binding_required"  # type: ignore[attr-defined]


def test_gate_detail_contains_attestation_id_prefix() -> None:
    sk = _sk()
    attestation = _make_attestation(sk)
    policy = _make_policy()
    gate = LogicAttestationGate(attestation, policy, [_pub_b64(sk)])
    result = gate(None, None)  # type: ignore[attr-defined]
    assert attestation.attestation_id[:8] in result.detail  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _write(path: Path, obj: object) -> None:
    if hasattr(obj, "model_dump_json"):
        path.write_text(obj.model_dump_json(indent=2), encoding="utf-8")
    else:
        path.write_text(str(obj), encoding="utf-8")


def test_cli_attest_create() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "agent.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
        prompt_path = p / "prompt.txt"
        prompt_path.write_text(_PROMPT, encoding="utf-8")
        out_path = p / "attestation.json"

        runner = CliRunner()
        result = runner.invoke(trust, [
            "attest", "create",
            "--agent-sovereign", "agent-a",
            "--model-id", _MODEL_ID,
            "--model-version", _VERSION,
            "--system-prompt-file", str(prompt_path),
            "--tool-id", "tool_read",
            "--tool-id", "tool_write",
            "--signing-key", str(key_path),
            "--output", str(out_path),
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output
        assert out_path.exists()
        parsed = json.loads(out_path.read_text())
        assert parsed["model_id"] == _MODEL_ID
        assert parsed["signature"] is not None


def test_cli_attest_verify_exit_0() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "agent.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
        prompt_path = p / "prompt.txt"
        prompt_path.write_text(_PROMPT, encoding="utf-8")
        att_path = p / "attestation.json"

        runner = CliRunner()
        runner.invoke(trust, [
            "attest", "create",
            "--agent-sovereign", "agent-a",
            "--model-id", _MODEL_ID,
            "--model-version", _VERSION,
            "--system-prompt-file", str(prompt_path),
            "--tool-id", "tool_read",
            "--signing-key", str(key_path),
            "--output", str(att_path),
        ])

        attestation = ModelAttestation.model_validate_json(att_path.read_text())
        policy = _make_policy(
            allow_models=[_MODEL_ID],
            allow_prompts=[attestation.system_prompt_hash],
            allow_tools=[attestation.tool_manifest_hash],
        )
        policy_path = p / "policy.json"
        _write(policy_path, policy)
        pub_b64 = _pub_b64(sk)

        result = runner.invoke(trust, [
            "attest", "verify",
            "--attestation", str(att_path),
            "--policy", str(policy_path),
            "--public-key", pub_b64,
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output


def test_cli_attest_verify_exit_1() -> None:
    sk = _sk()
    wrong_sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "agent.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
        prompt_path = p / "prompt.txt"
        prompt_path.write_text(_PROMPT, encoding="utf-8")
        att_path = p / "attestation.json"

        runner = CliRunner()
        runner.invoke(trust, [
            "attest", "create",
            "--agent-sovereign", "agent-a",
            "--model-id", "wrong-model",
            "--model-version", _VERSION,
            "--system-prompt-file", str(prompt_path),
            "--signing-key", str(key_path),
            "--output", str(att_path),
        ])

        policy = _make_policy(allow_models=[_MODEL_ID])
        policy_path = p / "policy.json"
        _write(policy_path, policy)

        result = runner.invoke(trust, [
            "attest", "verify",
            "--attestation", str(att_path),
            "--policy", str(policy_path),
            "--public-key", _pub_b64(sk),
        ])
        assert result.exit_code == 1
        assert "[FAIL]" in result.output


def test_cli_attest_policy() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        import base64  # noqa: PLC0415
        key_path = p / "op.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
        out_path = p / "policy.json"

        runner = CliRunner()
        result = runner.invoke(trust, [
            "attest", "policy",
            "--operator-sovereign", "operator-x",
            "--allow-model", _MODEL_ID,
            "--valid-until", "2027-01-01T00:00:00Z",
            "--signing-key", str(key_path),
            "--output", str(out_path),
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output
        assert out_path.exists()
        parsed = json.loads(out_path.read_text())
        assert parsed["allowed_model_ids"] == [_MODEL_ID]


def test_cli_attest_verify_json_format() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "agent.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
        prompt_path = p / "prompt.txt"
        prompt_path.write_text(_PROMPT, encoding="utf-8")
        att_path = p / "attestation.json"

        runner = CliRunner()
        runner.invoke(trust, [
            "attest", "create",
            "--agent-sovereign", "agent-a",
            "--model-id", _MODEL_ID,
            "--model-version", _VERSION,
            "--system-prompt-file", str(prompt_path),
            "--signing-key", str(key_path),
            "--output", str(att_path),
        ])

        attestation = ModelAttestation.model_validate_json(att_path.read_text())
        policy = _make_policy()
        policy_path = p / "policy.json"
        _write(policy_path, policy)

        result = runner.invoke(trust, [
            "attest", "verify",
            "--attestation", str(att_path),
            "--policy", str(policy_path),
            "--public-key", _pub_b64(sk),
            "--format", "json",
        ])
        parsed = json.loads(result.output)
        assert parsed["passed"] is True
        assert parsed["reason"] == "valid"
