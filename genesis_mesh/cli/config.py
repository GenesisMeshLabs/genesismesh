"""Configuration discovery and persistence for the Genesis Mesh CLI."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any


PROJECT_CONFIG = "genesis-mesh.toml"


def default_user_config_path() -> Path:
    """Return the default per-user CLI config path."""
    return Path.home() / ".genesis-mesh" / "config.toml"


def resolve_config_path(config_path: str | None = None) -> Path:
    """Resolve an explicit, project, environment, or user config path."""
    if config_path:
        return Path(config_path)

    env_path = os.environ.get("GENESIS_MESH_CONFIG")
    if env_path:
        return Path(env_path)

    project_path = Path(PROJECT_CONFIG)
    if project_path.exists():
        return project_path

    return default_user_config_path()


def load_config(config_path: str | None = None, required: bool = False) -> dict[str, Any]:
    """Load a Genesis Mesh CLI config file."""
    path = resolve_config_path(config_path)
    if not path.exists():
        if required:
            raise FileNotFoundError(
                f"No Genesis Mesh config found at {path}. Run 'genesis-mesh init' first."
            )
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def save_config(config: dict[str, Any], config_path: str | None = None) -> Path:
    """Persist a Genesis Mesh CLI config file."""
    path = resolve_config_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_to_toml(config), encoding="utf-8")
    return path


def get_config_value(
    config: dict[str, Any],
    section: str,
    key: str,
    default: Any = None,
) -> Any:
    """Return a value from a nested CLI config section."""
    return config.get(section, {}).get(key, default)


def set_config_value(config: dict[str, Any], section: str, key: str, value: Any) -> None:
    """Set a value in a nested CLI config section."""
    config.setdefault(section, {})[key] = value


def config_path_value(path: str | Path) -> str:
    """Return a stable path string for persisted CLI config files."""
    return Path(path).as_posix()


def _to_toml(config: dict[str, Any]) -> str:
    """Serialize the small CLI config subset to TOML."""
    lines: list[str] = []
    for section, values in config.items():
        if not isinstance(values, dict):
            continue
        lines.append(f"[{section}]")
        for key, value in values.items():
            lines.append(f"{key} = {_format_value(value)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _format_value(value: Any) -> str:
    """Format a primitive TOML value."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_value(item) for item in value) + "]"
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
