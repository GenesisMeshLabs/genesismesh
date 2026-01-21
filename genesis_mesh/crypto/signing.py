"""Cryptographic signing and verification."""

import base64
from typing import Union, Any

import nacl.signing
import nacl.encoding
import nacl.exceptions

from .keys import public_key_from_b64
from ..models.genesis import Signature


def sign_data(data: bytes, private_key: nacl.signing.SigningKey) -> str:
    """
    Sign data with Ed25519 private key.

    Args:
        data: Data to sign
        private_key: Ed25519 private key

    Returns:
        Base64-encoded signature
    """
    signed = private_key.sign(data)
    # Extract just the signature (last 64 bytes)
    signature = signed.signature
    return base64.b64encode(signature).decode('utf-8')


def verify_signature(
    data: bytes,
    signature_b64: str,
    public_key: Union[nacl.signing.VerifyKey, str]
) -> bool:
    """
    Verify Ed25519 signature.

    Args:
        data: Original data that was signed
        signature_b64: Base64-encoded signature
        public_key: Ed25519 public key (VerifyKey or base64 string)

    Returns:
        True if signature is valid, False otherwise
    """
    # Convert public key if needed
    if isinstance(public_key, str):
        public_key = public_key_from_b64(public_key)

    try:
        signature_bytes = base64.b64decode(signature_b64)
        public_key.verify(data, signature_bytes)
        return True
    except (nacl.exceptions.BadSignatureError, ValueError):
        return False


def sign_model(
    model: Any,
    private_key: nacl.signing.SigningKey,
    key_id: str
) -> Signature:
    """
    Sign a Pydantic model that has a to_canonical_json() method.

    Args:
        model: Model to sign
        private_key: Ed25519 private key
        key_id: Identifier for the signing key

    Returns:
        Signature object
    """
    canonical_json = model.to_canonical_json()
    signature_b64 = sign_data(canonical_json.encode('utf-8'), private_key)
    return Signature(key_id=key_id, sig=signature_b64)


def verify_model_signature(
    model: Any,
    signature: Signature,
    public_key: Union[nacl.signing.VerifyKey, str]
) -> bool:
    """
    Verify signature on a Pydantic model.

    Args:
        model: Model to verify
        signature: Signature to verify
        public_key: Ed25519 public key (VerifyKey or base64 string)

    Returns:
        True if signature is valid, False otherwise
    """
    canonical_json = model.to_canonical_json()
    return verify_signature(
        canonical_json.encode('utf-8'),
        signature.sig,
        public_key
    )
