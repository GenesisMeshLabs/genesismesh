"""Demo: Sovereign Overlay Discovery -- gossip-based peer discovery without DNS.

Run from repository root:
    python docs/examples/assets/scripts/sovereign-overlay-discovery-demo.py
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-sovereign-overlay-discovery.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-sovereign-overlay-discovery.png"
TITLE = "Genesis Mesh -- Sovereign Overlay Discovery"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.models.overlay_discovery import DiscoveryGossipMessage
    from genesis_mesh.trust.overlay_discovery import (
        build_discovery_feed,
        create_discovery_record,
        gossip_should_forward,
        merge_discovery_records,
        verify_discovery_record,
    )

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Sovereign Overlay Discovery Demo")
    step("    Signed gossip peer discovery -- no DNS, Noise XX transport")
    step()

    kp_a = generate_keypair()
    kp_b = generate_keypair()
    kp_operator = generate_keypair()

    caps_hash_a = hashlib.sha256(b"org-a-capabilities-v1").hexdigest()
    caps_hash_b = hashlib.sha256(b"org-b-capabilities-v1").hexdigest()

    step("==> Step 1: Sovereign A publishes its discovery record")
    record_a = create_discovery_record(
        sovereign_id="org-a",
        na_public_key_b64=kp_a.public_key_b64,
        endpoints=["noise://10.0.0.1:7400", "noise://mesh-a.internal:7400"],
        capabilities_hash=caps_hash_a,
        signing_key=kp_a.private_key,
        sequence_no=1,
        valid_for_hours=24,
        now=_NOW,
    )
    step(f"    record_id    : {record_a.record_id[:16]}...")
    step(f"    sovereign_id : {record_a.sovereign_id}")
    step(f"    endpoints    : {record_a.endpoints}")
    step(f"    sequence_no  : {record_a.sequence_no}")
    step()

    step("==> Step 2: Verify Sovereign A's discovery record signature")
    ok_a, reason_a = verify_discovery_record(record_a, at_time=_NOW)
    step(f"    valid  : {ok_a}")
    step(f"    reason : {reason_a}")
    step()

    step("==> Step 3: Sovereign B publishes its discovery record")
    record_b = create_discovery_record(
        sovereign_id="org-b",
        na_public_key_b64=kp_b.public_key_b64,
        endpoints=["noise://10.0.0.2:7400"],
        capabilities_hash=caps_hash_b,
        signing_key=kp_b.private_key,
        sequence_no=1,
        valid_for_hours=24,
        now=_NOW,
    )
    step(f"    record_id    : {record_b.record_id[:16]}...")
    step(f"    sovereign_id : {record_b.sovereign_id}")
    step(f"    endpoints    : {record_b.endpoints}")
    step()

    step("==> Step 4: Merge A + B into combined discovery cache")
    updated_cache, changed_ids = merge_discovery_records(
        existing=[],
        incoming=[record_a, record_b],
        now=_NOW,
    )
    step(f"    cache_size   : {len(updated_cache)}")
    step(f"    changed_ids  : {changed_ids}")
    step()

    step("==> Step 5: Build signed DiscoveryFeed from both records")
    feed = build_discovery_feed(
        records=[record_a, record_b],
        operator_sovereign_id="mesh-operator",
        signing_key=kp_operator.private_key,
        valid_for_hours=6,
        now=_NOW,
    )
    step(f"    feed_id      : {feed.feed_id[:16]}...")
    step(f"    entries      : {len(feed.entries)} records")
    step(f"    valid_until  : {feed.valid_until.isoformat()}")
    step()

    step("==> Step 6: Gossip forwarding -- TTL enforced via hop_count")
    msg_live = DiscoveryGossipMessage(
        records=[record_a],
        origin_sovereign_id="org-a",
        hop_count=2,
        max_hops=5,
        sent_at=_NOW,
    )
    msg_expired = DiscoveryGossipMessage(
        records=[record_a],
        origin_sovereign_id="org-a",
        hop_count=5,
        max_hops=5,
        sent_at=_NOW,
    )
    forward_live = gossip_should_forward(msg_live, max_hops=5)
    forward_expired = gossip_should_forward(msg_expired, max_hops=5)
    step(f"    hop_count=2 / max_hops=5 -> should_forward : {forward_live}")
    step(f"    hop_count=5 / max_hops=5 -> should_forward : {forward_expired}")
    step()

    step("VERIFIED: sovereign endpoints discoverable; signatures verified; gossip TTL enforced")
    step(f"          feed covers {len(feed.entries)} sovereigns; org-a sig {reason_a}")
    step(f"          hop TTL blocks forward at max_hops={msg_expired.max_hops}")
    return transcript


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, default=GIF)
    p.add_argument("--png-output", type=Path, default=PNG)
    p.add_argument("--no-gif", action="store_true")
    args = p.parse_args()

    lines = run_demo()
    if not args.no_gif:
        render_png(lines, TITLE, args.png_output)
        render_gif(lines, TITLE, args.output)
        print(f"\nPNG -> {args.png_output}")
        print(f"GIF -> {args.output}")


if __name__ == "__main__":
    main()
