"""Boundary decision routes — decide, verify."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, request

from ...models.context import ContextRecord
from ...trust.agreement import AgreementRecord
from ...trust.context.decisions import BoundaryDecision, verify_boundary_decision
from ...trust.context.engine import BoundaryEngine
from ..errors import (
    BadRequestError,
    ConflictError,
    RateLimitError,
    RequestValidationError,
    UnauthorizedError,
    request_json_object,
)
from ...models.canonical_registry import strict_refusal
from ..services.boundary_policy import agreement_parties

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService

logger = logging.getLogger(__name__)


def _j(model) -> dict:
    return json.loads(model.model_dump_json())


def _legacy_decision_json(decision: BoundaryDecision) -> dict:
    """Serialise a /decide result exactly as v0.56 did (no policy_binding key)."""
    return json.loads(decision.model_dump_json(exclude={"policy_binding"}))


def create_boundary_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    """Create boundary decision routes — decide, verify."""
    bp = Blueprint("boundary", __name__)

    def _pub_b64() -> str:
        return service.signer.public_key_b64

    def _rate_key(prefix: str) -> str:
        return f"{prefix}:{request.remote_addr or 'unknown'}"

    @bp.route("/admin/boundary/decide", methods=["POST"])
    def decide():
        """Evaluate a ContextRecord against an AgreementRecord and sign the decision."""
        if not service.rate_limiter.allow(_rate_key("admin"), service.rate_limits.admin, 60):
            raise RateLimitError()
        data = request_json_object()
        ok, err = service._verify_admin_request(data)
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")

        # v0.58: with policy enforcement required, the policy-free legacy path
        # would be a bypass. Refuse it and point callers at the evaluate route.
        if service.boundary_policy_enforcement == "required":
            service.db.add_audit_event("boundary_legacy_decide_refused", {
                "requested_capability": data.get("requested_capability"),
            })
            raise ConflictError(
                "Boundary policy enforcement is required; use /admin/boundary/evaluate",
                code="boundary_policy_required",
            )

        raw_agreement = data.get("agreement")
        capability = data.get("requested_capability")
        if not raw_agreement or not capability:
            raise BadRequestError(
                "agreement and requested_capability are required",
                code="missing_boundary_fields",
            )
        try:
            agreement = AgreementRecord.model_validate(raw_agreement)
        except Exception as exc:
            raise BadRequestError("Invalid agreement object", code="invalid_agreement") from exc
        service.agreements.require_trusted(agreement, route="/admin/boundary/decide")

        ctx_data = data.get("context") or {}
        if not isinstance(ctx_data, dict):
            raise BadRequestError("context must be an object", code="invalid_context")
        requester, provider = agreement_parties(ctx_data, agreement)
        try:
            context = ContextRecord(
                context_id=ctx_data.get("context_id") or str(uuid.uuid4()),
                agreement_id=agreement.agreement_id,
                parent_kind=ctx_data.get("parent_kind") or "direct",
                requester_sovereign_id=requester,
                provider_sovereign_id=provider,
                requested_capability=capability,
                request_parameters=ctx_data.get("request_parameters") or {},
                requested_at=datetime.now(timezone.utc),
                context_freshness_seq=ctx_data.get("context_freshness_seq") or 0,
            )
        except Exception as exc:
            raise BadRequestError("Invalid context record", code="invalid_context") from exc

        engine = BoundaryEngine(operator_sovereign_id=service.genesis_block.network_name)
        try:
            decision = engine.evaluate(
                context,
                agreement,
                service.signer,
                issued_by=service.key_id,
                now=datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.warning("boundary evaluation failed for capability %s: %s", capability, exc)
            raise RequestValidationError(
                "Boundary evaluation failed — check that the agreement is valid and not expired",
                code="boundary_eval_failed",
            ) from exc

        service.evidence_store_service.record_decision(decision, context)
        service.db.add_audit_event("boundary_decision_made", {
            "decision_id": decision.decision_id,
            "context_id": context.context_id,
            "agreement_id": agreement.agreement_id,
            "requested_capability": capability,
            "authorized": decision.authorized,
        })
        return jsonify(_legacy_decision_json(decision)), 201

    @bp.route("/boundary/verify", methods=["POST"])
    def verify():
        """Verify a signed BoundaryDecision."""
        if not service.rate_limiter.allow(_rate_key("boundary_verify"), service.rate_limits.verify, 60):
            raise RateLimitError()
        data = request_json_object()
        raw = data.get("decision")
        if not raw:
            raise BadRequestError("decision is required", code="missing_decision")
        operator_keys = data.get("operator_public_keys") or [_pub_b64()]
        # v1.2.0: refuse a field this release does not know, as every SDK does.
        refusal = strict_refusal("BoundaryDecision", raw, operator_keys)
        if refusal:
            service.db.add_audit_event("boundary_decision_verified", {
                "decision_id": raw.get("decision_id"), "accepted": False,
            })
            return jsonify({"accepted": False, "authorized": raw.get("authorized") is True,
                            "reason": refusal, "decision_id": raw.get("decision_id")})
        try:
            decision = BoundaryDecision.model_validate(raw)
        except Exception as exc:
            raise BadRequestError("Invalid decision object", code="invalid_decision") from exc

        result = verify_boundary_decision(
            decision,
            operator_public_keys=operator_keys,
            now=datetime.now(timezone.utc),
        )
        service.db.add_audit_event("boundary_decision_verified", {
            "decision_id": result.decision_id,
            "accepted": result.accepted,
        })
        return jsonify({
            "accepted": result.accepted,
            "authorized": result.authorized,
            "reason": result.reason,
            "decision_id": result.decision_id,
        })

    return bp
