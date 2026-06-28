"""Tests for Ephemeral Identity Purge Protocol (v0.42).

Covers:
- create_nullification_receipt(): digest, sensitive field exclusion, expiry check
- build_nullification_registry(): Merkle root, signed
- prove_nullification_inclusion(): valid path
- verify_nullification_inclusion(): valid / each failure reason
- PurgePolicyGate: passes with receipt / blocks overdue / passes within window
- Single-receipt registry (edge case: path length 0)
- Power-of-2 padding consistent with v0.35 algorithm
- CLI: receipt / register / prove / verify exit codes
"""

from __future__ import annotations

import base64
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nacl.signing
import pytest
from click.testing import CliRunner

from genesis_mesh.cli.decision_ops import trust
from genesis_mesh.models.consensus import EphemeralExecutionIdentity
from genesis_mesh.models.purge import (
    NullificationInclusionProof,
    NullificationReceipt,
    NullificationRegistryRoot,
    PurgePolicy,
)
from genesis_mesh.trust.purge import (
    PurgePolicyGate,
    build_nullification_registry,
    create_nullification_receipt,
    prove_nullification_inclusion,
    verify_nullification_inclusion,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PAST = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_ISSUED = _PAST - timedelta(seconds=120)
_PURGE_TIME = _PAST + timedelta(hours=1)


def _sk() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()


def _pub_b64(sk: nacl.signing.SigningKey) -> str:
    return base64.b64encode(bytes(sk.verify_key)).decode()


def _identity(
    expires_at: datetime = _PAST,
    identity_id: str | None = None,
) -> EphemeralExecutionIdentity:
    from genesis_mesh.crypto import sign_model  # noqa: PLC0415

    sk = _sk()
    eid = EphemeralExecutionIdentity(
        consensus_id="consensus-abc",
        decision_id="decision-xyz",
        bearer_sovereign_id="agent-bearer",
        issued_at=expires_at - timedelta(seconds=120),
        expires_at=expires_at,
        allowed_capabilities=["capability_read", "capability_write"],
    )
    if identity_id:
        eid = eid.model_copy(update={"identity_id": identity_id})
    sig = sign_model(eid, sk, "agent-bearer")
    return eid.model_copy(update={"signature": sig})


def _receipt(
    sk: nacl.signing.SigningKey,
    purging_sov: str = "operator-x",
    expires_at: datetime = _PAST,
    purge_now: datetime = _PURGE_TIME,
) -> NullificationReceipt:
    eid = _identity(expires_at=expires_at)
    return create_nullification_receipt(eid, purging_sov, sk, now=purge_now)


# ---------------------------------------------------------------------------
# NullificationReceipt — structure
# ---------------------------------------------------------------------------


def test_receipt_identity_digest_matches() -> None:
    sk = _sk()
    eid = _identity()
    rec = create_nullification_receipt(eid, "operator-x", sk, now=_PURGE_TIME)
    assert rec.identity_digest == eid.digest()


def test_receipt_does_not_contain_bearer_sovereign_id() -> None:
    sk = _sk()
    eid = _identity()
    rec = create_nullification_receipt(eid, "operator-x", sk, now=_PURGE_TIME)
    rec_json = rec.model_dump_json()
    assert "agent-bearer" not in rec_json
    assert "bearer_sovereign_id" not in rec_json


def test_receipt_does_not_contain_allowed_capabilities() -> None:
    sk = _sk()
    eid = _identity()
    rec = create_nullification_receipt(eid, "operator-x", sk, now=_PURGE_TIME)
    rec_json = rec.model_dump_json()
    assert "capability_read" not in rec_json
    assert "capability_write" not in rec_json
    assert "allowed_capabilities" not in rec_json


def test_receipt_retains_identity_id_and_consensus_id() -> None:
    sk = _sk()
    eid = _identity()
    rec = create_nullification_receipt(eid, "operator-x", sk, now=_PURGE_TIME)
    assert rec.identity_id == eid.identity_id
    assert rec.consensus_id == eid.consensus_id


def test_receipt_expiry_preserved() -> None:
    sk = _sk()
    eid = _identity(expires_at=_PAST)
    rec = create_nullification_receipt(eid, "operator-x", sk, now=_PURGE_TIME)
    assert rec.identity_expired_at == _PAST


def test_receipt_is_signed() -> None:
    sk = _sk()
    eid = _identity()
    rec = create_nullification_receipt(eid, "operator-x", sk, now=_PURGE_TIME)
    assert rec.signature is not None


def test_purge_non_expired_raises_value_error() -> None:
    sk = _sk()
    future_expiry = datetime(2030, 1, 1, tzinfo=timezone.utc)
    eid = _identity(expires_at=future_expiry)
    with pytest.raises(ValueError, match="not yet expired"):
        create_nullification_receipt(eid, "operator-x", sk, now=_PURGE_TIME)


def test_purge_exactly_at_expiry_raises_value_error() -> None:
    """Identity at exactly expires_at is not yet expired (strictly greater)."""
    sk = _sk()
    eid = _identity(expires_at=_PURGE_TIME)
    with pytest.raises(ValueError, match="not yet expired"):
        create_nullification_receipt(eid, "operator-x", sk, now=_PURGE_TIME)


# ---------------------------------------------------------------------------
# build_nullification_registry
# ---------------------------------------------------------------------------


def test_registry_merkle_root_non_empty() -> None:
    sk = _sk()
    receipts = [_receipt(sk) for _ in range(3)]
    registry, _ = build_nullification_registry(receipts, "operator-x", sk)
    assert len(registry.merkle_root) == 64


def test_registry_receipt_count() -> None:
    sk = _sk()
    receipts = [_receipt(sk) for _ in range(5)]
    registry, _ = build_nullification_registry(receipts, "operator-x", sk)
    assert registry.receipt_count == 5


def test_registry_is_signed() -> None:
    sk = _sk()
    receipts = [_receipt(sk)]
    registry, _ = build_nullification_registry(receipts, "operator-x", sk)
    assert registry.signature is not None


def test_registry_empty_receipts_raises() -> None:
    sk = _sk()
    with pytest.raises(ValueError):
        build_nullification_registry([], "operator-x", sk)


def test_registry_power_of_two_padded() -> None:
    """3 receipts → padded to 4 leaves (next power of 2)."""
    sk = _sk()
    receipts = [_receipt(sk) for _ in range(3)]
    _, levels = build_nullification_registry(receipts, "operator-x", sk)
    assert len(levels[0]) == 4  # padded to power of 2


# ---------------------------------------------------------------------------
# prove and verify inclusion
# ---------------------------------------------------------------------------


def test_prove_and_verify_valid() -> None:
    sk = _sk()
    receipts = [_receipt(sk) for _ in range(4)]
    registry, levels = build_nullification_registry(receipts, "operator-x", sk)
    target = receipts[2]
    proof = prove_nullification_inclusion(target.receipt_id, receipts, levels, registry)
    passed, reason = verify_nullification_inclusion(
        proof, registry, target, [_pub_b64(sk)]
    )
    assert passed is True
    assert reason == "valid"


def test_prove_first_receipt() -> None:
    sk = _sk()
    receipts = [_receipt(sk) for _ in range(3)]
    registry, levels = build_nullification_registry(receipts, "operator-x", sk)
    target = receipts[0]
    proof = prove_nullification_inclusion(target.receipt_id, receipts, levels, registry)
    passed, reason = verify_nullification_inclusion(
        proof, registry, target, [_pub_b64(sk)]
    )
    assert passed is True
    assert reason == "valid"


def test_prove_single_receipt_path_length_zero() -> None:
    """Single receipt → _next_power_of_two(1)=1 → no padding → path length 0."""
    sk = _sk()
    receipts = [_receipt(sk)]
    registry, levels = build_nullification_registry(receipts, "operator-x", sk)
    target = receipts[0]
    proof = prove_nullification_inclusion(target.receipt_id, receipts, levels, registry)
    # 1 receipt → padded to 1 → height 0
    assert len(proof.merkle_path) == 0
    passed, reason = verify_nullification_inclusion(
        proof, registry, target, [_pub_b64(sk)]
    )
    assert passed is True


def test_verify_non_member_receipt_fails() -> None:
    sk = _sk()
    receipts = [_receipt(sk) for _ in range(3)]
    registry, levels = build_nullification_registry(receipts, "operator-x", sk)
    non_member = _receipt(sk)  # not in the batch
    target = receipts[0]
    proof = prove_nullification_inclusion(target.receipt_id, receipts, levels, registry)
    # Use proof for target[0] but check against non_member
    passed, reason = verify_nullification_inclusion(
        proof, registry, non_member, [_pub_b64(sk)]
    )
    assert passed is False
    assert reason == "leaf_hash_mismatch"


def test_verify_tampered_receipt_fails() -> None:
    sk = _sk()
    receipts = [_receipt(sk) for _ in range(3)]
    registry, levels = build_nullification_registry(receipts, "operator-x", sk)
    target = receipts[1]
    proof = prove_nullification_inclusion(target.receipt_id, receipts, levels, registry)
    # Tamper the receipt's identity_digest
    tampered = target.model_copy(update={"identity_digest": "a" * 64})
    passed, reason = verify_nullification_inclusion(
        proof, registry, tampered, [_pub_b64(sk)]
    )
    assert passed is False
    assert reason == "leaf_hash_mismatch"


def test_verify_registry_missing_signature_fails() -> None:
    sk = _sk()
    receipts = [_receipt(sk) for _ in range(2)]
    registry, levels = build_nullification_registry(receipts, "operator-x", sk)
    unsigned_registry = registry.model_copy(update={"signature": None})
    target = receipts[0]
    proof = prove_nullification_inclusion(target.receipt_id, receipts, levels, registry)
    passed, reason = verify_nullification_inclusion(
        proof, unsigned_registry, target, [_pub_b64(sk)]
    )
    assert passed is False
    assert reason == "registry_missing_signature"


def test_verify_registry_invalid_signature_fails() -> None:
    sk = _sk()
    wrong_sk = _sk()
    receipts = [_receipt(sk) for _ in range(2)]
    registry, levels = build_nullification_registry(receipts, "operator-x", sk)
    target = receipts[0]
    proof = prove_nullification_inclusion(target.receipt_id, receipts, levels, registry)
    passed, reason = verify_nullification_inclusion(
        proof, registry, target, [_pub_b64(wrong_sk)]
    )
    assert passed is False
    assert reason == "registry_invalid_signature"


def test_prove_receipt_id_not_found_raises() -> None:
    sk = _sk()
    receipts = [_receipt(sk) for _ in range(2)]
    registry, levels = build_nullification_registry(receipts, "operator-x", sk)
    with pytest.raises(ValueError, match="not found"):
        prove_nullification_inclusion("nonexistent-id", receipts, levels, registry)


# ---------------------------------------------------------------------------
# PurgePolicyGate
# ---------------------------------------------------------------------------


def test_gate_passes_with_receipt() -> None:
    sk = _sk()
    eid = _identity(expires_at=_PAST)
    receipt = create_nullification_receipt(eid, "operator-x", sk, now=_PURGE_TIME)
    policy = PurgePolicy(
        operator_sovereign_id="operator-x",
        max_retention_after_expiry_seconds=3600,
    )
    gate = PurgePolicyGate(eid, receipt, policy, [_pub_b64(sk)])
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is True  # type: ignore[attr-defined]
    assert result.gate_name == "purge_policy"  # type: ignore[attr-defined]


def test_gate_blocks_overdue_no_receipt() -> None:
    sk = _sk()
    # Identity that expired far in the past (2024), max_retention = 60s
    eid = _identity(expires_at=_PAST)
    policy = PurgePolicy(
        operator_sovereign_id="operator-x",
        max_retention_after_expiry_seconds=60,
    )
    gate = PurgePolicyGate(eid, None, policy, [_pub_b64(sk)])
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is False  # type: ignore[attr-defined]
    assert "overdue" in result.detail  # type: ignore[attr-defined]


def test_gate_passes_within_window_no_receipt() -> None:
    """Identity expired 10 seconds ago with 24-hour retention window."""
    sk = _sk()
    recent_expiry = datetime.now(timezone.utc) - timedelta(seconds=10)
    eid = _identity(expires_at=recent_expiry)
    policy = PurgePolicy(
        operator_sovereign_id="operator-x",
        max_retention_after_expiry_seconds=86400,  # 24 hours
    )
    gate = PurgePolicyGate(eid, None, policy, [_pub_b64(sk)])
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is True  # type: ignore[attr-defined]


def test_gate_blocks_receipt_identity_id_mismatch() -> None:
    sk = _sk()
    eid = _identity(expires_at=_PAST)
    receipt = create_nullification_receipt(eid, "operator-x", sk, now=_PURGE_TIME)
    # Different identity in the gate
    other_eid = _identity(expires_at=_PAST)
    policy = PurgePolicy(operator_sovereign_id="operator-x")
    gate = PurgePolicyGate(other_eid, receipt, policy, [_pub_b64(sk)])
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is False  # type: ignore[attr-defined]
    assert "identity_id" in result.detail  # type: ignore[attr-defined]


def test_gate_blocks_tampered_receipt_digest() -> None:
    sk = _sk()
    eid = _identity(expires_at=_PAST)
    receipt = create_nullification_receipt(eid, "operator-x", sk, now=_PURGE_TIME)
    tampered = receipt.model_copy(update={"identity_digest": "f" * 64})
    policy = PurgePolicy(operator_sovereign_id="operator-x")
    gate = PurgePolicyGate(eid, tampered, policy, [_pub_b64(sk)])
    result = gate(None, None)  # type: ignore[attr-defined]
    assert result.passed is False  # type: ignore[attr-defined]
    assert "identity_digest" in result.detail  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_purge_receipt() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "op.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
        eid = _identity(expires_at=_PAST)
        eid_path = p / "identity.json"
        eid_path.write_text(eid.model_dump_json(indent=2), encoding="utf-8")
        out_path = p / "receipt.json"

        runner = CliRunner()
        result = runner.invoke(trust, [
            "purge", "receipt",
            "--identity", str(eid_path),
            "--purging-sovereign", "operator-x",
            "--signing-key", str(key_path),
            "--output", str(out_path),
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output
        rec = NullificationReceipt.model_validate_json(out_path.read_text())
        assert rec.identity_id == eid.identity_id
        assert rec.signature is not None


def test_cli_purge_receipt_not_expired_fails() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "op.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        eid = _identity(expires_at=future)
        eid_path = p / "identity.json"
        eid_path.write_text(eid.model_dump_json(indent=2), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(trust, [
            "purge", "receipt",
            "--identity", str(eid_path),
            "--purging-sovereign", "operator-x",
            "--signing-key", str(key_path),
            "--output", str(p / "receipt.json"),
        ])
        assert result.exit_code != 0


def test_cli_purge_register_and_prove_verify() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "op.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")

        # Create 3 receipts
        receipts: list[NullificationReceipt] = []
        receipt_paths: list[str] = []
        for i in range(3):
            eid = _identity(expires_at=_PAST)
            rec = create_nullification_receipt(eid, "operator-x", sk, now=_PURGE_TIME)
            rec_path = p / f"receipt_{i}.json"
            rec_path.write_text(rec.model_dump_json(indent=2), encoding="utf-8")
            receipts.append(rec)
            receipt_paths.append(str(rec_path))

        registry_path = p / "registry.json"
        receipts_list_path = p / "receipts_list.json"

        runner = CliRunner()

        # register
        register_args = ["purge", "register",
                         "--operator-sovereign", "operator-x",
                         "--signing-key", str(key_path),
                         "--output", str(registry_path),
                         "--output-receipts", str(receipts_list_path)]
        for rp in receipt_paths:
            register_args += ["--receipt", rp]
        result = runner.invoke(trust, register_args)
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output

        # prove
        proof_path = p / "proof.json"
        result = runner.invoke(trust, [
            "purge", "prove",
            "--receipt-id", receipts[1].receipt_id,
            "--receipts-file", str(receipts_list_path),
            "--registry", str(registry_path),
            "--output", str(proof_path),
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output

        # verify
        result = runner.invoke(trust, [
            "purge", "verify",
            "--proof", str(proof_path),
            "--registry", str(registry_path),
            "--receipt", str(receipt_paths[1]),
            "--public-key", _pub_b64(sk),
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output


def test_cli_purge_verify_json_format() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "op.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")

        receipts = [_receipt(sk) for _ in range(2)]
        registry, levels = build_nullification_registry(receipts, "operator-x", sk)
        target = receipts[0]
        proof = prove_nullification_inclusion(target.receipt_id, receipts, levels, registry)

        proof_path = p / "proof.json"
        proof_path.write_text(proof.model_dump_json(indent=2), encoding="utf-8")
        registry_path = p / "registry.json"
        registry_path.write_text(registry.model_dump_json(indent=2), encoding="utf-8")
        receipt_path = p / "receipt.json"
        receipt_path.write_text(target.model_dump_json(indent=2), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(trust, [
            "purge", "verify",
            "--proof", str(proof_path),
            "--registry", str(registry_path),
            "--receipt", str(receipt_path),
            "--public-key", _pub_b64(sk),
            "--format", "json",
        ])
        parsed = json.loads(result.output)
        assert parsed["passed"] is True
        assert parsed["reason"] == "valid"
