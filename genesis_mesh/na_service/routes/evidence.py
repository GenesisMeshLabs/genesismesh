"""Trust evidence routes — build, verify."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, request

from ...trust.decision import TrustDecision, TrustSignal
from ...trust.evidence import (
    TrustEvidence,
    build_trust_evidence,
    graph_digest_from_export,
    verify_trust_evidence,
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


def create_evidence_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    bp = Blueprint("evidence", __name__)

    def _pub_b64() -> str:
        import nacl.encoding
        return service.na_private_key.verify_key.encode(
            encoder=nacl.encoding.Base64Encoder
        ).decode()

    @bp.route("/admin/trust-evidence", methods=["POST"])
    def build():
        """Sign a TrustEvidence record from a TrustDecision."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            raise RateLimitError()
        data = request_json_object()
        ok, err = service._verify_admin_request(data)
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")

        raw_decision = data.get("decision")
        if not raw_decision or not isinstance(raw_decision, dict):
            raise BadRequestError("decision is required", code="missing_decision")
        try:
            signals = [
                TrustSignal(
                    code=s["code"],
                    severity=s["severity"],
                    detail=s.get("detail", ""),
                )
                for s in (raw_decision.get("signals") or [])
            ]
            decision = TrustDecision(
                source_sovereign_id=raw_decision["source_sovereign_id"],
                target_sovereign_id=raw_decision["target_sovereign_id"],
                verdict=raw_decision["verdict"],
                reason=raw_decision.get("reason", ""),
                requested_roles=raw_decision.get("requested_roles") or [],
                trusted=bool(raw_decision.get("trusted", False)),
                trust_path=raw_decision.get("trust_path") or [],
                hop_count=int(raw_decision.get("hop_count", 0)),
                signals=signals,
                evaluated_at=raw_decision.get("evaluated_at", ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BadRequestError(f"Invalid decision: {exc}", code="invalid_decision") from exc

        graph = service.db.export_recognition_graph()
        graph_digest = data.get("graph_digest") or graph_digest_from_export(graph)
        try:
            evidence = build_trust_evidence(
                decision=decision,
                issuer_sovereign_id=service.genesis_block.network_name,
                graph_digest=graph_digest,
                issued_by=service.key_id,
                signing_key=service.na_private_key,
                now=datetime.now(timezone.utc),
            )
        except Exception as exc:
            raise RequestValidationError(str(exc), code="evidence_build_failed") from exc

        return jsonify(_j(evidence)), 201

    @bp.route("/trust-evidence/verify", methods=["POST"])
    def verify():
        """Verify a TrustEvidence signature and optional graph digest."""
        data = request_json_object()
        raw = data.get("evidence")
        if not raw:
            raise BadRequestError("evidence is required", code="missing_evidence")
        try:
            evidence = TrustEvidence.model_validate(raw)
        except Exception as exc:
            raise BadRequestError("Invalid evidence object", code="invalid_evidence") from exc

        issuer_keys = data.get("issuer_public_keys") or [_pub_b64()]
        expected_digest = data.get("expected_graph_digest")
        result = verify_trust_evidence(
            evidence,
            issuer_public_keys=issuer_keys,
            expected_graph_digest=expected_digest,
        )
        return jsonify({
            "accepted": result.accepted,
            "reason": result.reason,
            "evidence_id": result.evidence_id,
            "issuer_sovereign_id": result.issuer_sovereign_id,
            "verdict": result.verdict,
        })

    return bp
