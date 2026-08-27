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


# Default allowlist for tests whose subject is not the allowlist itself.
# Entries are full command lines (F-01): "python" alone would not match.
_ALLOWLIST = ["python --version"]


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


def _issuer_keys(op_sk: nacl.signing.SigningKey) -> dict[str, list[str]]:
    """Token-issuer key map for the guard (F-01 gap 4)."""
    return {"operator-a": [_pub_b64(op_sk)]}


def _request(
    agent_sk: nacl.signing.SigningKey,
    capability: str = "run-python",
    decision_id: str = "dec-1",
    command: list[str] | None = None,
    token_id: str | None = None,
    token: InvocationToken | None = None,
) -> ExecutionMediationRequest:
    req = ExecutionMediationRequest(
        agent_sovereign_id="agent-a",
        requested_capability=capability,
        decision_id=decision_id,
        token_id=token_id,
        invocation_token=token,
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
    req = _request(agent_sk, decision_id=decision.decision_id, token=_token(op_sk))
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=_ALLOWLIST,
        at_time=_NOW,
    )
    assert ok
    assert reason is None


def test_invalid_signature_rejected() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, decision_id=decision.decision_id, token=_token(op_sk))
    # tamper: sign with different key
    other_sk = _sk()
    bad_sig = sign_model(req, other_sk, "agent-a")
    req = req.model_copy(update={"signature": bad_sig})
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=_ALLOWLIST,
        at_time=_NOW,
    )
    assert not ok
    assert reason == "invalid_request_signature"


def test_missing_signature_rejected() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, decision_id=decision.decision_id, token=_token(op_sk))
    req = req.model_copy(update={"signature": None})
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=_ALLOWLIST,
        at_time=_NOW,
    )
    assert not ok
    assert reason == "invalid_request_signature"


def test_decision_not_found() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    req = _request(agent_sk, token=_token(op_sk))
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
    req = _request(agent_sk, decision_id=decision.decision_id, token=_token(op_sk))
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=_ALLOWLIST,
        at_time=past + timedelta(hours=2),
    )
    assert not ok
    assert reason == "decision_expired"


def test_decision_not_authorized() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk, authorized=False)
    req = _request(agent_sk, decision_id=decision.decision_id, token=_token(op_sk))
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=_ALLOWLIST,
        at_time=_NOW,
    )
    assert not ok
    assert reason == "capability_not_authorized"


def test_capability_not_in_token() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    token = _token(op_sk, capabilities=["run-js"])
    req = _request(agent_sk, capability="run-python", decision_id=decision.decision_id,
                   token=token)
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=_ALLOWLIST,
        at_time=_NOW,
    )
    assert not ok
    assert reason == "capability_not_authorized"


def test_token_expired() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    past = datetime(2024, 1, 1, tzinfo=timezone.utc)
    token = _token(op_sk, capabilities=["run-python"], expires_at=past)
    req = _request(agent_sk, decision_id=decision.decision_id, token=token)
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=_ALLOWLIST,
        at_time=_NOW,
    )
    assert not ok
    assert reason == "token_expired"


def test_token_budget_exhausted() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    token = _token(op_sk, capabilities=["run-python"], max_invocations=3)
    req = _request(agent_sk, decision_id=decision.decision_id, token=token)
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=_ALLOWLIST,
        use_count=3, at_time=_NOW,
    )
    assert not ok
    assert reason == "token_budget_exhausted"


def test_command_not_in_allowlist() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, command=["bash", "-c", "whoami"], decision_id=decision.decision_id, token=_token(op_sk))
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=["python --version", "node --version"],
        at_time=_NOW,
    )
    assert not ok
    assert reason == "command_not_in_allowlist"


def test_command_in_allowlist_passes() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, command=["python", "--version"], decision_id=decision.decision_id, token=_token(op_sk))
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=["python --version", "node --version"],
        at_time=_NOW,
    )
    assert ok


# ---------------------------------------------------------------------------
# F-01 regression — fail-closed allowlist, full-command matching,
# decision-signature verification.  Gap 4 (binding the decision to the
# requesting agent/capability) is NOT covered here; it is still open.
# ---------------------------------------------------------------------------


def test_missing_allowlist_denies() -> None:
    """F-01 gap 1: an absent allowlist used to skip the check; it now denies."""
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, decision_id=decision.decision_id, token=_token(op_sk))
    allowlist: list[str] | None
    for allowlist in (None, []):
        ok, reason = validate_mediation_request(
            req, decision, [_pub_b64(agent_sk)],
            operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
            command_allowlist=allowlist,
            at_time=_NOW,
        )
        assert not ok
        assert reason == "command_not_in_allowlist"


def test_daemon_refuses_to_start_without_allowlist() -> None:
    """F-01 gap 1: the guard must refuse to start rather than allow everything."""
    allowlist: list[str] | None
    for allowlist in (None, []):
        with pytest.raises(ValueError, match="without a command allowlist"):
            GenesisGuardDaemon(
                guard_sovereign_id="guard-a",
                signing_key=_sk(),
                decision_store={},
                agent_public_keys={},
                command_allowlist=allowlist,
            )


def test_allowlist_matches_full_command_not_just_program() -> None:
    """F-01 gap 2: allowing 'python --version' must not allow 'python -c ...'."""
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    req = _request(
        agent_sk,
        command=["python", "-c", "import os; os.system('id')"],
        decision_id=decision.decision_id,
        token=_token(op_sk),
    )
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=["python --version"],
        at_time=_NOW,
    )
    assert not ok
    assert reason == "command_not_in_allowlist"


def test_prefix_rule_allows_variable_tail() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    req = _request(
        agent_sk,
        command=["python", "/opt/report.py", "--date", "2026-08-17"],
        decision_id=decision.decision_id,
        token=_token(op_sk),
    )
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=["python /opt/report.py ..."],
        at_time=_NOW,
    )
    assert ok, reason


def test_prefix_rule_still_rejects_different_program_or_script() -> None:
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    for command in (
        ["python", "/opt/other.py"],            # different script
        ["python"],                             # shorter than the fixed part
        ["node", "/opt/report.py", "--date"],   # different program
    ):
        req = _request(agent_sk, command=command, decision_id=decision.decision_id, token=_token(op_sk))
        ok, reason = validate_mediation_request(
            req, decision, [_pub_b64(agent_sk)],
            operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
            command_allowlist=["python /opt/report.py ..."],
            at_time=_NOW,
        )
        assert not ok, command
        assert reason == "command_not_in_allowlist"


def test_daemon_rejects_single_token_prefix_rule() -> None:
    """A prefix rule must not be allowed to degrade into first-word matching."""
    with pytest.raises(ValueError, match="fewer than two"):
        GenesisGuardDaemon(
            guard_sovereign_id="guard-a",
            signing_key=_sk(),
            decision_store={},
            agent_public_keys={},
            command_allowlist=["python ..."],
        )


def test_unsigned_decision_rejected() -> None:
    """F-01 gap 3: an unsigned BoundaryDecision must not authorise anything."""
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk).model_copy(update={"signature": None})
    req = _request(agent_sk, decision_id=decision.decision_id, token=_token(op_sk))
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=_ALLOWLIST,
        at_time=_NOW,
    )
    assert not ok
    assert reason == "invalid_decision_signature"


def test_decision_signed_by_unknown_key_rejected() -> None:
    """F-01 gap 3: a decision signed by anyone but the known operator is refused."""
    agent_sk = _sk()
    op_sk = _sk()
    impostor_sk = _sk()
    decision = _decision(impostor_sk)
    req = _request(agent_sk, decision_id=decision.decision_id, token=_token(op_sk))
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=_ALLOWLIST,
        at_time=_NOW,
    )
    assert not ok
    assert reason == "invalid_decision_signature"

    # No operator keys supplied at all is also a denial, not a skipped check.
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        operator_public_keys=None,
        command_allowlist=_ALLOWLIST,
        at_time=_NOW,
    )
    assert not ok
    assert reason == "invalid_decision_signature"


def test_daemon_rejects_decision_from_unknown_operator() -> None:
    """F-01 gap 3 at the daemon layer: keys are looked up by the claimed operator."""
    guard_sk = _sk()
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)

    daemon = GenesisGuardDaemon(
        guard_sovereign_id="guard-a",
        signing_key=guard_sk,
        decision_store={decision.decision_id: decision},
        agent_public_keys={"agent-a": [_pub_b64(agent_sk)]},
        operator_public_keys={"someone-else": [_pub_b64(op_sk)]},
        command_allowlist=["python --version"],
    )
    req = _request(agent_sk, command=["python", "--version"],
                   decision_id=decision.decision_id, token=_token(op_sk))
    result = daemon.handle_request(req)
    assert isinstance(result, MediationRejection)
    assert result.reason == "invalid_decision_signature"


# ---------------------------------------------------------------------------
# create_mediated_execution_receipt
# ---------------------------------------------------------------------------


def test_receipt_is_signed() -> None:
    guard_sk = _sk()
    agent_sk = _sk()
    op_sk = _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, decision_id=decision.decision_id, token=_token(op_sk))
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
    req = _request(agent_sk, capability="run-python", decision_id=decision.decision_id, token=_token(op_sk))
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
    op_sk = _sk()
    daemon = GenesisGuardDaemon(
        guard_sovereign_id="guard-a",
        signing_key=guard_sk,
        decision_store={},  # empty
        agent_public_keys={"agent-a": [_pub_b64(agent_sk)]},
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=_ALLOWLIST,
    )
    req = _request(agent_sk, token=_token(op_sk))
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
        operator_public_keys={"operator-a": [_pub_b64(op_sk)]},
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=["python --version"],
    )
    req = _request(agent_sk, command=["python", "--version"],
                   decision_id=decision.decision_id, token=_token(op_sk))
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
        operator_public_keys={"operator-a": [_pub_b64(op_sk)]},
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=["node --version"],
    )
    req = _request(agent_sk, command=["python", "--version"],
                   decision_id=decision.decision_id, token=_token(op_sk))
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
        operator_public_keys={"operator-a": [_pub_b64(op_sk)]},
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=["python --version"],
        host="127.0.0.1",
        port=0,
    )
    daemon.start()
    time.sleep(0.1)
    try:
        req = _request(agent_sk, command=["python", "--version"],
                       decision_id=decision.decision_id, token=_token(op_sk))
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
    req = _request(agent_sk, decision_id=decision.decision_id, token=_token(op_sk))
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
    req = _request(agent_sk, decision_id=decision.decision_id, token=_token(op_sk))
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


# ---------------------------------------------------------------------------
# F-01 gap 4 regression — the decision is now bound to the requesting agent.
#
# Gaps 1-3 (fail-closed allowlist, full-command matching, decision signature)
# shipped earlier and are covered above. These cover the fourth: an approval
# issued for one agent must not be usable by another.
# ---------------------------------------------------------------------------


def _mallory_request(mallory_sk, decision_id, token=None):
    """A request from an agent that is NOT the bearer of the operator's token."""
    req = ExecutionMediationRequest(
        agent_sovereign_id="mallory",
        requested_capability="run-python",
        decision_id=decision_id,
        invocation_token=token,
        subprocess_command=["python", "--version"],
        allowed_env_vars=[],
        requested_at=_NOW,
    )
    return req.model_copy(update={"signature": sign_model(req, mallory_sk, "mallory")})


def _validate(req, decision, agent_sk, op_sk, agent_id="agent-a", **kw):
    return validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=_ALLOWLIST,
        at_time=_NOW, **kw,
    )


def test_request_without_a_token_is_refused() -> None:
    """F-01 gap 4: the token is required, not optional."""
    agent_sk, op_sk = _sk(), _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, decision_id=decision.decision_id)  # no token

    ok, reason = _validate(req, decision, agent_sk, op_sk)

    assert not ok
    assert reason == "missing_invocation_token"


def test_agent_cannot_use_another_agents_decision() -> None:
    """F-01 gap 4, the headline case.

    alice's decision plus alice's token, presented by mallory. Before this fix
    the decision alone was enough and mallory succeeded.
    """
    agent_sk, op_sk, mallory_sk = _sk(), _sk(), _sk()
    decision = _decision(op_sk)
    alices_token = _token(op_sk)                      # bearer = "agent-a"

    req = _mallory_request(mallory_sk, decision.decision_id, token=alices_token)

    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(mallory_sk)],
        operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=_ALLOWLIST,
        at_time=_NOW,
    )

    assert not ok
    assert reason == "token_bearer_mismatch"


def test_token_from_an_unknown_issuer_is_refused() -> None:
    """A token the guard cannot attribute to a known issuer grants nothing."""
    agent_sk, op_sk, impostor_sk = _sk(), _sk(), _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, decision_id=decision.decision_id,
                   token=_token(impostor_sk))

    # The guard holds no key for this token's issuer at all.
    ok, reason = validate_mediation_request(
        req, decision, [_pub_b64(agent_sk)],
        operator_public_keys=[_pub_b64(op_sk)],
        token_issuer_public_keys={"someone-else": [_pub_b64(op_sk)]},
        command_allowlist=_ALLOWLIST, at_time=_NOW,
    )
    assert not ok
    assert reason == "unknown_token_issuer"


def test_token_signed_by_the_wrong_key_is_refused() -> None:
    """A forged token does not become valid by naming a known issuer."""
    agent_sk, op_sk, impostor_sk = _sk(), _sk(), _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, decision_id=decision.decision_id,
                   token=_token(impostor_sk))   # claims issuer "operator-a"

    ok, reason = _validate(req, decision, agent_sk, op_sk)

    assert not ok
    assert reason == "invalid_token_signature"


def test_token_and_decision_must_share_an_agreement() -> None:
    """A valid token cannot be paired with an unrelated valid decision."""
    agent_sk, op_sk = _sk(), _sk()
    decision = _decision(op_sk)
    other = _token(op_sk).model_copy(update={"agreement_id": "a-different-agreement"})
    resigned = other.model_copy(
        update={"signature": sign_model(other, op_sk, "operator-a")}
    )
    req = _request(agent_sk, decision_id=decision.decision_id, token=resigned)

    ok, reason = _validate(req, decision, agent_sk, op_sk)

    assert not ok
    assert reason == "token_agreement_mismatch"


def test_token_id_must_match_the_carried_token() -> None:
    agent_sk, op_sk = _sk(), _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, decision_id=decision.decision_id,
                   token_id="some-other-id", token=_token(op_sk))

    ok, reason = _validate(req, decision, agent_sk, op_sk)

    assert not ok
    assert reason == "token_id_mismatch"


def test_budget_is_enforced_across_requests() -> None:
    """max_invocations is counted, not silently ignored."""
    guard_sk, agent_sk, op_sk = _sk(), _sk(), _sk()
    decision = _decision(op_sk)
    token = _token(op_sk, max_invocations=2)

    daemon = GenesisGuardDaemon(
        guard_sovereign_id="guard-a", signing_key=guard_sk,
        decision_store={decision.decision_id: decision},
        agent_public_keys={"agent-a": [_pub_b64(agent_sk)]},
        operator_public_keys={"operator-a": [_pub_b64(op_sk)]},
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=["python --version"],
    )

    def once():
        return daemon.handle_request(
            _request(agent_sk, command=["python", "--version"],
                     decision_id=decision.decision_id, token=token)
        )

    assert isinstance(once(), MediatedExecutionReceipt)   # 1
    assert isinstance(once(), MediatedExecutionReceipt)   # 2
    third = once()                                        # 3 -> over budget
    assert isinstance(third, MediationRejection)
    assert third.reason == "token_budget_exhausted"


def test_genuine_agent_with_its_own_token_still_works() -> None:
    """Negative control: the fix must not break legitimate mediation."""
    guard_sk, agent_sk, op_sk = _sk(), _sk(), _sk()
    decision = _decision(op_sk)

    daemon = GenesisGuardDaemon(
        guard_sovereign_id="guard-a", signing_key=guard_sk,
        decision_store={decision.decision_id: decision},
        agent_public_keys={"agent-a": [_pub_b64(agent_sk)]},
        operator_public_keys={"operator-a": [_pub_b64(op_sk)]},
        token_issuer_public_keys=_issuer_keys(op_sk),
        command_allowlist=["python --version"],
    )
    result = daemon.handle_request(
        _request(agent_sk, command=["python", "--version"],
                 decision_id=decision.decision_id, token=_token(op_sk))
    )

    assert isinstance(result, MediatedExecutionReceipt)
    assert result.subprocess_exit_code == 0
