"""Create fresh demo identities and signed evidence without altering old state."""

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

from genesis_mesh.crypto import generate_keypair, save_keypair, sign_model
from genesis_mesh.models import GenesisBlock, NetworkAuthority, PolicyManifestRef
from genesis_mesh.models import RecognitionTreaty, RecognitionTreatyScope, SovereignRevocationFeed

from .records import Snapshot, TreatyRecord, digest
from .store import write_snapshot

NAMES = ["public", "edge", "local", "alpha", "beta", "gamma", "delta", "epsilon", "sandbox-a", "sandbox-b"]


def seed(root: Path) -> Snapshot:
    if root.exists():
        raise ValueError("Refusing to overwrite an existing dataset")
    root.mkdir(parents=True, mode=0o700)
    (root / "keys").mkdir(mode=0o700)
    now = datetime.now(timezone.utc)
    authorities = {}
    keys = {}
    for name in NAMES:
        identity = f"gm-demo-{name}-na"
        root_pair, na_pair = generate_keypair(), generate_keypair()
        save_keypair(root_pair, str(root / "keys" / (identity + "-root")), "demo-root")
        save_keypair(na_pair, str(root / "keys" / identity), "demo-na")
        keys[identity] = na_pair
        block = GenesisBlock(
            network_name=identity, network_version="v0.1", root_public_key=root_pair.public_key_b64,
            network_authority=NetworkAuthority(public_key=na_pair.public_key_b64,
                valid_from=now, valid_to=now + timedelta(days=365)),
            policy_manifest=PolicyManifestRef(hash="sha256:" + digest("read-only public reference instance")),
        )
        block.signatures.append(sign_model(block, root_pair.private_key, "demo-root"))
        authorities[identity] = block
    main = "gm-demo-public-na"
    snapshot = Snapshot(updated_at=now, genesis=authorities[main], authorities=authorities,
                        treaties=[], feeds={}, imports={})
    for identity, authority in authorities.items():
        if identity == main:
            continue
        treaty = RecognitionTreaty(treaty_id=str(uuid.uuid4()), issuer_sovereign_id=main,
            subject_sovereign_id=identity, subject_public_keys=[authority.network_authority.public_key],
            scope=RecognitionTreatyScope(allowed_roles=["role:demo"]), issued_at=now, valid_from=now,
            expires_at=now + timedelta(days=90), issued_by="demo-na")
        treaty.signatures.append(sign_model(treaty, keys[main].private_key, "demo-na"))
        snapshot.treaties.append(TreatyRecord(treaty=treaty, expected_active=True))
    for identity in authorities:
        feed = SovereignRevocationFeed(feed_id=str(uuid.uuid4()), issuer_sovereign_id=identity,
                                      sequence=0, issued_at=now, issued_by="demo-na")
        feed.signatures.append(sign_model(feed, keys[identity].private_key, "demo-na"))
        snapshot.feeds[identity] = feed
        snapshot.imports[identity] = now
    snapshot.signatures.append(sign_model(snapshot, keys[main].private_key, "demo-na"))
    write_snapshot(root / "public.db", snapshot)
    (root / "root.pub").write_text(snapshot.genesis.root_public_key, encoding="utf-8")
    return snapshot


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    seed(parser.parse_args().directory)
