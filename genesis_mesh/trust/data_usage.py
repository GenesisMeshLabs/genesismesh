"""Data Usage Attestation trust logic (v0.47).

verify_data_access_intent:  pre-execution compliance check
verify_data_access_record:  post-execution compliance check
create_data_access_intent:  signed intent builder
DataUsageGate:              BoundaryEngine gate
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Literal

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.context import GateResult
from ..models.data_usage import (
    DataAccessIntent,
    DataAccessRecord,
    DataLicensePolicy,
    DataSourceDescriptor,
    DataUsageViolation,
)

DataUsageViolationReason = Literal[
    "source_not_licensed",
    "access_type_not_permitted",
    "prohibited_classification",
    "volume_cap_exceeded",
    "intent_expired",
    "policy_expired",
    "intent_exceeds_license",
]


def _check_intent_vs_policy(
    intent: DataAccessIntent,
    policy: DataLicensePolicy,
    at_time: datetime,
    *,
    is_record: bool = False,
    sources: list[DataSourceDescriptor] | None = None,
    access_types: list[str] | None = None,
    volume_bytes: int | None = None,
    ref_intent_id: str | None = None,
    ref_record_id: str | None = None,
) -> list[DataUsageViolation]:
    violations: list[DataUsageViolation] = []
    agent_id = intent.agent_sovereign_id
    sources = sources or intent.declared_sources
    access_types = access_types or intent.declared_access_types
    vol = volume_bytes if volume_bytes is not None else intent.estimated_volume_bytes

    # Expiry checks
    if at_time > intent.expires_at:
        violations.append(DataUsageViolation(
            intent_id=ref_intent_id or intent.intent_id,
            record_id=ref_record_id,
            agent_sovereign_id=agent_id,
            violation_type="intent_expired",
            detail=f"Intent expired at {intent.expires_at}",
            detected_at=at_time,
        ))
    if at_time > policy.valid_until or at_time < policy.valid_from:
        violations.append(DataUsageViolation(
            intent_id=ref_intent_id or intent.intent_id,
            record_id=ref_record_id,
            agent_sovereign_id=agent_id,
            violation_type="policy_expired",
            detail=f"Policy not valid at {at_time}",
            detected_at=at_time,
        ))

    # Source allowlist
    allowed_ids = set(policy.allowed_source_ids)
    for src in sources:
        if src.source_id not in allowed_ids:
            violations.append(DataUsageViolation(
                intent_id=ref_intent_id or intent.intent_id,
                record_id=ref_record_id,
                agent_sovereign_id=agent_id,
                violation_type="source_not_licensed",
                detail=f"Source '{src.source_id}' not in allowed_source_ids",
                detected_at=at_time,
            ))
        # Prohibited classification
        prohibited = set(policy.prohibited_classification_tags)
        overlap = set(src.classification_tags) & prohibited
        if overlap:
            violations.append(DataUsageViolation(
                intent_id=ref_intent_id or intent.intent_id,
                record_id=ref_record_id,
                agent_sovereign_id=agent_id,
                violation_type="prohibited_classification",
                detail=f"Source '{src.source_id}' has prohibited tags: {sorted(overlap)}",
                detected_at=at_time,
            ))

    # Access type check
    allowed_types = set(policy.allowed_access_types) or {"read"}
    for at in access_types:
        if at not in allowed_types:
            violations.append(DataUsageViolation(
                intent_id=ref_intent_id or intent.intent_id,
                record_id=ref_record_id,
                agent_sovereign_id=agent_id,
                violation_type="access_type_not_permitted",
                detail=f"Access type '{at}' not in allowed_access_types",
                detected_at=at_time,
            ))

    # Volume cap
    if (
        policy.max_volume_bytes_per_session is not None
        and vol is not None
        and vol > policy.max_volume_bytes_per_session
    ):
        violations.append(DataUsageViolation(
            intent_id=ref_intent_id or intent.intent_id,
            record_id=ref_record_id,
            agent_sovereign_id=agent_id,
            violation_type="volume_cap_exceeded",
            detail=(
                f"Volume {vol} > max {policy.max_volume_bytes_per_session}"
            ),
            detected_at=at_time,
        ))

    return violations


def verify_data_access_intent(
    intent: DataAccessIntent,
    policy: DataLicensePolicy,
    agent_public_keys: list[str],
    *,
    at_time: datetime | None = None,
) -> tuple[bool, DataUsageViolationReason | None, list[DataUsageViolation]]:
    """Pre-execution compliance check."""
    t = at_time or datetime.now(timezone.utc)

    # Signature
    if intent.signature is None:
        return False, "intent_exceeds_license", [DataUsageViolation(
            intent_id=intent.intent_id,
            agent_sovereign_id=intent.agent_sovereign_id,
            violation_type="intent_exceeds_license",
            detail="Missing intent signature",
            detected_at=t,
        )]
    verified = False
    for pub_b64 in agent_public_keys:
        pub = nacl.signing.VerifyKey(base64.b64decode(pub_b64))
        if verify_model_signature(intent, intent.signature, pub):
            verified = True
            break
    if not verified:
        return False, "intent_exceeds_license", [DataUsageViolation(
            intent_id=intent.intent_id,
            agent_sovereign_id=intent.agent_sovereign_id,
            violation_type="intent_exceeds_license",
            detail="Invalid intent signature",
            detected_at=t,
        )]

    violations = _check_intent_vs_policy(intent, policy, t)
    if violations:
        return False, violations[0].violation_type, violations  # type: ignore[return-value]
    return True, None, []


def verify_data_access_record(
    record: DataAccessRecord,
    intent: DataAccessIntent,
    policy: DataLicensePolicy,
    agent_public_keys: list[str],
    *,
    at_time: datetime | None = None,
) -> tuple[bool, DataUsageViolationReason | None, list[DataUsageViolation]]:
    """Post-execution compliance check."""
    t = at_time or datetime.now(timezone.utc)

    if record.signature is None:
        return False, "intent_exceeds_license", [DataUsageViolation(
            record_id=record.record_id,
            agent_sovereign_id=record.agent_sovereign_id,
            violation_type="intent_exceeds_license",
            detail="Missing record signature",
            detected_at=t,
        )]
    verified = False
    for pub_b64 in agent_public_keys:
        pub = nacl.signing.VerifyKey(base64.b64decode(pub_b64))
        if verify_model_signature(record, record.signature, pub):
            verified = True
            break
    if not verified:
        return False, "intent_exceeds_license", [DataUsageViolation(
            record_id=record.record_id,
            agent_sovereign_id=record.agent_sovereign_id,
            violation_type="intent_exceeds_license",
            detail="Invalid record signature",
            detected_at=t,
        )]

    violations = _check_intent_vs_policy(
        intent, policy, t,
        is_record=True,
        sources=record.accessed_sources,
        access_types=record.access_types_used,
        volume_bytes=record.actual_volume_bytes,
        ref_intent_id=intent.intent_id,
        ref_record_id=record.record_id,
    )
    if violations:
        return False, violations[0].violation_type, violations  # type: ignore[return-value]
    return True, None, []


def create_data_access_intent(
    agent_sovereign_id: str,
    decision_id: str,
    sources: list[DataSourceDescriptor],
    access_types: list[str],
    signing_key: nacl.signing.SigningKey,
    *,
    estimated_volume_bytes: int | None = None,
    valid_for_seconds: int = 300,
    now: datetime | None = None,
) -> DataAccessIntent:
    now = now or datetime.now(timezone.utc)
    intent = DataAccessIntent(
        agent_sovereign_id=agent_sovereign_id,
        decision_id=decision_id,
        declared_sources=sources,
        declared_access_types=access_types,
        estimated_volume_bytes=estimated_volume_bytes,
        declared_at=now,
        expires_at=now + timedelta(seconds=valid_for_seconds),
    )
    sig = sign_model(intent, signing_key, agent_sovereign_id)
    return intent.model_copy(update={"signature": sig})


class DataUsageGate:
    """BoundaryEngine gate enforcing data license policy pre-execution."""

    gate_name = "data_usage"

    def __init__(
        self,
        intent: DataAccessIntent,
        policy: DataLicensePolicy,
        agent_public_keys: list[str],
    ) -> None:
        self._intent = intent
        self._policy = policy
        self._agent_keys = agent_public_keys

    def __call__(self, context: object, terms: object) -> GateResult:
        ok, reason, _ = verify_data_access_intent(
            self._intent, self._policy, self._agent_keys
        )
        return GateResult(
            gate_name=self.gate_name,
            passed=ok,
            detail=reason or "compliant",
        )
