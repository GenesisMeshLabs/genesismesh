"""Data usage routes — policy (admin), intent (admin), policy GET, verify."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, request

from ...trust.data_usage import (
    DataAccessIntent,
    DataLicensePolicy,
    DataSourceDescriptor,
    create_data_access_intent,
    verify_data_access_intent,
)
from ..errors import (
    BadRequestError,
    NotFoundError,
    RateLimitError,
    RequestValidationError,
    UnauthorizedError,
    request_json_object,
)

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService


def _j(model) -> dict:
    return json.loads(model.model_dump_json())


def create_data_usage_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    bp = Blueprint("data_usage", __name__)

    # In-memory policy store keyed by policy_id. Active policy is the latest.
    _policies: dict[str, DataLicensePolicy] = {}
    _active_policy_id: list[str] = []  # single-element list as mutable cell

    def _pub_b64() -> str:
        import nacl.encoding
        return service.na_private_key.verify_key.encode(
            encoder=nacl.encoding.Base64Encoder
        ).decode()

    def _sign_policy(p: DataLicensePolicy) -> DataLicensePolicy:
        from ...crypto import sign_model
        sig = sign_model(p, service.na_private_key, service.key_id)
        return p.model_copy(update={"signature": sig})

    # ── Admin routes ──────────────────────────────────────────────────────────

    @bp.route("/admin/data-usage/policy", methods=["POST"])
    def create_policy():
        """Create and sign a DataLicensePolicy as licensor (NA)."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            raise RateLimitError()
        data = request_json_object()
        ok, err = service._verify_admin_request(data)
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")

        licensee = data.get("licensee_sovereign_id")
        allowed_sources = data.get("allowed_source_ids")
        allowed_types = data.get("allowed_access_types")
        if not licensee or not isinstance(allowed_sources, list) or not isinstance(allowed_types, list):
            raise BadRequestError(
                "licensee_sovereign_id, allowed_source_ids[], and allowed_access_types[] are required",
                code="missing_policy_fields",
            )
        try:
            valid_from = datetime.fromisoformat(data["valid_from"]).replace(tzinfo=timezone.utc)
            valid_until = datetime.fromisoformat(data["valid_until"]).replace(tzinfo=timezone.utc)
        except (KeyError, ValueError) as exc:
            raise BadRequestError(
                "valid_from and valid_until are required ISO timestamps",
                code="invalid_timestamps",
            ) from exc

        policy = DataLicensePolicy(
            policy_id=str(uuid.uuid4()),
            licensor_sovereign_id=service.genesis_block.network_name,
            licensee_sovereign_id=licensee,
            allowed_source_ids=allowed_sources,
            allowed_access_types=allowed_types,
            max_volume_bytes_per_session=data.get("max_volume_bytes_per_session"),
            prohibited_classification_tags=data.get("prohibited_classification_tags") or [],
            valid_from=valid_from,
            valid_until=valid_until,
        )
        try:
            policy = _sign_policy(policy)
        except Exception as exc:
            raise RequestValidationError(str(exc), code="policy_sign_failed") from exc

        _policies[policy.policy_id] = policy
        _active_policy_id.clear()
        _active_policy_id.append(policy.policy_id)
        return jsonify(_j(policy)), 201

    @bp.route("/admin/data-usage/intent", methods=["POST"])
    def create_intent():
        """Create and sign a DataAccessIntent as agent (NA)."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            raise RateLimitError()
        data = request_json_object()
        ok, err = service._verify_admin_request(data)
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")

        raw_sources = data.get("sources")
        access_types = data.get("access_types")
        if not isinstance(raw_sources, list) or not raw_sources or not isinstance(access_types, list) or not access_types:
            raise BadRequestError(
                "sources[] and access_types[] are required",
                code="missing_intent_fields",
            )
        try:
            sources = [DataSourceDescriptor.model_validate(s) for s in raw_sources]
        except Exception as exc:
            raise BadRequestError("Invalid source descriptor", code="invalid_source") from exc

        try:
            intent = create_data_access_intent(
                agent_sovereign_id=service.genesis_block.network_name,
                decision_id=data.get("decision_id") or str(uuid.uuid4()),
                sources=sources,
                access_types=access_types,
                signing_key=service.na_private_key,
                estimated_volume_bytes=data.get("estimated_volume_bytes"),
                now=datetime.now(timezone.utc),
            )
        except Exception as exc:
            raise RequestValidationError(str(exc), code="intent_create_failed") from exc

        return jsonify(_j(intent)), 201

    # ── Public routes ─────────────────────────────────────────────────────────

    @bp.route("/data-usage/policy", methods=["GET"])
    def get_policy():
        """Return the currently active DataLicensePolicy."""
        if not _active_policy_id:
            raise NotFoundError("No active data usage policy", code="no_policy")
        policy = _policies.get(_active_policy_id[0])
        if not policy:
            raise NotFoundError("Policy not found", code="policy_not_found")
        return jsonify(_j(policy))

    @bp.route("/data-usage/verify", methods=["POST"])
    def verify():
        """Verify a DataAccessIntent against a DataLicensePolicy."""
        data = request_json_object()
        raw_intent = data.get("intent")
        raw_policy = data.get("policy")
        if not raw_intent or not raw_policy:
            raise BadRequestError(
                "intent and policy are required",
                code="missing_verify_fields",
            )
        try:
            intent = DataAccessIntent.model_validate(raw_intent)
            policy = DataLicensePolicy.model_validate(raw_policy)
        except Exception as exc:
            raise BadRequestError("Invalid intent or policy object", code="invalid_input") from exc

        agent_keys = data.get("agent_public_keys") or [_pub_b64()]
        valid, violation_reason, violations = verify_data_access_intent(
            intent=intent,
            policy=policy,
            agent_public_keys=agent_keys,
            at_time=datetime.now(timezone.utc),
        )
        return jsonify({
            "valid": valid,
            "violation_reason": violation_reason if violation_reason else None,
            "violation_count": len(violations),
            "violations": [json.loads(v.model_dump_json()) for v in violations],
        })

    return bp
