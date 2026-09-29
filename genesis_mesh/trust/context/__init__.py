"""Relationship Context — BoundaryEngine and built-in gates.

All symbols previously importable from ``genesis_mesh.trust.context``
remain importable unchanged.
"""

from .decisions import (
    BoundaryDecisionVerificationReason,
    BoundaryDecisionVerificationResult,
    verify_boundary_decision,
)
from .engine import POLICY_RESOLUTION_GATE, BoundaryEngine
from .gates import (
    GateCallable,
    capability_gate,
    freshness_gate,
    validity_window_gate,
)
from .policy import (
    BoundaryPolicyVerificationResult,
    PolicyValidationIssue,
    PolicyValidationResult,
    ResolvedPolicySet,
    check_active_policy,
    evaluate_configured_gates,
    resolve_policies,
    selector_matches,
    sign_boundary_policy,
    validate_boundary_policy,
    verify_boundary_policy,
)
from .registry import (
    ConfiguredGateOutcome,
    ConfiguredGateType,
    GateRegistry,
    fact_inputs,
    fact_path_error,
    resolve_fact,
)

__all__ = [
    # engine
    "BoundaryEngine",
    # gates
    "GateCallable",
    "capability_gate",
    "validity_window_gate",
    "freshness_gate",
    # decisions
    "BoundaryDecisionVerificationReason",
    "BoundaryDecisionVerificationResult",
    "verify_boundary_decision",
    # declarative boundary policy (v0.57)
    "POLICY_RESOLUTION_GATE",
    "BoundaryPolicyVerificationResult",
    "ConfiguredGateOutcome",
    "ConfiguredGateType",
    "GateRegistry",
    "PolicyValidationIssue",
    "PolicyValidationResult",
    "ResolvedPolicySet",
    "check_active_policy",
    "evaluate_configured_gates",
    "fact_inputs",
    "fact_path_error",
    "resolve_fact",
    "resolve_policies",
    "selector_matches",
    "sign_boundary_policy",
    "validate_boundary_policy",
    "verify_boundary_policy",
]
