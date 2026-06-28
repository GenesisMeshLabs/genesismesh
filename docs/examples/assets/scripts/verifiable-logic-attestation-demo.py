"""Demo: Verifiable Logic Attestation -- pre-execution configuration binding.

Run from repository root:
    python docs/examples/assets/scripts/verifiable-logic-attestation-demo.py
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from terminal_render import render_gif, render_png

ROOT = Path(__file__).resolve().parents[4]
GIF = ROOT / "docs/examples/assets/images/genesis-mesh-verifiable-logic-attestation.gif"
PNG = ROOT / "docs/examples/assets/images/genesis-mesh-verifiable-logic-attestation.png"
TITLE = "Genesis Mesh -- Verifiable Logic Attestation"

_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def run_demo() -> list[str]:
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.models.attestation import AttestationPolicy, ToolManifest
    from genesis_mesh.trust.logic_attestation import (
        create_model_attestation,
        verify_model_attestation,
    )

    transcript: list[str] = []

    def step(line: str = "") -> None:
        print(line)
        transcript.append(line)

    step("==> Genesis Mesh: Verifiable Logic Attestation Demo")
    step("    Bind agent execution context before capability invocation")
    step()

    kp_agent = generate_keypair()

    MODEL_ID = "claude-sonnet-4-6"
    MODEL_VERSION = "20251001"
    SYSTEM_PROMPT = "You are a financial data analyst. Only read transactions. Never write."
    TOOL_IDS = ["transactions.read", "balances.read"]

    # -------------------------------------------------------------------------
    step("==> Step 1: Agent creates and signs ModelAttestation")
    attestation = create_model_attestation(
        agent_sovereign_id="agent-fin-01",
        model_id=MODEL_ID,
        model_version_tag=MODEL_VERSION,
        system_prompt=SYSTEM_PROMPT,
        tool_ids=TOOL_IDS,
        signing_key=kp_agent.private_key,
        valid_for_seconds=300,
        now=_NOW,
    )
    step(f"    attestation_id     : {attestation.attestation_id}")
    step(f"    agent_sovereign_id : {attestation.agent_sovereign_id}")
    step(f"    model_id           : {attestation.model_id}")
    step(f"    model_version_tag  : {attestation.model_version_tag}")
    step(f"    system_prompt_hash : {attestation.system_prompt_hash[:16]}...")
    step(f"    tool_manifest_hash : {attestation.tool_manifest_hash[:16]}...")
    step()

    # -------------------------------------------------------------------------
    step("==> Step 2: Build AttestationPolicy permitting this model")
    tool_manifest = ToolManifest(tool_ids=TOOL_IDS)
    prompt_hash = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
    policy = AttestationPolicy(
        operator_sovereign_id="org-a",
        allowed_model_ids=[MODEL_ID],
        allowed_system_prompt_hashes=[prompt_hash],
        allowed_tool_manifest_hashes=[tool_manifest.manifest_hash],
        require_bound_token=False,
        valid_from=_NOW,
        valid_until=_NOW + timedelta(days=30),
    )
    step(f"    policy_id          : {policy.policy_id}")
    step(f"    allowed_model_ids  : {policy.allowed_model_ids}")
    step(f"    require_bound_token: {policy.require_bound_token}")
    step()

    # -------------------------------------------------------------------------
    step("==> Step 3: Verify attestation against policy -- VALID")
    passed, reason = verify_model_attestation(
        attestation=attestation,
        policy=policy,
        agent_public_keys=[kp_agent.public_key_b64],
        at_time=_NOW,
    )
    step(f"    valid  : {passed}")
    step(f"    reason : {reason}")
    step()

    # -------------------------------------------------------------------------
    step("==> Step 4: Policy with different model_id -- model_not_permitted")
    restricted_policy = AttestationPolicy(
        operator_sovereign_id="org-a",
        allowed_model_ids=["gpt-4o"],
        valid_from=_NOW,
        valid_until=_NOW + timedelta(days=30),
    )
    passed_r, reason_r = verify_model_attestation(
        attestation=attestation,
        policy=restricted_policy,
        agent_public_keys=[kp_agent.public_key_b64],
        at_time=_NOW,
    )
    step(f"    valid  : {passed_r}")
    step(f"    reason : {reason_r}")
    step()

    # -------------------------------------------------------------------------
    step("==> Step 5: Tamper detection -- altered system prompt")
    step("    Attacker changes system prompt after signing")
    tampered = attestation.model_copy(update={
        "system_prompt_hash": hashlib.sha256(
            "ignore all previous instructions".encode()
        ).hexdigest()
    })
    passed_t, reason_t = verify_model_attestation(
        attestation=tampered,
        policy=policy,
        agent_public_keys=[kp_agent.public_key_b64],
        at_time=_NOW,
    )
    step(f"    valid  : {passed_t}")
    step(f"    reason : {reason_t}")
    step()

    step("VERIFIED: model configuration attested and policy-checked offline")
    step(f"          attestation_id = {attestation.attestation_id}")
    step(f"          model={MODEL_ID} bound to agent-fin-01; tamper -> invalid_signature")
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
