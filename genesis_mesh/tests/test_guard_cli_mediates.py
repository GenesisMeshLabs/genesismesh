"""The guard started from the CLI can authorize requests (v1.0.2).

Before 1.0.2 `trust guard start` built the daemon with no agent keys, no
operator keys and an empty decision store, so it rejected every request.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from click.testing import CliRunner

from genesis_mesh.cli.decision_ops import trust
from genesis_mesh.cli.mediation_ops import _parse_issuer_keys
from genesis_mesh.guard.daemon import GenesisGuardDaemon
from genesis_mesh.models.mediation import MediatedExecutionReceipt, MediationRejection

from .test_process_level_mediation import _PY, _PY_VERSION, _decision, _pub_b64, _request, _sk, _token


def _daemon(tmp_path, *, agent_sk, op_sk, decision_dir=None):
    return GenesisGuardDaemon(
        guard_sovereign_id="guard-a",
        signing_key=_sk(),
        decision_store={},
        agent_public_keys={"agent-a": [_pub_b64(agent_sk)]},
        operator_public_keys={"operator-a": [_pub_b64(op_sk)]},
        token_issuer_public_keys={"operator-a": [_pub_b64(op_sk)]},
        command_allowlist=[_PY_VERSION],
        decision_dir=decision_dir,
    )


def test_a_decision_dropped_in_the_decision_dir_authorizes(tmp_path):
    agent_sk, op_sk = _sk(), _sk()
    decision = _decision(op_sk)
    (tmp_path / f"{decision.decision_id}.json").write_text(decision.model_dump_json(), encoding="utf-8")
    daemon = _daemon(tmp_path, agent_sk=agent_sk, op_sk=op_sk, decision_dir=tmp_path)
    result = daemon.handle_request(
        _request(agent_sk, decision_id=decision.decision_id, command=[_PY, "--version"], token=_token(op_sk)))
    assert isinstance(result, MediatedExecutionReceipt), result


def test_a_decision_under_any_file_name_is_found(tmp_path):
    agent_sk, op_sk = _sk(), _sk()
    decision = _decision(op_sk)
    (tmp_path / "decision.json").write_text(decision.model_dump_json(), encoding="utf-8")
    daemon = _daemon(tmp_path, agent_sk=agent_sk, op_sk=op_sk, decision_dir=tmp_path)
    result = daemon.handle_request(
        _request(agent_sk, decision_id=decision.decision_id, command=[_PY, "--version"], token=_token(op_sk)))
    assert isinstance(result, MediatedExecutionReceipt), result


def test_a_decision_id_is_never_a_path(tmp_path):
    agent_sk, op_sk = _sk(), _sk()
    daemon = _daemon(tmp_path, agent_sk=agent_sk, op_sk=op_sk, decision_dir=tmp_path)
    assert daemon._load_decision("../../etc/passwd") is None
    assert daemon._load_decision("") is None


def test_a_forged_decision_in_the_dir_is_still_rejected(tmp_path):
    agent_sk, op_sk, forger = _sk(), _sk(), _sk()
    decision = _decision(forger)  # signed by a key the guard does not trust
    (tmp_path / f"{decision.decision_id}.json").write_text(decision.model_dump_json(), encoding="utf-8")
    daemon = _daemon(tmp_path, agent_sk=agent_sk, op_sk=op_sk, decision_dir=tmp_path)
    result = daemon.handle_request(
        _request(agent_sk, decision_id=decision.decision_id, command=[_PY, "--version"], token=_token(op_sk)))
    assert isinstance(result, MediationRejection)
    assert result.reason == "invalid_decision_signature"


def test_key_options_take_a_key_file(tmp_path):
    sk = _sk()
    path = tmp_path / "agent.pub"
    path.write_text(f"# Ed25519 Public Key\n# Key ID: agent-a\n{_pub_b64(sk)}\n", encoding="utf-8")
    assert _parse_issuer_keys((f"agent-a={path}",), option="--agent-key") == {"agent-a": [_pub_b64(sk)]}


def test_guard_verify_takes_a_key_file(tmp_path):
    guard_sk, agent_sk, op_sk = _sk(), _sk(), _sk()
    decision = _decision(op_sk)
    req = _request(agent_sk, decision_id=decision.decision_id, token=_token(op_sk))
    from genesis_mesh.trust.mediation import create_mediated_execution_receipt
    receipt = create_mediated_execution_receipt(req, subprocess_pid=1, guard_sovereign_id="guard-a",
                                                signing_key=guard_sk, exit_code=0)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(receipt.model_dump_json(), encoding="utf-8")
    key_path = tmp_path / "guard.pub"
    key_path.write_text(f"# Ed25519 Public Key\n{_pub_b64(guard_sk)}\n", encoding="utf-8")
    result = CliRunner().invoke(trust, ["guard", "verify", "--receipt", str(receipt_path), "--guard-key",
                                        str(key_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["valid"] is True


def test_guard_verify_reports_a_rejection_without_a_trace(tmp_path):
    """A refused request's output file holds a rejection; verify says so (v1.0.2)."""
    rejection = MediationRejection(request_id="req-1", agent_sovereign_id="agent-a",
                                   rejected_at=datetime.now(timezone.utc), reason="invalid_request_signature")
    path = tmp_path / "receipt.json"
    path.write_text(rejection.model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(trust, ["guard", "verify", "--receipt", str(path), "--guard-key",
                                        _pub_b64(_sk()), "--format", "json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output) == {"valid": False, "reason": "not_a_receipt"}
    assert not isinstance(result.exception, ValueError)
