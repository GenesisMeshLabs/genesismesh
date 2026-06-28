"""Distributed Consensus Authorization — public re-exports.

All symbols previously importable from ``genesis_mesh.trust.consensus``
remain importable unchanged.  Internal code should prefer the submodule
imports; this shim exists solely for backward compatibility.
"""

from .cascade import CascadeAssessmentReason, assess_cascade_risk
from .gate import ConsensusGate
from .identity import (
    EphemeralIdentityVerificationReason,
    EphemeralIdentityVerificationResult,
    issue_ephemeral_identity,
    verify_ephemeral_identity,
)
from .proof import (
    ConsensusProofVerificationReason,
    ConsensusProofVerificationResult,
    assemble_consensus_proof,
    verify_consensus_proof,
)
from .votes import cast_validator_vote

__all__ = [
    # cascade
    "CascadeAssessmentReason",
    "assess_cascade_risk",
    # votes
    "cast_validator_vote",
    # proof
    "ConsensusProofVerificationReason",
    "ConsensusProofVerificationResult",
    "assemble_consensus_proof",
    "verify_consensus_proof",
    # identity
    "EphemeralIdentityVerificationReason",
    "EphemeralIdentityVerificationResult",
    "issue_ephemeral_identity",
    "verify_ephemeral_identity",
    # gate
    "ConsensusGate",
]
