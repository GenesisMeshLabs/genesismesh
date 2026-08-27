"""Regression tests for F-22: the systemd units must carry OS-level sandboxing.

Covers every unit the project ships or generates:

* the three canonical files in ``infrastructure/systemd/``
* the two units ``infrastructure/scripts/bootstrap-ubuntu-vm.sh`` writes inline
* the preprod NA unit in ``examples/preprod/install-miraos-na.reference.sh``

The generated ones are *rendered with bash*, using the scripts' own variable
defaults, so the test checks what actually lands in ``/etc/systemd/system`` and
not a regex approximation of it.

The important assertions are the ones that tie a unit's ``ReadWritePaths=`` back
to the paths the Python code writes to. ``ProtectSystem=strict`` mounts the
filesystem read-only, so a path the code writes but the unit does not allow-list
either stops the service from starting or silently disables the feature. If a
later change moves the NA database or the audit log without updating the units,
these tests fail instead of production doing so.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from genesis_mesh.audit import logger as audit_logger_module
from genesis_mesh.audit.logger import default_audit_log_path

# Bound at import time, before conftest's autouse _audit_logs_to_tmp fixture
# redirects the module attribute at each test. This is the value that ships,
# and the one the units have to allow-list.
REAL_AUDIT_DIR = audit_logger_module.DEFAULT_AUDIT_DIR

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_DIR = REPO_ROOT / "infrastructure" / "systemd"
BOOTSTRAP_SH = REPO_ROOT / "infrastructure" / "scripts" / "bootstrap-ubuntu-vm.sh"
PREPROD_SH = REPO_ROOT / "examples" / "preprod" / "install-miraos-na.reference.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None,
    reason="requires bash to render the script-generated units",
)

# Directives every unit must carry, with the exact value expected.
REQUIRED_DIRECTIVES = {
    "NoNewPrivileges": "true",
    "PrivateTmp": "true",
    "PrivateDevices": "true",
    "ProtectSystem": "strict",
    "ProtectKernelTunables": "true",
    "ProtectKernelModules": "true",
    "ProtectKernelLogs": "true",
    "ProtectControlGroups": "true",
    "ProtectClock": "true",
    "ProtectHostname": "true",
    "ProtectProc": "invisible",
    "RestrictSUIDSGID": "true",
    "RestrictRealtime": "true",
    "RestrictNamespaces": "true",
    "LockPersonality": "true",
    "SystemCallArchitectures": "native",
    "SystemCallFilter": "@system-service",
    "UMask": "0077",
    # Empty values: drop every capability rather than bounding a subset.
    "CapabilityBoundingSet": "",
    "AmbientCapabilities": "",
}

REQUIRED_ADDRESS_FAMILIES = {"AF_UNIX", "AF_INET", "AF_INET6", "AF_NETLINK"}


# --------------------------------------------------------------------------
# unit parsing / rendering
# --------------------------------------------------------------------------


def _service_section(unit_text: str) -> dict[str, list[str]]:
    """Return the [Service] section of a unit as {directive: [values]}."""
    section: dict[str, list[str]] = {}
    in_service = False
    for raw in unit_text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_service = line == "[Service]"
            continue
        if not in_service or not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        section.setdefault(key.strip(), []).append(value.strip())
    return section


def _one(section: dict[str, list[str]], key: str) -> str:
    """Return the single value of a directive, failing if it is absent."""
    values = section.get(key)
    assert values, f"missing {key}="
    assert len(values) == 1, f"{key} set {len(values)} times: {values}"
    return values[0]


def _leading_variable_block(script: Path) -> str:
    """Return a script's assignments up to its first function definition."""
    lines = script.read_text().splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\(\)\s*\{", line):
            return "\n".join(lines[:index])
    return "\n".join(lines)


def _service_heredocs(script: Path) -> list[str]:
    """Return the bodies of every heredoc that writes a .service unit."""
    bodies: list[str] = []
    lines = script.read_text().splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith("cat >") and ".service" in stripped and stripped.endswith("<<EOF"):
            index += 1
            body: list[str] = []
            while index < len(lines) and lines[index].strip() != "EOF":
                body.append(lines[index])
                index += 1
            bodies.append("\n".join(body))
        index += 1
    return bodies


def _render(body: str, setup: str) -> str:
    """Expand a heredoc body through bash exactly as the script would."""
    result = subprocess.run(
        ["bash", "-c", f"{setup}\ncat <<EOF\n{body}\nEOF\n"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"rendering failed: {result.stderr}"
    return result.stdout


def _canonical(name: str) -> dict[str, list[str]]:
    return _service_section((SYSTEMD_DIR / name).read_text())


def _bootstrap_units() -> dict[str, dict[str, list[str]]]:
    """Render the NA and both router units bootstrap-ubuntu-vm.sh writes."""
    base = _leading_variable_block(BOOTSTRAP_SH)
    na_body, router_body = _service_heredocs(BOOTSTRAP_SH)

    units = {"bootstrap:na": _service_section(_render(na_body, base))}
    for label, config_var, port_var in (
        ("bootstrap:node", "ROUTER_B_CONFIG", "ROUTER_B_PORT"),
        ("bootstrap:node-d", "ROUTER_D_CONFIG", "ROUTER_D_PORT"),
    ):
        setup = f'{base}\nname="{label}"\nconfig="${config_var}"\nport="${port_var}"'
        units[label] = _service_section(_render(router_body, setup))
    return units


def _preprod_unit() -> dict[str, list[str]]:
    base = _leading_variable_block(PREPROD_SH)
    (body,) = _service_heredocs(PREPROD_SH)
    return _service_section(_render(body, base))


NA_UNITS = {
    "genesis-mesh-na.service": lambda: _canonical("genesis-mesh-na.service"),
    "bootstrap:na": lambda: _bootstrap_units()["bootstrap:na"],
    "preprod:miraos-na": _preprod_unit,
}

ROUTER_UNITS = {
    "genesis-mesh-node.service": lambda: _canonical("genesis-mesh-node.service"),
    "genesis-mesh-node-d.service": lambda: _canonical("genesis-mesh-node-d.service"),
    "bootstrap:node": lambda: _bootstrap_units()["bootstrap:node"],
    "bootstrap:node-d": lambda: _bootstrap_units()["bootstrap:node-d"],
}

ALL_UNITS = {**NA_UNITS, **ROUTER_UNITS}


# --------------------------------------------------------------------------
# every unit
# --------------------------------------------------------------------------


@pytest.mark.parametrize("label", sorted(ALL_UNITS))
def test_unit_carries_the_hardening_stanza(label):
    """F-22: every shipped or generated unit sets the full sandboxing set."""
    section = ALL_UNITS[label]()
    for directive, expected in REQUIRED_DIRECTIVES.items():
        assert _one(section, directive) == expected, f"{label}: {directive}"


@pytest.mark.parametrize("label", sorted(ALL_UNITS))
def test_unit_restricts_address_families(label):
    """Only the socket families the services actually need are reachable."""
    families = set(_one(ALL_UNITS[label](), "RestrictAddressFamilies").split())
    # AF_NETLINK stays: glibc getaddrinfo() enumerates interfaces through it.
    assert families == REQUIRED_ADDRESS_FAMILIES, label


@pytest.mark.parametrize("label", sorted(ALL_UNITS))
def test_unit_does_not_set_memory_deny_write_execute(label):
    """Deliberately excluded: PyNaCl goes through cffi, whose closures need W|X."""
    assert "MemoryDenyWriteExecute" not in ALL_UNITS[label]()


@pytest.mark.parametrize("label", sorted(ALL_UNITS))
def test_unit_declares_read_write_paths(label):
    """ProtectSystem=strict is only safe with an explicit writable allow-list."""
    paths = _one(ALL_UNITS[label](), "ReadWritePaths").split()
    assert paths, f"{label}: ProtectSystem=strict with no ReadWritePaths"
    for path in paths:
        # A "-" prefix would let the unit start with the path missing, silently
        # dropping whatever the service meant to write there.
        assert not path.startswith("-"), f"{label}: {path} is optional"
        assert path.startswith("/"), f"{label}: {path} is not absolute"


# --------------------------------------------------------------------------
# NA units: the database must be writable
# --------------------------------------------------------------------------


@pytest.mark.parametrize("label", sorted(NA_UNITS))
def test_na_unit_allows_writing_its_own_database(label):
    """The directory holding DB_PATH (and its -wal/-journal/-shm) is writable."""
    section = NA_UNITS[label]()
    db_path = next(
        value.split("=", 1)[1]
        for value in section["Environment"]
        if value.startswith("DB_PATH=")
    )
    db_dir = _parent_dir(db_path)
    paths = _one(section, "ReadWritePaths").split()
    assert any(_covers(allowed, db_dir) for allowed in paths), (
        f"{label}: ReadWritePaths {paths} does not cover {db_dir}"
    )


@pytest.mark.parametrize("label", sorted(NA_UNITS))
def test_na_unit_hides_home_entirely(label):
    """The NA writes nothing under $HOME, so it gets the strongest setting."""
    assert _one(NA_UNITS[label](), "ProtectHome") == "true"


# --------------------------------------------------------------------------
# router units: config home + audit log must be writable
# --------------------------------------------------------------------------


@pytest.mark.parametrize("label", sorted(ROUTER_UNITS))
def test_router_unit_allows_writing_its_config_home(label):
    """cli/ops.py rewrites config.toml, the cert and the policy on every start."""
    section = ROUTER_UNITS[label]()
    exec_start = _one(section, "ExecStart").split()
    config = exec_start[exec_start.index("--config") + 1]
    config_home = _parent_dir(config)
    paths = _one(section, "ReadWritePaths").split()
    assert any(_covers(allowed, config_home) for allowed in paths), (
        f"{label}: ReadWritePaths {paths} does not cover {config_home}"
    )


@pytest.mark.parametrize("label", sorted(ROUTER_UNITS))
def test_router_unit_allows_writing_the_audit_log(label):
    """F-03's audit log lives under $HOME; the sandbox must not silence it.

    The expected directory is derived from DEFAULT_AUDIT_DIR in the code, so
    moving the audit log without updating the units fails here rather than in
    production, where AuditLogger would log "AUDIT DISABLED" and carry on.
    """
    section = ROUTER_UNITS[label]()
    user = _one(section, "User")
    audit_dir = _audit_dir_for_user(user)
    paths = _one(section, "ReadWritePaths").split()
    assert any(_covers(allowed, audit_dir) for allowed in paths), (
        f"{label}: ReadWritePaths {paths} does not cover {audit_dir}"
    )


@pytest.mark.parametrize("label", sorted(ROUTER_UNITS))
def test_router_unit_keeps_home_reachable(label):
    """ProtectHome=true/tmpfs replaces $HOME; ReadWritePaths cannot re-enter it."""
    assert _one(ROUTER_UNITS[label](), "ProtectHome") == "read-only"


def test_audit_log_path_still_derives_from_the_constant(monkeypatch, tmp_path):
    """Pins the two links the router assertions above depend on.

    The node runtime must resolve its audit log through
    ``default_audit_log_path``, and that helper must resolve through
    ``DEFAULT_AUDIT_DIR`` — otherwise the units could allow-list a directory
    nothing writes to while the real one stays read-only.
    """
    from genesis_mesh.node import runtime

    sentinel = tmp_path / "sentinel-audit"
    monkeypatch.setattr(audit_logger_module, "DEFAULT_AUDIT_DIR", sentinel)
    assert default_audit_log_path("node-key").parent == sentinel
    assert runtime.default_audit_log_path is default_audit_log_path


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _parent_dir(path: str) -> str:
    """Return the parent directory of an absolute POSIX path, as a string."""
    parent = path.rsplit("/", 1)[0]
    return parent or "/"


def _covers(allowed: str, target: str) -> bool:
    """Return whether an allow-listed path is `target` or one of its parents."""
    allowed = allowed.rstrip("/") or "/"
    target = target.rstrip("/") or "/"
    return target == allowed or target.startswith(f"{allowed}/")


def _audit_dir_for_user(user: str) -> str:
    """Map the shipped DEFAULT_AUDIT_DIR onto the home directory of a unit's User=."""
    try:
        relative = REAL_AUDIT_DIR.relative_to(Path.home())
    except ValueError:
        # Not under $HOME any more — the units must list the literal path.
        return str(REAL_AUDIT_DIR)
    return f"/home/{user}/{relative.as_posix()}"
