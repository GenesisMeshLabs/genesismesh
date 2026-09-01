"""Provision the dedicated operator credential used by the trust-cycle canary."""

from __future__ import annotations

import argparse
import base64
import json
import os
import tempfile
from pathlib import Path

from genesis_mesh.crypto import generate_keypair, load_public_key, save_keypair

DEFAULT_KEY_ID = "trust-cycle-canary"


def _json_assignment(lines: list[str], name: str) -> dict[str, str]:
    """Read one compact JSON systemd environment assignment."""
    prefix = f"{name}="
    matches = [line for line in lines if line.startswith(prefix)]
    if not matches:
        return {}
    raw = matches[-1][len(prefix):].strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        raw = raw[1:-1]
    value = json.loads(raw)
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in value.items()
    ):
        raise ValueError(f"{name} must be a JSON object with string values")
    return value


def _replace_assignment(lines: list[str], name: str, value: dict[str, str]) -> list[str]:
    """Replace one environment assignment while preserving unrelated lines."""
    prefix = f"{name}="
    rendered = f"{name}='{json.dumps(value, sort_keys=True, separators=(',', ':'))}'"
    updated = [line for line in lines if not line.startswith(prefix)]
    updated.append(rendered)
    return updated


def configure_operator(
    *,
    operator_env: Path,
    state_dir: Path,
    key_id: str = DEFAULT_KEY_ID,
    owner_uid: int | None = None,
    owner_gid: int | None = None,
) -> tuple[Path, Path]:
    """Create or reuse a canary key and register its public half."""
    state_dir.mkdir(parents=True, exist_ok=True)
    state_dir.chmod(0o700)
    key_base = state_dir / "operator"
    private_path = key_base.with_suffix(".key")
    public_path = key_base.with_suffix(".pub")

    if private_path.exists() != public_path.exists():
        raise ValueError("Canary operator keypair is incomplete; refusing to rotate it")
    if not private_path.exists():
        private_path, public_path = save_keypair(
            generate_keypair(),
            str(key_base),
            key_id,
        )

    private_path.chmod(0o600)
    public_path.chmod(0o644)
    if owner_uid is not None and owner_gid is not None:
        os.chown(state_dir, owner_uid, owner_gid)
        os.chown(private_path, owner_uid, owner_gid)
        os.chown(public_path, owner_uid, owner_gid)

    public_key = base64.b64encode(bytes(load_public_key(str(public_path)))).decode("utf-8")
    lines = operator_env.read_text(encoding="utf-8").splitlines() if operator_env.exists() else []
    public_keys = _json_assignment(lines, "OPERATOR_PUBLIC_KEYS_JSON")
    tiers = _json_assignment(lines, "OPERATOR_KEY_TIERS_JSON")
    public_keys[key_id] = public_key
    tiers[key_id] = "privileged"
    lines = _replace_assignment(lines, "OPERATOR_PUBLIC_KEYS_JSON", public_keys)
    lines = _replace_assignment(lines, "OPERATOR_KEY_TIERS_JSON", tiers)

    operator_env.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=operator_env.parent,
        delete=False,
    ) as handle:
        handle.write("\n".join(lines) + "\n")
        temp_path = Path(handle.name)
    temp_path.chmod(0o600)
    os.replace(temp_path, operator_env)
    operator_env.chmod(0o600)
    return private_path, public_path


def main() -> int:
    """Configure the live canary credential without printing key material."""
    import pwd

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--operator-env",
        type=Path,
        default=Path("/etc/genesis-mesh/operator-keys.env"),
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("/var/lib/genesis-mesh/trust-cycle-canary"),
    )
    parser.add_argument("--owner", default="azureuser")
    parser.add_argument("--key-id", default=DEFAULT_KEY_ID)
    args = parser.parse_args()

    owner = pwd.getpwnam(args.owner)
    configure_operator(
        operator_env=args.operator_env,
        state_dir=args.state_dir,
        key_id=args.key_id,
        owner_uid=owner.pw_uid,
        owner_gid=owner.pw_gid,
    )
    print(f"Configured operator credential {args.key_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
