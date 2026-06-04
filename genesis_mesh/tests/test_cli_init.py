"""Tests for CLI initialization commands."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from genesis_mesh.cli.config import load_config
from genesis_mesh.cli.main import cli
from genesis_mesh.models import GenesisBlock


def test_init_creates_config_and_local_artifacts(tmp_path):
    """The init command creates keys, genesis artifacts, and a project config."""
    config_path = tmp_path / "genesis-mesh.toml"
    home = tmp_path / ".genesis-mesh"

    result = CliRunner().invoke(
        cli,
        [
            "init",
            "--config",
            str(config_path),
            "--home",
            str(home),
            "--force",
        ],
    )

    assert result.exit_code == 0, result.output
    config = load_config(str(config_path), required=True)
    assert config["network"]["na_endpoint"] == "http://127.0.0.1:8443"
    genesis = GenesisBlock.model_validate_json(
        Path(config["paths"]["genesis"]).read_text(encoding="utf-8")
    )
    assert genesis.bootstrap_anchors == []
    assert Path(config["paths"]["genesis"]).exists()
    assert Path(config["paths"]["na_private_key"]).exists()
    assert Path(config["paths"]["operator_private_key"]).exists()

def test_init_accepts_explicit_operator_paths(tmp_path):
    """Operators can initialize a sovereign using production-style paths."""
    config_path = tmp_path / "config.toml"
    home = tmp_path / "home"
    genesis_path = tmp_path / "etc" / "genesis" / "genesis.signed.json"
    na_key_path = tmp_path / "etc" / "genesis-mesh" / "keys" / "na.key"
    operator_key_path = tmp_path / "etc" / "genesis-mesh" / "keys" / "operator.key"
    operator_pub_path = tmp_path / "etc" / "genesis-mesh" / "operator.pub"
    db_path = tmp_path / "var" / "lib" / "genesis-mesh" / "na.db"

    result = CliRunner().invoke(
        cli,
        [
            "init",
            "--config",
            str(config_path),
            "--home",
            str(home),
            "--network-name",
            "USG-NB",
            "--na-endpoint",
            "http://164.92.250.135:8443",
            "--genesis-file",
            str(genesis_path),
            "--na-private-key-file",
            str(na_key_path),
            "--operator-private-key-file",
            str(operator_key_path),
            "--operator-public-key-file",
            str(operator_pub_path),
            "--db-path",
            str(db_path),
            "--na-host",
            "0.0.0.0",
            "--na-port",
            "8443",
            "--force",
        ],
    )

    assert result.exit_code == 0, result.output
    config = load_config(str(config_path), required=True)
    assert config["network"]["name"] == "USG-NB"
    assert config["network"]["na_endpoint"] == "http://164.92.250.135:8443"
    assert config["paths"]["genesis"] == genesis_path.as_posix()
    assert config["paths"]["na_private_key"] == na_key_path.as_posix()
    assert config["paths"]["operator_private_key"] == operator_key_path.as_posix()
    assert config["paths"]["operator_public_key"] == operator_pub_path.as_posix()
    assert config["paths"]["db"] == db_path.as_posix()
    assert config["na"]["host"] == "0.0.0.0"
    assert config["na"]["port"] == 8443
    assert genesis_path.exists()
    assert na_key_path.exists()
    assert operator_key_path.exists()
    assert operator_pub_path.exists()

def test_init_requires_explicit_network_name_for_operator_paths(tmp_path):
    """Production-style paths should not silently reuse the default sovereign name."""
    result = CliRunner().invoke(
        cli,
        [
            "init",
            "--config",
            str(tmp_path / "config.toml"),
            "--home",
            str(tmp_path / "home"),
            "--genesis-file",
            str(tmp_path / "etc" / "genesis.signed.json"),
            "--force",
        ],
    )

    assert result.exit_code != 0
    assert "requires an explicit --network-name" in result.output
    assert "Traceback" not in result.output
