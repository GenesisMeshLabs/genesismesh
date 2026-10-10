"""Changes made outside the controlled path (v1.3.0, Stage 2): routes.

Observers and controllers (authenticated by the registered key that signed the record):
  POST /evidence/observations                          submit a signed ObservationRecord
  POST /evidence/observations/batch                    submit a backlog of observations
  POST /evidence/break-glass                           submit a signed BreakGlassRecord

Operators (operator-signed headers):
  POST /admin/evidence/observations/<id>/judge         judge an observation (once)
  POST /admin/evidence/break-glass/<id>/judge          judge a break-glass record (once)
  GET  /admin/evidence/changes/<resource_id>           every change to a resource, with its state
  GET  /admin/evidence/operator-holders                operator key holders as the store records them
  POST /admin/operator-keys/<key_id>/holder            propose a holder change (privileged)
  POST /admin/operator-keys/holder-changes/<id>/approve approve it, as another holder (privileged)

The routes are beta until 1.5.0; the records' signed forms are frozen from 1.3.0.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, request

from ..errors import RateLimitError, UnauthorizedError, request_json_object

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService


def create_out_of_band_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    """Create observation, break-glass, judgement and holder routes."""
    bp = Blueprint("out_of_band", __name__)
    oob = service.out_of_band_service

    def _rate_key(prefix: str) -> str:
        return f"{prefix}:{request.remote_addr or 'unknown'}"

    def _submission() -> None:
        if not service.rate_limiter.allow(_rate_key("observations"), service.rate_limits.observations, 60):
            raise RateLimitError()
        oob.require_enabled()

    def _admin(data: dict, tier: str = "standard") -> str:
        if not service.rate_limiter.allow(_rate_key("admin"), service.rate_limits.admin, 60):
            raise RateLimitError()
        ok, err = service._verify_admin_request(data, required_tier=tier)  # type: ignore[arg-type]
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")
        return request.headers.get("X-Admin-Key-Id", "unknown")

    @bp.route("/evidence/observations", methods=["POST"])
    def submit_observation():
        """Admit one signed observation (judged at admission unless that is turned off)."""
        _submission()
        data = request_json_object()
        body, status = oob.submit_observation(data.get("observation"))
        return jsonify(body), status

    @bp.route("/evidence/observations/batch", methods=["POST"])
    def submit_observations():
        """Admit up to 100 observations in order of their change times; one result each."""
        _submission()
        data = request_json_object()
        return jsonify({"results": oob.submit_observations(data.get("observations"))})

    @bp.route("/evidence/break-glass", methods=["POST"])
    def submit_break_glass():
        """Admit one signed break-glass record (judged at admission unless that is turned off)."""
        _submission()
        data = request_json_object()
        body, status = oob.submit_break_glass(data.get("record"))
        return jsonify(body), status

    @bp.route("/admin/evidence/observations/<observation_id>/judge", methods=["POST"])
    def judge_observation(observation_id: str):
        """Judge an observation once; returns the existing judgement when it is already judged."""
        oob.require_enabled()
        _admin(request_json_object())
        body, status = oob.judge("observation", observation_id)
        return jsonify(body), status

    @bp.route("/admin/evidence/break-glass/<break_glass_id>/judge", methods=["POST"])
    def judge_break_glass(break_glass_id: str):
        """Judge a break-glass record once; returns the existing judgement when it is already judged."""
        oob.require_enabled()
        _admin(request_json_object())
        body, status = oob.judge("break_glass", break_glass_id)
        return jsonify(body), status

    @bp.route("/admin/evidence/changes/<path:resource_id>", methods=["GET"])
    def resource_changes(resource_id: str):
        """Every change to a resource: how it was governed and its state."""
        oob.require_enabled()
        _admin({}, tier="read")
        return jsonify(oob.resource_changes(resource_id))

    @bp.route("/admin/evidence/operator-holders", methods=["GET"])
    def operator_holders():
        """Operator key holders as the evidence store records them."""
        oob.require_enabled()
        _admin({}, tier="read")
        return jsonify({"holders": sorted(oob.operator_holders().values(), key=lambda h: h["key_id"])})

    @bp.route("/admin/operator-keys/<key_id>/holder", methods=["POST"])
    def propose_holder(key_id: str):
        """Propose a new holder for an operator key; another holder approves it."""
        data = request_json_object(required=True)
        operator = _admin(data, tier="privileged")
        return jsonify(oob.propose_holder(key_id, data.get("holder"), operator)), 201

    @bp.route("/admin/operator-keys/holder-changes/<proposal_id>/approve", methods=["POST"])
    def approve_holder(proposal_id: str):
        """Approve a holder change with a privileged key of a different holder."""
        data = request_json_object()
        operator = _admin(data, tier="privileged")
        return jsonify(oob.approve_holder(proposal_id, operator))

    return bp
