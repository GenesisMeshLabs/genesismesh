"""Tests for the trust-cycle canary operator configuration helper."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "scripts"
    / "configure-trust-cycle-canary.py"
)
SPEC = importlib.util.spec_from_file_location("configure_trust_cycle_canary", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _assignment(path: Path, name: str) -> dict[str, str]:
    prefix = f"{name}="
    line = next(
        item for item in path.read_text(encoding="utf-8").splitlines()
        if item.startswith(prefix)
    )
    return json.loads(line[len(prefix):].strip().strip("'"))


def test_configure_operator_is_idempotent_and_preserves_existing_keys(tmp_path):
    """Repeated installation should reuse its key and retain other operators."""
    operator_env = tmp_path / "operator-keys.env"
    operator_env.write_text(
        "OPERATOR_PUBLIC_KEYS_JSON='{\"operator-local\":\"existing-public-key\"}'\n"
        "OPERATOR_KEY_TIERS_JSON='{\"operator-local\":\"privileged\"}'\n",
        encoding="utf-8",
    )
    state_dir = tmp_path / "canary"

    private_path, public_path = MODULE.configure_operator(
        operator_env=operator_env,
        state_dir=state_dir,
    )
    original_private = private_path.read_bytes()
    MODULE.configure_operator(operator_env=operator_env, state_dir=state_dir)

    public_keys = _assignment(operator_env, "OPERATOR_PUBLIC_KEYS_JSON")
    tiers = _assignment(operator_env, "OPERATOR_KEY_TIERS_JSON")
    assert public_keys["operator-local"] == "existing-public-key"
    assert public_keys["trust-cycle-canary"]
    assert tiers == {
        "operator-local": "privileged",
        "trust-cycle-canary": "privileged",
    }
    assert private_path.read_bytes() == original_private
    assert public_path.exists()


def test_configure_operator_rejects_incomplete_keypair(tmp_path):
    """A partial keypair should fail closed instead of silently rotating."""
    state_dir = tmp_path / "canary"
    state_dir.mkdir()
    (state_dir / "operator.key").write_text("incomplete", encoding="utf-8")

    with pytest.raises(ValueError, match="keypair is incomplete"):
        MODULE.configure_operator(
            operator_env=tmp_path / "operator-keys.env",
            state_dir=state_dir,
        )
