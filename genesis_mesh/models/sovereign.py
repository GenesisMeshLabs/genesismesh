"""Sovereign trust-domain and membership attestation models."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .genesis import Signature


AttestationStatus = Literal["active", "suspended", "revoked"]


def _default_accepted_statuses() -> list[AttestationStatus]:
    """Return the default locally accepted attestation statuses."""
    return ["active"]


class SovereignIdentity(BaseModel):
    """Public identity for an independently administered trust domain."""

    sovereign_id: str = Field(..., description="Stable sovereign identifier")
    network_name: str = Field(..., description="Mesh network name")
    root_public_key: str = Field(..., description="Base64 root public key")
    network_authority_public_key: str | None = Field(
        None,
        description="Optional base64 Network Authority public key",
    )
    endpoints: list[str] = Field(
        default_factory=list,
        description="Optional public endpoints for this sovereign",
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Optional local metadata for operators and demos",
    )

    def to_canonical_json(self) -> str:
        """Return canonical JSON used for signing and verification."""
        data = self.model_dump(mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))


class MembershipAttestation(BaseModel):
    """Signed claim that a subject is a member of a sovereign community."""

    attestation_id: str = Field(..., description="Unique attestation identifier")
    issuer_sovereign_id: str = Field(..., description="Sovereign issuing this claim")
    subject_id: str = Field(..., description="Human, agent, or service identifier")
    subject_public_key: str | None = Field(
        None,
        description="Optional subject public key bound to this claim",
    )
    roles: list[str] = Field(
        default_factory=list,
        description="Roles granted by the issuing sovereign",
    )
    status: AttestationStatus = Field(
        "active",
        description="Issuer-side membership status",
    )
    issued_at: datetime = Field(..., description="UTC issue timestamp")
    valid_from: datetime = Field(..., description="UTC validity start")
    expires_at: datetime = Field(..., description="UTC expiry timestamp")
    issued_by: str = Field(..., description="Issuer signing key identifier")
    claims: dict = Field(
        default_factory=dict,
        description="Optional scoped claims carried by the attestation",
    )
    signatures: list[Signature] = Field(
        default_factory=list,
        description="Issuer signatures over the canonical attestation",
    )

    @model_validator(mode="after")
    def _check_window(self) -> "MembershipAttestation":
        """Reject invalid validity windows."""
        if self.expires_at <= self.valid_from:
            raise ValueError("expires_at must be after valid_from")
        if self.issued_at > self.expires_at:
            raise ValueError("issued_at must not be after expires_at")
        return self

    def to_canonical_json(self) -> str:
        """Return canonical JSON used for signing and verification."""
        data = self.model_dump(exclude={"signatures"}, mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def is_valid(self, current_time: datetime | None = None) -> bool:
        """Return whether the attestation is active and within its time window."""
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        max_skew = timedelta(minutes=5)
        return (
            self.status == "active"
            and (self.valid_from - max_skew) <= current_time <= (self.expires_at + max_skew)
        )


class RecognizedIssuer(BaseModel):
    """Local policy entry for one accepted issuing sovereign."""

    sovereign_id: str = Field(..., description="Accepted issuer sovereign ID")
    public_keys: list[str] = Field(
        ...,
        min_length=1,
        description="Accepted base64 issuer signing public keys",
    )
    allowed_roles: list[str] = Field(
        default_factory=list,
        description="Allowed roles from this issuer; empty means any role",
    )
    accepted_statuses: list[AttestationStatus] = Field(
        default_factory=_default_accepted_statuses,
        description="Accepted attestation statuses",
    )

    def allows_roles(self, roles: list[str]) -> bool:
        """Return whether all roles are allowed by this issuer policy."""
        return not self.allowed_roles or all(role in self.allowed_roles for role in roles)


class RecognitionPolicy(BaseModel):
    """Local policy for accepting membership attestations from other sovereigns."""

    local_sovereign_id: str = Field(..., description="Sovereign applying this policy")
    recognized_issuers: list[RecognizedIssuer] = Field(
        default_factory=list,
        description="Issuers accepted by the local sovereign",
    )
    revoked_attestation_ids: set[str] = Field(
        default_factory=set,
        description="Locally revoked attestation IDs",
    )

    def get_issuer(self, sovereign_id: str) -> RecognizedIssuer | None:
        """Return the recognized issuer policy for a sovereign ID."""
        for issuer in self.recognized_issuers:
            if issuer.sovereign_id == sovereign_id:
                return issuer
        return None
