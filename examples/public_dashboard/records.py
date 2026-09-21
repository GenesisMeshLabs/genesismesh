"""Strict public record schema and independent cryptographic verification."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from genesis_mesh.crypto import verify_model_signature
from genesis_mesh.models import GenesisBlock, RecognitionTreaty, SovereignRevocationFeed, MembershipAttestation
from genesis_mesh.models.genesis import Signature


class PublicRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TreatyRecord(PublicRecord):
    treaty: RecognitionTreaty
    expected_active: bool
    retired: bool = False


class ImportEvent(PublicRecord):
    at: datetime
    issuer: str = Field(pattern=r"^gm-demo-[a-z0-9-]+$")
    outcome: Literal["success", "failed", "warning"]


class Canary(PublicRecord):
    completed_at: datetime | None = None
    status: Literal["not_observed", "verified", "failed"] = "not_observed"
    issuer: Literal["gm-demo-edge-na"] = "gm-demo-edge-na"
    attestation: MembershipAttestation | None = None
    treaty_id: str | None = None


class Snapshot(PublicRecord):
    schema_version: Literal[1] = 1
    updated_at: datetime
    genesis: GenesisBlock
    authorities: dict[str, GenesisBlock]
    treaties: list[TreatyRecord]
    feeds: dict[str, SovereignRevocationFeed]
    imports: dict[str, datetime]
    events: list[ImportEvent] = Field(default_factory=list)
    canary: Canary = Field(default_factory=Canary)
    signatures: list[Signature] = Field(default_factory=list)

    def to_canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json", exclude={"signatures"}), sort_keys=True, separators=(",", ":"))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def signed(model, public_key: str) -> bool:
    return bool(model.signatures) and all(
        verify_model_signature(model, sig, public_key) for sig in model.signatures
    )


def validate_snapshot(snapshot: Snapshot, root_key: str) -> None:
    """Fail closed on unexpected identities, unsigned records or arbitrary metadata.

    Do not redact signed documents: reject an unsafe dataset in its entirety.
    The pinned root must come from a separately trusted source.
    """
    import re

    genesis = snapshot.genesis
    if genesis.root_public_key != root_key or not signed(genesis, root_key):
        raise ValueError("untrusted_genesis")
    if not signed(snapshot, genesis.network_authority.public_key):
        raise ValueError("invalid_snapshot_signature")
    if any(sig.key_id != "demo-na" for sig in snapshot.signatures):
        raise ValueError("unexpected_snapshot_key_id")
    if set(snapshot.imports) - set(snapshot.authorities):
        raise ValueError("unexpected_import_issuer")
    for name, authority in snapshot.authorities.items():
        if not re.fullmatch(r"gm-demo-[a-z0-9-]+", name) or authority.network_name != name:
            raise ValueError("non_demo_identity")
        if authority.bootstrap_anchors or authority.policy_manifest.url is not None:
            raise ValueError("unexpected_public_metadata")
        if authority.network_version != "v0.1" or authority.allowed_crypto_suites != ["ed25519", "x25519"] or authority.allowed_transports != ["quic", "wireguard"]:
            raise ValueError("unexpected_protocol_metadata")
        if authority.policy_manifest.hash != "sha256:" + digest("read-only public reference instance"):
            raise ValueError("unexpected_policy_metadata")
        if not signed(authority, authority.root_public_key):
            raise ValueError("invalid_authority_signature")
        for sig in authority.signatures:
            if sig.key_id != "demo-root":
                raise ValueError("unexpected_key_id")
    if genesis != snapshot.authorities.get(genesis.network_name):
        raise ValueError("genesis_mismatch")
    for record in snapshot.treaties:
        treaty = record.treaty
        if treaty.issuer_sovereign_id != genesis.network_name:
            raise ValueError("unexpected_issuer")
        authority = snapshot.authorities[treaty.subject_sovereign_id]
        if treaty.subject_public_keys != [authority.network_authority.public_key]:
            raise ValueError("subject_key_mismatch")
        if treaty.metadata or treaty.scope.model_dump().get("claims"):
            raise ValueError("unexpected_treaty_metadata")
        if treaty.scope.allowed_roles != ["role:demo"] or treaty.issued_by != "demo-na":
            raise ValueError("unexpected_scope")
        if not re.fullmatch(r"[0-9a-f-]{36}", treaty.treaty_id):
            raise ValueError("unexpected_record_id")
        if any(sig.key_id != "demo-na" for sig in treaty.signatures):
            raise ValueError("unexpected_key_id")
        if not signed(treaty, genesis.network_authority.public_key):
            raise ValueError("invalid_treaty_signature")
    for issuer, feed in snapshot.feeds.items():
        authority = snapshot.authorities[issuer]
        if feed.issuer_sovereign_id != issuer or feed.issued_by != "demo-na":
            raise ValueError("unexpected_feed_issuer")
        if any(sig.key_id != "demo-na" for sig in feed.signatures):
            raise ValueError("unexpected_key_id")
        if not re.fullmatch(r"[0-9a-f-]{36}", feed.feed_id):
            raise ValueError("unexpected_feed_id")
        if any(not re.fullmatch(r"[0-9a-f-]{36}", item) for item in feed.revoked_attestation_ids):
            raise ValueError("unexpected_revocation_id")
        if any(reason != "demo-revocation" for reason in feed.revocation_reasons.values()):
            raise ValueError("unexpected_revocation_reason")
        if not signed(feed, authority.network_authority.public_key):
            raise ValueError("invalid_feed_signature")
    canary = snapshot.canary
    if canary.status == "verified":
        from genesis_mesh.trust import verify_attestation_with_treaty

        attestation = canary.attestation
        if attestation is None or canary.completed_at is None:
            raise ValueError("missing_canary_evidence")
        if attestation.subject_id != "gm-demo-canary" or attestation.issuer_sovereign_id != canary.issuer:
            raise ValueError("unexpected_canary_identity")
        if attestation.claims or attestation.roles != ["role:demo"] or attestation.issued_by != "demo-na":
            raise ValueError("unexpected_canary_metadata")
        if not re.fullmatch(r"[0-9a-f-]{36}", attestation.attestation_id) or attestation.subject_public_key is not None:
            raise ValueError("unexpected_canary_record")
        if any(sig.key_id != "demo-na" for sig in attestation.signatures):
            raise ValueError("unexpected_canary_key")
        treaty = next(r.treaty for r in snapshot.treaties if r.treaty.treaty_id == canary.treaty_id)
        keys = [genesis.network_authority.public_key]
        pre = verify_attestation_with_treaty(attestation, treaty, keys, current_time=canary.completed_at)
        post = verify_attestation_with_treaty(attestation, treaty, keys, current_time=canary.completed_at,
            revoked_attestation_ids=set(snapshot.feeds[canary.issuer].revoked_attestation_ids))
        if not pre.accepted or post.reason != "attestation_locally_revoked":
            raise ValueError("invalid_canary_evidence")


def freshness(issued_at: datetime | None, now: datetime) -> str:
    if issued_at is None or issued_at > now:
        return "missing"
    hours = (now - issued_at).total_seconds() / 3600
    return "fresh" if hours < 24 else "warning" if hours <= 72 else "stale"


def import_feed(snapshot: Snapshot, feed: SovereignRevocationFeed, now: datetime) -> None:
    """Accept a newer signed heartbeat without incrementing the content sequence."""
    issuer = feed.issuer_sovereign_id
    authority = snapshot.authorities[issuer]
    if not signed(feed, authority.network_authority.public_key):
        raise ValueError("invalid_signature")
    if feed.issued_at > now or freshness(feed.issued_at, now) in {"stale", "missing"}:
        raise ValueError("invalid_feed_time")
    old = snapshot.feeds.get(issuer)
    if old:
        old_content = (old.revoked_attestation_ids, old.revocation_reasons)
        new_content = (feed.revoked_attestation_ids, feed.revocation_reasons)
        if feed.sequence < old.sequence or feed.issued_at <= old.issued_at:
            raise ValueError("replayed_feed")
        if feed.sequence == old.sequence and old_content != new_content:
            raise ValueError("sequence_content_mismatch")
        if not set(old.revoked_attestation_ids).issubset(feed.revoked_attestation_ids):
            raise ValueError("revocation_rollback")
        if feed.sequence > old.sequence and old_content == new_content:
            raise ValueError("unchanged_content_sequence")
    snapshot.feeds[issuer] = feed.model_copy(deep=True)
    snapshot.imports[issuer] = now


def current_issuers(snapshot: Snapshot) -> set[str]:
    return {r.treaty.subject_sovereign_id for r in snapshot.treaties
            if r.expected_active and not r.retired and r.treaty.status == "active"}


def sensitive_authorization_allowed(snapshot: Snapshot, issuer: str, now: datetime) -> bool:
    """Local reference policy: missing/stale feed or expired expected treaty denies."""
    if issuer not in current_issuers(snapshot):
        return False
    active = any(r.expected_active and not r.retired and r.treaty.status == "active"
                 and r.treaty.subject_sovereign_id == issuer
                 and r.treaty.valid_from <= now < r.treaty.expires_at for r in snapshot.treaties)
    feed = snapshot.feeds.get(issuer)
    return active and feed is not None and freshness(feed.issued_at, now) in {"fresh", "warning"}
