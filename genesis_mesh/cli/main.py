"""Main CLI application for Genesis Mesh."""

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click

from ..crypto import generate_keypair, save_keypair, load_private_key, sign_model
from ..models import GenesisBlock, NetworkAuthority, BootstrapAnchor, PolicyManifestRef
from ..observability import configure_logging
from .env_file import EnvFileError, register_operator_key, registered_operator_keys
from .ops import register_operational_commands

logger = logging.getLogger(__name__)


@click.group()
@click.version_option(package_name="genesis-mesh", prog_name="genesis-mesh", message="%(prog)s %(version)s")
@click.option('--debug', is_flag=True, help='Enable debug logging')
def cli(debug):
    """Genesis Mesh CLI - Cryptographic mesh networking toolkit."""
    configure_logging(debug=debug)


@cli.group()
def keygen():
    """Generate cryptographic keys."""
    pass


@keygen.command('root')
@click.option('--output', required=True, help='Output path (without extension)')
@click.option('--key-id', default='rs-2025-q1', help='Key identifier')
def keygen_root(output, key_id):
    """Generate Root Sovereign keypair (offline authority)."""
    click.echo("Generating Root Sovereign keypair...")
    click.echo("WARNING: This key should be kept OFFLINE and highly secure!")

    keypair = generate_keypair()
    private_path, public_path = save_keypair(keypair, output, key_id)

    click.echo("\nOK Root Sovereign keys generated:")
    click.echo(f"  Private key: {private_path} (KEEP OFFLINE AND SECURE)")
    click.echo(f"  Public key:  {public_path}")
    click.echo(f"\nPublic key (base64): {keypair.public_key_b64}")


@keygen.command('network-authority')
@click.option('--output', required=True, help='Output path (without extension)')
@click.option('--key-id', default='na-2025-q1', help='Key identifier')
def keygen_na(output, key_id):
    """Generate Network Authority keypair."""
    click.echo("Generating Network Authority keypair...")

    keypair = generate_keypair()
    private_path, public_path = save_keypair(keypair, output, key_id)

    click.echo("\nOK Network Authority keys generated:")
    click.echo(f"  Private key: {private_path} (KEEP SECURE - HSM recommended)")
    click.echo(f"  Public key:  {public_path}")
    click.echo(f"\nPublic key (base64): {keypair.public_key_b64}")


@keygen.command('node')
@click.option('--output', required=True, help='Output path (without extension)')
@click.option('--key-id', help='Optional key identifier')
def keygen_node(output, key_id):
    """Generate node identity keypair."""
    click.echo("Generating node identity keypair...")

    keypair = generate_keypair()
    private_path, public_path = save_keypair(keypair, output, key_id)

    click.echo("\nOK Node identity keys generated:")
    click.echo(f"  Private key: {private_path}")
    click.echo(f"  Public key:  {public_path}")
    click.echo(f"\nPublic key (base64): {keypair.public_key_b64}")


@keygen.command('operator')
@click.option('--output', required=True, help='Output path (without extension)')
@click.option('--key-id', required=True, help='Operator key identifier, as the NA knows it')
@click.option(
    '--tier', type=click.Choice(["read", "standard", "privileged"]), default="standard", show_default=True,
    help='Operator tier: read (views), standard (evaluate, reads), privileged (policies, attestations, keys)',
)
@click.option(
    '--env-file', 'env_file', type=click.Path(dir_okay=False, path_type=Path), default=None,
    help='Register the key and its tier in this NA settings file (see na start --env-file)',
)
@click.option('--replace', is_flag=True, help='Replace a key ID already registered with another public key')
def keygen_operator(output, key_id, tier, env_file, replace):
    """Generate an operator (admin) keypair, optionally registered in an NA settings file (v1.1.0)."""
    key_id = key_id.strip()
    if not key_id:
        raise click.ClickException("--key-id must not be empty")
    base = Path(output)
    key_files = (base.with_suffix('.key'), base.with_suffix('.pub'))
    for path in key_files:
        if path.exists():
            raise click.ClickException(f"{path} already exists; choose another --output or remove it first")
    if env_file is not None:
        if not env_file.is_file():
            raise click.ClickException(f"Settings file not found: {env_file} (init --env-file creates one)")
        # Check before writing anything, so a refusal leaves no key files.
        try:
            registered = registered_operator_keys(env_file)
        except EnvFileError as exc:
            raise click.ClickException(str(exc)) from exc
        if key_id in registered and not replace:
            raise click.ClickException(
                f"{env_file}: operator key {key_id!r} is already registered with another public key; "
                "use --replace to replace it"
            )

    click.echo("Generating operator keypair...")
    keypair = generate_keypair()
    private_path, public_path = save_keypair(keypair, output, key_id)
    if env_file is not None:
        # Register only once the key files exist; undo them if that fails, so
        # the file never names a key nobody holds.
        try:
            register_operator_key(env_file, key_id, keypair.public_key_b64, tier, replace=replace)
        except Exception as exc:
            for path in key_files:
                path.unlink(missing_ok=True)
            raise click.ClickException(f"{env_file}: {exc}") from exc

    click.echo(f"\nOK Operator key {key_id} ({tier} tier) generated:")
    click.echo(f"  Private key: {private_path} (signs admin requests; keep it out of version control)")
    click.echo(f"  Public key:  {public_path}")
    click.echo(f"\nPublic key (base64): {keypair.public_key_b64}")
    if env_file is not None:
        click.echo(f"Registered in {env_file}; restart the Network Authority to load it.")
    else:
        click.echo(
            "\nRegister it with the NA in OPERATOR_PUBLIC_KEYS_JSON and OPERATOR_KEY_TIERS_JSON, "
            "or rerun with --env-file."
        )


@cli.group()
def genesis():
    """Manage genesis blocks."""
    pass


@genesis.command('create')
@click.option('--network-name', required=True, help='Network name (e.g., USG)')
@click.option('--network-version', default='v0.1', help='Network version')
@click.option('--root-key', required=True, help='Path to root public key')
@click.option('--na-key', required=True, help='Path to NA public key')
@click.option('--na-valid-days', default=90, help='NA key validity in days')
@click.option('--anchor', multiple=True, help='Bootstrap anchor (id:endpoint)')
@click.option('--output', required=True, help='Output genesis block path')
def genesis_create(network_name, network_version, root_key, na_key, na_valid_days, anchor, output):
    """Create a new genesis block (unsigned)."""
    click.echo(f"Creating genesis block for network: {network_name}")

    # Load public keys
    with open(root_key, 'r') as f:
        root_pub_lines = [l.strip() for l in f if not l.startswith('#')]
        root_pub_b64 = ''.join(root_pub_lines)

    with open(na_key, 'r') as f:
        na_pub_lines = [l.strip() for l in f if not l.startswith('#')]
        na_pub_b64 = ''.join(na_pub_lines)

    # Parse bootstrap anchors
    bootstrap_anchors = []
    for anchor_str in anchor:
        anchor_id, endpoint = anchor_str.split(':', 1)
        bootstrap_anchors.append(BootstrapAnchor(id=anchor_id, endpoint=endpoint))

    # Create NA validity window
    now = datetime.now(timezone.utc)
    na_valid_to = now + timedelta(days=na_valid_days)

    # Create genesis block
    genesis_block = GenesisBlock(
        network_name=network_name,
        network_version=network_version,
        root_public_key=root_pub_b64,
        network_authority=NetworkAuthority(
            public_key=na_pub_b64,
            valid_from=now,
            valid_to=na_valid_to
        ),
        policy_manifest=PolicyManifestRef(
            hash="sha256:placeholder",
            url=None
        ),
        bootstrap_anchors=bootstrap_anchors
    )

    # Save unsigned genesis block
    with open(output, 'w') as f:
        json.dump(genesis_block.model_dump(mode='json'), f, indent=2, default=str)

    click.echo(f"\nOK Genesis block created: {output}")
    click.echo(
        "Note: genesis block contains a placeholder policy hash. "
        "Replace PolicyManifestRef.hash with the SHA-256 of your policy document before production use.",
        err=True,
    )
    click.echo(f"  Network: {network_name} ({network_version})")
    click.echo(f"  NA validity: {na_valid_days} days")
    click.echo(f"  Bootstrap anchors: {len(bootstrap_anchors)}")
    click.echo(f"\nNext: Sign with root key using 'genesis sign'")


@genesis.command('sign')
@click.option('--genesis', required=True, help='Path to unsigned genesis block')
@click.option('--root-private-key', required=True, help='Path to root private key')
@click.option('--key-id', default='rs-2025-q1', help='Root key identifier')
@click.option('--output', required=True, help='Output signed genesis block path')
def genesis_sign(genesis, root_private_key, key_id, output):
    """Sign a genesis block with Root Sovereign key."""
    click.echo("Signing genesis block...")
    click.echo("WARNING: Ensure you are on an OFFLINE, SECURE system!")

    # Load genesis block
    with open(genesis, 'r') as f:
        genesis_data = json.load(f)
        genesis_block = GenesisBlock(**genesis_data)

    # Load root private key
    root_key = load_private_key(root_private_key)

    # Sign genesis block
    signature = sign_model(genesis_block, root_key, key_id)
    genesis_block.signatures.append(signature)

    # Save signed genesis block
    with open(output, 'w') as f:
        json.dump(genesis_block.model_dump(mode='json'), f, indent=2, default=str)

    click.echo(f"\nOK Genesis block signed: {output}")
    click.echo(f"  Signature key: {key_id}")
    click.echo(f"  Network: {genesis_block.network_name}")


@genesis.command('verify')
@click.option('--genesis', required=True, help='Path to signed genesis block')
def genesis_verify(genesis):
    """Verify genesis block signatures."""
    from ..crypto import verify_model_signature, public_key_from_b64

    click.echo("Verifying genesis block...")

    # Load genesis block
    with open(genesis, 'r') as f:
        genesis_data = json.load(f)
        genesis_block = GenesisBlock(**genesis_data)

    # A click command's return value is not its exit code: exit explicitly so
    # scripts can rely on it (v1.0.2).
    if not genesis_block.signatures:
        click.echo("ERROR No signatures found!", err=True)
        raise SystemExit(1)

    root_public_key = public_key_from_b64(genesis_block.root_public_key)

    all_valid = True
    for sig in genesis_block.signatures:
        valid = verify_model_signature(genesis_block, sig, root_public_key)
        status = "OK" if valid else "ERROR"
        click.echo(f"{status} Signature from {sig.key_id}: {'VALID' if valid else 'INVALID'}")
        all_valid = all_valid and valid

    if not all_valid:
        click.echo("\nERROR Signature verification failed!", err=True)
        raise SystemExit(1)
    click.echo("\nOK All signatures verified successfully")
    click.echo(f"  Network: {genesis_block.network_name} ({genesis_block.network_version})")


@cli.command()
@click.option('--genesis', required=True, help='Path to signed genesis block')
def info(genesis):
    """Display genesis block information."""
    # Load genesis block
    with open(genesis, 'r') as f:
        genesis_data = json.load(f)
        genesis_block = GenesisBlock(**genesis_data)

    click.echo("=== Genesis Block Information ===\n")
    click.echo(f"Network Name:    {genesis_block.network_name}")
    click.echo(f"Network Version: {genesis_block.network_version}")
    click.echo(f"\nRoot Public Key: {genesis_block.root_public_key[:32]}...")
    click.echo(f"\nNetwork Authority:")
    click.echo(f"  Public Key:  {genesis_block.network_authority.public_key[:32]}...")
    click.echo(f"  Valid From:  {genesis_block.network_authority.valid_from}")
    click.echo(f"  Valid To:    {genesis_block.network_authority.valid_to}")
    click.echo(f"\nCrypto Suites: {', '.join(genesis_block.allowed_crypto_suites)}")
    click.echo(f"Transports:    {', '.join(genesis_block.allowed_transports)}")
    click.echo(f"\nBootstrap Anchors ({len(genesis_block.bootstrap_anchors)}):")
    for anchor in genesis_block.bootstrap_anchors:
        click.echo(f"  - {anchor.id}: {anchor.endpoint}")
    click.echo(f"\nSignatures ({len(genesis_block.signatures)}):")
    for sig in genesis_block.signatures:
        click.echo(f"  - {sig.key_id}")


register_operational_commands(cli)


def _utf8_output() -> None:
    """Write UTF-8 on stdout and stderr.

    Help texts and data carry characters outside a Windows console code page;
    printing them into a pipe or file encoded with that code page raised
    UnicodeEncodeError (v1.0.2).
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "").replace("_", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def main():
    """Entry point for CLI."""
    _utf8_output()
    try:
        cli()
    except OSError as exc:
        # A file or network error is the user's to fix, not a crash: report it
        # like any other CLI error (v1.0.2). --debug keeps the traceback.
        if "--debug" in sys.argv[1:]:
            raise
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
