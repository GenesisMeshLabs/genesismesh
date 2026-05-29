"""Administrative Network Authority routes."""

import logging
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request

from ...crypto import sign_model
from ...models import PolicyManifest

logger = logging.getLogger(__name__)


def create_admin_blueprint(service) -> Blueprint:
    """Create admin routes bound to a Network Authority service."""
    bp = Blueprint("na_admin", __name__)

    @bp.route("/admin/invite", methods=["POST"])
    def create_invite():
        """Create a persisted invite token for a pre-authorized node."""
        try:
            data = request.get_json(silent=True) or {}
            remote_addr = request.remote_addr or "unknown"

            if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
                return jsonify({"error": "Rate limit exceeded"}), 429

            auth_ok, auth_err = service._verify_admin_request(data)
            if not auth_ok:
                return jsonify({"error": auth_err}), 401

            roles = data.get("roles", ["role:client"])
            max_validity_hours = int(data.get("max_validity_hours", 168))
            token_expiry_hours = int(data.get("token_expiry_hours", 24))

            valid, error = service._validate_roles(roles)
            if not valid:
                return jsonify({"error": error}), 400

            if max_validity_hours <= 0 or token_expiry_hours <= 0:
                return jsonify({"error": "Token validity windows must be positive"}), 400

            token = service.db.create_invite_token(
                assigned_roles=roles,
                max_validity_hours=max_validity_hours,
                token_expiry_hours=token_expiry_hours,
            )
            service.db.add_audit_event(
                "invite_created",
                {
                    "token_id": token.token_id,
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
        except Exception as exc:
            logger.error("Invite creation error: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/admin/policy", methods=["POST"])
    def publish_policy():
        """Publish and activate a signed policy version."""
        try:
            data = request.get_json(silent=True) or {}
            remote_addr = request.remote_addr or "unknown"
            if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
                return jsonify({"error": "Rate limit exceeded"}), 429

            auth_ok, auth_err = service._verify_admin_request(data)
            if not auth_ok:
                return jsonify({"error": auth_err}), 401

            policy = PolicyManifest(
                policy_id=data.get("policy_id") or f"policy-{uuid.uuid4()}",
                issued_at=datetime.utcnow(),
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
        except Exception as exc:
            logger.error("Policy publish error: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/admin/policy/history", methods=["GET"])
    def policy_history():
        """Return persisted policy versions."""
        auth_ok, auth_err = service._verify_admin_request({})
        if not auth_ok:
            return jsonify({"error": auth_err}), 401

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
            data = request.get_json(silent=True) or {}
            auth_ok, auth_err = service._verify_admin_request(data)
            if not auth_ok:
                return jsonify({"error": auth_err}), 401

            policy_id = data.get("policy_id")
            if not policy_id:
                return jsonify({"error": "policy_id required"}), 400

            if not service.db.activate_policy(policy_id):
                return jsonify({"error": "Unknown policy"}), 404

            policy = service.db.get_active_policy()
            return jsonify(policy.model_dump(mode="json"))
        except Exception as exc:
            logger.error("Policy rollback error: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/admin/revoke", methods=["POST"])
    def revoke_certificate():
        """Revoke an issued certificate and publish a new signed CRL."""
        try:
            data = request.get_json(silent=True) or {}
            remote_addr = request.remote_addr or "unknown"
            if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
                return jsonify({"error": "Rate limit exceeded"}), 429

            auth_ok, auth_err = service._verify_admin_request(data)
            if not auth_ok:
                return jsonify({"error": auth_err}), 401

            cert_id = data.get("cert_id")
            reason = data.get("reason", "unspecified")
            allowed_reasons = {
                "key_compromise",
                "cessation_of_operation",
                "superseded",
                "unspecified",
            }

            if not cert_id:
                return jsonify({"error": "cert_id required"}), 400
            if reason not in allowed_reasons:
                return jsonify({"error": "Invalid revocation reason"}), 400

            try:
                crl = service.db.revoke_cert(
                    cert_id=cert_id,
                    reason=reason,
                    issuer=service.key_id,
                )
            except KeyError:
                return jsonify({"error": "Unknown certificate"}), 404

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

            return jsonify(
                {
                    "crl_sequence": crl.sequence,
                    "revoked_count": len(crl.revoked_certificates),
                }
            )
        except Exception as exc:
            logger.error("Revocation error: %s", exc)
            return jsonify({"error": str(exc)}), 500

    return bp
