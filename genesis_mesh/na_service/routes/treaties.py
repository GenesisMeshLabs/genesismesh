"""Recognition treaty routes for cross-sovereign trust."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, request

from ...crypto import sign_model
from ...models import (
    MembershipAttestation,
    RecognitionTreaty,
    RecognitionTreatyScope,
    SovereignRevocationFeed,
)
from ...trust import (
    verify_attestation_with_treaty,
    verify_recognition_treaty,
    verify_sovereign_revocation_feed,
)

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService


def _json_model(model) -> dict:
    """Convert a Pydantic model to JSON-safe primitives."""
    return json.loads(model.model_dump_json())


def _row_payload(row: dict) -> dict:
    """Render a persisted treaty row for HTTP responses."""
    return {
        "treaty": _json_model(row["treaty"]),
        "status": row["status"],
        "revoked_at": row["revoked_at"],
        "revocation_reason": row["revocation_reason"],
    }


def _revoked_treaty_ids(service: "NetworkAuthorityService", treaty_id: str) -> set[str]:
    """Return local DB revocation input for a posted treaty."""
    stored = service.db.get_recognition_treaty(treaty_id)
    if stored and stored["status"] == "revoked":
        return {treaty_id}
    return set()


def _subject_public_keys_for_issuer(
    service: "NetworkAuthorityService",
    issuer_sovereign_id: str,
) -> list[str]:
    """Return public keys accepted for a treaty subject sovereign."""
    rows = service.db.list_recognition_treaties(
        subject_sovereign_id=issuer_sovereign_id,
        status="active",
    )
    keys = {
        public_key
        for row in rows
        for public_key in row["treaty"].subject_public_keys
    }
    return sorted(keys)


def create_treaty_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    """Create routes for issuing, revoking, reading, and verifying treaties."""
    bp = Blueprint("recognition_treaties", __name__)

    @bp.route("/admin/recognition-treaties", methods=["POST"])
    def issue_treaty():
        """Issue a signed direct-recognition treaty for another sovereign."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            return jsonify({"error": "Rate limit exceeded"}), 429

        data = request.get_json() or {}
        ok, error = service._verify_admin_request(data)
        if not ok:
            return jsonify({"error": error}), 401

        subject_sovereign_id = data.get("subject_sovereign_id")
        subject_public_keys = data.get("subject_public_keys") or []
        if not subject_sovereign_id or not isinstance(subject_public_keys, list):
            return jsonify({"error": "subject_sovereign_id and subject_public_keys are required"}), 400
        if not subject_public_keys:
            return jsonify({"error": "subject_public_keys must not be empty"}), 400

        try:
            scope = RecognitionTreatyScope.model_validate(data.get("scope") or {})
        except Exception:
            return jsonify({"error": "Invalid treaty scope"}), 400

        if scope.allowed_roles:
            valid_roles, role_error = service._validate_roles(scope.allowed_roles)
            if not valid_roles:
                return jsonify({"error": role_error}), 400

        validity_hours = int(data.get("validity_hours", 168))
        if validity_hours <= 0:
            return jsonify({"error": "validity_hours must be greater than zero"}), 400

        now = datetime.now(timezone.utc)
        treaty = RecognitionTreaty(
            treaty_id=str(uuid.uuid4()),
            issuer_sovereign_id=data.get(
                "issuer_sovereign_id",
                service.genesis_block.network_name,
            ),
            subject_sovereign_id=subject_sovereign_id,
            subject_public_keys=subject_public_keys,
            scope=scope,
            status="active",
            issued_at=now,
            valid_from=now,
            expires_at=now + timedelta(hours=validity_hours),
            issued_by=service.key_id,
            metadata=data.get("metadata") or {},
            signatures=[],
        )
        treaty.signatures.append(sign_model(treaty, service.na_private_key, service.key_id))
        service.db.save_recognition_treaty(treaty)
        service.db.add_audit_event("recognition_treaty_issued", {
            "treaty_id": treaty.treaty_id,
            "issuer_sovereign_id": treaty.issuer_sovereign_id,
            "subject_sovereign_id": treaty.subject_sovereign_id,
            "allowed_roles": treaty.scope.allowed_roles,
        })

        return jsonify(_json_model(treaty)), 201

    @bp.route("/admin/recognition-treaties/<treaty_id>/revoke", methods=["POST"])
    def revoke_treaty(treaty_id: str):
        """Revoke a locally issued or imported recognition treaty."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            return jsonify({"error": "Rate limit exceeded"}), 429

        data = request.get_json() or {}
        ok, error = service._verify_admin_request(data)
        if not ok:
            return jsonify({"error": error}), 401

        reason = data.get("reason", "unspecified")
        if not service.db.revoke_recognition_treaty(treaty_id, reason):
            return jsonify({"error": "Recognition treaty not found"}), 404

        service.db.add_audit_event("recognition_treaty_revoked", {
            "treaty_id": treaty_id,
            "reason": reason,
        })
        return jsonify({"treaty_id": treaty_id, "status": "revoked"}), 200

    @bp.route("/recognition-treaties/<treaty_id>", methods=["GET"])
    def get_treaty(treaty_id: str):
        """Return a persisted recognition treaty by ID."""
        row = service.db.get_recognition_treaty(treaty_id)
        if not row:
            return jsonify({"error": "Recognition treaty not found"}), 404
        return jsonify(_row_payload(row))

    @bp.route("/recognition-treaties", methods=["GET"])
    def list_treaties():
        """List persisted recognition treaties."""
        rows = service.db.list_recognition_treaties(
            issuer_sovereign_id=request.args.get("issuer_sovereign_id"),
            subject_sovereign_id=request.args.get("subject_sovereign_id"),
            status=request.args.get("status"),
        )
        return jsonify({
            "count": len(rows),
            "recognition_treaties": [_row_payload(row) for row in rows],
        })

    @bp.route("/recognition-treaties/verify", methods=["POST"])
    def verify_treaty():
        """Verify a signed recognition treaty."""
        data = request.get_json() or {}
        try:
            treaty = RecognitionTreaty.model_validate(data.get("treaty"))
            issuer_public_keys = data.get("issuer_public_keys") or [
                service.genesis_block.network_authority.public_key
            ]
        except Exception:
            return jsonify({"error": "Invalid recognition treaty"}), 400

        result = verify_recognition_treaty(
            treaty,
            issuer_public_keys,
            expected_issuer_sovereign_id=data.get("expected_issuer_sovereign_id"),
            expected_subject_sovereign_id=data.get("expected_subject_sovereign_id"),
            revoked_treaty_ids=_revoked_treaty_ids(service, treaty.treaty_id),
        )
        service.db.add_audit_event("recognition_treaty_verified", {
            "treaty_id": treaty.treaty_id,
            "issuer_sovereign_id": treaty.issuer_sovereign_id,
            "subject_sovereign_id": treaty.subject_sovereign_id,
            "accepted": result.accepted,
            "reason": result.reason,
        })
        return jsonify({
            "accepted": result.accepted,
            "reason": result.reason,
            "treaty_id": result.treaty_id,
            "issuer_sovereign_id": result.issuer_sovereign_id,
            "subject_sovereign_id": result.subject_sovereign_id,
        })

    @bp.route("/attestations/verify-with-treaty", methods=["POST"])
    def verify_attestation_with_treaty_route():
        """Verify a membership attestation using a recognition treaty."""
        data = request.get_json() or {}
        try:
            attestation = MembershipAttestation.model_validate(data.get("attestation"))
            treaty = RecognitionTreaty.model_validate(data.get("treaty"))
            treaty_issuer_public_keys = data.get("treaty_issuer_public_keys") or [
                service.genesis_block.network_authority.public_key
            ]
        except Exception:
            return jsonify({"error": "Invalid attestation or recognition treaty"}), 400

        result = verify_attestation_with_treaty(
            attestation,
            treaty,
            treaty_issuer_public_keys,
            revoked_treaty_ids=_revoked_treaty_ids(service, treaty.treaty_id),
            revoked_attestation_ids=service.db.get_imported_revoked_attestation_ids(
                attestation.issuer_sovereign_id,
            ),
        )
        service.db.add_audit_event("treaty_attestation_verified", {
            "treaty_id": treaty.treaty_id,
            "attestation_id": attestation.attestation_id,
            "accepted": result.accepted,
            "reason": result.reason,
        })
        return jsonify({
            "accepted": result.accepted,
            "reason": result.reason,
            "treaty_id": result.treaty_id,
            "attestation_id": result.attestation_id,
            "issuer_sovereign_id": result.issuer_sovereign_id,
            "subject_sovereign_id": result.subject_sovereign_id,
        })

    @bp.route("/admin/sovereign-revocation-feeds/import", methods=["POST"])
    def import_sovereign_revocation_feed():
        """Import a signed revocation feed from a recognized sovereign."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            return jsonify({"error": "Rate limit exceeded"}), 429

        data = request.get_json() or {}
        ok, error = service._verify_admin_request(data)
        if not ok:
            return jsonify({"error": error}), 401

        try:
            feed = SovereignRevocationFeed.model_validate(data.get("feed"))
        except Exception:
            return jsonify({"error": "Invalid sovereign revocation feed"}), 400

        issuer_public_keys = data.get("issuer_public_keys")
        if issuer_public_keys is None:
            issuer_public_keys = _subject_public_keys_for_issuer(
                service,
                feed.issuer_sovereign_id,
            )
        if not isinstance(issuer_public_keys, list) or not issuer_public_keys:
            return jsonify({
                "accepted": False,
                "reason": "missing_issuer_public_keys",
                "issuer_sovereign_id": feed.issuer_sovereign_id,
            }), 400

        latest_sequence = service.db.get_latest_sovereign_revocation_sequence(
            feed.issuer_sovereign_id,
        )
        result = verify_sovereign_revocation_feed(
            feed,
            issuer_public_keys,
            expected_issuer_sovereign_id=data.get("expected_issuer_sovereign_id"),
            min_sequence=latest_sequence,
        )
        if not result.accepted:
            status = 409 if result.reason == "stale_sequence" else 400
            service.db.add_audit_event("sovereign_revocation_feed_rejected", {
                "feed_id": feed.feed_id,
                "issuer_sovereign_id": feed.issuer_sovereign_id,
                "sequence": feed.sequence,
                "reason": result.reason,
            })
            return jsonify({
                "accepted": False,
                "reason": result.reason,
                "feed_id": feed.feed_id,
                "issuer_sovereign_id": feed.issuer_sovereign_id,
                "sequence": feed.sequence,
            }), status

        try:
            service.db.save_sovereign_revocation_feed(feed)
        except ValueError as exc:
            if str(exc) == "stale_sequence":
                return jsonify({
                    "accepted": False,
                    "reason": "stale_sequence",
                    "feed_id": feed.feed_id,
                    "issuer_sovereign_id": feed.issuer_sovereign_id,
                    "sequence": feed.sequence,
                }), 409
            raise

        service.db.add_audit_event("sovereign_revocation_feed_imported", {
            "feed_id": feed.feed_id,
            "issuer_sovereign_id": feed.issuer_sovereign_id,
            "sequence": feed.sequence,
            "revoked_count": len(feed.revoked_attestation_ids),
        })
        return jsonify({
            "accepted": True,
            "reason": "accepted",
            "feed_id": feed.feed_id,
            "issuer_sovereign_id": feed.issuer_sovereign_id,
            "sequence": feed.sequence,
            "revoked_count": len(feed.revoked_attestation_ids),
        })

    @bp.route("/recognition-graph", methods=["GET"])
    def recognition_graph():
        """Export minimal sovereign recognition graph data."""
        return jsonify(service.db.export_recognition_graph())

    return bp
