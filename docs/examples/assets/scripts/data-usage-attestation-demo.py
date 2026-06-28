"""Demo: Data Usage Attestation -- signed intent gated by license policy.

Run from repository root:
    python docs/examples/assets/scripts/data-usage-attestation-demo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-data-usage-attestation.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-data-usage-attestation.png"
TITLE = "Genesis Mesh -- Data Usage Attestation"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.models.data_usage import DataLicensePolicy, DataSourceDescriptor
    from genesis_mesh.trust.data_usage import (
        create_data_access_intent,
        verify_data_access_intent,
    )

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Data Usage Attestation Demo")
    step("    Signed intent gated offline by data license policy")
    step()

    kp = generate_keypair()

    step("==> Step 1: Define data license policy (10 MB, read-only, transactions_db)")
    policy = DataLicensePolicy(
        licensor_sovereign_id="bank-a",
        licensee_sovereign_id="org-a",
        allowed_source_ids=["transactions_db"],
        allowed_access_types=["read"],
        max_volume_bytes_per_session=10 * 1024 * 1024,
        prohibited_classification_tags=["pii_sensitive"],
        valid_from=_NOW - timedelta(days=1),
        valid_until=_NOW + timedelta(days=365),
    )
    step(f"    policy_id  : {policy.policy_id}")
    step(f"    licensee   : {policy.licensee_sovereign_id}")
    step(f"    sources    : {policy.allowed_source_ids}")
    step(f"    access     : {policy.allowed_access_types}")
    step(f"    max_bytes  : {policy.max_volume_bytes_per_session}")
    step()

    step("==> Step 2: Create compliant data access intent")
    source = DataSourceDescriptor(
        source_id="transactions_db",
        source_type="proprietary",
        owner_sovereign_id="bank-a",
        classification_tags=["financial"],
    )
    intent = create_data_access_intent(
        "org-a",
        "decision-001",
        [source],
        ["read"],
        kp.private_key,
        estimated_volume_bytes=1 * 1024 * 1024,
        valid_for_seconds=300,
        now=_NOW,
    )
    step(f"    intent_id  : {intent.intent_id}")
    step(f"    sources    : {[s.source_id for s in intent.declared_sources]}")
    step(f"    access     : {intent.declared_access_types}")
    step(f"    signed     : {intent.signature is not None}")
    step()

    step("==> Step 3: Verify compliant intent -- should pass")
    ok, reason, violations = verify_data_access_intent(
        intent, policy, [kp.public_key_b64], at_time=_NOW,
    )
    step(f"    valid      : {ok}")
    step(f"    reason     : {reason}")
    step(f"    violations : {len(violations)}")
    step()

    step("==> Step 4: Intent with unlicensed source -- source_not_licensed")
    bad_source = DataSourceDescriptor(
        source_id="audit_log_db",
        source_type="proprietary",
        owner_sovereign_id="bank-a",
        classification_tags=[],
    )
    bad_intent = create_data_access_intent(
        "org-a",
        "decision-002",
        [bad_source],
        ["read"],
        kp.private_key,
        now=_NOW,
    )
    bad_ok, bad_reason, bad_violations = verify_data_access_intent(
        bad_intent, policy, [kp.public_key_b64], at_time=_NOW,
    )
    step(f"    valid      : {bad_ok}")
    step(f"    reason     : {bad_reason}")
    step(f"    violation  : {bad_violations[0].violation_type if bad_violations else 'none'}")
    step()

    step("==> Step 5: Intent exceeding volume limit -- volume_cap_exceeded")
    over_intent = create_data_access_intent(
        "org-a",
        "decision-003",
        [source],
        ["read"],
        kp.private_key,
        estimated_volume_bytes=50 * 1024 * 1024,
        now=_NOW,
    )
    over_ok, over_reason, over_violations = verify_data_access_intent(
        over_intent, policy, [kp.public_key_b64], at_time=_NOW,
    )
    step(f"    valid      : {over_ok}")
    step(f"    reason     : {over_reason}")
    step(f"    violation  : {over_violations[0].violation_type if over_violations else 'none'}")
    step()

    step("VERIFIED: data access gated by policy; violations detected offline")
    step(f"          policy_id={policy.policy_id[:8]}...  intent_id={intent.intent_id[:8]}...")
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
