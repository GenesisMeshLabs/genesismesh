"""Flask blueprint registration for the Network Authority service."""

from .admin import create_admin_blueprint
from .agreement import create_agreement_blueprint
from .attestations import create_attestation_blueprint
from .boundary import create_boundary_blueprint
from .consensus import create_consensus_blueprint
from .crl import create_crl_blueprint
from .data_usage import create_data_usage_blueprint
from .disclosure import create_disclosure_blueprint
from .discovery import create_discovery_blueprint
from .enrollment import create_enrollment_blueprint
from .evidence import create_evidence_blueprint
from .health import create_health_blueprint
from .public import create_public_blueprint
from .treaties import create_treaty_blueprint

__all__ = [
    "create_admin_blueprint",
    "create_agreement_blueprint",
    "create_attestation_blueprint",
    "create_boundary_blueprint",
    "create_consensus_blueprint",
    "create_crl_blueprint",
    "create_data_usage_blueprint",
    "create_disclosure_blueprint",
    "create_discovery_blueprint",
    "create_enrollment_blueprint",
    "create_evidence_blueprint",
    "create_health_blueprint",
    "create_public_blueprint",
    "create_treaty_blueprint",
]
