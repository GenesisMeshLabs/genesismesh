"""Selective Disclosure Capability Proofs — Merkle-based membership proofs.

Lets an agent prove it holds a specific capability without revealing the full
capability set, agreement ID, or any other capability.

Algorithm:
  1. Sort capabilities lexicographically.
  2. Hash each leaf: SHA-256(capability.encode()).
  3. Pad to next power-of-2 with SHA-256(b"") as empty leaves.
  4. Build balanced binary Merkle tree bottom-up:
       parent = SHA-256(left_bytes || right_bytes)
  5. Root = CapabilityCommitment.merkle_root (hex).
  6. Membership proof = leaf_hash + sibling path from leaf to root.

No external library required — only hashlib.sha256.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.agreement import AgreementRecord
from ..models.context import GateResult
from ..models.selective_disclosure import (
    CapabilityCommitment,
    CapabilityMembershipProof,
    CapabilityNullifier,
    MerklePathNode,
)

# ---------------------------------------------------------------------------
# Verification result
# ---------------------------------------------------------------------------

CapabilityProofVerificationReason = Literal[
    "valid",
    "root_mismatch",
    "leaf_hash_mismatch",
    "path_length_inconsistent",
    "commitment_not_signed",
    "commitment_invalid_signature",
    "nullifier_expired",
    "nullifier_already_used",
]


@dataclass(frozen=True)
class CapabilityProofVerificationResult:
    valid: bool
    reason: CapabilityProofVerificationReason
    commitment_id: str


def _reject(
    reason: CapabilityProofVerificationReason, commitment_id: str
) -> CapabilityProofVerificationResult:
    return CapabilityProofVerificationResult(
        valid=False, reason=reason, commitment_id=commitment_id
    )


# ---------------------------------------------------------------------------
# Internal Merkle helpers
# ---------------------------------------------------------------------------

_PAD_HASH = hashlib.sha256(b"").hexdigest()


def _next_power_of_two(n: int) -> int:
    if n <= 1:
        return 1
    p = 1
    while p < n:
        p <<= 1
    return p


def _expected_path_length(capability_count: int) -> int:
    """Merkle tree height for a set of capability_count leaves (after padding)."""
    if capability_count <= 0:
        raise ValueError("capability_count must be >= 1")
    return (capability_count - 1).bit_length()


def _build_merkle_tree(capabilities: list[str]) -> tuple[str, list[list[str]]]:
    """Return (root_hex, levels) where levels[0] = padded leaf layer."""
    if not capabilities:
        raise ValueError("capability list cannot be empty")

    sorted_caps = sorted(capabilities)
    leaves = [hashlib.sha256(c.encode()).hexdigest() for c in sorted_caps]

    size = _next_power_of_two(len(leaves))
    leaves = leaves + [_PAD_HASH] * (size - len(leaves))

    levels: list[list[str]] = [leaves]
    current = leaves
    while len(current) > 1:
        parents = []
        for i in range(0, len(current), 2):
            left = bytes.fromhex(current[i])
            right = bytes.fromhex(current[i + 1])
            parents.append(hashlib.sha256(left + right).hexdigest())
        levels.append(parents)
        current = parents

    return current[0], levels


def _build_path(
    capability: str, sorted_caps: list[str], levels: list[list[str]]
) -> list[MerklePathNode]:
    try:
        idx = sorted_caps.index(capability)
    except ValueError:
        raise ValueError(f"capability '{capability}' is not in the capability set")

    path: list[MerklePathNode] = []
    for level_nodes in levels[:-1]:  # all levels except root
        sibling_idx = idx ^ 1  # toggle last bit
        sibling_hash = level_nodes[sibling_idx]
        is_left = bool(idx & 1)  # sibling is left when current is at odd index
        path.append(MerklePathNode(sibling_hash=sibling_hash, is_left=is_left))
        idx >>= 1

    return path


def _recompute_root(leaf_hash: str, path: list[MerklePathNode]) -> str:
    current = leaf_hash
    for node in path:
        current_bytes = bytes.fromhex(current)
        sibling_bytes = bytes.fromhex(node.sibling_hash)
        if node.is_left:
            parent = hashlib.sha256(sibling_bytes + current_bytes).hexdigest()
        else:
            parent = hashlib.sha256(current_bytes + sibling_bytes).hexdigest()
        current = parent
    return current


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def commit_capabilities(
    capabilities: list[str],
    agreement: AgreementRecord,
    signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
    now: datetime | None = None,
) -> CapabilityCommitment:
    """Build and sign a Merkle commitment over the provided capability list."""
    if not capabilities:
        raise ValueError("capabilities list must not be empty")

    now = now or datetime.now(timezone.utc)
    root, _ = _build_merkle_tree(capabilities)

    commitment = CapabilityCommitment(
        merkle_root=root,
        capability_count=len(capabilities),
        agreement_id=agreement.agreement_id,
        committed_at=now,
        issuer_sovereign_id=issued_by,
    )

    sig = sign_model(commitment, signing_key, issued_by)
    return commitment.model_copy(update={"signature": sig})


def prove_capability_membership(
    capability: str,
    capabilities: list[str],
    commitment: CapabilityCommitment,
    prover_sovereign_id: str,
    *,
    now: datetime | None = None,
) -> CapabilityMembershipProof:
    """Produce a Merkle membership proof for a single capability.

    The full capability list is used locally to build the path but is never
    embedded in the returned proof.  Raises ValueError if the capability is
    not in the list.
    """
    now = now or datetime.now(timezone.utc)

    if capability not in capabilities:
        raise ValueError(f"capability '{capability}' is not in the capability set")

    sorted_caps = sorted(capabilities)
    root, levels = _build_merkle_tree(capabilities)

    # Single-cap edge case: tree has one padded or unpadded leaf.
    leaf_hash = hashlib.sha256(capability.encode()).hexdigest()
    path = _build_path(capability, sorted_caps, levels)

    return CapabilityMembershipProof(
        commitment_id=commitment.commitment_id,
        revealed_capability=capability,
        leaf_hash=leaf_hash,
        merkle_path=path,
        prover_sovereign_id=prover_sovereign_id,
        proved_at=now,
    )


def verify_capability_proof(
    proof: CapabilityMembershipProof,
    commitment: CapabilityCommitment,
    issuer_public_keys: list[str],
    *,
    nullifier: CapabilityNullifier | None = None,
    used_nullifiers: set[str] | None = None,
) -> CapabilityProofVerificationResult:
    """Verify a CapabilityMembershipProof against its commitment.

    Verification order:
    1. commitment_not_signed
    2. commitment_invalid_signature
    3. path_length_inconsistent
    4. leaf_hash_mismatch
    5. root_mismatch
    6. nullifier_expired
    7. nullifier_already_used
    8. valid
    """
    cid = commitment.commitment_id
    now = datetime.now(timezone.utc)

    # 1. Commitment must be signed.
    if commitment.signature is None:
        return _reject("commitment_not_signed", cid)

    # 2. Commitment signature must be valid.
    if not any(verify_model_signature(commitment, commitment.signature, pub)
               for pub in issuer_public_keys):
        return _reject("commitment_invalid_signature", cid)

    # 3. Path length must be consistent with capability_count.
    expected = _expected_path_length(commitment.capability_count)
    if len(proof.merkle_path) != expected:
        return _reject("path_length_inconsistent", cid)

    # 4. Leaf hash must match the revealed capability.
    expected_leaf = hashlib.sha256(proof.revealed_capability.encode()).hexdigest()
    if proof.leaf_hash != expected_leaf:
        return _reject("leaf_hash_mismatch", cid)

    # 5. Recomputed root must match the commitment root.
    recomputed = _recompute_root(proof.leaf_hash, proof.merkle_path)
    if recomputed != commitment.merkle_root:
        return _reject("root_mismatch", cid)

    # 6–7. Nullifier checks.
    if nullifier is not None:
        if nullifier.expires_at <= now:
            return _reject("nullifier_expired", cid)
        if used_nullifiers and nullifier.nullifier_id in used_nullifiers:
            return _reject("nullifier_already_used", cid)

    return CapabilityProofVerificationResult(valid=True, reason="valid", commitment_id=cid)


def issue_nullifier(
    proof: CapabilityMembershipProof,
    signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
    valid_for_seconds: int = 60,
    now: datetime | None = None,
) -> CapabilityNullifier:
    """Issue a single-use nullifier tied to this proof."""
    now = now or datetime.now(timezone.utc)
    nonce = secrets.token_hex(16)
    nullifier = CapabilityNullifier(
        proof_id=proof.proof_id,
        nonce=nonce,
        issued_at=now,
        expires_at=now + timedelta(seconds=valid_for_seconds),
        prover_sovereign_id=issued_by,
    )
    sig = sign_model(nullifier, signing_key, issued_by)
    return nullifier.model_copy(update={"signature": sig})


# ---------------------------------------------------------------------------
# SelectiveDisclosureGate — plugs into BoundaryEngine.add_gate()
# ---------------------------------------------------------------------------


class SelectiveDisclosureGate:
    """Callable gate that verifies a CapabilityMembershipProof instead of checking
    the full agreement's capability list.

    Usage::

        gate = SelectiveDisclosureGate(commitment, proof, issuer_public_keys)
        engine.add_gate(gate)           # replaces capability_gate for this request

    The gate passes only when:
    - The commitment signature is valid.
    - The Merkle proof reconstructs the committed root.
    - ``proof.revealed_capability == context.requested_capability``.
    """

    def __init__(
        self,
        commitment: CapabilityCommitment,
        proof: CapabilityMembershipProof,
        issuer_public_keys: list[str],
    ) -> None:
        self._commitment = commitment
        self._proof = proof
        self._issuer_public_keys = issuer_public_keys

    def __call__(self, context: object, terms: object) -> GateResult:
        # context and terms are ContextRecord / AgreementTerms; import is lazy to
        # avoid circular imports.
        from ..models.context import ContextRecord

        result = verify_capability_proof(
            self._proof, self._commitment, self._issuer_public_keys
        )
        if not result.valid:
            return GateResult(
                gate_name="selective_disclosure",
                passed=False,
                detail=f"proof verification failed: {result.reason}",
            )

        if isinstance(context, ContextRecord):
            requested: str | None = context.requested_capability
        else:
            requested = getattr(context, "requested_capability", None)

        if requested != self._proof.revealed_capability:
            return GateResult(
                gate_name="selective_disclosure",
                passed=False,
                detail=(
                    f"disclosed capability '{self._proof.revealed_capability}' "
                    f"!= requested capability '{requested}'"
                ),
            )

        return GateResult(
            gate_name="selective_disclosure",
            passed=True,
            detail=f"selective disclosure proof valid for '{self._proof.revealed_capability}'",
        )
