"""Tests for Freshness Proofs + Bounded Revocation (v0.30).

Covers:
- issue_freshness_proof: valid proof with correct fields
- verify_freshness_proof: valid, expired, sequence_insufficient, invalid_signature, missing_signature
- BoundaryEngine.evaluate with require_freshness_proof=True:
  - valid proof embedded, decision authorized
  - absent proof, decision denied
  - invalid sig proof, denied
  - expired proof, denied
  - feed_sequence < commitment, denied
- BoundaryEngine default (require_freshness_proof=False) still works without proof
- BoundaryDecision.freshness_proof included in canonical JSON
- verify_boundary_decision with embedded proof: valid, proof_invalid_signature, proof_expired
- verify_evidence_chain stale_freshness_proof detection
- JSON round-trip transport independence
- CLI: trust freshness issue, verify
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from genesis_mesh.cli.freshness_ops import freshness
from genesis_mesh.crypto import generate_keypair
from genesis_mesh.models.agreement import AgreementRecord, AgreementTerms
from genesis_mesh.models.context import BoundaryDecision, ContextRecord
from genesis_mesh.models.freshness import FreshnessProof
from genesis_mesh.models.execution import EvidenceChain, ExecutionEvidence
from genesis_mesh.trust.context import BoundaryEngine, verify_boundary_decision
from genesis_mesh.trust.execution import record_execution, verify_evidence_chain
from genesis_mesh.trust.freshness import (
    FreshnessProofVerificationResult,
    issue_freshness_proof,
    verify_freshness_proof,
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
                "scope": {"allowed_roles": ["transactions.read"]},
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


def _terms(caps=None, days=30, freshness_commitment=0) -> AgreementTerms:
    now = _now()
    return AgreementTerms(
        capabilities=caps or ["transactions.read"],
        scope={},
        valid_from=now,
        valid_until=now + timedelta(days=days),
        freshness_commitment=freshness_commitment,
    )


def _make_agreement(commitment: int = 0):
    kp1 = generate_keypair()
    kp2 = generate_keypair()
    graph = _active_graph("aspayr", "bank-a")
    terms = _terms(freshness_commitment=commitment)
    now = _now()
    offer = build_offer("aspayr", "bank-a", terms, graph, kp1.private_key,
                        issued_by="k1", expires_at=now + timedelta(hours=1), now=now)
    counter = build_counter(offer, terms, graph, kp2.private_key, issued_by="k2", now=now)
    agreement = accept_counter(counter, offer, kp1.private_key, issued_by="k1", now=now)
    return agreement


def _make_proof(feed_sovereign_id="bank-a", feed_sequence=5, valid_for=300, now=None):
    kp = generate_keypair()
    ts = now or _now()
    proof = issue_freshness_proof(
        feed_sovereign_id,
        feed_sequence,
        hashlib.sha256(f"{feed_sovereign_id}:{feed_sequence}".encode()).hexdigest(),
        kp.private_key,
        issued_by="feed-key",
        issuer_sovereign_id="feed-node-1",
        valid_for_seconds=valid_for,
        now=ts,
    )
    return proof, kp.public_key_b64


# ---------------------------------------------------------------------------
# issue_freshness_proof
# ---------------------------------------------------------------------------


class TestIssueFreshnessProof:
    def test_basic_fields_correct(self):
        proof, pub = _make_proof()
        assert proof.feed_sovereign_id == "bank-a"
        assert proof.feed_sequence == 5
        assert proof.signature is not None
        assert proof.issuer_sovereign_id == "feed-node-1"

    def test_valid_until_is_attested_plus_valid_for(self):
        ts = _now()
        proof, _ = _make_proof(valid_for=120, now=ts)
        delta = (proof.proof_valid_until - proof.attested_at).total_seconds()
        assert abs(delta - 120) < 1


# ---------------------------------------------------------------------------
# verify_freshness_proof
# ---------------------------------------------------------------------------


class TestVerifyFreshnessProof:
    def test_valid_proof_passes(self):
        proof, pub = _make_proof(feed_sequence=5)
        result = verify_freshness_proof(proof, [pub], required_sequence=5, at_time=_now())
        assert result.valid, f"Expected valid, got {result.reason}"

    def test_sequence_exceeds_requirement_passes(self):
        proof, pub = _make_proof(feed_sequence=10)
        result = verify_freshness_proof(proof, [pub], required_sequence=3, at_time=_now())
        assert result.valid

    def test_expired_proof_fails(self):
        ts = _now() - timedelta(hours=2)
        proof, pub = _make_proof(feed_sequence=5, valid_for=10, now=ts)
        # proof.proof_valid_until = ts + 10s, now is ts + 2h → expired
        result = verify_freshness_proof(proof, [pub], required_sequence=5, at_time=_now())
        assert not result.valid
        assert result.reason == "expired"

    def test_sequence_insufficient_fails(self):
        proof, pub = _make_proof(feed_sequence=3)
        result = verify_freshness_proof(proof, [pub], required_sequence=10, at_time=_now())
        assert not result.valid
        assert result.reason == "sequence_insufficient"

    def test_invalid_signature_fails(self):
        proof, _ = _make_proof(feed_sequence=5)
        wrong_kp = generate_keypair()
        result = verify_freshness_proof(proof, [wrong_kp.public_key_b64],
                                        required_sequence=5, at_time=_now())
        assert not result.valid
        assert result.reason == "invalid_signature"

    def test_missing_signature_fails(self):
        proof, pub = _make_proof()
        unsigned = proof.model_copy(update={"signature": None})
        result = verify_freshness_proof(unsigned, [pub], required_sequence=5, at_time=_now())
        assert not result.valid
        assert result.reason == "missing_signature"

    def test_fail_fast_order_sig_before_expiry(self):
        """invalid_signature checked before expiry."""
        ts = _now() - timedelta(hours=2)
        proof, _ = _make_proof(feed_sequence=5, valid_for=10, now=ts)  # expired
        wrong_kp = generate_keypair()
        result = verify_freshness_proof(proof, [wrong_kp.public_key_b64],
                                        required_sequence=5, at_time=_now())
        # Signature check happens before expiry check
        assert result.reason == "invalid_signature"


# ---------------------------------------------------------------------------
# BoundaryEngine with require_freshness_proof
# ---------------------------------------------------------------------------


class TestBoundaryEngineWithProof:
    def test_valid_proof_authorized(self):
        agreement = _make_agreement(commitment=5)
        proof, pub = _make_proof(feed_sequence=5)
        op_kp = generate_keypair()
        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id="aspayr",
            provider_sovereign_id="bank-a",
            requested_capability="transactions.read",
            context_freshness_seq=5,
        )
        engine = BoundaryEngine("bank-a", require_freshness_proof=True)
        decision = engine.evaluate(
            ctx, agreement, op_kp.private_key,
            issued_by="op",
            freshness_proof=proof,
            freshness_proof_issuer_keys=[pub],
        )
        assert decision.authorized
        assert decision.freshness_proof is not None
        assert decision.freshness_proof.proof_id == proof.proof_id

    def test_absent_proof_denied(self):
        agreement = _make_agreement(commitment=5)
        op_kp = generate_keypair()
        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id="aspayr",
            provider_sovereign_id="bank-a",
            requested_capability="transactions.read",
            context_freshness_seq=5,
        )
        engine = BoundaryEngine("bank-a", require_freshness_proof=True)
        decision = engine.evaluate(ctx, agreement, op_kp.private_key, issued_by="op")
        assert not decision.authorized
        # freshness_proof gate failed
        proof_gate = [g for g in decision.gate_results if g.gate_name == "freshness_proof"]
        assert proof_gate and not proof_gate[0].passed

    def test_invalid_sig_proof_denied(self):
        agreement = _make_agreement(commitment=5)
        proof, _ = _make_proof(feed_sequence=5)
        wrong_kp = generate_keypair()
        op_kp = generate_keypair()
        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id="aspayr",
            provider_sovereign_id="bank-a",
            requested_capability="transactions.read",
            context_freshness_seq=5,
        )
        engine = BoundaryEngine("bank-a", require_freshness_proof=True)
        decision = engine.evaluate(
            ctx, agreement, op_kp.private_key, issued_by="op",
            freshness_proof=proof,
            freshness_proof_issuer_keys=[wrong_kp.public_key_b64],
        )
        assert not decision.authorized

    def test_expired_proof_denied(self):
        agreement = _make_agreement(commitment=5)
        ts = _now() - timedelta(hours=2)
        proof, pub = _make_proof(feed_sequence=5, valid_for=10, now=ts)  # expired
        op_kp = generate_keypair()
        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id="aspayr",
            provider_sovereign_id="bank-a",
            requested_capability="transactions.read",
            context_freshness_seq=5,
        )
        engine = BoundaryEngine("bank-a", require_freshness_proof=True)
        decision = engine.evaluate(
            ctx, agreement, op_kp.private_key, issued_by="op",
            freshness_proof=proof,
            freshness_proof_issuer_keys=[pub],
        )
        assert not decision.authorized

    def test_sequence_insufficient_proof_denied(self):
        agreement = _make_agreement(commitment=10)
        proof, pub = _make_proof(feed_sequence=3)  # proof seq < commitment
        op_kp = generate_keypair()
        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id="aspayr",
            provider_sovereign_id="bank-a",
            requested_capability="transactions.read",
            context_freshness_seq=10,
        )
        engine = BoundaryEngine("bank-a", require_freshness_proof=True)
        decision = engine.evaluate(
            ctx, agreement, op_kp.private_key, issued_by="op",
            freshness_proof=proof,
            freshness_proof_issuer_keys=[pub],
        )
        assert not decision.authorized

    def test_no_require_proof_no_proof_still_works(self):
        agreement = _make_agreement(commitment=0)
        op_kp = generate_keypair()
        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id="aspayr",
            provider_sovereign_id="bank-a",
            requested_capability="transactions.read",
        )
        engine = BoundaryEngine("bank-a")  # default: require_freshness_proof=False
        decision = engine.evaluate(ctx, agreement, op_kp.private_key, issued_by="op")
        assert decision.authorized
        assert decision.freshness_proof is None

    def test_proof_embedded_in_canonical_json(self):
        """freshness_proof is included in canonical JSON (operator signs over it)."""
        agreement = _make_agreement(commitment=5)
        proof, pub = _make_proof(feed_sequence=5)
        op_kp = generate_keypair()
        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id="aspayr",
            provider_sovereign_id="bank-a",
            requested_capability="transactions.read",
            context_freshness_seq=5,
        )
        engine = BoundaryEngine("bank-a", require_freshness_proof=True)
        decision = engine.evaluate(
            ctx, agreement, op_kp.private_key, issued_by="op",
            freshness_proof=proof, freshness_proof_issuer_keys=[pub],
        )
        canonical = json.loads(decision.to_canonical_json())
        assert "freshness_proof" in canonical
        assert canonical["freshness_proof"] is not None
        assert "proof_id" in canonical["freshness_proof"]


# ---------------------------------------------------------------------------
# verify_boundary_decision with embedded proof
# ---------------------------------------------------------------------------


class TestVerifyBoundaryDecisionWithProof:
    def _make_decision_with_proof(self):
        agreement = _make_agreement(commitment=5)
        proof, proof_pub = _make_proof(feed_sequence=5)
        op_kp = generate_keypair()
        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id="aspayr",
            provider_sovereign_id="bank-a",
            requested_capability="transactions.read",
            context_freshness_seq=5,
        )
        engine = BoundaryEngine("bank-a", require_freshness_proof=True, decision_valid_seconds=3600)
        decision = engine.evaluate(
            ctx, agreement, op_kp.private_key, issued_by="op",
            freshness_proof=proof, freshness_proof_issuer_keys=[proof_pub],
        )
        return decision, op_kp.public_key_b64, proof_pub

    def test_valid_decision_with_proof_accepted(self):
        decision, op_pub, proof_pub = self._make_decision_with_proof()
        result = verify_boundary_decision(
            decision, [op_pub],
            freshness_proof_issuer_keys=[proof_pub],
        )
        assert result.accepted
        assert result.reason == "authorized"

    def test_invalid_proof_sig_rejected(self):
        decision, op_pub, _ = self._make_decision_with_proof()
        wrong_kp = generate_keypair()
        result = verify_boundary_decision(
            decision, [op_pub],
            freshness_proof_issuer_keys=[wrong_kp.public_key_b64],
        )
        assert not result.accepted
        assert result.reason == "freshness_proof_invalid_signature"

    def test_expired_proof_in_decision_rejected(self):
        agreement = _make_agreement(commitment=5)
        ts_past = _now() - timedelta(hours=2)
        proof, proof_pub = _make_proof(feed_sequence=5, valid_for=10, now=ts_past)  # expired
        op_kp = generate_keypair()
        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id="aspayr",
            provider_sovereign_id="bank-a",
            requested_capability="transactions.read",
            context_freshness_seq=5,
        )
        engine = BoundaryEngine("bank-a", decision_valid_seconds=86400)
        # Force-embed an expired proof into decision (bypass engine's proof validation)
        ctx_now = _now()
        decision = engine.evaluate(ctx, agreement, op_kp.private_key, issued_by="op", now=ctx_now)
        # Manually attach expired proof via model_copy + re-sign
        # Reconstruct decision with proof and re-sign
        decision_with_proof = decision.model_copy(update={"freshness_proof": proof, "signature": None})
        from genesis_mesh.crypto import sign_model
        sig = sign_model(decision_with_proof, op_kp.private_key, "op")
        decision_with_proof = decision_with_proof.model_copy(update={"signature": sig})

        result = verify_boundary_decision(
            decision_with_proof, [op_kp.public_key_b64],
            freshness_proof_issuer_keys=[proof_pub],
        )
        assert not result.accepted
        assert result.reason == "freshness_proof_expired"


# ---------------------------------------------------------------------------
# verify_evidence_chain stale_freshness_proof
# ---------------------------------------------------------------------------


class TestStaleProofInChain:
    def _make_decision_and_proof(self):
        agreement = _make_agreement(commitment=5)
        now = _now()
        proof, proof_pub = _make_proof(feed_sequence=5, valid_for=300, now=now)
        op_kp = generate_keypair()
        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id="aspayr",
            provider_sovereign_id="bank-a",
            requested_capability="transactions.read",
            context_freshness_seq=5,
        )
        engine = BoundaryEngine("bank-a", require_freshness_proof=True, decision_valid_seconds=86400)
        decision = engine.evaluate(
            ctx, agreement, op_kp.private_key, issued_by="op",
            freshness_proof=proof, freshness_proof_issuer_keys=[proof_pub], now=now,
        )
        return decision, op_kp

    def test_execution_within_proof_window_passes(self):
        decision, op_kp = self._make_decision_and_proof()
        exec_kp = generate_keypair()
        # Execute while proof is still valid (now = attested_at + 60s)
        exec_time = decision.freshness_proof.attested_at + timedelta(seconds=60)
        ev = record_execution(
            decision, "bank-a", "transactions.read", "success",
            exec_kp.private_key, issued_by="exec", sequence_no=1, now=exec_time,
        )
        chain = EvidenceChain(decision_id=decision.decision_id, records=[ev])
        result = verify_evidence_chain(
            chain,
            executor_public_keys_by_sovereign={"bank-a": [exec_kp.public_key_b64]},
            decision=decision,
        )
        assert result.verified, f"Expected verified, got {result.reason}"

    def test_execution_after_proof_window_stale(self):
        decision, op_kp = self._make_decision_and_proof()
        exec_kp = generate_keypair()
        # Execute after proof.proof_valid_until
        exec_time = decision.freshness_proof.proof_valid_until + timedelta(seconds=1)
        ev = record_execution(
            decision, "bank-a", "transactions.read", "success",
            exec_kp.private_key, issued_by="exec", sequence_no=1, now=exec_time,
        )
        chain = EvidenceChain(decision_id=decision.decision_id, records=[ev])
        result = verify_evidence_chain(
            chain,
            executor_public_keys_by_sovereign={"bank-a": [exec_kp.public_key_b64]},
            decision=decision,
        )
        assert not result.verified
        assert result.reason == "stale_freshness_proof"
        assert result.failed_at_sequence == 1

    def test_no_decision_no_stale_check(self):
        """When decision not provided, stale-proof check is skipped."""
        agreement = _make_agreement(commitment=5)
        op_kp = generate_keypair()
        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id="aspayr",
            provider_sovereign_id="bank-a",
            requested_capability="transactions.read",
            context_freshness_seq=5,
        )
        engine = BoundaryEngine("bank-a", decision_valid_seconds=86400)
        decision = engine.evaluate(ctx, agreement, op_kp.private_key, issued_by="op")

        exec_kp = generate_keypair()
        ev = record_execution(
            decision, "bank-a", "transactions.read", "success",
            exec_kp.private_key, issued_by="exec", sequence_no=1,
        )
        chain = EvidenceChain(decision_id=decision.decision_id, records=[ev])
        result = verify_evidence_chain(
            chain,
            executor_public_keys_by_sovereign={"bank-a": [exec_kp.public_key_b64]},
            decision=None,  # no stale check
        )
        assert result.verified


# ---------------------------------------------------------------------------
# Transport independence
# ---------------------------------------------------------------------------


class TestTransportIndependence:
    def test_proof_json_round_trip(self):
        proof, pub = _make_proof()
        raw = proof.model_dump_json()
        recovered = FreshnessProof.model_validate_json(raw)
        assert proof.to_canonical_json() == recovered.to_canonical_json()

    def test_decision_with_proof_json_round_trip(self):
        agreement = _make_agreement(commitment=5)
        proof, pub = _make_proof(feed_sequence=5)
        op_kp = generate_keypair()
        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id="aspayr",
            provider_sovereign_id="bank-a",
            requested_capability="transactions.read",
            context_freshness_seq=5,
        )
        engine = BoundaryEngine("bank-a", require_freshness_proof=True, decision_valid_seconds=3600)
        decision = engine.evaluate(
            ctx, agreement, op_kp.private_key, issued_by="op",
            freshness_proof=proof, freshness_proof_issuer_keys=[pub],
        )
        raw = decision.model_dump_json()
        recovered = BoundaryDecision.model_validate_json(raw)
        assert decision.to_canonical_json() == recovered.to_canonical_json()


# ---------------------------------------------------------------------------
# CLI: trust freshness issue
# ---------------------------------------------------------------------------


class TestCliFreshnessIssue:
    def test_issue_creates_file(self, tmp_path: Path):
        kp = generate_keypair()
        key_file = tmp_path / "feed.key"
        key_file.write_text(kp.private_key_b64 + "\n", encoding="utf-8")
        output_file = tmp_path / "proof.json"

        runner = CliRunner()
        result = runner.invoke(freshness, [
            "issue",
            "--feed-sovereign", "bank-a",
            "--feed-sequence", "42",
            "--issuer-sovereign", "feed-node-1",
            "--valid-for", "300",
            "--signing-key", str(key_file),
            "--output", str(output_file),
        ])
        assert result.exit_code == 0, result.output
        assert output_file.exists()
        proof = FreshnessProof.model_validate_json(output_file.read_text())
        assert proof.feed_sequence == 42
        assert proof.signature is not None


# ---------------------------------------------------------------------------
# CLI: trust freshness verify
# ---------------------------------------------------------------------------


class TestCliFreshnessVerify:
    def test_valid_proof_exits_zero(self, tmp_path: Path):
        proof, pub = _make_proof(feed_sequence=10)
        proof_file = tmp_path / "proof.json"
        proof_file.write_text(proof.model_dump_json(), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(freshness, [
            "verify",
            "--proof", str(proof_file),
            "--issuer-key", pub,
            "--required-sequence", "10",
        ])
        assert result.exit_code == 0, result.output
        assert "OK" in result.output

    def test_expired_proof_exits_one(self, tmp_path: Path):
        ts = _now() - timedelta(hours=2)
        proof, pub = _make_proof(feed_sequence=5, valid_for=10, now=ts)
        proof_file = tmp_path / "proof.json"
        proof_file.write_text(proof.model_dump_json(), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(freshness, [
            "verify",
            "--proof", str(proof_file),
            "--issuer-key", pub,
            "--required-sequence", "5",
        ])
        assert result.exit_code == 1
        assert "FAIL" in result.output

    def test_sequence_insufficient_exits_one(self, tmp_path: Path):
        proof, pub = _make_proof(feed_sequence=3)
        proof_file = tmp_path / "proof.json"
        proof_file.write_text(proof.model_dump_json(), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(freshness, [
            "verify",
            "--proof", str(proof_file),
            "--issuer-key", pub,
            "--required-sequence", "10",
        ])
        assert result.exit_code == 1

    def test_json_output_format(self, tmp_path: Path):
        proof, pub = _make_proof(feed_sequence=5)
        proof_file = tmp_path / "proof.json"
        proof_file.write_text(proof.model_dump_json(), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(freshness, [
            "verify",
            "--proof", str(proof_file),
            "--issuer-key", pub,
            "--required-sequence", "5",
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["valid"] is True
        assert data["reason"] == "valid"
