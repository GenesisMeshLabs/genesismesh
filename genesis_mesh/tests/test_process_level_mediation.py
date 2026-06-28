"""Tests for Process-Level Execution Mediation (v0.45)."""

from __future__ import annotations

import base64
import json
import socket
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nacl.signing
import pytest
from click.testing import CliRunner

from genesis_mesh.cli.decision_ops import trust
from genesis_mesh.crypto import sign_model
from genesis_mesh.guard.daemon import GenesisGuardDaemon
from genesis_mesh.models.context import BoundaryDecision
from genesis_mesh.models.invocation_token import InvocationToken
from genesis_mesh.models.mediation import (
    ExecutionMediationRequest,
    MediatedExecutionReceipt,
    MediationRejection,
)
from genesis_mesh.trust.mediation import (
    MediationRejectionReason,
    create_mediated_execution_receipt,
    validate_mediation_request,
)

_NOW = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)


def _sk() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()


def _pub_b64(sk: nacl.signing.SigningKey) -> str:
    return base64.b64encode(bytes(sk.verify_key)).decode()


def _decision(
    sk: nacl.signing.SigningKey,
    authorized: bool = True,
    valid_until: datetime | None = None,
) -> BoundaryDecision:
    d = BoundaryDecision(
        context_id="ctx-1",
        agreement_id="agr-1",
        authorized=authorized,
        decision_valid_until=valid_until or (_NOW + timedelta(hours=1)),
        operator_sovereign_id="operator-a",
    )
    sig = sign_model(d, sk, "operator-a")
    return d.model_copy(update={"signature": sig})


def _token(
    sk: nacl.signing.SigningKey,
    capabilities: list[str] | None = None,
    max_invocations: int | None = None,
    expires_at: datetime | None = None,
) -> InvocationToken:
    t = InvocationToken(
        issued_at=_NOW,
        expires_at=expires_at or (_NOW + timedelta(hours=1)),
        issuer_sovereign_id="operator-a",
        bearer_sovereign_id="agent-a",
        agreement_id="agr-1",
        capabilities=capabilities or ["run-python"],
        max_invocations=max_invocations,
    )
    sig = sign_model(t, sk, "operator-a")
    return t.model_copy(update={"signature": sig})


def _request(
    agent_sk: nacl.signing.SigningKey,
    capability: str = "run-python",
    decision_id: str = "dec-1",
    command: list[str] | None = None,
    token_id: str | None = None,
) -> ExecutionMediationRequest:
    req = ExecutionMediationRequest(
        agent_sovereign_id="agent-a",
        requested_capability=capability,
        decision_id=decision_id,
        token_id=token_id,
        subprocess_command=command or ["python", "--version"],
        allowed_env_vars=[],
        requested_at=_NOW,
    )
    sig = sign_model(req, agent_sk, "agent-a")
    return req.model_copy(update={"signature": sig})


# ---------------------------------------------------------------------------
# validate_mediation_request
# ---------------------------------------------------------------------------


def test_valid_request_passes() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, decision_id=decision.decision_id)
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)], at_time=_NOW
    )
    assert ok
    assert reason is None


def test_invalid_signature_rejected() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, decision_id=decision.decision_id)
    # tamper: sign with different key
    other_sk = _sk()
    bad_sig = sign_model(req, other_sk, "agent-a")
    req = req.model_copy(update={"signature": bad_sig})
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)], at_time=_NOW
    )
    assert not ok
    assert reason == "invalid_request_signature"


def test_missing_signature_rejected() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, decision_id=decision.decision_id)
    req = req.model_copy(update={"signature": None})
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)], at_time=_NOW
    )
    assert not ok
    assert reason == "invalid_request_signature"


def test_decision_not_found() -> None:
    agent_sk = _sk()
    req = _request(agent_sk)
    ok, reason = validate_mediation_request(
        req, None, [_pub_b64(agent_sk)], at_time=_NOW
    )
    assert not ok
    assert reason == "decision_not_found"


def test_decision_expired() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    past = datetime(2024, 1, 1, tzinfo=timezone.utc)
    decision = _decision(op_sk, valid_until=past + timedelta(hours=1))
    req = _request(agent_sk, decision_id=decision.decision_id)
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)], at_time=past + timedelta(hours=2)
    )
    assert not ok
    assert reason == "decision_expired"


def test_decision_not_authorized() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk, authorized=False)
    req = _request(agent_sk, decision_id=decision.decision_id)
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)], at_time=_NOW
    )
    assert not ok
    assert reason == "capability_not_authorized"


def test_capability_not_in_token() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    token = _token(op_sk, capabilities=["run-js"])
    req = _request(agent_sk, capability="run-python", decision_id=decision.decision_id)
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        token=token, at_time=_NOW
    )
    assert not ok
    assert reason == "capability_not_authorized"


def test_token_expired() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    past = datetime(2024, 1, 1, tzinfo=timezone.utc)
    token = _token(op_sk, capabilities=["run-python"], expires_at=past)
    req = _request(agent_sk, decision_id=decision.decision_id)
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        token=token, at_time=_NOW
    )
    assert not ok
    assert reason == "token_expired"


def test_token_budget_exhausted() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    token = _token(op_sk, capabilities=["run-python"], max_invocations=3)
    req = _request(agent_sk, decision_id=decision.decision_id)
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        token=token, use_count=3, at_time=_NOW
    )
    assert not ok
    assert reason == "token_budget_exhausted"


def test_command_not_in_allowlist() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, command=["bash", "-c", "whoami"], decision_id=decision.decision_id)
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        command_allowlist=["python", "node"],
        at_time=_NOW,
    )
    assert not ok
    assert reason == "command_not_in_allowlist"


def test_command_in_allowlist_passes() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, command=["python", "--version"], decision_id=decision.decision_id)
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        command_allowlist=["python", "node"],
        at_time=_NOW,
    )
    assert ok


# ---------------------------------------------------------------------------
# create_mediated_execution_receipt
# ---------------------------------------------------------------------------


def test_receipt_is_signed() -> None:
    guard_sk = _sk()
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, decision_id=decision.decision_id)
    receipt = create_mediated_execution_receipt(
        req, subprocess_pid=1234,
        guard_sovereign_id="guard-a",
        signing_key=guard_sk,
        exit_code=0,
        now=_NOW,
    )
    assert receipt.signature is not None
    assert receipt.subprocess_pid == 1234
    assert receipt.subprocess_exit_code == 0
    assert receipt.guard_sovereign_id == "guard-a"


def test_receipt_fields_match_request() -> None:
    guard_sk = _sk()
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, capability="run-python", decision_id=decision.decision_id)
    receipt = create_mediated_execution_receipt(
        req, subprocess_pid=99,
        guard_sovereign_id="guard-a",
        signing_key=guard_sk,
        now=_NOW,
    )
    assert receipt.request_id == req.request_id
    assert receipt.capability == "run-python"
    assert receipt.decision_id == decision.decision_id


# ---------------------------------------------------------------------------
# GenesisGuardDaemon
# ---------------------------------------------------------------------------


def test_daemon_rejects_invalid_decision() -> None:
    guard_sk = _sk()
    agent_sk = _sk()
    daemon = GenesisGuardDaemon(
        guard_sovereign_id="guard-a",
        signing_key=guard_sk,
        decision_store={},  # empty
        agent_public_keys={"agent-a": [_pub_b64(agent_sk)]},
    )
    req = _request(agent_sk)
    result = daemon.handle_request(req)
    assert isinstance(result, MediationRejection)
    assert result.reason == "decision_not_found"


def test_daemon_issues_receipt_for_valid_request() -> None:
    guard_sk = _sk()
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)

    daemon = GenesisGuardDaemon(
        guard_sovereign_id="guard-a",
        signing_key=guard_sk,
        decision_store={decision.decision_id: decision},
        agent_public_keys={"agent-a": [_pub_b64(agent_sk)]},
        command_allowlist=["python"],
    )
    req = _request(agent_sk, command=["python", "--version"],
                   decision_id=decision.decision_id)
    result = daemon.handle_request(req)
    assert isinstance(result, MediatedExecutionReceipt)
    assert result.signature is not None
    assert result.subprocess_exit_code == 0


def test_daemon_rejects_command_not_in_allowlist() -> None:
    guard_sk = _sk()
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)

    daemon = GenesisGuardDaemon(
        guard_sovereign_id="guard-a",
        signing_key=guard_sk,
        decision_store={decision.decision_id: decision},
        agent_public_keys={"agent-a": [_pub_b64(agent_sk)]},
        command_allowlist=["node"],
    )
    req = _request(agent_sk, command=["python", "--version"],
                   decision_id=decision.decision_id)
    result = daemon.handle_request(req)
    assert isinstance(result, MediationRejection)
    assert result.reason == "command_not_in_allowlist"


def test_daemon_socket_integration() -> None:
    """End-to-end: start daemon, send request over TCP, receive receipt."""
    guard_sk = _sk()
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)

    daemon = GenesisGuardDaemon(
        guard_sovereign_id="guard-a",
        signing_key=guard_sk,
        decision_store={decision.decision_id: decision},
        agent_public_keys={"agent-a": [_pub_b64(agent_sk)]},
        command_allowlist=["python"],
        host="127.0.0.1",
        port=0,
    )
    daemon.start()
    time.sleep(0.1)
    try:
        req = _request(agent_sk, command=["python", "--version"],
                       decision_id=decision.decision_id)
        raw = req.model_dump_json().encode()
        with socket.create_connection(("127.0.0.1", daemon.port), timeout=5) as sock:
            sock.sendall(raw)
            resp = b""
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                resp += chunk
        receipt = MediatedExecutionReceipt.model_validate_json(resp)
        assert receipt.subprocess_exit_code == 0
    finally:
        daemon.stop()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_guard_verify_valid() -> None:
    guard_sk = _sk()
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, decision_id=decision.decision_id)
    receipt = create_mediated_execution_receipt(
        req, subprocess_pid=42,
        guard_sovereign_id="guard-a",
        signing_key=guard_sk,
        exit_code=0,
        now=_NOW,
    )
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        r_path = p / "receipt.json"
        r_path.write_text(receipt.model_dump_json(indent=2), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(trust, [
            "guard", "verify",
            "--receipt", str(r_path),
            "--guard-key", _pub_b64(guard_sk),
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output


def test_cli_guard_verify_wrong_key_fails() -> None:
    guard_sk = _sk()
    wrong_sk = _sk()
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, decision_id=decision.decision_id)
    receipt = create_mediated_execution_receipt(
        req, subprocess_pid=42,
        guard_sovereign_id="guard-a",
        signing_key=guard_sk,
        exit_code=0,
        now=_NOW,
    )
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        r_path = p / "receipt.json"
        r_path.write_text(receipt.model_dump_json(indent=2), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(trust, [
            "guard", "verify",
            "--receipt", str(r_path),
            "--guard-key", _pub_b64(wrong_sk),
        ])
        assert result.exit_code != 0
