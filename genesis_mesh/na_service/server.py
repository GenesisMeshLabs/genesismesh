"""Network Authority application factory and service orchestration."""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import Flask
import nacl.encoding
import nacl.signing

from ..crypto import load_private_key, sign_model
from ..models import GenesisBlock, JoinCertificate, PolicyManifest
from ..models.revocation import CertificateRevocationList
from ..observability import configure_logging
from .auth import (
    load_operator_public_keys,
    verify_admin_request,
    verify_node_request_signature,
)
from .db import NADatabase
from .errors import register_error_handlers
from .rate_limit import RateLimiter
from .routes import (
    create_admin_blueprint,
    create_agreement_blueprint,
    create_attestation_blueprint,
    create_boundary_blueprint,
    create_consensus_blueprint,
    create_crl_blueprint,
    create_data_usage_blueprint,
    create_disclosure_blueprint,
    create_discovery_blueprint,
    create_enrollment_blueprint,
    create_evidence_blueprint,
    create_health_blueprint,
    create_public_blueprint,
    create_treaty_blueprint,
)

logger = logging.getLogger(__name__)


class NetworkAuthorityService:
    """
    Orchestrate Network Authority state, signing, persistence, and routes.

    HTTP routes are registered through Flask blueprints under
    ``genesis_mesh.na_service.routes`` so domain logic remains independently
    testable while this class keeps shared state and cryptographic helpers.
    """

    VALID_ROLE_PREFIXES = [
        "role:anchor",
        "role:bridge",
        "role:client",
        "role:operator",
        "role:service:",
    ]

    def __init__(
        self,
        genesis_block: GenesisBlock,
        na_private_key: nacl.signing.SigningKey,
        key_id: str = "na-2025-q1",
        db_path: str = ":memory:",
        operator_public_keys: Optional[dict[str, str]] = None,
    ):
        """
        Initialize the Network Authority service.

        Args:
            genesis_block: Genesis block for the network.
            na_private_key: Network Authority signing key.
            key_id: Key identifier used in signatures.
            db_path: SQLite database path.
            operator_public_keys: Mapping of operator key IDs to public keys.
        """
        self.genesis_block = genesis_block
        self.na_private_key = na_private_key
        self.key_id = key_id
        self.db = NADatabase(db_path)
        self.db.migrate()
        self.operator_public_keys = operator_public_keys or {}
        self.rate_limiter = RateLimiter()
        self.connected_nodes: dict[str, dict] = {}
        self._nonce_max_age = 300.0

        na_pub_b64 = genesis_block.network_authority.public_key
        our_pub_b64 = self.na_private_key.verify_key.encode(
            encoder=nacl.encoding.Base64Encoder
        ).decode("utf-8")
        if na_pub_b64 != our_pub_b64:
            raise ValueError("NA private key does not match genesis block")

        self.app = Flask(__name__)
        register_error_handlers(self.app)
        self._register_blueprints()
        logger.info(
            "Network Authority service initialized for network: %s",
            genesis_block.network_name,
        )

    def _register_blueprints(self) -> None:
        """Register domain blueprints on the Flask app."""
        self.app.register_blueprint(create_health_blueprint(self))
        self.app.register_blueprint(create_public_blueprint(self))
        self.app.register_blueprint(create_crl_blueprint(self))
        self.app.register_blueprint(create_admin_blueprint(self))
        self.app.register_blueprint(create_enrollment_blueprint(self))
        self.app.register_blueprint(create_discovery_blueprint(self))
        self.app.register_blueprint(create_attestation_blueprint(self))
        self.app.register_blueprint(create_treaty_blueprint(self))
        self.app.register_blueprint(create_agreement_blueprint(self))
        self.app.register_blueprint(create_boundary_blueprint(self))
        self.app.register_blueprint(create_evidence_blueprint(self))
        self.app.register_blueprint(create_disclosure_blueprint(self))
        self.app.register_blueprint(create_consensus_blueprint(self))
        self.app.register_blueprint(create_data_usage_blueprint(self))

    def _validate_roles(self, roles: list[str]) -> tuple[bool, str | None]:
        """
        Validate that all roles use allowed prefixes.

        Returns:
            ``(is_valid, error_message)``.
        """
        for role in roles:
            if not any(role.startswith(prefix) for prefix in self.VALID_ROLE_PREFIXES):
                return False, f"Invalid role: {role}"
        return True, None

    def _verify_request_signature(
        self,
        data: dict,
        node_public_key: str,
        scope: Optional[str] = None,
    ) -> tuple[bool, str | None]:
        """Verify a signed node request for compatibility with existing callers."""
        return verify_node_request_signature(self, data, node_public_key, scope)

    def _verify_admin_request(self, data: dict) -> tuple[bool, str | None]:
        """Verify an admin request for compatibility with existing callers."""
        return verify_admin_request(self, data)

    def _cleanup_nonces(self) -> None:
        """Remove expired nonces from replay protection storage."""
        self.db.cleanup_expired_nonces(int(self._nonce_max_age * 2))

    def _issue_join_certificate(
        self,
        node_public_key: str,
        roles: list[str],
        validity_hours: int,
    ) -> JoinCertificate:
        """
        Issue and sign a join certificate to a node.

        Args:
            node_public_key: Node public key encoded as base64.
            roles: Authorized roles to embed in the certificate.
            validity_hours: Certificate validity duration.

        Returns:
            Signed join certificate.
        """
        now = datetime.now(timezone.utc)
        cert = JoinCertificate(
            cert_id=str(uuid.uuid4()),
            node_public_key=node_public_key,
            network_name=self.genesis_block.network_name,
            roles=roles,
            issued_at=now,
            expires_at=now + timedelta(hours=validity_hours),
            issued_by=self.key_id,
            signatures=[],
        )
        cert.signatures.append(sign_model(cert, self.na_private_key, self.key_id))
        return cert

    def _get_default_policy(self) -> PolicyManifest:
        """Return the default signed policy manifest."""
        now = datetime.now(timezone.utc)
        policy = PolicyManifest(
            policy_id=(
                f"policy-{self.genesis_block.network_name}-"
                f"{self.genesis_block.network_version}"
            ),
            issued_at=now,
            issued_by=self.key_id,
            min_client_version="0.1.0",
            allowed_ports=[443, 8443],
            allowed_services=["service-1", "service-2"],
        )
        policy.signatures.append(sign_model(policy, self.na_private_key, self.key_id))
        return policy

    def _get_or_create_active_crl(self) -> CertificateRevocationList:
        """Return the active CRL, creating a signed empty one if needed."""
        crl = self.db.get_active_crl()
        if crl is not None:
            return crl

        crl = CertificateRevocationList.create_empty(
            issuer=self.key_id,
            sequence=0,
        )
        crl.signatures.append(sign_model(crl, self.na_private_key, self.key_id))
        self.db.save_crl(crl, active=True)
        return crl


def create_app(
    genesis_block: GenesisBlock,
    na_private_key: nacl.signing.SigningKey,
    db_path: str = "genesis_mesh_na.db",
    key_id: str = "na-2025-q1",
    operator_public_keys: Optional[dict[str, str]] = None,
) -> Flask:
    """Create a Flask app configured for WSGI servers."""
    service = NetworkAuthorityService(
        genesis_block=genesis_block,
        na_private_key=na_private_key,
        key_id=key_id,
        db_path=db_path,
        operator_public_keys=operator_public_keys,
    )
    return service.app


def main():
    """Validate Network Authority configuration from the command line."""
    import argparse

    parser = argparse.ArgumentParser(description="Network Authority Service")
    parser.add_argument("--genesis", required=True, help="Path to signed genesis block JSON")
    parser.add_argument("--na-private-key", required=True, help="Path to NA private key")
    parser.add_argument("--key-id", default="na-2025-q1", help="Key identifier")
    parser.add_argument(
        "--operator-public-key",
        action="append",
        default=[],
        help="Operator admin key as key-id=base64-public-key or key-id=path",
    )
    parser.add_argument("--db-path", default="genesis_mesh_na.db", help="SQLite database path")
    args = parser.parse_args()

    configure_logging()

    with open(args.genesis, "r", encoding="utf-8") as f:
        genesis_block = GenesisBlock(**json.load(f))

    create_app(
        genesis_block=genesis_block,
        na_private_key=load_private_key(args.na_private_key),
        key_id=args.key_id,
        db_path=args.db_path,
        operator_public_keys=load_operator_public_keys(args.operator_public_key),
    )
    raise SystemExit(
        "Network Authority app factory validated. Start production service with "
        'gunicorn "genesis_mesh.na_service.wsgi:app".'
    )


if __name__ == "__main__":
    main()
