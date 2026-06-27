"""Build and verify Attenuable Delegation Chains.

A party holding an AgreementRecord (or a DelegatedAgreementRecord) can delegate
a strict subset of its rights to a third party.  Every hop must narrow authority.
Any hop that widens scope, extends validity, or breaks the parent-terms digest
makes the entire chain unverifiable.

Protocol: ``build_delegation`` (delegator signs) → ``cosign_delegation``
(delegate adds their signature) → ``verify_delegation_chain`` (walk root to
terminal, check every hop).

Key invariants
--------------
- ``delegated_terms.capabilities ⊆ parent.agreed_terms.capabilities``
- ``expires_at ≤ parent.expires_at``
- ``parent_terms_digest == terms_digest(parent.agreed_terms)``
- Both delegator and delegate sign the same canonical form.
- The chain root is always an ``AgreementRecord``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.agreement import AgreementRecord, AgreementTerms
from ..models.delegation import DelegatedAgreementRecord, DelegationChain, terms_digest
from ..models.genesis import Signature
from .decision import evaluate_trust_decision
from .evidence import build_trust_evidence, graph_digest_from_export


# ---------------------------------------------------------------------------
# DelegationChainVerificationResult
# ---------------------------------------------------------------------------

DelegationChainVerificationReason = Literal[
    "accepted",
    "missing_delegator_signature",
    "invalid_delegator_signature",
    "missing_delegate_signature",
    "invalid_delegate_signature",
    "scope_escalation",
    "validity_escalation",
    "terms_digest_mismatch",
    "root_agreement_invalid",
    "empty_chain",
    "parent_id_mismatch",
]


@dataclass(frozen=True)
class DelegationChainVerificationResult:
    """Structured outcome of a delegation-chain verification attempt."""

    accepted: bool
    reason: DelegationChainVerificationReason
    chain_length: int
    failed_at_hop: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "chain_length": self.chain_length,
            "failed_at_hop": self.failed_at_hop,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _reject(
    reason: DelegationChainVerificationReason,
    chain_length: int,
    hop: int | None = None,
) -> DelegationChainVerificationResult:
    return DelegationChainVerificationResult(
        accepted=False,
        reason=reason,
        chain_length=chain_length,
        failed_at_hop=hop,
    )


def _check_capabilities_subset(delegated: list[str], parent: list[str]) -> bool:
    return set(delegated) <= set(parent)


def _build_evidence_dict(
    graph: dict[str, Any],
    source_id: str,
    target_id: str,
    signing_key: nacl.signing.SigningKey,
    issued_by: str,
    now: datetime,
) -> dict[str, Any]:
    decision = evaluate_trust_decision(graph, source_id, target_id)
    digest = graph_digest_from_export(graph)
    evidence = build_trust_evidence(
        decision,
        issuer_sovereign_id=source_id,
        graph_digest=digest,
        issued_by=issued_by,
        signing_key=signing_key,
        now=now,
    )
    return evidence.model_dump(mode="json")


def _parent_agreed_terms(parent: AgreementRecord | DelegatedAgreementRecord) -> AgreementTerms:
    if isinstance(parent, AgreementRecord):
        return parent.agreed_terms
    return parent.delegated_terms


def _parent_expires_at(parent: AgreementRecord | DelegatedAgreementRecord) -> datetime:
    return parent.expires_at


def _parent_id(parent: AgreementRecord | DelegatedAgreementRecord) -> str:
    if isinstance(parent, AgreementRecord):
        return parent.agreement_id
    return parent.delegation_id


def _parent_kind(parent: AgreementRecord | DelegatedAgreementRecord) -> str:
    if isinstance(parent, AgreementRecord):
        return "agreement"
    return "delegation"


# ---------------------------------------------------------------------------
# build_delegation
# ---------------------------------------------------------------------------


def build_delegation(
    parent: AgreementRecord | DelegatedAgreementRecord,
    delegated_terms: AgreementTerms,
    graph: dict[str, Any],
    signing_key: nacl.signing.SigningKey,
    *,
    delegator_sovereign_id: str,
    delegate_sovereign_id: str,
    issued_by: str,
    now: datetime | None = None,
) -> DelegatedAgreementRecord:
    """Build and sign a DelegatedAgreementRecord (delegator's step).

    Returns a half-signed record containing only the delegator's signature.
    The delegate must call ``cosign_delegation`` to finalize.

    Raises:
        ValueError: If ``delegated_terms.capabilities`` exceed parent capabilities
            (scope widening is forbidden).
        ValueError: If ``delegated_terms.valid_until`` > parent ``expires_at``
            (validity escalation is forbidden).
        ValueError: If ``delegator_sovereign_id`` is not a party in the parent record.
    """
    ts = _now(now)
    parent_terms = _parent_agreed_terms(parent)
    parent_exp = _parent_expires_at(parent)

    # Verify the delegator is actually a party in the parent
    if isinstance(parent, AgreementRecord):
        valid_parties = {parent.offerer_sovereign_id, parent.responder_sovereign_id}
    else:
        valid_parties = {parent.delegator_sovereign_id, parent.delegate_sovereign_id}
    if delegator_sovereign_id not in valid_parties:
        raise ValueError(
            f"Delegator {delegator_sovereign_id!r} is not a party in the parent "
            f"record (parties: {sorted(valid_parties)!r})"
        )

    # Scope enforcement
    if not _check_capabilities_subset(delegated_terms.capabilities, parent_terms.capabilities):
        excess = sorted(set(delegated_terms.capabilities) - set(parent_terms.capabilities))
        raise ValueError(
            f"Delegated capabilities exceed parent scope: {excess!r} not in "
            f"{sorted(parent_terms.capabilities)!r}"
        )

    # Validity enforcement
    if delegated_terms.valid_until > parent_exp:
        raise ValueError(
            f"Delegated valid_until {delegated_terms.valid_until.isoformat()} exceeds "
            f"parent expires_at {parent_exp.isoformat()}"
        )

    delegator_evidence = _build_evidence_dict(
        graph, delegator_sovereign_id, delegate_sovereign_id,
        signing_key, issued_by, ts,
    )

    record = DelegatedAgreementRecord(
        parent_id=_parent_id(parent),
        parent_kind=_parent_kind(parent),
        parent_terms_digest=terms_digest(parent_terms),
        delegator_sovereign_id=delegator_sovereign_id,
        delegate_sovereign_id=delegate_sovereign_id,
        delegated_terms=delegated_terms,
        delegator_evidence=delegator_evidence,
        delegate_evidence={},  # filled in by cosign_delegation
        graph_digest=graph_digest_from_export(graph),
        established_at=ts,
        expires_at=delegated_terms.valid_until,
    )
    sig = sign_model(record, signing_key, issued_by)
    return record.model_copy(update={"signatures": [sig]})


# ---------------------------------------------------------------------------
# cosign_delegation
# ---------------------------------------------------------------------------


def cosign_delegation(
    record: DelegatedAgreementRecord,
    graph: dict[str, Any],
    signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
    now: datetime | None = None,
) -> DelegatedAgreementRecord:
    """Add the delegate's signature and evidence to finalize a delegation.

    ``delegate_evidence`` is excluded from the canonical JSON (see
    ``DelegatedAgreementRecord.to_canonical_json``), so the delegate's signature
    is computed over the same canonical form the delegator signed.  Both
    signatures verify against the finalized record.

    The delegate's evidence is embedded for auditability but does not affect
    signature validity.
    """
    ts = _now(now)

    delegate_evidence = _build_evidence_dict(
        graph,
        record.delegate_sovereign_id,
        record.delegator_sovereign_id,
        signing_key, issued_by, ts,
    )

    # Sign the record as-is (delegate_evidence not in canonical form)
    sig = sign_model(record, signing_key, issued_by)
    return record.model_copy(update={
        "delegate_evidence": delegate_evidence,
        "signatures": list(record.signatures) + [sig],
    })


# ---------------------------------------------------------------------------
# verify_delegation_chain
# ---------------------------------------------------------------------------


def verify_delegation_chain(
    chain: DelegationChain,
    *,
    root_offerer_public_keys: list[str],
    root_responder_public_keys: list[str],
    per_hop_keys: dict[str, list[str]] | None = None,
) -> DelegationChainVerificationResult:
    """Verify a delegation chain from root to terminal.

    Checks:
    1. Root AgreementRecord has at least one signature from each key set.
    2. For each hop (in order):
       a. ``parent_id`` matches the prior record's ID.
       b. ``parent_terms_digest`` matches terms_digest(parent.agreed_terms).
       c. ``delegated_terms.capabilities ⊆ parent.agreed_terms.capabilities``.
       d. ``expires_at ≤ parent.expires_at``.
       e. At least one valid delegator signature.
       f. At least one valid delegate signature.

    Args:
        chain: DelegationChain (root + ordered hops).
        root_offerer_public_keys: Public keys for the root agreement offerer.
        root_responder_public_keys: Public keys for the root agreement responder.
        per_hop_keys: Optional dict mapping sovereign_id → list[public_key_b64].
            When provided, hop signatures are verified against the named key.
            When absent, signatures are verified against both party key lists
            if they match the sovereign IDs in the chain.

    Returns:
        DelegationChainVerificationResult with reason and failed_at_hop.
    """
    from .agreement import verify_agreement  # local import to avoid circularity

    n = len(chain.hops)
    if n == 0:
        return _reject("empty_chain", 0)

    # Verify root
    root_result = verify_agreement(
        chain.root,
        root_offerer_public_keys,
        root_responder_public_keys,
    )
    if not root_result.accepted:
        return _reject("root_agreement_invalid", n)

    # Walk hops
    prev: AgreementRecord | DelegatedAgreementRecord = chain.root

    for hop_index, hop in enumerate(chain.hops):
        hop_num = hop_index + 1  # 1-based for user-facing messages

        # Parent linkage
        if hop.parent_id != _parent_id(prev):
            return _reject("parent_id_mismatch", n, hop_num)

        # Parent terms digest
        expected_digest = terms_digest(_parent_agreed_terms(prev))
        if hop.parent_terms_digest != expected_digest:
            return _reject("terms_digest_mismatch", n, hop_num)

        # Scope enforcement
        parent_caps = _parent_agreed_terms(prev).capabilities
        if not _check_capabilities_subset(hop.delegated_terms.capabilities, parent_caps):
            return _reject("scope_escalation", n, hop_num)

        # Validity enforcement
        parent_exp = _parent_expires_at(prev)
        if hop.expires_at > parent_exp:
            return _reject("validity_escalation", n, hop_num)

        # Signature verification
        delegator_keys = _resolve_keys(hop.delegator_sovereign_id, per_hop_keys)
        delegate_keys = _resolve_keys(hop.delegate_sovereign_id, per_hop_keys)

        if not delegator_keys:
            return _reject("missing_delegator_signature", n, hop_num)
        if not delegate_keys:
            return _reject("missing_delegate_signature", n, hop_num)

        delegator_valid = any(
            verify_model_signature(hop, sig, pub)
            for sig in hop.signatures
            for pub in delegator_keys
        )
        if not delegator_valid:
            return _reject("invalid_delegator_signature", n, hop_num)

        delegate_valid = any(
            verify_model_signature(hop, sig, pub)
            for sig in hop.signatures
            for pub in delegate_keys
        )
        if not delegate_valid:
            return _reject("invalid_delegate_signature", n, hop_num)

        prev = hop

    return DelegationChainVerificationResult(
        accepted=True,
        reason="accepted",
        chain_length=n,
        failed_at_hop=None,
    )


def _resolve_keys(
    sovereign_id: str,
    per_hop_keys: dict[str, list[str]] | None,
) -> list[str]:
    """Return public keys for a sovereign from per_hop_keys, or empty list."""
    if per_hop_keys is None:
        return []
    return per_hop_keys.get(sovereign_id, [])
