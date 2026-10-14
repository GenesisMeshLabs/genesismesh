"""Pre-issued grants (v1.6.0, Stage 5): routes.

Operators (operator-signed headers):
  POST /admin/grants                      issue a grant (privileged)
  GET  /admin/grants                      grants, newest first (read tier)
  GET  /admin/grants/<grant_id>           one grant, its state and its revocation (read tier)
  POST /admin/grants/<grant_id>/revoke    revoke a grant (privileged)

Holders (authenticated by the grant's bearer key, which signs the request or the record):
  POST /grants/time-tokens                a time token for a signed TimeTokenRequest
  POST /evidence/grant-executions         submit a signed GrantExecutionEvidence (one use)

The routes are beta; the records' signed forms are frozen from 1.6.0. With
``EVIDENCE_GRANTS=off`` (the default) every route answers ``404
grants_disabled`` once its caller is authenticated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, request

from ..errors import RateLimitError, UnauthorizedError, request_json_object

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService


def create_grants_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    """Create grant issuance, reading, revocation, time-token and use routes."""
    bp = Blueprint("grants", __name__)
    grants = service.grant_service

    def _rate_key(prefix: str) -> str:
        return f"{prefix}:{request.remote_addr or 'unknown'}"

    def _admin(data: dict, tier: str) -> str:
        if not service.rate_limiter.allow(_rate_key("admin"), service.rate_limits.admin, 60):
            raise RateLimitError()
        ok, err = service._verify_admin_request(data, required_tier=tier)  # type: ignore[arg-type]
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")
        return request.headers.get("X-Admin-Key-Id", "unknown")

    def _holder() -> None:
        # Holder routes share the evidence submission rate, as execution evidence does.
        if not service.rate_limiter.allow(_rate_key("evidence_submit"), service.rate_limits.evidence, 60):
            raise RateLimitError()
        grants.require_enabled()

    @bp.route("/admin/grants", methods=["POST"])
    def issue_grant():
        """Check a grant against every policy that applies, sign it and store it."""
        data = request_json_object(required=True)
        operator = _admin(data, "privileged")
        return jsonify(grants.issue(data, operator)), 201

    @bp.route("/admin/grants", methods=["GET"])
    def list_grants():
        """Grants, newest first: ?status=active|expired|revoked, ?bearer_key_id=, ?limit=, ?before=."""
        _admin({}, "read")
        return jsonify(grants.list_grants({k: v for k, v in request.args.items()}))

    @bp.route("/admin/grants/<grant_id>", methods=["GET"])
    def get_grant(grant_id: str):
        """One grant, its state (uses, status) and its revocation."""
        _admin({}, "read")
        return jsonify(grants.get(grant_id))

    @bp.route("/admin/grants/<grant_id>/revoke", methods=["POST"])
    def revoke_grant(grant_id: str):
        """Revoke a grant: uses executed from now on are refused."""
        data = request_json_object()
        operator = _admin(data, "privileged")
        return jsonify(grants.revoke(grant_id, data.get("reason"), operator))

    @bp.route("/grants/time-tokens", methods=["POST"])
    def time_token():
        """A time token for the holder of a grant (the request is signed by its bearer key)."""
        _holder()
        data = request_json_object()
        return jsonify(grants.issue_time_token(data.get("request"))), 201

    @bp.route("/evidence/grant-executions", methods=["POST"])
    def submit_grant_execution():
        """Admit one signed use of a grant; one refused for good is quarantined."""
        _holder()
        data = request_json_object()
        body, status = grants.submit_use(data.get("evidence"))
        return jsonify(body), status

    return bp
