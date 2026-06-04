"""Initialization commands for the Genesis Mesh operational CLI."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
from click.core import ParameterSource

from ..crypto import generate_keypair, save_keypair, sign_model
from ..models import BootstrapAnchor, GenesisBlock, NetworkAuthority, PolicyManifestRef
from .config import PROJECT_CONFIG, config_path_value, save_config
from .support import _parse_anchor


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
