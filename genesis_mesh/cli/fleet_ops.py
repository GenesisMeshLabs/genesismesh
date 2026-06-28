"""Fleet operations for the Genesis Mesh CLI.

A *fleet* is a set of independent sovereign Network Authorities described by a
manifest (``fleet.toml``). These commands cover the production-grade,
deterministic, API-driven lifecycle:

* ``fleet generate`` — scaffold N sovereigns (keys + signed genesis + per-NA
  config) and a manifest, ready to run and federate.
* ``fleet mesh`` — issue recognition treaties across every ordered pair so the
  whole fleet trusts itself (idempotent).
* ``fleet verify`` — confirm trust-paths resolve across every ordered pair.
* ``fleet status`` — health (``healthz``/``readyz``) of each NA.

Single-host process orchestration (start/stop/tunnels) is intentionally *not*
here — production NAs run one-per-host under systemd/Kubernetes. For local
dev/demo orchestration see ``ops/scripts/fleet.py``.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import click
import requests

from ..crypto import generate_keypair, save_keypair, sign_model
from ..models import GenesisBlock, NetworkAuthority, PolicyManifestRef
from .config import config_path_value, save_config
from ..workflows.federation import (
    FederationBootstrapVerificationError,
    run_federation_bootstrap,
)
from .support import _request_json, _require_positive_int, _validate_cli_roles

DEFAULT_MESH_ROLES = ["role:anchor", "role:bridge", "role:operator", "role:client"]


@click.group()
def fleet() -> None:
    """Generate and federate a fleet of Network Authorities."""


# --------------------------------------------------------------------------- #
# Manifest model
# --------------------------------------------------------------------------- #


@dataclass
class FleetNode:
    """One sovereign in the fleet, resolved from its genesis-mesh.toml."""

    name: str
    endpoint: str
    config_path: Path
    operator_key_id: str
    operator_key_path: Path


def _resolve(base: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else (base / candidate)


def _load_fleet_manifest(manifest_path: str) -> list[FleetNode]:
    """Read a fleet manifest and resolve each member NA's public config."""
    path = Path(manifest_path)
    if not path.exists():
        raise click.ClickException(
            f"Fleet manifest not found: {path}. Run 'genesis-mesh fleet generate' first."
        )
    manifest = tomllib.loads(path.read_text(encoding="utf-8"))
    entries = manifest.get("fleet", {}).get("nodes", [])
    if not entries:
        raise click.ClickException(f"{path}: [fleet].nodes is empty.")

    nodes: list[FleetNode] = []
    for entry in entries:
        node_config = _resolve(path.parent, entry)
        if not node_config.exists():
            raise click.ClickException(f"Member config not found: {node_config}")
        data = tomllib.loads(node_config.read_text(encoding="utf-8"))
        network = data.get("network", {})
        na = data.get("na", {})
        paths = data.get("paths", {})
        operator = data.get("operator", {})

        endpoint = network.get("na_endpoint")
        if not endpoint:
            host = na.get("host", "127.0.0.1")
            port = na.get("port")
            if port is None:
                raise click.ClickException(f"{node_config}: missing [network].na_endpoint and [na].port")
            endpoint = f"http://{host}:{port}"
        op_key = paths.get("operator_private_key")
        nodes.append(
            FleetNode(
                name=network.get("name") or node_config.parent.name,
                endpoint=endpoint.rstrip("/"),
                config_path=node_config,
                operator_key_id=operator.get("key_id", "operator-local"),
                operator_key_path=_resolve(node_config.parent.parent, op_key) if op_key else Path(),
            )
        )
    return nodes


# --------------------------------------------------------------------------- #
# generate
# --------------------------------------------------------------------------- #


@fleet.command("generate")
@click.option("--output", default="fleet", help="Directory for the generated fleet.")
@click.option("--count", default=0, type=int, help="Number of NAs to generate (with --prefix).")
@click.option("--prefix", default="na", help="Name prefix when using --count (e.g. na -> na-1).")
@click.option("--name", "names", multiple=True, help="Explicit NA name. Repeatable; overrides --count.")
@click.option("--network-version", default="v0.1", help="Network version for each sovereign.")
@click.option("--host", default="127.0.0.1", help="Bind host recorded in each config.")
@click.option("--base-port", default=8443, type=int, help="Port of the first NA; incremented per NA.")
@click.option("--na-valid-days", default=90, type=int, help="NA key validity in days.")
@click.option("--force", is_flag=True, help="Overwrite an existing output directory.")
def fleet_generate(
    output: str,
    count: int,
    prefix: str,
    names: tuple[str, ...],
    network_version: str,
    host: str,
    base_port: int,
    na_valid_days: int,
    force: bool,
) -> None:
    """Scaffold a fleet of independent sovereigns plus a manifest."""
    resolved_names = list(names) if names else [f"{prefix}-{i}" for i in range(1, count + 1)]
    if not resolved_names:
        raise click.ClickException("Specify --count N (with --prefix) or one or more --name values.")
    if len(set(resolved_names)) != len(resolved_names):
        raise click.ClickException("Duplicate NA names are not allowed.")
    _require_positive_int("--base-port", base_port)
    _require_positive_int("--na-valid-days", na_valid_days)

    root = Path(output)
    if root.exists() and any(root.iterdir()) and not force:
        raise click.ClickException(f"{root} is not empty. Use --force to replace it.")
    root.mkdir(parents=True, exist_ok=True)

    manifest_nodes: list[str] = []
    for index, name in enumerate(resolved_names):
        port = base_port + index
        endpoint = f"http://{host}:{port}"
        home = root / name
        config_path = home / "genesis-mesh.toml"
        _scaffold_sovereign(
            home=home,
            name=name,
            network_version=network_version,
            endpoint=endpoint,
            host=host,
            port=port,
            na_valid_days=na_valid_days,
        )
        manifest_nodes.append(config_path.relative_to(root).as_posix())
        click.echo(f"  {name}: {endpoint} -> {home}")

    manifest_path = root / "fleet.toml"
    save_config({"fleet": {"host": host, "nodes": manifest_nodes}}, str(manifest_path))
    click.echo(
        "Note: each genesis block uses a placeholder policy hash. Replace "
        "PolicyManifestRef.hash with your policy document's SHA-256 before production use.",
        err=True,
    )
    click.echo(f"Generated {len(resolved_names)} NA(s). Manifest: {manifest_path}")
    click.echo("Next: start each NA (genesis-mesh na start --config <config>), then "
               "'genesis-mesh fleet mesh --config " + manifest_path.as_posix() + "'.")


def _scaffold_sovereign(
    *,
    home: Path,
    name: str,
    network_version: str,
    endpoint: str,
    host: str,
    port: int,
    na_valid_days: int,
) -> None:
    """Create keys, a signed genesis block, and a CLI config for one sovereign."""
    keys_dir = home / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    na_private_key_path = keys_dir / "na.key"
    operator_private_path = keys_dir / "operator.key"
    operator_public_path = keys_dir / "operator.pub"
    signed_genesis_path = home / "genesis.signed.json"
    database_path = home / "na.db"

    root_keypair = generate_keypair()
    na_keypair = generate_keypair()
    operator_keypair = generate_keypair()
    save_keypair(root_keypair, str(keys_dir / "root"), "rs-local")
    save_keypair(na_keypair, str(na_private_key_path.with_suffix("")), "na-local")
    save_keypair(operator_keypair, str(operator_private_path.with_suffix("")), "operator-local")

    now = datetime.now(timezone.utc)
    genesis_block = GenesisBlock(
        network_name=name,
        network_version=network_version,
        root_public_key=root_keypair.public_key_b64,
        network_authority=NetworkAuthority(
            public_key=na_keypair.public_key_b64,
            valid_from=now,
            valid_to=now + timedelta(days=na_valid_days),
        ),
        policy_manifest=PolicyManifestRef(hash="sha256:placeholder", url=None),
        bootstrap_anchors=[],
    )
    genesis_block.signatures.append(sign_model(genesis_block, root_keypair.private_key, "rs-local"))
    signed_genesis_path.write_text(
        json.dumps(genesis_block.model_dump(mode="json"), indent=2, default=str),
        encoding="utf-8",
    )

    config = {
        "network": {"name": name, "version": network_version, "na_endpoint": endpoint},
        "paths": {
            "home": config_path_value(home),
            "genesis": config_path_value(signed_genesis_path),
            "na_private_key": config_path_value(na_private_key_path),
            "operator_private_key": config_path_value(operator_private_path),
            "operator_public_key": config_path_value(operator_public_path),
            "db": config_path_value(database_path),
        },
        "na": {"key_id": "na-local", "host": host, "port": port},
        "operator": {"key_id": "operator-local"},
    }
    save_config(config, str(home / "genesis-mesh.toml"))


# --------------------------------------------------------------------------- #
# mesh
# --------------------------------------------------------------------------- #


@fleet.command("mesh")
@click.option("--config", "manifest_path", required=True, help="Fleet manifest path.")
@click.option("--role", "roles", multiple=True, help="Role accepted across the mesh. Repeatable.")
@click.option("--validity-hours", default=24 * 365, type=int, help="Treaty validity window.")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table")
def fleet_mesh(
    manifest_path: str,
    roles: tuple[str, ...],
    validity_hours: int,
    output_format: str,
) -> None:
    """Issue recognition treaties across every ordered pair (idempotent)."""
    _require_positive_int("--validity-hours", validity_hours)
    nodes = _load_fleet_manifest(manifest_path)
    accepted_roles = _validate_cli_roles(roles) if roles else list(DEFAULT_MESH_ROLES)
    session = requests.Session()

    sovereign_ids = {n.name: _sovereign_id(session, n.endpoint) for n in nodes}

    created: list[str] = []
    skipped: list[str] = []
    failures: list[dict[str, Any]] = []
    for acceptor in nodes:
        existing = _active_treaty_subjects(session, acceptor.endpoint)
        for issuer in nodes:
            if issuer.name == acceptor.name:
                continue
            pair = f"{acceptor.name}->{issuer.name}"
            if sovereign_ids[issuer.name] in existing:
                skipped.append(pair)
                continue
            try:
                run_federation_bootstrap(
                    acceptor_endpoint=acceptor.endpoint,
                    issuer_endpoint=issuer.endpoint,
                    acceptor_signer=(acceptor.operator_key_id, acceptor.operator_key_path),
                    roles=accepted_roles,
                    accepted_statuses=["active"],
                    claims={},
                    validity_hours=validity_hours,
                    issue_treaty=True,
                    confirmed=True,
                )
                created.append(pair)
            except FederationBootstrapVerificationError as exc:
                failures.append({"pair": pair, "error": exc.message})
            except click.ClickException as exc:
                failures.append({"pair": pair, "error": exc.format_message()})

    summary = {
        "nodes": len(nodes),
        "pairs": len(nodes) * (len(nodes) - 1),
        "created": len(created),
        "skipped": len(skipped),
        "failed": len(failures),
        "failures": failures,
    }
    if output_format == "json":
        click.echo(json.dumps(summary, indent=2, sort_keys=True))
    else:
        click.echo(f"Fleet mesh: {summary['nodes']} NAs, {summary['pairs']} pairs")
        click.echo(f"  created: {len(created)}  skipped: {len(skipped)}  failed: {len(failures)}")
        for failure in failures:
            click.echo(f"  FAIL {failure['pair']}: {failure['error']}")
    if failures:
        raise SystemExit(1)


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #


@fleet.command("verify")
@click.option("--config", "manifest_path", required=True, help="Fleet manifest path.")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table")
def fleet_verify(manifest_path: str, output_format: str) -> None:
    """Confirm a trust-path resolves across every ordered pair."""
    nodes = _load_fleet_manifest(manifest_path)
    session = requests.Session()
    sovereign_ids = {n.name: _sovereign_id(session, n.endpoint) for n in nodes}

    results: list[dict[str, Any]] = []
    untrusted = 0
    for source in nodes:
        for target in nodes:
            if source.name == target.name:
                continue
            query = urlencode({"from": sovereign_ids[source.name], "to": sovereign_ids[target.name]})
            try:
                path = _request_json(
                    session, "GET",
                    f"{source.endpoint}/connectome/trust-path?{query}",
                    label="trust path",
                )
                trusted = bool(path.get("trusted"))
                results.append({
                    "from": source.name, "to": target.name,
                    "trusted": trusted, "reason": path.get("reason"),
                    "hops": path.get("hop_count"),
                })
            except click.ClickException as exc:
                trusted = False
                results.append({"from": source.name, "to": target.name,
                                "trusted": False, "reason": exc.format_message(), "hops": None})
            if not trusted:
                untrusted += 1

    if output_format == "json":
        click.echo(json.dumps({"untrusted": untrusted, "pairs": results}, indent=2, sort_keys=True))
    else:
        for row in results:
            mark = "OK " if row["trusted"] else "ERR"
            click.echo(f"  {mark} {row['from']} -> {row['to']}: "
                       f"trusted={row['trusted']} reason={row['reason']} hops={row['hops']}")
        click.echo(f"{untrusted} untrusted pair(s).")
    if untrusted:
        raise SystemExit(1)


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #


@fleet.command("status")
@click.option("--config", "manifest_path", required=True, help="Fleet manifest path.")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table")
def fleet_status(manifest_path: str, output_format: str) -> None:
    """Show healthz/readyz for each NA in the fleet."""
    nodes = _load_fleet_manifest(manifest_path)
    session = requests.Session()
    rows: list[dict[str, Any]] = []
    for node in nodes:
        row: dict[str, Any] = {"name": node.name, "endpoint": node.endpoint}
        for probe in ("healthz", "readyz"):
            try:
                resp = session.get(f"{node.endpoint}/{probe}", timeout=5)
                row[probe] = resp.status_code if resp.ok else f"{resp.status_code}"
            except requests.RequestException as exc:
                row[probe] = f"down ({exc.__class__.__name__})"
        rows.append(row)

    if output_format == "json":
        click.echo(json.dumps(rows, indent=2, sort_keys=True))
        return
    click.echo(f"{'NAME':<18} {'HEALTHZ':<10} {'READYZ':<10} ENDPOINT")
    click.echo("-" * 64)
    for row in rows:
        click.echo(f"{row['name']:<18} {str(row['healthz']):<10} {str(row['readyz']):<10} {row['endpoint']}")


# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #


def _sovereign_id(session: requests.Session, endpoint: str) -> str:
    payload = _request_json(session, "GET", f"{endpoint}/sovereign.json", label="sovereign metadata")
    return payload["sovereign_id"]


def _active_treaty_subjects(session: requests.Session, endpoint: str) -> set[str]:
    """Return subject sovereign ids that already have an active treaty here."""
    payload = _request_json(session, "GET", f"{endpoint}/recognition-treaties", label="recognition treaties")
    subjects: set[str] = set()
    for row in payload.get("recognition_treaties", []):
        if row.get("status") == "active":
            subject = (row.get("treaty") or {}).get("subject_sovereign_id")
            if subject:
                subjects.add(subject)
    return subjects
