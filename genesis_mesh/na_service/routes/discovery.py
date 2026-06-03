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
            return jsonify({"error": "Rate limit exceeded"}), 429

        try:
            payload = request.get_json(force=True, silent=False)
        except Exception:
            return jsonify({"error": "request body must be valid JSON"}), 400
        if not isinstance(payload, dict):
            return jsonify({"error": "request body must be a JSON object"}), 400

        try:
            descriptor = AgentDescriptor.model_validate(payload)
        except Exception as exc:
            return jsonify({"error": f"invalid descriptor: {exc}"}), 400

        if not descriptor.signatures:
            return jsonify({"error": "descriptor must be signed by the node key"}), 401

        if not descriptor.is_active(datetime.now(timezone.utc)):
            return jsonify({"error": "descriptor expires_at is not in the future"}), 400

        if descriptor.network_name != service.genesis_block.network_name:
            return (
                jsonify(
                    {
                        "error": "descriptor network_name does not match this NA",
                        "expected": service.genesis_block.network_name,
                    }
                ),
                400,
            )

        if not _node_has_active_cert(service, descriptor.node_public_key):
            return (
                jsonify({"error": "node has no active join certificate"}),
                403,
            )

        if _node_is_revoked(service, descriptor.node_public_key):
            return jsonify({"error": "node key is revoked"}), 403

        # Signature must be by the node key itself.
        signature = descriptor.signatures[0]
        if not verify_model_signature(descriptor, signature, descriptor.node_public_key):
            return jsonify({"error": "invalid signature"}), 401

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
            return jsonify({"error": "agent not registered"}), 404
        return jsonify(descriptor.model_dump(mode="json"))

    @bp.route("/agents/<path:node_public_key>", methods=["DELETE"], strict_slashes=False)
    def delete_agent(node_public_key: str):
        """Voluntary deregistration. Requires a signed envelope."""
        try:
            body = request.get_json(force=True, silent=False) or {}
        except Exception:
            return jsonify({"error": "request body must be valid JSON"}), 400

        signature_b64 = body.get("signature")
        signed_at = body.get("signed_at")
        version = body.get("version", _DELETE_VERSION)
        if not signature_b64 or not signed_at:
            return jsonify({"error": "signature and signed_at required"}), 401

        try:
            ts = datetime.fromisoformat(signed_at)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            return jsonify({"error": "signed_at must be ISO datetime"}), 400

        if abs((datetime.now(timezone.utc) - ts).total_seconds()) > 300:
            return jsonify({"error": "signed_at outside ±5 min window"}), 401

        from ...crypto import verify_signature

        envelope = (
            f"delete-agent|{version}|{node_public_key}|{signed_at}".encode("utf-8")
        )
        if not verify_signature(envelope, signature_b64, node_public_key):
            return jsonify({"error": "invalid signature"}), 401

        removed = service.db.delete_agent_registration(node_public_key)
        if not removed:
            return jsonify({"error": "agent not registered"}), 404
        return jsonify({"status": "deregistered"}), 200

    return bp
