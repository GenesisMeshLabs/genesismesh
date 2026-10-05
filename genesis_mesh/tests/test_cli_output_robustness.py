"""CLI output robustness (v1.0.2): UTF-8 on any stream, no traceback for a
missing output directory or an unreachable endpoint."""

from __future__ import annotations

import io
import subprocess
import sys

from click.testing import CliRunner

from genesis_mesh.cli.main import _utf8_output, cli


def test_output_into_a_new_directory_is_created(tmp_path):
    key = tmp_path / "keys" / "a"
    result = CliRunner().invoke(cli, ["keygen", "node", "--output", str(key), "--key-id", "a"])
    assert result.exit_code == 0, result.output
    out = tmp_path / "signals" / "deep" / "b.json"
    result = CliRunner().invoke(cli, ["trust", "risk", "create", "--from-sovereign", "a", "--to-sovereign", "b",
                                      "--signing-key", str(key) + ".key", "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()


def test_help_with_non_ascii_text_survives_a_legacy_code_page(monkeypatch):
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    _utf8_output()
    print("\u2264 Zo\u00eb \U0001F600")  # would raise UnicodeEncodeError under cp1252
    sys.stdout.flush()
    assert sys.stdout.encoding.lower().replace("-", "") == "utf8"


def test_unreachable_endpoint_is_a_clean_error():
    proc = subprocess.run(
        [sys.executable, "-c", "from genesis_mesh.cli.main import main; main()", "sovereign", "inspect",
         "--na", "http://127.0.0.1:9"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "Error" in proc.stderr
