"""Node enrollment, heartbeat, and renewal routes."""

import hashlib
import json
import logging
import math
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from ..errors import (
    ApiError,
    BadRequestError,
    ForbiddenError,
    InternalServerError,
    RateLimitError,
    UnauthorizedError,
    positive_int_field,
    request_json_object,
)

logger = logging.getLogger(__name__)


def _parse_db_datetime(value: str) -> datetime:
    """Parse a persisted ISO datetime and normalize it to UTC."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _certificate_time_rejection(existing: dict) -> tuple[str, str] | None:
    """Return an error/reason pair when a persisted certificate is not currently valid."""
    now = datetime.now(timezone.utc)
    issued_at = _parse_db_datetime(existing["issued_at"])
    expires_at = _parse_db_datetime(existing["expires_at"])
    if issued_at > now:
        return "Certificate is not yet valid", "certificate_not_yet_valid"
    if expires_at <= now:
        return "Certificate expired; re-enrollment required", "certificate_expired"
    return None


def _token_fingerprint(token_id: str) -> str:
    """Return a non-secret token fingerprint for audit correlation."""
    return hashlib.sha256(token_id.encode("utf-8")).hexdigest()[:16]


def create_enrollment_blueprint(service) -> Blueprint:
    """Create enrollment routes bound to a Network Authority service."""
    bp = Blueprint("na_enrollment", __name__)

    @bp.route("/join", methods=["POST"])
    def request_join():
        """Issue a join certificate using a persisted invite token."""
        try:
            data = request_json_object()
            remote_addr = request.remote_addr or "unknown"
            if not service.rate_limiter.allow(f"join:{remote_addr}", 10, 60):
                raise RateLimitError()

            node_public_key = data.get("node_public_key")
            invite_token = data.get("invite_token")
            requested_validity_hours = positive_int_field(
                data,
                "validity_hours",
                default=168,
                code="invalid_validity_hours",
            )

            if not node_public_key:
                raise BadRequestError("node_public_key required", code="missing_node_public_key")
            if not invite_token:
                raise ForbiddenError("invite_token required", code="missing_invite_token")
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
                    raise ForbiddenError(
                        "Node public key has been compromised",
                        code="node_key_compromised",
                    )

            available_token = service.db.get_available_invite_token(invite_token)
            if available_token is None:
                if not service.rate_limiter.allow(f"join-token-fail:{remote_addr}", 3, 60):
                    raise RateLimitError()
                raise ForbiddenError(
                    "Invalid, expired, or used invite token",
                    code="invalid_invite_token",
                )

            auth_ok, auth_err = service._verify_request_signature(
                data,
                node_public_key,
                scope=f"join:{node_public_key}",
            )
            if not auth_ok:
                logger.warning("Join proof-of-possession failed for node key %s...: %s", node_public_key[:8], auth_err)
                raise UnauthorizedError(auth_err or "Unauthorized", code="node_auth_failed")

            token = service.db.use_invite_token(invite_token, node_public_key)
            if token is None:
                if not service.rate_limiter.allow(f"join-token-fail:{remote_addr}", 3, 60):
                    raise RateLimitError()
                raise ForbiddenError(
                    "Invalid, expired, or used invite token",
                    code="invalid_invite_token",
                )

            roles = token.assigned_roles
            validity_hours = min(requested_validity_hours, token.max_validity_hours)
            valid, error = service._validate_roles(roles)
            if not valid:
                raise BadRequestError(error or "Invalid role", code="invalid_role")

            cert = service._issue_join_certificate(
                node_public_key=node_public_key,
                roles=roles,
                validity_hours=validity_hours,
            )
            service.db.issue_cert(
                cert=cert,
                remote_addr=remote_addr,
                max_validity_hours=token.max_validity_hours,
            )
            service.db.add_audit_event(
                "certificate_issued",
                {
                    "cert_id": cert.cert_id,
                    "node_public_key": node_public_key,
                    "invite_token_fingerprint": _token_fingerprint(invite_token),
                    "roles": roles,
                    "remote_addr": remote_addr,
                },
            )

            service.connected_nodes[cert.cert_id] = {
                "node_public_key": node_public_key,
                "roles": roles,
                "status": "joined",
                "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                "remote_addr": remote_addr,
            }
            logger.info("Issued join certificate %s for roles %s", cert.cert_id, roles)
            return jsonify(cert.model_dump(mode="json")), 201
        except ApiError:
            raise
        except Exception as exc:
            raise InternalServerError() from exc

    @bp.route("/heartbeat", methods=["POST"])
    def heartbeat():
        """Receive a signed heartbeat from an enrolled node."""
        try:
            data = request_json_object()
            cert_id = data.get("cert_id")
            node_public_key = data.get("node_public_key")
            status = data.get("status", "unknown")

            if not cert_id or not node_public_key:
                raise BadRequestError(
                    "cert_id and node_public_key required",
                    code="missing_certificate_identity",
                )

            existing = service.db.get_cert(cert_id)
            if not existing:
                raise ForbiddenError("Unknown certificate", code="certificate_not_found")
            if existing.get("node_public_key") != node_public_key:
                raise ForbiddenError(
                    "Public key does not match certificate",
                    code="certificate_key_mismatch",
                )
            if existing.get("status") == "revoked":
                logger.warning(
                    "Rejected heartbeat for revoked certificate %s: %s",
                    cert_id,
                    existing.get("revocation_reason") or "revoked",
                )
                service.db.add_audit_event(
                    "heartbeat_rejected",
                    {
                        "cert_id": cert_id,
                        "reason": existing.get("revocation_reason") or "revoked",
                        "remote_addr": request.remote_addr or "unknown",
                    },
                )
                raise ForbiddenError("Certificate revoked", code="certificate_revoked")
            auth_ok, auth_err = service._verify_request_signature(data, node_public_key)
            if not auth_ok:
                logger.warning("Heartbeat auth failed for %s...: %s", cert_id[:8], auth_err)
                raise UnauthorizedError(auth_err or "Unauthorized", code="node_auth_failed")

            time_rejection = _certificate_time_rejection(existing)
            if time_rejection is not None:
                error, reason = time_rejection
                logger.warning("Rejected heartbeat for %s: %s", cert_id, reason)
                service.db.add_audit_event(
                    "heartbeat_rejected",
                    {
                        "cert_id": cert_id,
                        "reason": reason,
                        "remote_addr": request.remote_addr or "unknown",
                    },
                )
                raise ForbiddenError(error, code=reason)

            now = datetime.now(timezone.utc)
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
        except ApiError:
            raise
        except Exception as exc:
            raise InternalServerError() from exc

    @bp.route("/renew", methods=["POST"])
    def renew_certificate():
        """Renew a node certificate while preserving server-side roles."""
        try:
            data = request_json_object()
            cert_id = data.get("cert_id")
            node_public_key = data.get("node_public_key")
            validity_hours = positive_int_field(
                data,
                "validity_hours",
                default=168,
                code="invalid_validity_hours",
            )

            if not cert_id or not node_public_key:
                raise BadRequestError(
                    "cert_id and node_public_key required",
                    code="missing_certificate_identity",
                )

            existing_node = service.db.get_cert(cert_id)
            if not existing_node:
                logger.warning("Renewal request from unknown cert %s...", cert_id[:8])
                raise ForbiddenError(
                    "Unknown certificate. Cannot renew.",
                    code="certificate_not_found",
                )

            if existing_node.get("node_public_key") != node_public_key:
                logger.warning(
                    "Renewal key mismatch for cert %s...: expected %s, got %s",
                    cert_id[:8],
                    existing_node.get("node_public_key", "?")[:8],
                    node_public_key[:8],
                )
                raise ForbiddenError(
                    "Public key does not match certificate",
                    code="certificate_key_mismatch",
                )

            if existing_node.get("status") == "revoked":
                logger.warning(
                    "Rejected renewal for revoked certificate %s: %s",
                    cert_id,
                    existing_node.get("revocation_reason") or "revoked",
                )
                service.db.add_audit_event(
                    "renewal_rejected",
                    {
                        "cert_id": cert_id,
                        "reason": existing_node.get("revocation_reason") or "revoked",
                        "remote_addr": request.remote_addr or "unknown",
                    },
                )
                raise ForbiddenError("Certificate revoked", code="certificate_revoked")
            auth_ok, auth_err = service._verify_request_signature(data, node_public_key)
            if not auth_ok:
                logger.warning("Renewal auth failed for %s...: %s", cert_id[:8], auth_err)
                raise UnauthorizedError(auth_err or "Unauthorized", code="node_auth_failed")

            time_rejection = _certificate_time_rejection(existing_node)
            if time_rejection is not None:
                error, reason = time_rejection
                logger.warning("Rejected renewal for %s: %s", cert_id, reason)
                service.db.add_audit_event(
                    "renewal_rejected",
                    {
                        "cert_id": cert_id,
                        "reason": reason,
                        "remote_addr": request.remote_addr or "unknown",
                    },
                )
                raise ForbiddenError(error, code=reason)

            roles = json.loads(existing_node.get("roles_json", '["role:client"]'))
            if "roles" in data and sorted(data["roles"]) != sorted(roles):
                logger.warning(
                    "Renewal role escalation attempt for cert %s...: requested %s, authorized %s",
                    cert_id[:8],
                    data["roles"],
                    roles,
                )
                raise ForbiddenError(
                    "Role changes are not permitted during renewal",
                    code="renewal_role_change_forbidden",
                )
            max_validity_hours = existing_node.get("max_validity_hours")
            if max_validity_hours is None:
                issued_at = _parse_db_datetime(existing_node["issued_at"])
                expires_at = _parse_db_datetime(existing_node["expires_at"])
                max_validity_hours = max(
                    1,
                    math.ceil((expires_at - issued_at).total_seconds() / 3600),
                )

            requested_validity_hours = validity_hours
            capped_validity_hours = min(requested_validity_hours, int(max_validity_hours))
            if requested_validity_hours > capped_validity_hours:
                logger.info(
                    "Capped renewal validity for cert %s from %s to %s hours",
                    cert_id,
                    requested_validity_hours,
                    capped_validity_hours,
                )

            new_cert = service._issue_join_certificate(
                node_public_key=node_public_key,
                roles=roles,
                validity_hours=capped_validity_hours,
            )
            service.db.issue_cert(
                cert=new_cert,
                remote_addr=request.remote_addr or "unknown",
                renewed_from=cert_id,
                max_validity_hours=int(max_validity_hours),
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
        except ApiError:
            raise
        except Exception as exc:
            raise InternalServerError() from exc

    return bp
