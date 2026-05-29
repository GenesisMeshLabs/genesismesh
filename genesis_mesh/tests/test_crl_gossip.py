"""Tests for CRL gossip propagation behavior."""

from datetime import datetime, timedelta, timezone

import pytest

from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.gossip.crl_gossip import CRLGossip
from genesis_mesh.models.revocation import CertificateRevocationList, RevokedCertificate
from genesis_mesh.transport.protocol import MeshMessage, MessageType


@pytest.mark.asyncio
async def test_newer_signed_crl_is_accepted_and_announced():
    """A valid newer CRL should update local state and gossip its sequence."""
    na_keypair = generate_keypair()
    broadcasts = []

    async def broadcast(message):
        """Record broadcast messages for assertion."""
        broadcasts.append(message)

    gossip = CRLGossip(
        "node-a",
        lambda key_id: na_keypair.public_key_b64 if key_id == "na-test" else None,
        broadcast,
    )
    current = CertificateRevocationList.create_empty("na-test", sequence=0)
    current.signatures.append(sign_model(current, na_keypair.private_key, "na-test"))
    gossip.set_crl(current)

    now = datetime.now(timezone.utc)
    newer = CertificateRevocationList(
        crl_id="crl-1",
        sequence=1,
        issued_at=now,
        next_update=now + timedelta(hours=24),
        issuer="na-test",
        revoked_certificates=[
            RevokedCertificate(
                certificate_id="cert-b",
                revoked_at=now,
                reason="key_compromise",
                issuer="na-test",
            )
        ],
        signatures=[],
    )
    newer.signatures.append(sign_model(newer, na_keypair.private_key, "na-test"))

    accepted = await gossip.handle_crl_data(
        MeshMessage(
            message_type=MessageType.REVOCATION,
            sender_id="node-b",
            payload={"action": "crl_data", "crl": newer.model_dump(mode="json")},
        )
    )

    assert accepted is True
    assert gossip.get_current_crl().sequence == 1
    assert gossip.is_certificate_revoked("cert-b") is True
    assert len(broadcasts) == 1
    assert broadcasts[0].payload["action"] == "announce_sequence"
    assert broadcasts[0].payload["sequence"] == 1
