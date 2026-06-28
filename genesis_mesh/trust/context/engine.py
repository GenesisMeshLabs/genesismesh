"""BoundaryEngine — evaluation core."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import nacl.signing

from ...crypto import sign_model
from ...models.agreement import AgreementRecord
from ...models.context import BoundaryDecision, ContextRecord, GateResult
from ...models.freshness import FreshnessProof
from .gates import (
    GateCallable,
    _GATE_TYPE_MAP,
    capability_gate,
    denial_reason,
    freshness_gate,
    freshness_proof_gate,
    freshness_proof_inputs,
    gate_inputs,
    validity_window_gate,
)


class BoundaryEngine:
    """Evaluate a ContextRecord against an AgreementRecord and return a signed BoundaryDecision.

    Gates run in order; first failure short-circuits. Custom gates can be
    appended via add_gate(gate).  When require_freshness_proof=True, a valid
    FreshnessProof must be supplied to evaluate().
    """

    def __init__(
        self,
        operator_sovereign_id: str,
        *,
        decision_valid_seconds: int = 300,
        require_freshness_proof: bool = False,
    ) -> None:
        self.operator_sovereign_id = operator_sovereign_id
        self.decision_valid_seconds = decision_valid_seconds
        self._require_freshness_proof = require_freshness_proof
        self._gates: list[GateCallable] = [
            capability_gate,
            validity_window_gate,
            freshness_gate,
        ]

    def add_gate(self, gate: GateCallable) -> None:
        self._gates.append(gate)

    def evaluate(
        self,
        context: ContextRecord,
        agreement: AgreementRecord,
        signing_key: nacl.signing.SigningKey,
        *,
        issued_by: str,
        freshness_proof: FreshnessProof | None = None,
        freshness_proof_issuer_keys: list[str] | None = None,
        now: datetime | None = None,
    ) -> BoundaryDecision:
        ts = now or datetime.now(timezone.utc)
        terms = agreement.agreed_terms
        gate_results: list[GateResult] = []
        first_failure: GateResult | None = None

        for gate in self._gates:
            result = gate(context, terms)
            gate_results.append(result)
            if not result.passed:
                first_failure = result
                break

        if first_failure is None and self._require_freshness_proof:
            proof_result = freshness_proof_gate(
                freshness_proof, terms, freshness_proof_issuer_keys or [], ts
            )
            gate_results.append(proof_result)
            if not proof_result.passed:
                first_failure = proof_result

        authorized = first_failure is None
        dr: str | None = denial_reason(first_failure) if first_failure is not None else None
        embedded_proof: FreshnessProof | None = freshness_proof if (authorized and freshness_proof) else None

        decision = BoundaryDecision(
            context_id=context.context_id,
            agreement_id=context.agreement_id,
            authorized=authorized,
            denial_reason=dr,
            gate_results=gate_results,
            decision_made_at=ts,
            decision_valid_until=ts + timedelta(seconds=self.decision_valid_seconds),
            operator_sovereign_id=self.operator_sovereign_id,
            freshness_proof=embedded_proof,
        )
        sig = sign_model(decision, signing_key, issued_by)
        return decision.model_copy(update={"signature": sig})

    def evaluate_with_proof(
        self,
        context: ContextRecord,
        agreement: AgreementRecord,
        signing_key: nacl.signing.SigningKey,
        *,
        issued_by: str,
        freshness_proof: FreshnessProof | None = None,
        freshness_proof_issuer_keys: list[str] | None = None,
        now: datetime | None = None,
    ) -> "tuple[BoundaryDecision, Any]":
        """Evaluate and additionally emit a signed JustificationProof.

        Returns (BoundaryDecision, JustificationProof).
        """
        from ...models.justification import GateTrace, GateTraceEntry
        from ..justification import sign_justification_proof

        ts = now or datetime.now(timezone.utc)
        terms = agreement.agreed_terms
        trace_entries: list[GateTraceEntry] = []
        gate_results: list[GateResult] = []
        first_failure: GateResult | None = None
        short_circuited_at: str | None = None

        for gate in self._gates:
            result = gate(context, terms)
            gate_results.append(result)
            trace_entries.append(GateTraceEntry(
                gate_name=result.gate_name,
                gate_type=_GATE_TYPE_MAP.get(result.gate_name, "CustomGate"),
                evaluated_at=ts,
                inputs=gate_inputs(result.gate_name, context, terms),
                result=result.passed,
                reason=result.detail,
            ))
            if not result.passed:
                first_failure = result
                short_circuited_at = result.gate_name
                break

        if first_failure is None and self._require_freshness_proof:
            proof_result = freshness_proof_gate(
                freshness_proof, terms, freshness_proof_issuer_keys or [], ts
            )
            gate_results.append(proof_result)
            trace_entries.append(GateTraceEntry(
                gate_name=proof_result.gate_name,
                gate_type="FreshnessProofGate",
                evaluated_at=ts,
                inputs=freshness_proof_inputs(freshness_proof, terms),
                result=proof_result.passed,
                reason=proof_result.detail,
            ))
            if not proof_result.passed:
                first_failure = proof_result
                short_circuited_at = proof_result.gate_name

        authorized = first_failure is None
        dr: str | None = denial_reason(first_failure) if first_failure else None
        embedded_proof: FreshnessProof | None = freshness_proof if (authorized and freshness_proof) else None

        decision = BoundaryDecision(
            context_id=context.context_id,
            agreement_id=context.agreement_id,
            authorized=authorized,
            denial_reason=dr,
            gate_results=gate_results,
            decision_made_at=ts,
            decision_valid_until=ts + timedelta(seconds=self.decision_valid_seconds),
            operator_sovereign_id=self.operator_sovereign_id,
            freshness_proof=embedded_proof,
        )
        sig = sign_model(decision, signing_key, issued_by)
        decision = decision.model_copy(update={"signature": sig})

        trace = GateTrace(
            decision_id=decision.decision_id,
            agreement_id=agreement.agreement_id,
            operator_sovereign_id=self.operator_sovereign_id,
            traced_at=ts,
            entries=trace_entries,
            short_circuited_at=short_circuited_at,
            final_authorized=authorized,
        )
        justification = sign_justification_proof(trace, decision, signing_key, issued_by=issued_by, now=ts)
        return decision, justification
