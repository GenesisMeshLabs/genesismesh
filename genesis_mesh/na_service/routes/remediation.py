"""Remediation, reviews and notification (v1.4.0, Stage 3): routes.

Controllers (authenticated by the registered executor key that signed the record):
  POST /evidence/remediations                              submit a signed RemediationRecord

Operators (operator-signed headers):
  GET  /admin/evidence/remediations                        the due queue (?state=, paged)
  GET  /admin/evidence/remediations/<subject_id>           one subject's state, reviews and records
  POST /admin/evidence/remediations/<subject_id>/notified  record that the actor was told
  POST /admin/evidence/reviews                             request a review (standard)
  GET  /admin/evidence/reviews/<review_id>                 a review, pending or decided
  POST /admin/evidence/reviews/<review_id>/decide          decide it, as a second holder (privileged)

The routes are beta until 1.5.0; the records' signed forms are frozen from 1.4.0.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, request

from ..errors import RateLimitError, UnauthorizedError, request_json_object

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService


def create_remediation_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    """Create remediation, review and due-queue routes."""
    bp = Blueprint("remediation", __name__)
    remediation = service.remediation_service

    def _rate_key(prefix: str) -> str:
        return f"{prefix}:{request.remote_addr or 'unknown'}"

    # Operators authenticate before learning whether the records are kept.
    def _admin(data: dict, tier: str = "standard") -> str:
        if not service.rate_limiter.allow(_rate_key("admin"), service.rate_limits.admin, 60):
            raise RateLimitError()
        ok, err = service._verify_admin_request(data, required_tier=tier)  # type: ignore[arg-type]
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")
        return request.headers.get("X-Admin-Key-Id", "unknown")

    def _approval(data: dict, key_id: str) -> dict[str, Any]:
        """The operator's signed request, as the NA verified it (signature version 2)."""
        return {
            "key_id": key_id,
            "public_key": service.operator_public_keys[key_id],
            "method": request.method,
            "path": request.path,
            "query": request.args.to_dict(flat=False),
            "audience": service.genesis_block.network_authority.public_key,
            "body": data,
            "timestamp": request.headers.get("X-Admin-Timestamp", ""),
            "nonce": request.headers.get("X-Admin-Nonce", ""),
            "admin_signature": request.headers.get("X-Admin-Signature", ""),
        }

    @bp.route("/evidence/remediations", methods=["POST"])
    def submit_remediation():
        """Admit one signed remediation record (a cancel carried out, or an alert)."""
        if not service.rate_limiter.allow(_rate_key("evidence_submit"), service.rate_limits.evidence, 60):
            raise RateLimitError()
        remediation.require_enabled()
        data = request_json_object()
        body, status = remediation.submit_remediation(data.get("record"))
        return jsonify(body), status

    @bp.route("/admin/evidence/remediations", methods=["GET"])
    def due_queue():
        """Remediations and reviews by state (default: remediation_due, overdue, review_pending, waived)."""
        _admin({}, tier="read")
        return jsonify(remediation.queue({k: v for k, v in request.args.items()}))

    @bp.route("/admin/evidence/remediations/<subject_id>", methods=["GET"])
    def get_remediation(subject_id: str):
        """One judgement's or decision's remediation state, its reviews and its stored records."""
        _admin({}, tier="read")
        return jsonify(remediation.get(subject_id))

    @bp.route("/admin/evidence/remediations/<subject_id>/notified", methods=["POST"])
    def record_notice(subject_id: str):
        """Record that the controller told the actor: an audit event and notified_at."""
        data = request_json_object()
        operator = _admin(data)
        return jsonify(remediation.record_notice(subject_id, data, operator))

    @bp.route("/admin/evidence/reviews", methods=["POST"])
    def request_review():
        """Ask a second holder to review a judged change or a decision, with a justification."""
        data = request_json_object(required=True)
        operator = _admin(data)
        return jsonify(remediation.request_review(data, operator, _approval(data, operator))), 201

    @bp.route("/admin/evidence/reviews/<review_id>", methods=["GET"])
    def get_review(review_id: str):
        """A review: pending (its request) or decided (its signed record)."""
        _admin({}, tier="read")
        return jsonify(remediation.get_review(review_id))

    @bp.route("/admin/evidence/reviews/<review_id>/decide", methods=["POST"])
    def decide_review(review_id: str):
        """Uphold, deny or waive (until a time) as a privileged key of another holder."""
        data = request_json_object(required=True)
        operator = _admin(data, tier="privileged")
        return jsonify(remediation.decide_review(review_id, data, operator, _approval(data, operator)))

    return bp
