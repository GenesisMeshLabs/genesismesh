"""Tests for signed recognition treaties and treaty-backed attestations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models import (
    MembershipAttestation,
    RecognitionTreaty,
    RecognitionTreatyScope,
)
from genesis_mesh.trust import verify_attestation_with_treaty, verify_recognition_treaty


def _treaty(
    issuer_id: str = "sovereign-a",
    subject_id: str = "sovereign-b",
    subject_public_key: str | None = None,
    roles: list[str] | None = None,
    status: str = "active",
    issued_at: datetime | None = None,
    valid_from: datetime | None = None,
    expires_at: datetime | None = None,
) -> RecognitionTreaty:
    """Build a default recognition treaty for verifier tests."""
    now = datetime.now(timezone.utc)
    return RecognitionTreaty(
        treaty_id="treaty-1",
        issuer_sovereign_id=issuer_id,
        subject_sovereign_id=subject_id,
        subject_public_keys=[subject_public_key or "subject-key"],
        scope=RecognitionTreatyScope(allowed_roles=roles or ["role:service:maintainer"]),
        status=status,  # type: ignore[arg-type]
        issued_at=issued_at or now,
        valid_from=valid_from or (now - timedelta(minutes=1)),
        expires_at=expires_at or (now + timedelta(hours=1)),
        issued_by="sovereign-a-na",
    )


def _attestation(
    issuer_id: str = "sovereign-b",
    roles: list[str] | None = None,
) -> MembershipAttestation:
    """Build a default membership attestation for treaty tests."""
    now = datetime.now(timezone.utc)
    return MembershipAttestation(
        attestation_id="att-1",
        issuer_sovereign_id=issuer_id,
        subject_id="alice",
        subject_public_key="alice-key",
        roles=roles or ["role:service:maintainer"],
        status="active",
        issued_at=now,
        valid_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        issued_by="sovereign-b-na",
        claims={"project": "demo"},
    )


def test_valid_recognition_treaty_is_accepted():
    """A signed active treaty from the expected issuer is accepted."""
    issuer_key = generate_keypair()
    treaty = _treaty()
    treaty.signatures.append(sign_model(treaty, issuer_key.private_key, "sovereign-a-na"))

    result = verify_recognition_treaty(
        treaty,
        [issuer_key.public_key_b64],
        expected_issuer_sovereign_id="sovereign-a",
        expected_subject_sovereign_id="sovereign-b",
    )

    assert result.accepted is True
    assert result.reason == "accepted"


def test_recognition_treaty_rejects_invalid_signature():
    """The treaty issuer ID is not enough without a valid issuer signature."""
    issuer_key = generate_keypair()
    wrong_key = generate_keypair()
    treaty = _treaty()
    treaty.signatures.append(sign_model(treaty, wrong_key.private_key, "wrong"))

    result = verify_recognition_treaty(treaty, [issuer_key.public_key_b64])

    assert result.accepted is False
    assert result.reason == "invalid_signature"


def test_recognition_treaty_rejects_expired_window():
    """Expired treaties stop future trust decisions."""
    issuer_key = generate_keypair()
    now = datetime.now(timezone.utc)
    treaty = _treaty(
        issued_at=now - timedelta(days=3),
        valid_from=now - timedelta(days=3),
        expires_at=now - timedelta(days=2),
    )
    treaty.signatures.append(sign_model(treaty, issuer_key.private_key, "sovereign-a-na"))

    result = verify_recognition_treaty(treaty, [issuer_key.public_key_b64], current_time=now)

    assert result.accepted is False
    assert result.reason == "outside_validity_window"


def test_attestation_is_accepted_through_treaty_scope():
    """Treaty scope can accept an attestation from the treaty subject sovereign."""
    treaty_issuer_key = generate_keypair()
    subject_key = generate_keypair()
    treaty = _treaty(subject_public_key=subject_key.public_key_b64)
    treaty.signatures.append(sign_model(treaty, treaty_issuer_key.private_key, "a"))
    attestation = _attestation()
    attestation.signatures.append(sign_model(attestation, subject_key.private_key, "b"))

    result = verify_attestation_with_treaty(
        attestation,
        treaty,
        [treaty_issuer_key.public_key_b64],
    )

    assert result.accepted is True
    assert result.reason == "accepted"


def test_attestation_role_outside_treaty_scope_is_rejected():
    """Treaties do not imply accepting every role the subject sovereign grants."""
    treaty_issuer_key = generate_keypair()
    subject_key = generate_keypair()
    treaty = _treaty(subject_public_key=subject_key.public_key_b64)
    treaty.signatures.append(sign_model(treaty, treaty_issuer_key.private_key, "a"))
    attestation = _attestation(roles=["role:admin"])
    attestation.signatures.append(sign_model(attestation, subject_key.private_key, "b"))

    result = verify_attestation_with_treaty(
        attestation,
        treaty,
        [treaty_issuer_key.public_key_b64],
    )

    assert result.accepted is False
    assert result.reason == "attestation_role_not_allowed"


def test_revoked_treaty_blocks_attestation_verification():
    """Local treaty revocation prevents treaty-backed attestation acceptance."""
    treaty_issuer_key = generate_keypair()
    subject_key = generate_keypair()
    treaty = _treaty(subject_public_key=subject_key.public_key_b64)
    treaty.signatures.append(sign_model(treaty, treaty_issuer_key.private_key, "a"))
    attestation = _attestation()
    attestation.signatures.append(sign_model(attestation, subject_key.private_key, "b"))

    result = verify_attestation_with_treaty(
        attestation,
        treaty,
        [treaty_issuer_key.public_key_b64],
        revoked_treaty_ids={"treaty-1"},
    )

    assert result.accepted is False
    assert result.reason == "treaty_locally_revoked"
