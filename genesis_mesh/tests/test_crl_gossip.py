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


@pytest.mark.asyncio
async def test_crl_announcement_requests_newer_crl_from_peer():
    """A peer announcing a newer CRL sequence triggers a targeted CRL request."""
    sent = []

    class Connection:
        """Minimal connection stub recording messages."""

        peer_id = "node-b"

        async def send_message(self, message):
            """Record a sent message."""
            sent.append(message)

    gossip = CRLGossip("node-a", lambda key_id: None, lambda message: None)
    current = CertificateRevocationList.create_empty("na-test", sequence=1)
    gossip.set_crl(current)
    announce = MeshMessage(
        message_type=MessageType.REVOCATION,
        sender_id="node-b",
        payload={"action": "announce_sequence", "sequence": 2, "crl_id": "crl-2"},
    )

    await gossip.handle_crl_announce(announce, Connection())

    assert len(sent) == 1
    assert sent[0].recipient_id == "node-b"
    assert sent[0].payload["action"] == "request_crl"


@pytest.mark.asyncio
async def test_crl_announcement_sends_newer_local_crl_to_peer():
    """A peer with an older CRL sequence receives the current local CRL."""
    sent = []

    class Connection:
        """Minimal connection stub recording messages."""

        peer_id = "node-b"

        async def send_message(self, message):
            """Record a sent message."""
            sent.append(message)

    gossip = CRLGossip("node-a", lambda key_id: None, lambda message: None)
    current = CertificateRevocationList.create_empty("na-test", sequence=3)
    gossip.set_crl(current)
    announce = MeshMessage(
        message_type=MessageType.REVOCATION,
        sender_id="node-b",
        payload={"action": "announce_sequence", "sequence": 1, "crl_id": "crl-1"},
    )

    await gossip.handle_crl_announce(announce, Connection())

    assert len(sent) == 1
    assert sent[0].recipient_id == "node-b"
    assert sent[0].payload["action"] == "crl_data"
    assert sent[0].payload["crl"]["sequence"] == 3


@pytest.mark.asyncio
async def test_crl_reply_addresses_authenticated_peer_not_forged_sender():
    """F-02: a forged sender_id cannot redirect the CRL reply's recipient label."""
    sent = []

    class Connection:
        """Minimal connection stub with an authenticated peer identity."""

        peer_id = "M-attacker"

        async def send_message(self, message):
            """Record a sent message."""
            sent.append(message)

    gossip = CRLGossip("node-a", lambda key_id: None, lambda message: None)
    gossip.set_crl(CertificateRevocationList.create_empty("na-test", sequence=1))
    announce = MeshMessage(
        message_type=MessageType.REVOCATION,
        sender_id="P-victim",  # forged; the frame really arrived from M-attacker
        payload={"action": "announce_sequence", "sequence": 2, "crl_id": "crl-2"},
    )

    await gossip.handle_crl_announce(announce, Connection())

    assert len(sent) == 1
    assert sent[0].recipient_id == "M-attacker"


# ---------------------------------------------------------------------------
# Times (1.8.0): the issuer key at the CRL's time, expiry, validity length
# ---------------------------------------------------------------------------


def _succeeded_history(old_pub, new_pub, succeeded_at):
    from genesis_mesh.models.key_succession import NAKey, NAKeyHistory

    old = NAKey(key_sequence=0, public_key=old_pub, key_id="na-1", valid_from=None,
                succeeded_at=succeeded_at, valid_to=None, valid_to_enforced=False)
    new = NAKey(key_sequence=1, public_key=new_pub, key_id="na-2", valid_from=succeeded_at,
                succeeded_at=None, valid_to=None, valid_to_enforced=False)
    return NAKeyHistory(sovereign_id="TEST", root_public_key=None, keys=(old, new))


def _key_valid_at(history):
    def valid(public_key, at):
        key = history.key_for(public_key)
        return True if key is None else key.accepts(at)
    return valid


def _signed_crl(keypair, key_id, *, sequence, issued_at, valid_for=timedelta(hours=24)):
    crl = CertificateRevocationList(
        crl_id=f"crl-{sequence}", sequence=sequence, issued_at=issued_at,
        next_update=issued_at + valid_for, issuer=key_id, revoked_certificates=[], signatures=[])
    crl.signatures.append(sign_model(crl, keypair.private_key, key_id))
    return crl


def _crl_message(crl):
    return MeshMessage(message_type=MessageType.REVOCATION, sender_id="node-b",
                       payload={"action": "crl_data", "crl": crl.model_dump(mode="json")})


async def _no_broadcast(message):
    return None


@pytest.mark.asyncio
async def test_a_crl_signed_by_a_succeeded_key_after_its_handover_is_refused():
    """The outgoing key's holder cannot sign a CRL dated after the succession."""
    old, new = generate_keypair(), generate_keypair()
    now = datetime.now(timezone.utc)
    history = _succeeded_history(old.public_key_b64, new.public_key_b64, now - timedelta(hours=1))
    keys = {"na-1": old.public_key_b64, "na-2": new.public_key_b64}
    gossip = CRLGossip("node-a", keys.get, _no_broadcast, key_valid_at=_key_valid_at(history))

    forged = _signed_crl(old, "na-1", sequence=10**6, issued_at=now)
    assert await gossip.handle_crl_data(_crl_message(forged)) is False
    assert gossip.get_current_crl() is None

    genuine = _signed_crl(new, "na-2", sequence=1, issued_at=now)
    assert await gossip.handle_crl_data(_crl_message(genuine)) is True


@pytest.mark.asyncio
async def test_an_expired_or_overlong_or_future_crl_is_refused():
    keypair = generate_keypair()
    gossip = CRLGossip("node-a", lambda key_id: keypair.public_key_b64, _no_broadcast)
    now = datetime.now(timezone.utc)
    expired = _signed_crl(keypair, "na-1", sequence=5, issued_at=now - timedelta(hours=30))
    overlong = _signed_crl(keypair, "na-1", sequence=6, issued_at=now, valid_for=timedelta(days=365))
    future = _signed_crl(keypair, "na-1", sequence=7, issued_at=now + timedelta(hours=1))
    for crl in (expired, overlong, future):
        assert await gossip.handle_crl_data(_crl_message(crl)) is False
    assert gossip.get_current_crl() is None


@pytest.mark.asyncio
async def test_an_expired_crl_does_not_block_a_fresh_one_with_a_lower_sequence():
    """A high sequence does not hold its place once its CRL has expired."""
    keypair = generate_keypair()
    gossip = CRLGossip("node-a", lambda key_id: keypair.public_key_b64, _no_broadcast)
    now = datetime.now(timezone.utc)
    stale = _signed_crl(keypair, "na-1", sequence=10**6, issued_at=now - timedelta(hours=25))
    gossip.set_crl(stale)
    fresh = _signed_crl(keypair, "na-1", sequence=3, issued_at=now)
    assert await gossip.handle_crl_data(_crl_message(fresh)) is True
    assert gossip.get_current_crl().sequence == 3
    # While the current CRL is still valid, a lower sequence is not newer.
    older = _signed_crl(keypair, "na-1", sequence=2, issued_at=now)
    assert await gossip.handle_crl_data(_crl_message(older)) is False
