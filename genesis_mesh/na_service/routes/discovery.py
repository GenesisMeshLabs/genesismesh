"""Agent discovery / service registry routes.

Endpoints:

- ``POST   /agents``                 register or refresh a signed descriptor
- ``GET    /agents``                 list live registrations, with ``?capability=`` filter
- ``GET    /agents/<node_key>``      fetch a specific registration
- ``DELETE /agents/<node_key>``      voluntary deregistration (signed)

Every write is authenticated by verifying the descriptor's signature against
the ``node_public_key`` it claims. The NA also refuses to register an entry
whose ``node_public_key`` does not own a currently-valid join certificate, or
whose key appears in the active CRL.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from ...crypto import verify_model_signature
from ...models import AgentDescriptor
from ..errors import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    RequestValidationError,
    UnauthorizedError,
    request_json_object,
)


logger = logging.getLogger(__name__)


_DELETE_VERSION = "v1"


def _node_has_active_cert(service, node_public_key: str) -> bool:
    """Return whether the node key owns at least one non-revoked, non-expired cert."""
    now = datetime.now(timezone.utc)
    for prior in service.db.get_certs_by_node_key(node_public_key):
        if prior.get("status") == "revoked":
            continue
        expires_at = prior.get("expires_at")
        if not expires_at:
            continue
        try:
            exp = datetime.fromisoformat(expires_at)
        except ValueError:
            continue
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp > now:
            return True
    return False


def _node_is_revoked(service, node_public_key: str) -> bool:
    """Return True if any cert for this node key is revoked for key_compromise."""
    for prior in service.db.get_certs_by_node_key(node_public_key):
        if (
            prior.get("status") == "revoked"
            and prior.get("revocation_reason") == "key_compromise"
        ):
            return True
    return False


def create_discovery_blueprint(service) -> Blueprint:
    """Create discovery routes bound to a Network Authority service."""
    bp = Blueprint("na_discovery", __name__)

    @bp.route("/agents", methods=["POST"])
    def register_agent():
        """Register or refresh a signed AgentDescriptor."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"discover:{remote_addr}", 30, 60):
            raise RateLimitError()

        payload = request_json_object(required=True)

        try:
            descriptor = AgentDescriptor.model_validate(payload)
        except Exception as exc:
            raise RequestValidationError(
                "invalid descriptor",
                code="invalid_agent_descriptor",
            ) from exc

        if not descriptor.signatures:
            raise UnauthorizedError(
                "descriptor must be signed by the node key",
                code="descriptor_signature_required",
            )

        if not descriptor.is_active(datetime.now(timezone.utc)):
            raise BadRequestError(
                "descriptor expires_at is not in the future",
                code="descriptor_expired",
            )

        if descriptor.network_name != service.genesis_block.network_name:
            raise BadRequestError(
                "descriptor network_name does not match this NA",
                code="descriptor_network_mismatch",
                details={"expected": service.genesis_block.network_name},
            )

        if not _node_has_active_cert(service, descriptor.node_public_key):
            raise ForbiddenError(
                "node has no active join certificate",
                code="node_has_no_active_certificate",
            )

        if _node_is_revoked(service, descriptor.node_public_key):
            raise ForbiddenError("node key is revoked", code="node_key_revoked")

        # Signature must be by the node key itself.
        signature = descriptor.signatures[0]
        if not verify_model_signature(descriptor, signature, descriptor.node_public_key):
            raise UnauthorizedError("invalid signature", code="invalid_signature")

        service.db.upsert_agent_registration(descriptor)
        logger.info(
            "Agent registered | agent_id=%s | node=%s | capabilities=%s",
            descriptor.agent_id,
            descriptor.node_public_key[:16],
            descriptor.capabilities,
        )
        return jsonify({"status": "registered", "expires_at": descriptor.expires_at.isoformat()}), 200

    @bp.route("/agents", methods=["GET"])
    def list_agents():
        """List live agent registrations, optionally filtered by capability."""
        capability = request.args.get("capability") or None
        descriptors = service.db.list_agent_registrations(capability=capability)
        return jsonify(
            {
                "count": len(descriptors),
                "agents": [d.model_dump(mode="json") for d in descriptors],
                "capability": capability,
            }
        )

    @bp.route("/agents/<path:node_public_key>", methods=["GET"], strict_slashes=False)
    def get_agent(node_public_key: str):
        """Return one registration."""
        descriptor = service.db.get_agent_registration(node_public_key)
        if descriptor is None:
            raise NotFoundError("agent not registered", code="agent_not_registered")
        return jsonify(descriptor.model_dump(mode="json"))

    @bp.route("/agents/<path:node_public_key>", methods=["DELETE"], strict_slashes=False)
    def delete_agent(node_public_key: str):
        """Voluntary deregistration. Requires a signed envelope."""
        body = request_json_object(required=True)

        signature_b64 = body.get("signature")
        signed_at = body.get("signed_at")
        version = body.get("version", _DELETE_VERSION)
        if not signature_b64 or not signed_at:
            raise UnauthorizedError(
                "signature and signed_at required",
                code="delete_signature_required",
            )

        try:
            ts = datetime.fromisoformat(signed_at)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            raise BadRequestError(
                "signed_at must be ISO datetime",
                code="invalid_signed_at",
            ) from None

        if abs((datetime.now(timezone.utc) - ts).total_seconds()) > 300:
            raise UnauthorizedError(
                "signed_at outside +/-5 min window",
                code="signed_at_outside_window",
            )

        from ...crypto import verify_signature

        envelope = (
            f"delete-agent|{version}|{node_public_key}|{signed_at}".encode("utf-8")
        )
        if not verify_signature(envelope, signature_b64, node_public_key):
            raise UnauthorizedError("invalid signature", code="invalid_signature")

        removed = service.db.delete_agent_registration(node_public_key)
        if not removed:
            raise NotFoundError("agent not registered", code="agent_not_registered")
        return jsonify({"status": "deregistered"}), 200

    return bp
