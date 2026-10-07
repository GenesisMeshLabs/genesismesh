"""Network Authority settings files for ``na start --env-file`` (v1.2.0).

A settings file holds the same variables the production NA reads from its
environment (``na_service.settings``), one ``KEY=VALUE`` per line, close to
``docker run --env-file``: ``#`` starts a comment line, values are taken
literally (no quotes, no ``export``, no ``${VAR}``) and a name set twice is
refused. ``init --env-file`` writes one and ``keygen operator --env-file``
registers keys in it.

Relative paths in the file resolve against the file's directory, so a
project can keep its NA in one folder and start it from anywhere.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from ..na_service.auth import OPERATOR_TIERS

#: Settings whose values are file paths, resolved against the file's directory.
PATH_SETTINGS = ("GENESIS_FILE", "NA_PRIVATE_KEY_FILE", "DB_PATH")

OPERATOR_KEYS_SETTING = "OPERATOR_PUBLIC_KEYS_JSON"
OPERATOR_TIERS_SETTING = "OPERATOR_KEY_TIERS_JSON"

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class EnvFileError(ValueError):
    """A settings file that cannot be read as KEY=VALUE lines."""


def _is_comment_or_blank(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _split(line: str, number: int, path: Path) -> tuple[str, str]:
    if "=" not in line:
        raise EnvFileError(f"{path}:{number}: expected KEY=VALUE")
    name, value = line.split("=", 1)
    name = name.strip()
    if not _NAME.fullmatch(name):
        raise EnvFileError(f"{path}:{number}: invalid setting name {name!r}")
    return name, value.strip()


def read_env_file(path: Path) -> dict[str, str]:
    """Return the settings in ``path``, with relative path settings resolved.

    Raises EnvFileError for a line that is not ``KEY=VALUE`` or a setting
    that appears twice (which value wins would otherwise depend on the
    reader). An empty value counts as unset: ``DB_PATH=`` would otherwise
    give SQLite a temporary database that is lost when the NA stops.
    """
    values: dict[str, str] = {}
    text = path.read_text(encoding="utf-8-sig")
    for number, line in enumerate(text.splitlines(), start=1):
        if _is_comment_or_blank(line):
            continue
        name, value = _split(line, number, path)
        if name in values:
            raise EnvFileError(f"{path}:{number}: {name} is set twice")
        values[name] = value
    values = {name: value for name, value in values.items() if value}
    base = path.resolve().parent
    for name in PATH_SETTINGS:
        path_value = values.get(name)
        # ":memory:" is SQLite's in-memory database, not a file.
        if path_value and path_value != ":memory:" and not Path(path_value).is_absolute():
            values[name] = str(base / path_value)
    return values


def relative_to_file(target: Path, env_path: Path) -> str:
    """Return ``target`` as written in a settings file at ``env_path``.

    Relative to the file's directory where possible (the folder stays
    movable), absolute otherwise (another drive on Windows).
    """
    try:
        value = os.path.relpath(target.resolve(), env_path.resolve().parent)
    except ValueError:
        return target.resolve().as_posix()
    return Path(value).as_posix()


def _compact_json(value: dict[str, str]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def write_new_env_file(
    path: Path, header: list[str], settings: list[tuple[str, str]], *, overwrite: bool = False
) -> None:
    """Write a settings file (owner-only on POSIX); an existing one only with ``overwrite``."""
    lines = [f"# {line}" if line else "#" for line in header]
    lines += [f"{name}={value}" for name, value in settings]
    _write(path, "\n".join(lines) + "\n", exclusive=not overwrite)


def operator_settings(keys: dict[str, str], tiers: dict[str, str]) -> list[tuple[str, str]]:
    """The two operator settings, as written in a settings file."""
    return [(OPERATOR_KEYS_SETTING, _compact_json(keys)), (OPERATOR_TIERS_SETTING, _compact_json(tiers))]


def registered_operator_keys(path: Path) -> dict[str, str]:
    """Return the operator key IDs and public keys registered in ``path``."""
    _, _, current = _operator_lines(path)
    return dict(current[OPERATOR_KEYS_SETTING])


def register_operator_key(
    path: Path, key_id: str, public_key: str, tier: str, *, replace: bool = False
) -> None:
    """Add or update one operator key and its tier in an existing settings file.

    Every other line is kept as it was. A key ID already registered with a
    different public key is refused unless ``replace`` is set, so a typo in
    ``--key-id`` cannot silently take over another operator's entry.
    """
    if tier not in OPERATOR_TIERS:
        raise EnvFileError(f"operator tier must be one of {', '.join(OPERATOR_TIERS)}")
    lines, found, current = _operator_lines(path)
    keys = current[OPERATOR_KEYS_SETTING]
    existing = keys.get(key_id)
    if existing and existing != public_key and not replace:
        raise EnvFileError(
            f"{path}: operator key {key_id!r} is already registered with another public key; "
            "use --replace to replace it"
        )
    keys[key_id] = public_key
    current[OPERATOR_TIERS_SETTING][key_id] = tier

    for name in (OPERATOR_KEYS_SETTING, OPERATOR_TIERS_SETTING):
        rendered = f"{name}={_compact_json(current[name])}"
        if name in found:
            lines[found[name]] = rendered
        else:
            lines.append(rendered)
    _write(path, "\n".join(lines) + "\n", exclusive=False)


def _operator_lines(path: Path) -> tuple[list[str], dict[str, int], dict[str, dict[str, str]]]:
    """The file's lines, where the operator settings are, and their values."""
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    found: dict[str, int] = {}
    current: dict[str, dict[str, str]] = {OPERATOR_KEYS_SETTING: {}, OPERATOR_TIERS_SETTING: {}}
    for index, line in enumerate(lines):
        if _is_comment_or_blank(line):
            continue
        name, value = _split(line, index + 1, path)
        if name not in current:
            continue
        if name in found:
            raise EnvFileError(f"{path}:{index + 1}: {name} is set twice")
        found[name] = index
        try:
            parsed = json.loads(value) if value else {}
        except json.JSONDecodeError as exc:
            raise EnvFileError(f"{path}:{index + 1}: {name} is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise EnvFileError(f"{path}:{index + 1}: {name} must be a JSON object")
        current[name] = {str(k): str(v) for k, v in parsed.items()}
    return lines, found, current


def _write(path: Path, content: str, *, exclusive: bool) -> None:
    """Write ``content``; ``exclusive`` refuses an existing file.

    An update goes through a new temporary file in the same directory and
    ``os.replace``, so an interrupted write never leaves half a settings file
    and the temporary name cannot be a planted link.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        return
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
