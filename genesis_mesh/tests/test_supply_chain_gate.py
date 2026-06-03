"""Tests for the supply-chain maintainer trust gate."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from click.testing import CliRunner

from genesis_mesh.cli.main import cli
from genesis_mesh.crypto import generate_keypair, sign_model
from genesis_mesh.models import (
    MembershipAttestation,
    RecognitionTreaty,
    RecognitionTreatyScope,
    SovereignRevocationFeed,
)
from genesis_mesh.trust import (
    DEFAULT_DELEGATED_ROLE,
    DEFAULT_MAINTAINER_ROLE,
    SUPPLY_CHAIN_MAINTAINER_PROFILE,
    verify_supply_chain_maintainer_gate,
)


PROJECT_ID = "pypi:demo-package"
REPOSITORY = "https://github.com/example/demo-package"


def test_supply_chain_gate_accepts_scoped_maintainer_attestation():
    """A treaty-backed maintainer attestation authorizes a release gate."""
    treaty_key = generate_keypair()
    issuer_key = generate_keypair()
    treaty = _treaty(subject_public_key=issuer_key.public_key_b64)
    treaty.signatures.append(sign_model(treaty, treaty_key.private_key, "project-b-na"))
    attestation = _attestation(issuer_key)

    result = verify_supply_chain_maintainer_gate(
        attestation=attestation,
        treaty=treaty,
        treaty_issuer_public_keys=[treaty_key.public_key_b64],
        project_id=PROJECT_ID,
        repository=REPOSITORY,
    )

    assert result.accepted is True
    assert result.reason == "accepted"
    assert result.exit_code == 0
    assert result.to_audit_dict()["trust_path"] == [
        {"from": "project-b", "to": "project-a", "treaty_id": "treaty-1"}
    ]


def test_supply_chain_gate_rejects_unknown_issuer():
    """An attestation from a non-recognized sovereign is denied."""
    treaty_key = generate_keypair()
    issuer_key = generate_keypair()
    treaty = _treaty(subject_public_key=issuer_key.public_key_b64)
    treaty.signatures.append(sign_model(treaty, treaty_key.private_key, "project-b-na"))
    attestation = _attestation(issuer_key, issuer_id="unknown-project")

    result = verify_supply_chain_maintainer_gate(
        attestation=attestation,
        treaty=treaty,
        treaty_issuer_public_keys=[treaty_key.public_key_b64],
        project_id=PROJECT_ID,
    )

    assert result.accepted is False
    assert result.reason == "treaty_wrong_subject"
    assert result.exit_code == 10


def test_supply_chain_gate_rejects_disallowed_role():
    """A valid signature is not enough when the role is outside gate scope."""
    treaty_key = generate_keypair()
    issuer_key = generate_keypair()
    treaty = _treaty(subject_public_key=issuer_key.public_key_b64)
    treaty.signatures.append(sign_model(treaty, treaty_key.private_key, "project-b-na"))
    attestation = _attestation(issuer_key, roles=["role:supply-chain:reviewer"])

    result = verify_supply_chain_maintainer_gate(
        attestation=attestation,
        treaty=treaty,
        treaty_issuer_public_keys=[treaty_key.public_key_b64],
        project_id=PROJECT_ID,
    )

    assert result.accepted is False
    assert result.reason == "role_not_allowed"


def test_supply_chain_gate_rejects_revoked_attestation_from_feed():
    """Imported revocation feed state blocks the same maintainer."""
    treaty_key = generate_keypair()
    issuer_key = generate_keypair()
    treaty = _treaty(subject_public_key=issuer_key.public_key_b64)
    treaty.signatures.append(sign_model(treaty, treaty_key.private_key, "project-b-na"))
    attestation = _attestation(issuer_key)
    feed = _revocation_feed(issuer_key, revoked_ids=[attestation.attestation_id])

    result = verify_supply_chain_maintainer_gate(
        attestation=attestation,
        treaty=treaty,
        treaty_issuer_public_keys=[treaty_key.public_key_b64],
        project_id=PROJECT_ID,
        revocation_feeds=[feed],
    )

    assert result.accepted is False
    assert result.reason == "attestation_locally_revoked"
    assert result.revocation_reason == "maintainer_key_rotated"


def test_supply_chain_gate_rejects_stale_revocation_feed():
    """A stale feed is a deny decision for a release gate."""
    treaty_key = generate_keypair()
    issuer_key = generate_keypair()
    treaty = _treaty(subject_public_key=issuer_key.public_key_b64)
    treaty.signatures.append(sign_model(treaty, treaty_key.private_key, "project-b-na"))
    attestation = _attestation(issuer_key)
    feed = _revocation_feed(issuer_key, sequence=1)

    result = verify_supply_chain_maintainer_gate(
        attestation=attestation,
        treaty=treaty,
        treaty_issuer_public_keys=[treaty_key.public_key_b64],
        project_id=PROJECT_ID,
        revocation_feeds=[feed],
        min_feed_sequence=1,
    )

    assert result.accepted is False
    assert result.reason == "revocation_feed_stale_sequence"


def test_supply_chain_cli_uses_stable_exit_codes_and_writes_bundle(tmp_path):
    """The CI verifier exits 0 for allow and 10 for deny."""
    treaty_key = generate_keypair()
    issuer_key = generate_keypair()
    treaty = _treaty(subject_public_key=issuer_key.public_key_b64)
    treaty.signatures.append(sign_model(treaty, treaty_key.private_key, "project-b-na"))
    attestation = _attestation(issuer_key)
    feed = _revocation_feed(issuer_key, revoked_ids=[attestation.attestation_id])
    attestation_path = _write_json(tmp_path / "attestation.json", attestation)
    treaty_path = _write_json(tmp_path / "treaty.json", treaty)
    feed_path = _write_json(tmp_path / "feed.json", feed)
    bundle_path = tmp_path / "proof-bundle.json"

    allow = CliRunner().invoke(
        cli,
        [
            "supply-chain",
            "verify",
            "--attestation",
            str(attestation_path),
            "--treaty",
            str(treaty_path),
            "--treaty-issuer-public-key",
            treaty_key.public_key_b64,
            "--project-id",
            PROJECT_ID,
            "--repository",
            REPOSITORY,
            "--proof-bundle",
            str(bundle_path),
        ],
    )

    assert allow.exit_code == 0, allow.output
    assert "ALLOW supply-chain trust gate" in allow.output
    assert json.loads(bundle_path.read_text(encoding="utf-8"))["accepted"] is True

    deny = CliRunner().invoke(
        cli,
        [
            "supply-chain",
            "verify",
            "--attestation",
            str(attestation_path),
            "--treaty",
            str(treaty_path),
            "--treaty-issuer-public-key",
            treaty_key.public_key_b64,
            "--project-id",
            PROJECT_ID,
            "--revocation-feed",
            str(feed_path),
            "--format",
            "json",
        ],
    )

    assert deny.exit_code == 10, deny.output
    payload = json.loads(deny.output)
    assert payload["accepted"] is False
    assert payload["reason"] == "attestation_locally_revoked"
    assert "signatures" not in deny.output


def _attestation(
    issuer_key,
    *,
    issuer_id: str = "project-a",
    roles: list[str] | None = None,
) -> MembershipAttestation:
    now = datetime.now(timezone.utc)
    attestation = MembershipAttestation(
        attestation_id="attestation-1",
        issuer_sovereign_id=issuer_id,
        subject_id="alice",
        subject_public_key="alice-public-key",
        roles=roles or [DEFAULT_MAINTAINER_ROLE],
        status="active",
        issued_at=now,
        valid_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        issued_by="project-a-na",
        claims={
            "profile": SUPPLY_CHAIN_MAINTAINER_PROFILE,
            "project_id": PROJECT_ID,
            "repository": REPOSITORY,
            "delegated_role": DEFAULT_DELEGATED_ROLE,
        },
    )
    attestation.signatures.append(sign_model(attestation, issuer_key.private_key, "project-a-na"))
    return attestation


def _treaty(subject_public_key: str) -> RecognitionTreaty:
    now = datetime.now(timezone.utc)
    return RecognitionTreaty(
        treaty_id="treaty-1",
        issuer_sovereign_id="project-b",
        subject_sovereign_id="project-a",
        subject_public_keys=[subject_public_key],
        scope=RecognitionTreatyScope(
            allowed_roles=[DEFAULT_MAINTAINER_ROLE],
            accepted_statuses=["active"],
            claims={
                "profile": SUPPLY_CHAIN_MAINTAINER_PROFILE,
                "project_id": PROJECT_ID,
            },
        ),
        status="active",
        issued_at=now,
        valid_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        issued_by="project-b-na",
    )


def _revocation_feed(
    issuer_key,
    *,
    revoked_ids: list[str] | None = None,
    sequence: int = 2,
) -> SovereignRevocationFeed:
    feed = SovereignRevocationFeed(
        feed_id="feed-1",
        issuer_sovereign_id="project-a",
        sequence=sequence,
        issued_at=datetime.now(timezone.utc),
        revoked_attestation_ids=revoked_ids or ["other-attestation"],
        revocation_reasons={
            attestation_id: "maintainer_key_rotated"
            for attestation_id in (revoked_ids or ["other-attestation"])
        },
        issued_by="project-a-na",
    )
    feed.signatures.append(sign_model(feed, issuer_key.private_key, "project-a-na"))
    return feed


def _write_json(path: Path, model) -> Path:
    path.write_text(json.dumps(model.model_dump(mode="json"), indent=2), encoding="utf-8")
    return path
