"""Local-only signed publication, hourly HTTP import, alerts and daily canary."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import uuid

import requests

from genesis_mesh.crypto import load_private_key, sign_model
from genesis_mesh.models import MembershipAttestation, SovereignRevocationFeed
from genesis_mesh.trust import verify_attestation_with_treaty
from .records import Canary, ImportEvent, current_issuers, freshness, import_feed, sensitive_authorization_allowed
from .store import read_snapshot, write_snapshot

logger = logging.getLogger(__name__)


def publish(path: Path, model) -> None:
    pending = path.with_suffix(".tmp")
    pending.write_text(model.model_dump_json(), encoding="utf-8")
    pending.replace(path)


def fetch(url: str, model):
    response = requests.get(url, timeout=10, allow_redirects=False)
    response.raise_for_status()
    if len(response.content) > 2_000_000:
        raise ValueError("oversized_feed")
    return model.model_validate_json(response.content)


def refresh(root: Path, origin: str) -> bool:
    if origin not in {"http://127.0.0.1:18444", "http://localhost:18444"}:
        raise ValueError("The reference feed publisher must be loopback-only")
    snapshot = read_snapshot(root / "public.db", (root / "root.pub").read_text().strip())
    now = datetime.now(timezone.utc)
    public = root / "published"
    public.mkdir(exist_ok=True)
    successful = True
    issuers = current_issuers(snapshot) | {snapshot.genesis.network_name}
    for issuer in sorted(issuers):
        old = snapshot.feeds.get(issuer)
        if old is None or freshness(old.issued_at, now) != "fresh":
            logger.warning("Feed requires attention: %s", issuer)
            snapshot.events.append(ImportEvent(at=now, issuer=issuer, outcome="warning"))
        try:
            key = load_private_key(str(root / "keys" / (issuer + ".key")))
            heartbeat = SovereignRevocationFeed(feed_id=str(uuid.uuid4()), issuer_sovereign_id=issuer,
                sequence=old.sequence if old else 0, issued_at=now,
                revoked_attestation_ids=old.revoked_attestation_ids if old else [],
                revocation_reasons=old.revocation_reasons if old else {}, issued_by="demo-na")
            heartbeat.signatures.append(sign_model(heartbeat, key, "demo-na"))
            publish(public / (issuer + ".json"), heartbeat)
            received = fetch(origin + "/" + issuer + ".json", SovereignRevocationFeed)
            if received.issuer_sovereign_id != issuer:
                raise ValueError("wrong_issuer")
            import_feed(snapshot, received, datetime.now(timezone.utc))
            snapshot.events.append(ImportEvent(at=now, issuer=issuer, outcome="success"))
        except (OSError, ValueError, requests.RequestException):
            successful = False
            logger.error("Feed publication/import failed: %s", issuer)
            snapshot.events.append(ImportEvent(at=now, issuer=issuer, outcome="failed"))

    if snapshot.canary.completed_at is None or now - snapshot.canary.completed_at >= timedelta(hours=24):
        issuer = "gm-demo-edge-na"
        try:
            key = load_private_key(str(root / "keys" / (issuer + ".key")))
            attestation = MembershipAttestation(attestation_id=str(uuid.uuid4()), issuer_sovereign_id=issuer,
                subject_id="gm-demo-canary", roles=["role:demo"], issued_at=now, valid_from=now,
                expires_at=now + timedelta(hours=1), issued_by="demo-na")
            attestation.signatures.append(sign_model(attestation, key, "demo-na"))
            publish(public / "canary.json", attestation)
            received_attestation = fetch(origin + "/canary.json", MembershipAttestation)
            treaty = next(r.treaty for r in snapshot.treaties if r.treaty.subject_sovereign_id == issuer and r.expected_active and not r.retired)
            main_key = snapshot.genesis.network_authority.public_key
            pre = verify_attestation_with_treaty(received_attestation, treaty, [main_key],
                revoked_attestation_ids=set(snapshot.feeds[issuer].revoked_attestation_ids))
            if not pre.accepted or not sensitive_authorization_allowed(snapshot, issuer, now):
                raise ValueError("canary_initial_acceptance_failed")
            old = snapshot.feeds[issuer]
            revoked = SovereignRevocationFeed(feed_id=str(uuid.uuid4()), issuer_sovereign_id=issuer,
                sequence=old.sequence + 1, issued_at=datetime.now(timezone.utc), issued_by="demo-na",
                revoked_attestation_ids=[*old.revoked_attestation_ids, received_attestation.attestation_id])
            revoked.signatures.append(sign_model(revoked, key, "demo-na"))
            publish(public / (issuer + ".json"), revoked)
            import_feed(snapshot, fetch(origin + "/" + issuer + ".json", SovereignRevocationFeed), datetime.now(timezone.utc))
            post = verify_attestation_with_treaty(received_attestation, treaty, [main_key],
                revoked_attestation_ids=set(snapshot.feeds[issuer].revoked_attestation_ids))
            if post.accepted or post.reason != "attestation_locally_revoked":
                raise ValueError("canary_revocation_failed")
            snapshot.canary = Canary(completed_at=datetime.now(timezone.utc), status="verified", issuer=issuer,
                                     attestation=received_attestation, treaty_id=treaty.treaty_id)
        except (OSError, ValueError, StopIteration, KeyError, requests.RequestException):
            successful = False
            snapshot.canary.status = "failed"
            logger.error("Daily cross-authority canary failed")
    # Full import history stays local; public history is bounded to 1,000 entries.
    new_events = [e for e in snapshot.events if e.at >= now]
    with (root / "imports.jsonl").open("a", encoding="utf-8") as log:
        for event in new_events:
            log.write(event.model_dump_json() + "\n")
    snapshot.events = snapshot.events[-1000:]
    snapshot.updated_at = datetime.now(timezone.utc)
    snapshot.signatures = []
    main_signer = load_private_key(str(root / "keys" / (snapshot.genesis.network_name + ".key")))
    snapshot.signatures.append(sign_model(snapshot, main_signer, "demo-na"))
    write_snapshot(root / "public.db", snapshot)
    return successful


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--origin", default="http://127.0.0.1:18444")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(0 if refresh(args.directory, args.origin) else 1)
