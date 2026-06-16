"""Tests for the `genesis-mesh fleet` command group."""

from __future__ import annotations

import tomllib
from pathlib import Path

from click.testing import CliRunner

from genesis_mesh.cli.fleet_ops import _load_fleet_manifest
from genesis_mesh.cli.main import cli
from genesis_mesh.crypto import public_key_from_b64, verify_model_signature
from genesis_mesh.models import GenesisBlock


def _generate(tmp_path: Path, *args: str):
    return CliRunner().invoke(
        cli,
        ["fleet", "generate", "--output", str(tmp_path / "fleet"), *args],
    )


def test_generate_creates_runnable_fleet(tmp_path):
    """generate scaffolds per-NA keys, signed genesis, configs, and a manifest."""
    result = _generate(tmp_path, "--count", "3", "--prefix", "demo", "--base-port", "9100")
    assert result.exit_code == 0, result.output

    fleet_dir = tmp_path / "fleet"
    manifest = tomllib.loads((fleet_dir / "fleet.toml").read_text(encoding="utf-8"))
    assert len(manifest["fleet"]["nodes"]) == 3

    seen_na_keys = set()
    for index, name in enumerate(("demo-1", "demo-2", "demo-3")):
        home = fleet_dir / name
        config = tomllib.loads((home / "genesis-mesh.toml").read_text(encoding="utf-8"))
        assert config["network"]["name"] == name
        assert config["na"]["port"] == 9100 + index
        assert config["network"]["na_endpoint"].endswith(str(9100 + index))
        for key in ("na.key", "operator.key", "operator.pub", "root.key"):
            assert (home / "keys" / key).exists(), key

        # Each sovereign is independent: distinct, validly-signed genesis.
        genesis = GenesisBlock.model_validate_json(
            (home / "genesis.signed.json").read_text(encoding="utf-8")
        )
        assert genesis.network_name == name
        assert genesis.signatures, "genesis should be signed"
        root_key = public_key_from_b64(genesis.root_public_key)
        assert verify_model_signature(genesis, genesis.signatures[0], root_key)
        seen_na_keys.add(genesis.network_authority.public_key)
    assert len(seen_na_keys) == 3, "each NA must have a unique key"


def test_generate_with_explicit_names(tmp_path):
    """--name overrides --count and sets each sovereign's identity."""
    result = _generate(tmp_path, "--name", "alpha", "--name", "beta")
    assert result.exit_code == 0, result.output
    nodes = _load_fleet_manifest(str(tmp_path / "fleet" / "fleet.toml"))
    assert [n.name for n in nodes] == ["alpha", "beta"]
    assert all(n.operator_key_path.exists() for n in nodes)
    assert all(n.endpoint.startswith("http://") for n in nodes)


def test_generate_requires_count_or_names(tmp_path):
    """generate with neither --count nor --name fails clearly."""
    result = _generate(tmp_path)
    assert result.exit_code != 0
    assert "--count" in result.output or "--name" in result.output
    assert "Traceback" not in result.output


def test_generate_refuses_nonempty_dir_without_force(tmp_path):
    """generate will not clobber an existing non-empty fleet directory."""
    assert _generate(tmp_path, "--count", "1").exit_code == 0
    second = _generate(tmp_path, "--count", "1")
    assert second.exit_code != 0
    assert "not empty" in second.output
    assert "Traceback" not in second.output


def test_generate_rejects_duplicate_names(tmp_path):
    """Duplicate sovereign names are rejected before any files are written."""
    result = _generate(tmp_path, "--name", "dup", "--name", "dup")
    assert result.exit_code != 0
    assert "Duplicate" in result.output


def test_mesh_missing_manifest_errors():
    """fleet mesh against a missing manifest raises a clean Click error."""
    result = CliRunner().invoke(cli, ["fleet", "mesh", "--config", "does-not-exist.toml"])
    assert result.exit_code != 0
    assert "manifest not found" in result.output.lower()
    assert "Traceback" not in result.output
