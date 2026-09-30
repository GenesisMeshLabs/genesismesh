"""Evidence store routes (v0.59).

Controllers:
  POST /evidence/execution                             submit signed ExecutionEvidence
                                                       (authenticated by a registered executor key)

Operators (operator-signed headers):
  GET  /admin/evidence                                 search stored entries
  GET  /admin/evidence/status                          store mode, size, last sequence
  GET  /admin/evidence/verify                          verify the whole store
  GET  /admin/evidence/resources/<resource_id>         one resource's history, verified
  GET  /admin/evidence/vendors/<vendor_id>             one vendor's history, verified
  GET  /admin/evidence/export                          gm.evidence.event JSON Lines
  GET  /admin/evidence/executor-keys                   registered executor keys
  POST /admin/evidence/executor-keys                   register an executor key (privileged)
  POST /admin/evidence/executor-keys/<key_id>/retire   retire an executor key (privileged)
  POST /admin/evidence/retention/apply                 apply retention (privileged)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flask import Blueprint, Response, jsonify, request

from ..errors import RateLimitError, UnauthorizedError, request_json_object

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService


def create_evidence_store_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    """Create evidence store submission, search, export and admin routes."""
    bp = Blueprint("evidence_store", __name__)
    store = service.evidence_store_service

    def _rate_key(prefix: str) -> str:
        return f"{prefix}:{request.remote_addr or 'unknown'}"

    def _admin(data: dict, tier: str = "standard") -> str:
        if not service.rate_limiter.allow(_rate_key("admin"), 30, 60):
            raise RateLimitError()
        ok, err = service._verify_admin_request(data, required_tier=tier)  # type: ignore[arg-type]
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")
        return request.headers.get("X-Admin-Key-Id", "unknown")

    def _query() -> dict[str, str]:
        return {k: v for k, v in request.args.items()}

    @bp.route("/evidence/execution", methods=["POST"])
    def submit_execution():
        """Validate and store one signed ExecutionEvidence record."""
        if not service.rate_limiter.allow(_rate_key("evidence_submit"), 120, 60):
            raise RateLimitError()
        store.require_enabled()
        data = request_json_object()
        body, created = store.submit_execution(data.get("evidence"))
        return jsonify({**body, "status": "recorded" if created else "duplicate"}), (201 if created else 200)

    @bp.route("/admin/evidence", methods=["GET"])
    def search():
        """Search stored entries by vendor, attestation, capability, resource, outcome or time."""
        store.require_enabled()
        _admin({})
        return jsonify(store.search(_query()))

    @bp.route("/admin/evidence/status", methods=["GET"])
    def status():
        """Store mode, size, last store sequence and latest retention checkpoint."""
        _admin({})
        return jsonify(store.status())

    @bp.route("/admin/evidence/verify", methods=["GET"])
    def verify():
        """Verify every stored entry, chain and signature."""
        store.require_enabled()
        _admin({})
        return jsonify(store.verify_store())

    @bp.route("/admin/evidence/resources/<path:resource_id>", methods=["GET"])
    def resource_history(resource_id: str):
        """Full history of one resource, decision to execution, with verification."""
        store.require_enabled()
        _admin({})
        return jsonify(store.resource_history(resource_id))

    @bp.route("/admin/evidence/vendors/<vendor_id>", methods=["GET"])
    def vendor_history(vendor_id: str):
        """A vendor's decisions and the evidence under them, with verification."""
        store.require_enabled()
        _admin({})
        return jsonify(store.vendor_history(vendor_id))

    @bp.route("/admin/evidence/export", methods=["GET"])
    def export():
        """gm.evidence.event JSON Lines from since_sequence, for SIEM pipelines."""
        store.require_enabled()
        _admin({})
        lines = store.export_lines(_query())
        body = "".join(line + "\n" for line in lines)
        return Response(body, mimetype="application/x-ndjson")

    @bp.route("/admin/evidence/executor-keys", methods=["GET"])
    def list_executor_keys():
        """Registered executor keys (public keys; retired keys included)."""
        store.require_enabled()
        _admin({})
        return jsonify({"executor_keys": store.list_executor_keys()})

    @bp.route("/admin/evidence/executor-keys", methods=["POST"])
    def register_executor_key():
        """Register a controller's executor signing key."""
        store.require_enabled()
        data = request_json_object()
        operator = _admin(data, tier="privileged")
        return jsonify(store.register_executor_key(data, operator)), 201

    @bp.route("/admin/evidence/executor-keys/<key_id>/retire", methods=["POST"])
    def retire_executor_key(key_id: str):
        """Retire an executor key: it verifies old records and signs no new ones."""
        store.require_enabled()
        data = request_json_object()
        operator = _admin(data, tier="privileged")
        return jsonify(store.retire_executor_key(key_id, operator))

    @bp.route("/admin/evidence/retention/apply", methods=["POST"])
    def apply_retention():
        """Remove a verifiable prefix of old entries behind a signed checkpoint."""
        store.require_enabled()
        data = request_json_object()
        operator = _admin(data, tier="privileged")
        return jsonify(store.apply_retention(data.get("older_than_days"), operator))

    return bp
