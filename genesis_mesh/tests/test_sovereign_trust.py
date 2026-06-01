"""Tests for sovereign membership attestations and local recognition policy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models import (
    MembershipAttestation,
    RecognitionPolicy,
    RecognizedIssuer,
    SovereignIdentity,
)
from genesis_mesh.trust import verify_membership_attestation


def _attestation(
    issuer_id: str = "genesis-core",
    roles: list[str] | None = None,
    status: str = "active",
    issued_at: datetime | None = None,
    valid_from: datetime | None = None,
    expires_at: datetime | None = None,
) -> MembershipAttestation:
    """Build a default attestation for verifier tests."""
    now = datetime.now(timezone.utc)
    return MembershipAttestation(
        attestation_id="att-1",
        issuer_sovereign_id=issuer_id,
        subject_id="alice",
        subject_public_key="alice-key",
        roles=roles if roles is not None else ["role:maintainer"],
        status=status,  # type: ignore[arg-type]
        issued_at=issued_at or now,
        valid_from=valid_from or (now - timedelta(minutes=1)),
        expires_at=expires_at or (now + timedelta(hours=1)),
        issued_by="genesis-core-root",
        claims={"project": "demo"},
    )


def _policy(public_key: str) -> RecognitionPolicy:
    """Build a policy that recognizes Genesis Core for maintainer trust."""
    return RecognitionPolicy(
        local_sovereign_id="ai-research",
        recognized_issuers=[
            RecognizedIssuer(
                sovereign_id="genesis-core",
                public_keys=[public_key],
                allowed_roles=["role:maintainer", "role:agent"],
            )
        ],
    )


def test_sovereign_identity_creation():
    """Sovereign identity models describe independent trust domains."""
    identity = SovereignIdentity(
        sovereign_id="genesis-core",
        network_name="USG",
        root_public_key="root-key",
        network_authority_public_key="na-key",
        endpoints=["https://na.genesismesh.connectorzzz.com"],
    )

    assert identity.sovereign_id == "genesis-core"
    assert identity.endpoints == ["https://na.genesismesh.connectorzzz.com"]


def test_valid_membership_attestation_is_accepted():
    """A recognized issuer with a valid signature can grant portable trust."""
    issuer_key = generate_keypair()
    attestation = _attestation()
    attestation.signatures.append(
        sign_model(attestation, issuer_key.private_key, "genesis-core-root")
    )

    result = verify_membership_attestation(attestation, _policy(issuer_key.public_key_b64))

    assert result.accepted is True
    assert result.reason == "accepted"


def test_unknown_issuer_is_rejected():
    """Local policy must explicitly recognize an issuer."""
    issuer_key = generate_keypair()
    attestation = _attestation(issuer_id="unknown-sovereign")
    attestation.signatures.append(
        sign_model(attestation, issuer_key.private_key, "unknown-root")
    )

    result = verify_membership_attestation(attestation, _policy(issuer_key.public_key_b64))

    assert result.accepted is False
    assert result.reason == "unknown_issuer"


def test_expired_attestation_is_rejected():
    """Attestation validity windows are enforced locally."""
    issuer_key = generate_keypair()
    now = datetime.now(timezone.utc)
    attestation = _attestation(
        issued_at=now - timedelta(days=3),
        valid_from=now - timedelta(days=3),
        expires_at=now - timedelta(days=2),
    )
    attestation.signatures.append(
        sign_model(attestation, issuer_key.private_key, "genesis-core-root")
    )

    result = verify_membership_attestation(attestation, _policy(issuer_key.public_key_b64), now)

    assert result.accepted is False
    assert result.reason == "outside_validity_window"


def test_not_yet_valid_attestation_is_rejected():
    """Future-dated attestations are not accepted early."""
    issuer_key = generate_keypair()
    now = datetime.now(timezone.utc)
    attestation = _attestation(
        issued_at=now,
        valid_from=now + timedelta(hours=1),
        expires_at=now + timedelta(hours=2),
    )
    attestation.signatures.append(
        sign_model(attestation, issuer_key.private_key, "genesis-core-root")
    )

    result = verify_membership_attestation(attestation, _policy(issuer_key.public_key_b64), now)

    assert result.accepted is False
    assert result.reason == "outside_validity_window"


def test_locally_revoked_attestation_is_rejected():
    """The accepting sovereign can withdraw trust for a specific attestation."""
    issuer_key = generate_keypair()
    attestation = _attestation()
    attestation.signatures.append(
        sign_model(attestation, issuer_key.private_key, "genesis-core-root")
    )
    policy = _policy(issuer_key.public_key_b64)
    policy.revoked_attestation_ids.add("att-1")

    result = verify_membership_attestation(attestation, policy)

    assert result.accepted is False
    assert result.reason == "locally_revoked"


def test_invalid_signature_is_rejected():
    """A recognized issuer ID is not enough without a valid issuer signature."""
    issuer_key = generate_keypair()
    wrong_key = generate_keypair()
    attestation = _attestation()
    attestation.signatures.append(
        sign_model(attestation, wrong_key.private_key, "wrong-root")
    )

    result = verify_membership_attestation(attestation, _policy(issuer_key.public_key_b64))

    assert result.accepted is False
    assert result.reason == "invalid_signature"


def test_disallowed_role_is_rejected():
    """Recognizing an issuer does not imply accepting every role it grants."""
    issuer_key = generate_keypair()
    attestation = _attestation(roles=["role:admin"])
    attestation.signatures.append(
        sign_model(attestation, issuer_key.private_key, "genesis-core-root")
    )

    result = verify_membership_attestation(attestation, _policy(issuer_key.public_key_b64))

    assert result.accepted is False
    assert result.reason == "role_not_allowed"


def test_suspended_status_is_rejected_by_default():
    """Only active attestations are accepted unless policy says otherwise."""
    issuer_key = generate_keypair()
    attestation = _attestation(status="suspended")
    attestation.signatures.append(
        sign_model(attestation, issuer_key.private_key, "genesis-core-root")
    )

    result = verify_membership_attestation(attestation, _policy(issuer_key.public_key_b64))

    assert result.accepted is False
    assert result.reason == "bad_status"
