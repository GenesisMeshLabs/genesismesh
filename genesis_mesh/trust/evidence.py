"""Build and verify signed TrustEvidence records.

A TrustEvidence record is the portable, signed proof of a trust decision.
It lets a second sovereign verify -- offline, without sharing a backend --
that a named source sovereign evaluated trust toward a named target sovereign
at a specific time, over a specific recognition graph.

Key design points:
- ``build_trust_evidence`` accepts a ``TrustDecision`` (from
  ``evaluate_trust_decision``) plus signing material and produces a signed
  ``TrustEvidence`` record.
- ``verify_trust_evidence`` checks the Ed25519 signature and, when
  ``expected_graph_digest`` is supplied, binds the evidence to the graph state
  that produced it.  Signature check is always performed; digest binding is
  optional so evidence can be spot-checked without re-fetching the graph.
- ``graph_digest_from_export`` canonicalises a graph export to the same form
  the issuer used, so verifiers can derive the digest independently.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.evidence import TrustEvidence
from .decision import TrustDecision

EvidenceVerificationReason = Literal[
    "accepted",
    "missing_signature",
    "invalid_signature",
    "graph_digest_mismatch",
]


@dataclass(frozen=True)
class EvidenceVerificationResult:
    """Structured outcome of a trust evidence verification attempt."""

    accepted: bool
    reason: EvidenceVerificationReason
    evidence_id: str
    issuer_sovereign_id: str
    verdict: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "evidence_id": self.evidence_id,
            "issuer_sovereign_id": self.issuer_sovereign_id,
            "verdict": self.verdict,
        }


def graph_digest_from_export(graph: dict[str, Any]) -> str:
    """Return the SHA-256 hex digest of the canonical graph export.

    The graph is sorted by keys and serialised with compact separators before
    hashing, so the digest is deterministic regardless of insertion order.
    """
    canonical = json.dumps(graph, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_trust_evidence(
    decision: TrustDecision,
    issuer_sovereign_id: str,
    graph_digest: str,
    issued_by: str,
    signing_key: nacl.signing.SigningKey,
    *,
    metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> TrustEvidence:
    """Build and sign a TrustEvidence record from a trust decision.

    Args:
        decision: The ``TrustDecision`` returned by ``evaluate_trust_decision``.
        issuer_sovereign_id: Sovereign ID of the entity signing the evidence.
        graph_digest: SHA-256 hex digest of the recognition-graph export that
            was used to produce ``decision``.  Derive with
            ``graph_digest_from_export``.
        issued_by: Key identifier for the signing key (recorded in the
            ``Signature`` entry).
        signing_key: Ed25519 ``SigningKey`` used to sign the evidence body.
        metadata: Optional operator metadata to embed in the evidence.
        now: Issue timestamp; defaults to ``datetime.now(UTC)``.
    """
    evidence = TrustEvidence(
        issuer_sovereign_id=issuer_sovereign_id,
        source_sovereign_id=decision.source_sovereign_id,
        target_sovereign_id=decision.target_sovereign_id,
        verdict=decision.verdict,
        reason=decision.reason,
        requested_roles=list(decision.requested_roles),
        trusted=decision.trusted,
        hop_count=decision.hop_count,
        signals=[s.to_dict() for s in decision.signals],
        graph_digest=graph_digest,
        evaluated_at=decision.evaluated_at,
        issued_at=now or datetime.now(timezone.utc),
        issued_by=issued_by,
        metadata=metadata or {},
    )
    signature = sign_model(evidence, signing_key, issued_by)
    evidence.signatures.append(signature)
    return evidence


def verify_trust_evidence(
    evidence: TrustEvidence,
    issuer_public_keys: list[str],
    *,
    expected_graph_digest: str | None = None,
) -> EvidenceVerificationResult:
    """Verify a signed TrustEvidence record.

    Always checks the Ed25519 signature against ``issuer_public_keys``.
    When ``expected_graph_digest`` is supplied, additionally verifies that the
    evidence's ``graph_digest`` matches -- confirming the evidence was produced
    over the same graph state the verifier holds.

    Args:
        evidence: The TrustEvidence record to verify.
        issuer_public_keys: One or more base64 public keys accepted as the
            issuer's signing key.
        expected_graph_digest: Optional SHA-256 hex digest to enforce graph
            binding.  Derive from your local graph with
            ``graph_digest_from_export``.
    """
    if not evidence.signatures:
        return _reject(evidence, "missing_signature")

    signature_valid = False
    for sig in evidence.signatures:
        for pub_key in issuer_public_keys:
            if verify_model_signature(evidence, sig, pub_key):
                signature_valid = True
                break
        if signature_valid:
            break

    if not signature_valid:
        return _reject(evidence, "invalid_signature")

    if expected_graph_digest is not None:
        if evidence.graph_digest != expected_graph_digest:
            return _reject(evidence, "graph_digest_mismatch")

    return EvidenceVerificationResult(
        accepted=True,
        reason="accepted",
        evidence_id=evidence.evidence_id,
        issuer_sovereign_id=evidence.issuer_sovereign_id,
        verdict=evidence.verdict,
    )


def _reject(
    evidence: TrustEvidence,
    reason: EvidenceVerificationReason,
) -> EvidenceVerificationResult:
    return EvidenceVerificationResult(
        accepted=False,
        reason=reason,
        evidence_id=evidence.evidence_id,
        issuer_sovereign_id=evidence.issuer_sovereign_id,
        verdict=evidence.verdict,
    )
