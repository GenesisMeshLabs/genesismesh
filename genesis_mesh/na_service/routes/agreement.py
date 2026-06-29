"""Agreement negotiation routes — offer, counter, accept, verify."""

from __future__ import annotations

import json
import logging
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

logger = logging.getLogger(__name__)


def _j(model) -> dict:
    return json.loads(model.model_dump_json())


def create_agreement_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    """Create agreement negotiation routes — offer, counter, accept, verify."""
    bp = Blueprint("agreement", __name__)

    def _sovereign_id() -> str:
        return service.genesis_block.network_name

    def _pub_b64() -> str:
        import nacl.encoding
        return service.na_private_key.verify_key.encode(
            encoder=nacl.encoding.Base64Encoder
        ).decode()

    def _rate_key(prefix: str) -> str:
        return f"{prefix}:{request.remote_addr or 'unknown'}"

    # ── Signing routes (admin-authenticated) ─────────────────────────────────

    @bp.route("/admin/agreements/offer", methods=["POST"])
    def build_offer_route():
        """Build and sign a CapabilityOffer as the NA sovereign."""
        if not service.rate_limiter.allow(_rate_key("admin"), 30, 60):
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

        if valid_from >= valid_until:
            raise BadRequestError(
                "valid_from must be before valid_until", code="invalid_timestamp_order"
            )

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
            logger.warning("build_offer failed for responder %s: %s", responder, exc)
            raise RequestValidationError(
                "Could not build offer — check that recognition policy permits this sovereign",
                code="offer_rejected",
            ) from exc

        service.db.add_audit_event("capability_offer_built", {
            "offer_id": offer.offer_id,
            "offerer_sovereign_id": _sovereign_id(),
            "responder_sovereign_id": responder,
            "capabilities": capabilities,
        })
        return jsonify(_j(offer)), 201

    @bp.route("/admin/agreements/counter", methods=["POST"])
    def build_counter_route():
        """Build and sign a CapabilityCounter in response to an existing offer."""
        if not service.rate_limiter.allow(_rate_key("admin"), 30, 60):
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

        if valid_from >= valid_until:
            raise BadRequestError(
                "valid_from must be before valid_until", code="invalid_timestamp_order"
            )

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
            logger.warning("build_counter failed for offer %s: %s", offer.offer_id, exc)
            raise RequestValidationError(
                "Could not build counter-offer — check that recognition policy permits this sovereign",
                code="counter_rejected",
            ) from exc

        service.db.add_audit_event("capability_counter_built", {
            "original_offer_id": offer.offer_id,
            "counter_offer_id": counter.offer_id,
            "offerer_sovereign_id": _sovereign_id(),
            "capabilities": capabilities,
        })
        return jsonify(_j(counter)), 201

    @bp.route("/admin/agreements/accept", methods=["POST"])
    def accept_route():
        """Accept an offer or counter-offer, producing a signed AgreementRecord."""
        if not service.rate_limiter.allow(_rate_key("admin"), 30, 60):
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
            logger.warning("agreement acceptance failed: %s", exc)
            raise RequestValidationError(
                "Could not accept — check that the offer or counter is valid and not expired",
                code="accept_rejected",
            ) from exc

        service.db.add_audit_event("agreement_accepted", {
            "agreement_id": agreement.agreement_id,
            "offerer_sovereign_id": agreement.offerer_sovereign_id,
            "responder_sovereign_id": agreement.responder_sovereign_id,
        })
        return jsonify(_j(agreement)), 201

    # ── Verification route (unauthenticated, rate-limited) ───────────────────

    @bp.route("/agreements/verify", methods=["POST"])
    def verify_route():
        """Verify a signed AgreementRecord without storing it."""
        if not service.rate_limiter.allow(_rate_key("agreements_verify"), 60, 60):
            raise RateLimitError()
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
        service.db.add_audit_event("agreement_verified", {
            "agreement_id": result.agreement_id,
            "accepted": result.accepted,
        })
        return jsonify({
            "accepted": result.accepted,
            "reason": result.reason,
            "agreement_id": result.agreement_id,
        })

    return bp
