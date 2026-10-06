"""Membership attestation routes for sovereign trust portability."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, request

from ...models import MembershipAttestation, RecognitionPolicy, SovereignRevocationFeed
from ...trust import verify_membership_attestation
from ..errors import (
    BadRequestError,
    NotFoundError,
    RateLimitError,
    RequestValidationError,
    UnauthorizedError,
    positive_int_field,
    request_json_object,
)

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService


def _json_model(model) -> dict:
    """Convert a Pydantic model to JSON-safe primitives."""
    return json.loads(model.model_dump_json())


def _row_payload(row: dict) -> dict:
    """Render a persisted attestation row for HTTP responses."""
    return {
        "attestation": _json_model(row["attestation"]),
        "status": row["status"],
        "revoked_at": row["revoked_at"],
        "revocation_reason": row["revocation_reason"],
    }


def _policy_with_db_revocation(
    service: "NetworkAuthorityService",
    attestation: MembershipAttestation,
    policy: RecognitionPolicy,
) -> RecognitionPolicy:
    """Add local issuer-side revocation state to a verification policy."""
    stored = service.db.get_membership_attestation(attestation.attestation_id)
    if not stored or stored["status"] != "revoked":
        return policy

    revoked = set(policy.revoked_attestation_ids)
    revoked.add(attestation.attestation_id)
    return policy.model_copy(update={"revoked_attestation_ids": sorted(revoked)})


def create_attestation_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    """Create routes for issuing, reading, revoking, and verifying attestations."""
    bp = Blueprint("attestations", __name__)

    @bp.route("/admin/attestations", methods=["POST"])
    def issue_attestation():
        """Issue a signed membership attestation for a subject."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", service.rate_limits.admin, 60):
            raise RateLimitError()

        data = request_json_object()
        ok, error = service._verify_admin_request(data, required_tier="privileged")
        if not ok:
            raise UnauthorizedError(error or "Unauthorized", code="admin_auth_failed")

        subject_id = data.get("subject_id")
        roles = data.get("roles") or []
        if not subject_id or not isinstance(roles, list) or not roles:
            raise BadRequestError(
                "subject_id and roles are required",
                code="missing_attestation_subject",
            )

        valid_roles, role_error = service._validate_roles(roles)
        if not valid_roles:
            raise BadRequestError(role_error or "Invalid role", code="invalid_role")

        validity_hours = positive_int_field(
            data,
            "validity_hours",
            default=168,
            code="invalid_validity_hours",
            message="validity_hours must be greater than zero",
        )

        # v1.0.2: this NA signs the attestation, so it names this sovereign as
        # the issuer; it never signs an identity claim for another sovereign.
        issuer_sovereign_id = service.genesis_block.network_name
        if data.get("issuer_sovereign_id", issuer_sovereign_id) != issuer_sovereign_id:
            raise BadRequestError(
                "Attestations issued here name this sovereign as their issuer",
                code="attestation_issuer_mismatch",
            )

        now = datetime.now(timezone.utc)
        attestation = MembershipAttestation(
            attestation_id=str(uuid.uuid4()),
            issuer_sovereign_id=issuer_sovereign_id,
            subject_id=subject_id,
            subject_public_key=data.get("subject_public_key"),
            roles=roles,
            status="active",
            issued_at=now,
            valid_from=now,
            expires_at=now + timedelta(hours=validity_hours),
            issued_by=service.key_id,
            claims=data.get("claims") or {},
            signatures=[],
        )
        attestation.signatures.append(
            service.signer.sign_model(attestation)
        )
        service.db.save_membership_attestation(attestation)
        service.db.add_audit_event("membership_attestation_issued", {
            "attestation_id": attestation.attestation_id,
            "issuer_sovereign_id": attestation.issuer_sovereign_id,
            "subject_id": subject_id,
            "roles": roles,
        })

        return jsonify(_json_model(attestation)), 201

    @bp.route("/admin/attestations/<attestation_id>/revoke", methods=["POST"])
    def revoke_attestation(attestation_id: str):
        """Revoke an issued membership attestation."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", service.rate_limits.admin, 60):
            raise RateLimitError()

        data = request_json_object()
        ok, error = service._verify_admin_request(data, required_tier="privileged")
        if not ok:
            raise UnauthorizedError(error or "Unauthorized", code="admin_auth_failed")

        reason = data.get("reason", "unspecified")
        if not service.db.revoke_membership_attestation(attestation_id, reason):
            raise NotFoundError("Attestation not found", code="attestation_not_found")

        service.db.add_audit_event("membership_attestation_revoked", {
            "attestation_id": attestation_id,
            "reason": reason,
        })
        return jsonify({"attestation_id": attestation_id, "status": "revoked"}), 200

    @bp.route("/admin/recognition-policy", methods=["POST"])
    def save_recognition_policy():
        """Persist the local recognition policy used by attestation verification."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", service.rate_limits.admin, 60):
            raise RateLimitError()

        data = request_json_object()
        ok, error = service._verify_admin_request(data, required_tier="privileged")
        if not ok:
            raise UnauthorizedError(error or "Unauthorized", code="admin_auth_failed")

        try:
            policy = RecognitionPolicy.model_validate(data.get("recognition_policy"))
        except Exception as exc:
            raise RequestValidationError(
                "Invalid recognition_policy",
                code="invalid_recognition_policy",
            ) from exc

        policy_id = data.get("policy_id", f"recognition-{policy.local_sovereign_id}")
        service.db.save_recognition_policy(policy_id, policy, active=True)
        service.db.add_audit_event("recognition_policy_saved", {
            "policy_id": policy_id,
            "local_sovereign_id": policy.local_sovereign_id,
            "recognized_issuer_count": len(policy.recognized_issuers),
        })
        return jsonify({
            "policy_id": policy_id,
            "local_sovereign_id": policy.local_sovereign_id,
            "active": True,
        }), 200

    @bp.route("/recognition-policy", methods=["GET"])
    def get_recognition_policy():
        """Return the active local recognition policy, if configured."""
        policy = service.db.get_active_recognition_policy()
        if policy is None:
            raise NotFoundError(
                "Recognition policy not configured",
                code="recognition_policy_not_configured",
            )
        return jsonify(_json_model(policy))

    @bp.route("/attestations/<attestation_id>", methods=["GET"])
    def get_attestation(attestation_id: str):
        """Return a persisted membership attestation by ID."""
        row = service.db.get_membership_attestation(attestation_id)
        if not row:
            raise NotFoundError("Attestation not found", code="attestation_not_found")
        return jsonify(_row_payload(row))

    @bp.route("/attestations", methods=["GET"])
    def list_attestations():
        """List membership attestations to operators; count them for anyone else.

        The list names every attested subject with its key, roles and claims,
        so it goes to operators only, as the node roster does; a read-tier key
        is enough. An unsigned request gets the count, optionally by
        ``status``; filtering by subject or issuer would answer "is this
        subject a member", so it needs an operator signature (v1.0.2).
        """
        status = request.args.get("status")
        if not request.headers.get("X-Admin-Key-Id"):
            if request.args.get("subject_id") or request.args.get("issuer_sovereign_id"):
                raise UnauthorizedError(
                    "Filtering attestations by subject or issuer requires operator authentication",
                    code="admin_auth_failed",
                )
            return jsonify({"count": len(service.db.list_membership_attestations(status=status))})
        # The operator view is an admin request: same limit as /admin/* (v1.1.0).
        if not service.rate_limiter.allow(
            f"admin:{request.remote_addr or 'unknown'}", service.rate_limits.admin, 60
        ):
            raise RateLimitError()
        ok, error = service._verify_admin_request({}, required_tier="read")
        if not ok:
            raise UnauthorizedError(error or "Unauthorized", code="admin_auth_failed")
        rows = service.db.list_membership_attestations(
            issuer_sovereign_id=request.args.get("issuer_sovereign_id"),
            subject_id=request.args.get("subject_id"),
            status=status,
        )
        return jsonify({
            "count": len(rows),
            "attestations": [_row_payload(row) for row in rows],
        })

    @bp.route("/sovereign-revocation-feed", methods=["GET"])
    def sovereign_revocation_feed():
        """Publish this sovereign's signed feed of revoked membership attestations."""
        issuer_sovereign_id = service.genesis_block.network_name
        requested = request.args.get("issuer_sovereign_id")
        if requested is not None and requested != issuer_sovereign_id:
            # v1.0.2: this NA signs the feed, so the feed may only name this
            # sovereign as its issuer. Another sovereign's feed comes from that
            # sovereign's own endpoint.
            raise BadRequestError(
                "This Network Authority publishes only its own revocation feed",
                code="feed_issuer_mismatch",
            )
        revoked_rows = service.db.list_membership_attestations(
            issuer_sovereign_id=issuer_sovereign_id,
            status="revoked",
        )
        revoked_ids = [
            row["attestation"].attestation_id
            for row in revoked_rows
        ]
        reasons = {
            row["attestation"].attestation_id: row["revocation_reason"] or "unspecified"
            for row in revoked_rows
        }
        feed = SovereignRevocationFeed(
            feed_id=str(uuid.uuid4()),
            issuer_sovereign_id=issuer_sovereign_id,
            sequence=len(revoked_ids),
            issued_at=datetime.now(timezone.utc),
            revoked_attestation_ids=revoked_ids,
            revocation_reasons=reasons,
            issued_by=service.key_id,
            signatures=[],
        )
        feed.signatures.append(service.signer.sign_model(feed))
        return jsonify(_json_model(feed))

    @bp.route("/attestations/verify", methods=["POST"])
    def verify_attestation():
        """Verify a membership attestation against a local recognition policy."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"attestations_verify:{remote_addr}", service.rate_limits.verify, 60):
            raise RateLimitError()

        data = request_json_object()
        try:
            attestation = MembershipAttestation.model_validate(data.get("attestation"))
            if "recognition_policy" in data:
                policy = RecognitionPolicy.model_validate(data["recognition_policy"])
            else:
                policy = service.db.get_active_recognition_policy()
                if policy is None:
                    raise BadRequestError(
                        "recognition_policy is required",
                        code="missing_recognition_policy",
                    )
        except BadRequestError:
            raise
        except Exception as exc:
            raise RequestValidationError(
                "Invalid attestation or recognition policy",
                code="invalid_attestation_or_policy",
            ) from exc

        policy = _policy_with_db_revocation(service, attestation, policy)
        result = verify_membership_attestation(attestation, policy)
        service.db.add_audit_event("membership_attestation_verified", {
            "attestation_id": attestation.attestation_id,
            "issuer_sovereign_id": attestation.issuer_sovereign_id,
            "accepted": result.accepted,
            "reason": result.reason,
        })
        return jsonify({
            "accepted": result.accepted,
            "reason": result.reason,
            "issuer_sovereign_id": result.issuer_sovereign_id,
            "attestation_id": result.attestation_id,
        })

    return bp
