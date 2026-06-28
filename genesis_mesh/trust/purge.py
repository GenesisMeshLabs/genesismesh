"""Ephemeral Identity Purge Protocol — verifiable deletion of expired identities (v0.42).

Produces NullificationReceipts that prove an EphemeralExecutionIdentity existed
and was destroyed, without retaining its sensitive fields. Receipts are batched
into a signed Merkle registry root so auditors can verify inclusion without
resurrecting the deleted content.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.consensus import EphemeralExecutionIdentity
from ..models.context import GateResult
from ..models.purge import (
    NullificationInclusionProof,
    NullificationReceipt,
    NullificationRegistryRoot,
    PurgePolicy,
)
from ..models.selective_disclosure import MerklePathNode

# ---------------------------------------------------------------------------
# Internal Merkle helpers (same algorithm as v0.35 selective_disclosure)
# ---------------------------------------------------------------------------

_PAD_HASH = hashlib.sha256(b"").hexdigest()


def _next_power_of_two(n: int) -> int:
    if n <= 1:
        return 1
    p = 1
    while p < n:
        p <<= 1
    return p


def _build_merkle_tree(leaf_hashes: list[str]) -> tuple[str, list[list[str]]]:
    """Return (root_hex, levels). levels[0] = padded leaf layer.

    Does NOT sort leaves — receipt order is preserved for audit purposes.
    """
    if not leaf_hashes:
        raise ValueError("leaf_hashes cannot be empty")

    size = _next_power_of_two(len(leaf_hashes))
    padded = leaf_hashes + [_PAD_HASH] * (size - len(leaf_hashes))

    levels: list[list[str]] = [padded]
    current = padded
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
    leaf_idx: int, levels: list[list[str]]
) -> list[MerklePathNode]:
    path: list[MerklePathNode] = []
    idx = leaf_idx
    for level_nodes in levels[:-1]:
        sibling_idx = idx ^ 1
        sibling_hash = level_nodes[sibling_idx]
        is_left = bool(idx & 1)
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
# create_nullification_receipt
# ---------------------------------------------------------------------------


def create_nullification_receipt(
    identity: EphemeralExecutionIdentity,
    purging_sovereign_id: str,
    signing_key: nacl.signing.SigningKey,
    *,
    now: datetime | None = None,
) -> NullificationReceipt:
    """Produce a signed NullificationReceipt for an expired identity.

    Raises ValueError if the identity has not yet expired at `now`.
    The receipt retains only identity_id, consensus_id, expiry, and the
    SHA-256 digest of the full canonical JSON — not the sensitive fields.
    """
    now = now or datetime.now(timezone.utc)
    if now <= identity.expires_at:
        raise ValueError(
            f"Identity {identity.identity_id!r} has not yet expired "
            f"(expires_at={identity.expires_at.isoformat()}, now={now.isoformat()})"
        )

    receipt = NullificationReceipt(
        identity_id=identity.identity_id,
        consensus_id=identity.consensus_id,
        identity_expired_at=identity.expires_at,
        purged_at=now,
        purged_by_sovereign_id=purging_sovereign_id,
        identity_digest=identity.digest(),
    )
    sig = sign_model(receipt, signing_key, purging_sovereign_id)
    return receipt.model_copy(update={"signature": sig})


# ---------------------------------------------------------------------------
# build_nullification_registry
# ---------------------------------------------------------------------------


def build_nullification_registry(
    receipts: list[NullificationReceipt],
    operator_sovereign_id: str,
    signing_key: nacl.signing.SigningKey,
    *,
    now: datetime | None = None,
) -> tuple[NullificationRegistryRoot, list[list[str]]]:
    """Build a signed Merkle registry over a batch of NullificationReceipts.

    Returns (registry_root, merkle_levels) where merkle_levels is used for
    proof generation. The root covers receipt digests in their supplied order.
    """
    if not receipts:
        raise ValueError("receipts cannot be empty")

    now = now or datetime.now(timezone.utc)
    leaf_hashes = [r.digest() for r in receipts]
    merkle_root, levels = _build_merkle_tree(leaf_hashes)

    registry = NullificationRegistryRoot(
        merkle_root=merkle_root,
        receipt_count=len(receipts),
        batch_start=min(r.purged_at for r in receipts),
        batch_end=max(r.purged_at for r in receipts),
        operator_sovereign_id=operator_sovereign_id,
    )
    sig = sign_model(registry, signing_key, operator_sovereign_id)
    signed_registry = registry.model_copy(update={"signature": sig})
    return signed_registry, levels


# ---------------------------------------------------------------------------
# prove_nullification_inclusion
# ---------------------------------------------------------------------------


def prove_nullification_inclusion(
    receipt_id: str,
    receipts: list[NullificationReceipt],
    levels: list[list[str]],
    registry_root: NullificationRegistryRoot,
) -> NullificationInclusionProof:
    """Build a Merkle inclusion proof for the receipt with the given receipt_id."""
    ids = [r.receipt_id for r in receipts]
    try:
        idx = ids.index(receipt_id)
    except ValueError:
        raise ValueError(f"receipt_id {receipt_id!r} not found in receipts list")

    leaf_hash = receipts[idx].digest()
    path = _build_path(idx, levels)

    return NullificationInclusionProof(
        receipt_id=receipt_id,
        registry_root_id=registry_root.root_id,
        leaf_hash=leaf_hash,
        merkle_path=path,
        proved_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# verify_nullification_inclusion
# ---------------------------------------------------------------------------


def verify_nullification_inclusion(
    proof: NullificationInclusionProof,
    registry_root: NullificationRegistryRoot,
    expected_receipt: NullificationReceipt,
    issuer_public_keys: list[str],
) -> tuple[bool, str]:
    """Verify that a NullificationReceipt is included in the registry.

    Checks:
    1. Registry root has a valid signature from one of issuer_public_keys
    2. proof.registry_root_id matches registry_root.root_id
    3. proof.leaf_hash == expected_receipt.digest()
    4. Recomputed root from leaf + path == registry_root.merkle_root

    Returns (passed, reason) where reason is "valid" or a failure description.
    """
    if registry_root.signature is None:
        return False, "registry_missing_signature"

    if not any(
        verify_model_signature(registry_root, registry_root.signature, pk)
        for pk in issuer_public_keys
    ):
        return False, "registry_invalid_signature"

    if proof.registry_root_id != registry_root.root_id:
        return False, "root_id_mismatch"

    if proof.leaf_hash != expected_receipt.digest():
        return False, "leaf_hash_mismatch"

    recomputed = _recompute_root(proof.leaf_hash, proof.merkle_path)
    if recomputed != registry_root.merkle_root:
        return False, "root_mismatch"

    return True, "valid"


# ---------------------------------------------------------------------------
# PurgePolicyGate
# ---------------------------------------------------------------------------


class PurgePolicyGate:
    """Gate that enforces identities are purged within the configured policy window.

    Used in post-execution audit workflows — verifies that a NullificationReceipt
    exists for an identity that has been expired for longer than the policy allows.

    Passes when a valid receipt exists. Blocks when no receipt is found for a
    long-expired identity (i.e. the purge is overdue).
    """

    gate_name = "purge_policy"

    def __init__(
        self,
        identity: EphemeralExecutionIdentity,
        receipt: NullificationReceipt | None,
        policy: PurgePolicy,
        issuer_public_keys: list[str],
    ) -> None:
        self._identity = identity
        self._receipt = receipt
        self._policy = policy
        self._keys = issuer_public_keys

    def __call__(self, context: object, terms: object) -> object:
        from datetime import timedelta  # noqa: PLC0415

        now = datetime.now(timezone.utc)
        deadline = self._identity.expires_at + timedelta(
            seconds=self._policy.max_retention_after_expiry_seconds
        )
        overdue = now > deadline

        if self._receipt is None:
            if overdue:
                return GateResult(
                    gate_name=self.gate_name,
                    passed=False,
                    detail=(
                        f"identity '{self._identity.identity_id[:8]}' "
                        f"purge overdue (expired {self._identity.expires_at.isoformat()})"
                    ),
                )
            # Not yet overdue — gate passes (purge still within window)
            return GateResult(
                gate_name=self.gate_name,
                passed=True,
                detail=(
                    f"identity '{self._identity.identity_id[:8]}' "
                    f"purge still within policy window"
                ),
            )

        # Receipt exists — verify it matches this identity
        if self._receipt.identity_id != self._identity.identity_id:
            return GateResult(
                gate_name=self.gate_name,
                passed=False,
                detail="receipt identity_id does not match gate identity",
            )

        if self._receipt.identity_digest != self._identity.digest():
            return GateResult(
                gate_name=self.gate_name,
                passed=False,
                detail="receipt identity_digest does not match identity",
            )

        return GateResult(
            gate_name=self.gate_name,
            passed=True,
            detail=f"receipt '{self._receipt.receipt_id[:8]}' verified",
        )
