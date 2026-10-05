"""Recognition treaty routes for cross-sovereign trust."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from flask import Blueprint, Response, jsonify, request

from ...models import (
    MembershipAttestation,
    RecognitionTreaty,
    RecognitionTreatyScope,
    SovereignRevocationFeed,
)
from ...trust import (
    build_connectome_view,
    explain_trust_path,
    verify_attestation_with_treaty,
    verify_recognition_treaty,
    verify_sovereign_revocation_feed,
)
from ...trust.treaty_lifecycle import treaty_lifecycle
from ..errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    RequestValidationError,
    UnauthorizedError,
    positive_int_field,
    request_json_object,
)
from ..operator_console.connectome import render_connectome

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
        "lifecycle": treaty_lifecycle(row),
    }


def _supplied_keys(data: dict, field: str) -> list[str] | None:
    """Return caller-supplied verification keys, or None when the field is absent."""
    value = data.get(field)
    if value in (None, []):
        return None
    if not isinstance(value, list) or not all(isinstance(k, str) and k for k in value):
        raise RequestValidationError(
            f"{field} must be a list of base64 public keys",
            code="invalid_public_keys",
        )
    return value


def _treaty_trust_keys(
    service: "NetworkAuthorityService",
    treaty: RecognitionTreaty,
    supplied: list[str] | None,
) -> tuple[list[str], str, str | None]:
    """Return (keys, trust_basis, rejection) for verifying ``treaty`` here (v1.0.2).

    * A treaty that names this Network Authority as its issuer verifies only
      against this NA's own key and must be the treaty this NA stored; an
      answer for it is this NA's own judgement (``this_authority``).
    * Another sovereign's treaty verifies against the keys the caller pins
      (``caller_supplied_keys``) or, without them, against the keys this NA
      pinned for that sovereign in its own active treaties
      (``recognized_issuer_keys``).
    """
    own_id = service.genesis_block.network_name
    own_key = service.genesis_block.network_authority.public_key
    if treaty.issuer_sovereign_id == own_id:
        if supplied is not None and set(supplied) != {own_key}:
            raise RequestValidationError(
                "A treaty issued by this Network Authority verifies only against its own key",
                code="caller_keys_not_accepted",
            )
        stored = service.db.get_recognition_treaty(treaty.treaty_id)
        if stored is None or _json_model(stored["treaty"]) != _json_model(treaty):
            return [], "this_authority", "not_held"
        return [own_key], "this_authority", None
    if supplied is not None:
        return supplied, "caller_supplied_keys", None
    pinned = _pinned_issuer_keys(service, treaty.issuer_sovereign_id)
    if not pinned:
        return [], "recognized_issuer_keys", "issuer_not_recognized"
    return pinned, "recognized_issuer_keys", None


def _pinned_issuer_keys(service: "NetworkAuthorityService", sovereign_id: str) -> list[str]:
    """Keys this NA pinned for ``sovereign_id`` in its own treaties that are
    active, unrevoked and within their validity window (v1.0.2).

    An expired treaty no longer recognises its subject, even before anyone
    revokes it, so its keys are not used.
    """
    own_id = service.genesis_block.network_name
    now = datetime.now(timezone.utc)
    pinned: list[str] = []
    for row in service.db.list_recognition_treaties(subject_sovereign_id=sovereign_id, status="active"):
        treaty = row["treaty"]
        if treaty.issuer_sovereign_id == own_id and treaty.is_valid(now):
            pinned.extend(k for k in treaty.subject_public_keys if k not in pinned)
    return pinned


def _revoked_treaty_ids(service: "NetworkAuthorityService", treaty_id: str) -> set[str]:
    """Return local DB revocation input for a posted treaty."""
    stored = service.db.get_recognition_treaty(treaty_id)
    if stored and stored["status"] == "revoked":
        return {treaty_id}
    return set()


def create_treaty_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    """Create routes for issuing, revoking, reading, and verifying treaties."""
    bp = Blueprint("recognition_treaties", __name__)

    @bp.route("/admin/recognition-treaties", methods=["POST"])
    def issue_treaty():
        """Issue a signed direct-recognition treaty for another sovereign."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", service.rate_limits.admin, 60):
            raise RateLimitError()

        data = request_json_object()
        ok, error = service._verify_admin_request(data, required_tier="privileged")
        if not ok:
            raise UnauthorizedError(error or "Unauthorized", code="admin_auth_failed")

        subject_sovereign_id = data.get("subject_sovereign_id")
        subject_public_keys = data.get("subject_public_keys") or []
        if not subject_sovereign_id or not isinstance(subject_public_keys, list):
            raise BadRequestError(
                "subject_sovereign_id and subject_public_keys are required",
                code="missing_treaty_subject",
            )
        if not subject_public_keys:
            raise BadRequestError(
                "subject_public_keys must not be empty",
                code="empty_subject_public_keys",
            )

        try:
            scope = RecognitionTreatyScope.model_validate(data.get("scope") or {})
        except Exception as exc:
            raise RequestValidationError(
                "Invalid treaty scope",
                code="invalid_treaty_scope",
            ) from exc

        if scope.allowed_roles:
            valid_roles, role_error = service._validate_roles(scope.allowed_roles)
            if not valid_roles:
                raise BadRequestError(role_error or "Invalid role", code="invalid_role")

        validity_hours = positive_int_field(
            data,
            "validity_hours",
            default=168,
            code="invalid_validity_hours",
            message="validity_hours must be greater than zero",
        )

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
        treaty.signatures.append(service.signer.sign_model(treaty))
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
        if not service.rate_limiter.allow(f"admin:{remote_addr}", service.rate_limits.admin, 60):
            raise RateLimitError()

        data = request_json_object()
        ok, error = service._verify_admin_request(data, required_tier="privileged")
        if not ok:
            raise UnauthorizedError(error or "Unauthorized", code="admin_auth_failed")

        reason = data.get("reason", "unspecified")
        if not service.db.revoke_recognition_treaty(treaty_id, reason):
            raise NotFoundError(
                "Recognition treaty not found",
                code="treaty_not_found",
            )

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
            raise NotFoundError("Recognition treaty not found", code="treaty_not_found")
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
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"treaties_verify:{remote_addr}", service.rate_limits.verify, 60):
            raise RateLimitError()

        data = request_json_object()
        try:
            treaty = RecognitionTreaty.model_validate(data.get("treaty"))
        except Exception as exc:
            raise RequestValidationError(
                "Invalid recognition treaty",
                code="invalid_recognition_treaty",
            ) from exc
        keys, trust_basis, rejection = _treaty_trust_keys(
            service, treaty, _supplied_keys(data, "issuer_public_keys"),
        )

        if rejection:
            accepted, reason = False, rejection
        else:
            result = verify_recognition_treaty(
                treaty,
                keys,
                expected_issuer_sovereign_id=data.get("expected_issuer_sovereign_id"),
                expected_subject_sovereign_id=data.get("expected_subject_sovereign_id"),
                revoked_treaty_ids=_revoked_treaty_ids(service, treaty.treaty_id),
            )
            accepted, reason = result.accepted, result.reason
        service.db.add_audit_event("recognition_treaty_verified", {
            "treaty_id": treaty.treaty_id,
            "issuer_sovereign_id": treaty.issuer_sovereign_id,
            "subject_sovereign_id": treaty.subject_sovereign_id,
            "accepted": accepted,
            "reason": reason,
            "trust_basis": trust_basis,
        })
        return jsonify({
            "accepted": accepted,
            "reason": reason,
            "trust_basis": trust_basis,
            "treaty_id": treaty.treaty_id,
            "issuer_sovereign_id": treaty.issuer_sovereign_id,
            "subject_sovereign_id": treaty.subject_sovereign_id,
        })

    @bp.route("/attestations/verify-with-treaty", methods=["POST"])
    def verify_attestation_with_treaty_route():
        """Verify a membership attestation using a recognition treaty."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"attestations_verify_with_treaty:{remote_addr}", service.rate_limits.verify, 60):
            raise RateLimitError()

        data = request_json_object()
        try:
            attestation = MembershipAttestation.model_validate(data.get("attestation"))
            treaty = RecognitionTreaty.model_validate(data.get("treaty"))
        except Exception as exc:
            raise RequestValidationError(
                "Invalid attestation or recognition treaty",
                code="invalid_attestation_or_treaty",
            ) from exc
        keys, trust_basis, rejection = _treaty_trust_keys(
            service, treaty, _supplied_keys(data, "treaty_issuer_public_keys"),
        )

        if rejection:
            accepted, reason = False, f"treaty_{rejection}"
        else:
            result = verify_attestation_with_treaty(
                attestation,
                treaty,
                keys,
                revoked_treaty_ids=_revoked_treaty_ids(service, treaty.treaty_id),
                revoked_attestation_ids=service.db.get_imported_revoked_attestation_ids(
                    attestation.issuer_sovereign_id,
                ),
            )
            accepted, reason = result.accepted, result.reason
        service.db.add_audit_event("treaty_attestation_verified", {
            "treaty_id": treaty.treaty_id,
            "attestation_id": attestation.attestation_id,
            "accepted": accepted,
            "reason": reason,
            "trust_basis": trust_basis,
        })
        return jsonify({
            "accepted": accepted,
            "reason": reason,
            "trust_basis": trust_basis,
            "treaty_id": treaty.treaty_id,
            "attestation_id": attestation.attestation_id,
            "issuer_sovereign_id": treaty.issuer_sovereign_id,
            "subject_sovereign_id": treaty.subject_sovereign_id,
        })

    @bp.route("/admin/sovereign-revocation-feeds/import", methods=["POST"])
    def import_sovereign_revocation_feed():
        """Import a signed revocation feed from a recognized sovereign."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", service.rate_limits.admin, 60):
            raise RateLimitError()

        data = request_json_object()
        ok, error = service._verify_admin_request(data, required_tier="privileged")
        if not ok:
            raise UnauthorizedError(error or "Unauthorized", code="admin_auth_failed")

        try:
            feed = SovereignRevocationFeed.model_validate(data.get("feed"))
        except Exception as exc:
            raise RequestValidationError(
                "Invalid sovereign revocation feed",
                code="invalid_sovereign_revocation_feed",
            ) from exc

        # v1.0.2: a feed from a sovereign this NA recognises verifies only
        # against the keys its treaties pinned; keys supplied by the caller
        # are accepted only for a sovereign it has no treaty with.
        supplied = _supplied_keys(data, "issuer_public_keys")
        pinned = _pinned_issuer_keys(service, feed.issuer_sovereign_id)
        if pinned:
            if supplied is not None and not set(supplied) <= set(pinned):
                raise RequestValidationError(
                    "This Network Authority pins keys for this issuer; its feed "
                    "verifies only against them",
                    code="caller_keys_not_accepted",
                    details={"issuer_sovereign_id": feed.issuer_sovereign_id},
                )
            issuer_public_keys, trust_basis = pinned, "recognized_issuer_keys"
        elif supplied is not None:
            issuer_public_keys, trust_basis = supplied, "caller_supplied_keys"
        else:
            raise BadRequestError(
                "missing_issuer_public_keys",
                code="missing_issuer_public_keys",
                details={"issuer_sovereign_id": feed.issuer_sovereign_id},
            )

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
            service.db.add_audit_event("sovereign_revocation_feed_rejected", {
                "feed_id": feed.feed_id,
                "issuer_sovereign_id": feed.issuer_sovereign_id,
                "sequence": feed.sequence,
                "reason": result.reason,
                "trust_basis": trust_basis,
            })
            error_cls = ConflictError if result.reason == "stale_sequence" else BadRequestError
            raise error_cls(
                result.reason,
                code=result.reason,
                details={
                    "feed_id": feed.feed_id,
                    "issuer_sovereign_id": feed.issuer_sovereign_id,
                    "sequence": feed.sequence,
                },
            )

        try:
            service.db.save_sovereign_revocation_feed(feed)
        except ValueError as exc:
            if str(exc) == "stale_sequence":
                raise ConflictError(
                    "stale_sequence",
                    code="stale_sequence",
                    details={
                        "feed_id": feed.feed_id,
                        "issuer_sovereign_id": feed.issuer_sovereign_id,
                        "sequence": feed.sequence,
                    },
                ) from None
            raise

        service.db.add_audit_event("sovereign_revocation_feed_imported", {
            "feed_id": feed.feed_id,
            "issuer_sovereign_id": feed.issuer_sovereign_id,
            "sequence": feed.sequence,
            "trust_basis": trust_basis,
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

    @bp.route("/connectome.json", methods=["GET"])
    def connectome_json():
        """Return an operator-facing Connectome view as JSON."""
        return jsonify(build_connectome_view(service.db.export_recognition_graph()))

    @bp.route("/connectome/trust-path", methods=["GET"])
    def connectome_trust_path():
        """Explain whether one sovereign currently recognizes another."""
        source = request.args.get("from") or request.args.get("source")
        target = request.args.get("to") or request.args.get("target")
        if not source or not target:
            raise BadRequestError(
                "from/source and to/target are required",
                code="missing_trust_path_parameters",
            )
        return jsonify(explain_trust_path(
            service.db.export_recognition_graph(),
            source,
            target,
        ))

    @bp.route("/connectome", methods=["GET"])
    def connectome_page():
        """Render a self-contained operator Connectome page."""
        view = build_connectome_view(service.db.export_recognition_graph())
        return Response(render_connectome(view), mimetype="text/html")

    return bp
