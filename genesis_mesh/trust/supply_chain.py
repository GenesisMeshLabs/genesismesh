"""Supply-chain maintainer trust gate helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from genesis_mesh.models import (
    MembershipAttestation,
    RecognitionTreaty,
    SovereignRevocationFeed,
)

from .treaty import (
    verify_attestation_with_treaty,
    verify_sovereign_revocation_feed,
)


SUPPLY_CHAIN_MAINTAINER_PROFILE = "genesis-mesh/supply-chain-maintainer/v1"
DEFAULT_MAINTAINER_ROLE = "role:supply-chain:release-maintainer"
DEFAULT_DELEGATED_ROLE = "release-maintainer"


SupplyChainGateReason = Literal[
    "accepted",
    "profile_missing",
    "project_mismatch",
    "repository_mismatch",
    "delegated_role_mismatch",
    "role_not_allowed",
    "revocation_feed_wrong_issuer",
    "revocation_feed_stale_sequence",
    "revocation_feed_missing_signature",
    "revocation_feed_invalid_signature",
    "treaty_wrong_issuer",
    "treaty_wrong_subject",
    "treaty_locally_revoked",
    "treaty_bad_status",
    "treaty_outside_validity_window",
    "treaty_missing_signature",
    "treaty_invalid_signature",
    "attestation_unknown_issuer",
    "attestation_locally_revoked",
    "attestation_bad_status",
    "attestation_outside_validity_window",
    "attestation_role_not_allowed",
    "attestation_missing_signature",
    "attestation_invalid_signature",
]


@dataclass(frozen=True)
class SupplyChainGateResult:
    """Compact CI-safe result for a maintainer trust gate decision."""

    accepted: bool
    reason: SupplyChainGateReason
    project_id: str
    repository: str | None
    delegated_role: str
    required_role: str
    attestation_id: str
    treaty_id: str
    issuer_sovereign_id: str
    accepting_sovereign_id: str
    subject_id: str
    revocation_feed_ids: list[str] = field(default_factory=list)
    revocation_reason: str | None = None

    @property
    def exit_code(self) -> int:
        """Return the stable CI exit code for this decision."""
        return 0 if self.accepted else 10

    def to_audit_dict(self) -> dict[str, object]:
        """Return a redacted audit payload suitable for CI logs."""
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "exit_code": self.exit_code,
            "project_id": self.project_id,
            "repository": self.repository,
            "delegated_role": self.delegated_role,
            "required_role": self.required_role,
            "attestation_id": self.attestation_id,
            "treaty_id": self.treaty_id,
            "issuer_sovereign_id": self.issuer_sovereign_id,
            "accepting_sovereign_id": self.accepting_sovereign_id,
            "subject_id": self.subject_id,
            "revocation_feed_ids": self.revocation_feed_ids,
            "revocation_reason": self.revocation_reason,
            "trust_path": [
                {
                    "from": self.accepting_sovereign_id,
                    "to": self.issuer_sovereign_id,
                    "treaty_id": self.treaty_id,
                }
            ],
        }


def verify_supply_chain_maintainer_gate(
    *,
    attestation: MembershipAttestation,
    treaty: RecognitionTreaty,
    treaty_issuer_public_keys: list[str],
    project_id: str,
    required_role: str = DEFAULT_MAINTAINER_ROLE,
    repository: str | None = None,
    delegated_role: str = DEFAULT_DELEGATED_ROLE,
    revocation_feeds: list[SovereignRevocationFeed] | None = None,
    min_feed_sequence: int | None = None,
    current_time: datetime | None = None,
) -> SupplyChainGateResult:
    """Verify whether a portable maintainer attestation authorizes a CI action."""
    profile_reason = _validate_maintainer_profile(
        attestation=attestation,
        project_id=project_id,
        repository=repository,
        delegated_role=delegated_role,
        required_role=required_role,
    )
    if profile_reason is not None:
        return _result(
            accepted=False,
            reason=profile_reason,
            attestation=attestation,
            treaty=treaty,
            project_id=project_id,
            repository=repository,
            delegated_role=delegated_role,
            required_role=required_role,
        )

    revoked_attestation_ids: set[str] = set()
    feed_ids: list[str] = []
    revocation_reason: str | None = None
    for feed in revocation_feeds or []:
        feed_result = verify_sovereign_revocation_feed(
            feed,
            treaty.subject_public_keys,
            expected_issuer_sovereign_id=attestation.issuer_sovereign_id,
            min_sequence=min_feed_sequence,
        )
        if not feed_result.accepted:
            return _result(
                accepted=False,
                reason=f"revocation_feed_{feed_result.reason}",  # type: ignore[arg-type]
                attestation=attestation,
                treaty=treaty,
                project_id=project_id,
                repository=repository,
                delegated_role=delegated_role,
                required_role=required_role,
                revocation_feed_ids=[feed.feed_id],
            )
        feed_ids.append(feed.feed_id)
        revoked_attestation_ids.update(feed.revoked_attestation_ids)
        if attestation.attestation_id in feed.revocation_reasons:
            revocation_reason = feed.revocation_reasons[attestation.attestation_id]

    result = verify_attestation_with_treaty(
        attestation,
        treaty,
        treaty_issuer_public_keys,
        revoked_attestation_ids=revoked_attestation_ids,
        current_time=current_time,
    )
    return _result(
        accepted=result.accepted,
        reason=result.reason,
        attestation=attestation,
        treaty=treaty,
        project_id=project_id,
        repository=repository,
        delegated_role=delegated_role,
        required_role=required_role,
        revocation_feed_ids=feed_ids,
        revocation_reason=revocation_reason,
    )


def _validate_maintainer_profile(
    *,
    attestation: MembershipAttestation,
    project_id: str,
    repository: str | None,
    delegated_role: str,
    required_role: str,
) -> SupplyChainGateReason | None:
    """Validate the supply-chain profile before treaty-backed verification."""
    claims = attestation.claims
    if claims.get("profile") != SUPPLY_CHAIN_MAINTAINER_PROFILE:
        return "profile_missing"
    if claims.get("project_id") != project_id:
        return "project_mismatch"
    if repository is not None and claims.get("repository") != repository:
        return "repository_mismatch"
    if claims.get("delegated_role") != delegated_role:
        return "delegated_role_mismatch"
    if required_role not in attestation.roles:
        return "role_not_allowed"
    return None


def _result(
    *,
    accepted: bool,
    reason: SupplyChainGateReason,
    attestation: MembershipAttestation,
    treaty: RecognitionTreaty,
    project_id: str,
    repository: str | None,
    delegated_role: str,
    required_role: str,
    revocation_feed_ids: list[str] | None = None,
    revocation_reason: str | None = None,
) -> SupplyChainGateResult:
    """Build a redacted gate result."""
    return SupplyChainGateResult(
        accepted=accepted,
        reason=reason,
        project_id=project_id,
        repository=repository,
        delegated_role=delegated_role,
        required_role=required_role,
        attestation_id=attestation.attestation_id,
        treaty_id=treaty.treaty_id,
        issuer_sovereign_id=attestation.issuer_sovereign_id,
        accepting_sovereign_id=treaty.issuer_sovereign_id,
        subject_id=attestation.subject_id,
        revocation_feed_ids=revocation_feed_ids or [],
        revocation_reason=revocation_reason,
    )
