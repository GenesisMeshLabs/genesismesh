"""Node enrollment, heartbeat, and renewal routes."""

import json
import logging
from datetime import datetime

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)


def create_enrollment_blueprint(service) -> Blueprint:
    """Create enrollment routes bound to a Network Authority service."""
    bp = Blueprint("na_enrollment", __name__)

    @bp.route("/join", methods=["POST"])
    def request_join():
        """Issue a join certificate using a persisted invite token."""
        try:
            data = request.get_json(silent=True) or {}
            remote_addr = request.remote_addr or "unknown"
            if not service.rate_limiter.allow(f"join:{remote_addr}", 10, 60):
                return jsonify({"error": "Rate limit exceeded"}), 429

            node_public_key = data.get("node_public_key")
            invite_token = data.get("invite_token")
            requested_validity_hours = int(data.get("validity_hours", 168))

            if not node_public_key:
                return jsonify({"error": "node_public_key required"}), 400
            if not invite_token:
                return jsonify({"error": "invite_token required"}), 403

            for prior in service.db.get_certs_by_node_key(node_public_key):
                if (
                    prior.get("status") == "revoked"
                    and prior.get("revocation_reason") == "key_compromise"
                ):
                    service.db.add_audit_event(
                        "join_rejected",
                        {
                            "reason": "key_compromise",
                            "node_public_key": node_public_key,
                            "prior_cert_id": prior.get("cert_id"),
                            "remote_addr": remote_addr,
                        },
                    )
                    return jsonify({"error": "Node public key has been compromised"}), 403

            token = service.db.use_invite_token(invite_token, node_public_key)
            if token is None:
                if not service.rate_limiter.allow(f"join-token-fail:{remote_addr}", 3, 60):
                    return jsonify({"error": "Rate limit exceeded"}), 429
                return jsonify({"error": "Invalid, expired, or used invite token"}), 403

            roles = token.assigned_roles
            validity_hours = min(requested_validity_hours, token.max_validity_hours)
            valid, error = service._validate_roles(roles)
            if not valid:
                return jsonify({"error": error}), 400

            cert = service._issue_join_certificate(
                node_public_key=node_public_key,
                roles=roles,
                validity_hours=validity_hours,
            )
            service.db.issue_cert(cert=cert, remote_addr=remote_addr)
            service.db.add_audit_event(
                "certificate_issued",
                {
                    "cert_id": cert.cert_id,
                    "node_public_key": node_public_key,
                    "invite_token": invite_token,
                    "roles": roles,
                    "remote_addr": remote_addr,
                },
            )

            service.connected_nodes[cert.cert_id] = {
                "node_public_key": node_public_key,
                "roles": roles,
                "status": "joined",
                "last_heartbeat": datetime.utcnow().isoformat(),
                "remote_addr": remote_addr,
            }
            logger.info("Issued join certificate %s for roles %s", cert.cert_id, roles)
            return jsonify(cert.model_dump(mode="json")), 201
        except Exception as exc:
            logger.error("Error issuing certificate: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/heartbeat", methods=["POST"])
    def heartbeat():
        """Receive a signed heartbeat from an enrolled node."""
        try:
            data = request.get_json(silent=True) or {}
            cert_id = data.get("cert_id")
            node_public_key = data.get("node_public_key")
            status = data.get("status", "unknown")

            if not cert_id or not node_public_key:
                return jsonify({"error": "cert_id and node_public_key required"}), 400

            existing = service.db.get_cert(cert_id)
            if not existing:
                return jsonify({"error": "Unknown certificate"}), 403
            if existing.get("node_public_key") != node_public_key:
                return jsonify({"error": "Public key does not match certificate"}), 403
            if existing.get("status") == "revoked":
                service.db.add_audit_event(
                    "heartbeat_rejected",
                    {
                        "cert_id": cert_id,
                        "reason": "revoked",
                        "remote_addr": request.remote_addr or "unknown",
                    },
                )
                return jsonify({"error": "Certificate revoked"}), 403

            auth_ok, auth_err = service._verify_request_signature(data, node_public_key)
            if not auth_ok:
                logger.warning("Heartbeat auth failed for %s...: %s", cert_id[:8], auth_err)
                return jsonify({"error": auth_err}), 401

            now = datetime.utcnow()
            service.db.mark_heartbeat(
                cert_id=cert_id,
                status=status,
                remote_addr=request.remote_addr or "unknown",
            )
            mirror_info = service.connected_nodes.get(cert_id, {})
            service.connected_nodes[cert_id] = {
                **mirror_info,
                "node_public_key": node_public_key,
                "roles": json.loads(existing.get("roles_json", "[]")),
                "status": status,
                "last_heartbeat": now.isoformat(),
                "remote_addr": request.remote_addr,
            }

            logger.debug("Heartbeat from node %s... status=%s", cert_id[:8], status)
            return jsonify({"ack": True, "server_time": now.isoformat()})
        except Exception as exc:
            logger.error("Heartbeat error: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/renew", methods=["POST"])
    def renew_certificate():
        """Renew a node certificate while preserving server-side roles."""
        try:
            data = request.get_json(silent=True) or {}
            cert_id = data.get("cert_id")
            node_public_key = data.get("node_public_key")
            validity_hours = data.get("validity_hours", 168)

            if not cert_id or not node_public_key:
                return jsonify({"error": "cert_id and node_public_key required"}), 400

            existing_node = service.db.get_cert(cert_id)
            if not existing_node:
                logger.warning("Renewal request from unknown cert %s...", cert_id[:8])
                return jsonify({"error": "Unknown certificate. Cannot renew."}), 403

            if existing_node.get("node_public_key") != node_public_key:
                logger.warning(
                    "Renewal key mismatch for cert %s...: expected %s, got %s",
                    cert_id[:8],
                    existing_node.get("node_public_key", "?")[:8],
                    node_public_key[:8],
                )
                return jsonify({"error": "Public key does not match certificate"}), 403

            if existing_node.get("status") == "revoked":
                service.db.add_audit_event(
                    "renewal_rejected",
                    {
                        "cert_id": cert_id,
                        "reason": "revoked",
                        "remote_addr": request.remote_addr or "unknown",
                    },
                )
                return jsonify({"error": "Certificate revoked"}), 403

            auth_ok, auth_err = service._verify_request_signature(data, node_public_key)
            if not auth_ok:
                logger.warning("Renewal auth failed for %s...: %s", cert_id[:8], auth_err)
                return jsonify({"error": auth_err}), 401

            roles = json.loads(existing_node.get("roles_json", '["role:client"]'))
            if "roles" in data and sorted(data["roles"]) != sorted(roles):
                logger.warning(
                    "Renewal role escalation attempt for cert %s...: requested %s, authorized %s",
                    cert_id[:8],
                    data["roles"],
                    roles,
                )
                return jsonify({"error": "Role changes are not permitted during renewal"}), 403

            new_cert = service._issue_join_certificate(
                node_public_key=node_public_key,
                roles=roles,
                validity_hours=validity_hours,
            )
            service.db.issue_cert(
                cert=new_cert,
                remote_addr=request.remote_addr or "unknown",
                renewed_from=cert_id,
            )
            service.db.add_audit_event(
                "certificate_renewed",
                {
                    "old_cert_id": cert_id,
                    "new_cert_id": new_cert.cert_id,
                    "node_public_key": node_public_key,
                },
            )

            old_info = service.connected_nodes.pop(cert_id, {})
            service.connected_nodes[new_cert.cert_id] = {
                **old_info,
                "node_public_key": node_public_key,
                "roles": roles,
                "renewed_from": cert_id,
            }
            logger.info("Renewed certificate %s... -> %s...", cert_id[:8], new_cert.cert_id[:8])
            return jsonify(new_cert.model_dump(mode="json")), 201
        except Exception as exc:
            logger.error("Renewal error: %s", exc)
            return jsonify({"error": str(exc)}), 500

    return bp
