"""Persona-oriented operational commands for the Genesis Mesh CLI."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import click
import requests
from werkzeug.serving import run_simple

from .dev_ops import dev
from .federation import federation
from .fleet_ops import fleet
from .init_ops import init
from .managed import managed
from .proof_ops import proof
from .supply_chain import supply_chain
from .treaty_ops import treaty
from .trust_bundle import trust_bundle
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
    _admin_signer_from_inputs,
    _describe_unusable_certificate,
    _load_cli_config,
    _load_existing_certificate,
    _load_existing_policy,
    _load_genesis,
    _request_json,
    _require_positive_int,
    _required_config_path,
    _run_runtime_forever,
    _signed_admin_headers,
    _validate_cli_roles,
)

logger = logging.getLogger(__name__)


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
    cli.add_command(federation)
    cli.add_command(fleet)
    cli.add_command(proof)
    cli.add_command(managed)
    cli.add_command(supply_chain)
    cli.add_command(trust_bundle)
    cli.add_command(treaty)



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
    logger.info("Starting Network Authority", extra={"endpoint": f"http://{bind_host}:{bind_port}"})
    logger.warning(
        "Starting Werkzeug development server. For production deployments use start.sh and Gunicorn."
    )
    run_simple(
        hostname=bind_host,
        port=bind_port,
        application=app,
        use_reloader=False,
        use_debugger=False,
    )


@click.group()
def admin() -> None:
    """Run operator admin actions against the Network Authority."""


@admin.command("invite")
@click.option("--config", "config_path", default=None, help="Config path.")
@click.option("--na", "na_endpoint", default=None, help="Network Authority URL.")
@click.option("--operator-key", default=None, help="Operator private key.")
@click.option("--operator-key-id", default="operator-local", help="Operator key ID.")
@click.option("--role", "roles", multiple=True, default=["client"], help="Role to assign.")
@click.option("--validity-hours", default=168, type=int, help="Maximum certificate validity.")
@click.option("--token-expiry-hours", default=24, type=int, help="Invite validity.")
def admin_invite(
    config_path: str | None,
    na_endpoint: str | None,
    operator_key: str | None,
    operator_key_id: str,
    roles: tuple[str, ...],
    validity_hours: int,
    token_expiry_hours: int,
) -> None:
    """Create a single-use invite token and print it."""
    config = _load_cli_config(config_path, required=operator_key is None)
    endpoint_value = na_endpoint or get_config_value(config, "network", "na_endpoint")
    if not endpoint_value:
        raise click.ClickException("No NA endpoint. Pass --na or set [network].na_endpoint in config.")
    _require_positive_int("--validity-hours", validity_hours)
    _require_positive_int("--token-expiry-hours", token_expiry_hours)
    endpoint = endpoint_value.rstrip("/")
    body: dict[str, Any] = {
        "roles": _validate_cli_roles(roles),
        "max_validity_hours": validity_hours,
        "token_expiry_hours": token_expiry_hours,
    }
    payload = _request_json(
        requests.Session(),
        "POST",
        f"{endpoint}/admin/invite",
        expected_status=201,
        label="invite creation",
        json=body,
        headers=_admin_headers_from_inputs(config_path, operator_key, operator_key_id, config, body),
    )
    click.echo(payload["token_id"])


@admin.command("revoke")
@click.argument("cert_id")
@click.option("--config", "config_path", default=None, help="Config path.")
@click.option("--na", "na_endpoint", default=None, help="Network Authority URL.")
@click.option("--operator-key", default=None, help="Operator private key.")
@click.option("--operator-key-id", default="operator-local", help="Operator key ID.")
@click.option("--reason", default="unspecified", help="Revocation reason.")
def admin_revoke(
    config_path: str | None,
    na_endpoint: str | None,
    operator_key: str | None,
    operator_key_id: str,
    cert_id: str,
    reason: str,
) -> None:
    """Revoke a certificate by ID."""
    config = _load_cli_config(config_path, required=operator_key is None)
    endpoint_value = na_endpoint or get_config_value(config, "network", "na_endpoint")
    if not endpoint_value:
        raise click.ClickException("No NA endpoint. Pass --na or set [network].na_endpoint in config.")
    endpoint = endpoint_value.rstrip("/")
    body = {"cert_id": cert_id, "reason": reason}
    payload = _request_json(
        requests.Session(),
        "POST",
        f"{endpoint}/admin/revoke",
        label="certificate revocation",
        json=body,
        headers=_admin_headers_from_inputs(config_path, operator_key, operator_key_id, config, body),
    )
    click.echo(json.dumps(payload, indent=2))


def _admin_headers_from_inputs(
    config_path: str | None,
    operator_key: str | None,
    operator_key_id: str,
    config: dict[str, Any],
    body: dict[str, Any],
) -> dict[str, str]:
    """Create signed admin headers from direct key flags or a CLI config."""
    if operator_key:
        signer_key_id, key_path = _admin_signer_from_inputs(
            config_path,
            operator_key,
            operator_key_id,
        )
        return _signed_admin_headers(signer_key_id, key_path, body)
    return _admin_headers(config, body)


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
    _require_positive_int("--validity-hours", validity_hours)
    config = _load_cli_config(config_path, required=False)
    endpoint = na_endpoint.rstrip("/")
    config_target = resolve_config_path(config_path)
    home = Path(get_config_value(config, "paths", "home", config_target.parent))
    keys_dir = home / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)

    genesis_path = Path(get_config_value(config, "paths", "genesis", home / "genesis.signed.json"))
    if not genesis_path.exists():
        payload = _request_json(
            requests.Session(),
            "GET",
            f"{endpoint}/genesis",
            label="genesis fetch",
        )
        genesis_path.parent.mkdir(parents=True, exist_ok=True)
        genesis_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

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
        roles=_validate_cli_roles(roles),
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
        try:
            cert = node.join_network(endpoint, validity_hours=validity_hours, invite_token=token)
        except Exception as exc:
            raise click.ClickException(
                "Join enrollment failed. Check that --config belongs to the same "
                "sovereign as --na, that the invite token is still valid, and that "
                f"the requested role is allowed. Detail: {exc}"
            ) from exc
        try:
            policy = node.fetch_policy(endpoint)
        except Exception as exc:
            raise click.ClickException(f"Policy fetch failed after enrollment: {exc}") from exc

    try:
        heartbeat_ok = node.send_heartbeat(endpoint)
    except Exception as exc:
        raise click.ClickException(f"Heartbeat failed after enrollment: {exc}") from exc
    if not heartbeat_ok:
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
    payload = _request_json(
        requests.Session(),
        "GET",
        url,
        params=params,
        label="discovery query",
    )
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
@click.option(
    "--na",
    "--endpoint",
    "na_endpoint",
    required=True,
    help="Network Authority URL.",
)
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
    payload = _request_json(
        requests.Session(),
        "GET",
        f"{endpoint}/sovereign.json",
        label="sovereign metadata query",
    )
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
