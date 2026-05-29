"""Noise XX handshake support for encrypted peer sessions."""

from typing import Any, Optional

import nacl.signing
from dissononce.cipher.aesgcm import AESGCMCipher
from dissononce.dh.x25519.keypair import KeyPair as NoiseKeyPair
from dissononce.dh.x25519.private import PrivateKey
from dissononce.dh.x25519.x25519 import X25519DH
from dissononce.hash.sha256 import SHA256Hash
from dissononce.processing.handshakepatterns.interactive.XX import XXHandshakePattern
from dissononce.processing.impl.cipherstate import CipherState
from dissononce.processing.impl.handshakestate import HandshakeState
from dissononce.processing.impl.symmetricstate import SymmetricState


PROLOGUE = b"GenesisMeshNoiseXX"


class NoiseHandshake:
    """Runs the Noise XX handshake over an async WebSocket-like object."""

    @staticmethod
    def keypair_from_join_cert_key(
        nacl_signing_key: nacl.signing.SigningKey,
    ) -> NoiseKeyPair:
        """Derive a Noise X25519 keypair from the node's Ed25519 signing key."""
        curve_private_key = nacl_signing_key.to_curve25519_private_key()
        return X25519DH().generate_keypair(PrivateKey(bytes(curve_private_key)))

    @staticmethod
    def public_key_from_join_cert_key(
        nacl_verify_key: nacl.signing.VerifyKey,
    ) -> bytes:
        """Derive the expected Noise X25519 public key from an Ed25519 public key."""
        curve_public_key = nacl_verify_key.to_curve25519_public_key()
        return bytes(curve_public_key)

    async def perform_initiator(
        self,
        ws: Any,
        static_keypair: NoiseKeyPair,
        local_cert_b64: str,
    ) -> tuple["NoiseSession", str, bytes]:
        """
        Run Noise XX as initiator.

        Returns:
            (NoiseSession, remote_cert_b64, remote_static_pub)
        """
        handshake_state = self._new_handshake_state(
            initiator=True,
            static_keypair=static_keypair,
        )

        message_1 = bytearray()
        handshake_state.write_message(b"", message_1)
        await ws.send(bytes(message_1))

        data_2 = await ws.recv()
        payload_2 = bytearray()
        handshake_state.read_message(self._as_bytes(data_2), payload_2)
        remote_static_pub = handshake_state.rs.data

        message_3 = bytearray()
        split = handshake_state.write_message(local_cert_b64.encode("utf-8"), message_3)
        await ws.send(bytes(message_3))

        if split is None:
            raise ValueError("Noise initiator handshake did not complete")

        send_cipher, receive_cipher = split
        return (
            NoiseSession(ws, send_cipher, receive_cipher),
            payload_2.decode("utf-8"),
            remote_static_pub,
        )

    async def perform_responder(
        self,
        ws: Any,
        static_keypair: NoiseKeyPair,
        local_cert_b64: str,
    ) -> tuple["NoiseSession", str, bytes]:
        """
        Run Noise XX as responder.

        Returns:
            (NoiseSession, remote_cert_b64, remote_static_pub)
        """
        handshake_state = self._new_handshake_state(
            initiator=False,
            static_keypair=static_keypair,
        )

        data_1 = await ws.recv()
        payload_1 = bytearray()
        handshake_state.read_message(self._as_bytes(data_1), payload_1)

        message_2 = bytearray()
        handshake_state.write_message(local_cert_b64.encode("utf-8"), message_2)
        await ws.send(bytes(message_2))

        data_3 = await ws.recv()
        payload_3 = bytearray()
        split = handshake_state.read_message(self._as_bytes(data_3), payload_3)
        remote_static_pub = handshake_state.rs.data

        if split is None:
            raise ValueError("Noise responder handshake did not complete")

        receive_cipher, send_cipher = split
        return (
            NoiseSession(ws, send_cipher, receive_cipher),
            payload_3.decode("utf-8"),
            remote_static_pub,
        )

    def _new_handshake_state(
        self,
        *,
        initiator: bool,
        static_keypair: NoiseKeyPair,
    ) -> HandshakeState:
        """Create and initialize a Noise XX handshake state."""
        cipher_state = CipherState(AESGCMCipher())
        symmetric_state = SymmetricState(cipher_state, SHA256Hash())
        handshake_state = HandshakeState(symmetric_state, X25519DH())
        handshake_state.initialize(
            XXHandshakePattern(),
            initiator=initiator,
            prologue=PROLOGUE,
            s=static_keypair,
        )
        return handshake_state

    @staticmethod
    def _as_bytes(data: Any) -> bytes:
        """Normalize WebSocket payloads into bytes for Noise processing."""
        if isinstance(data, bytes):
            return data
        if isinstance(data, bytearray):
            return bytes(data)
        if isinstance(data, str):
            return data.encode("utf-8")
        raise TypeError(f"Expected WebSocket bytes or str payload, got {type(data)!r}")


class NoiseSession:
    """Wraps a WebSocket with Noise transport-mode encryption."""

    def __init__(self, ws: Any, send_cipher: Any, receive_cipher: Any):
        """Store the underlying socket and transport-mode cipher states."""
        self._ws = ws
        self._send_cipher = send_cipher
        self._receive_cipher = receive_cipher
        self._closed = False

    async def send(self, plaintext: bytes) -> None:
        """Encrypt and send a plaintext transport frame."""
        if self._closed:
            raise ConnectionError("Noise session is closed")
        ciphertext = self._send_cipher.encrypt_with_ad(b"", plaintext)
        await self._ws.send(ciphertext)

    async def receive(self) -> Optional[bytes]:
        """Receive and decrypt one transport frame."""
        if self._closed:
            return None
        data = await self._ws.recv()
        if data is None:
            return None
        return self._receive_cipher.decrypt_with_ad(b"", NoiseHandshake._as_bytes(data))

    async def close(self) -> None:
        """Close the encrypted session and underlying WebSocket."""
        if self._closed:
            return
        self._closed = True
        await self._ws.close()

    @property
    def is_closed(self) -> bool:
        """Return whether the session has been closed locally."""
        return self._closed
