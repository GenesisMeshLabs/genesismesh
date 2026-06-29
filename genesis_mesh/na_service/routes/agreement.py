"""Agreement negotiation routes — offer, counter, accept, verify."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, request

from ...trust.agreement import (
    AgreementRecord,
    AgreementTerms,
    CapabilityCounter,
    CapabilityOffer,
    accept_counter,
    accept_offer,
    build_counter,
    build_offer,
    graph_digest_from_export,
    verify_agreement,
)
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


def create_agreement_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    bp = Blueprint("agreement", __name__)

    def _sovereign_id() -> str:
        return service.genesis_block.network_name

    def _pub_b64() -> str:
        import base64
        import nacl.encoding
        return service.na_private_key.verify_key.encode(
            encoder=nacl.encoding.Base64Encoder
        ).decode()

    # ── Signing routes (admin-authenticated) ─────────────────────────────────

    @bp.route("/admin/agreements/offer", methods=["POST"])
    def build_offer_route():
        """Build and sign a CapabilityOffer as the NA sovereign."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            raise RateLimitError()
        data = request_json_object()
        ok, err = service._verify_admin_request(data)
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")

        responder = data.get("responder_sovereign_id")
        capabilities = data.get("capabilities")
        if not responder or not isinstance(capabilities, list) or not capabilities:
            raise BadRequestError(
                "responder_sovereign_id and capabilities[] are required",
                code="missing_offer_fields",
            )

        try:
            valid_from = datetime.fromisoformat(data["valid_from"]).replace(tzinfo=timezone.utc)
            valid_until = datetime.fromisoformat(data["valid_until"]).replace(tzinfo=timezone.utc)
            expires_at = datetime.fromisoformat(data["expires_at"]).replace(tzinfo=timezone.utc)
        except (KeyError, ValueError) as exc:
            raise BadRequestError(
                "valid_from, valid_until, expires_at are required ISO timestamps",
                code="invalid_timestamps",
            ) from exc

        terms = AgreementTerms(
            capabilities=capabilities,
            scope=data.get("scope") or {},
            valid_from=valid_from,
            valid_until=valid_until,
        )
        graph = service.db.export_recognition_graph()
        try:
            offer = build_offer(
                offerer_sovereign_id=_sovereign_id(),
                responder_sovereign_id=responder,
                requested_terms=terms,
                graph=graph,
                signing_key=service.na_private_key,
                issued_by=service.key_id,
                expires_at=expires_at,
                now=datetime.now(timezone.utc),
            )
        except Exception as exc:
            raise RequestValidationError(str(exc), code="offer_rejected") from exc

        return jsonify(_j(offer)), 201

    @bp.route("/admin/agreements/counter", methods=["POST"])
    def build_counter_route():
        """Build and sign a CapabilityCounter in response to an existing offer."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            raise RateLimitError()
        data = request_json_object()
        ok, err = service._verify_admin_request(data)
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")

        raw_offer = data.get("offer")
        capabilities = data.get("capabilities")
        if not raw_offer or not isinstance(capabilities, list) or not capabilities:
            raise BadRequestError(
                "offer and capabilities[] are required",
                code="missing_counter_fields",
            )
        try:
            offer = CapabilityOffer.model_validate(raw_offer)
        except Exception as exc:
            raise BadRequestError("Invalid offer object", code="invalid_offer") from exc

        try:
            valid_from = datetime.fromisoformat(data["valid_from"]).replace(tzinfo=timezone.utc)
            valid_until = datetime.fromisoformat(data["valid_until"]).replace(tzinfo=timezone.utc)
        except (KeyError, ValueError) as exc:
            raise BadRequestError(
                "valid_from and valid_until are required ISO timestamps",
                code="invalid_timestamps",
            ) from exc

        terms = AgreementTerms(
            capabilities=capabilities,
            scope=data.get("scope") or {},
            valid_from=valid_from,
            valid_until=valid_until,
        )
        graph = service.db.export_recognition_graph()
        try:
            counter = build_counter(
                offer=offer,
                offered_terms=terms,
                graph=graph,
                signing_key=service.na_private_key,
                issued_by=service.key_id,
                now=datetime.now(timezone.utc),
            )
        except Exception as exc:
            raise RequestValidationError(str(exc), code="counter_rejected") from exc

        return jsonify(_j(counter)), 201

    @bp.route("/admin/agreements/accept", methods=["POST"])
    def accept_route():
        """Accept an offer or counter-offer, producing a signed AgreementRecord."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            raise RateLimitError()
        data = request_json_object()
        ok, err = service._verify_admin_request(data)
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")

        graph = service.db.export_recognition_graph()
        now = datetime.now(timezone.utc)
        try:
            if "counter" in data and "original_offer" in data:
                counter = CapabilityCounter.model_validate(data["counter"])
                original = CapabilityOffer.model_validate(data["original_offer"])
                agreement = accept_counter(
                    counter=counter,
                    original_offer=original,
                    signing_key=service.na_private_key,
                    issued_by=service.key_id,
                    now=now,
                )
            elif "offer" in data:
                offer = CapabilityOffer.model_validate(data["offer"])
                agreement = accept_offer(
                    offer=offer,
                    graph=graph,
                    signing_key=service.na_private_key,
                    issued_by=service.key_id,
                    now=now,
                )
            else:
                raise BadRequestError(
                    "Provide {offer} or {counter, original_offer}",
                    code="missing_accept_fields",
                )
        except (BadRequestError, UnauthorizedError):
            raise
        except Exception as exc:
            raise RequestValidationError(str(exc), code="accept_rejected") from exc

        return jsonify(_j(agreement)), 201

    # ── Verification route (unauthenticated) ─────────────────────────────────

    @bp.route("/agreements/verify", methods=["POST"])
    def verify_route():
        """Verify a signed AgreementRecord without storing it."""
        data = request_json_object()
        raw = data.get("agreement")
        offerer_keys = data.get("offerer_public_keys") or []
        responder_keys = data.get("responder_public_keys") or []
        if not raw:
            raise BadRequestError("agreement is required", code="missing_agreement")
        try:
            agreement = AgreementRecord.model_validate(raw)
        except Exception as exc:
            raise BadRequestError("Invalid agreement object", code="invalid_agreement") from exc

        graph = service.db.export_recognition_graph()
        expected_digest = graph_digest_from_export(graph) if not offerer_keys else None
        result = verify_agreement(
            agreement,
            offerer_public_keys=offerer_keys or [_pub_b64()],
            responder_public_keys=responder_keys or [_pub_b64()],
            expected_graph_digest=expected_digest,
        )
        return jsonify({
            "accepted": result.accepted,
            "reason": result.reason,
            "agreement_id": result.agreement_id,
        })

    return bp
