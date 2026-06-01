"""Membership attestation routes for sovereign trust portability."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, request

from ...crypto import sign_model
from ...models import MembershipAttestation, RecognitionPolicy, SovereignRevocationFeed
from ...trust import verify_membership_attestation

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
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            return jsonify({"error": "Rate limit exceeded"}), 429

        data = request.get_json() or {}
        ok, error = service._verify_admin_request(data)
        if not ok:
            return jsonify({"error": error}), 401

        subject_id = data.get("subject_id")
        roles = data.get("roles") or []
        if not subject_id or not isinstance(roles, list) or not roles:
            return jsonify({"error": "subject_id and roles are required"}), 400

        valid_roles, role_error = service._validate_roles(roles)
        if not valid_roles:
            return jsonify({"error": role_error}), 400

        validity_hours = int(data.get("validity_hours", 168))
        if validity_hours <= 0:
            return jsonify({"error": "validity_hours must be greater than zero"}), 400

        now = datetime.now(timezone.utc)
        attestation = MembershipAttestation(
            attestation_id=str(uuid.uuid4()),
            issuer_sovereign_id=data.get(
                "issuer_sovereign_id",
                service.genesis_block.network_name,
            ),
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
            sign_model(attestation, service.na_private_key, service.key_id)
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
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            return jsonify({"error": "Rate limit exceeded"}), 429

        data = request.get_json() or {}
        ok, error = service._verify_admin_request(data)
        if not ok:
            return jsonify({"error": error}), 401

        reason = data.get("reason", "unspecified")
        if not service.db.revoke_membership_attestation(attestation_id, reason):
            return jsonify({"error": "Attestation not found"}), 404

        service.db.add_audit_event("membership_attestation_revoked", {
            "attestation_id": attestation_id,
            "reason": reason,
        })
        return jsonify({"attestation_id": attestation_id, "status": "revoked"}), 200

    @bp.route("/admin/recognition-policy", methods=["POST"])
    def save_recognition_policy():
        """Persist the local recognition policy used by attestation verification."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            return jsonify({"error": "Rate limit exceeded"}), 429

        data = request.get_json() or {}
        ok, error = service._verify_admin_request(data)
        if not ok:
            return jsonify({"error": error}), 401

        try:
            policy = RecognitionPolicy.model_validate(data.get("recognition_policy"))
        except Exception:
            return jsonify({"error": "Invalid recognition_policy"}), 400

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
            return jsonify({"error": "Recognition policy not configured"}), 404
        return jsonify(_json_model(policy))

    @bp.route("/attestations/<attestation_id>", methods=["GET"])
    def get_attestation(attestation_id: str):
        """Return a persisted membership attestation by ID."""
        row = service.db.get_membership_attestation(attestation_id)
        if not row:
            return jsonify({"error": "Attestation not found"}), 404
        return jsonify(_row_payload(row))

    @bp.route("/attestations", methods=["GET"])
    def list_attestations():
        """List persisted membership attestations."""
        rows = service.db.list_membership_attestations(
            issuer_sovereign_id=request.args.get("issuer_sovereign_id"),
            subject_id=request.args.get("subject_id"),
            status=request.args.get("status"),
        )
        return jsonify({
            "count": len(rows),
            "attestations": [_row_payload(row) for row in rows],
        })

    @bp.route("/sovereign-revocation-feed", methods=["GET"])
    def sovereign_revocation_feed():
        """Publish a signed feed of revoked membership attestations."""
        issuer_sovereign_id = request.args.get(
            "issuer_sovereign_id",
            service.genesis_block.network_name,
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
        feed.signatures.append(sign_model(feed, service.na_private_key, service.key_id))
        return jsonify(_json_model(feed))

    @bp.route("/attestations/verify", methods=["POST"])
    def verify_attestation():
        """Verify a membership attestation against a local recognition policy."""
        data = request.get_json() or {}
        try:
            attestation = MembershipAttestation.model_validate(data.get("attestation"))
            if "recognition_policy" in data:
                policy = RecognitionPolicy.model_validate(data["recognition_policy"])
            else:
                policy = service.db.get_active_recognition_policy()
                if policy is None:
                    return jsonify({"error": "recognition_policy is required"}), 400
        except Exception:
            return jsonify({"error": "Invalid attestation or recognition policy"}), 400

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
