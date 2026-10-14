"""Image tag selection and the vulnerability gate (scripts used by the image workflows, v1.1)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tags = _load("image_tags")
gate = _load("image_vuln_gate")


@pytest.mark.parametrize("version, released, expected", [
    ("1.1.0", ["v1.0.0", "v1.0.1"], ["1.1.0", "1.1", "latest"]),
    ("1.0.2", ["v1.0.1", "v1.1.0"], ["1.0.2", "1.0"]),            # a patch of an older line keeps latest
    ("1.0.1", ["v1.0.1", "v1.0.2", "v1.1.0"], ["1.0.1"]),         # a backfill moves nothing
    ("1.1.0", ["v1.1.0", "v1.2.0-rc1", "notes"], ["1.1.0", "1.1", "latest"]),  # pre-releases ignored
])
def test_floating_tags_never_move_backwards(version, released, expected):
    assert tags.tags_for(version, released) == expected


def test_a_non_stable_version_is_refused():
    with pytest.raises(ValueError):
        tags.tags_for("1.1.0-rc1", [])


def _report(*findings, secrets=()):
    results = {}
    for cls, severity, fixed in findings:
        results.setdefault(cls, []).append({"VulnerabilityID": "CVE-1", "PkgName": "p", "InstalledVersion": "1",
                                            "Severity": severity, "FixedVersion": fixed})
    out = [{"Target": cls, "Class": cls, "Vulnerabilities": v} for cls, v in results.items()]
    if not any(r["Class"] == "os-pkgs" for r in out):
        out.append({"Target": "alpine", "Class": "os-pkgs", "Vulnerabilities": []})
    if secrets:
        out.append({"Target": "/x", "Class": "secret", "Secrets": [{"RuleID": r} for r in secrets]})
    return {"Results": out}


def test_the_gate_passes_medium_and_low_findings():
    assert gate.evaluate(_report(("os-pkgs", "MEDIUM", ""), ("lang-pkgs", "LOW", "2"))) == []


@pytest.mark.parametrize("finding", [
    ("os-pkgs", "CRITICAL", ""),     # any critical
    ("os-pkgs", "HIGH", "1.2"),      # a fix exists: the image is stale
    ("os-pkgs", "HIGH", ""),         # no fix yet: still blocks (v1.1, Alpine base)
    ("lang-pkgs", "HIGH", ""),       # Python packages are ours to fix
])
def test_the_gate_blocks(finding):
    assert gate.evaluate(_report(finding))


def test_the_gate_blocks_secrets():
    assert gate.evaluate(_report(secrets=["private-key"]))


@pytest.mark.parametrize("report", [{}, {"Results": []}, {"Results": [{"Target": "x", "Class": "lang-pkgs"}]}])
def test_the_gate_refuses_a_report_without_os_packages(report):
    assert any(line.startswith("NO-SCAN") for line in gate.evaluate(report))


def test_the_edge_smoke_runs_the_agent_in_the_na_namespace_on_loopback():
    """The edge agent enrols over plain HTTP only to a loopback NA: the smoke shares the NA container's
    network namespace, read-only and without capabilities (v1.7.0)."""
    import sys

    # Its dataclasses resolve their annotations through sys.modules.
    spec = importlib.util.spec_from_file_location("container_smoke", SCRIPTS / "container_smoke.py")
    assert spec and spec.loader
    smoke = importlib.util.module_from_spec(spec)
    sys.modules["container_smoke"] = smoke
    try:
        spec.loader.exec_module(smoke)
    finally:
        sys.modules.pop("container_smoke", None)
    env = smoke.edge_env("root-key", "local-token")
    assert env["GM_EDGE_NA_URL"] == "http://127.0.0.1:8443" and "GM_EDGE_ALLOW_INSECURE_HTTP" not in env
    assert env["GM_EDGE_LISTEN"] == "tcp://127.0.0.1:7600" and "local-token" not in str(env)
    enrol = smoke.edge_run_args("gmt-x-na", "vol", env, "edge:1.7.0", "enroll")
    assert enrol[:2] == ["run", "--rm"] and enrol[-2:] == ["edge:1.7.0", "enroll"]
    assert enrol[enrol.index("--network") + 1] == "container:gmt-x-na"
    assert {"--read-only", "ALL", "no-new-privileges:true", "vol:/var/lib/genesis-mesh-edge"} <= set(enrol)
    run = smoke.edge_run_args("gmt-x-na", "vol", env, "edge:1.7.0", name="gmt-x-edge")
    assert run[:4] == ["run", "-d", "--name", "gmt-x-edge"] and run[-1] == "edge:1.7.0"
