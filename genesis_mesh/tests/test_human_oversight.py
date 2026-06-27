"""Tests for Human Oversight + Dual-Signed Commitments (v0.34).

Covers:
- evaluate_oversight_policy(): all 8 checks individually and combined
- propose_commitment(): human_approve path, automatic raises, block raises
- approve_commitment(): DualSignedCommitment with both signatures
- reject_commitment(): signed rejection response
- verify_dual_signed_commitment(): all 7 reason codes
- DualSignedCommitment.is_fully_signed()
- CLI: evaluate / propose / approve / reject / verify
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nacl.signing
import pytest
from click.testing import CliRunner

from genesis_mesh.cli.decision_ops import trust
from genesis_mesh.models.oversight import (
    DualSignedCommitment,
    HumanApprovalRequest,
    HumanOversightPolicy,
)
from genesis_mesh.trust.oversight import (
    DualSignedCommitmentVerificationResult,
    approve_commitment,
    evaluate_oversight_policy,
    propose_commitment,
    reject_commitment,
    verify_dual_signed_commitment,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 1, 14, 0, 0, tzinfo=timezone.utc)  # 14:00 UTC
_AGREEMENT_ID = "agr-123"
_HUMAN_ID = "human-custodian"
_AGENT_ID = "agent-sovereign"


def _agent_sk() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()


def _human_sk() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()


def _pub_b64(sk: nacl.signing.SigningKey) -> str:
    return base64.b64encode(bytes(sk.verify_key)).decode()


def _write_key(sk: nacl.signing.SigningKey) -> str:
    fd, path = tempfile.mkstemp(suffix=".key")
    os.close(fd)
    Path(path).write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
    return path


def _make_policy(
    allowed_caps: list[str] | None = None,
    allowlist: list[str] | None = None,
    value_threshold: float | None = None,
    allowed_hours: tuple[int, int] | None = None,
    frequency_limit: tuple[int, int] | None = None,
) -> HumanOversightPolicy:
    return HumanOversightPolicy(
        agreement_id=_AGREEMENT_ID,
        human_sovereign_id=_HUMAN_ID,
        allowed_capabilities=allowed_caps or ["transactions.send", "config.write"],
        counterparty_allowlist=allowlist or [],
        value_threshold=value_threshold,
        allowed_hours=allowed_hours,
        frequency_limit=frequency_limit,
        created_at=_NOW,
    )


def _make_action(**kwargs) -> dict:
    return {"capability": "transactions.send", "value": 100.0, **kwargs}


# ---------------------------------------------------------------------------
# evaluate_oversight_policy — per-check tests
# ---------------------------------------------------------------------------


class TestPolicyChecks:
    def test_all_pass_automatic(self) -> None:
        policy = _make_policy()
        result = evaluate_oversight_policy(policy, _make_action(), _AGENT_ID, now=_NOW)
        assert result.result == "automatic"
        assert not result.escalation_reasons

    def test_capability_not_in_allowed_blocks(self) -> None:
        policy = _make_policy()
        action = {"capability": "admin.delete"}
        result = evaluate_oversight_policy(policy, action, _AGENT_ID, now=_NOW)
        assert result.result == "block"
        cap_check = next(o for n, o in result.checks if n == "capability_scope")
        assert cap_check == "block"

    def test_counterparty_not_in_allowlist_escalates(self) -> None:
        policy = _make_policy(allowlist=["trusted-sovereign"])
        result = evaluate_oversight_policy(policy, _make_action(), "unknown-sovereign", now=_NOW)
        assert result.result == "human_approve"
        cc_check = next(o for n, o in result.checks if n == "counterparty_allowlist")
        assert cc_check == "escalate"

    def test_counterparty_in_allowlist_passes(self) -> None:
        policy = _make_policy(allowlist=["trusted-sovereign"])
        result = evaluate_oversight_policy(policy, _make_action(), "trusted-sovereign", now=_NOW)
        assert result.result == "automatic"

    def test_empty_allowlist_passes_any_requester(self) -> None:
        policy = _make_policy(allowlist=[])
        result = evaluate_oversight_policy(policy, _make_action(), "any-sovereign", now=_NOW)
        cc_check = next(o for n, o in result.checks if n == "counterparty_allowlist")
        assert cc_check == "pass"

    def test_value_above_threshold_escalates(self) -> None:
        policy = _make_policy(value_threshold=50.0)
        action = _make_action(value=200.0)
        result = evaluate_oversight_policy(policy, action, _AGENT_ID, now=_NOW)
        assert result.result == "human_approve"
        vt_check = next(o for n, o in result.checks if n == "value_threshold")
        assert vt_check == "escalate"

    def test_value_below_threshold_passes(self) -> None:
        policy = _make_policy(value_threshold=500.0)
        action = _make_action(value=100.0)
        result = evaluate_oversight_policy(policy, action, _AGENT_ID, now=_NOW)
        vt_check = next(o for n, o in result.checks if n == "value_threshold")
        assert vt_check == "pass"

    def test_no_value_threshold_passes(self) -> None:
        policy = _make_policy(value_threshold=None)
        result = evaluate_oversight_policy(policy, _make_action(value=9999), _AGENT_ID, now=_NOW)
        vt_check = next(o for n, o in result.checks if n == "value_threshold")
        assert vt_check == "pass"

    def test_outside_time_window_escalates(self) -> None:
        # _NOW is 14:00 UTC; window is 09:00-12:00
        policy = _make_policy(allowed_hours=(9, 12))
        result = evaluate_oversight_policy(policy, _make_action(), _AGENT_ID, now=_NOW)
        tw_check = next(o for n, o in result.checks if n == "time_window")
        assert tw_check == "escalate"

    def test_inside_time_window_passes(self) -> None:
        # _NOW is 14:00 UTC; window is 13:00-17:00
        policy = _make_policy(allowed_hours=(13, 17))
        result = evaluate_oversight_policy(policy, _make_action(), _AGENT_ID, now=_NOW)
        tw_check = next(o for n, o in result.checks if n == "time_window")
        assert tw_check == "pass"

    def test_frequency_limit_exceeded_escalates(self) -> None:
        policy = _make_policy(frequency_limit=(5, 60))
        result = evaluate_oversight_policy(policy, _make_action(), _AGENT_ID, now=_NOW,
                                           recent_action_count=5)
        fl_check = next(o for n, o in result.checks if n == "frequency_limit")
        assert fl_check == "escalate"

    def test_frequency_limit_not_exceeded_passes(self) -> None:
        policy = _make_policy(frequency_limit=(5, 60))
        result = evaluate_oversight_policy(policy, _make_action(), _AGENT_ID, now=_NOW,
                                           recent_action_count=4)
        fl_check = next(o for n, o in result.checks if n == "frequency_limit")
        assert fl_check == "pass"

    def test_irreversible_flag_escalates(self) -> None:
        policy = _make_policy()
        action = _make_action(irreversible=True)
        result = evaluate_oversight_policy(policy, action, _AGENT_ID, now=_NOW)
        ir_check = next(o for n, o in result.checks if n == "irreversibility")
        assert ir_check == "escalate"

    def test_novel_counterparty_flag_escalates(self) -> None:
        policy = _make_policy()
        action = _make_action(novel_counterparty=True)
        result = evaluate_oversight_policy(policy, action, _AGENT_ID, now=_NOW)
        nc_check = next(o for n, o in result.checks if n == "novel_counterparty")
        assert nc_check == "escalate"

    def test_anomaly_flag_blocks(self) -> None:
        policy = _make_policy()
        result = evaluate_oversight_policy(policy, _make_action(), _AGENT_ID, now=_NOW,
                                           anomaly=True)
        assert result.result == "block"
        af_check = next(o for n, o in result.checks if n == "anomaly_flag")
        assert af_check == "block"

    def test_block_takes_precedence_over_escalate(self) -> None:
        # anomaly=True (block) + irreversible=True (escalate) → block
        policy = _make_policy()
        action = _make_action(irreversible=True)
        result = evaluate_oversight_policy(policy, action, _AGENT_ID, now=_NOW, anomaly=True)
        assert result.result == "block"

    def test_all_8_checks_present_in_output(self) -> None:
        policy = _make_policy()
        result = evaluate_oversight_policy(policy, _make_action(), _AGENT_ID, now=_NOW)
        check_names = [n for n, _ in result.checks]
        expected = [
            "capability_scope", "counterparty_allowlist", "value_threshold",
            "time_window", "frequency_limit", "irreversibility",
            "novel_counterparty", "anomaly_flag",
        ]
        assert check_names == expected


# ---------------------------------------------------------------------------
# propose_commitment
# ---------------------------------------------------------------------------


class TestProposeCommitment:
    def test_escalating_action_returns_request(self) -> None:
        policy = _make_policy()
        action = _make_action(irreversible=True)
        agent_sk = _agent_sk()
        request, evaluation = propose_commitment(
            policy, action, _AGENT_ID, agent_sk, issued_by="agent-key", now=_NOW,
        )
        assert isinstance(request, HumanApprovalRequest)
        assert request.agent_signature is not None
        assert evaluation.result == "human_approve"

    def test_automatic_action_raises_runtime_error(self) -> None:
        policy = _make_policy()
        agent_sk = _agent_sk()
        with pytest.raises(RuntimeError, match="does not require human approval"):
            propose_commitment(
                policy, _make_action(), _AGENT_ID, agent_sk, issued_by="agent-key", now=_NOW,
            )

    def test_blocked_action_raises_value_error(self) -> None:
        policy = _make_policy()
        agent_sk = _agent_sk()
        with pytest.raises(ValueError, match="blocked by oversight policy"):
            propose_commitment(
                policy, _make_action(), _AGENT_ID, agent_sk,
                issued_by="agent-key", now=_NOW, anomaly=True,
            )

    def test_request_has_correct_expires_at(self) -> None:
        policy = _make_policy()
        action = _make_action(irreversible=True)
        agent_sk = _agent_sk()
        request, _ = propose_commitment(
            policy, action, _AGENT_ID, agent_sk, issued_by="agent-key",
            approval_window_seconds=120, now=_NOW,
        )
        expected_expires = _NOW + timedelta(seconds=120)
        assert request.expires_at == expected_expires


# ---------------------------------------------------------------------------
# approve_commitment
# ---------------------------------------------------------------------------


class TestApproveCommitment:
    def _make_request(self) -> tuple[HumanApprovalRequest, HumanOversightPolicy,
                                     nacl.signing.SigningKey, nacl.signing.SigningKey]:
        policy = _make_policy()
        action = _make_action(irreversible=True)
        agent_sk = _agent_sk()
        human_sk = _human_sk()
        request, _ = propose_commitment(
            policy, action, _AGENT_ID, agent_sk, issued_by="agent-key", now=_NOW,
        )
        return request, policy, agent_sk, human_sk

    def test_approve_returns_response_and_commitment(self) -> None:
        request, policy, _, human_sk = self._make_request()
        response, commitment = approve_commitment(request, policy, human_sk,
                                                  issued_by="human-key", now=_NOW)
        assert response.approved is True
        assert commitment.is_fully_signed()

    def test_commitment_has_both_signatures(self) -> None:
        request, policy, _, human_sk = self._make_request()
        _, commitment = approve_commitment(request, policy, human_sk,
                                           issued_by="human-key", now=_NOW)
        assert commitment.agent_signature is not None
        assert commitment.human_signature is not None

    def test_commitment_links_to_request(self) -> None:
        request, policy, _, human_sk = self._make_request()
        _, commitment = approve_commitment(request, policy, human_sk,
                                           issued_by="human-key", now=_NOW)
        assert commitment.request_id == request.request_id

    def test_is_fully_signed_false_before_approval(self) -> None:
        request, _, _, _ = self._make_request()
        partial = DualSignedCommitment(
            request_id=request.request_id,
            response_id="resp-1",
            agreement_id=_AGREEMENT_ID,
            acting_sovereign_id=_AGENT_ID,
            human_sovereign_id=_HUMAN_ID,
            proposed_action=request.proposed_action,
            committed_at=_NOW,
            expires_at=_NOW + timedelta(minutes=10),
            agent_signature=request.agent_signature,
        )
        assert partial.is_fully_signed() is False


# ---------------------------------------------------------------------------
# reject_commitment
# ---------------------------------------------------------------------------


class TestRejectCommitment:
    def test_reject_returns_response_not_approved(self) -> None:
        policy = _make_policy()
        action = _make_action(irreversible=True)
        agent_sk = _agent_sk()
        human_sk = _human_sk()
        request, _ = propose_commitment(
            policy, action, _AGENT_ID, agent_sk, issued_by="agent-key", now=_NOW,
        )
        response = reject_commitment(request, policy, human_sk,
                                     issued_by="human-key", note="unusual activity")
        assert response.approved is False
        assert response.human_signature is not None
        assert response.response_note == "unusual activity"


# ---------------------------------------------------------------------------
# verify_dual_signed_commitment — all 7 reason codes
# ---------------------------------------------------------------------------


class TestVerifyDualSignedCommitment:
    def _make_commitment(self) -> tuple[DualSignedCommitment, HumanApprovalRequest,
                                        nacl.signing.SigningKey, nacl.signing.SigningKey]:
        policy = _make_policy()
        action = _make_action(irreversible=True)
        agent_sk = _agent_sk()
        human_sk = _human_sk()
        request, _ = propose_commitment(
            policy, action, _AGENT_ID, agent_sk, issued_by="agent-key", now=_NOW,
        )
        _, commitment = approve_commitment(request, policy, human_sk,
                                           issued_by="human-key", now=_NOW)
        return commitment, request, agent_sk, human_sk

    def test_valid(self) -> None:
        commitment, request, agent_sk, human_sk = self._make_commitment()
        result = verify_dual_signed_commitment(
            commitment, [_pub_b64(agent_sk)], [_pub_b64(human_sk)],
            request=request, at_time=_NOW,
        )
        assert result.valid is True
        assert result.reason == "valid"

    def test_missing_agent_signature(self) -> None:
        commitment, _, agent_sk, human_sk = self._make_commitment()
        unsigned = commitment.model_copy(update={"agent_signature": None})
        result = verify_dual_signed_commitment(
            unsigned, [_pub_b64(agent_sk)], [_pub_b64(human_sk)], at_time=_NOW,
        )
        assert result.valid is False
        assert result.reason == "missing_agent_signature"

    def test_missing_human_signature(self) -> None:
        commitment, _, agent_sk, human_sk = self._make_commitment()
        unsigned = commitment.model_copy(update={"human_signature": None})
        result = verify_dual_signed_commitment(
            unsigned, [_pub_b64(agent_sk)], [_pub_b64(human_sk)], at_time=_NOW,
        )
        assert result.valid is False
        assert result.reason == "missing_human_signature"

    def test_invalid_agent_signature(self) -> None:
        commitment, request, _, human_sk = self._make_commitment()
        wrong_sk = _agent_sk()
        result = verify_dual_signed_commitment(
            commitment, [_pub_b64(wrong_sk)], [_pub_b64(human_sk)],
            request=request, at_time=_NOW,
        )
        assert result.valid is False
        assert result.reason == "invalid_agent_signature"

    def test_invalid_human_signature(self) -> None:
        commitment, _, agent_sk, _ = self._make_commitment()
        wrong_sk = _human_sk()
        result = verify_dual_signed_commitment(
            commitment, [_pub_b64(agent_sk)], [_pub_b64(wrong_sk)], at_time=_NOW,
        )
        assert result.valid is False
        assert result.reason == "invalid_human_signature"

    def test_request_response_mismatch(self) -> None:
        commitment, request, agent_sk, human_sk = self._make_commitment()
        wrong_request = request.model_copy(update={"request_id": "wrong-id"})
        result = verify_dual_signed_commitment(
            commitment, [_pub_b64(agent_sk)], [_pub_b64(human_sk)],
            request=wrong_request, at_time=_NOW,
        )
        assert result.valid is False
        assert result.reason == "request_response_mismatch"

    def test_expired(self) -> None:
        commitment, _, agent_sk, human_sk = self._make_commitment()
        future_time = commitment.expires_at + timedelta(seconds=1)
        result = verify_dual_signed_commitment(
            commitment, [_pub_b64(agent_sk)], [_pub_b64(human_sk)], at_time=future_time,
        )
        assert result.valid is False
        assert result.reason == "expired"


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestOversightCLI:
    def _setup(self) -> tuple[CliRunner, str, str, str, str, str, str]:
        runner = CliRunner()
        agent_sk = _agent_sk()
        human_sk = _human_sk()
        tmpdir = tempfile.mkdtemp()

        policy = _make_policy()
        action = _make_action(irreversible=True)

        policy_path = os.path.join(tmpdir, "policy.json")
        action_path = os.path.join(tmpdir, "action.json")
        agent_key_path = _write_key(agent_sk)
        human_key_path = _write_key(human_sk)

        Path(policy_path).write_text(policy.model_dump_json(indent=2), encoding="utf-8")
        Path(action_path).write_text(json.dumps(action, indent=2), encoding="utf-8")

        return (
            runner, policy_path, action_path,
            agent_key_path, human_key_path,
            _pub_b64(agent_sk), _pub_b64(human_sk),
        )

    def test_cli_evaluate_escalates(self) -> None:
        runner, policy_path, action_path, _, _, _, _ = self._setup()
        result = runner.invoke(trust, [
            "oversight", "evaluate",
            "--policy", policy_path,
            "--action", action_path,
            "--requester", _AGENT_ID,
        ])
        assert result.exit_code == 1, result.output  # human_approve = exit 1
        assert "HUMAN_APPROVE" in result.output

    def test_cli_evaluate_automatic(self) -> None:
        runner, policy_path, _, _, _, _, _ = self._setup()
        tmpdir = tempfile.mkdtemp()
        simple_action_path = os.path.join(tmpdir, "action.json")
        Path(simple_action_path).write_text(
            json.dumps({"capability": "transactions.send", "value": 10.0}),
            encoding="utf-8",
        )
        result = runner.invoke(trust, [
            "oversight", "evaluate",
            "--policy", policy_path,
            "--action", simple_action_path,
            "--requester", _AGENT_ID,
        ])
        assert result.exit_code == 0, result.output
        assert "AUTOMATIC" in result.output

    def test_cli_propose(self) -> None:
        runner, policy_path, action_path, agent_key_path, _, _, _ = self._setup()
        tmpdir = tempfile.mkdtemp()
        request_path = os.path.join(tmpdir, "request.json")
        result = runner.invoke(trust, [
            "oversight", "propose",
            "--policy", policy_path,
            "--action", action_path,
            "--requester", _AGENT_ID,
            "--signing-key", agent_key_path,
            "--output", request_path,
        ])
        assert result.exit_code == 0, result.output
        assert Path(request_path).exists()
        data = json.loads(Path(request_path).read_text(encoding="utf-8"))
        assert "request_id" in data
        assert "agent_signature" in data

    def test_cli_approve(self) -> None:
        runner, policy_path, action_path, agent_key_path, human_key_path, _, _ = self._setup()
        tmpdir = tempfile.mkdtemp()
        request_path = os.path.join(tmpdir, "request.json")
        commitment_path = os.path.join(tmpdir, "commitment.json")

        runner.invoke(trust, [
            "oversight", "propose",
            "--policy", policy_path,
            "--action", action_path,
            "--requester", _AGENT_ID,
            "--signing-key", agent_key_path,
            "--output", request_path,
        ])

        result = runner.invoke(trust, [
            "oversight", "approve",
            "--request", request_path,
            "--policy", policy_path,
            "--signing-key", human_key_path,
            "--output", commitment_path,
        ])
        assert result.exit_code == 0, result.output
        data = json.loads(Path(commitment_path).read_text(encoding="utf-8"))
        assert data["agent_signature"] is not None
        assert data["human_signature"] is not None

    def test_cli_verify_ok(self) -> None:
        runner, policy_path, action_path, agent_key_path, human_key_path, agent_pub, human_pub = self._setup()
        tmpdir = tempfile.mkdtemp()
        request_path = os.path.join(tmpdir, "request.json")
        commitment_path = os.path.join(tmpdir, "commitment.json")

        runner.invoke(trust, [
            "oversight", "propose",
            "--policy", policy_path, "--action", action_path,
            "--requester", _AGENT_ID, "--signing-key", agent_key_path,
            "--output", request_path,
        ])
        runner.invoke(trust, [
            "oversight", "approve",
            "--request", request_path, "--policy", policy_path,
            "--signing-key", human_key_path, "--output", commitment_path,
        ])

        result = runner.invoke(trust, [
            "oversight", "verify",
            "--commitment", commitment_path,
            "--agent-key", agent_pub,
            "--human-key", human_pub,
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output

    def test_cli_verify_json_format(self) -> None:
        runner, policy_path, action_path, agent_key_path, human_key_path, agent_pub, human_pub = self._setup()
        tmpdir = tempfile.mkdtemp()
        request_path = os.path.join(tmpdir, "request.json")
        commitment_path = os.path.join(tmpdir, "commitment.json")

        runner.invoke(trust, [
            "oversight", "propose",
            "--policy", policy_path, "--action", action_path,
            "--requester", _AGENT_ID, "--signing-key", agent_key_path,
            "--output", request_path,
        ])
        runner.invoke(trust, [
            "oversight", "approve",
            "--request", request_path, "--policy", policy_path,
            "--signing-key", human_key_path, "--output", commitment_path,
        ])

        result = runner.invoke(trust, [
            "oversight", "verify",
            "--commitment", commitment_path,
            "--agent-key", agent_pub,
            "--human-key", human_pub,
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["valid"] is True
        assert data["reason"] == "valid"
