"""Persona-oriented operational commands for the Genesis Mesh CLI."""

from __future__ import annotations

import asyncio
import base64
import sqlite3
import json
import runpy
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import click
from click.core import ParameterSource
import requests

from .supply_chain import supply_chain
from ..crypto import (
    KeyPair,
    generate_keypair,
    load_private_key,
    save_keypair,
    sign_data,
    sign_model,
)
from ..models import BootstrapAnchor, GenesisBlock, JoinCertificate, PolicyManifest
from ..models import NetworkAuthority, PolicyManifestRef
from ..na_service.auth import load_operator_public_keys
from ..na_service.server import create_app
from ..node.node import MeshNode
from ..node.runtime import MeshNodeRuntime
from .config import (
    PROJECT_CONFIG,
    config_path_value,
    get_config_value,
    load_config,
    resolve_config_path,
    save_config,
    set_config_value,
)


def register_operational_commands(cli: click.Group) -> None:
    """Register persona-oriented operational commands on the root CLI."""
    cli.add_command(init)
    cli.add_command(na)
    cli.add_command(admin)
    cli.add_command(join)
    cli.add_command(send)
    cli.add_command(status)
    cli.add_command(dev)
    cli.add_command(discover)
    cli.add_command(sovereign)
    cli.add_command(proof)
    cli.add_command(supply_chain)


def _load_cli_config(config_path: str | None = None, required: bool = False) -> dict[str, Any]:
    """Load CLI config and translate missing-file errors into Click errors."""
    try:
        return load_config(config_path, required=required)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc


@click.command()
@click.option("--config", "config_path", default=PROJECT_CONFIG, help="Config path to write.")
@click.option("--home", default=".genesis-mesh", help="Directory for generated artifacts.")
@click.option("--network-name", default="USG", help="Network name.")
@click.option("--network-version", default="v0.1", help="Network version.")
@click.option("--na-endpoint", default="http://127.0.0.1:8443", help="Network Authority URL.")
@click.option("--genesis-file", default=None, help="Signed genesis output path.")
@click.option("--na-private-key-file", default=None, help="Network Authority private key output path.")
@click.option("--operator-private-key-file", default=None, help="Operator private key output path.")
@click.option("--operator-public-key-file", default=None, help="Operator public key output path.")
@click.option("--db-path", default=None, help="Network Authority SQLite DB path to store in config.")
@click.option("--na-host", default="127.0.0.1", help="Network Authority bind host to store in config.")
@click.option("--na-port", default=8443, type=int, help="Network Authority bind port to store in config.")
@click.option(
    "--anchor",
    default="",
    help="Optional peer bootstrap anchor id:endpoint. Do not use the NA HTTP endpoint.",
)
@click.option("--force", is_flag=True, help="Overwrite existing config and artifacts.")
@click.pass_context
def init(
    ctx: click.Context,
    config_path: str,
    home: str,
    network_name: str,
    network_version: str,
    na_endpoint: str,
    genesis_file: str | None,
    na_private_key_file: str | None,
    operator_private_key_file: str | None,
    operator_public_key_file: str | None,
    db_path: str | None,
    na_host: str,
    na_port: int,
    anchor: str,
    force: bool,
) -> None:
    """Create local keys, a signed genesis block, and CLI config."""
    root = Path(home)
    keys_dir = root / "keys"
    genesis_path = root / "genesis.json"
    signed_genesis_path = Path(genesis_file) if genesis_file else root / "genesis.signed.json"
    na_private_key_path = Path(na_private_key_file) if na_private_key_file else keys_dir / "na.key"
    operator_private_path = (
        Path(operator_private_key_file) if operator_private_key_file else keys_dir / "operator.key"
    )
    operator_public_path = (
        Path(operator_public_key_file) if operator_public_key_file else keys_dir / "operator.pub"
    )
    database_path = Path(db_path) if db_path else root / "na.db"
    target_config = Path(config_path)
    explicit_operator_paths = any(
        value is not None
        for value in (
            genesis_file,
            na_private_key_file,
            operator_private_key_file,
            operator_public_key_file,
            db_path,
        )
    )
    if (
        explicit_operator_paths
        and network_name == "USG"
        and ctx.get_parameter_source("network_name") != ParameterSource.COMMANDLINE
    ):
        raise click.ClickException(
            "Production-style sovereign initialization requires an explicit "
            "--network-name. Refusing to reuse the default 'USG'."
        )

    if target_config.exists() and not force:
        raise click.ClickException(f"{target_config} already exists. Use --force to replace it.")
    if root.exists() and any(root.iterdir()) and not force:
        raise click.ClickException(f"{root} is not empty. Use --force to replace it.")

    if force and root.exists():
        shutil.rmtree(root)
    keys_dir.mkdir(parents=True, exist_ok=True)
    signed_genesis_path.parent.mkdir(parents=True, exist_ok=True)
    na_private_key_path.parent.mkdir(parents=True, exist_ok=True)
    operator_private_path.parent.mkdir(parents=True, exist_ok=True)
    operator_public_path.parent.mkdir(parents=True, exist_ok=True)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    root_keypair = generate_keypair()
    na_keypair = generate_keypair()
    operator_keypair = generate_keypair()
    save_keypair(root_keypair, str(keys_dir / "root"), "rs-local")
    save_keypair(na_keypair, str(na_private_key_path.with_suffix("")), "na-local")
    save_keypair(operator_keypair, str(operator_private_path.with_suffix("")), "operator-local")
    if operator_public_path != operator_private_path.with_suffix(".pub"):
        operator_public_path.write_text(
            f"# key-id: operator-local\n{operator_keypair.public_key_b64}\n",
            encoding="utf-8",
        )

    bootstrap_anchors: list[BootstrapAnchor] = []
    if anchor:
        anchor_id, anchor_endpoint = _parse_anchor(anchor)
        bootstrap_anchors.append(BootstrapAnchor(id=anchor_id, endpoint=anchor_endpoint))
    now = datetime.now(timezone.utc)
    genesis_block = GenesisBlock(
        network_name=network_name,
        network_version=network_version,
        root_public_key=root_keypair.public_key_b64,
        network_authority=NetworkAuthority(
            public_key=na_keypair.public_key_b64,
            valid_from=now,
            valid_to=now + timedelta(days=90),
        ),
        policy_manifest=PolicyManifestRef(hash="sha256:placeholder", url=None),
        bootstrap_anchors=bootstrap_anchors,
    )
    genesis_path.write_text(
        json.dumps(genesis_block.model_dump(mode="json"), indent=2, default=str),
        encoding="utf-8",
    )
    genesis_block.signatures.append(sign_model(genesis_block, root_keypair.private_key, "rs-local"))
    signed_genesis_path.write_text(
        json.dumps(genesis_block.model_dump(mode="json"), indent=2, default=str),
        encoding="utf-8",
    )
    click.echo(
        "Note: genesis block contains a placeholder policy hash. "
        "Replace PolicyManifestRef.hash with the SHA-256 of your policy document before production use.",
        err=True,
    )

    config = {
        "network": {
            "name": network_name,
            "version": network_version,
            "na_endpoint": na_endpoint.rstrip("/"),
        },
        "paths": {
            "home": config_path_value(root),
            "genesis": config_path_value(signed_genesis_path),
            "na_private_key": config_path_value(na_private_key_path),
            "operator_private_key": config_path_value(operator_private_path),
            "operator_public_key": config_path_value(operator_public_path),
            "node_private_key": config_path_value(keys_dir / "node.key"),
            "node_certificate": config_path_value(root / "node.cert.json"),
            "policy": config_path_value(root / "policy.json"),
            "db": config_path_value(database_path),
        },
        "na": {"key_id": "na-local", "host": na_host, "port": na_port},
        "operator": {"key_id": "operator-local"},
    }
    written_config = save_config(config, config_path)

    click.echo(f"Initialized Genesis Mesh config: {written_config}")
    click.echo(f"Genesis block: {signed_genesis_path}")
    click.echo(f"Operator key: {keys_dir / 'operator.key'}")


@click.group()
def na() -> None:
    """Run Network Authority operations."""


@na.command("start")
@click.option("--config", "config_path", default=None, help="Config path.")
@click.option("--host", default=None, help="Bind host.")
@click.option("--port", default=None, type=int, help="Bind port.")
@click.option("--db-path", default=None, help="SQLite database path.")
def na_start(config_path: str | None, host: str | None, port: int | None, db_path: str | None) -> None:
    """Start a local Network Authority server from config."""
    config = _load_cli_config(config_path, required=True)
    genesis_path = _required_config_path(config, "paths", "genesis")
    na_private_key_path = _required_config_path(config, "paths", "na_private_key")
    operator_public_key_path = _required_config_path(config, "paths", "operator_public_key")
    key_id = get_config_value(config, "na", "key_id", "na-local")
    bind_host = host or get_config_value(config, "na", "host", "127.0.0.1")
    bind_port = port or int(get_config_value(config, "na", "port", 8443))
    database_path = db_path or get_config_value(
        config,
        "paths",
        "db",
        str(Path(get_config_value(config, "paths", "home", ".")) / "na.db"),
    )
    operator_key_id = get_config_value(config, "operator", "key_id", "operator-local")

    genesis_block = _load_genesis(genesis_path)
    app = create_app(
        genesis_block=genesis_block,
        na_private_key=load_private_key(str(na_private_key_path)),
        key_id=key_id,
        db_path=database_path,
        operator_public_keys=load_operator_public_keys([f"{operator_key_id}={operator_public_key_path}"]),
    )
    click.echo(f"Starting Network Authority on http://{bind_host}:{bind_port}")
    click.echo(
        "WARNING: Starting Flask development server. "
        "For production deployments use start.sh and Gunicorn.",
        err=True,
    )
    app.run(host=bind_host, port=bind_port)


@click.group()
def admin() -> None:
    """Run operator admin actions against the Network Authority."""


@admin.command("invite")
@click.option("--config", "config_path", default=None, help="Config path.")
@click.option("--na", "na_endpoint", default=None, help="Network Authority URL.")
@click.option("--role", "roles", multiple=True, default=["client"], help="Role to assign.")
@click.option("--validity-hours", default=168, type=int, help="Maximum certificate validity.")
@click.option("--token-expiry-hours", default=24, type=int, help="Invite validity.")
def admin_invite(
    config_path: str | None,
    na_endpoint: str | None,
    roles: tuple[str, ...],
    validity_hours: int,
    token_expiry_hours: int,
) -> None:
    """Create a single-use invite token and print it."""
    config = _load_cli_config(config_path, required=True)
    endpoint = (na_endpoint or get_config_value(config, "network", "na_endpoint")).rstrip("/")
    body: dict[str, Any] = {
        "roles": [_normalize_role(role) for role in roles],
        "max_validity_hours": validity_hours,
        "token_expiry_hours": token_expiry_hours,
    }
    response = requests.post(
        f"{endpoint}/admin/invite",
        json=body,
        headers=_admin_headers(config, body),
        timeout=10,
    )
    response.raise_for_status()
    click.echo(response.json()["token_id"])


@admin.command("revoke")
@click.argument("cert_id")
@click.option("--config", "config_path", default=None, help="Config path.")
@click.option("--na", "na_endpoint", default=None, help="Network Authority URL.")
@click.option("--reason", default="unspecified", help="Revocation reason.")
def admin_revoke(config_path: str | None, na_endpoint: str | None, cert_id: str, reason: str) -> None:
    """Revoke a certificate by ID."""
    config = _load_cli_config(config_path, required=True)
    endpoint = (na_endpoint or get_config_value(config, "network", "na_endpoint")).rstrip("/")
    body = {"cert_id": cert_id, "reason": reason}
    response = requests.post(
        f"{endpoint}/admin/revoke",
        json=body,
        headers=_admin_headers(config, body),
        timeout=10,
    )
    response.raise_for_status()
    click.echo(json.dumps(response.json(), indent=2))


@click.command()
@click.option("--config", "config_path", default=None, help="Config path.")
@click.option("--na", "na_endpoint", required=True, help="Network Authority URL.")
@click.option("--token", default=None, help="Invite token. Required only for first enrollment.")
@click.option("--role", "roles", multiple=True, default=["client"], help="Requested local role.")
@click.option("--validity-hours", default=168, type=int, help="Requested certificate validity.")
@click.option("--persistent", is_flag=True, help="Start the peer runtime after enrollment.")
@click.option("--listen-host", default="0.0.0.0", help="Peer runtime bind host.")
@click.option("--listen-port", default=0, type=int, help="Peer runtime bind port.")
@click.option("--peer", "peers", multiple=True, help="Bootstrap peer endpoint (host:port or ws://host:port). Repeatable.")
def join(
    config_path: str | None,
    na_endpoint: str,
    token: str | None,
    roles: tuple[str, ...],
    validity_hours: int,
    persistent: bool,
    listen_host: str,
    listen_port: int,
    peers: tuple[str, ...],
) -> None:
    """Enroll this machine as a node and persist node config."""
    config = _load_cli_config(config_path, required=False)
    endpoint = na_endpoint.rstrip("/")
    config_target = resolve_config_path(config_path)
    home = Path(get_config_value(config, "paths", "home", config_target.parent))
    keys_dir = home / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)

    genesis_path = Path(get_config_value(config, "paths", "genesis", home / "genesis.signed.json"))
    if not genesis_path.exists():
        response = requests.get(f"{endpoint}/genesis", timeout=10)
        response.raise_for_status()
        genesis_path.parent.mkdir(parents=True, exist_ok=True)
        genesis_path.write_text(json.dumps(response.json(), indent=2), encoding="utf-8")

    node_key_path = Path(get_config_value(config, "paths", "node_private_key", keys_dir / "node.key"))
    if node_key_path.exists():
        private_key = load_private_key(str(node_key_path))
        node_keypair = KeyPair(private_key=private_key, public_key=private_key.verify_key)
    else:
        node_keypair = generate_keypair()
        save_keypair(node_keypair, str(node_key_path.with_suffix("")), "node-local")

    genesis_block = _load_genesis(genesis_path)
    cert_path = Path(get_config_value(config, "paths", "node_certificate", home / "node.cert.json"))
    policy_path = Path(get_config_value(config, "paths", "policy", home / "policy.json"))

    node = MeshNode(
        genesis_block=genesis_block,
        node_keypair=node_keypair,
        roles=[_normalize_role(role) for role in roles],
    )

    reused_existing_cert = False
    cert = _load_existing_certificate(cert_path, node)
    if cert is not None:
        reused_existing_cert = True
        node.join_certificate = cert
        node.roles = cert.roles
        policy = _load_existing_policy(policy_path, node) or node.fetch_policy(endpoint)
        click.echo(f"Using existing certificate: {cert.cert_id}")
    else:
        if not token:
            cert_error = _describe_unusable_certificate(cert_path, node)
            if cert_error:
                raise click.ClickException(f"{cert_error} Run with --token to re-enroll.")
            raise click.ClickException("No local certificate found. Run with --token for first enrollment.")
        cert = node.join_network(endpoint, validity_hours=validity_hours, invite_token=token)
        policy = node.fetch_policy(endpoint)

    if not node.send_heartbeat(endpoint):
        if reused_existing_cert:
            raise click.ClickException(
                "Existing local certificate was rejected by the Network Authority. "
                "Run with --token to re-enroll if this node is still authorized."
            )
        click.echo(
            "Warning: heartbeat failed; Network Authority node status may not update.",
            err=True,
        )

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_text(cert.model_dump_json(indent=2), encoding="utf-8")
    policy_path.write_text(policy.model_dump_json(indent=2), encoding="utf-8")

    set_config_value(config, "network", "name", genesis_block.network_name)
    set_config_value(config, "network", "version", genesis_block.network_version)
    set_config_value(config, "network", "na_endpoint", endpoint)
    set_config_value(config, "paths", "home", config_path_value(home))
    set_config_value(config, "paths", "genesis", config_path_value(genesis_path))
    set_config_value(config, "paths", "node_private_key", config_path_value(node_key_path))
    set_config_value(config, "paths", "node_certificate", config_path_value(cert_path))
    set_config_value(config, "paths", "policy", config_path_value(policy_path))
    save_config(config, config_path)

    click.echo(f"Joined {genesis_block.network_name} as {', '.join(cert.roles)}")
    click.echo(f"Certificate: {cert.cert_id}")
    click.echo(f"Config: {resolve_config_path(config_path)}")

    if persistent:
        runtime = MeshNodeRuntime(node, endpoint, listen_host=listen_host, listen_port=listen_port, bootstrap_peers=list(peers))
        click.echo("Starting persistent peer runtime. Press Ctrl+C to stop.")
        try:
            asyncio.run(_run_runtime_forever(runtime))
        except KeyboardInterrupt:
            click.echo("Runtime stopped")


@click.command()
@click.option("--to", "target_key", required=True, help="Recipient node public key.")
@click.option("--via", "peer_endpoint", required=True, help="Peer WebSocket endpoint (ws://host:port).")
@click.option("--message", "message", required=True, help="Message text to send.")
@click.option("--config", "config_path", default=None, help="Config path.")
def send(
    target_key: str,
    peer_endpoint: str,
    message: str,
    config_path: str | None,
) -> None:
    """Send a message to a node through a peer WebSocket connection."""
    import base64

    from ..crypto import KeyPair
    from ..transport import connect_websocket_with_noise
    from ..transport.noise_handshake import NoiseHandshake
    from ..transport.protocol import create_data_message

    config = _load_cli_config(config_path, required=True)
    genesis_path = _required_config_path(config, "paths", "genesis")
    node_key_path = _required_config_path(config, "paths", "node_private_key")
    cert_path = _required_config_path(config, "paths", "node_certificate")

    private_key = load_private_key(str(node_key_path))
    node_keypair = KeyPair(private_key=private_key, public_key=private_key.verify_key)
    cert = JoinCertificate.model_validate_json(cert_path.read_text(encoding="utf-8"))
    local_cert_b64 = base64.b64encode(cert.model_dump_json().encode()).decode()
    noise_keypair = NoiseHandshake.keypair_from_join_cert_key(private_key)
    uri = peer_endpoint if peer_endpoint.startswith("ws") else f"ws://{peer_endpoint}"

    async def _send() -> None:
        transport, _, _ = await connect_websocket_with_noise(uri, noise_keypair, local_cert_b64)
        msg = create_data_message(
            sender_id=node_keypair.public_key_b64,
            recipient_id=target_key,
            data=message.encode(),
        )
        await transport.send(msg.to_bytes())
        click.echo(f"Sent: {message!r}")
        click.echo(f"  to:  {target_key[:24]}...")
        click.echo(f"  via: {uri}")
        await transport.close()

    asyncio.run(_send())


@click.command()
@click.option("--config", "config_path", default=None, help="Config path.")
def status(config_path: str | None) -> None:
    """Show Network Authority and node status from config."""
    config = _load_cli_config(config_path, required=True)
    endpoint = get_config_value(config, "network", "na_endpoint")
    if endpoint:
        click.echo(f"Network Authority: {endpoint}")
        for probe in ("healthz", "readyz"):
            try:
                response = requests.get(f"{endpoint.rstrip('/')}/{probe}", timeout=5)
                click.echo(f"  /{probe}: {response.status_code} {response.text.strip()}")
            except requests.RequestException as exc:
                click.echo(f"  /{probe}: unavailable ({exc})")
        try:
            nodes = requests.get(f"{endpoint.rstrip('/')}/nodes", timeout=5)
            if nodes.ok:
                payload = nodes.json()
                click.echo(f"  active nodes: {payload.get('count', 0)}")
        except requests.RequestException:
            pass

    cert_path = get_config_value(config, "paths", "node_certificate")
    if cert_path and Path(cert_path).exists():
        cert = JoinCertificate.model_validate_json(Path(cert_path).read_text(encoding="utf-8"))
        click.echo("Node:")
        click.echo(f"  certificate: {cert.cert_id}")
        click.echo(f"  roles: {', '.join(cert.roles)}")
        click.echo(f"  expires: {cert.expires_at.isoformat()}")
        click.echo(f"  valid: {cert.is_valid()}")


@click.command()
@click.option("--config", "config_path", default=None, help="Config path.")
@click.option("--na", "na_endpoint", default=None, help="Network Authority URL (overrides config).")
@click.option("--capability", default=None, help="Filter to agents advertising this capability.")
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]), default="table",
    help="Output format.",
)
def discover(
    config_path: str | None,
    na_endpoint: str | None,
    capability: str | None,
    output_format: str,
) -> None:
    """Discover registered agents on the Network Authority by capability."""
    config = _load_cli_config(config_path, required=False)
    endpoint = na_endpoint or get_config_value(config, "network", "na_endpoint")
    if not endpoint:
        raise click.ClickException(
            "No NA endpoint. Pass --na or run `genesis-mesh init` to create a config."
        )

    url = f"{endpoint.rstrip('/')}/agents"
    params = {"capability": capability} if capability else {}
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise click.ClickException(f"Discovery query failed: {exc}") from exc

    payload = response.json()
    agents = payload.get("agents", [])

    if output_format == "json":
        click.echo(json.dumps(payload, indent=2))
        return

    if not agents:
        click.echo("No matching agents." if capability else "No registered agents.")
        return

    click.echo(f"{len(agents)} agent(s) matching capability={capability or '<any>'}:")
    for entry in agents:
        endpoint_info = entry.get("endpoint", {})
        click.echo("")
        click.echo(f"  agent_id     : {entry.get('agent_id')}")
        click.echo(f"  node_key     : {entry.get('node_public_key')}")
        click.echo(f"  capabilities : {', '.join(entry.get('capabilities', []))}")
        click.echo(
            f"  endpoint     : {endpoint_info.get('scheme', 'ws')}://"
            f"{endpoint_info.get('host')}:{endpoint_info.get('port')}"
        )
        click.echo(f"  expires_at   : {entry.get('expires_at')}")
        if entry.get("metadata"):
            click.echo(f"  metadata     : {entry.get('metadata')}")


@click.group()
def sovereign() -> None:
    """Inspect public sovereign metadata."""


@sovereign.command("inspect")
@click.option("--na", "na_endpoint", required=True, help="Network Authority URL.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
def sovereign_inspect(na_endpoint: str, output_format: str) -> None:
    """Fetch operator-safe public trust material for a sovereign."""
    endpoint = na_endpoint.rstrip("/")
    try:
        response = requests.get(f"{endpoint}/sovereign.json", timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise click.ClickException(f"Sovereign metadata query failed: {exc}") from exc

    payload = response.json()
    if output_format == "json":
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    na = payload.get("network_authority", {})
    surfaces = payload.get("supported_surfaces", {})
    click.echo(f"Sovereign: {payload.get('sovereign_id')}")
    click.echo(f"  network_version: {payload.get('network_version')}")
    click.echo(f"  endpoint:        {payload.get('endpoint')}")
    click.echo(f"  na_public_key:   {str(na.get('public_key', ''))[:32]}...")
    click.echo(f"  valid_to:        {na.get('valid_to')}")
    click.echo("  public surfaces:")
    for name, url in surfaces.items():
        click.echo(f"    {name}: {url}")


@click.group()
def proof() -> None:
    """Run and clean sovereign proof workflows."""


@proof.command("cleanup")
@click.option("--db-path", required=True, help="Network Authority SQLite database path.")
@click.option("--backup-path", default=None, help="Explicit backup destination path.")
@click.option("--backup-dir", default=None, help="Directory for timestamped DB backup.")
@click.option("--yes", is_flag=True, help="Confirm cleanup without an interactive prompt.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
def proof_cleanup(
    db_path: str,
    backup_path: str | None,
    backup_dir: str | None,
    yes: bool,
    output_format: str,
) -> None:
    """Remove only proof artifacts from a Network Authority database."""
    if not yes:
        click.confirm(
            "Delete proof tables from this NA database after creating a backup?",
            abort=True,
        )

    result = _cleanup_proof_state(Path(db_path), backup_path, backup_dir)
    if output_format == "json":
        click.echo(json.dumps(result, indent=2, sort_keys=True))
        return

    click.echo(f"Backup: {result['backup_path']}")
    click.echo("Deleted proof rows:")
    for table, count in result["deleted_rows"].items():
        click.echo(f"  {table}: {count}")


@proof.command("remote")
@click.option("--acceptor", required=True, help="Recognizing sovereign NA endpoint.")
@click.option("--issuer", required=True, help="Subject/issuing sovereign NA endpoint.")
@click.option("--acceptor-config", default=None, help="Config for acceptor admin signing.")
@click.option("--issuer-config", default=None, help="Config for issuer admin signing.")
@click.option("--operator-key", default=None, help="Shared operator private key for both NAs.")
@click.option("--operator-key-id", default="operator-local", help="Shared operator key ID.")
@click.option("--acceptor-operator-key", default=None, help="Acceptor operator private key.")
@click.option("--acceptor-operator-key-id", default=None, help="Acceptor operator key ID.")
@click.option("--issuer-operator-key", default=None, help="Issuer operator private key.")
@click.option("--issuer-operator-key-id", default=None, help="Issuer operator key ID.")
@click.option("--role", default="role:service:maintainer", help="Attested role to prove.")
@click.option("--subject-id", default=None, help="Subject ID for the proof attestation.")
@click.option("--subject-public-key", default="proof-subject-public-key", help="Subject public key.")
@click.option("--claim", multiple=True, help="Extra proof claim as key=value. Repeatable.")
@click.option("--validity-hours", default=24, type=int, help="Proof artifact validity window.")
@click.option("--proof-bundle", default=None, help="Optional JSON proof bundle output path.")
@click.option("--adoption-proof", is_flag=True, help="Require external-operator evidence fields.")
@click.option("--acceptor-operator-label", default="unspecified", help="Human label for the acceptor operator.")
@click.option("--issuer-operator-label", default="unspecified", help="Human label for the issuer operator.")
@click.option(
    "--acceptor-operator-type",
    type=click.Choice(["maintainer", "external", "unknown"]),
    default="unknown",
    help="Relationship of the acceptor operator to Genesis Core.",
)
@click.option(
    "--issuer-operator-type",
    type=click.Choice(["maintainer", "external", "unknown"]),
    default="unknown",
    help="Relationship of the issuer operator to Genesis Core.",
)
@click.option("--issuer-controls-keys", is_flag=True, help="Issuer operator confirms they control their keys.")
@click.option(
    "--issuer-controls-infrastructure",
    is_flag=True,
    help="Issuer operator confirms they control their infrastructure.",
)
@click.option(
    "--operator-assistance-note",
    multiple=True,
    help="Onboarding assistance note for the proof bundle. Repeatable.",
)
def proof_remote(
    acceptor: str,
    issuer: str,
    acceptor_config: str | None,
    issuer_config: str | None,
    operator_key: str | None,
    operator_key_id: str,
    acceptor_operator_key: str | None,
    acceptor_operator_key_id: str | None,
    issuer_operator_key: str | None,
    issuer_operator_key_id: str | None,
    role: str,
    subject_id: str | None,
    subject_public_key: str,
    claim: tuple[str, ...],
    validity_hours: int,
    proof_bundle: str | None,
    adoption_proof: bool,
    acceptor_operator_label: str,
    issuer_operator_label: str,
    acceptor_operator_type: str,
    issuer_operator_type: str,
    issuer_controls_keys: bool,
    issuer_controls_infrastructure: bool,
    operator_assistance_note: tuple[str, ...],
) -> None:
    """Run the attestation -> treaty -> revocation proof against two endpoints."""
    if adoption_proof and (
        issuer_operator_type != "external"
        or not issuer_controls_keys
        or not issuer_controls_infrastructure
    ):
        raise click.ClickException(
            "--adoption-proof requires --issuer-operator-type external, "
            "--issuer-controls-keys, and --issuer-controls-infrastructure."
        )

    bundle = _run_remote_proof(
        acceptor_endpoint=acceptor,
        issuer_endpoint=issuer,
        acceptor_signer=_admin_signer_from_inputs(
            acceptor_config,
            acceptor_operator_key or operator_key,
            acceptor_operator_key_id or operator_key_id,
        ),
        issuer_signer=_admin_signer_from_inputs(
            issuer_config,
            issuer_operator_key or operator_key,
            issuer_operator_key_id or operator_key_id,
        ),
        role=_normalize_role(role),
        subject_id=subject_id or f"proof-subject-{uuid.uuid4()}",
        subject_public_key=subject_public_key,
        claims=_parse_claims(claim),
        validity_hours=validity_hours,
        operator_evidence={
            "acceptor": {
                "operator_label": acceptor_operator_label,
                "operator_type": acceptor_operator_type,
            },
            "issuer": {
                "operator_label": issuer_operator_label,
                "operator_type": issuer_operator_type,
                "controls_keys": issuer_controls_keys,
                "controls_infrastructure": issuer_controls_infrastructure,
            },
            "assistance_notes": list(operator_assistance_note),
            "adoption_proof": adoption_proof,
        },
    )

    if proof_bundle:
        output = Path(proof_bundle)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")

    click.echo("Remote sovereign proof passed")
    click.echo(f"  acceptor:    {bundle['acceptor']['network_name']}")
    click.echo(f"  issuer:      {bundle['issuer']['network_name']}")
    click.echo(f"  attestation: {bundle['attestation_id']}")
    click.echo(f"  treaty:      {bundle['treaty_id']}")
    click.echo(f"  feed:        {bundle['feed_id']}")
    click.echo(f"  sequence:    {bundle['feed_sequence']}")
    click.echo(f"  pre:         {bundle['pre_revocation']['reason']}")
    click.echo(f"  post:        {bundle['post_revocation']['reason']}")
    if adoption_proof:
        click.echo("  adoption:    external operator evidence captured")


@click.group()
def dev() -> None:
    """Run local developer workflows."""


@dev.command("up")
def dev_up() -> None:
    """Run the in-process local smoke workflow."""
    workflow_path = Path(__file__).resolve().parents[2] / "examples" / "test_workflow.py"
    if not workflow_path.exists():
        raise click.ClickException(f"Smoke workflow not found at {workflow_path}")
    smoke_main = runpy.run_path(str(workflow_path))["main"]
    smoke_main()


@dev.command("down")
def dev_down() -> None:
    """Remove local development artifacts created by `genesis-mesh init`."""
    locked_paths: list[str] = []
    generated_paths = [Path(".genesis-mesh"), Path(PROJECT_CONFIG)]
    generated_paths.extend(Path.cwd().glob(".node*"))

    for path in generated_paths:
        if path.exists():
            display_path = path
            if path.is_absolute():
                try:
                    display_path = path.relative_to(Path.cwd())
                except ValueError:
                    display_path = path
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                click.echo(f"Removed {display_path}")
            except PermissionError as exc:
                locked_paths.append(str(display_path))
                click.echo(f"Could not remove {display_path}: {exc}", err=True)

    if locked_paths:
        raise click.ClickException(
            "Some generated files are locked. Stop any running `genesis-mesh na start` "
            "or node runtime processes, then run `genesis-mesh dev down` again."
        )


def _parse_anchor(anchor: str) -> tuple[str, str]:
    """Parse an anchor string into ID and endpoint."""
    if ":" not in anchor:
        raise click.ClickException("Anchor must use id:endpoint format")
    anchor_id, endpoint = anchor.split(":", 1)
    return anchor_id, endpoint


def _normalize_role(role: str) -> str:
    """Return a canonical role string."""
    return role if role.startswith("role:") else f"role:{role}"


def _load_genesis(path: Path) -> GenesisBlock:
    """Load a signed genesis block from disk."""
    with path.open("r", encoding="utf-8") as f:
        return GenesisBlock(**json.load(f))


def _load_existing_certificate(cert_path: Path, node: MeshNode) -> JoinCertificate | None:
    """Load a valid local certificate for a node if one exists."""
    if not cert_path.exists():
        return None

    cert = JoinCertificate.model_validate_json(cert_path.read_text(encoding="utf-8"))
    if cert.node_public_key != node.node_keypair.public_key_b64:
        raise click.ClickException(
            f"Local certificate {cert_path} does not match the configured node key."
        )
    if not node._verify_join_certificate(cert):
        return None
    return cert


def _describe_unusable_certificate(cert_path: Path, node: MeshNode) -> str | None:
    """Return a user-facing reason that a local certificate cannot be reused."""
    if not cert_path.exists():
        return None

    try:
        cert = JoinCertificate.model_validate_json(cert_path.read_text(encoding="utf-8"))
    except Exception:
        return f"Local certificate {cert_path} is malformed."

    if cert.node_public_key != node.node_keypair.public_key_b64:
        return f"Local certificate {cert_path} does not match the configured node key."

    now = datetime.now(timezone.utc)
    if cert.expires_at < now:
        return f"Local certificate {cert.cert_id} expired at {cert.expires_at.isoformat()}."
    if cert.issued_at > now:
        return f"Local certificate {cert.cert_id} is not valid until {cert.issued_at.isoformat()}."

    return f"Local certificate {cert.cert_id} could not be verified."


def _load_existing_policy(policy_path: Path, node: MeshNode) -> PolicyManifest | None:
    """Load a valid local policy manifest if one exists."""
    if not policy_path.exists():
        return None

    policy = PolicyManifest.model_validate_json(policy_path.read_text(encoding="utf-8"))
    if not node._verify_policy_manifest(policy):
        return None
    node.policy_manifest = policy
    return policy


def _required_config_path(config: dict[str, Any], section: str, key: str) -> Path:
    """Return a required config path or raise a click error."""
    value = get_config_value(config, section, key)
    if not value:
        raise click.ClickException(f"Missing [{section}].{key} in config")
    return Path(value)


def _admin_headers(config: dict[str, Any], body: dict[str, Any]) -> dict[str, str]:
    """Create signed admin request headers from CLI config."""
    key_id = get_config_value(config, "operator", "key_id", "operator-local")
    key_path = _required_config_path(config, "paths", "operator_private_key")
    return _signed_admin_headers(key_id, key_path, body)


def _signed_admin_headers(key_id: str, key_path: Path, body: dict[str, Any]) -> dict[str, str]:
    """Create signed admin request headers from a key ID and private key path."""
    timestamp = datetime.now(timezone.utc).isoformat()
    nonce = str(uuid.uuid4())
    canonical = json.dumps(
        {
            "body": body,
            "key_id": key_id,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "X-Admin-Key-Id": key_id,
        "X-Admin-Timestamp": timestamp,
        "X-Admin-Nonce": nonce,
        "X-Admin-Signature": sign_data(
            canonical.encode("utf-8"),
            load_private_key(str(key_path)),
        ),
    }


def _admin_signer_from_inputs(
    config_path: str | None,
    operator_key: str | None,
    operator_key_id: str,
) -> tuple[str, Path]:
    """Resolve an admin signing key from explicit options or a CLI config."""
    if operator_key:
        return operator_key_id, Path(operator_key)
    if not config_path:
        raise click.ClickException(
            "Missing admin signing key. Pass --operator-key, endpoint-specific "
            "operator key options, or endpoint-specific config."
        )
    config = _load_cli_config(config_path, required=True)
    key_id = get_config_value(config, "operator", "key_id", operator_key_id)
    return key_id, _required_config_path(config, "paths", "operator_private_key")


def _request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    expected_status: int = 200,
    label: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run an HTTP request and raise compact Click errors on failure."""
    try:
        response = session.request(method, url, timeout=20, **kwargs)
    except requests.RequestException as exc:
        raise click.ClickException(f"{label} failed: {exc}") from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:500]}

    if response.status_code != expected_status:
        raise click.ClickException(f"{label} failed: {response.status_code} {payload}")
    return payload


def _parse_claims(claims: tuple[str, ...]) -> dict[str, str]:
    """Parse repeated key=value claim options."""
    parsed: dict[str, str] = {}
    for item in claims:
        if "=" not in item:
            raise click.ClickException("--claim values must use key=value format")
        key, value = item.split("=", 1)
        if not key:
            raise click.ClickException("--claim keys must not be empty")
        parsed[key] = value
    return parsed


def _run_remote_proof(
    *,
    acceptor_endpoint: str,
    issuer_endpoint: str,
    acceptor_signer: tuple[str, Path],
    issuer_signer: tuple[str, Path],
    role: str,
    subject_id: str,
    subject_public_key: str,
    claims: dict[str, str],
    validity_hours: int,
    operator_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the direct-recognition proof and return a redacted proof bundle."""
    acceptor = acceptor_endpoint.rstrip("/")
    issuer = issuer_endpoint.rstrip("/")
    session = requests.Session()

    acceptor_genesis = _request_json(
        session,
        "GET",
        f"{acceptor}/genesis",
        label="acceptor genesis",
    )
    issuer_genesis = _request_json(
        session,
        "GET",
        f"{issuer}/genesis",
        label="issuer genesis",
    )
    acceptor_id = acceptor_genesis["network_name"]
    issuer_id = issuer_genesis["network_name"]
    issuer_public_key = issuer_genesis["network_authority"]["public_key"]

    attestation_body = {
        "subject_id": subject_id,
        "subject_public_key": subject_public_key,
        "roles": [role],
        "claims": claims,
        "validity_hours": validity_hours,
    }
    issuer_key_id, issuer_key_path = issuer_signer
    attestation = _request_json(
        session,
        "POST",
        f"{issuer}/admin/attestations",
        expected_status=201,
        label="issuer attestation issue",
        json=attestation_body,
        headers=_signed_admin_headers(issuer_key_id, issuer_key_path, attestation_body),
    )

    treaty_body = {
        "subject_sovereign_id": issuer_id,
        "subject_public_keys": [issuer_public_key],
        "scope": {
            "allowed_roles": [role],
            "accepted_statuses": ["active"],
            "claims": claims,
        },
        "validity_hours": validity_hours,
        "metadata": {
            "proof": "remote-sovereign-proof",
            "subject_endpoint": issuer,
        },
    }
    acceptor_key_id, acceptor_key_path = acceptor_signer
    treaty = _request_json(
        session,
        "POST",
        f"{acceptor}/admin/recognition-treaties",
        expected_status=201,
        label="acceptor treaty issue",
        json=treaty_body,
        headers=_signed_admin_headers(acceptor_key_id, acceptor_key_path, treaty_body),
    )

    pre_revocation = _request_json(
        session,
        "POST",
        f"{acceptor}/attestations/verify-with-treaty",
        label="pre-revocation verification",
        json={"attestation": attestation, "treaty": treaty},
    )
    if not pre_revocation.get("accepted"):
        raise click.ClickException(f"Pre-revocation proof was rejected: {pre_revocation}")

    revoke_body = {"reason": "remote_sovereign_proof_revocation"}
    _request_json(
        session,
        "POST",
        f"{issuer}/admin/attestations/{attestation['attestation_id']}/revoke",
        label="issuer attestation revoke",
        json=revoke_body,
        headers=_signed_admin_headers(issuer_key_id, issuer_key_path, revoke_body),
    )

    feed = _request_json(
        session,
        "GET",
        f"{issuer}/sovereign-revocation-feed?issuer_sovereign_id={issuer_id}",
        label="issuer revocation feed",
    )
    import_body = {
        "feed": feed,
        "issuer_public_keys": [issuer_public_key],
        "expected_issuer_sovereign_id": issuer_id,
    }
    imported = _request_json(
        session,
        "POST",
        f"{acceptor}/admin/sovereign-revocation-feeds/import",
        label="acceptor feed import",
        json=import_body,
        headers=_signed_admin_headers(acceptor_key_id, acceptor_key_path, import_body),
    )
    if not imported.get("accepted"):
        raise click.ClickException(f"Revocation feed import was rejected: {imported}")

    post_revocation = _request_json(
        session,
        "POST",
        f"{acceptor}/attestations/verify-with-treaty",
        label="post-revocation verification",
        json={"attestation": attestation, "treaty": treaty},
    )
    if post_revocation.get("accepted"):
        raise click.ClickException("Post-revocation proof was still accepted")

    connectome = _request_json(
        session,
        "GET",
        f"{acceptor}/connectome.json",
        label="acceptor Connectome",
    )
    trust_path = _request_json(
        session,
        "GET",
        f"{acceptor}/connectome/trust-path?from={acceptor_id}&to={issuer_id}",
        label="acceptor trust path",
    )

    return {
        "proof": "remote-sovereign-recognition-revocation",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "operators": operator_evidence or {
            "acceptor": {"operator_label": "unspecified", "operator_type": "unknown"},
            "issuer": {
                "operator_label": "unspecified",
                "operator_type": "unknown",
                "controls_keys": False,
                "controls_infrastructure": False,
            },
            "assistance_notes": [],
            "adoption_proof": False,
        },
        "acceptor": {
            "network_name": acceptor_id,
            "endpoint": acceptor,
            "na_public_key_prefix": acceptor_genesis["network_authority"]["public_key"][:24],
        },
        "issuer": {
            "network_name": issuer_id,
            "endpoint": issuer,
            "na_public_key_prefix": issuer_public_key[:24],
        },
        "attestation_id": attestation["attestation_id"],
        "treaty_id": treaty["treaty_id"],
        "feed_id": feed["feed_id"],
        "feed_sequence": feed["sequence"],
        "pre_revocation": {
            "accepted": pre_revocation["accepted"],
            "reason": pre_revocation["reason"],
        },
        "post_revocation": {
            "accepted": post_revocation["accepted"],
            "reason": post_revocation["reason"],
        },
        "trust_path": trust_path,
        "connectome_summary": connectome["summary"],
    }


def _cleanup_proof_state(
    db_path: Path,
    backup_path: str | None,
    backup_dir: str | None,
) -> dict[str, Any]:
    """Back up a SQLite database and delete only cross-sovereign proof rows."""
    if not db_path.exists():
        raise click.ClickException(f"Database not found: {db_path}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    if backup_path:
        backup = Path(backup_path)
    else:
        directory = Path(backup_dir) if backup_dir else db_path.parent
        backup = directory / f"{db_path.name}.backup-before-proof-cleanup-{timestamp}"
    backup.parent.mkdir(parents=True, exist_ok=True)

    tables = [
        "imported_sovereign_revocations",
        "sovereign_revocation_feeds",
        "recognition_treaties",
        "membership_attestations",
    ]
    deleted: dict[str, int] = {}
    conn = sqlite3.connect(str(db_path))
    try:
        dest = sqlite3.connect(str(backup))
        try:
            conn.backup(dest)
        finally:
            dest.close()

        with conn:
            for table in tables:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (table,),
                ).fetchone()
                if not exists:
                    deleted[table] = 0
                    continue
                before = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                conn.execute(f"DELETE FROM {table}")
                deleted[table] = int(before)
    finally:
        conn.close()

    return {
        "db_path": str(db_path),
        "backup_path": str(backup),
        "deleted_rows": deleted,
    }


async def _run_runtime_forever(runtime: MeshNodeRuntime) -> None:
    """Start a runtime and keep it alive until cancelled."""
    await runtime.start()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runtime.stop()
