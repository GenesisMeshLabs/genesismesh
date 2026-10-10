"""Introspection of the public surfaces recorded in contract/public-surface.json.

Shared by test_public_contract.py and scripts/render_public_contract.py: each
function returns what the code actually exposes, so the contract can be
compared with it.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
import tempfile
import typing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import click
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contract" / "public-surface.json"
CONTRACT_PAGE = ROOT / "docs" / "reference" / "public-contract.md"

_CODE_LITERAL = re.compile(r"""\bcode\s*=\s*["']([a-z0-9_]+)["']""")


def http_routes() -> list[tuple[str, list[str]]]:
    """Every route the Network Authority registers, with its methods (evidence store on)."""
    from genesis_mesh.crypto import generate_keypair, sign_model
    from genesis_mesh.models import GenesisBlock, NetworkAuthority, PolicyManifestRef
    from genesis_mesh.na_service.server import NetworkAuthorityService

    root = generate_keypair()
    now = datetime.now(timezone.utc)
    genesis = GenesisBlock(
        network_name="contract", network_version="v1", root_public_key=root.public_key_b64,
        network_authority=NetworkAuthority(
            public_key=root.public_key_b64, valid_from=now, valid_to=now + timedelta(days=1)
        ),
        policy_manifest=PolicyManifestRef(hash="sha256:contract", url=None),
    )
    genesis.signatures.append(sign_model(genesis, root.private_key, "root"))
    with tempfile.TemporaryDirectory(prefix="gm-contract-") as tmp:
        service = NetworkAuthorityService(
            genesis_block=genesis, na_private_key=root.private_key, key_id="contract",
            db_path=str(Path(tmp) / "na.db"), evidence_store="on",
        )
        routes: dict[str, set[str]] = {}
        for rule in service.app.url_map.iter_rules():
            if rule.endpoint == "static":
                continue
            methods = {m for m in rule.methods or () if m not in ("HEAD", "OPTIONS")}
            routes.setdefault(rule.rule, set()).update(methods)
        service.db.close()
    return [(path, sorted(methods)) for path, methods in sorted(routes.items())]


def cli_commands() -> list[str]:
    """Every leaf command reachable from `genesis-mesh`."""
    from genesis_mesh.cli.main import cli

    def walk(cmd: click.Command, prefix: list[str]) -> list[str]:
        if isinstance(cmd, click.Group):
            return [c for name, sub in sorted(cmd.commands.items()) for c in walk(sub, [*prefix, name])]
        return [" ".join(prefix)]

    return walk(cli, [])


def signed_models() -> list[tuple[str, str, str]]:
    """(module, class, signature field) for every signed model in genesis_mesh.models."""
    import genesis_mesh.models as models

    found: list[tuple[str, str, str]] = []
    for info in pkgutil.iter_modules(models.__path__):
        module = importlib.import_module(f"genesis_mesh.models.{info.name}")
        for name, obj in sorted(vars(module).items()):
            if not (inspect.isclass(obj) and issubclass(obj, BaseModel) and obj.__module__ == module.__name__):
                continue
            for field in ("signature", "signatures"):
                if field in obj.model_fields:
                    found.append((module.__name__, name, field))
                    break
    return sorted(found)


def error_codes() -> set[str]:
    """Every error code the Network Authority can put in its error envelope.

    Literal ``code=`` arguments and default codes in genesis_mesh/na_service,
    plus the revocation-feed reasons the feed import returns as codes and the
    refusal codes of submitted records (``EvidenceRejectionCode``,
    ``OutOfBandRejectionCode``). Codes
    derived from a plain HTTP status (``not_found``, ``method_not_allowed``)
    are covered by the contract's rule for them, not listed here.
    """
    from genesis_mesh.na_service import errors
    from genesis_mesh.trust.evidence_store import EvidenceRejectionCode
    from genesis_mesh.trust.out_of_band import OutOfBandRejectionCode
    from genesis_mesh.trust.treaty import RevocationFeedReason

    codes: set[str] = set()
    for path in (ROOT / "genesis_mesh" / "na_service").rglob("*.py"):
        codes.update(_CODE_LITERAL.findall(path.read_text(encoding="utf-8")))
    for obj in vars(errors).values():
        if inspect.isclass(obj) and issubclass(obj, errors.ApiError):
            codes.add(obj.default_code)
    codes.update(r for r in typing.get_args(RevocationFeedReason) if r != "accepted")
    # Refusals of submitted records, raised with the reason as the code (listed
    # since 1.3.0; the evidence codes were missing before).
    codes.update(typing.get_args(EvidenceRejectionCode))
    codes.update(typing.get_args(OutOfBandRejectionCode))
    return codes


def signature_of(obj: Any) -> list[dict[str, Any]] | None:
    """Parameters of a public function (or a non-model class constructor): name, kind, required."""
    if inspect.isclass(obj):
        if issubclass(obj, BaseModel):
            return None
        target = obj.__init__
    elif callable(obj):
        target = obj
    else:
        return None
    params = []
    for p in inspect.signature(target).parameters.values():
        if p.name == "self":
            continue
        params.append({"name": p.name, "kind": p.kind.name.lower(), "required": p.default is inspect.Parameter.empty
                       and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)})
    return params


def resolve(symbol: str) -> Any:
    """Import `module:name`."""
    module, _, name = symbol.partition(":")
    return getattr(importlib.import_module(module), name)


LEVEL_TEXT = {
    "stable": "Will not break within 1.x. Removed or changed incompatibly only after the deprecation cycle in `DEPRECATION_POLICY.md`.",
    "beta": "Shipped and supported; may change in a minor version with a CHANGELOG notice.",
    "internal": "No compatibility promise. Operator UI pages and implementation details.",
}


def render_contract_page(contract: dict[str, Any]) -> str:
    """Render docs/reference/public-contract.md from the contract file."""
    out: list[str] = []
    w = out.append
    w("# Public Contract")
    w("")
    w("<!-- Generated from contract/public-surface.json by scripts/render_public_contract.py. Do not edit. -->")
    w("")
    w("This page is the v1 public contract of Genesis Mesh: every HTTP route of the")
    w("Network Authority, every CLI command, the public Python API, every signed")
    w("artifact and every API error code, each classified as stable, beta or")
    w("internal. The source of truth is `contract/public-surface.json`;")
    w("`genesis_mesh/tests/test_public_contract.py` fails when the code exposes")
    w("anything the contract does not classify, or when a listed item changes or")
    w("disappears. Compatibility rules are in `DEPRECATION_POLICY.md`.")
    w("")
    w("| Level | Meaning |")
    w("| --- | --- |")
    for level, text in LEVEL_TEXT.items():
        w(f"| **{level}** | {text} |")
    w("")
    w("## Packages")
    w("")
    w("| Package | Level | Support |")
    w("| --- | --- | --- |")
    for p in contract["packages"]:
        w(f"| {p['package']} (`{p['repository']}`) | {p['level']} | {p['support']} |")
    w("")
    w("## HTTP routes")
    w("")
    w("| Method | Path | Level |")
    w("| --- | --- | --- |")
    for r in contract["http_routes"]:
        w(f"| {', '.join(r['methods'])} | `{r['path']}` | {r['level']} |")
    w("")
    w("## Error codes")
    w("")
    w(contract["rules"]["error_envelope"])
    w(contract["rules"]["http_status_codes"])
    w("Every code below is stable: it is never removed or given a new meaning.")
    w("")
    w(", ".join(f"`{c}`" for c in contract["error_codes"]))
    w("")
    w("## Signed artifacts")
    w("")
    w("Each is signed over its canonical form without the signature field (see")
    w("RFC-001, *Canonical JSON and signatures*, and `DEPRECATION_POLICY.md` for how")
    w("signed formats evolve).")
    w("")
    w("| Model | Signature field | Level |")
    w("| --- | --- | --- |")
    for a in contract["signed_artifacts"]:
        w(f"| `{a['model']}` | `{a['signature_field']}` | {a['level']} |")
    w("")
    w("## CLI commands")
    w("")
    w("| Command | Level |")
    w("| --- | --- |")
    for c in contract["cli_commands"]:
        w(f"| `genesis-mesh {c['command']}` | {c['level']} |")
    w("")
    w("## Python API")
    w("")
    w("Symbols not listed are internal. Parameters are listed in order;")
    w("`*` marks keyword-only parameters and `?` optional ones.")
    w("")
    w("| Symbol | Parameters | Level |")
    w("| --- | --- | --- |")
    for s in contract["python"]:
        params = s.get("parameters")
        if params is None:
            shown = "model"
        else:
            shown = ", ".join(
                ("*" if p["kind"] == "keyword_only" else "") + p["name"] + ("" if p["required"] else "?")
                for p in params
            ) or "(none)"
        w(f"| `{s['symbol']}` | {shown} | {s['level']} |")
    w("")
    return "\n".join(out)
