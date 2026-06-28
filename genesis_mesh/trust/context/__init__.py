"""Relationship Context — BoundaryEngine and built-in gates.

All symbols previously importable from ``genesis_mesh.trust.context``
remain importable unchanged.
"""

from .decisions import (
    BoundaryDecisionVerificationReason,
    BoundaryDecisionVerificationResult,
    verify_boundary_decision,
)
from .engine import BoundaryEngine
from .gates import (
    GateCallable,
    capability_gate,
    freshness_gate,
    validity_window_gate,
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
]
