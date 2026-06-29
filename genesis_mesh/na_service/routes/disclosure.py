"""Selective disclosure routes — commit, prove, verify, nullifier."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, request

from ...trust.agreement import AgreementRecord
from ...trust.selective_disclosure import (
    CapabilityCommitment,
    CapabilityMembershipProof,
    CapabilityNullifier,
    commit_capabilities,
    issue_nullifier,
    prove_capability_membership,
    verify_capability_proof,
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


def create_disclosure_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    bp = Blueprint("disclosure", __name__)

    def _pub_b64() -> str:
        import nacl.encoding
        return service.na_private_key.verify_key.encode(
            encoder=nacl.encoding.Base64Encoder
        ).decode()

    # ── Signing routes (admin-authenticated) ─────────────────────────────────

    @bp.route("/admin/disclosure/commit", methods=["POST"])
    def commit():
        """Commit to a list of capabilities under an AgreementRecord, signed by the NA."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            raise RateLimitError()
        data = request_json_object()
        ok, err = service._verify_admin_request(data)
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")

        capabilities = data.get("capabilities")
        raw_agreement = data.get("agreement")
        if not isinstance(capabilities, list) or not capabilities or not raw_agreement:
            raise BadRequestError(
                "capabilities[] and agreement are required",
                code="missing_commit_fields",
            )
        try:
            agreement = AgreementRecord.model_validate(raw_agreement)
        except Exception as exc:
            raise BadRequestError("Invalid agreement object", code="invalid_agreement") from exc

        try:
            commitment = commit_capabilities(
                capabilities=capabilities,
                agreement=agreement,
                signing_key=service.na_private_key,
                issued_by=service.key_id,
                now=datetime.now(timezone.utc),
            )
        except Exception as exc:
            raise RequestValidationError(str(exc), code="commit_failed") from exc

        return jsonify(_j(commitment)), 201

    @bp.route("/admin/disclosure/nullifier", methods=["POST"])
    def nullifier():
        """Issue a one-time nullifier for a capability membership proof, signed by the NA."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            raise RateLimitError()
        data = request_json_object()
        ok, err = service._verify_admin_request(data)
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")

        raw_proof = data.get("proof")
        if not raw_proof:
            raise BadRequestError("proof is required", code="missing_proof")
        try:
            proof = CapabilityMembershipProof.model_validate(raw_proof)
        except Exception as exc:
            raise BadRequestError("Invalid proof object", code="invalid_proof") from exc

        try:
            null = issue_nullifier(
                proof=proof,
                signing_key=service.na_private_key,
                issued_by=service.key_id,
                now=datetime.now(timezone.utc),
            )
        except Exception as exc:
            raise RequestValidationError(str(exc), code="nullifier_failed") from exc

        return jsonify(_j(null)), 201

    # ── Unauthenticated routes ────────────────────────────────────────────────

    @bp.route("/disclosure/prove", methods=["POST"])
    def prove():
        """Generate a Merkle membership proof from caller-supplied data (no NA state used)."""
        data = request_json_object()
        capability = data.get("capability")
        capabilities = data.get("capabilities")
        raw_commitment = data.get("commitment")
        prover_id = data.get("prover_sovereign_id")
        if not capability or not isinstance(capabilities, list) or not raw_commitment or not prover_id:
            raise BadRequestError(
                "capability, capabilities[], commitment, and prover_sovereign_id are required",
                code="missing_prove_fields",
            )
        try:
            commitment = CapabilityCommitment.model_validate(raw_commitment)
        except Exception as exc:
            raise BadRequestError("Invalid commitment object", code="invalid_commitment") from exc

        try:
            proof = prove_capability_membership(
                capability=capability,
                capabilities=capabilities,
                commitment=commitment,
                prover_sovereign_id=prover_id,
                now=datetime.now(timezone.utc),
            )
        except Exception as exc:
            raise RequestValidationError(str(exc), code="prove_failed") from exc

        return jsonify(_j(proof)), 200

    @bp.route("/disclosure/verify", methods=["POST"])
    def verify():
        """Verify a CapabilityMembershipProof against its commitment."""
        data = request_json_object()
        raw_proof = data.get("proof")
        raw_commitment = data.get("commitment")
        if not raw_proof or not raw_commitment:
            raise BadRequestError(
                "proof and commitment are required",
                code="missing_verify_fields",
            )
        try:
            proof = CapabilityMembershipProof.model_validate(raw_proof)
            commitment = CapabilityCommitment.model_validate(raw_commitment)
        except Exception as exc:
            raise BadRequestError("Invalid proof or commitment object", code="invalid_input") from exc

        issuer_keys = data.get("issuer_public_keys") or [_pub_b64()]
        result = verify_capability_proof(
            proof=proof,
            commitment=commitment,
            issuer_public_keys=issuer_keys,
        )
        return jsonify({
            "valid": result.valid,
            "reason": result.reason,
            "commitment_id": result.commitment_id,
        })

    return bp
