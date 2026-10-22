"""NA key history and key succession routes (v1.5.0, Stage 4).

Public:
  GET  /na/key-history       the genesis block, the successions and each key's validity

Operators (operator-signed headers):
  POST /admin/na/succession  record a succession the root key signed (privileged); the NA
                             countersigns it with the outgoing key
  POST /admin/na/reissue     re-issue, under the key that signs now, every record of a
                             succeeded key that outlives its horizon (privileged; 1.8.0)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, request

from ..errors import RateLimitError, UnauthorizedError, request_json_object

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService


def create_key_history_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    """Create the key history and succession routes."""
    bp = Blueprint("key_history", __name__)

    def _rate_key(prefix: str) -> str:
        return f"{prefix}:{request.remote_addr or 'unknown'}"

    @bp.route("/na/key-history", methods=["GET"])
    def key_history():
        """The NA's key history: what a verifier holding the root key needs to check NA signatures."""
        if not service.rate_limiter.allow(_rate_key("read"), service.rate_limits.read, 60):
            raise RateLimitError()
        return jsonify(service.key_history.public_view())

    @bp.route("/admin/na/succession", methods=["POST"])
    def succession():
        """Record a key succession: checked, countersigned by the outgoing key, stored."""
        if not service.rate_limiter.allow(_rate_key("admin"), service.rate_limits.admin, 60):
            raise RateLimitError()
        data = request_json_object(required=True)
        ok, err = service._verify_admin_request(data, required_tier="privileged")
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")
        operator = request.headers.get("X-Admin-Key-Id", "unknown")
        return jsonify(service.key_history.succeed(data, operator)), 201

    @bp.route("/admin/na/reissue", methods=["POST"])
    def reissue():
        """Re-issue every record of a succeeded key that outlives its horizon, now (1.8.0).

        The NA does this on its own once the new key signs; this runs it at
        once, without the batch limit. ``503`` while this instance's key may
        not sign.
        """
        if not service.rate_limiter.allow(_rate_key("admin"), service.rate_limits.admin, 60):
            raise RateLimitError()
        data = request_json_object()
        ok, err = service._verify_admin_request(data, required_tier="privileged")
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")
        return jsonify(service.reissue_service.run(all_due=True)), 200

    return bp
