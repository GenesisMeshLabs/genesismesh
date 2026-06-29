"""Consensus routes — vote, proof, verify."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, request

from ...models.consensus import ConsensusProof, ValidatorVote
from ...models.justification import JustificationProof
from ...trust.consensus import (
    ConsensusProofVerificationResult,
    assemble_consensus_proof,
    cast_validator_vote,
    verify_consensus_proof,
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


def create_consensus_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    """Create consensus voting routes — vote, proof, verify."""
    bp = Blueprint("consensus", __name__)

    def _pub_b64() -> str:
        import nacl.encoding
        return service.na_private_key.verify_key.encode(
            encoder=nacl.encoding.Base64Encoder
        ).decode()

    def _rate_key(prefix: str) -> str:
        return f"{prefix}:{request.remote_addr or 'unknown'}"

    # ── Signing routes (admin-authenticated) ─────────────────────────────────

    @bp.route("/admin/consensus/vote", methods=["POST"])
    def vote():
        """Cast a ValidatorVote signed by the NA as validator."""
        if not service.rate_limiter.allow(_rate_key("admin"), 30, 60):
            raise RateLimitError()
        data = request_json_object()
        ok, err = service._verify_admin_request(data)
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")

        raw_proof = data.get("justification_proof")
        vote_val = data.get("vote")
        if not raw_proof or vote_val is None:
            raise BadRequestError(
                "justification_proof and vote (bool) are required",
                code="missing_vote_fields",
            )
        if not isinstance(vote_val, bool):
            raise BadRequestError("vote must be a boolean", code="invalid_vote_type")
        try:
            j_proof = JustificationProof.model_validate(raw_proof)
        except Exception as exc:
            raise BadRequestError("Invalid justification_proof", code="invalid_justification") from exc

        try:
            v = cast_validator_vote(
                justification_proof=j_proof,
                validator_sovereign_id=service.genesis_block.network_name,
                vote=vote_val,
                signing_key=service.na_private_key,
                reason=data.get("reason"),
                now=datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.warning("cast_validator_vote failed for proof %s: %s", j_proof.proof_id, exc)
            raise RequestValidationError(
                "Could not cast validator vote",
                code="vote_failed",
            ) from exc

        service.db.add_audit_event("validator_vote_cast", {
            "vote_id": v.vote_id,
            "proof_id": j_proof.proof_id,
            "decision_id": j_proof.decision_id,
            "vote": vote_val,
        })
        return jsonify(_j(v)), 201

    @bp.route("/admin/consensus/proof", methods=["POST"])
    def proof():
        """Assemble a ConsensusProof from votes, signed by the NA as assembler."""
        if not service.rate_limiter.allow(_rate_key("admin"), 30, 60):
            raise RateLimitError()
        data = request_json_object()
        ok, err = service._verify_admin_request(data)
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")

        raw_proof = data.get("justification_proof")
        raw_votes = data.get("votes")
        required_threshold = data.get("required_threshold")
        validator_ids = data.get("validator_sovereign_ids")
        if (
            not raw_proof
            or not isinstance(raw_votes, list)
            or required_threshold is None
            or not isinstance(validator_ids, list)
        ):
            raise BadRequestError(
                "justification_proof, votes[], required_threshold, and validator_sovereign_ids[] are required",
                code="missing_proof_fields",
            )
        try:
            j_proof = JustificationProof.model_validate(raw_proof)
            votes = [ValidatorVote.model_validate(v) for v in raw_votes]
        except Exception as exc:
            raise BadRequestError("Invalid votes or justification_proof", code="invalid_input") from exc

        try:
            cp = assemble_consensus_proof(
                justification_proof=j_proof,
                votes=votes,
                required_threshold=int(required_threshold),
                validator_sovereign_ids=validator_ids,
                assembler_signing_key=service.na_private_key,
                issued_by=service.key_id,
                now=datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.warning("assemble_consensus_proof failed for proof %s: %s", j_proof.proof_id, exc)
            raise RequestValidationError(
                "Could not assemble consensus proof — check that enough valid votes are provided",
                code="proof_assembly_failed",
            ) from exc

        service.db.add_audit_event("consensus_proof_assembled", {
            "consensus_id": cp.consensus_id,
            "proof_id": j_proof.proof_id,
            "vote_count": len(votes),
            "required_threshold": int(required_threshold),
        })
        return jsonify(_j(cp)), 201

    # ── Verification route (unauthenticated, rate-limited) ───────────────────

    @bp.route("/consensus/verify", methods=["POST"])
    def verify():
        """Verify a ConsensusProof signature and threshold."""
        if not service.rate_limiter.allow(_rate_key("consensus_verify"), 60, 60):
            raise RateLimitError()
        data = request_json_object()
        raw = data.get("proof")
        if not raw:
            raise BadRequestError("proof is required", code="missing_proof")
        try:
            cp = ConsensusProof.model_validate(raw)
        except Exception as exc:
            raise BadRequestError("Invalid proof object", code="invalid_proof") from exc

        validator_keys = data.get("validator_public_keys") or {service.key_id: _pub_b64()}
        assembler_keys = data.get("assembler_public_keys") or [_pub_b64()]
        result = verify_consensus_proof(
            proof=cp,
            validator_public_keys=validator_keys,
            assembler_public_keys=assembler_keys,
            at_time=datetime.now(timezone.utc),
        )
        service.db.add_audit_event("consensus_proof_verified", {
            "consensus_id": result.consensus_id,
            "valid": result.valid,
        })
        return jsonify({
            "valid": result.valid,
            "reason": result.reason,
            "consensus_id": result.consensus_id,
        })

    return bp
