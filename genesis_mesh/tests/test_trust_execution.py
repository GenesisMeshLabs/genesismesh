"""Tests for Execution Evidence Hash Chain (v0.29).

Covers:
- record_execution (no prior) → valid signed record with prev=None
- record_execution (with prior) → prev_evidence_digest set correctly
- verify_evidence_chain: 1, 2, 3 records in order
- Chain break: removed middle record (sequence gap)
- Digest mismatch (tampered prior digest)
- Tampered field (executed_at) breaks signature
- Capability mismatch detection
- Sequence out-of-order (seq 2 before seq 1)
- Sequence gap (1, 3 — skipping 2)
- Missing signature
- Wrong executor key
- Empty chain
- JSON round-trip (transport independence)
- CLI: trust execution record, verify
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from genesis_mesh.cli.execution_ops import execution
from genesis_mesh.crypto import generate_keypair
from genesis_mesh.models.agreement import AgreementRecord, AgreementTerms
from genesis_mesh.models.context import BoundaryDecision, ContextRecord
from genesis_mesh.models.execution import EvidenceChain, ExecutionEvidence
from genesis_mesh.trust.context import BoundaryEngine
from genesis_mesh.trust.execution import (
    EvidenceChainVerificationResult,
    record_execution,
    verify_evidence_chain,
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


def _terms(caps=None, days=30) -> AgreementTerms:
    now = _now()
    return AgreementTerms(
        capabilities=caps or ["transactions.read"],
        scope={},
        valid_from=now,
        valid_until=now + timedelta(days=days),
        freshness_commitment=0,
    )


def _make_decision() -> tuple[BoundaryDecision, object, str]:
    kp1 = generate_keypair()
    kp2 = generate_keypair()
    graph = _active_graph("aspayr", "bank-a")
    terms = _terms()
    now = _now()
    offer = build_offer("aspayr", "bank-a", terms, graph, kp1.private_key,
                        issued_by="k1", expires_at=now + timedelta(hours=1), now=now)
    counter = build_counter(offer, terms, graph, kp2.private_key, issued_by="k2", now=now)
    agreement = accept_counter(counter, offer, kp1.private_key, issued_by="k1", now=now)
    ctx = ContextRecord(
        agreement_id=agreement.agreement_id,
        requester_sovereign_id="aspayr",
        provider_sovereign_id="bank-a",
        requested_capability="transactions.read",
    )
    op_kp = generate_keypair()
    engine = BoundaryEngine("bank-a", decision_valid_seconds=3600)
    decision = engine.evaluate(ctx, agreement, op_kp.private_key, issued_by="op-key", now=now)
    return decision, op_kp.private_key, op_kp.public_key_b64


def _make_chain(n: int, decision: BoundaryDecision, executor_sk, executor_id="bank-a"):
    """Build a chain of n ExecutionEvidence records."""
    records = []
    prior = None
    for i in range(1, n + 1):
        ev = record_execution(
            decision,
            executor_sovereign_id=executor_id,
            executed_capability="transactions.read",
            outcome="success",
            signing_key=executor_sk,
            issued_by="exec-key",
            sequence_no=i,
            prior_record=prior,
        )
        records.append(ev)
        prior = ev
    return records


# ---------------------------------------------------------------------------
# record_execution
# ---------------------------------------------------------------------------


class TestRecordExecution:
    def test_first_record_has_no_prev_digest(self):
        decision, sk, pub = _make_decision()
        ev = record_execution(decision, "bank-a", "transactions.read", "success",
                               sk, issued_by="k", sequence_no=1)
        assert ev.prev_evidence_digest is None
        assert ev.sequence_no == 1
        assert ev.signature is not None

    def test_second_record_links_to_first(self):
        decision, sk, pub = _make_decision()
        ev1 = record_execution(decision, "bank-a", "transactions.read", "success",
                                sk, issued_by="k", sequence_no=1)
        ev2 = record_execution(decision, "bank-a", "transactions.read", "success",
                                sk, issued_by="k", sequence_no=2, prior_record=ev1)
        assert ev2.prev_evidence_digest == ev1.digest()

    def test_digest_covers_all_fields(self):
        decision, sk, pub = _make_decision()
        ev1 = record_execution(decision, "bank-a", "transactions.read", "success",
                                sk, issued_by="k", sequence_no=1)
        # Tamper a field
        tampered = ev1.model_copy(update={"outcome": "failure"})
        assert tampered.digest() != ev1.digest()

    def test_outcome_variants(self):
        decision, sk, pub = _make_decision()
        for outcome in ("success", "failure", "partial"):
            ev = record_execution(decision, "bank-a", "transactions.read", outcome,
                                   sk, issued_by="k", sequence_no=1)
            assert ev.outcome == outcome


# ---------------------------------------------------------------------------
# verify_evidence_chain — valid
# ---------------------------------------------------------------------------


class TestValidChain:
    def test_single_record_verifies(self):
        decision, sk, pub = _make_decision()
        records = _make_chain(1, decision, sk)
        chain = EvidenceChain(decision_id=decision.decision_id, records=records)
        result = verify_evidence_chain(chain, executor_public_keys_by_sovereign={"bank-a": [pub]})
        assert result.verified, f"Expected verified, got {result.reason}"
        assert result.chain_length == 1

    def test_three_record_chain_verifies(self):
        decision, sk, pub = _make_decision()
        records = _make_chain(3, decision, sk)
        chain = EvidenceChain(decision_id=decision.decision_id, records=records)
        result = verify_evidence_chain(chain, executor_public_keys_by_sovereign={"bank-a": [pub]})
        assert result.verified, f"Expected verified, got {result.reason}"
        assert result.chain_length == 3

    def test_capability_filter_passes(self):
        decision, sk, pub = _make_decision()
        records = _make_chain(2, decision, sk)
        chain = EvidenceChain(decision_id=decision.decision_id, records=records)
        result = verify_evidence_chain(
            chain,
            executor_public_keys_by_sovereign={"bank-a": [pub]},
            expected_capability="transactions.read",
        )
        assert result.verified


# ---------------------------------------------------------------------------
# Chain break scenarios
# ---------------------------------------------------------------------------


class TestChainBreak:
    def test_missing_middle_record_detected(self):
        decision, sk, pub = _make_decision()
        records = _make_chain(3, decision, sk)
        # Remove middle record — records now: [seq1, seq3]
        broken = [records[0], records[2]]
        chain = EvidenceChain(decision_id=decision.decision_id, records=broken)
        result = verify_evidence_chain(chain, executor_public_keys_by_sovereign={"bank-a": [pub]})
        assert not result.verified
        assert result.reason == "sequence_gap"
        assert result.failed_at_sequence == 3

    def test_wrong_prev_digest_detected(self):
        decision, sk, pub = _make_decision()
        records = _make_chain(2, decision, sk)
        tampered = records[1].model_copy(update={"prev_evidence_digest": "a" * 64})
        chain = EvidenceChain(decision_id=decision.decision_id, records=[records[0], tampered])
        result = verify_evidence_chain(chain, executor_public_keys_by_sovereign={"bank-a": [pub]})
        assert not result.verified
        assert result.reason == "digest_mismatch"
        assert result.failed_at_sequence == 2

    def test_tampered_field_breaks_chain(self):
        """Tampered executed_at → digest changes → next record's prev_digest invalid."""
        decision, sk, pub = _make_decision()
        records = _make_chain(2, decision, sk)
        tampered = records[0].model_copy(update={"outcome_detail": "injected"})
        chain = EvidenceChain(decision_id=decision.decision_id, records=[tampered, records[1]])
        result = verify_evidence_chain(chain, executor_public_keys_by_sovereign={"bank-a": [pub]})
        assert not result.verified
        # Either signature fails on tampered record or digest fails on next
        assert result.reason in ("invalid_signature", "digest_mismatch")

    def test_first_record_with_prev_digest_is_chain_break(self):
        decision, sk, pub = _make_decision()
        records = _make_chain(1, decision, sk)
        tampered = records[0].model_copy(update={"prev_evidence_digest": "b" * 64})
        chain = EvidenceChain(decision_id=decision.decision_id, records=[tampered])
        result = verify_evidence_chain(chain, executor_public_keys_by_sovereign={"bank-a": [pub]})
        assert not result.verified
        assert result.reason == "chain_break"

    def test_reordered_records_start_detected(self):
        """[seq2, seq1] — seq=2 where expected=1 (2 > 1) → sequence_gap."""
        decision, sk, pub = _make_decision()
        records = _make_chain(2, decision, sk)
        # Put seq2 before seq1 — first check sees seq=2 where expected=1
        chain = EvidenceChain(decision_id=decision.decision_id, records=[records[1], records[0]])
        result = verify_evidence_chain(chain, executor_public_keys_by_sovereign={"bank-a": [pub]})
        assert not result.verified
        assert result.reason == "sequence_gap"

    def test_out_of_order_lower_seq_after_higher(self):
        """[seq1, seq2, seq1] — seq=1 where expected=3 (1 < 3) → sequence_out_of_order."""
        decision, sk, pub = _make_decision()
        records = _make_chain(2, decision, sk)
        # After seq2, supply seq1 again
        extra = records[0]
        chain = EvidenceChain(decision_id=decision.decision_id,
                              records=[records[0], records[1], extra])
        result = verify_evidence_chain(chain, executor_public_keys_by_sovereign={"bank-a": [pub]})
        assert not result.verified
        assert result.reason == "sequence_out_of_order"

    def test_empty_chain_rejected(self):
        decision, sk, pub = _make_decision()
        chain = EvidenceChain(decision_id=decision.decision_id, records=[])
        result = verify_evidence_chain(chain, executor_public_keys_by_sovereign={"bank-a": [pub]})
        assert not result.verified
        assert result.reason == "empty_chain"


# ---------------------------------------------------------------------------
# Signature requirements
# ---------------------------------------------------------------------------


class TestSignatureRequirements:
    def test_wrong_executor_key_rejected(self):
        decision, sk, pub = _make_decision()
        wrong_kp = generate_keypair()
        records = _make_chain(1, decision, sk)
        chain = EvidenceChain(decision_id=decision.decision_id, records=records)
        result = verify_evidence_chain(
            chain,
            executor_public_keys_by_sovereign={"bank-a": [wrong_kp.public_key_b64]},
        )
        assert not result.verified
        assert result.reason == "invalid_signature"

    def test_no_keys_for_sovereign_rejected(self):
        decision, sk, pub = _make_decision()
        records = _make_chain(1, decision, sk)
        chain = EvidenceChain(decision_id=decision.decision_id, records=records)
        result = verify_evidence_chain(chain, executor_public_keys_by_sovereign={})
        assert not result.verified
        assert result.reason == "invalid_signature"

    def test_missing_signature_rejected(self):
        decision, sk, pub = _make_decision()
        records = _make_chain(1, decision, sk)
        unsigned = records[0].model_copy(update={"signature": None})
        chain = EvidenceChain(decision_id=decision.decision_id, records=[unsigned])
        result = verify_evidence_chain(chain, executor_public_keys_by_sovereign={"bank-a": [pub]})
        assert not result.verified
        assert result.reason == "missing_signature"


# ---------------------------------------------------------------------------
# Capability mismatch
# ---------------------------------------------------------------------------


class TestCapabilityMismatch:
    def test_capability_mismatch_detected(self):
        decision, sk, pub = _make_decision()
        records = _make_chain(1, decision, sk)
        chain = EvidenceChain(decision_id=decision.decision_id, records=records)
        result = verify_evidence_chain(
            chain,
            executor_public_keys_by_sovereign={"bank-a": [pub]},
            expected_capability="admin.write",  # wrong
        )
        assert not result.verified
        assert result.reason == "capability_mismatch"


# ---------------------------------------------------------------------------
# Transport independence
# ---------------------------------------------------------------------------


class TestTransportIndependence:
    def test_json_round_trip_single_record(self):
        decision, sk, pub = _make_decision()
        records = _make_chain(1, decision, sk)
        raw = records[0].model_dump_json()
        recovered = ExecutionEvidence.model_validate_json(raw)
        assert records[0].to_canonical_json() == recovered.to_canonical_json()

    def test_json_round_trip_chain_verifies(self):
        decision, sk, pub = _make_decision()
        records = _make_chain(2, decision, sk)
        rt_records = [
            ExecutionEvidence.model_validate_json(r.model_dump_json()) for r in records
        ]
        chain = EvidenceChain(decision_id=decision.decision_id, records=rt_records)
        result = verify_evidence_chain(chain, executor_public_keys_by_sovereign={"bank-a": [pub]})
        assert result.verified, f"JSON round-trip failed: {result.reason}"


# ---------------------------------------------------------------------------
# CLI: trust execution record
# ---------------------------------------------------------------------------


class TestCliExecutionRecord:
    def test_record_creates_file(self, tmp_path: Path):
        decision, sk, pub = _make_decision()
        decision_file = tmp_path / "decision.json"
        decision_file.write_text(decision.model_dump_json(), encoding="utf-8")
        from genesis_mesh.crypto import generate_keypair as gkp
        kp = gkp()
        key_file = tmp_path / "exec.key"
        key_file.write_text(kp.private_key_b64 + "\n", encoding="utf-8")
        output_file = tmp_path / "ev1.json"

        runner = CliRunner()
        result = runner.invoke(execution, [
            "record",
            "--decision", str(decision_file),
            "--capability", "transactions.read",
            "--executor", "bank-a",
            "--outcome", "success",
            "--sequence", "1",
            "--signing-key", str(key_file),
            "--output", str(output_file),
        ])
        assert result.exit_code == 0, result.output
        assert output_file.exists()
        ev = ExecutionEvidence.model_validate_json(output_file.read_text())
        assert ev.sequence_no == 1
        assert ev.prev_evidence_digest is None

    def test_chained_record_creates_file(self, tmp_path: Path):
        decision, sk, pub = _make_decision()
        decision_file = tmp_path / "decision.json"
        decision_file.write_text(decision.model_dump_json(), encoding="utf-8")
        from genesis_mesh.crypto import generate_keypair as gkp
        kp = gkp()
        key_file = tmp_path / "exec.key"
        key_file.write_text(kp.private_key_b64 + "\n", encoding="utf-8")

        # Create first record
        ev1 = record_execution(decision, "bank-a", "transactions.read", "success",
                                kp.private_key, issued_by="k", sequence_no=1)
        ev1_file = tmp_path / "ev1.json"
        ev1_file.write_text(ev1.model_dump_json(), encoding="utf-8")

        output_file = tmp_path / "ev2.json"
        runner = CliRunner()
        result = runner.invoke(execution, [
            "record",
            "--decision", str(decision_file),
            "--capability", "transactions.read",
            "--executor", "bank-a",
            "--outcome", "success",
            "--sequence", "2",
            "--prior", str(ev1_file),
            "--signing-key", str(key_file),
            "--output", str(output_file),
        ])
        assert result.exit_code == 0, result.output
        ev2 = ExecutionEvidence.model_validate_json(output_file.read_text())
        assert ev2.prev_evidence_digest == ev1.digest()


# ---------------------------------------------------------------------------
# CLI: trust execution verify
# ---------------------------------------------------------------------------


class TestCliExecutionVerify:
    def test_valid_chain_exits_zero(self, tmp_path: Path):
        decision, sk, pub = _make_decision()
        records = _make_chain(2, decision, sk)

        ev1_file = tmp_path / "ev1.json"
        ev1_file.write_text(records[0].model_dump_json(), encoding="utf-8")
        ev2_file = tmp_path / "ev2.json"
        ev2_file.write_text(records[1].model_dump_json(), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(execution, [
            "verify",
            "--decision-id", decision.decision_id,
            "--evidence", str(ev1_file),
            "--evidence", str(ev2_file),
            "--key", f"bank-a:{pub}",
        ])
        assert result.exit_code == 0, result.output
        assert "OK" in result.output

    def test_wrong_key_exits_one(self, tmp_path: Path):
        decision, sk, pub = _make_decision()
        records = _make_chain(1, decision, sk)

        ev1_file = tmp_path / "ev1.json"
        ev1_file.write_text(records[0].model_dump_json(), encoding="utf-8")

        wrong_kp = generate_keypair()
        runner = CliRunner()
        result = runner.invoke(execution, [
            "verify",
            "--decision-id", decision.decision_id,
            "--evidence", str(ev1_file),
            "--key", f"bank-a:{wrong_kp.public_key_b64}",
        ])
        assert result.exit_code == 1
        assert "FAIL" in result.output

    def test_json_output_format(self, tmp_path: Path):
        decision, sk, pub = _make_decision()
        records = _make_chain(1, decision, sk)

        ev1_file = tmp_path / "ev1.json"
        ev1_file.write_text(records[0].model_dump_json(), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(execution, [
            "verify",
            "--decision-id", decision.decision_id,
            "--evidence", str(ev1_file),
            "--key", f"bank-a:{pub}",
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["verified"] is True
        assert data["reason"] == "verified"
        assert "chain_length" in data
