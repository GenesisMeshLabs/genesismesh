"""Tests for Distributed Consensus Authorization (v0.36).

Covers:
- cast_validator_vote(): approve and reject paths
- assemble_consensus_proof(): 2-of-3 threshold met / threshold not met
- Votes from non-named validators excluded from count
- verify_consensus_proof(): all 8 verification reason codes
- issue_ephemeral_identity() / verify_ephemeral_identity(): all paths
- ConsensusGate in BoundaryEngine: passes with valid proof / blocks without
- Normal BoundaryEngine (no consensus gate) unaffected
- CLI: vote / assemble / verify / issue-identity / verify-identity
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
from genesis_mesh.models.consensus import ConsensusProof, EphemeralExecutionIdentity, ValidatorVote
from genesis_mesh.models.context import ContextRecord
from genesis_mesh.models.justification import JustificationProof
from genesis_mesh.trust.agreement import accept_counter, build_counter, build_offer
from genesis_mesh.trust.consensus import (
    ConsensusGate,
    assemble_consensus_proof,
    cast_validator_vote,
    issue_ephemeral_identity,
    verify_consensus_proof,
    verify_ephemeral_identity,
)
from genesis_mesh.trust.context import BoundaryEngine, validity_window_gate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
_CAPS = ["transactions.send", "balances.read"]
_V1 = "validator-1"
_V2 = "validator-2"
_V3 = "validator-3"
_BEARER = "agent-b"
_ASSEMBLER = "assembler"


def _sk() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()


def _pub_b64(sk: nacl.signing.SigningKey) -> str:
    return base64.b64encode(bytes(sk.verify_key)).decode()


def _write_key(sk: nacl.signing.SigningKey) -> str:
    fd, path = tempfile.mkstemp(suffix=".key")
    os.close(fd)
    Path(path).write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
    return path


def _make_agreement() -> tuple[AgreementRecord, nacl.signing.SigningKey]:
    kp1 = generate_keypair()
    kp2 = generate_keypair()
    now = _NOW
    terms = AgreementTerms(
        capabilities=_CAPS,
        scope={},
        valid_from=now - timedelta(hours=1),
        valid_until=now + timedelta(days=30),
        freshness_commitment=0,
    )
    graph = {
        "sovereigns": [{"sovereign_id": "a"}, {"sovereign_id": "b"}],
        "recognition_edges": [
            {
                "from": "a", "to": "b", "treaty_id": "t-ab", "status": "active",
                "lifecycle_state": "active", "expiry_risk": "low",
                "valid_from": (now - timedelta(hours=2)).isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
            },
            {
                "from": "b", "to": "a", "treaty_id": "t-ba", "status": "active",
                "lifecycle_state": "active", "expiry_risk": "low",
                "valid_from": (now - timedelta(hours=2)).isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
            },
        ],
        "active_treaties": [],
        "revoked_trust_material": [],
    }
    offer = build_offer("a", "b", terms, graph, kp1.private_key,
                        issued_by="a-key", expires_at=now + timedelta(hours=1), now=now)
    counter = build_counter(offer, terms, graph, kp2.private_key, issued_by="b-key", now=now)
    agreement = accept_counter(counter, offer, kp1.private_key, issued_by="a-key", now=now)
    return agreement, kp1.private_key


def _make_justification_proof() -> tuple[JustificationProof, AgreementRecord, nacl.signing.SigningKey]:
    """Return a real JustificationProof from evaluate_with_proof."""
    agreement, sk = _make_agreement()
    engine = BoundaryEngine("operator", decision_valid_seconds=3600)
    ctx = ContextRecord(
        agreement_id=agreement.agreement_id,
        requester_sovereign_id="a",
        provider_sovereign_id="b",
        requested_capability=_CAPS[0],
        context_freshness_seq=0,
        requested_at=_NOW,
    )
    _, proof = engine.evaluate_with_proof(ctx, agreement, sk, issued_by="op-key", now=_NOW)
    return proof, agreement, sk


def _make_consensus_proof(
    v1_sk: nacl.signing.SigningKey,
    v2_sk: nacl.signing.SigningKey,
    v3_sk: nacl.signing.SigningKey,
    assembler_sk: nacl.signing.SigningKey,
    jp: JustificationProof,
    threshold: int = 2,
) -> ConsensusProof:
    v1_vote = cast_validator_vote(jp, _V1, True, v1_sk, now=_NOW)
    v2_vote = cast_validator_vote(jp, _V2, True, v2_sk, now=_NOW)
    v3_vote = cast_validator_vote(jp, _V3, False, v3_sk, now=_NOW)  # rejects
    return assemble_consensus_proof(
        jp, [v1_vote, v2_vote, v3_vote], threshold, [_V1, _V2, _V3],
        assembler_sk, issued_by=_ASSEMBLER, valid_for_seconds=300, now=_NOW,
    )


# ---------------------------------------------------------------------------
# cast_validator_vote
# ---------------------------------------------------------------------------


class TestCastValidatorVote:
    def test_approve_vote_signed(self) -> None:
        jp, _, _ = _make_justification_proof()
        sk = _sk()
        vote = cast_validator_vote(jp, _V1, True, sk, now=_NOW)
        assert vote.vote is True
        assert vote.signature is not None
        assert vote.proof_id == jp.proof_id

    def test_reject_vote_signed(self) -> None:
        jp, _, _ = _make_justification_proof()
        sk = _sk()
        vote = cast_validator_vote(jp, _V1, False, sk, reason="unusual pattern", now=_NOW)
        assert vote.vote is False
        assert vote.reason == "unusual pattern"

    def test_vote_links_to_decision_id(self) -> None:
        jp, _, _ = _make_justification_proof()
        sk = _sk()
        vote = cast_validator_vote(jp, _V1, True, sk, now=_NOW)
        assert vote.decision_id == jp.decision_id


# ---------------------------------------------------------------------------
# assemble_consensus_proof
# ---------------------------------------------------------------------------


class TestAssembleConsensusProof:
    def test_2_of_3_threshold_met(self) -> None:
        jp, _, _ = _make_justification_proof()
        v1_sk, v2_sk, v3_sk, asm_sk = _sk(), _sk(), _sk(), _sk()
        cp = _make_consensus_proof(v1_sk, v2_sk, v3_sk, asm_sk, jp)
        assert cp.threshold_met()
        assert len(cp.approvals()) == 2

    def test_threshold_not_met_raises(self) -> None:
        jp, _, _ = _make_justification_proof()
        v1_sk, v2_sk, v3_sk, asm_sk = _sk(), _sk(), _sk(), _sk()
        vote1 = cast_validator_vote(jp, _V1, False, v1_sk, now=_NOW)  # reject
        vote2 = cast_validator_vote(jp, _V2, False, v2_sk, now=_NOW)  # reject
        with pytest.raises(ValueError, match="threshold not met"):
            assemble_consensus_proof(
                jp, [vote1, vote2], 2, [_V1, _V2, _V3], asm_sk,
                issued_by=_ASSEMBLER, now=_NOW,
            )

    def test_vote_outside_named_set_not_counted(self) -> None:
        jp, _, _ = _make_justification_proof()
        v1_sk, v2_sk, v3_sk, asm_sk = _sk(), _sk(), _sk(), _sk()
        unknown_sk = _sk()
        vote_unknown = cast_validator_vote(jp, "unknown-validator", True, unknown_sk, now=_NOW)
        vote1 = cast_validator_vote(jp, _V1, True, v1_sk, now=_NOW)
        vote2 = cast_validator_vote(jp, _V2, True, v2_sk, now=_NOW)
        cp = assemble_consensus_proof(
            jp, [vote_unknown, vote1, vote2], 2, [_V1, _V2, _V3], asm_sk,
            issued_by=_ASSEMBLER, now=_NOW,
        )
        assert cp.threshold_met()
        # unknown-validator is NOT in approvals() (not in named set)
        assert all(v.validator_sovereign_id in [_V1, _V2, _V3] for v in cp.approvals())

    def test_assembled_proof_is_signed(self) -> None:
        jp, _, _ = _make_justification_proof()
        v1_sk, v2_sk, v3_sk, asm_sk = _sk(), _sk(), _sk(), _sk()
        cp = _make_consensus_proof(v1_sk, v2_sk, v3_sk, asm_sk, jp)
        assert cp.signature is not None


# ---------------------------------------------------------------------------
# verify_consensus_proof — all 8 reason codes
# ---------------------------------------------------------------------------


class TestVerifyConsensusProof:
    def _make(self) -> tuple[ConsensusProof, JustificationProof,
                             nacl.signing.SigningKey, nacl.signing.SigningKey,
                             nacl.signing.SigningKey, nacl.signing.SigningKey]:
        jp, _, _ = _make_justification_proof()
        v1_sk, v2_sk, v3_sk, asm_sk = _sk(), _sk(), _sk(), _sk()
        cp = _make_consensus_proof(v1_sk, v2_sk, v3_sk, asm_sk, jp)
        return cp, jp, v1_sk, v2_sk, v3_sk, asm_sk

    def _val_keys(
        self, v1_sk: nacl.signing.SigningKey, v2_sk: nacl.signing.SigningKey,
        v3_sk: nacl.signing.SigningKey,
    ) -> dict[str, str]:
        return {_V1: _pub_b64(v1_sk), _V2: _pub_b64(v2_sk), _V3: _pub_b64(v3_sk)}

    def test_valid(self) -> None:
        cp, jp, v1_sk, v2_sk, v3_sk, asm_sk = self._make()
        result = verify_consensus_proof(
            cp, self._val_keys(v1_sk, v2_sk, v3_sk), [_pub_b64(asm_sk)],
            justification_proof=jp, at_time=_NOW,
        )
        assert result.valid is True
        assert result.reason == "valid"

    def test_missing_signature(self) -> None:
        cp, jp, v1_sk, v2_sk, v3_sk, asm_sk = self._make()
        unsigned = cp.model_copy(update={"signature": None})
        result = verify_consensus_proof(unsigned, {}, [_pub_b64(asm_sk)], at_time=_NOW)
        assert result.reason == "missing_signature"

    def test_invalid_assembler_signature(self) -> None:
        cp, jp, v1_sk, v2_sk, v3_sk, asm_sk = self._make()
        wrong_sk = _sk()
        result = verify_consensus_proof(cp, {}, [_pub_b64(wrong_sk)], at_time=_NOW)
        assert result.reason == "invalid_assembler_signature"

    def test_proof_id_mismatch(self) -> None:
        cp, jp, v1_sk, v2_sk, v3_sk, asm_sk = self._make()
        wrong_jp = jp.model_copy(update={"proof_id": "wrong-id"})
        result = verify_consensus_proof(
            cp, self._val_keys(v1_sk, v2_sk, v3_sk), [_pub_b64(asm_sk)],
            justification_proof=wrong_jp, at_time=_NOW,
        )
        assert result.reason == "proof_id_mismatch"

    def test_invalid_vote_signature(self) -> None:
        cp, jp, v1_sk, v2_sk, v3_sk, asm_sk = self._make()
        wrong_v1 = _sk()
        val_keys = {_V1: _pub_b64(wrong_v1), _V2: _pub_b64(v2_sk), _V3: _pub_b64(v3_sk)}
        result = verify_consensus_proof(cp, val_keys, [_pub_b64(asm_sk)], at_time=_NOW)
        assert result.reason == "invalid_vote_signature"

    def test_threshold_not_met(self) -> None:
        jp, _, _ = _make_justification_proof()
        v1_sk, v2_sk, v3_sk, asm_sk = _sk(), _sk(), _sk(), _sk()
        # Only 1 approves but we ask for threshold=2; create with threshold=1, then verify with 2
        vote1 = cast_validator_vote(jp, _V1, True, v1_sk, now=_NOW)
        vote2 = cast_validator_vote(jp, _V2, False, v2_sk, now=_NOW)
        vote3 = cast_validator_vote(jp, _V3, False, v3_sk, now=_NOW)
        # Assemble with threshold=1 (so it assembles), then verify checking threshold>=2
        cp = assemble_consensus_proof(
            jp, [vote1, vote2, vote3], 1, [_V1, _V2, _V3], asm_sk,
            issued_by=_ASSEMBLER, now=_NOW,
        )
        # Tamper: bump required_threshold to 2 so it fails verification
        tampered = cp.model_copy(update={"required_threshold": 2})
        # Re-sign with assembler key so assembler sig still passes
        from genesis_mesh.crypto import sign_model
        sig = sign_model(tampered, asm_sk, _ASSEMBLER)
        tampered = tampered.model_copy(update={"signature": sig})
        result = verify_consensus_proof(tampered, {}, [_pub_b64(asm_sk)], at_time=_NOW)
        assert result.reason == "threshold_not_met"

    def test_vote_not_in_validator_set(self) -> None:
        jp, _, _ = _make_justification_proof()
        unknown_sk = _sk()
        asm_sk = _sk()
        # A vote from "unknown" with vote=True, but validator_sovereign_ids doesn't include it
        unknown_vote = cast_validator_vote(jp, "unknown", True, unknown_sk, now=_NOW)
        # We need at least threshold=1 from named set to assemble
        v1_sk = _sk()
        v1_vote = cast_validator_vote(jp, _V1, True, v1_sk, now=_NOW)
        cp = assemble_consensus_proof(
            jp, [v1_vote, unknown_vote], 1, [_V1, _V2], asm_sk,
            issued_by=_ASSEMBLER, now=_NOW,
        )
        # Tamper: inject the unknown vote as if it's from a named validator
        from genesis_mesh.models.consensus import ValidatorVote as VV
        tampered_vote = unknown_vote.model_copy(
            update={"validator_sovereign_id": _V2}
        )
        # This vote has sovereign_id=_V2 (in named set) but signature was over "unknown"
        # verify_consensus_proof will see invalid sig for _V2 → invalid_vote_signature
        # OR, manipulate so the vote appears in approved but not_in_set is checked
        # Actually, the simplest path: directly test by placing a vote with true where
        # the sovereign_id is NOT in the named set but vote=True
        # The check in verify_consensus_proof: vote_not_in_validator_set if vote.vote and
        # v.validator_sovereign_id not in proof.validator_sovereign_ids
        # We need to bypass assembler rejection first... let's build directly
        from genesis_mesh.models.consensus import ConsensusProof as CP
        from datetime import timezone
        from genesis_mesh.crypto import sign_model
        cp2 = CP(
            proof_id=jp.proof_id,
            decision_id=jp.decision_id,
            required_threshold=1,
            validator_sovereign_ids=[_V1],  # only V1 is named
            votes=[
                v1_vote,
                unknown_vote,   # unknown has vote=True but sovereign_id="unknown" ∉ [_V1]
            ],
            reached_at=_NOW,
            expires_at=_NOW + timedelta(minutes=5),
        )
        sig = sign_model(cp2, asm_sk, _ASSEMBLER)
        cp2 = cp2.model_copy(update={"signature": sig})
        result = verify_consensus_proof(
            cp2, {_V1: _pub_b64(v1_sk)}, [_pub_b64(asm_sk)], at_time=_NOW,
        )
        assert result.reason == "vote_not_in_validator_set"

    def test_expired(self) -> None:
        cp, jp, v1_sk, v2_sk, v3_sk, asm_sk = self._make()
        future_time = cp.expires_at + timedelta(seconds=1)
        result = verify_consensus_proof(
            cp, self._val_keys(v1_sk, v2_sk, v3_sk), [_pub_b64(asm_sk)], at_time=future_time,
        )
        assert result.reason == "expired"


# ---------------------------------------------------------------------------
# issue_ephemeral_identity / verify_ephemeral_identity
# ---------------------------------------------------------------------------


class TestEphemeralIdentity:
    def _make_identity(
        self,
    ) -> tuple[EphemeralExecutionIdentity, ConsensusProof,
               nacl.signing.SigningKey, nacl.signing.SigningKey,
               nacl.signing.SigningKey, nacl.signing.SigningKey]:
        jp, _, _ = _make_justification_proof()
        v1_sk, v2_sk, v3_sk, asm_sk = _sk(), _sk(), _sk(), _sk()
        cp = _make_consensus_proof(v1_sk, v2_sk, v3_sk, asm_sk, jp)
        eid = issue_ephemeral_identity(
            cp, _BEARER, _CAPS, asm_sk, issued_by=_ASSEMBLER,
            valid_for_seconds=120, now=_NOW,
        )
        return eid, cp, v1_sk, v2_sk, v3_sk, asm_sk

    def test_identity_has_short_expiry(self) -> None:
        eid, *_ = self._make_identity()
        assert eid.expires_at == _NOW + timedelta(seconds=120)

    def test_identity_is_signed(self) -> None:
        eid, *_ = self._make_identity()
        assert eid.signature is not None

    def test_verify_valid(self) -> None:
        eid, _, _, _, _, asm_sk = self._make_identity()
        result = verify_ephemeral_identity(
            eid, [_pub_b64(asm_sk)],
            requested_capability=_CAPS[0],
            bearer_sovereign_id=_BEARER,
            at_time=_NOW,
        )
        assert result.valid is True
        assert result.reason == "valid"

    def test_missing_signature(self) -> None:
        eid, _, _, _, _, asm_sk = self._make_identity()
        unsigned = eid.model_copy(update={"signature": None})
        result = verify_ephemeral_identity(
            unsigned, [_pub_b64(asm_sk)],
            requested_capability=_CAPS[0],
            bearer_sovereign_id=_BEARER,
        )
        assert result.reason == "missing_signature"

    def test_invalid_signature(self) -> None:
        eid, _, _, _, _, asm_sk = self._make_identity()
        wrong_sk = _sk()
        result = verify_ephemeral_identity(
            eid, [_pub_b64(wrong_sk)],
            requested_capability=_CAPS[0],
            bearer_sovereign_id=_BEARER,
        )
        assert result.reason == "invalid_signature"

    def test_bearer_mismatch(self) -> None:
        eid, _, _, _, _, asm_sk = self._make_identity()
        result = verify_ephemeral_identity(
            eid, [_pub_b64(asm_sk)],
            requested_capability=_CAPS[0],
            bearer_sovereign_id="wrong-bearer",
        )
        assert result.reason == "bearer_mismatch"

    def test_capability_not_granted(self) -> None:
        eid, _, _, _, _, asm_sk = self._make_identity()
        result = verify_ephemeral_identity(
            eid, [_pub_b64(asm_sk)],
            requested_capability="not.a.granted.cap",
            bearer_sovereign_id=_BEARER,
        )
        assert result.reason == "capability_not_granted"

    def test_consensus_id_mismatch(self) -> None:
        eid, cp, _, _, _, asm_sk = self._make_identity()
        wrong_cp = cp.model_copy(update={"consensus_id": "wrong-id"})
        result = verify_ephemeral_identity(
            eid, [_pub_b64(asm_sk)],
            requested_capability=_CAPS[0],
            bearer_sovereign_id=_BEARER,
            consensus_proof=wrong_cp,
        )
        assert result.reason == "consensus_id_mismatch"

    def test_expired(self) -> None:
        jp, _, _ = _make_justification_proof()
        v1_sk, v2_sk, v3_sk, asm_sk = _sk(), _sk(), _sk(), _sk()
        cp = _make_consensus_proof(v1_sk, v2_sk, v3_sk, asm_sk, jp)
        # Issue with a past now so the identity is already expired when verified at _NOW
        past = _NOW - timedelta(seconds=300)
        eid = issue_ephemeral_identity(
            cp, _BEARER, _CAPS, asm_sk, issued_by=_ASSEMBLER,
            valid_for_seconds=60, now=past,
        )
        result = verify_ephemeral_identity(
            eid, [_pub_b64(asm_sk)],
            requested_capability=_CAPS[0],
            bearer_sovereign_id=_BEARER,
            at_time=_NOW,
        )
        assert result.reason == "expired"


# ---------------------------------------------------------------------------
# ConsensusGate in BoundaryEngine
# ---------------------------------------------------------------------------


class TestConsensusGate:
    def test_blocks_without_valid_proof(self) -> None:
        agreement, sk = _make_agreement()
        # Build an unsigned / wrong ConsensusProof
        wrong_sk = _sk()
        jp, _, _ = _make_justification_proof()
        v1_sk, v2_sk, v3_sk, asm_sk = _sk(), _sk(), _sk(), _sk()
        cp = _make_consensus_proof(v1_sk, v2_sk, v3_sk, asm_sk, jp)

        # Use the wrong assembler key so the gate fails
        gate = ConsensusGate(cp, {}, [_pub_b64(wrong_sk)])
        engine = BoundaryEngine("operator")
        engine._gates = [gate]  # type: ignore[attr-defined, list-item]

        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id="a",
            provider_sovereign_id="b",
            requested_capability=_CAPS[0],
            context_freshness_seq=0,
            requested_at=_NOW,
        )
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        assert decision.authorized is False

    def test_passes_with_valid_proof(self) -> None:
        agreement, sk = _make_agreement()
        jp, _, _ = _make_justification_proof()
        v1_sk, v2_sk, v3_sk, asm_sk = _sk(), _sk(), _sk(), _sk()
        cp = _make_consensus_proof(v1_sk, v2_sk, v3_sk, asm_sk, jp)

        val_keys = {_V1: _pub_b64(v1_sk), _V2: _pub_b64(v2_sk), _V3: _pub_b64(v3_sk)}
        gate = ConsensusGate(cp, val_keys, [_pub_b64(asm_sk)])
        engine = BoundaryEngine("operator")
        engine._gates = [gate, validity_window_gate]  # type: ignore[attr-defined, list-item]

        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id="a",
            provider_sovereign_id="b",
            requested_capability=_CAPS[0],
            context_freshness_seq=0,
            requested_at=_NOW,
        )
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        assert decision.authorized is True

    def test_normal_engine_unaffected(self) -> None:
        agreement, sk = _make_agreement()
        engine = BoundaryEngine("operator")  # default gates, no consensus

        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id="a",
            provider_sovereign_id="b",
            requested_capability=_CAPS[0],
            context_freshness_seq=0,
            requested_at=_NOW,
        )
        decision = engine.evaluate(ctx, agreement, sk, issued_by="op-key", now=_NOW)
        assert decision.authorized is True


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestConsensusCLI:
    def _make_jp_file(self, tmpdir: str) -> tuple[str, nacl.signing.SigningKey]:
        jp, _, sk = _make_justification_proof()
        jp_path = os.path.join(tmpdir, "proof.json")
        Path(jp_path).write_text(jp.model_dump_json(indent=2), encoding="utf-8")
        return jp_path, sk

    def test_cli_vote(self) -> None:
        runner = CliRunner()
        tmpdir = tempfile.mkdtemp()
        jp_path, _ = self._make_jp_file(tmpdir)
        v_sk = _sk()
        key_path = _write_key(v_sk)
        vote_path = os.path.join(tmpdir, "vote.json")

        result = runner.invoke(trust, [
            "consensus", "vote",
            "--proof", jp_path, "--validator", _V1, "--approve",
            "--signing-key", key_path, "--output", vote_path,
        ])
        assert result.exit_code == 0, result.output
        data = json.loads(Path(vote_path).read_text(encoding="utf-8"))
        assert data["vote"] is True

    def test_cli_assemble_and_verify(self) -> None:
        runner = CliRunner()
        tmpdir = tempfile.mkdtemp()
        jp_path, _ = self._make_jp_file(tmpdir)
        v1_sk, v2_sk, asm_sk = _sk(), _sk(), _sk()
        v1_kp = _write_key(v1_sk)
        v2_kp = _write_key(v2_sk)
        asm_kp = _write_key(asm_sk)
        v1_path = os.path.join(tmpdir, "v1.json")
        v2_path = os.path.join(tmpdir, "v2.json")
        cp_path = os.path.join(tmpdir, "cp.json")

        runner.invoke(trust, [
            "consensus", "vote", "--proof", jp_path, "--validator", _V1,
            "--approve", "--signing-key", v1_kp, "--output", v1_path,
        ])
        runner.invoke(trust, [
            "consensus", "vote", "--proof", jp_path, "--validator", _V2,
            "--approve", "--signing-key", v2_kp, "--output", v2_path,
        ])
        result = runner.invoke(trust, [
            "consensus", "assemble",
            "--proof", jp_path, "--vote", v1_path, "--vote", v2_path,
            "--threshold", "2", "--validators", f"{_V1},{_V2}",
            "--signing-key", asm_kp, "--assembler", _ASSEMBLER,
            "--output", cp_path,
        ])
        assert result.exit_code == 0, result.output

        result = runner.invoke(trust, [
            "consensus", "verify",
            "--consensus", cp_path,
            "--assembler-key", _pub_b64(asm_sk),
            f"--validator-key={_V1}:{_pub_b64(v1_sk)}",
            f"--validator-key={_V2}:{_pub_b64(v2_sk)}",
            "--proof", jp_path,
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output

    def test_cli_issue_identity_and_verify(self) -> None:
        runner = CliRunner()
        tmpdir = tempfile.mkdtemp()
        jp_path, _ = self._make_jp_file(tmpdir)
        v1_sk, v2_sk, asm_sk = _sk(), _sk(), _sk()
        v1_kp = _write_key(v1_sk)
        v2_kp = _write_key(v2_sk)
        asm_kp = _write_key(asm_sk)
        v1_path = os.path.join(tmpdir, "v1.json")
        v2_path = os.path.join(tmpdir, "v2.json")
        cp_path = os.path.join(tmpdir, "cp.json")
        eid_path = os.path.join(tmpdir, "identity.json")

        runner.invoke(trust, [
            "consensus", "vote", "--proof", jp_path, "--validator", _V1,
            "--approve", "--signing-key", v1_kp, "--output", v1_path,
        ])
        runner.invoke(trust, [
            "consensus", "vote", "--proof", jp_path, "--validator", _V2,
            "--approve", "--signing-key", v2_kp, "--output", v2_path,
        ])
        runner.invoke(trust, [
            "consensus", "assemble",
            "--proof", jp_path, "--vote", v1_path, "--vote", v2_path,
            "--threshold", "2", "--validators", f"{_V1},{_V2}",
            "--signing-key", asm_kp, "--assembler", _ASSEMBLER,
            "--output", cp_path,
        ])

        result = runner.invoke(trust, [
            "consensus", "issue-identity",
            "--consensus", cp_path, "--bearer", _BEARER,
            "--cap", _CAPS[0], "--cap", _CAPS[1],
            "--signing-key", asm_kp, "--issuer", _ASSEMBLER,
            "--output", eid_path,
        ])
        assert result.exit_code == 0, result.output

        result = runner.invoke(trust, [
            "consensus", "verify-identity",
            "--identity", eid_path,
            "--issuer-key", _pub_b64(asm_sk),
            "--capability", _CAPS[0],
            "--bearer", _BEARER,
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output
