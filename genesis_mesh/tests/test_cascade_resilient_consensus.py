"""Tests for Cascade-Resilient Consensus (v0.38).

Covers:
- assess_cascade_risk(): CDS + TCS + CascadeScore calculations
- Independent votes (all unique digests) -> independent
- Identical context digests -> cascade_detected
- Majority identical -> cascade_detected
- Tight temporal window -> high TCS
- Spread temporal window -> low TCS
- Configurable weights
- cascade_threshold=0.0 always passes (disabled)
- assemble_consensus_proof() blocks when cascade detected
- assemble_consensus_proof() succeeds when independent
- verify_consensus_proof() returns missing_context_digest / cascade_detected
- CLI: assess-cascade exit 0 / exit 1
"""

from __future__ import annotations

import base64
import hashlib
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
from genesis_mesh.models.consensus import CascadeAssessment, ConsensusProof, ValidatorVote
from genesis_mesh.models.context import ContextRecord
from genesis_mesh.models.justification import JustificationProof
from genesis_mesh.trust.agreement import accept_counter, build_counter, build_offer
from genesis_mesh.trust.consensus import (
    assess_cascade_risk,
    assemble_consensus_proof,
    cast_validator_vote,
    verify_consensus_proof,
)
from genesis_mesh.trust.context import BoundaryEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
_CAPS = ["transfers.send"]
_V1 = "validator-1"
_V2 = "validator-2"
_V3 = "validator-3"
_ASSEMBLER = "assembler-sovereign"


def _sk() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()


def _pub_b64(sk: nacl.signing.SigningKey) -> str:
    return base64.b64encode(bytes(sk.verify_key)).decode()


def _write_key(sk: nacl.signing.SigningKey) -> str:
    fd, path = tempfile.mkstemp(suffix=".key")
    os.close(fd)
    Path(path).write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
    return path


def _write_json(obj: object) -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    if hasattr(obj, "model_dump_json"):
        Path(path).write_text(obj.model_dump_json(indent=2), encoding="utf-8")  # type: ignore[union-attr]
    else:
        Path(path).write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return path


def _make_justification_proof() -> tuple[JustificationProof, nacl.signing.SigningKey]:
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
    engine = BoundaryEngine("operator", decision_valid_seconds=3600)
    ctx = ContextRecord(
        agreement_id=agreement.agreement_id,
        requester_sovereign_id="a",
        provider_sovereign_id="b",
        requested_capability=_CAPS[0],
        context_freshness_seq=0,
        requested_at=now,
    )
    _, proof = engine.evaluate_with_proof(ctx, agreement, kp1.private_key, issued_by="op-key", now=now)
    return proof, kp1.private_key


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _make_vote(
    jp: JustificationProof,
    validator_id: str,
    sk: nacl.signing.SigningKey,
    approve: bool = True,
    context_digest: str | None = None,
    voted_at: datetime | None = None,
) -> ValidatorVote:
    vote = cast_validator_vote(
        jp, validator_id, approve, sk,
        context_digest=context_digest,
        now=voted_at or _NOW,
    )
    return vote


# ---------------------------------------------------------------------------
# TestAssessCascadeRisk
# ---------------------------------------------------------------------------


class TestAssessCascadeRisk:
    def test_all_unique_digests_independent(self) -> None:
        jp, _ = _make_justification_proof()
        v1_sk, v2_sk, v3_sk = _sk(), _sk(), _sk()
        t0 = _NOW
        # Spread timestamps to keep TCS low
        votes = [
            _make_vote(jp, _V1, v1_sk, context_digest=_digest("unique-A"),
                       voted_at=t0),
            _make_vote(jp, _V2, v2_sk, context_digest=_digest("unique-B"),
                       voted_at=t0 + timedelta(seconds=30)),
            _make_vote(jp, _V3, v3_sk, context_digest=_digest("unique-C"),
                       voted_at=t0 + timedelta(seconds=60)),
        ]
        assessment, reason = assess_cascade_risk(votes, now=_NOW)
        assert reason == "independent"
        assert not assessment.blocked
        assert assessment.unique_context_count == 3
        # CDS = (1-1)/(3-1) = 0.0 when all digests unique
        assert assessment.context_divergence_score == pytest.approx(0.0, abs=0.01)

    def test_all_identical_digests_cascade_detected(self) -> None:
        jp, _ = _make_justification_proof()
        shared_digest = _digest("shared-context")
        v1_sk, v2_sk, v3_sk = _sk(), _sk(), _sk()
        t0 = _NOW
        votes = [
            _make_vote(jp, _V1, v1_sk, context_digest=shared_digest, voted_at=t0),
            _make_vote(jp, _V2, v2_sk, context_digest=shared_digest,
                       voted_at=t0 + timedelta(seconds=1)),
            _make_vote(jp, _V3, v3_sk, context_digest=shared_digest,
                       voted_at=t0 + timedelta(seconds=2)),
        ]
        assessment, reason = assess_cascade_risk(
            votes, cascade_threshold=0.4, expected_deliberation_seconds=30.0, now=_NOW
        )
        assert reason == "cascade_detected"
        assert assessment.blocked
        assert assessment.context_divergence_score == pytest.approx(1.0, abs=0.01)

    def test_majority_identical_cascade_detected(self) -> None:
        jp, _ = _make_justification_proof()
        shared = _digest("shared")
        v1_sk, v2_sk, v3_sk = _sk(), _sk(), _sk()
        t0 = _NOW
        votes = [
            _make_vote(jp, _V1, v1_sk, context_digest=shared, voted_at=t0),
            _make_vote(jp, _V2, v2_sk, context_digest=shared,
                       voted_at=t0 + timedelta(seconds=1)),
            _make_vote(jp, _V3, v3_sk, context_digest=_digest("unique"),
                       voted_at=t0 + timedelta(seconds=60)),
        ]
        # CDS = (2-1)/(3-1) = 0.5 -> cascade_score = 0.5 > 0.4
        assessment, reason = assess_cascade_risk(
            votes, cascade_threshold=0.4, cds_weight=1.0, tcs_weight=0.0, now=_NOW
        )
        assert reason == "cascade_detected"
        assert assessment.context_divergence_score == pytest.approx(0.5, abs=0.01)

    def test_tight_temporal_window_raises_tcs(self) -> None:
        jp, _ = _make_justification_proof()
        v1_sk, v2_sk = _sk(), _sk()
        t0 = _NOW
        votes = [
            _make_vote(jp, _V1, v1_sk, context_digest=_digest("A"), voted_at=t0),
            _make_vote(jp, _V2, v2_sk, context_digest=_digest("B"),
                       voted_at=t0 + timedelta(seconds=0.1)),
        ]
        assessment, _ = assess_cascade_risk(
            votes, cascade_threshold=0.9, cds_weight=0.0, tcs_weight=1.0,
            expected_deliberation_seconds=30.0, now=_NOW,
        )
        assert assessment.temporal_clustering_score > 0.9

    def test_spread_temporal_window_low_tcs(self) -> None:
        jp, _ = _make_justification_proof()
        v1_sk, v2_sk, v3_sk = _sk(), _sk(), _sk()
        t0 = _NOW
        votes = [
            _make_vote(jp, _V1, v1_sk, context_digest=_digest("A"), voted_at=t0),
            _make_vote(jp, _V2, v2_sk, context_digest=_digest("B"),
                       voted_at=t0 + timedelta(seconds=30)),
            _make_vote(jp, _V3, v3_sk, context_digest=_digest("C"),
                       voted_at=t0 + timedelta(seconds=60)),
        ]
        assessment, reason = assess_cascade_risk(
            votes, cascade_threshold=0.4, cds_weight=0.0, tcs_weight=1.0,
            expected_deliberation_seconds=30.0, now=_NOW,
        )
        assert assessment.temporal_clustering_score < 0.4
        assert reason == "independent"

    def test_cds_weight_1_disables_tcs(self) -> None:
        jp, _ = _make_justification_proof()
        v1_sk, v2_sk, v3_sk = _sk(), _sk(), _sk()
        t0 = _NOW
        shared = _digest("shared")
        votes = [
            _make_vote(jp, _V1, v1_sk, context_digest=shared, voted_at=t0),
            _make_vote(jp, _V2, v2_sk, context_digest=shared,
                       voted_at=t0 + timedelta(seconds=0.001)),
            _make_vote(jp, _V3, v3_sk, context_digest=_digest("unique"),
                       voted_at=t0 + timedelta(seconds=60)),
        ]
        assessment, reason = assess_cascade_risk(
            votes, cascade_threshold=0.4, cds_weight=1.0, tcs_weight=0.0,
            expected_deliberation_seconds=30.0, now=_NOW,
        )
        # CDS = (2-1)/(3-1) = 0.5 (majority shared), TCS weight = 0 -> cascade_score = 0.5 > 0.4
        assert reason == "cascade_detected"

    def test_cascade_threshold_zero_always_independent(self) -> None:
        jp, _ = _make_justification_proof()
        shared = _digest("all-same")
        v1_sk, v2_sk, v3_sk = _sk(), _sk(), _sk()
        t0 = _NOW
        votes = [
            _make_vote(jp, _V1, v1_sk, context_digest=shared, voted_at=t0),
            _make_vote(jp, _V2, v2_sk, context_digest=shared, voted_at=t0),
            _make_vote(jp, _V3, v3_sk, context_digest=shared, voted_at=t0),
        ]
        assessment, reason = assess_cascade_risk(votes, cascade_threshold=0.0, now=_NOW)
        assert not assessment.blocked

    def test_empty_votes_independent(self) -> None:
        assessment, reason = assess_cascade_risk([], now=_NOW)
        assert reason == "independent"
        assert not assessment.blocked

    def test_single_approve_vote_insufficient_temporal_data(self) -> None:
        jp, _ = _make_justification_proof()
        v1_sk = _sk()
        votes = [_make_vote(jp, _V1, v1_sk, context_digest=_digest("A"))]
        assessment, reason = assess_cascade_risk(votes, cascade_threshold=0.9, now=_NOW)
        assert reason in ("independent", "insufficient_temporal_data")
        assert not assessment.blocked

    def test_only_reject_votes_no_cascade(self) -> None:
        jp, _ = _make_justification_proof()
        v1_sk, v2_sk = _sk(), _sk()
        shared = _digest("same")
        votes = [
            _make_vote(jp, _V1, v1_sk, approve=False, context_digest=shared),
            _make_vote(jp, _V2, v2_sk, approve=False, context_digest=shared),
        ]
        assessment, reason = assess_cascade_risk(votes, now=_NOW)
        assert reason == "independent"
        assert assessment.approve_vote_count == 0


# ---------------------------------------------------------------------------
# TestAssembleConsensusProof (cascade integration)
# ---------------------------------------------------------------------------


class TestAssembleWithCascade:
    def test_blocks_when_cascade_detected(self) -> None:
        jp, _ = _make_justification_proof()
        shared = _digest("shared-context")
        v1_sk, v2_sk, v3_sk = _sk(), _sk(), _sk()
        asm_sk = _sk()
        t0 = _NOW
        votes = [
            _make_vote(jp, _V1, v1_sk, context_digest=shared, voted_at=t0),
            _make_vote(jp, _V2, v2_sk, context_digest=shared,
                       voted_at=t0 + timedelta(seconds=1)),
            _make_vote(jp, _V3, v3_sk, context_digest=shared,
                       voted_at=t0 + timedelta(seconds=2)),
        ]
        with pytest.raises(ValueError, match="cascade_detected"):
            assemble_consensus_proof(
                jp, votes, 2, [_V1, _V2, _V3], asm_sk,
                issued_by=_ASSEMBLER, cascade_threshold=0.4, now=_NOW,
            )

    def test_succeeds_when_independent(self) -> None:
        jp, _ = _make_justification_proof()
        v1_sk, v2_sk, v3_sk = _sk(), _sk(), _sk()
        asm_sk = _sk()
        t0 = _NOW
        votes = [
            _make_vote(jp, _V1, v1_sk, context_digest=_digest("A"),
                       voted_at=t0),
            _make_vote(jp, _V2, v2_sk, context_digest=_digest("B"),
                       voted_at=t0 + timedelta(seconds=30)),
            _make_vote(jp, _V3, v3_sk, context_digest=_digest("C"),
                       voted_at=t0 + timedelta(seconds=60)),
        ]
        cp = assemble_consensus_proof(
            jp, votes, 2, [_V1, _V2, _V3], asm_sk,
            issued_by=_ASSEMBLER, cascade_threshold=0.4, now=_NOW,
        )
        assert cp.cascade_assessment_digest is not None

    def test_cascade_disabled_allows_correlated_votes(self) -> None:
        jp, _ = _make_justification_proof()
        shared = _digest("shared")
        v1_sk, v2_sk = _sk(), _sk()
        asm_sk = _sk()
        votes = [
            _make_vote(jp, _V1, v1_sk, context_digest=shared),
            _make_vote(jp, _V2, v2_sk, context_digest=shared),
        ]
        cp = assemble_consensus_proof(
            jp, votes, 2, [_V1, _V2], asm_sk,
            issued_by=_ASSEMBLER, cascade_threshold=0.0, now=_NOW,
        )
        assert cp is not None


# ---------------------------------------------------------------------------
# TestVerifyConsensusProof (cascade codes)
# ---------------------------------------------------------------------------


class TestVerifyConsensusProofCascade:
    def _make_clean_proof(
        self, jp: JustificationProof
    ) -> tuple[ConsensusProof, nacl.signing.SigningKey, dict[str, str]]:
        v1_sk, v2_sk, v3_sk = _sk(), _sk(), _sk()
        asm_sk = _sk()
        t0 = _NOW
        votes = [
            _make_vote(jp, _V1, v1_sk, context_digest=_digest("A"),
                       voted_at=t0),
            _make_vote(jp, _V2, v2_sk, context_digest=_digest("B"),
                       voted_at=t0 + timedelta(seconds=30)),
            _make_vote(jp, _V3, v3_sk, context_digest=_digest("C"),
                       voted_at=t0 + timedelta(seconds=60)),
        ]
        cp = assemble_consensus_proof(
            jp, votes, 2, [_V1, _V2, _V3], asm_sk,
            issued_by=_ASSEMBLER, cascade_threshold=0.4, now=_NOW,
        )
        val_keys = {
            _V1: _pub_b64(v1_sk),
            _V2: _pub_b64(v2_sk),
            _V3: _pub_b64(v3_sk),
        }
        return cp, asm_sk, val_keys

    def test_valid_proof_passes(self) -> None:
        jp, _ = _make_justification_proof()
        cp, asm_sk, val_keys = self._make_clean_proof(jp)
        result = verify_consensus_proof(
            cp, val_keys, [_pub_b64(asm_sk)],
            cascade_threshold=0.4, at_time=_NOW,
        )
        assert result.valid
        assert result.reason == "valid"

    def test_missing_context_digest_rejected(self) -> None:
        jp, _ = _make_justification_proof()
        v1_sk, v2_sk = _sk(), _sk()
        asm_sk = _sk()
        # Create votes without context_digest (pre-v0.38 style)
        v1 = ValidatorVote(
            proof_id=jp.proof_id, decision_id=jp.decision_id,
            validator_sovereign_id=_V1, vote=True,
            voted_at=_NOW, context_digest=None,
        )
        v2 = ValidatorVote(
            proof_id=jp.proof_id, decision_id=jp.decision_id,
            validator_sovereign_id=_V2, vote=True,
            voted_at=_NOW, context_digest=None,
        )
        # Assemble with cascade disabled so we can get a proof
        cp = assemble_consensus_proof(
            jp, [v1, v2], 2, [_V1, _V2], asm_sk,
            issued_by=_ASSEMBLER, cascade_threshold=0.0, now=_NOW,
        )
        result = verify_consensus_proof(
            cp, {}, [_pub_b64(asm_sk)],
            cascade_threshold=0.4, at_time=_NOW,
        )
        assert not result.valid
        assert result.reason == "missing_context_digest"

    def test_correlated_votes_in_proof_returns_cascade_detected(self) -> None:
        jp, _ = _make_justification_proof()
        shared = _digest("same")
        v1_sk, v2_sk = _sk(), _sk()
        asm_sk = _sk()
        t0 = _NOW
        votes = [
            _make_vote(jp, _V1, v1_sk, context_digest=shared, voted_at=t0),
            _make_vote(jp, _V2, v2_sk, context_digest=shared,
                       voted_at=t0 + timedelta(seconds=1)),
        ]
        # Bypass assembly cascade check to create a "tampered" proof
        cp = assemble_consensus_proof(
            jp, votes, 2, [_V1, _V2], asm_sk,
            issued_by=_ASSEMBLER, cascade_threshold=0.0, now=_NOW,
        )
        # Now verify with strict threshold
        result = verify_consensus_proof(
            cp, {_V1: _pub_b64(v1_sk), _V2: _pub_b64(v2_sk)}, [_pub_b64(asm_sk)],
            cascade_threshold=0.4, at_time=_NOW,
        )
        assert not result.valid
        assert result.reason == "cascade_detected"

    def test_cascade_threshold_zero_skips_cascade_check(self) -> None:
        jp, _ = _make_justification_proof()
        shared = _digest("same")
        v1_sk, v2_sk = _sk(), _sk()
        asm_sk = _sk()
        votes = [
            _make_vote(jp, _V1, v1_sk, context_digest=shared),
            _make_vote(jp, _V2, v2_sk, context_digest=shared),
        ]
        cp = assemble_consensus_proof(
            jp, votes, 2, [_V1, _V2], asm_sk,
            issued_by=_ASSEMBLER, cascade_threshold=0.0, now=_NOW,
        )
        result = verify_consensus_proof(
            cp, {}, [_pub_b64(asm_sk)],
            cascade_threshold=0.0, at_time=_NOW,
        )
        assert result.valid


# ---------------------------------------------------------------------------
# TestCLIAssessCascade
# ---------------------------------------------------------------------------


class TestCLIAssessCascade:
    def _make_vote_files(
        self,
        jp: JustificationProof,
        digests: list[str],
        offsets_seconds: list[float],
    ) -> list[str]:
        paths = []
        sks = [_sk() for _ in digests]
        vids = [f"validator-{i}" for i in range(len(digests))]
        for i, (d, offset) in enumerate(zip(digests, offsets_seconds)):
            vote = _make_vote(
                jp, vids[i], sks[i],
                context_digest=d,
                voted_at=_NOW + timedelta(seconds=offset),
            )
            paths.append(_write_json(vote))
        return paths

    def test_independent_votes_exit_0(self) -> None:
        jp, _ = _make_justification_proof()
        paths = self._make_vote_files(
            jp,
            [_digest("A"), _digest("B"), _digest("C")],
            [0, 30, 60],
        )
        runner = CliRunner()
        args = ["consensus", "assess-cascade"] + [f"--vote={p}" for p in paths]
        result = runner.invoke(trust, args)
        assert result.exit_code == 0

    def test_cascade_detected_exit_1(self) -> None:
        jp, _ = _make_justification_proof()
        shared = _digest("same")
        paths = self._make_vote_files(
            jp,
            [shared, shared, shared],
            [0, 1, 2],
        )
        runner = CliRunner()
        args = ["consensus", "assess-cascade"] + [f"--vote={p}" for p in paths]
        result = runner.invoke(trust, args)
        assert result.exit_code == 1

    def test_json_format_output(self) -> None:
        jp, _ = _make_justification_proof()
        paths = self._make_vote_files(
            jp,
            [_digest("A"), _digest("B")],
            [0, 30],
        )
        runner = CliRunner()
        args = ["consensus", "assess-cascade", "--format=json"] + [f"--vote={p}" for p in paths]
        result = runner.invoke(trust, args)
        data = json.loads(result.output)
        assert "cascade_score" in data
        assert "context_divergence_score" in data
        assert "blocked" in data
