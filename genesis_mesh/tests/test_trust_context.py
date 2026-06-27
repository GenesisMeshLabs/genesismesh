"""Tests for Relationship Context — BoundaryEngine and BoundaryDecision (v0.28).

Covers:
- Valid evaluation (all gates pass)
- CapabilityGate failure
- ValidityWindowGate failures (before/after window)
- FreshnessGate failure
- Custom gate extension
- Short-circuit on first failure (later gates not evaluated)
- verify_boundary_decision: valid, expired, invalid signature, missing sig
- Authorization status mapping (denial_reason)
- CLI: trust context request, evaluate, verify
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from genesis_mesh.cli.context_ops import context
from genesis_mesh.crypto import generate_keypair
from genesis_mesh.models.agreement import AgreementRecord, AgreementTerms
from genesis_mesh.models.context import BoundaryDecision, ContextRecord, GateResult
from genesis_mesh.trust.context import (
    BoundaryDecisionVerificationResult,
    BoundaryEngine,
    capability_gate,
    freshness_gate,
    validity_window_gate,
    verify_boundary_decision,
)
from genesis_mesh.trust.agreement import build_offer, build_counter, accept_counter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _active_graph(src: str, dst: str) -> dict:
    now = _now()
    return {
        "sovereigns": [{"sovereign_id": src}, {"sovereign_id": dst}],
        "recognition_edges": [
            {
                "from": src, "to": dst,
                "treaty_id": f"t-{src}-{dst}", "status": "active",
                "lifecycle_state": "active", "expiry_risk": "low",
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
            },
            {
                "from": dst, "to": src,
                "treaty_id": f"t-{dst}-{src}", "status": "active",
                "lifecycle_state": "active", "expiry_risk": "low",
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
            },
        ],
        "active_treaties": [
            {
                "treaty_id": f"t-{src}-{dst}",
                "issuer_sovereign_id": src, "subject_sovereign_id": dst,
                "scope": {"allowed_roles": ["transactions.read", "balances.read"]},
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
                "signatures": [],
            },
            {
                "treaty_id": f"t-{dst}-{src}",
                "issuer_sovereign_id": dst, "subject_sovereign_id": src,
                "scope": {"allowed_roles": ["transactions.read"]},
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
                "signatures": [],
            },
        ],
        "revoked_trust_material": [],
    }


def _terms(
    caps: list[str] | None = None,
    days: int = 30,
    freshness: int = 0,
) -> AgreementTerms:
    now = _now()
    return AgreementTerms(
        capabilities=caps or ["transactions.read", "balances.read"],
        scope={},
        valid_from=now,
        valid_until=now + timedelta(days=days),
        freshness_commitment=freshness,
    )


def _make_agreement(
    caps: list[str] | None = None,
    days: int = 30,
    freshness: int = 0,
) -> tuple[AgreementRecord, object, str]:
    """Return (agreement, operator_sk, operator_pub_b64)."""
    kp1 = generate_keypair()
    kp2 = generate_keypair()
    graph = _active_graph("aspayr", "bank-a")
    terms = _terms(caps, days, freshness)
    now = _now()
    offer = build_offer(
        "aspayr", "bank-a", terms, graph, kp1.private_key,
        issued_by="aspayr-key", expires_at=now + timedelta(hours=1), now=now,
    )
    counter = build_counter(offer, terms, graph, kp2.private_key, issued_by="bank-key", now=now)
    agreement = accept_counter(counter, offer, kp1.private_key, issued_by="aspayr-key", now=now)
    # Return kp1 as "operator" for signing decisions
    return agreement, kp1.private_key, kp1.public_key_b64


def _make_context(
    agreement: AgreementRecord,
    capability: str = "transactions.read",
    freshness_seq: int = 0,
    requested_at: datetime | None = None,
) -> ContextRecord:
    return ContextRecord(
        agreement_id=agreement.agreement_id,
        requester_sovereign_id=agreement.offerer_sovereign_id,
        provider_sovereign_id=agreement.responder_sovereign_id,
        requested_capability=capability,
        context_freshness_seq=freshness_seq,
        requested_at=requested_at or _now(),
    )


# ---------------------------------------------------------------------------
# BoundaryEngine — valid evaluation
# ---------------------------------------------------------------------------


class TestValidEvaluation:
    def test_all_gates_pass(self):
        agreement, sk, pub = _make_agreement()
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement)
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")

        assert decision.authorized is True
        assert decision.denial_reason is None
        assert len(decision.gate_results) == 3
        assert all(gr.passed for gr in decision.gate_results)

    def test_decision_is_signed(self):
        agreement, sk, pub = _make_agreement()
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement)
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")
        assert decision.signature is not None

    def test_decision_valid_until_set(self):
        agreement, sk, pub = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=600)
        ctx = _make_context(agreement)
        now = _now()
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key", now=now)
        delta = decision.decision_valid_until - decision.decision_made_at
        assert abs(delta.total_seconds() - 600) < 2

    def test_operator_sovereign_id_recorded(self):
        agreement, sk, pub = _make_agreement()
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement)
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")
        assert decision.operator_sovereign_id == "bank-a"

    def test_gate_names_in_results(self):
        agreement, sk, pub = _make_agreement()
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement)
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")
        names = {gr.gate_name for gr in decision.gate_results}
        assert "capability_check" in names
        assert "validity_window" in names
        assert "freshness_check" in names


# ---------------------------------------------------------------------------
# CapabilityGate
# ---------------------------------------------------------------------------


class TestCapabilityGate:
    def test_capability_not_in_scope_denied(self):
        agreement, sk, pub = _make_agreement(caps=["transactions.read"])
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement, capability="admin.write")
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")

        assert decision.authorized is False
        cap_gate = next(gr for gr in decision.gate_results if gr.gate_name == "capability_check")
        assert cap_gate.passed is False

    def test_capability_not_in_scope_short_circuits(self):
        """Validity and freshness gates not evaluated when capability fails."""
        agreement, sk, pub = _make_agreement(caps=["transactions.read"])
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement, capability="admin.write")
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")
        # Only capability gate ran
        assert len(decision.gate_results) == 1

    def test_capability_in_scope_passes(self):
        agreement, sk, pub = _make_agreement(caps=["transactions.read"])
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement, capability="transactions.read")
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")
        cap_gate = next(gr for gr in decision.gate_results if gr.gate_name == "capability_check")
        assert cap_gate.passed is True


# ---------------------------------------------------------------------------
# ValidityWindowGate
# ---------------------------------------------------------------------------


class TestValidityWindowGate:
    def test_request_before_valid_from_denied(self):
        now = _now()
        agreement, sk, pub = _make_agreement()
        engine = BoundaryEngine("bank-a")
        # requested_at is before valid_from
        ctx = _make_context(
            agreement,
            requested_at=agreement.agreed_terms.valid_from - timedelta(hours=1),
        )
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")
        assert decision.authorized is False
        vw = next(gr for gr in decision.gate_results if gr.gate_name == "validity_window")
        assert vw.passed is False

    def test_request_after_valid_until_denied(self):
        agreement, sk, pub = _make_agreement()
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(
            agreement,
            requested_at=agreement.agreed_terms.valid_until + timedelta(hours=1),
        )
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")
        assert decision.authorized is False
        vw = next(gr for gr in decision.gate_results if gr.gate_name == "validity_window")
        assert vw.passed is False

    def test_request_within_window_passes(self):
        agreement, sk, pub = _make_agreement()
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement)  # requested_at = now, which is within window
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")
        vw = next(gr for gr in decision.gate_results if gr.gate_name == "validity_window")
        assert vw.passed is True


# ---------------------------------------------------------------------------
# FreshnessGate
# ---------------------------------------------------------------------------


class TestFreshnessGate:
    def test_insufficient_freshness_denied(self):
        agreement, sk, pub = _make_agreement(freshness=10)
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement, freshness_seq=5)  # < 10
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")
        assert decision.authorized is False
        fg = next(gr for gr in decision.gate_results if gr.gate_name == "freshness_check")
        assert fg.passed is False

    def test_exact_freshness_passes(self):
        agreement, sk, pub = _make_agreement(freshness=10)
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement, freshness_seq=10)
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")
        fg = next(gr for gr in decision.gate_results if gr.gate_name == "freshness_check")
        assert fg.passed is True

    def test_surplus_freshness_passes(self):
        agreement, sk, pub = _make_agreement(freshness=5)
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement, freshness_seq=100)
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")
        fg = next(gr for gr in decision.gate_results if gr.gate_name == "freshness_check")
        assert fg.passed is True

    def test_zero_commitment_always_passes(self):
        agreement, sk, pub = _make_agreement(freshness=0)
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement, freshness_seq=0)
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")
        assert decision.authorized is True


# ---------------------------------------------------------------------------
# Custom gate extension
# ---------------------------------------------------------------------------


class TestCustomGate:
    def test_custom_gate_appended_and_evaluated(self):
        agreement, sk, pub = _make_agreement()
        engine = BoundaryEngine("bank-a")

        def always_pass_gate(ctx: ContextRecord, terms: AgreementTerms) -> GateResult:
            return GateResult(gate_name="custom_always_pass", passed=True, detail="custom gate")

        engine.add_gate(always_pass_gate)
        ctx = _make_context(agreement)
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")
        assert decision.authorized is True
        names = [gr.gate_name for gr in decision.gate_results]
        assert "custom_always_pass" in names

    def test_custom_gate_failure_denies(self):
        agreement, sk, pub = _make_agreement()
        engine = BoundaryEngine("bank-a")

        def always_fail_gate(ctx: ContextRecord, terms: AgreementTerms) -> GateResult:
            return GateResult(gate_name="custom_blocker", passed=False, detail="blocked by policy")

        engine.add_gate(always_fail_gate)
        ctx = _make_context(agreement)
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")
        assert decision.authorized is False
        blocker = next(gr for gr in decision.gate_results if gr.gate_name == "custom_blocker")
        assert blocker.passed is False

    def test_custom_gate_not_reached_after_earlier_failure(self):
        """Custom gate at end not evaluated when capability gate fails first."""
        agreement, sk, pub = _make_agreement(caps=["transactions.read"])
        engine = BoundaryEngine("bank-a")
        reached = []

        def probe_gate(ctx: ContextRecord, terms: AgreementTerms) -> GateResult:
            reached.append(True)
            return GateResult(gate_name="probe", passed=True, detail="probe")

        engine.add_gate(probe_gate)
        ctx = _make_context(agreement, capability="admin.write")
        engine.evaluate(ctx, agreement, sk, issued_by="op-key")
        assert len(reached) == 0


# ---------------------------------------------------------------------------
# verify_boundary_decision
# ---------------------------------------------------------------------------


class TestVerifyBoundaryDecision:
    def test_valid_decision_verifies(self):
        agreement, sk, pub = _make_agreement()
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement)
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")

        result = verify_boundary_decision(decision, [pub])
        assert result.accepted is True
        assert result.reason == "authorized"

    def test_expired_decision_rejected(self):
        agreement, sk, pub = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=1)
        ctx = _make_context(agreement)
        past = _now() - timedelta(hours=1)
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key", now=past)

        result = verify_boundary_decision(decision, [pub])
        assert result.accepted is False
        assert result.reason == "decision_expired"

    def test_wrong_key_rejected(self):
        agreement, sk, pub = _make_agreement()
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement)
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")

        wrong_kp = generate_keypair()
        result = verify_boundary_decision(decision, [wrong_kp.public_key_b64])
        assert result.accepted is False
        assert result.reason == "invalid_signature"

    def test_missing_signature_rejected(self):
        agreement, sk, pub = _make_agreement()
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement)
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")
        unsigned = decision.model_copy(update={"signature": None})

        result = verify_boundary_decision(unsigned, [pub])
        assert result.accepted is False
        assert result.reason == "missing_signature"

    def test_denied_decision_returns_unauthorized_reason(self):
        agreement, sk, pub = _make_agreement(caps=["transactions.read"])
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement, capability="admin.write")
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")

        result = verify_boundary_decision(decision, [pub])
        assert result.accepted is True  # signature valid
        assert result.authorized is False
        assert result.reason == "unauthorized_capability_out_of_scope"

    def test_json_round_trip_preserves_verifiability(self):
        agreement, sk, pub = _make_agreement()
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement)
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key")

        recovered = BoundaryDecision.model_validate_json(decision.model_dump_json())
        result = verify_boundary_decision(recovered, [pub])
        assert result.accepted is True

    def test_future_expiry_check(self):
        """Verify at a future time after decision_valid_until fails."""
        agreement, sk, pub = _make_agreement()
        engine = BoundaryEngine("bank-a", decision_valid_seconds=60)
        past = _now() - timedelta(hours=2)
        ctx = _make_context(agreement)
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key", now=past)

        result = verify_boundary_decision(decision, [pub], now=_now())
        assert result.accepted is False
        assert result.reason == "decision_expired"


# ---------------------------------------------------------------------------
# CLI: trust context request
# ---------------------------------------------------------------------------


class TestCliContextRequest:
    def test_creates_context_file(self, tmp_path: Path):
        agreement, sk, pub = _make_agreement()
        agreement_file = tmp_path / "agreement.json"
        agreement_file.write_text(agreement.model_dump_json(), encoding="utf-8")
        output_file = tmp_path / "context.json"

        runner = CliRunner()
        result = runner.invoke(context, [
            "request",
            "--agreement", str(agreement_file),
            "--capability", "transactions.read",
            "--requester", "aspayr",
            "--provider", "bank-a",
            "--freshness-seq", "5",
            "--output", str(output_file),
        ])
        assert result.exit_code == 0, result.output
        assert output_file.exists()
        rec = ContextRecord.model_validate_json(output_file.read_text())
        assert rec.requested_capability == "transactions.read"
        assert rec.context_freshness_seq == 5

    def test_output_shows_context_id(self, tmp_path: Path):
        agreement, sk, pub = _make_agreement()
        agreement_file = tmp_path / "agreement.json"
        agreement_file.write_text(agreement.model_dump_json(), encoding="utf-8")
        output_file = tmp_path / "context.json"

        runner = CliRunner()
        result = runner.invoke(context, [
            "request",
            "--agreement", str(agreement_file),
            "--capability", "transactions.read",
            "--requester", "aspayr",
            "--provider", "bank-a",
            "--output", str(output_file),
        ])
        assert "Context" in result.output


# ---------------------------------------------------------------------------
# CLI: trust context evaluate
# ---------------------------------------------------------------------------


class TestCliContextEvaluate:
    def _write_files(self, tmp_path: Path, caps=None, freshness=0):
        from genesis_mesh.crypto import generate_keypair as gkp
        agreement, sk, pub = _make_agreement(caps=caps, freshness=freshness)
        agreement_file = tmp_path / "agreement.json"
        agreement_file.write_text(agreement.model_dump_json(), encoding="utf-8")
        ctx = _make_context(agreement)
        context_file = tmp_path / "context.json"
        context_file.write_text(ctx.model_dump_json(), encoding="utf-8")
        key_file = tmp_path / "op.key"
        key_file.write_text(gkp().private_key_b64 + "\n", encoding="utf-8")
        # Use the agreement's own key for signing (any key works for the operator)
        op_kp = gkp()
        key_file.write_text(op_kp.private_key_b64 + "\n", encoding="utf-8")
        return agreement_file, context_file, key_file, op_kp.public_key_b64

    def test_authorized_exits_zero(self, tmp_path: Path):
        agreement, sk, pub = _make_agreement()
        agreement_file = tmp_path / "agreement.json"
        agreement_file.write_text(agreement.model_dump_json(), encoding="utf-8")
        ctx = _make_context(agreement)
        context_file = tmp_path / "context.json"
        context_file.write_text(ctx.model_dump_json(), encoding="utf-8")
        from genesis_mesh.crypto import generate_keypair as gkp
        op_kp = gkp()
        key_file = tmp_path / "op.key"
        key_file.write_text(op_kp.private_key_b64 + "\n", encoding="utf-8")
        output_file = tmp_path / "decision.json"

        runner = CliRunner()
        result = runner.invoke(context, [
            "evaluate",
            "--context", str(context_file),
            "--agreement", str(agreement_file),
            "--operator", "bank-a",
            "--signing-key", str(key_file),
            "--output", str(output_file),
        ])
        assert result.exit_code == 0, result.output
        assert output_file.exists()
        assert "AUTHORIZED" in result.output

    def test_denied_exits_one(self, tmp_path: Path):
        agreement, sk, pub = _make_agreement(caps=["transactions.read"])
        agreement_file = tmp_path / "agreement.json"
        agreement_file.write_text(agreement.model_dump_json(), encoding="utf-8")
        ctx = _make_context(agreement, capability="admin.write")
        context_file = tmp_path / "context.json"
        context_file.write_text(ctx.model_dump_json(), encoding="utf-8")
        from genesis_mesh.crypto import generate_keypair as gkp
        op_kp = gkp()
        key_file = tmp_path / "op.key"
        key_file.write_text(op_kp.private_key_b64 + "\n", encoding="utf-8")
        output_file = tmp_path / "decision.json"

        runner = CliRunner()
        result = runner.invoke(context, [
            "evaluate",
            "--context", str(context_file),
            "--agreement", str(agreement_file),
            "--operator", "bank-a",
            "--signing-key", str(key_file),
            "--output", str(output_file),
        ])
        assert result.exit_code == 1
        assert "DENIED" in result.output


# ---------------------------------------------------------------------------
# CLI: trust context verify
# ---------------------------------------------------------------------------


class TestCliContextVerify:
    def test_valid_decision_exits_zero(self, tmp_path: Path):
        from genesis_mesh.crypto import generate_keypair as gkp
        agreement, sk, pub = _make_agreement()
        op_kp = gkp()
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement)
        decision = engine.evaluate(ctx, agreement, op_kp.private_key, issued_by="op-key")

        decision_file = tmp_path / "decision.json"
        decision_file.write_text(decision.model_dump_json(), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(context, [
            "verify",
            "--decision", str(decision_file),
            "--operator-public-key", op_kp.public_key_b64,
        ])
        assert result.exit_code == 0, result.output
        assert "OK" in result.output

    def test_wrong_key_exits_one(self, tmp_path: Path):
        from genesis_mesh.crypto import generate_keypair as gkp
        agreement, sk, pub = _make_agreement()
        op_kp = gkp()
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement)
        decision = engine.evaluate(ctx, agreement, op_kp.private_key, issued_by="op-key")

        decision_file = tmp_path / "decision.json"
        decision_file.write_text(decision.model_dump_json(), encoding="utf-8")

        wrong_kp = gkp()
        runner = CliRunner()
        result = runner.invoke(context, [
            "verify",
            "--decision", str(decision_file),
            "--operator-public-key", wrong_kp.public_key_b64,
        ])
        assert result.exit_code == 1
        assert "FAIL" in result.output

    def test_json_output_format(self, tmp_path: Path):
        from genesis_mesh.crypto import generate_keypair as gkp
        agreement, sk, pub = _make_agreement()
        op_kp = gkp()
        engine = BoundaryEngine("bank-a")
        ctx = _make_context(agreement)
        decision = engine.evaluate(ctx, agreement, op_kp.private_key, issued_by="op-key")

        decision_file = tmp_path / "decision.json"
        decision_file.write_text(decision.model_dump_json(), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(context, [
            "verify",
            "--decision", str(decision_file),
            "--operator-public-key", op_kp.public_key_b64,
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["accepted"] is True
        assert data["reason"] == "authorized"
        assert "decision_id" in data
