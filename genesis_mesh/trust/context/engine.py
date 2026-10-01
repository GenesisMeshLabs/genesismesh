"""BoundaryEngine — evaluation core."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Sequence

import nacl.signing

from ...crypto import sign_model
from ...models.agreement import AgreementRecord
from ...models.boundary_policy import BoundaryPolicy, PolicyBinding, policy_set_digest
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
from .attestation_basis import (
    ATTESTATION_GATE_TYPES,
    AttestationBasis,
    attestation_capability_gate,
    attestation_denial_reason,
    attestation_freshness_gate,
    attestation_gate_inputs,
    attestation_status_gate,
    attestation_validity_gate,
)
from .policy import ConfiguredGateRecord, evaluate_configured_gates, resolve_policies
from .registry import GateRegistry
from genesis_mesh.crypto.signing import SigningKeyLike

if TYPE_CHECKING:
    from ...models.justification import JustificationProof

#: gate_name recorded when policy resolution fails closed.
POLICY_RESOLUTION_GATE = "policy_resolution"


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
        signing_key: SigningKeyLike,
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

    def _run_builtin_gates(
        self,
        context: ContextRecord,
        terms: Any,
        ts: datetime,
        freshness_proof: FreshnessProof | None,
        freshness_proof_issuer_keys: list[str] | None,
    ) -> "_GateRun":
        """Run built-in and add_gate() gates with v0.28 short-circuit semantics."""
        from ...models.justification import GateTraceEntry

        run = _GateRun()
        for gate in self._gates:
            result = gate(context, terms)
            run.gate_results.append(result)
            run.trace_entries.append(GateTraceEntry(
                gate_name=result.gate_name,
                gate_type=_GATE_TYPE_MAP.get(result.gate_name, "CustomGate"),
                evaluated_at=ts,
                inputs=gate_inputs(result.gate_name, context, terms),
                result=result.passed,
                reason=result.detail,
            ))
            if not result.passed:
                run.first_failure = result
                run.short_circuited_at = result.gate_name
                break

        if run.first_failure is None and self._require_freshness_proof:
            proof_result = freshness_proof_gate(
                freshness_proof, terms, freshness_proof_issuer_keys or [], ts
            )
            run.gate_results.append(proof_result)
            run.trace_entries.append(GateTraceEntry(
                gate_name=proof_result.gate_name,
                gate_type="FreshnessProofGate",
                evaluated_at=ts,
                inputs=freshness_proof_inputs(freshness_proof, terms),
                result=proof_result.passed,
                reason=proof_result.detail,
            ))
            if not proof_result.passed:
                run.first_failure = proof_result
                run.short_circuited_at = proof_result.gate_name
        return run

    def evaluate_with_proof(
        self,
        context: ContextRecord,
        agreement: AgreementRecord,
        signing_key: SigningKeyLike,
        *,
        issued_by: str,
        freshness_proof: FreshnessProof | None = None,
        freshness_proof_issuer_keys: list[str] | None = None,
        now: datetime | None = None,
    ) -> "tuple[BoundaryDecision, Any]":
        """Evaluate and additionally emit a signed JustificationProof.

        Returns (BoundaryDecision, JustificationProof).
        """
        from ...models.justification import GateTrace
        from ..justification import sign_justification_proof

        ts = now or datetime.now(timezone.utc)
        terms = agreement.agreed_terms
        run = self._run_builtin_gates(context, terms, ts, freshness_proof, freshness_proof_issuer_keys)

        authorized = run.first_failure is None
        dr: str | None = denial_reason(run.first_failure) if run.first_failure else None
        embedded_proof: FreshnessProof | None = freshness_proof if (authorized and freshness_proof) else None

        decision = BoundaryDecision(
            context_id=context.context_id,
            agreement_id=context.agreement_id,
            authorized=authorized,
            denial_reason=dr,
            gate_results=run.gate_results,
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
            entries=run.trace_entries,
            short_circuited_at=run.short_circuited_at,
            final_authorized=authorized,
        )
        justification = sign_justification_proof(trace, decision, signing_key, issued_by=issued_by, now=ts)
        return decision, justification

    def evaluate_with_policies(
        self,
        context: ContextRecord,
        agreement: AgreementRecord,
        signing_key: SigningKeyLike,
        *,
        issued_by: str,
        policies: Sequence[BoundaryPolicy],
        registry: GateRegistry,
        policy_public_keys: Sequence[str],
        policy_integrity_failures: Sequence[str] = (),
        freshness_proof: FreshnessProof | None = None,
        freshness_proof_issuer_keys: list[str] | None = None,
        now: datetime | None = None,
    ) -> "tuple[BoundaryDecision, JustificationProof]":
        """Evaluate built-in gates plus every applicable active BoundaryPolicy.

        ``policies`` is the full *active* set; resolution selects the ones that
        apply.  Returns a signed BoundaryDecision whose signed body carries a
        PolicyBinding, and a signed JustificationProof covering every gate.

        Fails closed: a resolution failure (untrusted, ambiguous or expired
        policy, store integrity failure) or any failing enforce-mode gate
        yields ``authorized=False``.  Built-in gates keep their short-circuit
        semantics; configured gates are all evaluated so the proof shows every
        failing rule.
        """
        from ...models.justification import GateTrace
        from ..justification import sign_justification_proof

        ts = now or datetime.now(timezone.utc)
        terms = agreement.agreed_terms
        run = self._run_builtin_gates(context, terms, ts, freshness_proof, freshness_proof_issuer_keys)

        dr: str | None = denial_reason(run.first_failure) if run.first_failure else None
        binding, dr, authorized = _apply_policies(
            run, context, ts, dr, policies, registry, policy_public_keys, policy_integrity_failures,
        )
        embedded_proof: FreshnessProof | None = freshness_proof if (authorized and freshness_proof) else None

        decision = BoundaryDecision(
            context_id=context.context_id,
            agreement_id=context.agreement_id,
            authorized=authorized,
            denial_reason=None if authorized else dr,
            gate_results=run.gate_results,
            decision_made_at=ts,
            decision_valid_until=ts + timedelta(seconds=self.decision_valid_seconds),
            operator_sovereign_id=self.operator_sovereign_id,
            freshness_proof=embedded_proof,
            policy_binding=binding,
        )
        sig = sign_model(decision, signing_key, issued_by)
        decision = decision.model_copy(update={"signature": sig})

        trace = GateTrace(
            decision_id=decision.decision_id,
            agreement_id=agreement.agreement_id,
            operator_sovereign_id=self.operator_sovereign_id,
            traced_at=ts,
            entries=run.trace_entries,
            short_circuited_at=run.short_circuited_at,
            final_authorized=authorized,
        )
        justification = sign_justification_proof(trace, decision, signing_key, issued_by=issued_by, now=ts)
        return decision, justification

    def evaluate_attestation_with_policies(
        self,
        context: ContextRecord,
        basis: AttestationBasis,
        signing_key: SigningKeyLike,
        *,
        issued_by: str,
        policies: Sequence[BoundaryPolicy],
        registry: GateRegistry,
        policy_public_keys: Sequence[str],
        policy_integrity_failures: Sequence[str] = (),
        now: datetime | None = None,
    ) -> "tuple[BoundaryDecision, JustificationProof]":
        """Evaluate a request under a MembershipAttestation (v0.58.1).

        The attestation gates replace the agreement gates and run first, with
        the same short-circuit semantics: ``attestation_status``,
        ``attestation_validity``, ``capability_check`` (``claims.capabilities``)
        and ``freshness_check``.  Policies then resolve and evaluate exactly as
        in ``evaluate_with_policies``, with the attestation fact root bound.

        The signed decision carries both an AttestationBinding and a
        PolicyBinding.  Any failure yields a signed DENY; a failed attestation
        gate sets ``denial_reason`` to its stable code (e.g.
        ``attestation_revoked``).  Custom gates added with ``add_gate`` expect
        agreement terms and do not run on this path.
        """
        from ...models.justification import GateTrace, GateTraceEntry
        from ..justification import sign_justification_proof

        if context.parent_kind != "attestation" or context.attestation_id != basis.attestation_id:
            raise ValueError("context is not an attestation context for this basis")

        ts = now or datetime.now(timezone.utc)
        context = context.with_attestation_facts(basis.facts())
        checks: list[Any] = [
            lambda: attestation_status_gate(basis),
            lambda: attestation_validity_gate(basis, context),
            lambda: attestation_capability_gate(basis, context),
            lambda: attestation_freshness_gate(context),
        ]
        run = _GateRun()
        for check in checks:
            result: GateResult = check()
            run.gate_results.append(result)
            run.trace_entries.append(GateTraceEntry(
                gate_name=result.gate_name,
                gate_type=ATTESTATION_GATE_TYPES.get(result.gate_name) or _GATE_TYPE_MAP[result.gate_name],
                evaluated_at=ts,
                inputs=attestation_gate_inputs(result.gate_name, basis, context),
                result=result.passed,
                reason=result.detail,
            ))
            if not result.passed:
                run.first_failure = result
                run.short_circuited_at = result.gate_name
                break

        dr: str | None = None
        if run.first_failure is not None:
            dr = attestation_denial_reason(run.first_failure) or denial_reason(run.first_failure)
        policy_binding, dr, authorized = _apply_policies(
            run, context, ts, dr, policies, registry, policy_public_keys, policy_integrity_failures,
        )

        decision = BoundaryDecision(
            context_id=context.context_id,
            agreement_id=context.agreement_id,
            authorized=authorized,
            denial_reason=None if authorized else dr,
            gate_results=run.gate_results,
            decision_made_at=ts,
            decision_valid_until=ts + timedelta(seconds=self.decision_valid_seconds),
            operator_sovereign_id=self.operator_sovereign_id,
            policy_binding=policy_binding,
            attestation_binding=basis.binding(),
        )
        sig = sign_model(decision, signing_key, issued_by)
        decision = decision.model_copy(update={"signature": sig})

        trace = GateTrace(
            decision_id=decision.decision_id,
            agreement_id=context.agreement_id,
            operator_sovereign_id=self.operator_sovereign_id,
            traced_at=ts,
            entries=run.trace_entries,
            short_circuited_at=run.short_circuited_at,
            final_authorized=authorized,
        )
        justification = sign_justification_proof(trace, decision, signing_key, issued_by=issued_by, now=ts)
        return decision, justification


@dataclass
class _GateRun:
    """Mutable accumulator for one gate run (internal)."""

    gate_results: list[GateResult] = field(default_factory=list)
    trace_entries: list[Any] = field(default_factory=list)
    first_failure: GateResult | None = None
    short_circuited_at: str | None = None


def _apply_policies(
    run: "_GateRun",
    context: ContextRecord,
    ts: datetime,
    dr: str | None,
    policies: Sequence[BoundaryPolicy],
    registry: GateRegistry,
    policy_public_keys: Sequence[str],
    policy_integrity_failures: Sequence[str],
) -> tuple[PolicyBinding, str | None, bool]:
    """Resolve and evaluate configured policy gates after the built-in gates.

    Mutates ``run`` with the policy gate results and trace entries.  Returns
    the PolicyBinding, the denial reason and whether the request is authorized.
    """
    from ...models.justification import GateTraceEntry

    resolution = resolve_policies(
        policies, context, registry, policy_public_keys, ts,
        integrity_failures=policy_integrity_failures,
    )
    records: list[ConfiguredGateRecord] = []

    if not resolution.resolved:
        failure = resolution.failure or "policy_invalid"
        detail = f"policy resolution failed: {failure}"
        if resolution.failure_policy is not None:
            detail += f" ({resolution.failure_policy[0]} v{resolution.failure_policy[1]})"
        run.gate_results.append(GateResult(gate_name=POLICY_RESOLUTION_GATE, passed=False, detail=detail))
        run.trace_entries.append(GateTraceEntry(
            gate_name=POLICY_RESOLUTION_GATE,
            gate_type="PolicyResolution",
            evaluated_at=ts,
            inputs={"active_policy_count": len(policies)},
            result=False,
            reason=detail,
            metadata={"resolution_failure": failure},
        ))
        if run.short_circuited_at is None:
            run.short_circuited_at = POLICY_RESOLUTION_GATE
            dr = f"policy resolution failed: {failure}"
    elif run.first_failure is None:
        records = evaluate_configured_gates(resolution.applied, context, registry)
        for rec in records:
            ev = rec.evaluation
            prefix = "[observe] " if ev.mode == "observe" else ""
            run.gate_results.append(GateResult(
                gate_name=rec.gate_name, passed=ev.passed, detail=prefix + rec.detail,
            ))
            run.trace_entries.append(GateTraceEntry(
                gate_name=rec.gate_name,
                gate_type=ev.gate_type,
                evaluated_at=ts,
                inputs={**rec.inputs, "condition": rec.condition},
                result=ev.passed,
                reason=rec.detail,
                metadata={
                    "policy_id": ev.policy_id,
                    "policy_version": ev.policy_version,
                    "gate_id": ev.gate_id,
                    "order": ev.order,
                    "mode": ev.mode,
                    "outcome": ev.outcome,
                },
            ))
        denying = [rec for rec in records if rec.denies]
        if denying:
            run.short_circuited_at = denying[0].gate_name
            dr = f"policy gate '{denying[0].gate_name}' failed"
            if len(denying) > 1:
                dr += f" (+{len(denying) - 1} more)"

    authorized = run.short_circuited_at is None
    applied = resolution.applied_policies()
    binding = PolicyBinding(
        policies=applied,
        policy_set_digest=policy_set_digest(applied),
        gate_evaluations=[rec.evaluation for rec in records],
        context_digest=context.digest(),
        registry_gate_types=sorted({g.gate_type for p in resolution.applied for g in p.gates}),
        resolution_status=resolution.status,
        resolution_failure=resolution.failure,
    )
    return binding, dr, authorized
