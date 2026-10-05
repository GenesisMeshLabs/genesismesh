"""`genesis-mesh genesis verify` exit codes (v1.0.2): scripts rely on them."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from click.testing import CliRunner

from genesis_mesh.cli.main import cli
from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models import GenesisBlock, NetworkAuthority, PolicyManifestRef


def _genesis(tmp_path, *, signed=True, tamper=False):
    root = generate_keypair()
    now = datetime.now(timezone.utc)
    genesis = GenesisBlock(
        network_name="verify-me", network_version="v0.1", root_public_key=root.public_key_b64,
        network_authority=NetworkAuthority(public_key=root.public_key_b64, valid_from=now,
                                           valid_to=now + timedelta(days=1)),
        policy_manifest=PolicyManifestRef(hash="sha256:test", url=None),
    )
    if signed:
        genesis.signatures.append(sign_model(genesis, root.private_key, "root"))
    data = json.loads(genesis.model_dump_json())
    if tamper:
        data["network_name"] = "tampered"
    path = tmp_path / "genesis.signed.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_a_valid_genesis_exits_zero(tmp_path):
    result = CliRunner().invoke(cli, ["genesis", "verify", "--genesis", _genesis(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "verified successfully" in result.output


def test_a_tampered_genesis_exits_non_zero(tmp_path):
    result = CliRunner().invoke(cli, ["genesis", "verify", "--genesis", _genesis(tmp_path, tamper=True)])
    assert result.exit_code == 1
    assert "INVALID" in result.output


def test_an_unsigned_genesis_exits_non_zero(tmp_path):
    result = CliRunner().invoke(cli, ["genesis", "verify", "--genesis", _genesis(tmp_path, signed=False)])
    assert result.exit_code == 1
