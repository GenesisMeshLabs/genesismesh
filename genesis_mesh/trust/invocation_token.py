"""Issue and verify Invocation-Bound Capability Tokens (IBCTs).

An InvocationToken lets a bearer prove offline that it is authorised to
invoke specific capabilities, at most N times, subject to policy constraints.

Verification order for verify_invocation_token:
  1. missing_signature  — no signature on the token
  2. invalid_signature  — signature present but does not verify
  3. bearer_mismatch    — bearer_sovereign_id ≠ requested bearer
  4. expired            — expires_at < at_time
  5. capability_not_granted — requested capability not in token.capabilities
  6. budget_exhausted   — use_records count ≥ max_invocations (when set)
  7. policy_violated    — a policy constraint is not satisfied
  8. valid

Based on: arXiv:2603.24775 (AIP — Agent Identity Protocol)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.agreement import AgreementRecord
from ..models.delegation import DelegatedAgreementRecord
from ..models.invocation_token import InvocationToken, InvocationUseRecord


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

InvocationTokenVerificationReason = Literal[
    "valid",
    "expired",
    "missing_signature",
    "invalid_signature",
    "capability_not_granted",
    "budget_exhausted",
    "policy_violated",
    "bearer_mismatch",
]


@dataclass(frozen=True)
class InvocationTokenVerificationResult:
    """Structured outcome of an InvocationToken verification attempt."""

    valid: bool
    reason: InvocationTokenVerificationReason

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "reason": self.reason}


# ---------------------------------------------------------------------------
# InvocationUseRecord result
# ---------------------------------------------------------------------------

InvocationUseRecordReason = Literal[
    "recorded",
    "missing_token_signature",
    "bearer_mismatch",
]


@dataclass(frozen=True)
class InvocationUseRecordResult:
    """Structured outcome of a record_invocation_use call."""

    recorded: bool
    reason: InvocationUseRecordReason

    def to_dict(self) -> dict[str, Any]:
        return {"recorded": self.recorded, "reason": self.reason}


# ---------------------------------------------------------------------------
# _now helper
# ---------------------------------------------------------------------------


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# issue_invocation_token
# ---------------------------------------------------------------------------


def issue_invocation_token(
    agreement: AgreementRecord,
    bearer_sovereign_id: str,
    capabilities: list[str],
    signing_key: nacl.signing.SigningKey,
    *,
    issued_by: str,
    valid_for_seconds: int = 300,
    max_invocations: int | None = None,
    policy_constraints: list[str] | None = None,
    delegation: DelegatedAgreementRecord | None = None,
    now: datetime | None = None,
) -> InvocationToken:
    """Create and sign an InvocationToken.

    Args:
        agreement: The AgreementRecord that grants the capabilities.
        bearer_sovereign_id: Sovereign that will use the token.
        capabilities: Subset of capabilities to grant (must be ⊆ agreement terms
            or, when delegation is supplied, ⊆ delegation.delegated_terms).
        signing_key: Issuer's Ed25519 private key.
        issued_by: Key identifier recorded in the signature.
        valid_for_seconds: Token lifetime in seconds (default 300 = 5 min).
        max_invocations: Maximum number of uses; None means unlimited.
        policy_constraints: Optional list of structured policy predicates.
        delegation: When the token is derived from a delegation hop rather than
            the root agreement, provide the DelegatedAgreementRecord for scope
            validation.
        now: Override for the current timestamp.

    Raises:
        ValueError: If any requested capability is outside the source scope.
    """
    ts = _now(now)

    # Determine the allowed source scope
    if delegation is not None:
        source_caps = set(delegation.delegated_terms.capabilities)
    else:
        source_caps = set(agreement.agreed_terms.capabilities)

    invalid = [c for c in capabilities if c not in source_caps]
    if invalid:
        raise ValueError(
            f"Capabilities not in source scope: {invalid}. "
            f"Source scope: {sorted(source_caps)}"
        )

    issuer_sovereign_id = (
        delegation.delegator_sovereign_id
        if delegation is not None
        else agreement.offerer_sovereign_id
    )

    token = InvocationToken(
        issued_at=ts,
        expires_at=ts.replace(second=0, microsecond=0).__class__(
            ts.year, ts.month, ts.day,
            ts.hour, ts.minute, ts.second, ts.microsecond,
            tzinfo=ts.tzinfo,
        ),  # will be overwritten below via model_copy
        issuer_sovereign_id=issuer_sovereign_id,
        bearer_sovereign_id=bearer_sovereign_id,
        agreement_id=agreement.agreement_id,
        delegation_id=delegation.delegation_id if delegation is not None else None,
        capabilities=list(capabilities),
        max_invocations=max_invocations,
        policy_constraints=list(policy_constraints or []),
    )
    # Compute expires_at properly
    from datetime import timedelta
    expires = ts + timedelta(seconds=valid_for_seconds)
    token = token.model_copy(update={"issued_at": ts, "expires_at": expires})

    sig = sign_model(token, signing_key, issued_by)
    return token.model_copy(update={"signature": sig})


# ---------------------------------------------------------------------------
# _check_policy_constraints
# ---------------------------------------------------------------------------


def _check_policy_constraints(
    token: InvocationToken,
    bearer_sovereign_id: str,
    at_time: datetime,
) -> bool:
    """Return True if all policy constraints are satisfied."""
    for constraint in token.policy_constraints:
        if constraint.startswith("not_before:"):
            not_before_str = constraint[len("not_before:"):]
            try:
                from datetime import datetime as _dt
                nb = _dt.fromisoformat(not_before_str)
                if nb.tzinfo is None:
                    from datetime import timezone as _tz
                    nb = nb.replace(tzinfo=_tz.utc)
                if at_time < nb:
                    return False
            except ValueError:
                return False
        elif constraint.startswith("peer_sovereign:"):
            required_peer = constraint[len("peer_sovereign:"):]
            if bearer_sovereign_id != required_peer:
                return False
        # Unknown constraints are passed through without validation failure.
    return True


# ---------------------------------------------------------------------------
# verify_invocation_token
# ---------------------------------------------------------------------------


def verify_invocation_token(
    token: InvocationToken,
    issuer_public_keys: list[str],
    *,
    requested_capability: str,
    bearer_sovereign_id: str,
    use_records: list[InvocationUseRecord] | None = None,
    at_time: datetime | None = None,
) -> InvocationTokenVerificationResult:
    """Verify an InvocationToken against a specific invocation request.

    Args:
        token: The InvocationToken to verify.
        issuer_public_keys: Base64-encoded public keys for the token issuer.
        requested_capability: The capability the bearer wants to invoke.
        bearer_sovereign_id: Claimed identity of the bearer.
        use_records: Known InvocationUseRecords for this token (for budget check).
        at_time: Time to check expiry against (default: now).

    Returns:
        InvocationTokenVerificationResult with reason code.
    """
    ts = _now(at_time)
    _ok = InvocationTokenVerificationResult
    _fail = InvocationTokenVerificationResult

    if token.signature is None:
        return _fail(valid=False, reason="missing_signature")

    sig_valid = any(
        verify_model_signature(token, token.signature, pub)
        for pub in issuer_public_keys
    )
    if not sig_valid:
        return _fail(valid=False, reason="invalid_signature")

    if token.bearer_sovereign_id != bearer_sovereign_id:
        return _fail(valid=False, reason="bearer_mismatch")

    if token.expires_at < ts:
        return _fail(valid=False, reason="expired")

    if requested_capability not in token.capabilities:
        return _fail(valid=False, reason="capability_not_granted")

    if token.max_invocations is not None:
        use_count = len(use_records) if use_records else 0
        if use_count >= token.max_invocations:
            return _fail(valid=False, reason="budget_exhausted")

    if not _check_policy_constraints(token, bearer_sovereign_id, ts):
        return _fail(valid=False, reason="policy_violated")

    return _ok(valid=True, reason="valid")


# ---------------------------------------------------------------------------
# record_invocation_use
# ---------------------------------------------------------------------------


def record_invocation_use(
    token: InvocationToken,
    action_tag: str,
    outcome: str,
    signing_key: nacl.signing.SigningKey,
    *,
    used_by: str,
    prior_use: InvocationUseRecord | None = None,
    now: datetime | None = None,
) -> InvocationUseRecord:
    """Create and sign an InvocationUseRecord.

    If ``prior_use`` is provided, sets ``prev_use_digest`` to the SHA-256 of
    that record's canonical JSON, extending the use-chain.

    Args:
        token: The InvocationToken being used.
        action_tag: Short label for the invoked action.
        outcome: "success" or "failure".
        signing_key: Bearer's Ed25519 private key.
        used_by: Key identifier recorded in the signature.
        prior_use: Previous InvocationUseRecord in the chain (None if first).
        now: Override for the current timestamp.
    """
    ts = _now(now)
    prev_digest: str | None = prior_use.digest() if prior_use is not None else None

    record = InvocationUseRecord(
        token_id=token.token_id,
        used_at=ts,
        used_by_sovereign_id=token.bearer_sovereign_id,
        action_tag=action_tag,
        outcome=outcome,
        prev_use_digest=prev_digest,
    )
    sig = sign_model(record, signing_key, used_by)
    return record.model_copy(update={"signature": sig})
