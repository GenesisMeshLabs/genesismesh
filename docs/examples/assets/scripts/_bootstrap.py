"""Shared bootstrap helpers for Genesis Mesh demo scripts.

Provides a minimal active two-sovereign graph and convenience factories
so each demo script can focus on its protocol feature, not setup.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_DEMO_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)
_DEMO_VALID = _DEMO_NOW + timedelta(days=365)


def active_graph(src: str, dst: str, *, now: datetime | None = None) -> dict:
    """Minimal bidirectional recognition graph with one active treaty per direction."""
    t = now or _DEMO_NOW
    exp = t + timedelta(days=365)
    return {
        "sovereigns": [{"sovereign_id": src}, {"sovereign_id": dst}],
        "recognition_edges": [
            {
                "from": src,
                "to": dst,
                "treaty_id": f"t-{src}-{dst}",
                "status": "active",
                "lifecycle_state": "active",
                "expiry_risk": "low",
                "valid_from": t.isoformat(),
                "expires_at": exp.isoformat(),
            },
            {
                "from": dst,
                "to": src,
                "treaty_id": f"t-{dst}-{src}",
                "status": "active",
                "lifecycle_state": "active",
                "expiry_risk": "low",
                "valid_from": t.isoformat(),
                "expires_at": exp.isoformat(),
            },
        ],
        "active_treaties": [
            {
                "treaty_id": f"t-{src}-{dst}",
                "issuer_sovereign_id": src,
                "subject_sovereign_id": dst,
                "scope": {"allowed_roles": ["transactions.read", "balances.read", "payments.write"]},
                "valid_from": t.isoformat(),
                "expires_at": exp.isoformat(),
                "signatures": [],
            },
            {
                "treaty_id": f"t-{dst}-{src}",
                "issuer_sovereign_id": dst,
                "subject_sovereign_id": src,
                "scope": {"allowed_roles": ["transactions.read", "balances.read", "payments.write"]},
                "valid_from": t.isoformat(),
                "expires_at": exp.isoformat(),
                "signatures": [],
            },
        ],
    }


def make_agreement(
    src: str = "org-a",
    dst: str = "bank-a",
    capabilities: list[str] | None = None,
    *,
    now: datetime | None = None,
):
    """Build a minimal dual-signed AgreementRecord between two sovereigns."""
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.models.agreement import AgreementTerms
    from genesis_mesh.trust.agreement import accept_counter, build_counter, build_offer

    t = now or _DEMO_NOW
    caps = capabilities or ["transactions.read"]
    kp_a = generate_keypair()
    kp_b = generate_keypair()
    graph = active_graph(src, dst, now=t)
    terms = AgreementTerms(
        capabilities=caps,
        scope={"delegation": False},
        valid_from=t,
        valid_until=t + timedelta(days=365),
        freshness_commitment=42,
    )
    offer = build_offer(
        src, dst, terms, graph, kp_a.private_key,
        issued_by=f"{src}-op", expires_at=t + timedelta(hours=1), now=t,
    )
    counter = build_counter(offer, terms, graph, kp_b.private_key, issued_by=f"{dst}-op", now=t)
    agreement = accept_counter(counter, offer, kp_a.private_key, issued_by=f"{src}-op", now=t)
    return agreement, kp_a, kp_b


def make_boundary_decision_with_proof(
    agreement=None,
    capability: str = "transactions.read",
    *,
    now: datetime | None = None,
):
    """Evaluate with proof and return (decision, justification_proof, operator_keypair)."""
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.models.context import ContextRecord
    from genesis_mesh.trust.context import BoundaryEngine

    t = now or _DEMO_NOW
    if agreement is None:
        agreement, _kp_a, _kp_b = make_agreement()

    kp_op = generate_keypair()
    engine = BoundaryEngine("org-a", decision_valid_seconds=300)

    ctx = ContextRecord(
        context_id="ctx-demo-002",
        agreement_id=agreement.agreement_id,
        parent_kind="agreement",
        requester_sovereign_id=agreement.offerer_sovereign_id,
        provider_sovereign_id=agreement.responder_sovereign_id,
        requested_capability=capability,
        request_parameters={},
        requested_at=t,
        context_freshness_seq=50,
    )
    decision, jp = engine.evaluate_with_proof(
        context=ctx,
        agreement=agreement,
        signing_key=kp_op.private_key,
        issued_by="org-a-op",
        now=t,
    )
    return decision, jp, kp_op


def make_boundary_decision(
    agreement=None,
    capability: str = "transactions.read",
    *,
    now: datetime | None = None,
):
    """Evaluate a BoundaryEngine and return (decision, engine_keypair)."""
    from genesis_mesh.crypto import generate_keypair
    from genesis_mesh.models.context import ContextRecord
    from genesis_mesh.trust.context import BoundaryEngine

    t = now or _DEMO_NOW
    if agreement is None:
        agreement, _kp_a, _kp_b = make_agreement()

    kp_op = generate_keypair()
    engine = BoundaryEngine("org-a", decision_valid_seconds=300)

    ctx = ContextRecord(
        context_id="ctx-demo-001",
        agreement_id=agreement.agreement_id,
        parent_kind="agreement",
        requester_sovereign_id=agreement.offerer_sovereign_id,
        provider_sovereign_id=agreement.responder_sovereign_id,
        requested_capability=capability,
        request_parameters={},
        requested_at=t,
        context_freshness_seq=50,
    )
    decision = engine.evaluate(
        context=ctx,
        agreement=agreement,
        signing_key=kp_op.private_key,
        issued_by="org-a-op",
        now=t,
    )
    return decision, kp_op
