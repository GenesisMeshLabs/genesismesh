"""CLI commands for Selective Disclosure Capability Proofs.

trust disclose commit   -- build + sign a Merkle commitment over agreement caps
trust disclose prove    -- produce a membership proof for one capability
trust disclose verify   -- verify the proof against a commitment
trust disclose nullify  -- issue a single-use nullifier for a proof
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from ..models.agreement import AgreementRecord
from ..models.selective_disclosure import CapabilityCommitment, CapabilityMembershipProof
from ..trust.selective_disclosure import (
    commit_capabilities,
    issue_nullifier,
    prove_capability_membership,
    verify_capability_proof,
)
from ..crypto import load_private_key


@click.group("disclose")
def disclose() -> None:
    """Selective disclosure capability proofs (Merkle-based membership proofs)."""


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------


@disclose.command("commit")
@click.option("--agreement", "agreement_path", required=True, type=click.Path(exists=True),
              help="Path to AgreementRecord JSON.")
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True),
              help="Base64-encoded Ed25519 signing key file.")
@click.option("--output", "output_path", required=True, type=click.Path(),
              help="Path to write the signed CapabilityCommitment JSON.")
@click.option("--issuer", "issuer", required=True,
              help="Sovereign ID of the commitment issuer.")
def disclose_commit(
    agreement_path: str, key_path: str, output_path: str, issuer: str
) -> None:
    """Build and sign a Merkle commitment over an agreement's capabilities."""
    agreement = AgreementRecord.model_validate_json(Path(agreement_path).read_text(encoding="utf-8"))
    signing_key = load_private_key(key_path)

    commitment = commit_capabilities(
        capabilities=list(agreement.agreed_terms.capabilities),
        agreement=agreement,
        signing_key=signing_key,
        issued_by=issuer,
    )

    Path(output_path).write_text(commitment.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] Commitment {commitment.commitment_id} written to {output_path}")
    click.echo(f"     Merkle root : {commitment.merkle_root[:16]}...")
    click.echo(f"     Capabilities: {commitment.capability_count}")


# ---------------------------------------------------------------------------
# prove
# ---------------------------------------------------------------------------


@disclose.command("prove")
@click.option("--capability", required=True, help="The single capability to prove membership for.")
@click.option("--agreement", "agreement_path", required=True, type=click.Path(exists=True),
              help="Path to AgreementRecord JSON (full capability set, kept local).")
@click.option("--commitment", "commitment_path", required=True, type=click.Path(exists=True),
              help="Path to the signed CapabilityCommitment JSON.")
@click.option("--prover", "prover", required=True,
              help="Sovereign ID of the prover.")
@click.option("--output", "output_path", required=True, type=click.Path(),
              help="Path to write the CapabilityMembershipProof JSON.")
def disclose_prove(
    capability: str, agreement_path: str, commitment_path: str,
    prover: str, output_path: str
) -> None:
    """Generate a Merkle membership proof for one capability."""
    agreement = AgreementRecord.model_validate_json(Path(agreement_path).read_text(encoding="utf-8"))
    commitment = CapabilityCommitment.model_validate_json(
        Path(commitment_path).read_text(encoding="utf-8")
    )
    capabilities = list(agreement.agreed_terms.capabilities)

    try:
        proof = prove_capability_membership(
            capability=capability,
            capabilities=capabilities,
            commitment=commitment,
            prover_sovereign_id=prover,
        )
    except ValueError as exc:
        click.echo(f"[ERROR] {exc}", err=True)
        sys.exit(2)

    Path(output_path).write_text(proof.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] Proof {proof.proof_id} written to {output_path}")
    click.echo(f"     Disclosed: {capability}")
    click.echo(f"     Path nodes: {len(proof.merkle_path)}")


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@disclose.command("verify")
@click.option("--proof", "proof_path", required=True, type=click.Path(exists=True),
              help="Path to CapabilityMembershipProof JSON.")
@click.option("--commitment", "commitment_path", required=True, type=click.Path(exists=True),
              help="Path to CapabilityCommitment JSON.")
@click.option("--verify-key", "verify_key", required=True, multiple=True,
              help="Base64-encoded Ed25519 public key(s) of the commitment issuer.")
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human",
              help="Output format.")
def disclose_verify(
    proof_path: str, commitment_path: str, verify_key: tuple[str, ...], fmt: str
) -> None:
    """Verify a CapabilityMembershipProof against its commitment."""
    proof = CapabilityMembershipProof.model_validate_json(
        Path(proof_path).read_text(encoding="utf-8")
    )
    commitment = CapabilityCommitment.model_validate_json(
        Path(commitment_path).read_text(encoding="utf-8")
    )

    result = verify_capability_proof(proof, commitment, list(verify_key))

    if fmt == "json":
        click.echo(json.dumps({"valid": result.valid, "reason": result.reason}, indent=2))
    else:
        status = "[OK]" if result.valid else "[FAIL]"
        click.echo(f"{status} {result.reason}")
        if result.valid:
            click.echo(f"     Commitment: {result.commitment_id}")
            click.echo(f"     Disclosed : {proof.revealed_capability}")

    if not result.valid:
        sys.exit(1)


# ---------------------------------------------------------------------------
# nullify
# ---------------------------------------------------------------------------


@disclose.command("nullify")
@click.option("--proof", "proof_path", required=True, type=click.Path(exists=True),
              help="Path to CapabilityMembershipProof JSON.")
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True),
              help="Base64-encoded Ed25519 signing key file.")
@click.option("--prover", "prover", required=True,
              help="Sovereign ID of the nullifier issuer.")
@click.option("--valid-for", "valid_for", type=int, default=60,
              help="Nullifier validity in seconds (default 60).")
@click.option("--output", "output_path", required=True, type=click.Path(),
              help="Path to write the CapabilityNullifier JSON.")
def disclose_nullify(
    proof_path: str, key_path: str, prover: str, valid_for: int, output_path: str
) -> None:
    """Issue a single-use nullifier for a capability proof."""
    from ..models.selective_disclosure import CapabilityMembershipProof

    proof = CapabilityMembershipProof.model_validate_json(
        Path(proof_path).read_text(encoding="utf-8")
    )
    signing_key = load_private_key(key_path)

    nullifier = issue_nullifier(proof, signing_key, issued_by=prover, valid_for_seconds=valid_for)

    Path(output_path).write_text(nullifier.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] Nullifier {nullifier.nullifier_id} written to {output_path}")
    click.echo(f"     Expires: {nullifier.expires_at.isoformat()}")
