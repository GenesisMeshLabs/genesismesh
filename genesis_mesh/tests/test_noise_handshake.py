"""Proof tests for the Noise XX dependency and PyNaCl key conversion."""

import asyncio

import nacl.signing
import pytest

from genesis_mesh.transport.noise_handshake import NoiseHandshake


def test_pynacl_ed25519_keys_convert_to_curve25519_keys():
    """PyNaCl exposes the key conversion needed for Noise key binding."""
    signing_key = nacl.signing.SigningKey.generate()

    private_key = signing_key.to_curve25519_private_key()
    public_key = signing_key.verify_key.to_curve25519_public_key()

    assert bytes(private_key)
    assert bytes(public_key)
    assert len(bytes(private_key)) == 32
    assert len(bytes(public_key)) == 32


class _MemorySocket:
    """Minimal async socket pair endpoint for in-memory handshake tests."""

    def __init__(self):
        """Initialize queue-backed inbound and outbound channels."""
        self.incoming: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.outgoing: asyncio.Queue[bytes | None] | None = None
        self.closed = False

    async def send(self, data: bytes):
        """Send bytes into the paired endpoint's inbound queue."""
        assert self.outgoing is not None
        await self.outgoing.put(data)

    async def recv(self):
        """Receive bytes from this endpoint's inbound queue."""
        return await self.incoming.get()

    async def close(self):
        """Mark the endpoint closed and notify the paired endpoint."""
        self.closed = True
        if self.outgoing is not None:
            await self.outgoing.put(None)


def _socket_pair():
    """Return two connected in-memory socket endpoints."""
    first = _MemorySocket()
    second = _MemorySocket()
    first.outgoing = second.incoming
    second.outgoing = first.incoming
    return first, second


@pytest.mark.asyncio
async def test_dissononce_noise_xx_roundtrip_with_transport_encryption():
    """NoiseHandshake exchanges cert payloads and encrypted frames both ways."""
    initiator_signing_key = nacl.signing.SigningKey.generate()
    responder_signing_key = nacl.signing.SigningKey.generate()

    initiator_static = NoiseHandshake.keypair_from_join_cert_key(initiator_signing_key)
    responder_static = NoiseHandshake.keypair_from_join_cert_key(responder_signing_key)

    initiator_socket, responder_socket = _socket_pair()
    handshake = NoiseHandshake()

    initiator_result, responder_result = await asyncio.gather(
        handshake.perform_initiator(
            initiator_socket,
            initiator_static,
            "initiator-cert",
        ),
        handshake.perform_responder(
            responder_socket,
            responder_static,
            "responder-cert",
        ),
    )

    initiator_session, initiator_remote_cert, initiator_remote_static = initiator_result
    responder_session, responder_remote_cert, responder_remote_static = responder_result

    assert initiator_remote_cert == "responder-cert"
    assert responder_remote_cert == "initiator-cert"
    assert initiator_remote_static == responder_static.public.data
    assert responder_remote_static == initiator_static.public.data

    await initiator_session.send(b"hello responder")
    assert await responder_session.receive() == b"hello responder"

    await responder_session.send(b"hello initiator")
    assert await initiator_session.receive() == b"hello initiator"
