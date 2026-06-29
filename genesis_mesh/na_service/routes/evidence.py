"""Trust evidence routes — build, verify."""

from __future__ import annotations

import json
import logging
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

logger = logging.getLogger(__name__)

_VALID_VERDICTS = frozenset({"allow", "warn", "block", "escalate"})


def _j(model) -> dict:
    return json.loads(model.model_dump_json())


def create_evidence_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    """Create trust evidence routes — build, verify."""
    bp = Blueprint("evidence", __name__)

    def _pub_b64() -> str:
        import nacl.encoding
        return service.na_private_key.verify_key.encode(
            encoder=nacl.encoding.Base64Encoder
        ).decode()

    def _rate_key(prefix: str) -> str:
        return f"{prefix}:{request.remote_addr or 'unknown'}"

    @bp.route("/admin/trust-evidence", methods=["POST"])
    def build():
        """Sign a TrustEvidence record from a TrustDecision."""
        if not service.rate_limiter.allow(_rate_key("admin"), 30, 60):
            raise RateLimitError()
        data = request_json_object()
        ok, err = service._verify_admin_request(data)
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")

        raw_decision = data.get("decision")
        if not raw_decision or not isinstance(raw_decision, dict):
            raise BadRequestError("decision is required", code="missing_decision")

        verdict = raw_decision.get("verdict")
        if verdict not in _VALID_VERDICTS:
            raise BadRequestError(
                f"verdict must be one of: {', '.join(sorted(_VALID_VERDICTS))}",
                code="invalid_verdict",
            )

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
                verdict=verdict,
                reason=raw_decision.get("reason", ""),
                requested_roles=raw_decision.get("requested_roles") or [],
                trusted=bool(raw_decision.get("trusted", False)),
                trust_path=raw_decision.get("trust_path") or [],
                hop_count=int(raw_decision.get("hop_count", 0)),
                signals=signals,
                evaluated_at=raw_decision.get("evaluated_at", ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BadRequestError("Invalid decision fields", code="invalid_decision") from exc

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
            logger.warning("build_trust_evidence failed: %s", exc)
            raise RequestValidationError(
                "Could not build trust evidence",
                code="evidence_build_failed",
            ) from exc

        service.db.add_audit_event("trust_evidence_built", {
            "evidence_id": evidence.evidence_id,
            "source_sovereign_id": decision.source_sovereign_id,
            "target_sovereign_id": decision.target_sovereign_id,
            "verdict": verdict,
        })
        return jsonify(_j(evidence)), 201

    @bp.route("/trust-evidence/verify", methods=["POST"])
    def verify():
        """Verify a TrustEvidence signature and optional graph digest."""
        if not service.rate_limiter.allow(_rate_key("evidence_verify"), 60, 60):
            raise RateLimitError()
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
        service.db.add_audit_event("trust_evidence_verified", {
            "evidence_id": result.evidence_id,
            "accepted": result.accepted,
        })
        return jsonify({
            "accepted": result.accepted,
            "reason": result.reason,
            "evidence_id": result.evidence_id,
            "issuer_sovereign_id": result.issuer_sovereign_id,
            "verdict": result.verdict,
        })

    return bp
