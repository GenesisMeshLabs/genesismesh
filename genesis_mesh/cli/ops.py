"""Persona-oriented operational commands for the Genesis Mesh CLI."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import click
import requests

from .dev_ops import dev
from .init_ops import init
from .managed import managed
from .proof_ops import proof
from .supply_chain import supply_chain
from ..crypto import (
    KeyPair,
    generate_keypair,
    load_private_key,
    save_keypair,
)
from ..models import JoinCertificate
from ..na_service.auth import load_operator_public_keys
from ..na_service.server import create_app
from ..node.node import MeshNode
from ..node.runtime import MeshNodeRuntime
from .config import (
    config_path_value,
    get_config_value,
    resolve_config_path,
    save_config,
    set_config_value,
)
from .support import (
    _admin_headers,
    _describe_unusable_certificate,
    _load_cli_config,
    _load_existing_certificate,
    _load_existing_policy,
    _load_genesis,
    _normalize_role,
    _required_config_path,
    _run_runtime_forever,
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
    cli.add_command(managed)
    cli.add_command(supply_chain)



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
