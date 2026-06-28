"""CLI commands for Data Usage Attestation Layer.

trust data policy  -- create a signed DataLicensePolicy
trust data intent  -- create a signed DataAccessIntent
trust data record  -- create a signed DataAccessRecord
trust data verify  -- verify intent against policy
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
import nacl.signing

from ..crypto import load_private_key, sign_model
from ..models.data_usage import (
    DataAccessIntent,
    DataAccessRecord,
    DataLicensePolicy,
    DataSourceDescriptor,
)
from ..trust.data_usage import (
    create_data_access_intent,
    verify_data_access_intent,
)


@click.group("data")
def data() -> None:
    """Data usage attestation — license policies, access intents, and records."""


def _parse_source(s: str) -> DataSourceDescriptor:
    """Parse 'source_id:source_type:owner_id[:tag1,tag2]' into a descriptor."""
    parts = s.split(":")
    if len(parts) < 3:  # noqa: PLR2004
        raise click.BadParameter(
            f"source must be 'id:type:owner[:tags]', got: {s!r}"
        )
    tags = parts[3].split(",") if len(parts) > 3 else []
    return DataSourceDescriptor(
        source_id=parts[0],
        source_type=parts[1],
        owner_sovereign_id=parts[2],
        classification_tags=[t for t in tags if t],
    )


# ---------------------------------------------------------------------------
# policy
# ---------------------------------------------------------------------------


@data.command("policy")
@click.option("--licensor-sovereign", "licensor", required=True)
@click.option("--licensee-sovereign", "licensee", required=True)
@click.option("--allow-source", "allow_sources", multiple=True)
@click.option("--allow-access", "allow_access", multiple=True)
@click.option("--prohibit-tag", "prohibit_tags", multiple=True)
@click.option("--max-volume-bytes", "max_vol", type=int, default=None)
@click.option("--valid-for-hours", "valid_hours", type=int, default=24)
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True))
@click.option("--output", "output_path", required=True, type=click.Path())
def policy_cmd(
    licensor: str, licensee: str,
    allow_sources: tuple[str, ...], allow_access: tuple[str, ...],
    prohibit_tags: tuple[str, ...], max_vol: int | None,
    valid_hours: int, key_path: str, output_path: str,
) -> None:
    """Create a signed DataLicensePolicy."""
    sk = load_private_key(key_path)
    now = datetime.now(timezone.utc)
    p = DataLicensePolicy(
        licensor_sovereign_id=licensor,
        licensee_sovereign_id=licensee,
        allowed_source_ids=list(allow_sources),
        allowed_access_types=list(allow_access),
        prohibited_classification_tags=list(prohibit_tags),
        max_volume_bytes_per_session=max_vol,
        valid_from=now,
        valid_until=now + timedelta(hours=valid_hours),
    )
    sig = sign_model(p, sk, licensor)
    p = p.model_copy(update={"signature": sig})
    Path(output_path).write_text(p.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] DataLicensePolicy {p.policy_id}")
    click.echo(f"     Licensor : {licensor}")
    click.echo(f"     Licensee : {licensee}")
    click.echo(f"     Sources  : {list(allow_sources) or '(none)'}")
    click.echo(f"     Output   : {output_path}")


# ---------------------------------------------------------------------------
# intent
# ---------------------------------------------------------------------------


@data.command("intent")
@click.option("--agent-sovereign", "agent_id", required=True)
@click.option("--decision-id", "decision_id", required=True)
@click.option("--source", "sources", multiple=True, required=True,
              help="Source as 'id:type:owner[:tag1,tag2]'")
@click.option("--access-type", "access_types", multiple=True, required=True)
@click.option("--volume-bytes", "vol", type=int, default=None)
@click.option("--valid-for-seconds", "ttl", type=int, default=300)
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True))
@click.option("--output", "output_path", required=True, type=click.Path())
def intent_cmd(
    agent_id: str, decision_id: str, sources: tuple[str, ...],
    access_types: tuple[str, ...], vol: int | None,
    ttl: int, key_path: str, output_path: str,
) -> None:
    """Create a signed DataAccessIntent."""
    sk = load_private_key(key_path)
    descriptors = [_parse_source(s) for s in sources]
    intent = create_data_access_intent(
        agent_id, decision_id, descriptors, list(access_types),
        sk, estimated_volume_bytes=vol, valid_for_seconds=ttl,
    )
    Path(output_path).write_text(intent.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] DataAccessIntent {intent.intent_id}")
    click.echo(f"     Agent    : {agent_id}")
    click.echo(f"     Sources  : {[s.source_id for s in descriptors]}")
    click.echo(f"     Output   : {output_path}")


# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------


@data.command("record")
@click.option("--intent", "intent_path", required=True, type=click.Path(exists=True))
@click.option("--source", "sources", multiple=True, required=True,
              help="Source as 'id:type:owner[:tag1,tag2]'")
@click.option("--access-type", "access_types", multiple=True, required=True)
@click.option("--volume-bytes", "vol", type=int, default=None)
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True))
@click.option("--output", "output_path", required=True, type=click.Path())
def record_cmd(
    intent_path: str, sources: tuple[str, ...], access_types: tuple[str, ...],
    vol: int | None, key_path: str, output_path: str,
) -> None:
    """Create a signed DataAccessRecord from a completed access."""
    sk = load_private_key(key_path)
    intent = DataAccessIntent.model_validate_json(
        Path(intent_path).read_text(encoding="utf-8")
    )
    descriptors = [_parse_source(s) for s in sources]
    now = datetime.now(timezone.utc)
    rec = DataAccessRecord(
        intent_id=intent.intent_id,
        agent_sovereign_id=intent.agent_sovereign_id,
        decision_id=intent.decision_id,
        accessed_sources=descriptors,
        access_types_used=list(access_types),
        actual_volume_bytes=vol,
        accessed_at=now,
        completed_at=now,
    )
    sig = sign_model(rec, sk, intent.agent_sovereign_id)
    rec = rec.model_copy(update={"signature": sig})
    Path(output_path).write_text(rec.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"[OK] DataAccessRecord {rec.record_id}")
    click.echo(f"     Intent   : {intent.intent_id}")
    click.echo(f"     Sources  : {[s.source_id for s in descriptors]}")
    click.echo(f"     Output   : {output_path}")


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@data.command("verify")
@click.option("--intent", "intent_path", required=True, type=click.Path(exists=True))
@click.option("--policy", "policy_path", required=True, type=click.Path(exists=True))
@click.option("--public-key", "pub_keys", multiple=True,
              help="Agent Ed25519 public key (base64). Pass once per key.")
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human")
def verify_cmd(
    intent_path: str, policy_path: str,
    pub_keys: tuple[str, ...], fmt: str,
) -> None:
    """Verify a DataAccessIntent against a DataLicensePolicy."""
    intent = DataAccessIntent.model_validate_json(
        Path(intent_path).read_text(encoding="utf-8")
    )
    policy = DataLicensePolicy.model_validate_json(
        Path(policy_path).read_text(encoding="utf-8")
    )
    ok, reason, violations = verify_data_access_intent(intent, policy, list(pub_keys))
    if fmt == "json":
        click.echo(json.dumps({
            "compliant": ok,
            "reason": reason,
            "violations": [v.violation_type for v in violations],
        }, indent=2))
    else:
        if ok:
            click.echo(f"[OK] compliant — {intent.intent_id}")
        else:
            click.echo(f"[FAIL] {reason} — {intent.intent_id}", err=True)
            for v in violations:
                click.echo(f"  - {v.violation_type}: {v.detail}", err=True)
    if not ok:
        raise SystemExit(1)
