"""Persona-oriented operational commands for the Genesis Mesh CLI."""

from __future__ import annotations

import asyncio
import base64
import json
import runpy
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import click
import requests

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
@click.option(
    "--anchor",
    default="",
    help="Optional peer bootstrap anchor id:endpoint. Do not use the NA HTTP endpoint.",
)
@click.option("--force", is_flag=True, help="Overwrite existing config and artifacts.")
def init(
    config_path: str,
    home: str,
    network_name: str,
    network_version: str,
    na_endpoint: str,
    anchor: str,
    force: bool,
) -> None:
    """Create local keys, a signed genesis block, and CLI config."""
    root = Path(home)
    keys_dir = root / "keys"
    genesis_path = root / "genesis.json"
    signed_genesis_path = root / "genesis.signed.json"
    target_config = Path(config_path)

    if target_config.exists() and not force:
        raise click.ClickException(f"{target_config} already exists. Use --force to replace it.")
    if root.exists() and any(root.iterdir()) and not force:
        raise click.ClickException(f"{root} is not empty. Use --force to replace it.")

    if force and root.exists():
        shutil.rmtree(root)
    keys_dir.mkdir(parents=True, exist_ok=True)

    root_keypair = generate_keypair()
    na_keypair = generate_keypair()
    operator_keypair = generate_keypair()
    save_keypair(root_keypair, str(keys_dir / "root"), "rs-local")
    save_keypair(na_keypair, str(keys_dir / "na"), "na-local")
    save_keypair(operator_keypair, str(keys_dir / "operator"), "operator-local")

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
            "na_private_key": config_path_value(keys_dir / "na.key"),
            "operator_private_key": config_path_value(keys_dir / "operator.key"),
            "operator_public_key": config_path_value(keys_dir / "operator.pub"),
            "node_private_key": config_path_value(keys_dir / "node.key"),
            "node_certificate": config_path_value(root / "node.cert.json"),
            "policy": config_path_value(root / "policy.json"),
        },
        "na": {"key_id": "na-local", "host": "127.0.0.1", "port": 8443},
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
    database_path = db_path or str(Path(get_config_value(config, "paths", "home", ".")) / "na.db")
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
        "X-Admin-Signature": sign_data(canonical.encode("utf-8"), load_private_key(str(key_path))),
    }


async def _run_runtime_forever(runtime: MeshNodeRuntime) -> None:
    """Start a runtime and keep it alive until cancelled."""
    await runtime.start()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runtime.stop()
