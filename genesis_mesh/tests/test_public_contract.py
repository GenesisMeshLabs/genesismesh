"""The v1 public contract (contract/public-surface.json) matches the code.

A route, CLI command, signed model or error code that exists but is not
classified fails here, as does a listed item that disappeared or a public
signature that changed. Changing the contract is deliberate: edit the
contract file, re-render the page, and record the change in the CHANGELOG
(DEPRECATION_POLICY.md says which changes need a deprecation cycle).
"""

from __future__ import annotations

import json

import pytest

from genesis_mesh.tests.public_contract_support import (
    CONTRACT,
    CONTRACT_PAGE,
    cli_commands,
    error_codes,
    http_routes,
    render_contract_page,
    resolve,
    signature_of,
    signed_models,
)

LEVELS = {"stable", "beta", "internal"}


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _diff(code: set, listed: set) -> str:
    return f"unclassified: {sorted(code - listed)}; listed but gone: {sorted(listed - code)}"


def test_every_http_route_is_classified_with_its_methods(contract):
    code = {path: methods for path, methods in http_routes()}
    listed = {r["path"]: r["methods"] for r in contract["http_routes"]}
    assert set(code) == set(listed), _diff(set(code), set(listed))
    changed = {p: (listed[p], code[p]) for p in code if code[p] != listed[p]}
    assert not changed, f"methods changed (contract, code): {changed}"


def test_every_cli_command_is_classified(contract):
    code = set(cli_commands())
    listed = {c["command"] for c in contract["cli_commands"]}
    assert code == listed, _diff(code, listed)


def test_every_signed_model_is_classified(contract):
    code = {(f"{m}:{n}", f) for m, n, f in signed_models()}
    listed = {(a["model"], a["signature_field"]) for a in contract["signed_artifacts"]}
    assert code == listed, _diff(code, listed)


def test_every_error_code_is_listed(contract):
    code = error_codes()
    listed = set(contract["error_codes"])
    assert code == listed, _diff(code, listed)


@pytest.mark.parametrize("section", ["http_routes", "cli_commands", "python", "signed_artifacts"])
def test_levels_are_valid(contract, section):
    bad = [item for item in contract[section] if item["level"] not in LEVELS]
    assert not bad, bad


def test_python_symbols_exist_with_their_listed_signatures(contract):
    problems = []
    for entry in contract["python"]:
        try:
            obj = resolve(entry["symbol"])
        except (ImportError, AttributeError) as exc:
            problems.append(f"{entry['symbol']}: {exc}")
            continue
        if signature_of(obj) != entry.get("parameters"):
            problems.append(f"{entry['symbol']}: listed {entry.get('parameters')} actual {signature_of(obj)}")
    assert not problems, "\n".join(problems)


def test_stable_artifacts_and_routes_are_not_internal_details(contract):
    """Admin routes the operator console uses are not hidden as internal."""
    internal_admin = [r["path"] for r in contract["http_routes"] if r["level"] == "internal" and r["path"].startswith("/admin/")]
    assert not internal_admin


def test_rendered_contract_page_is_current(contract):
    expected = render_contract_page(contract)
    actual = CONTRACT_PAGE.read_text(encoding="utf-8") if CONTRACT_PAGE.exists() else ""
    assert actual == expected, "docs/reference/public-contract.md is stale: run python scripts/render_public_contract.py"
