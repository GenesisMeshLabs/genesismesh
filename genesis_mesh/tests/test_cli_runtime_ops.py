"""Tests for CLI runtime and local development operations."""

from __future__ import annotations

import asyncio
from pathlib import Path

from click.testing import CliRunner

from genesis_mesh.cli.main import cli
from genesis_mesh.cli.ops import _run_runtime_forever


def test_na_start_reports_missing_config_without_traceback(tmp_path):
    """Missing config is reported as a Click error instead of a traceback."""
    missing_config = tmp_path / "missing.toml"

    result = CliRunner().invoke(
        cli,
        ["na", "start", "--config", str(missing_config)],
    )

    assert result.exit_code != 0
    assert "No Genesis Mesh config found" in result.output
    assert "Traceback" not in result.output

def test_status_reports_missing_config_without_traceback(tmp_path):
    """The status command reports a missing config without leaking a traceback."""
    missing_config = tmp_path / "missing.toml"

    result = CliRunner().invoke(cli, ["status", "--config", str(missing_config)])

    assert result.exit_code != 0
    assert "No Genesis Mesh config found" in result.output
    assert "Traceback" not in result.output

def test_dev_down_removes_runtime_artifacts(tmp_path):
    """The dev-down command removes generated local runtime artifacts."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path(".genesis-mesh").mkdir()
        Path(".genesis-mesh", "na.db").write_text("placeholder", encoding="utf-8")
        Path(".node2").mkdir()
        Path(".node2", "node.json").write_text("placeholder", encoding="utf-8")
        Path("genesis-mesh.toml").write_text("[network]\n", encoding="utf-8")

        result = runner.invoke(cli, ["dev", "down"])

        assert result.exit_code == 0, result.output
        assert "Removed .genesis-mesh" in result.output
        assert "Removed .node2" in result.output
        assert "Removed genesis-mesh.toml" in result.output
        assert not Path(".genesis-mesh").exists()
        assert not Path(".node2").exists()
        assert not Path("genesis-mesh.toml").exists()

def test_dev_down_reports_locked_runtime_artifacts(tmp_path, monkeypatch):
    """Locked runtime artifacts produce a clean remediation message."""
    runner = CliRunner()

    def locked_rmtree(path):
        raise PermissionError("file is locked")

    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path(".genesis-mesh").mkdir()
        monkeypatch.setattr("genesis_mesh.cli.dev_ops.shutil.rmtree", locked_rmtree)

        result = runner.invoke(cli, ["dev", "down"])

        assert result.exit_code != 0
        assert "Some generated files are locked" in result.output
        assert "Stop any running `genesis-mesh na start`" in result.output
        assert "Traceback" not in result.output

def test_runtime_forever_stops_runtime_when_cancelled():
    """Persistent CLI runtime loop stops subsystems when interrupted."""

    class Runtime:
        """Minimal runtime stub for cancellation behavior."""

        def __init__(self):
            self.started = False
            self.stopped = False

        async def start(self):
            self.started = True

        async def stop(self):
            self.stopped = True

    async def run_cancel():
        runtime = Runtime()
        task = asyncio.create_task(_run_runtime_forever(runtime))
        while not runtime.started:
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return runtime

    runtime = asyncio.run(run_cancel())

    assert runtime.started is True
    assert runtime.stopped is True
