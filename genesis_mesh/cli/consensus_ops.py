"""CLI commands for Distributed Consensus Authorization.

trust consensus vote          -- validator casts a signed vote on a JustificationProof
trust consensus assemble      -- assemble K-of-N votes into a ConsensusProof
trust consensus issue-identity -- derive an EphemeralExecutionIdentity from consensus
trust consensus verify        -- verify a ConsensusProof
trust consensus verify-identity -- verify an EphemeralExecutionIdentity
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from ..crypto import load_private_key
from ..models.consensus import ConsensusProof, EphemeralExecutionIdentity
from ..models.justification import JustificationProof
from ..trust.consensus import (
    assemble_consensus_proof,
    cast_validator_vote,
    issue_ephemeral_identity,
    verify_consensus_proof,
    verify_ephemeral_identity,
)


@click.group("consensus")
def consensus() -> None:
    """Distributed consensus authorization — K-of-N validator threshold (opt-in)."""


# ---------------------------------------------------------------------------
# vote
# ---------------------------------------------------------------------------


@consensus.command("vote")
@click.option("--proof", "proof_path", required=True, type=click.Path(exists=True),
              help="JustificationProof JSON to vote on.")
@click.option("--validator", "validator_id", required=True,
              help="Sovereign ID of the validator casting this vote.")
@click.option("--approve/--reject", default=True,
              help="Cast an approval (default) or rejection.")
@click.option("--reason", default=None, help="Optional vote reason string.")
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True),
              help="Validator's signing key file (base64 Ed25519).")
@click.option("--output", "output_path", required=True, type=click.Path(),
              help="Output path for the signed ValidatorVote JSON.")
def consensus_vote(
    proof_path: str, validator_id: str, approve: bool,
    reason: str | None, key_path: str, output_path: str
) -> None:
    """Cast a signed validator vote on a JustificationProof."""
    proof = JustificationProof.model_validate_json(Path(proof_path).read_text(encoding="utf-8"))
    sk = load_private_key(key_path)

    vote = cast_validator_vote(proof, validator_id, approve, sk, reason=reason)
    Path(output_path).write_text(vote.model_dump_json(indent=2), encoding="utf-8")
    verdict = "APPROVE" if approve else "REJECT"
    click.echo(f"[OK] Vote {vote.vote_id} ({verdict}) written to {output_path}")


# ---------------------------------------------------------------------------
# assemble
# ---------------------------------------------------------------------------


@consensus.command("assemble")
@click.option("--proof", "proof_path", required=True, type=click.Path(exists=True),
              help="JustificationProof JSON being voted on.")
@click.option("--vote", "vote_paths", required=True, multiple=True, type=click.Path(exists=True),
              help="ValidatorVote JSON files (supply once per vote).")
@click.option("--threshold", required=True, type=int,
              help="K: number of approvals required.")
@click.option("--validators", required=True,
              help="Comma-separated list of named validator sovereign IDs.")
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True),
              help="Assembler's signing key file.")
@click.option("--assembler", "assembler_id", required=True,
              help="Assembler sovereign ID (key_id).")
@click.option("--valid-for", "valid_for", type=int, default=300,
              help="ConsensusProof validity in seconds (default 300).")
@click.option("--output", "output_path", required=True, type=click.Path(),
              help="Output path for the signed ConsensusProof JSON.")
def consensus_assemble(
    proof_path: str, vote_paths: tuple[str, ...], threshold: int,
    validators: str, key_path: str, assembler_id: str,
    valid_for: int, output_path: str,
) -> None:
    """Assemble K-of-N ValidatorVotes into a signed ConsensusProof."""
    from ..models.consensus import ValidatorVote

    proof = JustificationProof.model_validate_json(Path(proof_path).read_text(encoding="utf-8"))
    votes = [
        ValidatorVote.model_validate_json(Path(p).read_text(encoding="utf-8"))
        for p in vote_paths
    ]
    validator_ids = [v.strip() for v in validators.split(",") if v.strip()]
    sk = load_private_key(key_path)

    try:
        cp = assemble_consensus_proof(
            proof, votes, threshold, validator_ids, sk,
            issued_by=assembler_id, valid_for_seconds=valid_for,
        )
    except ValueError as exc:
        click.echo(f"[ERROR] {exc}", err=True)
        sys.exit(1)

    Path(output_path).write_text(cp.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] ConsensusProof {cp.consensus_id} written to {output_path}")
    click.echo(f"     Approvals : {len(cp.approvals())}/{threshold} (threshold met)")
    click.echo(f"     Expires   : {cp.expires_at.isoformat()}")


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@consensus.command("verify")
@click.option("--consensus", "cp_path", required=True, type=click.Path(exists=True),
              help="ConsensusProof JSON to verify.")
@click.option("--assembler-key", "assembler_keys", required=True, multiple=True,
              help="Base64-encoded Ed25519 public key(s) of the assembler.")
@click.option("--validator-key", "validator_key_pairs", multiple=True,
              help="Validator public keys as 'id:b64key' pairs.")
@click.option("--proof", "proof_path", default=None, type=click.Path(exists=True),
              help="Optional JustificationProof for cross-check.")
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human",
              help="Output format.")
def consensus_verify(
    cp_path: str, assembler_keys: tuple[str, ...],
    validator_key_pairs: tuple[str, ...], proof_path: str | None, fmt: str,
) -> None:
    """Verify a ConsensusProof signature and threshold."""
    cp = ConsensusProof.model_validate_json(Path(cp_path).read_text(encoding="utf-8"))

    val_keys: dict[str, str] = {}
    for pair in validator_key_pairs:
        parts = pair.split(":", 1)
        if len(parts) == 2:
            val_keys[parts[0]] = parts[1]

    jp = None
    if proof_path:
        jp = JustificationProof.model_validate_json(Path(proof_path).read_text(encoding="utf-8"))

    result = verify_consensus_proof(cp, val_keys, list(assembler_keys), justification_proof=jp)

    if fmt == "json":
        click.echo(json.dumps({"valid": result.valid, "reason": result.reason}, indent=2))
    else:
        status = "[OK]" if result.valid else "[FAIL]"
        click.echo(f"{status} {result.reason}")
        if result.valid:
            click.echo(f"     Consensus : {cp.consensus_id}")
            click.echo(f"     Approvals : {len(cp.approvals())}/{cp.required_threshold}")

    if not result.valid:
        sys.exit(1)


# ---------------------------------------------------------------------------
# issue-identity
# ---------------------------------------------------------------------------


@consensus.command("issue-identity")
@click.option("--consensus", "cp_path", required=True, type=click.Path(exists=True),
              help="ConsensusProof JSON.")
@click.option("--bearer", "bearer_id", required=True,
              help="Sovereign ID authorized to use this identity.")
@click.option("--cap", "caps", required=True, multiple=True,
              help="Allowed capability (supply once per cap).")
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True),
              help="Issuer's signing key file.")
@click.option("--issuer", "issuer_id", required=True, help="Issuer sovereign ID.")
@click.option("--valid-for", "valid_for", type=int, default=120,
              help="Identity validity in seconds (default 120).")
@click.option("--output", "output_path", required=True, type=click.Path(),
              help="Output path for the signed EphemeralExecutionIdentity JSON.")
def consensus_issue_identity(
    cp_path: str, bearer_id: str, caps: tuple[str, ...],
    key_path: str, issuer_id: str, valid_for: int, output_path: str,
) -> None:
    """Derive a short-lived EphemeralExecutionIdentity from a ConsensusProof."""
    cp = ConsensusProof.model_validate_json(Path(cp_path).read_text(encoding="utf-8"))
    sk = load_private_key(key_path)

    eid = issue_ephemeral_identity(
        cp, bearer_id, list(caps), sk, issued_by=issuer_id, valid_for_seconds=valid_for,
    )
    Path(output_path).write_text(eid.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] EphemeralExecutionIdentity {eid.identity_id} written to {output_path}")
    click.echo(f"     Bearer  : {bearer_id}")
    click.echo(f"     Expires : {eid.expires_at.isoformat()}")
    click.echo(f"     Caps    : {', '.join(caps)}")


# ---------------------------------------------------------------------------
# verify-identity
# ---------------------------------------------------------------------------


@consensus.command("verify-identity")
@click.option("--identity", "eid_path", required=True, type=click.Path(exists=True),
              help="EphemeralExecutionIdentity JSON.")
@click.option("--issuer-key", "issuer_keys", required=True, multiple=True,
              help="Base64-encoded Ed25519 public key(s) of the issuer.")
@click.option("--capability", required=True, help="Capability to check access for.")
@click.option("--bearer", "bearer_id", required=True, help="Expected bearer sovereign ID.")
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human",
              help="Output format.")
def consensus_verify_identity(
    eid_path: str, issuer_keys: tuple[str, ...],
    capability: str, bearer_id: str, fmt: str,
) -> None:
    """Verify an EphemeralExecutionIdentity for a specific capability and bearer."""
    eid = EphemeralExecutionIdentity.model_validate_json(
        Path(eid_path).read_text(encoding="utf-8")
    )

    result = verify_ephemeral_identity(
        eid, list(issuer_keys),
        requested_capability=capability,
        bearer_sovereign_id=bearer_id,
    )

    if fmt == "json":
        click.echo(json.dumps({"valid": result.valid, "reason": result.reason}, indent=2))
    else:
        status = "[OK]" if result.valid else "[FAIL]"
        click.echo(f"{status} {result.reason}")
        if result.valid:
            click.echo(f"     Identity  : {eid.identity_id}")
            click.echo(f"     Capability: {capability}")
            click.echo(f"     Bearer    : {bearer_id}")
            click.echo(f"     Expires   : {eid.expires_at.isoformat()}")

    if not result.valid:
        sys.exit(1)
