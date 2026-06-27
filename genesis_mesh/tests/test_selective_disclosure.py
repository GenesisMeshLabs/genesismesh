"""Tests for Selective Disclosure Capability Proofs — Merkle-based membership proofs (v0.35).

Covers:
- commit_capabilities(): deterministic root, single/multi-cap
- prove_capability_membership(): valid proof, cap-not-in-set error
- Merkle path lengths: 1-cap (0), 2-cap (1), 4-cap (2), 8-cap (3), 7-cap padded→8 (3)
- verify_capability_proof(): all 8 verification reason codes
- issue_nullifier()
- SelectiveDisclosureGate in BoundaryEngine: pass / fail
- CLI: commit / prove / verify / nullify
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
from genesis_mesh.models.context import ContextRecord
from genesis_mesh.models.selective_disclosure import (
    CapabilityCommitment,
    CapabilityMembershipProof,
    MerklePathNode,
)
from genesis_mesh.trust.agreement import accept_counter, build_counter, build_offer
from genesis_mesh.trust.context import BoundaryEngine, validity_window_gate
from genesis_mesh.trust.selective_disclosure import (
    SelectiveDisclosureGate,
    _expected_path_length,
    _recompute_root,
    commit_capabilities,
    issue_nullifier,
    prove_capability_membership,
    verify_capability_proof,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)
_CAPS = ["transactions.send", "balances.read", "config.write", "audit.read"]


def _signing_key() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()


def _pub_b64(sk: nacl.signing.SigningKey) -> str:
    return base64.b64encode(bytes(sk.verify_key)).decode()


def _write_key(sk: nacl.signing.SigningKey) -> str:
    fd, path = tempfile.mkstemp(suffix=".key")
    os.close(fd)
    Path(path).write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
    return path


def _make_agreement(caps: list[str] | None = None) -> tuple[AgreementRecord, nacl.signing.SigningKey]:
    kp1 = generate_keypair()
    kp2 = generate_keypair()
    now = _NOW
    terms = AgreementTerms(
        capabilities=caps or _CAPS,
        scope={},
        valid_from=now,
        valid_until=now + timedelta(days=30),
        freshness_commitment=0,
    )
    graph = {
        "sovereigns": [{"sovereign_id": "a"}, {"sovereign_id": "b"}],
        "recognition_edges": [
            {
                "from": "a", "to": "b", "treaty_id": "t-ab", "status": "active",
                "lifecycle_state": "active", "expiry_risk": "low",
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
            },
            {
                "from": "b", "to": "a", "treaty_id": "t-ba", "status": "active",
                "lifecycle_state": "active", "expiry_risk": "low",
                "valid_from": now.isoformat(),
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


def _make_commitment(caps: list[str] | None = None,
                     sk: nacl.signing.SigningKey | None = None
                     ) -> tuple[CapabilityCommitment, nacl.signing.SigningKey, AgreementRecord]:
    agreement, agr_sk = _make_agreement(caps)
    sk = sk or agr_sk
    commitment = commit_capabilities(
        capabilities=list(agreement.agreed_terms.capabilities),
        agreement=agreement,
        signing_key=sk,
        issued_by="issuer",
        now=_NOW,
    )
    return commitment, sk, agreement


# ---------------------------------------------------------------------------
# commit_capabilities
# ---------------------------------------------------------------------------


class TestCommitCapabilities:
    def test_single_capability_root_is_leaf(self) -> None:
        agreement, sk = _make_agreement(caps=["transactions.send"])
        commitment = commit_capabilities(["transactions.send"], agreement, sk, issued_by="issuer")
        expected_leaf = hashlib.sha256("transactions.send".encode()).hexdigest()
        assert commitment.merkle_root == expected_leaf

    def test_root_is_deterministic(self) -> None:
        agreement, sk = _make_agreement()
        c1 = commit_capabilities(_CAPS, agreement, sk, issued_by="issuer", now=_NOW)
        c2 = commit_capabilities(list(reversed(_CAPS)), agreement, sk, issued_by="issuer", now=_NOW)
        assert c1.merkle_root == c2.merkle_root

    def test_different_caps_produce_different_roots(self) -> None:
        agreement, sk = _make_agreement()
        c1 = commit_capabilities(_CAPS, agreement, sk, issued_by="issuer", now=_NOW)
        c2 = commit_capabilities(["other.cap"], agreement, sk, issued_by="issuer", now=_NOW)
        assert c1.merkle_root != c2.merkle_root

    def test_commitment_is_signed(self) -> None:
        commitment, _, _ = _make_commitment()
        assert commitment.signature is not None

    def test_capability_count_correct(self) -> None:
        commitment, _, _ = _make_commitment()
        assert commitment.capability_count == len(_CAPS)

    def test_empty_caps_raises(self) -> None:
        agreement, sk = _make_agreement(caps=["placeholder"])
        with pytest.raises(ValueError, match="empty"):
            commit_capabilities([], agreement, sk, issued_by="issuer")


# ---------------------------------------------------------------------------
# Merkle path lengths
# ---------------------------------------------------------------------------


class TestPathLengths:
    def _path_len_for_n(self, n: int) -> int:
        caps = [f"cap.{i}" for i in range(n)]
        agreement, sk = _make_agreement(caps=caps)
        commitment = commit_capabilities(caps, agreement, sk, issued_by="issuer", now=_NOW)
        proof = prove_capability_membership(caps[0], caps, commitment, "prover", now=_NOW)
        return len(proof.merkle_path)

    def test_1_cap_path_length_0(self) -> None:
        assert self._path_len_for_n(1) == 0

    def test_2_caps_path_length_1(self) -> None:
        assert self._path_len_for_n(2) == 1

    def test_4_caps_path_length_2(self) -> None:
        assert self._path_len_for_n(4) == 2

    def test_8_caps_path_length_3(self) -> None:
        assert self._path_len_for_n(8) == 3

    def test_7_caps_padded_to_8_path_length_3(self) -> None:
        assert self._path_len_for_n(7) == 3

    def test_expected_path_length_formula(self) -> None:
        assert _expected_path_length(1) == 0
        assert _expected_path_length(2) == 1
        assert _expected_path_length(3) == 2
        assert _expected_path_length(4) == 2
        assert _expected_path_length(5) == 3
        assert _expected_path_length(8) == 3


# ---------------------------------------------------------------------------
# prove_capability_membership
# ---------------------------------------------------------------------------


class TestProveMembership:
    def test_valid_proof_for_each_cap(self) -> None:
        commitment, sk, agreement = _make_commitment()
        caps = list(agreement.agreed_terms.capabilities)
        for cap in caps:
            proof = prove_capability_membership(cap, caps, commitment, "prover", now=_NOW)
            assert proof.revealed_capability == cap
            assert proof.leaf_hash == hashlib.sha256(cap.encode()).hexdigest()

    def test_cap_not_in_set_raises(self) -> None:
        commitment, _, agreement = _make_commitment()
        caps = list(agreement.agreed_terms.capabilities)
        with pytest.raises(ValueError, match="not in the capability set"):
            prove_capability_membership("nonexistent.cap", caps, commitment, "prover")

    def test_proof_verifies_correctly(self) -> None:
        commitment, sk, agreement = _make_commitment()
        caps = list(agreement.agreed_terms.capabilities)
        proof = prove_capability_membership(caps[0], caps, commitment, "prover", now=_NOW)
        recomputed = _recompute_root(proof.leaf_hash, proof.merkle_path)
        assert recomputed == commitment.merkle_root


# ---------------------------------------------------------------------------
# verify_capability_proof — all 8 reason codes
# ---------------------------------------------------------------------------


class TestVerifyCapabilityProof:
    def _make_proof_and_commitment(
        self, caps: list[str] | None = None
    ) -> tuple[CapabilityMembershipProof, CapabilityCommitment, nacl.signing.SigningKey]:
        cap_list = caps or _CAPS
        commitment, sk, agreement = _make_commitment(cap_list)
        proof = prove_capability_membership(
            cap_list[0], cap_list, commitment, "prover", now=_NOW
        )
        return proof, commitment, sk

    def test_valid(self) -> None:
        proof, commitment, sk = self._make_proof_and_commitment()
        result = verify_capability_proof(proof, commitment, [_pub_b64(sk)])
        assert result.valid is True
        assert result.reason == "valid"

    def test_commitment_not_signed(self) -> None:
        proof, commitment, sk = self._make_proof_and_commitment()
        unsigned = commitment.model_copy(update={"signature": None})
        result = verify_capability_proof(proof, unsigned, [_pub_b64(sk)])
        assert result.valid is False
        assert result.reason == "commitment_not_signed"

    def test_commitment_invalid_signature(self) -> None:
        proof, commitment, sk = self._make_proof_and_commitment()
        wrong_sk = _signing_key()
        result = verify_capability_proof(proof, commitment, [_pub_b64(wrong_sk)])
        assert result.valid is False
        assert result.reason == "commitment_invalid_signature"

    def test_path_length_inconsistent(self) -> None:
        proof, commitment, sk = self._make_proof_and_commitment()
        # Tamper: strip one path node, making the path too short
        short_path = proof.merkle_path[:-1]
        tampered_proof = proof.model_copy(update={"merkle_path": short_path})
        result = verify_capability_proof(tampered_proof, commitment, [_pub_b64(sk)])
        assert result.valid is False
        assert result.reason == "path_length_inconsistent"

    def test_leaf_hash_mismatch(self) -> None:
        proof, commitment, sk = self._make_proof_and_commitment()
        tampered = proof.model_copy(update={
            "revealed_capability": _CAPS[1],  # different cap, but leaf_hash unchanged
        })
        result = verify_capability_proof(tampered, commitment, [_pub_b64(sk)])
        assert result.valid is False
        assert result.reason == "leaf_hash_mismatch"

    def test_root_mismatch(self) -> None:
        proof, commitment, sk = self._make_proof_and_commitment()
        # Tamper a sibling hash in the path so root recomputation fails
        bad_node = MerklePathNode(sibling_hash="0" * 64, is_left=proof.merkle_path[0].is_left)
        tampered_path = [bad_node] + list(proof.merkle_path[1:])
        tampered_proof = proof.model_copy(update={"merkle_path": tampered_path})
        result = verify_capability_proof(tampered_proof, commitment, [_pub_b64(sk)])
        assert result.valid is False
        assert result.reason == "root_mismatch"

    def test_nullifier_expired(self) -> None:
        from datetime import datetime, timezone

        proof, commitment, sk = self._make_proof_and_commitment()
        real_now = datetime.now(timezone.utc)
        # Set expires_at to a moment already in the past
        expired_nullifier = issue_nullifier(
            proof, sk, issued_by="prover", valid_for_seconds=0, now=real_now
        )
        expired_nullifier = expired_nullifier.model_copy(
            update={"expires_at": real_now - timedelta(seconds=1)}
        )
        result = verify_capability_proof(
            proof, commitment, [_pub_b64(sk)], nullifier=expired_nullifier,
        )
        assert result.valid is False
        assert result.reason == "nullifier_expired"

    def test_nullifier_already_used(self) -> None:
        proof, commitment, sk = self._make_proof_and_commitment()
        nullifier = issue_nullifier(proof, sk, issued_by="prover", valid_for_seconds=3600, now=_NOW)
        used = {nullifier.nullifier_id}
        result = verify_capability_proof(
            proof, commitment, [_pub_b64(sk)],
            nullifier=nullifier, used_nullifiers=used,
        )
        assert result.valid is False
        assert result.reason == "nullifier_already_used"


# ---------------------------------------------------------------------------
# Single-capability edge case
# ---------------------------------------------------------------------------


class TestSingleCapEdgeCase:
    def test_single_cap_verify_valid(self) -> None:
        caps = ["single.cap"]
        agreement, sk = _make_agreement(caps=caps)
        commitment = commit_capabilities(caps, agreement, sk, issued_by="issuer", now=_NOW)
        proof = prove_capability_membership(caps[0], caps, commitment, "prover", now=_NOW)
        assert len(proof.merkle_path) == 0
        result = verify_capability_proof(proof, commitment, [_pub_b64(sk)])
        assert result.valid is True

    def test_single_cap_root_recomputes(self) -> None:
        caps = ["single.cap"]
        agreement, sk = _make_agreement(caps=caps)
        commitment = commit_capabilities(caps, agreement, sk, issued_by="issuer", now=_NOW)
        proof = prove_capability_membership(caps[0], caps, commitment, "prover", now=_NOW)
        # With empty path, recomputed root == leaf hash
        assert _recompute_root(proof.leaf_hash, proof.merkle_path) == commitment.merkle_root


# ---------------------------------------------------------------------------
# SelectiveDisclosureGate
# ---------------------------------------------------------------------------


class TestSelectiveDisclosureGate:
    def test_valid_proof_passes(self) -> None:
        commitment, sk, agreement = _make_commitment(_CAPS)
        proof = prove_capability_membership(_CAPS[0], _CAPS, commitment, "prover", now=_NOW)
        gate = SelectiveDisclosureGate(commitment, proof, [_pub_b64(sk)])

        engine = BoundaryEngine("operator")
        # Replace standard gates: selective_disclosure + validity_window only
        engine._gates = [gate, validity_window_gate]  # type: ignore[attr-defined]

        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id=agreement.offerer_sovereign_id,
            provider_sovereign_id=agreement.responder_sovereign_id,
            requested_capability=_CAPS[0],
            context_freshness_seq=0,
            requested_at=_NOW,
        )
        decision = engine.evaluate(ctx, agreement, sk, issued_by="operator")
        assert decision.authorized is True

    def test_invalid_proof_fails(self) -> None:
        commitment, sk, agreement = _make_commitment(_CAPS)
        # Proof is for _CAPS[0], but request is for _CAPS[1]
        proof = prove_capability_membership(_CAPS[0], _CAPS, commitment, "prover", now=_NOW)
        gate = SelectiveDisclosureGate(commitment, proof, [_pub_b64(sk)])

        engine = BoundaryEngine("operator")
        engine._gates = [gate]  # type: ignore[attr-defined]

        ctx = ContextRecord(
            agreement_id=agreement.agreement_id,
            requester_sovereign_id=agreement.offerer_sovereign_id,
            provider_sovereign_id=agreement.responder_sovereign_id,
            requested_capability=_CAPS[1],  # mismatch with disclosed cap
            context_freshness_seq=0,
            requested_at=_NOW,
        )
        decision = engine.evaluate(ctx, agreement, sk, issued_by="operator")
        assert decision.authorized is False


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestDiscloseCLI:
    def _setup(
        self,
    ) -> tuple[CliRunner, str, str, nacl.signing.SigningKey]:
        runner = CliRunner()
        tmpdir = tempfile.mkdtemp()
        sk = _signing_key()
        agreement, agr_sk = _make_agreement()

        agreement_path = os.path.join(tmpdir, "agreement.json")
        key_path = _write_key(sk)

        Path(agreement_path).write_text(
            agreement.model_dump_json(indent=2), encoding="utf-8"
        )
        return runner, agreement_path, key_path, sk

    def test_cli_commit(self) -> None:
        runner, agreement_path, key_path, sk = self._setup()
        tmpdir = tempfile.mkdtemp()
        commitment_path = os.path.join(tmpdir, "commitment.json")

        result = runner.invoke(trust, [
            "disclose", "commit",
            "--agreement", agreement_path,
            "--signing-key", key_path,
            "--issuer", "test-issuer",
            "--output", commitment_path,
        ])
        assert result.exit_code == 0, result.output
        data = json.loads(Path(commitment_path).read_text(encoding="utf-8"))
        assert "merkle_root" in data
        assert data["capability_count"] == len(_CAPS)

    def test_cli_prove(self) -> None:
        runner, agreement_path, key_path, sk = self._setup()
        tmpdir = tempfile.mkdtemp()
        commitment_path = os.path.join(tmpdir, "commitment.json")
        proof_path = os.path.join(tmpdir, "proof.json")

        runner.invoke(trust, [
            "disclose", "commit",
            "--agreement", agreement_path, "--signing-key", key_path,
            "--issuer", "issuer", "--output", commitment_path,
        ])
        result = runner.invoke(trust, [
            "disclose", "prove",
            "--capability", _CAPS[0],
            "--agreement", agreement_path,
            "--commitment", commitment_path,
            "--prover", "agent-b",
            "--output", proof_path,
        ])
        assert result.exit_code == 0, result.output
        data = json.loads(Path(proof_path).read_text(encoding="utf-8"))
        assert data["revealed_capability"] == _CAPS[0]

    def test_cli_verify(self) -> None:
        runner, agreement_path, key_path, sk = self._setup()
        tmpdir = tempfile.mkdtemp()
        commitment_path = os.path.join(tmpdir, "commitment.json")
        proof_path = os.path.join(tmpdir, "proof.json")

        runner.invoke(trust, [
            "disclose", "commit",
            "--agreement", agreement_path, "--signing-key", key_path,
            "--issuer", "issuer", "--output", commitment_path,
        ])
        runner.invoke(trust, [
            "disclose", "prove",
            "--capability", _CAPS[0],
            "--agreement", agreement_path, "--commitment", commitment_path,
            "--prover", "agent-b", "--output", proof_path,
        ])
        result = runner.invoke(trust, [
            "disclose", "verify",
            "--proof", proof_path,
            "--commitment", commitment_path,
            "--verify-key", _pub_b64(sk),
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output

    def test_cli_verify_json_format(self) -> None:
        runner, agreement_path, key_path, sk = self._setup()
        tmpdir = tempfile.mkdtemp()
        commitment_path = os.path.join(tmpdir, "commitment.json")
        proof_path = os.path.join(tmpdir, "proof.json")

        runner.invoke(trust, [
            "disclose", "commit",
            "--agreement", agreement_path, "--signing-key", key_path,
            "--issuer", "issuer", "--output", commitment_path,
        ])
        runner.invoke(trust, [
            "disclose", "prove",
            "--capability", _CAPS[0],
            "--agreement", agreement_path, "--commitment", commitment_path,
            "--prover", "agent-b", "--output", proof_path,
        ])
        result = runner.invoke(trust, [
            "disclose", "verify",
            "--proof", proof_path, "--commitment", commitment_path,
            "--verify-key", _pub_b64(sk), "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["valid"] is True
        assert data["reason"] == "valid"

    def test_cli_nullify(self) -> None:
        runner, agreement_path, key_path, sk = self._setup()
        tmpdir = tempfile.mkdtemp()
        commitment_path = os.path.join(tmpdir, "commitment.json")
        proof_path = os.path.join(tmpdir, "proof.json")
        nullifier_path = os.path.join(tmpdir, "nullifier.json")

        runner.invoke(trust, [
            "disclose", "commit",
            "--agreement", agreement_path, "--signing-key", key_path,
            "--issuer", "issuer", "--output", commitment_path,
        ])
        runner.invoke(trust, [
            "disclose", "prove",
            "--capability", _CAPS[0],
            "--agreement", agreement_path, "--commitment", commitment_path,
            "--prover", "agent-b", "--output", proof_path,
        ])
        result = runner.invoke(trust, [
            "disclose", "nullify",
            "--proof", proof_path,
            "--signing-key", key_path,
            "--prover", "agent-b",
            "--output", nullifier_path,
        ])
        assert result.exit_code == 0, result.output
        data = json.loads(Path(nullifier_path).read_text(encoding="utf-8"))
        assert "nullifier_id" in data
        assert "nonce" in data
