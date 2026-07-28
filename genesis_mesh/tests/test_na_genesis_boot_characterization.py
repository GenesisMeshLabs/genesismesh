"""Characterization tests for NA boot-time genesis handling (finding F-11).

These tests pin the CURRENT asymmetry the F-11 remediation will close
(assessment report F-11, evidence ``na_service/server.py:90-95`` vs
``node/node.py:64-83``):

  * The Network Authority service boots from a genesis block WITHOUT
    verifying its ``signatures[]`` — it only checks that its own private key
    matches ``genesis.network_authority.public_key``.
  * The mesh node DOES verify every genesis signature against
    ``root_public_key`` and refuses to construct otherwise.

Tests marked "DEFECT PIN" assert the NA-side non-verification on purpose;
the F-11 fix is EXPECTED to flip them (unsigned / badly-signed genesis must
then fail NA boot), and they must be updated deliberately as part of that
fix. The properly-signed-genesis test and the key-match test must KEEP
passing after the fix.

NOTE for the F-11 implementer: the shared ``na_service`` fixture in
``conftest.py`` builds an UNSIGNED genesis, so enabling verification will
break every test that uses it until that fixture signs its genesis. The
helper below shows the shape of a correctly signed fixture.
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


# ── DEFECT PINS: the NA does not verify genesis signatures at boot ──


def test_na_boots_with_completely_unsigned_genesis():
    """DEFECT PIN (F-11): a genesis with an EMPTY signatures[] list boots the
    NA today. After the F-11 fix this must raise instead — update this test
    deliberately (and sign the conftest.py fixture genesis) when it does."""
    root_kp = generate_keypair()
    na_sk, na_pub = _na_signing_key()
    genesis = _make_genesis(root_kp.public_key_b64, na_pub)
    assert genesis.signatures == []

    service = _boot_na(genesis, na_sk)
    assert service.genesis_block is genesis


def test_na_boots_with_garbage_signature_on_genesis():
    """DEFECT PIN (F-11): a syntactically valid but cryptographically bogus
    signature is never checked on the NA path — boot succeeds today."""
    root_kp = generate_keypair()
    na_sk, na_pub = _na_signing_key()
    genesis = _make_genesis(root_kp.public_key_b64, na_pub)
    genesis.signatures.append(Signature(key_id="root", sig="Zm9yZ2VkLXNpZ25hdHVyZQ=="))

    service = _boot_na(genesis, na_sk)
    assert service.genesis_block is genesis


def test_na_boots_with_genesis_signed_by_wrong_key():
    """DEFECT PIN (F-11): a genesis signed by a key that is NOT the root key
    also boots the NA today — the signer's identity is never checked."""
    root_kp = generate_keypair()
    interloper_kp = generate_keypair()
    na_sk, na_pub = _na_signing_key()
    genesis = _make_genesis(root_kp.public_key_b64, na_pub)
    genesis.signatures.append(sign_model(genesis, interloper_kp.private_key, "root"))

    service = _boot_na(genesis, na_sk)
    assert service.genesis_block is genesis


# ── Behavior that must SURVIVE the F-11 fix ──


def test_na_boots_with_properly_root_signed_genesis():
    """A genesis correctly signed by the root key boots the NA — this is the
    target state and must keep passing unchanged after the F-11 fix."""
    root_kp = generate_keypair()
    na_sk, na_pub = _na_signing_key()
    genesis = _make_genesis(root_kp.public_key_b64, na_pub)
    genesis.signatures.append(sign_model(genesis, root_kp.private_key, "root"))

    service = _boot_na(genesis, na_sk)
    assert service.genesis_block is genesis


def test_na_rejects_private_key_not_matching_genesis():
    """The one boot-time check the NA DOES perform today: its private key
    must match genesis.network_authority.public_key. Must survive F-11."""
    root_kp = generate_keypair()
    _, na_pub = _na_signing_key()
    other_sk, _ = _na_signing_key()
    genesis = _make_genesis(root_kp.public_key_b64, na_pub)

    with pytest.raises(ValueError, match="NA private key does not match genesis block"):
        _boot_na(genesis, other_sk)


# ── The node-side contrast (the logic F-11 will mirror onto the NA path) ──


def test_node_rejects_unsigned_genesis():
    """MeshNode refuses an unsigned genesis (node/node.py:64-83) — the
    verification behavior the NA path lacks."""
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
