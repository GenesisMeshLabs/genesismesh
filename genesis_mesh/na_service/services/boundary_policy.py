"""Boundary policy lifecycle and policy-aware evaluation for the NA (v0.58).

Routes in ``routes/boundary_policy.py`` parse HTTP and call this service.
The service owns the invariants that must not depend on the HTTP layer:

- the NA builds every policy from declared intent fields and signs it; a
  caller never supplies version, issuer or signature
- publishing never activates; activation re-verifies the stored version
- the active set is re-verified on every evaluation
- evaluation failures yield signed DENY decisions, never an HTTP 500 or ALLOW
- an attestation basis (v0.58.1) is loaded from the NA's own store, verified
  against the NA key and checked against local and imported revocation
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError

from ...models.agreement import AgreementRecord
from ...models.boundary_policy import BoundaryPolicy, GateSpec, PolicySelector
from ...models.context import BoundaryDecision, ContextRecord
from ...models.justification import JustificationProof
from ...trust.context import (
    AttestationBasis,
    BoundaryEngine,
    GateRegistry,
    PolicyValidationResult,
    assess_attestation_basis,
    check_active_policy,
    sign_boundary_policy,
    validate_boundary_policy,
)
from ..errors import BadRequestError, ConflictError, NotFoundError

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService

logger = logging.getLogger(__name__)

BoundaryPolicyEnforcement = Literal["optional", "required"]
ENFORCEMENT_MODES: tuple[str, ...] = ("optional", "required")

#: Intent fields a publish/validate request may carry.
INTENT_FIELDS: frozenset[str] = frozenset(
    {"policy_id", "description", "valid_from", "valid_until", "selector", "gates"}
)
#: Fields only the NA assigns; a caller supplying one is refused.
NA_ASSIGNED_FIELDS: frozenset[str] = frozenset(
    {"version", "signature", "issued_at", "issued_by", "issuer_sovereign_id"}
)


def _summarise(exc: ValidationError) -> list[dict[str, str]]:
    """Field locations and messages only -- never echo input values."""
    return [
        {"field": ".".join(str(p) for p in err.get("loc", ())), "message": str(err.get("msg", "invalid"))}
        for err in exc.errors(include_input=False, include_url=False)[:16]
    ]


@dataclass(frozen=True)
class PolicyHealth:
    """Health of the active policy set: unhealthy means every evaluation denies."""

    healthy: bool
    problems: list[dict[str, Any]]



def agreement_parties(ctx: dict[str, Any], agreement: AgreementRecord) -> tuple[str, str]:
    """Return (requester, provider) bound to the agreement's roles (v1.1.1).

    The requester is the agreement's responder and the provider its offerer; a
    context naming another party is refused, so a caller cannot step outside a
    policy whose selector names the requester.
    """
    requester = agreement.responder_sovereign_id
    provider = agreement.offerer_sovereign_id
    for field, bound in (("requester_sovereign_id", requester), ("provider_sovereign_id", provider)):
        supplied = ctx.get(field)
        if supplied is not None and supplied != bound:
            raise BadRequestError(
                f"{field} must be the agreement's party ({bound})",
                code="context_party_mismatch",
            )
    return requester, provider


class BoundaryPolicyService:
    """NA application logic for declarative boundary policies."""

    def __init__(self, service: "NetworkAuthorityService") -> None:
        self._na = service

    # -- identity -----------------------------------------------------------

    @property
    def registry(self) -> GateRegistry:
        return self._na.gate_registry

    @property
    def enforcement(self) -> str:
        return self._na.boundary_policy_enforcement

    def policy_public_keys(self) -> list[str]:
        return [
            self._na.signer.public_key_b64
        ]

    # -- intent -> policy ---------------------------------------------------

    def build_from_intent(self, data: dict[str, Any], *, version: int | None = None) -> BoundaryPolicy:
        """Construct an unsigned BoundaryPolicy from declared intent fields."""
        supplied_na_fields = sorted(NA_ASSIGNED_FIELDS & data.keys())
        if supplied_na_fields:
            raise BadRequestError(
                "version, issuer and signature are assigned by the Network Authority",
                code="unexpected_field",
                details={"fields": supplied_na_fields},
            )
        unknown = sorted(data.keys() - INTENT_FIELDS)
        if unknown:
            raise BadRequestError(
                "unknown policy fields", code="unexpected_field", details={"fields": unknown}
            )
        policy_id = data.get("policy_id")
        if not isinstance(policy_id, str) or not policy_id:
            raise BadRequestError("policy_id is required", code="missing_policy_id")
        if not data.get("valid_from") or not data.get("valid_until"):
            raise BadRequestError(
                "valid_from and valid_until are required", code="missing_validity_window"
            )
        try:
            selector = PolicySelector.model_validate(data.get("selector") or {})
            gates = [GateSpec.model_validate(g) for g in (data.get("gates") or [])]
            return BoundaryPolicy(
                policy_id=policy_id,
                version=version if version is not None else self._na.db.next_boundary_policy_version(policy_id),
                description=data.get("description") or "",
                valid_from=data["valid_from"],
                valid_until=data["valid_until"],
                selector=selector,
                gates=gates,
                issued_at=datetime.now(timezone.utc),
                issued_by=self._na.key_id,
                issuer_sovereign_id=self._na.genesis_block.network_name,
            )
        except ValidationError as exc:
            raise BadRequestError(
                "invalid boundary policy", code="invalid_boundary_policy",
                details={"errors": _summarise(exc)},
            ) from exc
        except TypeError as exc:
            raise BadRequestError(
                "invalid boundary policy", code="invalid_boundary_policy"
            ) from exc

    def validate_intent(self, data: dict[str, Any]) -> tuple[BoundaryPolicy, PolicyValidationResult]:
        policy = self.build_from_intent(data)
        return policy, validate_boundary_policy(policy, self.registry)

    # -- lifecycle ----------------------------------------------------------

    PUBLISH_ATTEMPTS = 5

    def publish(self, data: dict[str, Any]) -> BoundaryPolicy:
        """Validate, sign and store a new inactive version."""
        policy, result = self.validate_intent(data)
        if not result.valid:
            raise BadRequestError(
                "boundary policy failed validation", code="boundary_policy_invalid",
                details=result.to_dict(),
            )
        # v0.60: another instance may publish the same policy_id concurrently
        # and take the version number; rebuild with the next one (bounded).
        for _ in range(self.PUBLISH_ATTEMPTS):
            signed = sign_boundary_policy(policy, self._na.signer, self._na.key_id)
            try:
                self._na.db.save_boundary_policy(signed)
            except self._na.db.integrity_errors:
                policy = self.build_from_intent(data)
                continue
            return signed
        raise ConflictError(
            "boundary policy version was taken by concurrent publishes; retry",
            code="boundary_policy_version_conflict",
        )

    def _stored(self, policy_id: str, version: int) -> tuple[dict, BoundaryPolicy]:
        row = self._na.db.get_boundary_policy_row(policy_id, version)
        if row is None:
            raise NotFoundError("unknown boundary policy version", code="boundary_policy_not_found")
        policy = self._na.db.parse_boundary_policy_row(row)
        if policy is None:
            raise ConflictError(
                "stored boundary policy failed its integrity check",
                code="boundary_policy_integrity_failed",
            )
        return row, policy

    def activate(
        self, policy_id: str, version: int, *, recorded_by: str | None = None, audit_event_id: str | None = None,
    ) -> tuple[BoundaryPolicy, int | None]:
        """Re-verify a stored version and make it the active one for its policy_id.

        v1.3.1: with ``EVIDENCE_OUT_OF_BAND=on`` the activation and its registry
        records (named by ``audit_event_id``) commit in one transaction.
        """
        _, policy = self._stored(policy_id, version)
        failure = check_active_policy(policy, self.registry, self.policy_public_keys())
        if failure is not None:
            raise ConflictError(
                "boundary policy cannot be activated", code="boundary_policy_activation_refused",
                details={"reason": failure},
            )
        if datetime.now(timezone.utc) > policy.valid_until:
            raise ConflictError(
                "boundary policy has expired", code="boundary_policy_activation_refused",
                details={"reason": "policy_expired"},
            )
        try:
            previous = self._na.out_of_band_service.activate_policy(policy, recorded_by, audit_event_id)
        except self._na.db.integrity_errors as exc:
            # The one-active-version index refused a concurrent activation.
            raise ConflictError(
                "another version of this policy was activated concurrently; retry",
                code="boundary_policy_activation_conflict",
            ) from exc
        return policy, previous

    def deactivate(
        self, policy_id: str, version: int, *, recorded_by: str | None = None, audit_event_id: str | None = None,
    ) -> None:
        if self._na.db.get_boundary_policy_row(policy_id, version) is None:
            raise NotFoundError("unknown boundary policy version", code="boundary_policy_not_found")
        if not self._na.out_of_band_service.deactivate_policy(policy_id, version, recorded_by, audit_event_id):
            raise ConflictError("boundary policy version is not active", code="boundary_policy_not_active")

    # -- inspection ---------------------------------------------------------

    @staticmethod
    def _summary(row: dict, policy: BoundaryPolicy | None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "policy_id": row["policy_id"],
            "version": row["version"],
            "active": bool(row["active"]),
            "policy_digest": row["policy_digest"],
            "created_at": row["created_at"],
            "activated_at": row["activated_at"],
            "deactivated_at": row["deactivated_at"],
            "integrity_ok": policy is not None,
        }
        if policy is not None:
            out.update({
                "description": policy.description,
                "valid_from": policy.valid_from.isoformat(),
                "valid_until": policy.valid_until.isoformat(),
                "gate_count": len(policy.gates),
                "global": policy.selector.is_global(),
            })
        return out

    def list_versions(self, policy_id: str | None = None, *, include_policy: bool = False) -> list[dict[str, Any]]:
        out = []
        for row in self._na.db.list_boundary_policy_rows(policy_id):
            policy = self._na.db.parse_boundary_policy_row(row)
            item = self._summary(row, policy)
            if include_policy and policy is not None:
                item["policy"] = policy.model_dump(mode="json")
            out.append(item)
        return out

    def health(self) -> PolicyHealth:
        """Re-verify the active set exactly as evaluation would."""
        loaded = self._na.db.load_active_boundary_policies()
        problems: list[dict[str, Any]] = [
            {"policy": ref, "reason": "policy_store_integrity_failed"} for ref in loaded.integrity_failures
        ]
        now = datetime.now(timezone.utc)
        keys = self.policy_public_keys()
        for policy in loaded.policies:
            ref = f"{policy.policy_id}@{policy.version}"
            failure = check_active_policy(policy, self.registry, keys)
            if failure is not None:
                problems.append({"policy": ref, "reason": failure})
            elif now > policy.valid_until:
                problems.append({"policy": ref, "reason": "policy_expired"})
        return PolicyHealth(healthy=not problems, problems=problems)

    def active_status(self) -> dict[str, Any]:
        health = self.health()
        active = []
        for policy in self._na.db.load_active_boundary_policies().policies:
            active.append({
                "policy_id": policy.policy_id,
                "version": policy.version,
                "policy_digest": policy.digest(),
                "valid_from": policy.valid_from.isoformat(),
                "valid_until": policy.valid_until.isoformat(),
                "gate_count": len(policy.gates),
                "selector": policy.selector.model_dump(mode="json"),
                "policy": policy.model_dump(mode="json"),
            })
        return {
            "enforcement": self.enforcement,
            "policy_set_healthy": health.healthy,
            "problems": health.problems,
            "registry_gate_types": self.registry.gate_types(),
            "active": active,
        }

    # -- evaluation ---------------------------------------------------------

    @staticmethod
    def build_context(data: dict[str, Any], agreement: AgreementRecord) -> ContextRecord:
        """Build the ContextRecord for an evaluate request (same shape as /decide)."""
        ctx = data.get("context") or {}
        if not isinstance(ctx, dict):
            raise BadRequestError("context must be an object", code="invalid_context")
        requester, provider = agreement_parties(ctx, agreement)
        try:
            return ContextRecord(
                context_id=ctx.get("context_id") or str(uuid.uuid4()),
                agreement_id=agreement.agreement_id,
                parent_kind=ctx.get("parent_kind") or "direct",
                requester_sovereign_id=requester,
                provider_sovereign_id=provider,
                requested_capability=data["requested_capability"],
                request_parameters=ctx.get("request_parameters") or {},
                attributes=ctx.get("attributes") or {},
                requested_at=datetime.now(timezone.utc),
                context_freshness_seq=ctx.get("context_freshness_seq") or 0,
            )
        except (ValidationError, TypeError) as exc:
            raise BadRequestError("Invalid context record", code="invalid_context") from exc

    def evaluate(
        self, context: ContextRecord, agreement: AgreementRecord
    ) -> tuple[BoundaryDecision, JustificationProof]:
        """Evaluate a context against built-in gates and the active policy set."""
        loaded = self._na.db.load_active_boundary_policies()
        engine = BoundaryEngine(operator_sovereign_id=self._na.genesis_block.network_name)
        return engine.evaluate_with_policies(
            context,
            agreement,
            self._na.signer,
            issued_by=self._na.key_id,
            policies=loaded.policies,
            registry=self.registry,
            policy_public_keys=self.policy_public_keys(),
            policy_integrity_failures=loaded.integrity_failures,
            now=datetime.now(timezone.utc),
        )

    # -- attestation basis (v0.58.1) -----------------------------------------

    def assess_attestation(self, attestation_id: str, requester_id: str | None) -> tuple[AttestationBasis, str]:
        """Load and check an attestation; return the basis and the requester id used.

        The requester defaults to the attestation subject when not supplied.
        """
        row = self._na.db.get_membership_attestation(attestation_id)
        attestation = row["attestation"] if row else None
        feed_revoked = False
        seq = 0
        if attestation is not None:
            issuer = attestation.issuer_sovereign_id
            feed_revoked = attestation_id in self._na.db.get_imported_revoked_attestation_ids(issuer)
            seq = self._na.db.get_latest_sovereign_revocation_sequence(issuer) or 0
        requester = requester_id or (attestation.subject_id if attestation is not None else "unknown")
        basis = assess_attestation_basis(
            attestation_id,
            attestation,
            issuer_public_keys=self.policy_public_keys(),
            stored_status=row["status"] if row else None,
            feed_revoked=feed_revoked,
            revocation_seq_checked=seq,
            requester_id=requester,
        )
        return basis, requester

    def build_attestation_context(
        self, data: dict[str, Any], attestation_id: str, requester_id: str
    ) -> ContextRecord:
        """Build the ContextRecord for an attestation-basis evaluate request.

        ``parent_kind`` is always ``"attestation"``; a caller cannot choose it.
        """
        ctx = data.get("context") or {}
        if not isinstance(ctx, dict):
            raise BadRequestError("context must be an object", code="invalid_context")
        own_id = self._na.genesis_block.network_name
        supplied_provider = ctx.get("provider_sovereign_id")
        if supplied_provider is not None and supplied_provider != own_id:
            # v1.1.1: under an attestation this NA is the provider.
            raise BadRequestError(
                f"provider_sovereign_id must be this sovereign ({own_id})",
                code="context_party_mismatch",
            )
        try:
            return ContextRecord(
                context_id=ctx.get("context_id") or str(uuid.uuid4()),
                agreement_id=attestation_id,
                attestation_id=attestation_id,
                parent_kind="attestation",
                requester_sovereign_id=requester_id,
                provider_sovereign_id=own_id,
                requested_capability=data["requested_capability"],
                request_parameters=ctx.get("request_parameters") or {},
                attributes=ctx.get("attributes") or {},
                requested_at=datetime.now(timezone.utc),
                context_freshness_seq=ctx.get("context_freshness_seq") or 0,
            )
        except (ValidationError, TypeError) as exc:
            raise BadRequestError("Invalid context record", code="invalid_context") from exc

    def evaluate_attestation(
        self, context: ContextRecord, basis: AttestationBasis
    ) -> tuple[BoundaryDecision, JustificationProof]:
        """Evaluate a context under an attestation basis and the active policy set."""
        loaded = self._na.db.load_active_boundary_policies()
        engine = BoundaryEngine(operator_sovereign_id=self._na.genesis_block.network_name)
        return engine.evaluate_attestation_with_policies(
            context,
            basis,
            self._na.signer,
            issued_by=self._na.key_id,
            policies=loaded.policies,
            registry=self.registry,
            policy_public_keys=self.policy_public_keys(),
            policy_integrity_failures=loaded.integrity_failures,
            now=datetime.now(timezone.utc),
        )
