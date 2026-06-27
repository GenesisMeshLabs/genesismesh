"""Build and verify Execution Evidence hash chains.

After a BoundaryDecision authorizes execution, the executor records what
happened as an ExecutionEvidence record.  Multiple records under the same
decision are linked by prev_evidence_digest, forming a tamper-evident chain.

Any insertion, deletion, reorder, or field tamper breaks the chain and is
surfaced as a specific failure reason by verify_evidence_chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.context import BoundaryDecision
from ..models.execution import EvidenceChain, ExecutionEvidence


# ---------------------------------------------------------------------------
# EvidenceChainVerificationResult
# ---------------------------------------------------------------------------

EvidenceChainVerificationReason = Literal[
    "verified",
    "empty_chain",
    "chain_break",
    "digest_mismatch",
    "invalid_signature",
    "capability_mismatch",
    "sequence_gap",
    "sequence_out_of_order",
    "missing_signature",
    "stale_freshness_proof",
]


@dataclass(frozen=True)
class EvidenceChainVerificationResult:
    """Structured outcome of an evidence chain verification attempt."""

    verified: bool
    reason: EvidenceChainVerificationReason
    chain_length: int
    failed_at_sequence: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "reason": self.reason,
            "chain_length": self.chain_length,
            "failed_at_sequence": self.failed_at_sequence,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _reject(
    reason: EvidenceChainVerificationReason,
    chain_length: int,
    seq: int | None = None,
) -> EvidenceChainVerificationResult:
    return EvidenceChainVerificationResult(
        verified=False,
        reason=reason,
        chain_length=chain_length,
        failed_at_sequence=seq,
    )


# ---------------------------------------------------------------------------
# record_execution
# ---------------------------------------------------------------------------


def record_execution(
    decision: BoundaryDecision,
    executor_sovereign_id: str,
    executed_capability: str,
    outcome: str,
    signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
    sequence_no: int = 1,
    execution_parameters: dict[str, Any] | None = None,
    outcome_detail: str | None = None,
    prior_record: ExecutionEvidence | None = None,
    now: datetime | None = None,
) -> ExecutionEvidence:
    """Create and sign a new ExecutionEvidence record.

    If ``prior_record`` is provided, sets ``prev_evidence_digest`` to the
    SHA-256 of the prior record's canonical JSON, linking the chain.

    Args:
        decision: The BoundaryDecision that authorized this execution.
        executor_sovereign_id: Sovereign performing the execution.
        executed_capability: Capability identifier that was executed.
        outcome: "success", "failure", or "partial".
        signing_key: Executor's Ed25519 private key.
        issued_by: Key identifier recorded in the signature.
        sequence_no: 1-based sequence number within this decision.
        execution_parameters: Final parameters used.
        outcome_detail: Optional human-readable detail.
        prior_record: Previous ExecutionEvidence in the chain (None if first).
        now: Override for the current timestamp.
    """
    ts = _now(now)
    prev_digest: str | None = prior_record.digest() if prior_record is not None else None

    record = ExecutionEvidence(
        sequence_no=sequence_no,
        decision_id=decision.decision_id,
        context_id=decision.context_id,
        agreement_id=decision.agreement_id,
        executor_sovereign_id=executor_sovereign_id,
        executed_capability=executed_capability,
        execution_parameters=execution_parameters or {},
        executed_at=ts,
        outcome=outcome,
        outcome_detail=outcome_detail,
        prev_evidence_digest=prev_digest,
    )
    sig = sign_model(record, signing_key, issued_by)
    return record.model_copy(update={"signature": sig})


# ---------------------------------------------------------------------------
# verify_evidence_chain
# ---------------------------------------------------------------------------


def verify_evidence_chain(
    chain: EvidenceChain,
    *,
    executor_public_keys_by_sovereign: dict[str, list[str]],
    expected_capability: str | None = None,
    decision: BoundaryDecision | None = None,
) -> EvidenceChainVerificationResult:
    """Verify an ExecutionEvidence hash chain.

    Checks for each record:
    1. ``sequence_no`` starts at 1 and increments by 1 (no gaps, no reorder).
    2. ``prev_evidence_digest`` matches SHA-256 of the prior record's canonical
       JSON (None for the first record).
    3. Signature is valid for the declared ``executor_sovereign_id``.
    4. ``executed_capability`` matches ``expected_capability`` if provided.
    5. When ``decision`` is provided and has an embedded ``freshness_proof``:
       each ``executed_at`` must be <= ``proof_valid_until``.  Any record
       executed after the proof expired returns ``stale_freshness_proof``.

    Args:
        chain: EvidenceChain with decision_id and ordered records.
        executor_public_keys_by_sovereign: Maps sovereign_id → list of
            base64 public keys.
        expected_capability: When provided, each record's executed_capability
            must match.
        decision: Optional BoundaryDecision.  When provided and it has an
            embedded freshness_proof, stale-proof detection is active.

    Returns:
        EvidenceChainVerificationResult with reason and failed_at_sequence.
    """
    n = len(chain.records)
    if n == 0:
        return _reject("empty_chain", 0)

    prev: ExecutionEvidence | None = None

    for record in chain.records:
        seq = record.sequence_no

        # Sequence integrity
        expected_seq = 1 if prev is None else prev.sequence_no + 1
        if seq != expected_seq:
            # seq < expected_seq: a lower number came after a higher one → out of order
            # seq > expected_seq: a number was skipped → gap
            reason: EvidenceChainVerificationReason = (
                "sequence_out_of_order" if seq < expected_seq else "sequence_gap"
            )
            return _reject(reason, n, seq)

        # Capability check
        if expected_capability is not None and record.executed_capability != expected_capability:
            return _reject("capability_mismatch", n, seq)

        # Hash-chain linkage
        if prev is None:
            if record.prev_evidence_digest is not None:
                return _reject("chain_break", n, seq)
        else:
            expected_digest = prev.digest()
            if record.prev_evidence_digest != expected_digest:
                return _reject("digest_mismatch", n, seq)

        # Signature check
        if record.signature is None:
            return _reject("missing_signature", n, seq)

        keys = executor_public_keys_by_sovereign.get(record.executor_sovereign_id, [])
        if not keys:
            return _reject("invalid_signature", n, seq)

        sig_valid = any(
            verify_model_signature(record, record.signature, pub)
            for pub in keys
        )
        if not sig_valid:
            return _reject("invalid_signature", n, seq)

        # Stale-proof check: execution occurred after the proof's validity window
        if (
            decision is not None
            and decision.freshness_proof is not None
            and record.executed_at > decision.freshness_proof.proof_valid_until
        ):
            return _reject("stale_freshness_proof", n, seq)

        prev = record

    return EvidenceChainVerificationResult(
        verified=True,
        reason="verified",
        chain_length=n,
        failed_at_sequence=None,
    )
