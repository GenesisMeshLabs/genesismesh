"""Consensus routes — vote, proof, verify."""

from __future__ import annotations

import json
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


def _j(model) -> dict:
    return json.loads(model.model_dump_json())


def create_consensus_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    bp = Blueprint("consensus", __name__)

    def _pub_b64() -> str:
        import nacl.encoding
        return service.na_private_key.verify_key.encode(
            encoder=nacl.encoding.Base64Encoder
        ).decode()

    # ── Signing routes (admin-authenticated) ─────────────────────────────────

    @bp.route("/admin/consensus/vote", methods=["POST"])
    def vote():
        """Cast a ValidatorVote signed by the NA as validator."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
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
            raise RequestValidationError(str(exc), code="vote_failed") from exc

        return jsonify(_j(v)), 201

    @bp.route("/admin/consensus/proof", methods=["POST"])
    def proof():
        """Assemble a ConsensusProof from votes, signed by the NA as assembler."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            raise RateLimitError()
        data = request_json_object()
        ok, err = service._verify_admin_request(data)
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")

        raw_proof = data.get("justification_proof")
        raw_votes = data.get("votes")
        required_threshold = data.get("required_threshold")
        validator_ids = data.get("validator_sovereign_ids")
        if not raw_proof or not isinstance(raw_votes, list) or required_threshold is None or not isinstance(validator_ids, list):
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
            raise RequestValidationError(str(exc), code="proof_assembly_failed") from exc

        return jsonify(_j(cp)), 201

    # ── Verification route (unauthenticated) ─────────────────────────────────

    @bp.route("/consensus/verify", methods=["POST"])
    def verify():
        """Verify a ConsensusProof signature and threshold."""
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
        return jsonify({
            "valid": result.valid,
            "reason": result.reason,
            "consensus_id": result.consensus_id,
        })

    return bp
