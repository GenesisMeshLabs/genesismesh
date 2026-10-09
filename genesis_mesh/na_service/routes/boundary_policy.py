"""Declarative boundary policy routes (v0.58).

Admin lifecycle routes (operator-authenticated):
  POST /admin/boundary-policies/validate          dry-run validation of intent
  POST /admin/boundary-policies                   publish a signed, inactive version (privileged)
  GET  /admin/boundary-policies                   list every stored version
  GET  /admin/boundary-policies/active            active set, health, enforcement mode
  GET  /admin/boundary-policies/<id>/history      all versions of one policy
  POST /admin/boundary-policies/<id>/activate     activate / roll back to a version (privileged)
  POST /admin/boundary-policies/<id>/deactivate   deactivate a version (privileged)

Policy-aware evaluation:
  POST /admin/boundary/evaluate                   signed decision + justification proof
                                                  (agreement or attestation_id basis, v0.58.1)

Public:
  POST /boundary-policies/verify                  verify a policy signature
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from ...models.boundary_policy import BoundaryPolicy
from ...trust.agreement import AgreementRecord
from ...trust.context import verify_boundary_policy
from ..errors import (
    BadRequestError,
    RateLimitError,
    UnauthorizedError,
    request_json_object,
)

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService

logger = logging.getLogger(__name__)


def _j(model) -> dict:
    return json.loads(model.model_dump_json())


def _version_field(data: dict[str, Any]) -> int:
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise BadRequestError("version must be a positive integer", code="invalid_policy_version")
    return version


def create_boundary_policy_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    """Create declarative boundary policy lifecycle and evaluation routes."""
    bp = Blueprint("boundary_policy", __name__)
    policies = service.boundary_policies

    def _rate_key(prefix: str) -> str:
        return f"{prefix}:{request.remote_addr or 'unknown'}"

    def _admin(data: dict, tier: str = "standard") -> None:
        if not service.rate_limiter.allow(_rate_key("admin"), service.rate_limits.admin, 60):
            raise RateLimitError()
        ok, err = service._verify_admin_request(data, required_tier=tier)  # type: ignore[arg-type]
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")

    @bp.route("/admin/boundary-policies/validate", methods=["POST"])
    def validate_policy():
        """Validate policy intent against the trusted registry without signing it."""
        data = request_json_object()
        _admin(data)
        policy, result = policies.validate_intent(data)
        service.db.add_audit_event("boundary_policy_validated", {
            "policy_id": policy.policy_id,
            "valid": result.valid,
            "issue_codes": result.codes(),
        })
        return jsonify({
            **result.to_dict(),
            "policy_id": policy.policy_id,
            "next_version": policy.version,
        })

    @bp.route("/admin/boundary-policies", methods=["POST"])
    def publish_policy():
        """Validate, sign and store a new inactive policy version."""
        data = request_json_object()
        _admin(data, "privileged")
        policy = policies.publish(data)
        service.db.add_audit_event("boundary_policy_published", {
            "policy_id": policy.policy_id,
            "version": policy.version,
            "policy_digest": policy.digest(),
            "gate_count": len(policy.gates),
            "issued_by": policy.issued_by,
        })
        return jsonify(_j(policy)), 201

    @bp.route("/admin/boundary-policies", methods=["GET"])
    def list_policies():
        """List every stored boundary policy version."""
        _admin({})
        return jsonify({"policies": policies.list_versions()})

    @bp.route("/admin/boundary-policies/active", methods=["GET"])
    def active_policies():
        """Return the active policy set, its health, and the enforcement mode."""
        _admin({})
        return jsonify(policies.active_status())

    @bp.route("/admin/boundary-policies/<policy_id>/history", methods=["GET"])
    def policy_history(policy_id: str):
        """Return every stored version of one policy, newest first."""
        _admin({})
        versions = policies.list_versions(policy_id, include_policy=True)
        if not versions:
            raise BadRequestError("unknown boundary policy", code="boundary_policy_not_found")
        return jsonify({"policy_id": policy_id, "versions": versions})

    @bp.route("/admin/boundary-policies/<policy_id>/activate", methods=["POST"])
    def activate_policy(policy_id: str):
        """Activate a version (re-verified first); also the rollback path."""
        data = request_json_object()
        _admin(data, "privileged")
        version = _version_field(data)
        policy, previous = policies.activate(policy_id, version)
        service.db.add_audit_event("boundary_policy_activated", {
            "policy_id": policy_id,
            "version": version,
            "previous_version": previous,
            "policy_digest": policy.digest(),
            "rollback": previous is not None and previous > version,
        })
        return jsonify({
            "policy_id": policy_id,
            "version": version,
            "previous_version": previous,
            "active": True,
        })

    @bp.route("/admin/boundary-policies/<policy_id>/deactivate", methods=["POST"])
    def deactivate_policy(policy_id: str):
        """Deactivate an active version."""
        data = request_json_object()
        _admin(data, "privileged")
        version = _version_field(data)
        policies.deactivate(policy_id, version)
        service.db.add_audit_event("boundary_policy_deactivated", {
            "policy_id": policy_id,
            "version": version,
        })
        return jsonify({"policy_id": policy_id, "version": version, "active": False})

    def _evaluate_attestation(data: dict, attestation_id: object, capability: str):
        """Evaluate under an NA-issued MembershipAttestation (fails closed)."""
        if not isinstance(attestation_id, str) or not attestation_id:
            raise BadRequestError(
                "attestation_id must be a non-empty string", code="invalid_attestation_id"
            )
        ctx = data.get("context") or {}
        requester = ctx.get("requester_sovereign_id") if isinstance(ctx, dict) else None
        if requester is not None and not isinstance(requester, str):
            raise BadRequestError("Invalid context record", code="invalid_context")
        basis, requester_id = policies.assess_attestation(attestation_id, requester)
        context = policies.build_attestation_context(data, attestation_id, requester_id)
        decision, proof = policies.evaluate_attestation(context, basis)
        service.evidence_store_service.record_decision(decision, context, proof)

        binding = decision.policy_binding
        service.db.add_audit_event("boundary_attestation_decision_made", {
            "decision_id": decision.decision_id,
            "context_id": context.context_id,
            "attestation_id": attestation_id,
            "subject_id": basis.attestation.subject_id if basis.attestation else None,
            "requester_sovereign_id": requester_id,
            "requested_capability": capability,
            "authorized": decision.authorized,
            "denial_reason": decision.denial_reason,
            "revocation_seq_checked": basis.revocation_seq_checked,
            "applied_policies": [
                f"{p.policy_id}@{p.version}" for p in (binding.policies if binding else [])
            ],
            "failed_gates": [gr.gate_name for gr in decision.gate_results if not gr.passed],
        })
        return jsonify({"decision": _j(decision), "justification_proof": _j(proof)}), 201

    @bp.route("/admin/boundary/evaluate", methods=["POST"])
    def evaluate():
        """Policy-aware evaluation under an agreement or (v0.58.1) an attestation basis."""
        data = request_json_object()
        _admin(data)
        raw_agreement = data.get("agreement")
        attestation_id = data.get("attestation_id")
        if (raw_agreement is None) == (attestation_id is None):
            raise BadRequestError(
                "provide exactly one of agreement or attestation_id",
                code="ambiguous_basis",
            )
        capability = data.get("requested_capability")
        if not capability or not isinstance(capability, str):
            raise BadRequestError(
                "requested_capability is required",
                code="missing_boundary_fields",
            )
        if attestation_id is not None:
            return _evaluate_attestation(data, attestation_id, capability)
        if not raw_agreement:
            raise BadRequestError(
                "agreement and requested_capability are required",
                code="missing_boundary_fields",
            )
        try:
            agreement = AgreementRecord.model_validate(raw_agreement)
        except ValidationError as exc:
            raise BadRequestError("Invalid agreement object", code="invalid_agreement") from exc
        service.agreements.require_trusted(agreement, route="/admin/boundary/evaluate", raw=raw_agreement)
        context = policies.build_context(data, agreement)

        decision, proof = policies.evaluate(context, agreement)
        service.evidence_store_service.record_decision(decision, context, proof)

        binding = decision.policy_binding
        service.db.add_audit_event("boundary_policy_decision_made", {
            "decision_id": decision.decision_id,
            "context_id": context.context_id,
            "agreement_id": agreement.agreement_id,
            "requested_capability": capability,
            "authorized": decision.authorized,
            "applied_policies": [
                f"{p.policy_id}@{p.version}" for p in (binding.policies if binding else [])
            ],
            "failed_gates": [
                f"{e.policy_id}/{e.gate_id}"
                for e in (binding.gate_evaluations if binding else [])
                if not e.passed
            ],
            "resolution_status": binding.resolution_status if binding else None,
            "resolution_failure": binding.resolution_failure if binding else None,
        })
        return jsonify({"decision": _j(decision), "justification_proof": _j(proof)}), 201

    @bp.route("/boundary-policies/verify", methods=["POST"])
    def verify_policy():
        """Verify a signed BoundaryPolicy against the NA key or supplied issuer keys."""
        if not service.rate_limiter.allow(_rate_key("boundary_policy_verify"), service.rate_limits.verify, 60):
            raise RateLimitError()
        data = request_json_object()
        raw = data.get("policy")
        if not raw or not isinstance(raw, dict):
            raise BadRequestError("policy is required", code="missing_policy")
        try:
            policy = BoundaryPolicy.model_validate(raw)
        except ValidationError as exc:
            raise BadRequestError("Invalid policy object", code="invalid_policy") from exc
        keys = data.get("issuer_public_keys") or [
            service.signer.public_key_b64
        ]
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            raise BadRequestError("issuer_public_keys must be a list of strings", code="invalid_public_keys")
        result = verify_boundary_policy(policy, keys)
        service.db.add_audit_event("boundary_policy_verified", {
            "policy_id": result.policy_id,
            "version": result.version,
            "valid": result.valid,
            "reason": result.reason,
        })
        return jsonify(result.to_dict())

    return bp
