"""Verifiable Logic Attestation — pre-execution configuration binding (v0.40).

An agent signs a ModelAttestation declaring its exact execution context
(model_id, model_version_tag, system_prompt_hash, tool_manifest_hash) before
invoking a capability. The LogicAttestationGate validates this against an
operator's AttestationPolicy.

This closes the "hidden instruction" exploit: a valid IBCT issued to agent A
cannot be used by agent A running under a manipulated system prompt, a
jailbroken model, or with additional undeclared tools.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Literal

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.attestation import AttestationPolicy, ModelAttestation, ToolManifest

# ---------------------------------------------------------------------------
# Typed reason codes
# ---------------------------------------------------------------------------

LogicAttestationVerificationReason = Literal[
    "valid",
    "missing_signature",
    "invalid_signature",
    "expired",
    "model_not_permitted",
    "system_prompt_not_permitted",
    "tool_manifest_not_permitted",
    "token_binding_required",
]

# ---------------------------------------------------------------------------
# create_model_attestation
# ---------------------------------------------------------------------------


def create_model_attestation(
    agent_sovereign_id: str,
    model_id: str,
    model_version_tag: str,
    system_prompt: str,
    tool_ids: list[str],
    signing_key: nacl.signing.SigningKey,
    *,
    token_id: str | None = None,
    valid_for_seconds: int = 300,
    now: datetime | None = None,
) -> ModelAttestation:
    """Create and sign a ModelAttestation for a given execution context.

    system_prompt is hashed (SHA-256, UTF-8) — the raw prompt is never stored.
    tool_ids are sorted before hashing so declaration order does not affect
    the manifest_hash.
    """
    now = now or datetime.now(timezone.utc)
    system_prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()
    tool_manifest = ToolManifest(tool_ids=tool_ids)

    attestation = ModelAttestation(
        agent_sovereign_id=agent_sovereign_id,
        model_id=model_id,
        model_version_tag=model_version_tag,
        system_prompt_hash=system_prompt_hash,
        tool_manifest_hash=tool_manifest.manifest_hash,
        token_id=token_id,
        attested_at=now,
        expires_at=now + timedelta(seconds=valid_for_seconds),
    )
    sig = sign_model(attestation, signing_key, agent_sovereign_id)
    return attestation.model_copy(update={"signature": sig})


# ---------------------------------------------------------------------------
# verify_model_attestation
# ---------------------------------------------------------------------------


def verify_model_attestation(
    attestation: ModelAttestation,
    policy: AttestationPolicy,
    agent_public_keys: list[str],
    *,
    at_time: datetime | None = None,
) -> tuple[bool, LogicAttestationVerificationReason]:
    """Verify a ModelAttestation against an AttestationPolicy.

    Returns (passed, reason). Checks run in order:
    signature → expiry → model_id → prompt_hash → tool_hash → token_binding.

    Empty allowlists mean "any value permitted" for that dimension.
    """
    at_time = at_time or datetime.now(timezone.utc)

    if attestation.signature is None:
        return False, "missing_signature"

    if not any(
        verify_model_signature(attestation, attestation.signature, pk)
        for pk in agent_public_keys
    ):
        return False, "invalid_signature"

    if at_time > attestation.expires_at:
        return False, "expired"

    if (
        policy.allowed_model_ids
        and attestation.model_id not in policy.allowed_model_ids
    ):
        return False, "model_not_permitted"

    if (
        policy.allowed_system_prompt_hashes
        and attestation.system_prompt_hash not in policy.allowed_system_prompt_hashes
    ):
        return False, "system_prompt_not_permitted"

    if (
        policy.allowed_tool_manifest_hashes
        and attestation.tool_manifest_hash not in policy.allowed_tool_manifest_hashes
    ):
        return False, "tool_manifest_not_permitted"

    if policy.require_bound_token and attestation.token_id is None:
        return False, "token_binding_required"

    return True, "valid"


# ---------------------------------------------------------------------------
# LogicAttestationGate — plugs into BoundaryEngine via add_gate()
# ---------------------------------------------------------------------------


class LogicAttestationGate:
    """Callable gate that verifies ModelAttestation against an AttestationPolicy.

    Usage (opt-in):

        gate = LogicAttestationGate(
            attestation=agent_attestation,
            policy=operator_policy,
            agent_public_keys=[agent_pub_b64],
        )
        engine.add_gate(gate)
    """

    def __init__(
        self,
        attestation: ModelAttestation,
        policy: AttestationPolicy,
        agent_public_keys: list[str],
    ) -> None:
        self._attestation = attestation
        self._policy = policy
        self._keys = agent_public_keys

    def __call__(self, context: object, terms: object) -> object:
        from ..models.context import GateResult

        passed, reason = verify_model_attestation(
            self._attestation,
            self._policy,
            self._keys,
        )
        if passed:
            return GateResult(
                gate_name="logic_attestation",
                passed=True,
                detail=(
                    f"attestation '{self._attestation.attestation_id[:8]}' "
                    f"verified for model '{self._attestation.model_id}'"
                ),
            )
        return GateResult(
            gate_name="logic_attestation",
            passed=False,
            detail=reason,
        )
