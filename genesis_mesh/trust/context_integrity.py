"""Context-Injection Defense Gate — runtime context integrity verification (v0.41).

A ContextIntegrityRecord commits to the base context hash and a list of typed,
bounded ContextAppendSegments before execution. The ContextInjectionGate blocks
execution if any undeclared, out-of-bounds, or tampered segment is present in the
final context.

Security property:
    final_context = committed_base + declared_typed_append_segments

Any segment present in the final context that was not declared (typed, sized, and
provenance-linked) before execution is a violation.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

import nacl.signing

from ..crypto import sign_model, verify_model_signature
from ..models.context_integrity import (
    ContextAppendSegment,
    ContextIntegrityRecord,
    ContextTree,
    ContextViolationReport,
)

# ---------------------------------------------------------------------------
# Typed reason codes
# ---------------------------------------------------------------------------

ContextIntegrityReason = Literal[
    "valid",
    "missing_signature",
    "invalid_signature",
    "expired",
    "undeclared_segment",
    "segment_token_exceeded",
    "total_token_exceeded",
    "base_context_tampered",
]

# ---------------------------------------------------------------------------
# Injection pattern heuristics (non-blocking, informational)
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions?",
    r"system\s*prompt\s*override",
    r"<\|im_start\|>",
    r"\[INST\]",
    r"JAILBREAK",
]


def scan_for_injection_markers(
    content: str,
    patterns: list[str] | None = None,
) -> list[str]:
    """Return list of matched injection-pattern strings found in content.

    Non-blocking: the caller decides what to do with matches.
    """
    active = patterns if patterns is not None else _INJECTION_PATTERNS
    return [p for p in active if re.search(p, content, re.IGNORECASE)]


# ---------------------------------------------------------------------------
# create_context_integrity_record
# ---------------------------------------------------------------------------


def create_context_integrity_record(
    agent_sovereign_id: str,
    decision_id: str,
    base_context_tree: ContextTree,
    declared_segments: list[ContextAppendSegment],
    signing_key: nacl.signing.SigningKey,
    *,
    max_total_tokens: int = 8192,
    valid_for_seconds: int = 600,
    now: datetime | None = None,
) -> ContextIntegrityRecord:
    """Create and sign a ContextIntegrityRecord.

    committed_base_context_hash is auto-computed from base_context_tree.
    """
    now = now or datetime.now(timezone.utc)
    record = ContextIntegrityRecord(
        agent_sovereign_id=agent_sovereign_id,
        decision_id=decision_id,
        base_context=base_context_tree,
        declared_append_segments=declared_segments,
        max_total_tokens=max_total_tokens,
        committed_at=now,
        expires_at=now + timedelta(seconds=valid_for_seconds),
    )
    sig = sign_model(record, signing_key, agent_sovereign_id)
    return record.model_copy(update={"signature": sig})


# ---------------------------------------------------------------------------
# verify_context_integrity
# ---------------------------------------------------------------------------


def verify_context_integrity(
    record: ContextIntegrityRecord,
    final_context_tree: ContextTree,
    observed_segments: list[ContextAppendSegment],
    agent_public_keys: list[str],
    *,
    at_time: datetime | None = None,
) -> tuple[bool, ContextIntegrityReason, ContextViolationReport | None]:
    """Verify that final context = committed base + declared append segments.

    Checks run in order:
    signature → expiry → base_context_tampered → undeclared_segment
    → segment_token_exceeded → total_token_exceeded.

    Returns (passed, reason, violation_report). Report is None on success.
    """
    at_time = at_time or datetime.now(timezone.utc)

    def _v(vtype: str, committed: str, observed: str) -> ContextViolationReport:
        return ContextViolationReport(
            record_id=record.record_id,
            agent_sovereign_id=record.agent_sovereign_id,
            detected_at=at_time,
            violation_type=vtype,
            committed_value=committed,
            observed_value=observed,
            severity="block",
        )

    if record.signature is None:
        return False, "missing_signature", _v("missing_signature", "signature_present", "missing")

    if not any(
        verify_model_signature(record, record.signature, pk)
        for pk in agent_public_keys
    ):
        return False, "invalid_signature", _v("invalid_signature", "valid", "invalid")

    if at_time > record.expires_at:
        return False, "expired", _v("expired", record.expires_at.isoformat(), at_time.isoformat())

    if final_context_tree.system_prompt_hash != record.base_context.system_prompt_hash:
        return (
            False,
            "base_context_tampered",
            _v(
                "base_context_tampered",
                record.base_context.system_prompt_hash,
                final_context_tree.system_prompt_hash,
            ),
        )

    declared_ids = {s.segment_id for s in record.declared_append_segments}
    for obs in observed_segments:
        if obs.segment_id not in declared_ids:
            return (
                False,
                "undeclared_segment",
                _v("undeclared_segment", "declared", obs.segment_id),
            )

    declared_by_id = {s.segment_id: s for s in record.declared_append_segments}
    for obs in observed_segments:
        if obs.actual_tokens is not None:
            decl = declared_by_id[obs.segment_id]
            if obs.actual_tokens > decl.max_tokens:
                return (
                    False,
                    "segment_token_exceeded",
                    _v("segment_token_exceeded", str(decl.max_tokens), str(obs.actual_tokens)),
                )

    if final_context_tree.total_token_estimate > record.max_total_tokens:
        return (
            False,
            "total_token_exceeded",
            _v(
                "total_token_exceeded",
                str(record.max_total_tokens),
                str(final_context_tree.total_token_estimate),
            ),
        )

    return True, "valid", None


# ---------------------------------------------------------------------------
# ContextInjectionGate — plugs into BoundaryEngine via add_gate()
# ---------------------------------------------------------------------------


class ContextInjectionGate:
    """Callable gate: passes only if final context = committed base + declared segments.

    Usage (opt-in):

        gate = ContextInjectionGate(
            record=pre_execution_record,
            final_context=post_tool_call_context_tree,
            observed_segments=segments_present_after_execution,
            agent_public_keys=[agent_pub_b64],
        )
        engine.add_gate(gate)
    """

    gate_name = "context_injection"

    def __init__(
        self,
        record: ContextIntegrityRecord,
        final_context: ContextTree,
        observed_segments: list[ContextAppendSegment],
        agent_public_keys: list[str],
    ) -> None:
        self._record = record
        self._final_context = final_context
        self._observed_segments = observed_segments
        self._keys = agent_public_keys

    def __call__(self, context: object, terms: object) -> object:
        from ..models.context import GateResult  # noqa: PLC0415

        passed, reason, report = verify_context_integrity(
            self._record,
            self._final_context,
            self._observed_segments,
            self._keys,
        )
        if passed:
            return GateResult(
                gate_name=self.gate_name,
                passed=True,
                detail=f"record '{self._record.record_id[:8]}' integrity verified",
            )
        return GateResult(
            gate_name=self.gate_name,
            passed=False,
            detail=reason,
        )
