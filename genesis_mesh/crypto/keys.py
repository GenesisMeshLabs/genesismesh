"""Key generation and management for Ed25519 cryptography."""

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import nacl.signing
import nacl.encoding


@dataclass
class KeyPair:
    """Ed25519 key pair."""
    private_key: nacl.signing.SigningKey
    public_key: nacl.signing.VerifyKey

    @property
    def public_key_b64(self) -> str:
        """Get base64-encoded public key."""
        return base64.b64encode(bytes(self.public_key)).decode('utf-8')

    @property
    def private_key_b64(self) -> str:
        """Get base64-encoded private key."""
        return base64.b64encode(bytes(self.private_key)).decode('utf-8')


def generate_keypair() -> KeyPair:
    """
    Generate a new Ed25519 key pair.

    Returns:
        KeyPair: New cryptographic key pair
    """
    private_key = nacl.signing.SigningKey.generate()
    public_key = private_key.verify_key
    return KeyPair(private_key=private_key, public_key=public_key)


def save_keypair(keypair: KeyPair, base_path: str, key_id: Optional[str] = None) -> tuple[Path, Path]:
    """
    Save key pair to files.

    Args:
        keypair: Key pair to save
        base_path: Base path for key files (without extension)
        key_id: Optional key identifier to include in files

    Returns:
        Tuple of (private_key_path, public_key_path)
    """
    base = Path(base_path)
    base.parent.mkdir(parents=True, exist_ok=True)

    private_path = base.with_suffix('.key')
    public_path = base.with_suffix('.pub')

    # Save private key
    with open(private_path, 'w') as f:
        f.write(f"# Ed25519 Private Key\n")
        if key_id:
            f.write(f"# Key ID: {key_id}\n")
        f.write(f"{keypair.private_key_b64}\n")

    # Save public key
    with open(public_path, 'w') as f:
        f.write(f"# Ed25519 Public Key\n")
        if key_id:
            f.write(f"# Key ID: {key_id}\n")
        f.write(f"{keypair.public_key_b64}\n")

    # Restrict private key permissions
    private_path.chmod(0o600)

    return private_path, public_path


def load_private_key(path: str) -> nacl.signing.SigningKey:
    """
    Load private key from file.

    Args:
        path: Path to private key file

    Returns:
        SigningKey: Ed25519 private key
    """
    with open(path, 'r') as f:
        lines = f.readlines()
        # Skip comment lines
        key_lines = [line.strip() for line in lines if not line.startswith('#')]
        key_b64 = ''.join(key_lines)

    key_bytes = base64.b64decode(key_b64)
    return nacl.signing.SigningKey(key_bytes)


def load_public_key(path: str) -> nacl.signing.VerifyKey:
    """
    Load public key from file.

    Args:
        path: Path to public key file

    Returns:
        VerifyKey: Ed25519 public key
    """
    with open(path, 'r') as f:
        lines = f.readlines()
        # Skip comment lines
        key_lines = [line.strip() for line in lines if not line.startswith('#')]
        key_b64 = ''.join(key_lines)

    key_bytes = base64.b64decode(key_b64)
    return nacl.signing.VerifyKey(key_bytes)


def public_key_from_b64(public_key_b64: str) -> nacl.signing.VerifyKey:
    """
    Create VerifyKey from base64-encoded public key.

    Args:
        public_key_b64: Base64-encoded public key

    Returns:
        VerifyKey: Ed25519 public key
    """
    key_bytes = base64.b64decode(public_key_b64)
    return nacl.signing.VerifyKey(key_bytes)
