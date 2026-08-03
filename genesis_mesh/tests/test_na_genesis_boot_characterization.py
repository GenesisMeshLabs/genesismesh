"""Regression tests for NA boot-time genesis verification (finding F-11).

Originally these pinned the pre-fix asymmetry: the NA booted from a genesis
block without verifying its ``signatures[]`` (key-match only), while the mesh
node verified every signature against ``root_public_key``.

The F-11 fix closed that gap — ``NetworkAuthorityService.__init__`` now runs
the same verification as ``node/node.py:_verify_genesis_block`` before the
key-match. The former "DEFECT PIN" tests below are flipped accordingly and now
assert that an unsigned, garbage-signed, or wrong-key-signed genesis REFUSES
to boot the NA; the properly-signed-genesis and key-match tests are unchanged
from the pre-fix characterization run.
"""

import nacl.encoding
import nacl.signing
import pytest
from datetime import datetime, timedelta, timezone

from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models import (
    GenesisBlock,
    NetworkAuthority,
    PolicyManifestRef,
    Signature,
)
from genesis_mesh.na_service.server import NetworkAuthorityService
from genesis_mesh.node.node import MeshNode


def _make_genesis(root_pub_b64: str, na_pub_b64: str) -> GenesisBlock:
    now = datetime.now(timezone.utc)
    return GenesisBlock(
        network_name="CHARACTERIZATION-TEST",
        network_version="v0.1",
        root_public_key=root_pub_b64,
        network_authority=NetworkAuthority(
            public_key=na_pub_b64,
            valid_from=now - timedelta(hours=1),
            valid_to=now + timedelta(days=90),
        ),
        policy_manifest=PolicyManifestRef(hash="sha256:test", url=None),
    )


def _na_signing_key() -> tuple[nacl.signing.SigningKey, str]:
    sk = nacl.signing.SigningKey.generate()
    pub_b64 = sk.verify_key.encode(encoder=nacl.encoding.Base64Encoder).decode("utf-8")
    return sk, pub_b64


def _boot_na(genesis: GenesisBlock, na_sk: nacl.signing.SigningKey) -> NetworkAuthorityService:
    return NetworkAuthorityService(
        genesis_block=genesis,
        na_private_key=na_sk,
        key_id="test-key",
        operator_public_keys={},
    )


# ── F-11 regression tests: the NA verifies genesis signatures at boot ──


def test_na_rejects_completely_unsigned_genesis():
    """F-11 regression: a genesis with an EMPTY signatures[] list must not
    boot the NA (pre-fix DEFECT PIN, flipped with the fix)."""
    root_kp = generate_keypair()
    na_sk, na_pub = _na_signing_key()
    genesis = _make_genesis(root_kp.public_key_b64, na_pub)
    assert genesis.signatures == []

    with pytest.raises(ValueError, match="Genesis block signature verification failed"):
        _boot_na(genesis, na_sk)


def test_na_rejects_garbage_signature_on_genesis():
    """F-11 regression: a syntactically valid but cryptographically bogus
    signature must not boot the NA (pre-fix DEFECT PIN, flipped with the fix)."""
    root_kp = generate_keypair()
    na_sk, na_pub = _na_signing_key()
    genesis = _make_genesis(root_kp.public_key_b64, na_pub)
    genesis.signatures.append(Signature(key_id="root", sig="Zm9yZ2VkLXNpZ25hdHVyZQ=="))

    with pytest.raises(ValueError, match="Genesis block signature verification failed"):
        _boot_na(genesis, na_sk)


def test_na_rejects_genesis_signed_by_wrong_key():
    """F-11 regression: a genesis signed by a key that is NOT the root key
    must not boot the NA (pre-fix DEFECT PIN, flipped with the fix)."""
    root_kp = generate_keypair()
    interloper_kp = generate_keypair()
    na_sk, na_pub = _na_signing_key()
    genesis = _make_genesis(root_kp.public_key_b64, na_pub)
    genesis.signatures.append(sign_model(genesis, interloper_kp.private_key, "root"))

    with pytest.raises(ValueError, match="Genesis block signature verification failed"):
        _boot_na(genesis, na_sk)


# ── Behavior that survived the F-11 fix unchanged ──


def test_na_boots_with_properly_root_signed_genesis():
    """A genesis correctly signed by the root key boots the NA — the target
    state; passing unchanged since the pre-fix characterization run."""
    root_kp = generate_keypair()
    na_sk, na_pub = _na_signing_key()
    genesis = _make_genesis(root_kp.public_key_b64, na_pub)
    genesis.signatures.append(sign_model(genesis, root_kp.private_key, "root"))

    service = _boot_na(genesis, na_sk)
    assert service.genesis_block is genesis


def test_na_rejects_private_key_not_matching_genesis():
    """The key-match check that predates F-11: the NA private key must match
    genesis.network_authority.public_key. The genesis is properly root-signed
    here because signature verification now runs first (F-11)."""
    root_kp = generate_keypair()
    _, na_pub = _na_signing_key()
    other_sk, _ = _na_signing_key()
    genesis = _make_genesis(root_kp.public_key_b64, na_pub)
    genesis.signatures.append(sign_model(genesis, root_kp.private_key, "root"))

    with pytest.raises(ValueError, match="NA private key does not match genesis block"):
        _boot_na(genesis, other_sk)


# ── The node-side check (the logic the F-11 fix mirrors onto the NA path) ──


def test_node_rejects_unsigned_genesis():
    """MeshNode refuses an unsigned genesis (node/node.py:64-83) — the
    verification behavior the NA path now mirrors."""
    root_kp = generate_keypair()
    na_kp = generate_keypair()
    genesis = _make_genesis(root_kp.public_key_b64, na_kp.public_key_b64)

    with pytest.raises(ValueError, match="Genesis block signature verification failed"):
        MeshNode(genesis_block=genesis, node_keypair=generate_keypair())


def test_node_accepts_root_signed_genesis():
    root_kp = generate_keypair()
    na_kp = generate_keypair()
    genesis = _make_genesis(root_kp.public_key_b64, na_kp.public_key_b64)
    genesis.signatures.append(sign_model(genesis, root_kp.private_key, "root"))

    node = MeshNode(genesis_block=genesis, node_keypair=generate_keypair())
    assert node.genesis_block is genesis
