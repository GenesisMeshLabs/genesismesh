"""Boundary decision routes — decide, verify."""

from __future__ import annotations

import json
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
    RateLimitError,
    RequestValidationError,
    UnauthorizedError,
    request_json_object,
)

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService


def _j(model) -> dict:
    return json.loads(model.model_dump_json())


def create_boundary_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    bp = Blueprint("boundary", __name__)

    def _pub_b64() -> str:
        import nacl.encoding
        return service.na_private_key.verify_key.encode(
            encoder=nacl.encoding.Base64Encoder
        ).decode()

    @bp.route("/admin/boundary/decide", methods=["POST"])
    def decide():
        """Evaluate a ContextRecord against an AgreementRecord and sign the decision."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            raise RateLimitError()
        data = request_json_object()
        ok, err = service._verify_admin_request(data)
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")

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

        ctx_data = data.get("context") or {}
        try:
            context = ContextRecord(
                context_id=ctx_data.get("context_id") or str(uuid.uuid4()),
                agreement_id=agreement.agreement_id,
                parent_kind=ctx_data.get("parent_kind") or "direct",
                requester_sovereign_id=ctx_data.get("requester_sovereign_id")
                    or agreement.responder_sovereign_id,
                provider_sovereign_id=ctx_data.get("provider_sovereign_id")
                    or agreement.offerer_sovereign_id,
                requested_capability=capability,
                request_parameters=ctx_data.get("request_parameters") or {},
                requested_at=datetime.now(timezone.utc),
                context_freshness_seq=ctx_data.get("context_freshness_seq") or 0,
            )
        except Exception as exc:
            raise BadRequestError(str(exc), code="invalid_context") from exc

        engine = BoundaryEngine(operator_sovereign_id=service.genesis_block.network_name)
        try:
            decision = engine.evaluate(
                context,
                agreement,
                service.na_private_key,
                issued_by=service.key_id,
                now=datetime.now(timezone.utc),
            )
        except Exception as exc:
            raise RequestValidationError(str(exc), code="boundary_eval_failed") from exc

        return jsonify(_j(decision)), 201

    @bp.route("/boundary/verify", methods=["POST"])
    def verify():
        """Verify a signed BoundaryDecision."""
        data = request_json_object()
        raw = data.get("decision")
        if not raw:
            raise BadRequestError("decision is required", code="missing_decision")
        try:
            decision = BoundaryDecision.model_validate(raw)
        except Exception as exc:
            raise BadRequestError("Invalid decision object", code="invalid_decision") from exc

        operator_keys = data.get("operator_public_keys") or [_pub_b64()]
        result = verify_boundary_decision(
            decision,
            operator_public_keys=operator_keys,
            now=datetime.now(timezone.utc),
        )
        return jsonify({
            "accepted": result.accepted,
            "authorized": result.authorized,
            "reason": result.reason,
            "decision_id": result.decision_id,
        })

    return bp
