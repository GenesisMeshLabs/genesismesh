"""Demo: Communication Privacy -- metadata normalization for outbound messages.

Run from repository root:
    python docs/examples/assets/scripts/communication-privacy-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-communication-privacy.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-communication-privacy.png"
TITLE = "Genesis Mesh -- Communication Privacy"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.models.privacy import CommunicationPrivacyProfile
    from genesis_mesh.trust.privacy import (
        apply_privacy_profile,
        scan_metadata_fingerprints,
    )

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Communication Privacy Demo")
    step("    Strip headers, bucket timestamps, normalize payload length")
    step()

    kp = generate_keypair()
    sender_id = "org-a"

    step("==> Step 1: Create CommunicationPrivacyProfile (strip + normalize all)")
    profile = CommunicationPrivacyProfile(
        sovereign_id=sender_id,
        strip_custom_headers=True,
        normalize_timestamps=True,
        timestamp_bucket_seconds=60,
        normalize_message_length=True,
        message_length_block_bytes=256,
        strip_routing_metadata=True,
        allowed_header_keys=["content-type"],
    )
    step(f"    profile_id              : {profile.profile_id[:16]}...")
    step(f"    strip_custom_headers    : {profile.strip_custom_headers}")
    step(f"    normalize_timestamps    : {profile.normalize_timestamps} (bucket={profile.timestamp_bucket_seconds}s)")
    step(f"    message_length_block    : {profile.message_length_block_bytes} bytes")
    step()

    # Raw payload: 300 bytes -> will pad to 512
    raw_payload = b"A" * 300
    raw_headers = {
        "content-type": "application/json",
        "gm-version": "1.0",
        "gm-sovereign": sender_id,
        "gm-message-id": "msg-0001",
        "X-Agent-ID": "agent-abc-123",
        "X-Session-Token": "tok-secret-xyz",
        "X-Routing-Path": "node1->node2->node3",
    }
    dispatch_time = datetime(2026, 6, 28, 12, 0, 37, tzinfo=timezone.utc)

    step("==> Step 2: Scan raw headers for fingerprinting risks")
    fingerprints = scan_metadata_fingerprints(raw_headers, profile)
    step(f"    raw header count  : {len(raw_headers)}")
    step(f"    risky headers     : {fingerprints}")
    step(f"    fingerprint count : {len(fingerprints)}")
    step()

    step("==> Step 3: Apply privacy profile to payload + headers")
    envelope, normalized_payload, audit = apply_privacy_profile(
        payload=raw_payload,
        headers=raw_headers,
        dispatch_time=dispatch_time,
        sender_sovereign_id=sender_id,
        profile=profile,
        signing_key=kp.private_key,
        now=_NOW,
    )
    step(f"    envelope_id       : {envelope.envelope_id[:16]}...")
    step(f"    retained_headers  : {list(envelope.retained_headers.keys())}")
    step(f"    headers_stripped  : {audit.headers_stripped}")
    step()

    step("==> Step 4: Payload length before vs. after normalization")
    step(f"    original_length   : {audit.original_length} bytes")
    step(f"    normalized_length : {audit.normalized_length} bytes (next 256-byte block)")
    step(f"    padded_bytes      : {audit.length_padded_bytes}")
    step()

    step("==> Step 5: Timestamp bucketing")
    step(f"    dispatch_time     : {dispatch_time.isoformat()}")
    step(f"    bucketed          : {envelope.bucketed_timestamp.isoformat()}")
    step(f"    shift_seconds     : {audit.timestamp_shifted_seconds}")
    step()

    step("==> Step 6: Scan stripped envelope headers -- no fingerprints remain")
    post_fingerprints = scan_metadata_fingerprints(envelope.retained_headers, profile)
    step(f"    post-strip risky  : {post_fingerprints}")
    step(f"    fingerprints_clean: {len(post_fingerprints) == 0}")
    step()

    step("VERIFIED: metadata stripped, timing bucketed, payload normalized")
    step(f"          {audit.headers_stripped} headers stripped; {audit.length_padded_bytes} pad bytes added")
    step(f"          envelope_id = {envelope.envelope_id[:16]}...")
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
