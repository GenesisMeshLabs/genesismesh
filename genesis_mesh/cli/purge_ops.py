"""CLI commands for Ephemeral Identity Purge Protocol.

trust purge receipt   -- create a NullificationReceipt for an expired identity
trust purge register  -- batch receipts into a signed Merkle registry root
trust purge prove     -- generate a Merkle inclusion proof for a receipt
trust purge verify    -- verify a Merkle inclusion proof against a registry
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from ..crypto import load_private_key
from ..models.consensus import EphemeralExecutionIdentity
from ..models.purge import (
    NullificationInclusionProof,
    NullificationReceipt,
    NullificationRegistryRoot,
)
from ..trust.purge import (
    build_nullification_registry,
    create_nullification_receipt,
    prove_nullification_inclusion,
    verify_nullification_inclusion,
)


@click.group("purge")
def purge() -> None:
    """Ephemeral identity purge protocol — verifiable deletion of expired identities."""


# ---------------------------------------------------------------------------
# receipt
# ---------------------------------------------------------------------------


@purge.command("receipt")
@click.option("--identity", "identity_path", required=True, type=click.Path(exists=True),
              help="EphemeralExecutionIdentity JSON file to purge.")
@click.option("--purging-sovereign", "purging_sov", required=True,
              help="Sovereign ID performing the purge.")
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True),
              help="Ed25519 signing key file.")
@click.option("--output", "output_path", required=True, type=click.Path(),
              help="Output path for the signed NullificationReceipt JSON.")
def purge_receipt(
    identity_path: str, purging_sov: str, key_path: str, output_path: str,
) -> None:
    """Create a signed NullificationReceipt for an expired EphemeralExecutionIdentity.

    Fails if the identity has not yet expired.
    The receipt retains only identity_id, consensus_id, expiry, and a digest —
    not bearer_sovereign_id, allowed_capabilities, or decision_id.
    """
    sk = load_private_key(key_path)
    identity = EphemeralExecutionIdentity.model_validate_json(
        Path(identity_path).read_text(encoding="utf-8")
    )

    try:
        receipt = create_nullification_receipt(identity, purging_sov, sk)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    Path(output_path).write_text(receipt.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] NullificationReceipt {receipt.receipt_id}")
    click.echo(f"     Identity  : {identity.identity_id}")
    click.echo(f"     Purged by : {purging_sov}")
    click.echo(f"     Digest    : {receipt.identity_digest[:16]}...")
    click.echo(f"     Output    : {output_path}")


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


@purge.command("register")
@click.option("--receipt", "receipt_paths", required=True, multiple=True,
              type=click.Path(exists=True),
              help="NullificationReceipt JSON file. Pass once per receipt.")
@click.option("--operator-sovereign", "operator_sov", required=True,
              help="Operator sovereign ID signing the registry.")
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True),
              help="Ed25519 signing key file.")
@click.option("--output", "output_path", required=True, type=click.Path(),
              help="Output path for the signed NullificationRegistryRoot JSON.")
@click.option("--output-receipts", "receipts_path", default=None, type=click.Path(),
              help="Optional: output path for the ordered receipts list JSON (for proof generation).")
def purge_register(
    receipt_paths: tuple[str, ...], operator_sov: str,
    key_path: str, output_path: str, receipts_path: str | None,
) -> None:
    """Batch NullificationReceipts into a signed Merkle registry root."""
    sk = load_private_key(key_path)
    receipts = [
        NullificationReceipt.model_validate_json(Path(p).read_text(encoding="utf-8"))
        for p in receipt_paths
    ]

    registry, _ = build_nullification_registry(receipts, operator_sov, sk)
    Path(output_path).write_text(registry.model_dump_json(indent=2), encoding="utf-8")

    if receipts_path:
        receipts_json = json.dumps(
            [json.loads(r.model_dump_json()) for r in receipts], indent=2
        )
        Path(receipts_path).write_text(receipts_json, encoding="utf-8")

    click.echo(f"[OK] NullificationRegistryRoot {registry.root_id}")
    click.echo(f"     Receipts  : {len(receipts)}")
    click.echo(f"     Root      : {registry.merkle_root[:16]}...")
    click.echo(f"     Output    : {output_path}")


# ---------------------------------------------------------------------------
# prove
# ---------------------------------------------------------------------------


@purge.command("prove")
@click.option("--receipt-id", "receipt_id", required=True,
              help="receipt_id of the receipt to prove.")
@click.option("--receipts-file", "receipts_file", required=True, type=click.Path(exists=True),
              help="JSON array of NullificationReceipts (same order used in register).")
@click.option("--registry", "registry_path", required=True, type=click.Path(exists=True),
              help="NullificationRegistryRoot JSON.")
@click.option("--output", "output_path", required=True, type=click.Path(),
              help="Output path for the NullificationInclusionProof JSON.")
def purge_prove(
    receipt_id: str, receipts_file: str, registry_path: str, output_path: str,
) -> None:
    """Generate a Merkle inclusion proof for a NullificationReceipt."""
    receipts_data = json.loads(Path(receipts_file).read_text(encoding="utf-8"))
    receipts = [NullificationReceipt.model_validate(r) for r in receipts_data]
    registry = NullificationRegistryRoot.model_validate_json(
        Path(registry_path).read_text(encoding="utf-8")
    )

    leaf_hashes = [r.digest() for r in receipts]
    from ..trust.purge import _build_merkle_tree  # noqa: PLC0415
    _, levels = _build_merkle_tree(leaf_hashes)

    try:
        proof = prove_nullification_inclusion(receipt_id, receipts, levels, registry)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    Path(output_path).write_text(proof.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] NullificationInclusionProof {proof.proof_id}")
    click.echo(f"     Receipt   : {receipt_id}")
    click.echo(f"     Path len  : {len(proof.merkle_path)}")
    click.echo(f"     Output    : {output_path}")


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@purge.command("verify")
@click.option("--proof", "proof_path", required=True, type=click.Path(exists=True),
              help="NullificationInclusionProof JSON.")
@click.option("--registry", "registry_path", required=True, type=click.Path(exists=True),
              help="NullificationRegistryRoot JSON.")
@click.option("--receipt", "receipt_path", required=True, type=click.Path(exists=True),
              help="NullificationReceipt JSON for the claimed receipt_id.")
@click.option("--public-key", "public_keys", required=True, multiple=True,
              help="Operator public key (base64). Pass once per key.")
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human",
              help="Output format.")
def purge_verify(
    proof_path: str, registry_path: str, receipt_path: str,
    public_keys: tuple[str, ...], fmt: str,
) -> None:
    """Verify a Merkle inclusion proof against a NullificationRegistryRoot.

    Exits 0 if valid, 1 if any check fails.
    """
    proof = NullificationInclusionProof.model_validate_json(
        Path(proof_path).read_text(encoding="utf-8")
    )
    registry = NullificationRegistryRoot.model_validate_json(
        Path(registry_path).read_text(encoding="utf-8")
    )
    receipt = NullificationReceipt.model_validate_json(
        Path(receipt_path).read_text(encoding="utf-8")
    )

    passed, reason = verify_nullification_inclusion(
        proof, registry, receipt, list(public_keys)
    )

    if fmt == "json":
        click.echo(json.dumps({
            "passed": passed,
            "reason": reason,
            "receipt_id": receipt.receipt_id,
            "root_id": registry.root_id,
        }, indent=2))
    else:
        status = "[OK]" if passed else "[FAIL]"
        click.echo(f"{status} {reason}")
        click.echo(f"  Receipt   : {receipt.receipt_id}")
        click.echo(f"  Registry  : {registry.root_id}")
        click.echo(f"  Root      : {registry.merkle_root[:16]}...")

    if not passed:
        sys.exit(1)
