"""Flask blueprint registration for the Network Authority service."""

from .admin import create_admin_blueprint
from .crl import create_crl_blueprint
from .enrollment import create_enrollment_blueprint
from .health import create_health_blueprint
from .public import create_public_blueprint

__all__ = [
    "create_admin_blueprint",
    "create_crl_blueprint",
    "create_enrollment_blueprint",
    "create_health_blueprint",
    "create_public_blueprint",
]
