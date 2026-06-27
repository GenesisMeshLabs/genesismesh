"""Interop bridge CLI commands (trust interop subgroup)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from ..crypto import load_private_key
from ..interop import spiffe, w3c_vc, jose as jose_bridge
from ..models.agreement import AgreementRecord
from ..models.context import BoundaryDecision
from ..models.evidence import TrustEvidence


# ---------------------------------------------------------------------------
# interop group
# ---------------------------------------------------------------------------


@click.group()
def interop() -> None:
    """Interop bridges — convert GM records to SPIFFE, W3C VC, and JWT formats."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(obj: Any, output: str) -> Path:
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# trust interop to-spiffe
# ---------------------------------------------------------------------------


@interop.command("to-spiffe")
@click.option("--agreement", "agreement_path", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="AgreementRecord JSON to convert.")
@click.option("--output", required=True,
              type=click.Path(dir_okay=False),
              help="Output path for the SVID-like JSON.")
def interop_to_spiffe(agreement_path: str, output: str) -> None:
    """Convert an AgreementRecord to a SPIFFE SVID-like JSON.

    The output is not a self-contained X.509 or JWT SVID.  It carries the GM
    signatures as extensions for verification against GM public keys.

    Example:

    \b
        genesis-mesh trust interop to-spiffe \\
            --agreement agreement.json \\
            --output svid.json
    """
    try:
        record = AgreementRecord.model_validate_json(
            Path(agreement_path).read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise click.ClickException(f"Cannot load agreement {agreement_path!r}: {exc}") from exc

    svid = spiffe.agreement_to_svid(record)
    out = _write_json(svid, output)
    click.echo(f"SPIFFE ID : {svid['spiffe_id']}")
    click.echo(f"Parties   : {svid['parties']['offerer']} ↔ {svid['parties']['responder']}")
    click.echo(f"Caps      : {', '.join(svid['capabilities'])}")
    click.echo(f"Output    : {out}")


# ---------------------------------------------------------------------------
# trust interop to-vc
# ---------------------------------------------------------------------------


@interop.command("to-vc")
@click.option("--agreement", "agreement_path", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help="AgreementRecord JSON to convert.")
@click.option("--evidence", "evidence_path", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help="TrustEvidence JSON to convert.")
@click.option("--output", required=True,
              type=click.Path(dir_okay=False),
              help="Output path for the VC JSON.")
def interop_to_vc(
    agreement_path: str | None,
    evidence_path: str | None,
    output: str,
) -> None:
    """Convert an AgreementRecord or TrustEvidence to a W3C Verifiable Credential.

    Pass either --agreement or --evidence (not both).

    Example:

    \b
        genesis-mesh trust interop to-vc \\
            --agreement agreement.json \\
            --output vc.json
    """
    if agreement_path and evidence_path:
        raise click.ClickException("Pass --agreement or --evidence, not both.")
    if not agreement_path and not evidence_path:
        raise click.ClickException("Pass --agreement or --evidence.")

    if agreement_path is not None:
        try:
            record = AgreementRecord.model_validate_json(
                Path(agreement_path).read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise click.ClickException(f"Cannot load agreement: {exc}") from exc
        vc = w3c_vc.agreement_to_vc(record)
        subject = vc["credentialSubject"]["id"]
    else:
        assert evidence_path is not None
        try:
            evidence = TrustEvidence.model_validate_json(
                Path(evidence_path).read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise click.ClickException(f"Cannot load evidence: {exc}") from exc
        vc = w3c_vc.trust_evidence_to_vc(evidence)
        subject = vc["credentialSubject"]["id"]

    out = _write_json(vc, output)
    click.echo(f"VC ID    : {vc['id']}")
    click.echo(f"Issuer   : {vc['issuer']}")
    click.echo(f"Subject  : {subject}")
    click.echo(f"Output   : {out}")


# ---------------------------------------------------------------------------
# trust interop to-jwt
# ---------------------------------------------------------------------------


@interop.command("to-jwt")
@click.option("--decision", "decision_path", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="BoundaryDecision JSON to encode as JWT.")
@click.option("--signing-key", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Ed25519 private key for JWT signature.")
@click.option("--key-id", default="gm-bridge", help="JWT key ID (kid header).")
@click.option("--output", required=True,
              type=click.Path(dir_okay=False),
              help="Output path for the JWT string.")
def interop_to_jwt(
    decision_path: str,
    signing_key: str,
    key_id: str,
    output: str,
) -> None:
    """Convert a BoundaryDecision to a signed EdDSA JWT.

    The JWT can be consumed by any REST API that understands OKP/EdDSA JWTs.
    GM-specific fields are in the 'gm:' claim namespace.

    Example:

    \b
        genesis-mesh trust interop to-jwt \\
            --decision decision.json \\
            --signing-key keys/bridge.key --key-id bridge-2026 \\
            --output decision.jwt
    """
    try:
        decision = BoundaryDecision.model_validate_json(
            Path(decision_path).read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise click.ClickException(f"Cannot load decision {decision_path!r}: {exc}") from exc

    private_key = load_private_key(signing_key)
    token = jose_bridge.decision_to_jwt(decision, private_key, key_id=key_id)

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(token, encoding="utf-8")

    header_count = token.count(".")
    click.echo(f"JWT      : {token[:40]}... ({len(token)} chars)")
    click.echo(f"Decision : {decision.decision_id}")
    click.echo(f"Auth     : {'yes' if decision.authorized else 'no'}")
    click.echo(f"Output   : {out}")
