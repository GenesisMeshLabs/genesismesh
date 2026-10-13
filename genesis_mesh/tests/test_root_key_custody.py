"""Root key custody (v1.5.0, Stage 4).

The root key signs the genesis block and every NA key succession; whoever
holds it and the NA key can replace the NA's key history. ``init`` still
writes one for local use, and warns. ``NA_DEPLOYMENT=managed`` refuses to
start an NA whose host holds it, and ``na doctor`` reports it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from genesis_mesh.cli.env_file import read_env_file
from genesis_mesh.cli.main import cli
from genesis_mesh.na_service.app_factory import build_app
from genesis_mesh.na_service.settings import load_settings


@pytest.fixture
def initialized(tmp_path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["init", "--home", "home", "--network-name", "custody",
                                      "--env-file", "na.env"])
    assert result.exit_code == 0, result.output
    assert "root private key was written to" in result.output and "next to the NA key" in result.output
    return tmp_path


def _settings(directory: Path, **overrides: str):
    values = read_env_file(directory / "na.env")
    values.update(overrides)
    # Paths in the file are relative to it.
    for name in ("GENESIS_FILE", "NA_PRIVATE_KEY_FILE", "DB_PATH"):
        values[name] = str((directory / values[name]).resolve())
    return load_settings(values)


def test_a_managed_na_refuses_to_start_with_the_root_key_on_its_host(initialized):
    root_key = initialized / "home" / "keys" / "root.key"
    assert root_key.is_file()
    with pytest.raises(ValueError, match="root private key is in"):
        build_app(_settings(initialized, NA_DEPLOYMENT="managed"))
    # A local deployment starts, as before 1.5.0.
    assert build_app(_settings(initialized))
    root_key.unlink()
    assert build_app(_settings(initialized, NA_DEPLOYMENT="managed"))


def test_the_deployment_setting_is_checked():
    with pytest.raises(ValueError, match="NA_DEPLOYMENT"):
        load_settings({"GENESIS_FILE": "g.json", "NA_DEPLOYMENT": "cloud"})


def test_na_doctor_reports_the_root_key_and_the_na_key(initialized):
    env = initialized / "na.env"
    found = CliRunner().invoke(cli, ["na", "doctor", "--env-file", str(env), "--format", "json"])
    assert found.exit_code == 1, found.output
    checks = {c["check"]: c for c in json.loads(found.output)["checks"]}
    assert checks["root_key_absent"]["status"] == "fail" and "root.key" in checks["root_key_absent"]["detail"]
    assert checks["na_key"]["status"] == "ok" and "not enforced" in checks["na_key"]["detail"]
    assert checks["retention_archive"]["status"] == "ok"
    (initialized / "home" / "keys" / "root.key").unlink()
    clean = CliRunner().invoke(cli, ["na", "doctor", "--env-file", str(env)])
    assert clean.exit_code == 0, clean.output
    assert "WARN  deployment" in clean.output
