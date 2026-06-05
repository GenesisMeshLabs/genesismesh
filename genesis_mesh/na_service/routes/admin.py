"""Administrative Network Authority routes."""

import hashlib
import logging
import uuid
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from ...crypto import sign_model
from ...models import PolicyManifest
from ..errors import (
    ApiError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    UnauthorizedError,
    positive_int_field,
    request_json_object,
)

logger = logging.getLogger(__name__)


def _token_fingerprint(token_id: str) -> str:
    """Return a non-secret token fingerprint for audit correlation."""
    return hashlib.sha256(token_id.encode("utf-8")).hexdigest()[:16]


def create_admin_blueprint(service) -> Blueprint:
    """Create admin routes bound to a Network Authority service."""
    bp = Blueprint("na_admin", __name__)

    @bp.route("/admin/invite", methods=["POST"])
    def create_invite():
        """Create a persisted invite token for a pre-authorized node."""
        try:
            data = request_json_object()
            remote_addr = request.remote_addr or "unknown"

            if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
                raise RateLimitError()

            auth_ok, auth_err = service._verify_admin_request(data)
            if not auth_ok:
                raise UnauthorizedError(auth_err or "Unauthorized", code="admin_auth_failed")

            roles = data.get("roles", ["role:client"])
            max_validity_hours = positive_int_field(
                data,
                "max_validity_hours",
                default=168,
                code="invalid_max_validity_hours",
                message="Token validity windows must be positive",
            )
            token_expiry_hours = positive_int_field(
                data,
                "token_expiry_hours",
                default=24,
                code="invalid_token_expiry_hours",
                message="Token validity windows must be positive",
            )

            valid, error = service._validate_roles(roles)
            if not valid:
                raise BadRequestError(error or "Invalid role", code="invalid_role")

            token = service.db.create_invite_token(
                assigned_roles=roles,
                max_validity_hours=max_validity_hours,
                token_expiry_hours=token_expiry_hours,
            )
            service.db.add_audit_event(
                "invite_created",
                {
                    "token_fingerprint": _token_fingerprint(token.token_id),
                    "roles": roles,
                    "remote_addr": remote_addr,
                },
            )

            logger.info("Created invite token for roles %s", roles)
            return jsonify(
                {
                    "token_id": token.token_id,
                    "expires_at": token.expires_at.isoformat(),
                }
            ), 201
        except ApiError:
            raise
        except Exception as exc:
            logger.error("Invite creation error: %s", exc)
            raise InternalServerError() from exc

    @bp.route("/admin/policy", methods=["POST"])
    def publish_policy():
        """Publish and activate a signed policy version."""
        try:
            data = request_json_object()
            remote_addr = request.remote_addr or "unknown"
            if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
                raise RateLimitError()

            auth_ok, auth_err = service._verify_admin_request(data)
            if not auth_ok:
                raise UnauthorizedError(auth_err or "Unauthorized", code="admin_auth_failed")

            policy = PolicyManifest(
                policy_id=data.get("policy_id") or f"policy-{uuid.uuid4()}",
                issued_at=datetime.now(timezone.utc),
                issued_by=service.key_id,
                min_client_version=data.get("min_client_version", "0.1.0"),
                allowed_ports=data.get("allowed_ports", [443, 8443]),
                allowed_services=data.get("allowed_services", []),
                routing=data.get("routing", {}),
                signatures=[],
            )
            policy.signatures.append(sign_model(policy, service.na_private_key, service.key_id))
            service.db.save_policy(policy, active=True)

            return jsonify(policy.model_dump(mode="json")), 201
        except ApiError:
            raise
        except Exception as exc:
            logger.error("Policy publish error: %s", exc)
            raise InternalServerError() from exc

    @bp.route("/admin/policy/history", methods=["GET"])
    def policy_history():
        """Return persisted policy versions."""
        auth_ok, auth_err = service._verify_admin_request({})
        if not auth_ok:
            raise UnauthorizedError(auth_err or "Unauthorized", code="admin_auth_failed")

        versions = []
        for row in service.db.list_policy_versions():
            policy = PolicyManifest.model_validate_json(row["policy_json"])
            versions.append(
                {
                    "policy_id": row["policy_id"],
                    "active": bool(row["active"]),
                    "created_at": row["created_at"],
                    "policy": policy.model_dump(mode="json"),
                }
            )
        return jsonify({"versions": versions})

    @bp.route("/admin/policy/rollback", methods=["POST"])
    def rollback_policy():
        """Activate a previously persisted policy version."""
        try:
            data = request_json_object()
            auth_ok, auth_err = service._verify_admin_request(data)
            if not auth_ok:
                raise UnauthorizedError(auth_err or "Unauthorized", code="admin_auth_failed")

            policy_id = data.get("policy_id")
            if not policy_id:
                raise BadRequestError("policy_id required", code="missing_policy_id")

            if not service.db.activate_policy(policy_id):
                raise NotFoundError("Unknown policy", code="policy_not_found")

            policy = service.db.get_active_policy()
            return jsonify(policy.model_dump(mode="json"))
        except ApiError:
            raise
        except Exception as exc:
            logger.error("Policy rollback error: %s", exc)
            raise InternalServerError() from exc

    @bp.route("/admin/revoke", methods=["POST"])
    def revoke_certificate():
        """Revoke an issued certificate and publish a new signed CRL."""
        try:
            data = request_json_object()
            remote_addr = request.remote_addr or "unknown"
            if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
                raise RateLimitError()

            auth_ok, auth_err = service._verify_admin_request(data)
            if not auth_ok:
                raise UnauthorizedError(auth_err or "Unauthorized", code="admin_auth_failed")

            cert_id = data.get("cert_id")
            reason = data.get("reason", "unspecified")
            allowed_reasons = {
                "key_compromise",
                "cessation_of_operation",
                "superseded",
                "unspecified",
            }

            if not cert_id:
                raise BadRequestError("cert_id required", code="missing_cert_id")
            if reason not in allowed_reasons:
                raise BadRequestError(
                    "Invalid revocation reason",
                    code="invalid_revocation_reason",
                )

            cert_row = service.db.get_cert(cert_id)
            if cert_row is None:
                raise NotFoundError("Unknown certificate", code="certificate_not_found")

            try:
                crl = service.db.revoke_cert(
                    cert_id=cert_id,
                    reason=reason,
                    issuer=service.key_id,
                )
            except KeyError:
                raise NotFoundError("Unknown certificate", code="certificate_not_found") from None

            if not crl.signatures:
                crl.signatures.append(sign_model(crl, service.na_private_key, service.key_id))
            service.db.save_crl(crl, active=True)
            service.db.add_audit_event(
                "certificate_revoked",
                {
                    "cert_id": cert_id,
                    "reason": reason,
                    "crl_sequence": crl.sequence,
                    "remote_addr": remote_addr,
                },
            )

            if cert_id in service.connected_nodes:
                service.connected_nodes[cert_id]["status"] = "revoked"
                service.connected_nodes[cert_id]["revocation_reason"] = reason

            revoked_node_key = cert_row.get("node_public_key")
            if revoked_node_key:
                evicted = service.db.evict_agent_registrations_for_revoked_keys(
                    [revoked_node_key]
                )
                if evicted:
                    logger.info(
                        "Evicted %s agent registration(s) for revoked certificate %s",
                        evicted,
                        cert_id,
                    )

            return jsonify(
                {
                    "crl_sequence": crl.sequence,
                    "revoked_count": len(crl.revoked_certificates),
                }
            )
        except ApiError:
            raise
        except Exception as exc:
            logger.error("Revocation error: %s", exc)
            raise InternalServerError() from exc

    return bp
