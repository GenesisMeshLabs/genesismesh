"""Tests for Justification Proofs + Gate Trace Artifacts (v0.33).

Covers:
- BoundaryEngine.evaluate_with_proof() returns (decision, JustificationProof)
- Trace matches gate evaluation order including short-circuit
- Authorized decision: all gates traced, short_circuited_at=None
- Denied decision: first failed gate in short_circuited_at
- evaluate() (no-proof path) still works unchanged
- verify_justification_proof(): all 6 reason codes
- sign_justification_proof(): mismatch validation raises
- Proof digest is deterministic
- CLI trust justify sign / verify
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
from genesis_mesh.crypto import generate_keypair
from genesis_mesh.models.agreement import AgreementRecord, AgreementTerms
from genesis_mesh.models.context import BoundaryDecision, ContextRecord
from genesis_mesh.models.justification import GateTrace, GateTraceEntry, JustificationProof
from genesis_mesh.trust.agreement import accept_counter, build_counter, build_offer
from genesis_mesh.trust.context import BoundaryEngine
from genesis_mesh.trust.justification import (
    JustificationProofVerificationResult,
    sign_justification_proof,
    verify_justification_proof,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


def _pub_b64(sk: nacl.signing.SigningKey) -> str:
    return base64.b64encode(bytes(sk.verify_key)).decode()


def _active_graph() -> dict:
    return {
        "sovereigns": [{"sovereign_id": "bank-a"}, {"sovereign_id": "bank-b"}],
        "recognition_edges": [
            {
                "from": "bank-a", "to": "bank-b",
                "treaty_id": "t-a-b", "status": "active",
                "lifecycle_state": "active", "expiry_risk": "low",
                "valid_from": (_NOW - timedelta(days=1)).isoformat(),
                "expires_at": (_NOW + timedelta(days=180)).isoformat(),
            },
        ],
        "active_treaties": [
            {
                "treaty_id": "t-a-b",
                "issuer_sovereign_id": "bank-a", "subject_sovereign_id": "bank-b",
                "scope": {"allowed_roles": ["transactions.read", "audit.read"]},
                "valid_from": (_NOW - timedelta(days=1)).isoformat(),
                "expires_at": (_NOW + timedelta(days=180)).isoformat(),
                "signatures": [],
            },
        ],
    }


def _make_agreement(
    caps: list[str] | None = None,
    freshness_commitment: int = 5,
) -> tuple[AgreementRecord, nacl.signing.SigningKey]:
    kp1 = generate_keypair()
    kp2 = generate_keypair()
    terms = AgreementTerms(
        capabilities=caps or ["transactions.read", "audit.read"],
        valid_from=_NOW - timedelta(hours=1),
        valid_until=_NOW + timedelta(hours=24),
        freshness_commitment=freshness_commitment,
    )
    graph = _active_graph()
    offer = build_offer(
        "bank-a", "bank-b", terms, graph, kp1.private_key,
        issued_by="bank-a-key", expires_at=_NOW + timedelta(hours=2), now=_NOW,
    )
    counter = build_counter(offer, terms, graph, kp2.private_key, issued_by="bank-b-key", now=_NOW)
    agreement = accept_counter(counter, offer, kp1.private_key, issued_by="bank-a-key", now=_NOW)
    return agreement, kp1.private_key


def _make_context(
    agreement: AgreementRecord,
    capability: str = "transactions.read",
    freshness_seq: int = 10,
    requested_at: datetime | None = None,
) -> ContextRecord:
    return ContextRecord(
        agreement_id=agreement.agreement_id,
        requester_sovereign_id="bank-b",
        provider_sovereign_id="bank-a",
        requested_capability=capability,
        context_freshness_seq=freshness_seq,
        requested_at=requested_at or _NOW,
    )


def _write_key(sk: nacl.signing.SigningKey) -> str:
    fd, path = tempfile.mkstemp(suffix=".key")
    os.close(fd)
    Path(path).write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# evaluate_with_proof — authorized path
# ---------------------------------------------------------------------------


class TestEvaluateWithProofAuthorized:
    def test_returns_decision_and_proof(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        result = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        decision, proof = result
        assert isinstance(decision, BoundaryDecision)
        assert isinstance(proof, JustificationProof)

    def test_decision_authorized(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        decision, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        assert decision.authorized is True

    def test_proof_decision_id_matches(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        decision, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        assert proof.decision_id == decision.decision_id

    def test_proof_has_signature(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        _, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        assert proof.signature is not None

    def test_all_gates_in_trace(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        decision, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        gate_names = [e.gate_name for e in proof.trace.entries]
        assert "capability_check" in gate_names
        assert "validity_window" in gate_names
        assert "freshness_check" in gate_names

    def test_short_circuited_at_none_when_all_pass(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        _, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        assert proof.trace.short_circuited_at is None

    def test_trace_entry_count_matches_decision_gate_results(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        decision, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        assert len(proof.trace.entries) == len(decision.gate_results)

    def test_trace_final_authorized_matches(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        decision, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        assert proof.trace.final_authorized == decision.authorized

    def test_gate_inputs_captured_capability(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        _, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        cap_entry = next(e for e in proof.trace.entries if e.gate_name == "capability_check")
        assert cap_entry.inputs["requested_capability"] == "transactions.read"
        assert "transactions.read" in cap_entry.inputs["capabilities"]

    def test_gate_types_set(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        _, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        types = {e.gate_type for e in proof.trace.entries}
        assert "CapabilityGate" in types
        assert "ValidityWindowGate" in types
        assert "FreshnessGate" in types


# ---------------------------------------------------------------------------
# evaluate_with_proof — denied / short-circuit
# ---------------------------------------------------------------------------


class TestEvaluateWithProofDenied:
    def test_capability_failure_short_circuits(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement, capability="admin.delete")
        decision, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        assert decision.authorized is False
        assert proof.trace.short_circuited_at == "capability_check"
        assert len(proof.trace.entries) == 1

    def test_freshness_failure_short_circuits_after_two_gates(self) -> None:
        agreement, sk = _make_agreement(freshness_commitment=20)
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement, freshness_seq=5)
        decision, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        assert decision.authorized is False
        assert proof.trace.short_circuited_at == "freshness_check"
        assert len(proof.trace.entries) == 3

    def test_denied_trace_final_authorized_false(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement, capability="unknown.cap")
        _, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        assert proof.trace.final_authorized is False


# ---------------------------------------------------------------------------
# evaluate() unchanged (no-proof path)
# ---------------------------------------------------------------------------


class TestEvaluateNoProofPathUnchanged:
    def test_evaluate_still_returns_decision_directly(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        assert isinstance(decision, BoundaryDecision)
        assert decision.authorized is True

    def test_evaluate_denial_unchanged(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement, capability="bad.cap")
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        assert decision.authorized is False


# ---------------------------------------------------------------------------
# sign_justification_proof — validation
# ---------------------------------------------------------------------------


class TestSignJustificationProof:
    def test_raises_on_decision_id_mismatch(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        decision, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op", now=_NOW)
        other_decision = decision.model_copy(update={"decision_id": "wrong-id"})
        with pytest.raises(ValueError, match="decision_id"):
            sign_justification_proof(proof.trace, other_decision, sk, issued_by="op", now=_NOW)

    def test_raises_on_authorized_mismatch(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        decision, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op", now=_NOW)
        mismatched = decision.model_copy(update={"authorized": not decision.authorized})
        with pytest.raises(ValueError, match="authorized"):
            sign_justification_proof(proof.trace, mismatched, sk, issued_by="op", now=_NOW)


# ---------------------------------------------------------------------------
# verify_justification_proof — all 6 reason codes
# ---------------------------------------------------------------------------


class TestVerifyJustificationProof:
    def _make_proof(self) -> tuple[JustificationProof, BoundaryDecision, str]:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        decision, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op", now=_NOW)
        return proof, decision, _pub_b64(sk)

    def test_valid(self) -> None:
        proof, decision, pub = self._make_proof()
        result = verify_justification_proof(proof, [pub], decision=decision)
        assert result.valid is True
        assert result.reason == "valid"

    def test_valid_no_decision(self) -> None:
        proof, _, pub = self._make_proof()
        result = verify_justification_proof(proof, [pub])
        assert result.valid is True
        assert result.reason == "valid"

    def test_missing_signature(self) -> None:
        proof, _, pub = self._make_proof()
        unsigned = proof.model_copy(update={"signature": None})
        result = verify_justification_proof(unsigned, [pub])
        assert result.valid is False
        assert result.reason == "missing_signature"

    def test_invalid_signature(self) -> None:
        proof, _, _ = self._make_proof()
        other_sk = nacl.signing.SigningKey.generate()
        result = verify_justification_proof(proof, [_pub_b64(other_sk)])
        assert result.valid is False
        assert result.reason == "invalid_signature"

    def test_decision_id_mismatch(self) -> None:
        proof, decision, pub = self._make_proof()
        wrong_decision = decision.model_copy(update={"decision_id": "wrong-id"})
        result = verify_justification_proof(proof, [pub], decision=wrong_decision)
        assert result.valid is False
        assert result.reason == "decision_id_mismatch"

    def test_trace_entry_count_mismatch(self) -> None:
        proof, decision, pub = self._make_proof()
        extra = decision.model_copy(update={
            "gate_results": list(decision.gate_results) + list(decision.gate_results)
        })
        result = verify_justification_proof(proof, [pub], decision=extra)
        assert result.valid is False
        assert result.reason == "trace_entry_count_mismatch"

    def test_short_circuit_inconsistent_authorized_but_short_circuited(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        decision, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op", now=_NOW)
        tampered_trace = proof.trace.model_copy(update={"short_circuited_at": "capability_check"})
        new_proof = sign_justification_proof(tampered_trace, decision, sk, issued_by="op", now=_NOW)
        result = verify_justification_proof(new_proof, [_pub_b64(sk)], decision=decision)
        assert result.valid is False
        assert result.reason == "short_circuit_inconsistent"

    def test_short_circuit_inconsistent_denied_but_no_short_circuit(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement, capability="bad.cap")
        decision, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op", now=_NOW)
        tampered_trace = proof.trace.model_copy(update={"short_circuited_at": None})
        new_proof = sign_justification_proof(tampered_trace, decision, sk, issued_by="op", now=_NOW)
        result = verify_justification_proof(new_proof, [_pub_b64(sk)], decision=decision)
        assert result.valid is False
        assert result.reason == "short_circuit_inconsistent"


# ---------------------------------------------------------------------------
# Digest determinism
# ---------------------------------------------------------------------------


class TestProofDigest:
    def test_digest_stable(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        _, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op", now=_NOW)
        assert proof.digest() == proof.digest()

    def test_digest_changes_on_tamper(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        _, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op", now=_NOW)
        tampered = proof.model_copy(update={"decision_id": "tampered-id"})
        assert tampered.digest() != proof.digest()


# ---------------------------------------------------------------------------
# Custom gate integration
# ---------------------------------------------------------------------------


class TestCustomGateInTrace:
    def test_custom_gate_appears_in_trace(self) -> None:
        from genesis_mesh.models.context import GateResult

        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)

        def custom_gate(context: ContextRecord, terms: AgreementTerms) -> GateResult:
            return GateResult(gate_name="custom_check", passed=True, detail="custom passed")

        from genesis_mesh.models.agreement import AgreementTerms as _AT  # noqa: F401
        engine.add_gate(custom_gate)
        _, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op", now=_NOW)
        gate_names = [e.gate_name for e in proof.trace.entries]
        assert "custom_check" in gate_names
        custom_entry = next(e for e in proof.trace.entries if e.gate_name == "custom_check")
        assert custom_entry.gate_type == "CustomGate"


# ---------------------------------------------------------------------------
# CLI: trust justify sign / verify
# ---------------------------------------------------------------------------


class TestJustifyCLI:
    def _setup(self) -> tuple[CliRunner, str, str, str, str, str]:
        runner = CliRunner()
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
        ctx = _make_context(agreement)
        decision, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op", now=_NOW)

        tmpdir = tempfile.mkdtemp()
        key_path = _write_key(sk)
        pub_b64 = _pub_b64(sk)

        decision_path = os.path.join(tmpdir, "decision.json")
        trace_path = os.path.join(tmpdir, "trace.json")
        proof_path = os.path.join(tmpdir, "proof.json")

        Path(decision_path).write_text(decision.model_dump_json(indent=2), encoding="utf-8")
        Path(trace_path).write_text(proof.trace.model_dump_json(indent=2), encoding="utf-8")

        return runner, key_path, pub_b64, decision_path, trace_path, proof_path

    def test_cli_justify_sign(self) -> None:
        runner, key_path, _, decision_path, trace_path, proof_path = self._setup()
        result = runner.invoke(trust, [
            "justify", "sign",
            "--decision", decision_path,
            "--trace", trace_path,
            "--signing-key", key_path,
            "--output", proof_path,
        ])
        assert result.exit_code == 0, result.output
        assert Path(proof_path).exists()
        data = json.loads(Path(proof_path).read_text(encoding="utf-8"))
        assert "proof_id" in data
        assert "signature" in data

    def test_cli_justify_verify_ok(self) -> None:
        runner, key_path, pub_b64, decision_path, trace_path, proof_path = self._setup()
        runner.invoke(trust, [
            "justify", "sign",
            "--decision", decision_path,
            "--trace", trace_path,
            "--signing-key", key_path,
            "--output", proof_path,
        ])
        result = runner.invoke(trust, [
            "justify", "verify",
            "--proof", proof_path,
            "--verify-key", pub_b64,
            "--decision", decision_path,
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output

    def test_cli_justify_verify_wrong_key(self) -> None:
        runner, key_path, _, decision_path, trace_path, proof_path = self._setup()
        runner.invoke(trust, [
            "justify", "sign",
            "--decision", decision_path,
            "--trace", trace_path,
            "--signing-key", key_path,
            "--output", proof_path,
        ])
        wrong_pub = _pub_b64(nacl.signing.SigningKey.generate())
        result = runner.invoke(trust, [
            "justify", "verify",
            "--proof", proof_path,
            "--verify-key", wrong_pub,
        ])
        assert result.exit_code == 1
        assert "FAIL" in result.output
        assert "invalid_signature" in result.output

    def test_cli_justify_verify_json_format(self) -> None:
        runner, key_path, pub_b64, decision_path, trace_path, proof_path = self._setup()
        runner.invoke(trust, [
            "justify", "sign",
            "--decision", decision_path,
            "--trace", trace_path,
            "--signing-key", key_path,
            "--output", proof_path,
        ])
        result = runner.invoke(trust, [
            "justify", "verify",
            "--proof", proof_path,
            "--verify-key", pub_b64,
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["valid"] is True
        assert data["reason"] == "valid"
