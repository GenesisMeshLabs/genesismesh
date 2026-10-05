"""Network Authority application factory and service orchestration."""

import json
import logging
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from flask import Flask
import nacl.signing

from ..crypto import (
    public_key_from_b64,
    verify_model_signature,
)
from ..models import GenesisBlock, JoinCertificate, PolicyManifest
from ..models.revocation import CertificateRevocationList
from ..observability import configure_logging
from ..trust.context import GateRegistry
from .auth import (
    OperatorTier,
    load_operator_public_keys,
    load_operator_key_tiers,
    validate_operator_key_tiers,
    verify_admin_request,
    verify_node_request_signature,
)
from .db import NADatabase, expected_schema_version
from .db_policy import CrlSequenceConflict
from .errors import ConflictError, register_error_handlers
from .key_provider import KeyProviderConfig, Signer, as_signer, load_signer
from .rate_limit import RATE_LIMIT_STORES, DatabaseRateLimiter, RateLimiter, RateLimits
from .services import BoundaryPolicyService, EvidenceStoreService
from .services.evidence_store import EVIDENCE_STORE_MODES
from .services.boundary_policy import ENFORCEMENT_MODES
from .routes import (
    create_admin_blueprint,
    create_agreement_blueprint,
    create_attestation_blueprint,
    create_boundary_blueprint,
    create_boundary_policy_blueprint,
    create_consensus_blueprint,
    create_crl_blueprint,
    create_data_usage_blueprint,
    create_disclosure_blueprint,
    create_discovery_blueprint,
    create_enrollment_blueprint,
    create_evidence_blueprint,
    create_evidence_store_blueprint,
    create_health_blueprint,
    create_public_blueprint,
    create_treaty_blueprint,
)

logger = logging.getLogger(__name__)

HA_MODES = ("off", "on")
# v1.0.2: version 1 admin signatures (no method/path/query/audience binding).
ADMIN_LEGACY_SIGNATURE_MODES = ("reject", "accept")

#: Bounded retries when another instance publishes a CRL sequence first.
CRL_PUBLISH_ATTEMPTS = 5
#: Republish the active CRL when less than this much validity remains (v0.64.1).
CRL_REFRESH_MARGIN = timedelta(hours=12)
#: Validity of a published CRL, as for every other CRL the NA signs.
CRL_VALIDITY = timedelta(hours=24)


# Default request body limit (NA_MAX_REQUEST_BYTES); a revocation feed of ~50,000 ids fits.
DEFAULT_MAX_REQUEST_BYTES = 2 * 1024 * 1024

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
        na_private_key: "Signer | nacl.signing.SigningKey",
        key_id: str = "na-2025-q1",
        db_path: str = ":memory:",
        operator_public_keys: Optional[dict[str, str]] = None,
        operator_key_tiers: Optional[dict[str, str]] = None,
        renewal_grace_seconds: int = 900,
        gate_registry: Optional[GateRegistry] = None,
        boundary_policy_enforcement: str = "optional",
        evidence_store: str = "off",
        database_url: Optional[str] = None,
        ha_mode: str = "off",
        rate_limit_store: Optional[str] = None,
        max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
        rate_limits: Optional[RateLimits] = None,
        admin_legacy_signatures: str = "reject",
    ):
        """
        Initialize the Network Authority service.

        Args:
            genesis_block: Genesis block for the network.
            na_private_key: Network Authority signing key.
            key_id: Key identifier used in signatures.
            db_path: SQLite database path.
            operator_public_keys: Mapping of operator key IDs to public keys.
            operator_key_tiers: Mapping of operator key IDs to "standard" or
                "privileged". Required for every configured key (F-21).
            renewal_grace_seconds: How long a renewed certificate's predecessor
                stays usable before it is rejected and published in the CRL
                (F-20). Must outlast the node's renewal-retry backoff and CRL
                propagation; 0 revokes the predecessor immediately.
            gate_registry: Trusted, frozen registry of configurable gate types
                boundary policies may reference (v0.58). Defaults to the
                built-in gate types.
            boundary_policy_enforcement: "optional" (default) leaves the
                legacy /admin/boundary/decide route available; "required"
                refuses it so every decision goes through the policy-aware
                /admin/boundary/evaluate route.
            evidence_store: "off" (default) stores nothing; "on" keeps an
                append-only record of every decision and of the execution
                evidence controllers submit (v0.59).
            database_url: ``postgresql://...`` stores state in a shared
                PostgreSQL database so several instances can serve together
                (v0.60). Unset keeps the SQLite file at ``db_path``.
            ha_mode: "on" refuses to start unless the deployment can really
                run as several instances: PostgreSQL, a non-file key provider
                and the shared rate limiter (v0.60).
            rate_limit_store: "memory" (per process) or "database" (shared).
                Defaults to "database" on PostgreSQL and "memory" on SQLite.
            admin_legacy_signatures: "reject" (default) refuses version 1
                admin signatures, which do not cover the method, path, query
                or audience (v1.0.2); "accept" allows them for a
                migration window and audits every use.
        """
        self.genesis_block = genesis_block
        if admin_legacy_signatures not in ADMIN_LEGACY_SIGNATURE_MODES:
            raise ValueError(
                f"admin_legacy_signatures must be one of {ADMIN_LEGACY_SIGNATURE_MODES}"
            )
        self.admin_legacy_signatures = admin_legacy_signatures
        # v0.60: every NA signature goes through one Signer. ``na_private_key``
        # remains as an alias so existing callers keep working; it is the
        # Signer, never the raw key.
        self.signer = as_signer(na_private_key, key_id)
        self.na_private_key = self.signer
        self.key_id = key_id
        if ha_mode not in HA_MODES:
            raise ValueError(f"ha_mode must be one of {HA_MODES}")
        self.ha_mode = ha_mode
        self.instance_id = f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
        self.db = NADatabase(db_path, database_url=database_url)
        self.rate_limits = rate_limits or RateLimits()
        store = rate_limit_store or ("database" if self.db.backend == "postgres" else "memory")
        if store not in RATE_LIMIT_STORES:
            raise ValueError(f"rate_limit_store must be one of {RATE_LIMIT_STORES}")
        if ha_mode == "on":
            problems = []
            if self.db.backend != "postgres":
                problems.append("DATABASE_URL must select PostgreSQL")
            if self.signer.provider == "file":
                problems.append("the signing key must come from a non-file provider (azure-keyvault or env)")
            if store != "database":
                problems.append("the rate limiter must be the shared database store")
            if problems:
                raise ValueError("NA_HA_MODE=on refused: " + "; ".join(problems))
        self.db.migrate()
        self.operator_public_keys = operator_public_keys or {}
        # F-21: every configured operator key must declare a tier. Raising
        # here means a misconfigured deployment never starts, rather than
        # discovering the problem mid-incident.
        self.operator_key_tiers = operator_key_tiers or {}
        validate_operator_key_tiers(self.operator_public_keys, self.operator_key_tiers)
        self.rate_limiter: "RateLimiter | DatabaseRateLimiter" = (
            DatabaseRateLimiter(self.db) if store == "database" else RateLimiter()
        )
        self.connected_nodes: dict[str, dict] = {}
        self._nonce_max_age = 300.0
        self.renewal_grace_seconds = renewal_grace_seconds
        # In-process counter (not DB-backed: it must survive audit-store outages).
        self.audit_write_failures = 0

        if boundary_policy_enforcement not in ENFORCEMENT_MODES:
            raise ValueError(
                f"boundary_policy_enforcement must be one of {ENFORCEMENT_MODES}"
            )
        self.boundary_policy_enforcement = boundary_policy_enforcement
        registry = gate_registry if gate_registry is not None else GateRegistry.default()
        if not registry.frozen:
            # A registry that can still change at runtime is not a trusted set.
            raise ValueError("gate_registry must be frozen before the NA starts")
        self.gate_registry = registry
        self.boundary_policies = BoundaryPolicyService(self)
        if evidence_store not in EVIDENCE_STORE_MODES:
            raise ValueError(f"evidence_store must be one of {EVIDENCE_STORE_MODES}")
        self.evidence_store = evidence_store
        self.evidence_store_service = EvidenceStoreService(self)

        # F-11: verify genesis signatures before trusting the block, mirroring
        # the node-side check (node/node.py:_verify_genesis_block).
        if not genesis_block.signatures:
            logger.error("Genesis block has no signatures")
            raise ValueError("Genesis block signature verification failed")
        root_public_key = public_key_from_b64(genesis_block.root_public_key)
        for sig in genesis_block.signatures:
            if not verify_model_signature(genesis_block, sig, root_public_key):
                logger.error("Invalid genesis signature from key %s", sig.key_id)
                raise ValueError("Genesis block signature verification failed")

        na_pub_b64 = genesis_block.network_authority.public_key
        our_pub_b64 = self.signer.public_key_b64
        if na_pub_b64 != our_pub_b64:
            raise ValueError("NA private key does not match genesis block")

        self.app = Flask(__name__)
        # Bound every request body: public verify routes are unauthenticated,
        # and an unbounded JSON body is a memory denial of service (v0.62.0
        # security review). Larger bodies get 413 request_entity_too_large.
        if max_request_bytes <= 0:
            raise ValueError("max_request_bytes must be positive")
        self.app.config["MAX_CONTENT_LENGTH"] = max_request_bytes
        # Lets tooling (and test clients) reach the service from the app.
        self.app.extensions["genesis_mesh_na"] = self
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
        self.app.register_blueprint(create_boundary_policy_blueprint(self))
        self.app.register_blueprint(create_evidence_blueprint(self))
        self.app.register_blueprint(create_evidence_store_blueprint(self))
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

    def _verify_admin_request(
        self, data: dict, required_tier: OperatorTier = "standard"
    ) -> tuple[bool, str | None]:
        """Verify an admin request for compatibility with existing callers."""
        return verify_admin_request(self, data, required_tier)

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
        cert.signatures.append(self.signer.sign_model(cert))
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
        policy.signatures.append(self.signer.sign_model(policy))
        return policy

    def publish_crl(
        self,
        build: Callable[[], Optional[CertificateRevocationList]],
    ) -> Optional[CertificateRevocationList]:
        """Build, sign and save the next CRL, exactly once across instances (v0.60).

        ``build`` derives the next CRL from the current active one. If another
        instance takes the same sequence first, the save raises
        ``CrlSequenceConflict`` and the CRL is rebuilt from the new active
        CRL, so no revocation is lost and no sequence is reused.
        """
        for _ in range(CRL_PUBLISH_ATTEMPTS):
            crl = build()
            if crl is None:
                return None
            if not crl.signatures:
                crl.signatures.append(self.signer.sign_model(crl))
            try:
                self.db.save_crl(crl, active=True)
            except CrlSequenceConflict:
                logger.info("CRL sequence %s taken by another writer; rebuilding", crl.sequence)
                continue
            return crl
        raise ConflictError(
            "Could not publish the CRL: concurrent revocations kept taking the sequence",
            code="crl_publish_contention",
        )

    def _publish_superseded_revocations(self) -> Optional[CertificateRevocationList]:
        """Publish a signed CRL for renewal-superseded certs past their grace (F-20).

        Returns the newly published CRL, or None when nothing had matured. Called
        from the CRL read path so a booting node always fetches a swept list.
        """
        crl = self.publish_crl(lambda: self.db.sweep_superseded_certs(issuer=self.key_id))
        if crl is None:
            return None
        logger.info(
            "Published CRL sequence %s with %s revocation(s) after renewal grace",
            crl.sequence,
            len(crl.revoked_certificates),
        )
        return crl

    def _get_or_create_active_crl(self) -> CertificateRevocationList:
        """Return a fresh active CRL, creating or republishing it if needed.

        A CRL is valid for 24 hours. Before v0.64.1 the NA republished only when
        a revocation changed it, so a quiet NA served an expired CRL and every
        node and gateway reading it fell back to "not fresh". When less than
        ``CRL_REFRESH_MARGIN`` remains, the same revocations are re-signed
        under the next sequence number.
        """
        published = self._publish_superseded_revocations()
        if published is not None:
            return published

        def build() -> Optional[CertificateRevocationList]:
            current = self.db.get_active_crl()
            if current is None:
                return CertificateRevocationList.create_empty(issuer=self.key_id, sequence=0)
            now = datetime.now(timezone.utc)
            if current.next_update - now > CRL_REFRESH_MARGIN:
                return None
            return CertificateRevocationList(
                crl_id=str(uuid.uuid4()),
                sequence=current.sequence + 1,
                issued_at=now,
                next_update=now + CRL_VALIDITY,
                issuer=current.issuer,
                revoked_certificates=current.revoked_certificates,
                signatures=[],
            )

        self.publish_crl(build)
        crl = self.db.get_active_crl()
        if crl is None:  # pragma: no cover - publish_crl either saved one or found one
            raise ConflictError("No active CRL could be published", code="crl_publish_contention")
        return crl

    def readiness(self) -> tuple[bool, dict]:
        """Readiness for load-balancer probes (v0.60).

        Ready only when the database accepts writes at the expected schema
        version, the signing key is loaded, and (HA mode) the shared rate
        limiter is in use. Never includes secrets.
        """
        checks: dict = {"instance": self.instance_id, "ha_mode": self.ha_mode}
        ready = True
        db_info: dict = {"backend": self.db.backend, "expected_schema_version": expected_schema_version()}
        try:
            self.db.check_writable()
            db_info["writable"] = True
            db_info["schema_version"] = self.db.schema_version()
            if db_info["schema_version"] != db_info["expected_schema_version"]:
                ready = False
                db_info["error"] = "schema_version_mismatch"
        except Exception as exc:  # any database failure means not ready
            ready = False
            db_info["writable"] = False
            db_info["error"] = type(exc).__name__
        checks["database"] = db_info
        checks["signing_key"] = self.signer.describe()
        checks["rate_limiter"] = self.rate_limiter.store
        if not self.genesis_block:
            ready = False
        if self.ha_mode == "on" and self.rate_limiter.store != "database":
            ready = False
        return ready, checks


def create_app(
    genesis_block: GenesisBlock,
    na_private_key: "Signer | nacl.signing.SigningKey",
    db_path: str = "genesis_mesh_na.db",
    key_id: str = "na-2025-q1",
    operator_public_keys: Optional[dict[str, str]] = None,
    operator_key_tiers: Optional[dict[str, str]] = None,
    renewal_grace_seconds: int = 900,
    gate_registry: Optional[GateRegistry] = None,
    boundary_policy_enforcement: str = "optional",
    evidence_store: str = "off",
    database_url: Optional[str] = None,
    ha_mode: str = "off",
    rate_limit_store: Optional[str] = None,
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
    rate_limits: Optional[RateLimits] = None,
    admin_legacy_signatures: str = "reject",
) -> Flask:
    """Create a Flask app configured for WSGI servers."""
    service = NetworkAuthorityService(
        genesis_block=genesis_block,
        na_private_key=na_private_key,
        key_id=key_id,
        db_path=db_path,
        operator_public_keys=operator_public_keys,
        operator_key_tiers=operator_key_tiers,
        renewal_grace_seconds=renewal_grace_seconds,
        gate_registry=gate_registry,
        boundary_policy_enforcement=boundary_policy_enforcement,
        evidence_store=evidence_store,
        database_url=database_url,
        ha_mode=ha_mode,
        rate_limit_store=rate_limit_store,
        max_request_bytes=max_request_bytes,
        rate_limits=rate_limits,
        admin_legacy_signatures=admin_legacy_signatures,
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
    parser.add_argument(
        "--operator-key-tier",
        action="append",
        default=[],
        help="Operator key tier as key-id=read|standard|privileged (required per key)",
    )
    parser.add_argument("--db-path", default="genesis_mesh_na.db", help="SQLite database path")
    parser.add_argument(
        "--boundary-policy-enforcement",
        choices=ENFORCEMENT_MODES,
        default="optional",
        help="'required' refuses the legacy /admin/boundary/decide route",
    )
    parser.add_argument(
        "--evidence-store",
        choices=EVIDENCE_STORE_MODES,
        default="off",
        help="'on' keeps an append-only record of decisions and execution evidence",
    )
    args = parser.parse_args()

    configure_logging()

    with open(args.genesis, "r", encoding="utf-8") as f:
        genesis_block = GenesisBlock(**json.load(f))

    create_app(
        genesis_block=genesis_block,
        na_private_key=load_signer(
            KeyProviderConfig(provider="file", key_id=args.key_id, key_file=args.na_private_key)
        ),
        key_id=args.key_id,
        db_path=args.db_path,
        operator_public_keys=load_operator_public_keys(args.operator_public_key),
        operator_key_tiers=load_operator_key_tiers(args.operator_key_tier),
        boundary_policy_enforcement=args.boundary_policy_enforcement,
        evidence_store=args.evidence_store,
    )
    raise SystemExit(
        "Network Authority app factory validated. Start production service with "
        'gunicorn "genesis_mesh.na_service.wsgi:app".'
    )


if __name__ == "__main__":
    main()
