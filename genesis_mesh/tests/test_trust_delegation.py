"""Tests for Attenuable Delegation Chains (v0.27).

Covers:
- build_delegation + cosign_delegation round-trip (chain of length 1)
- Two-hop delegation chain (chain of length 2)
- Scope widening rejection (build_delegation and verify_delegation_chain)
- Validity escalation rejection
- Parent-terms digest mismatch
- Parent ID mismatch
- Missing / invalid signatures at each hop
- Tamper detection (agreed_terms tampered)
- Non-party delegator rejection
- JSON serialization round-trip (transport independence)
- CLI: trust delegate create, cosign, verify
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

import nacl.signing

from genesis_mesh.cli.delegation_ops import delegate
from genesis_mesh.crypto import generate_keypair
from genesis_mesh.models.agreement import AgreementRecord, AgreementTerms
from genesis_mesh.models.delegation import DelegatedAgreementRecord, DelegationChain, terms_digest
from genesis_mesh.trust.agreement import accept_counter, build_counter, build_offer, cosign_agreement, accept_offer
from genesis_mesh.trust.delegation import (
    DelegationChainVerificationResult,
    build_delegation,
    cosign_delegation,
    verify_delegation_chain,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _active_graph(src: str, dst: str) -> dict:
    now = _now()
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
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
            },
            {
                "from": dst,
                "to": src,
                "treaty_id": f"t-{dst}-{src}",
                "status": "active",
                "lifecycle_state": "active",
                "expiry_risk": "low",
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
            },
        ],
        "active_treaties": [
            {
                "treaty_id": f"t-{src}-{dst}",
                "issuer_sovereign_id": src,
                "subject_sovereign_id": dst,
                "scope": {"allowed_roles": ["transactions.read", "balances.read"]},
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
                "signatures": [],
            },
            {
                "treaty_id": f"t-{dst}-{src}",
                "issuer_sovereign_id": dst,
                "subject_sovereign_id": src,
                "scope": {"allowed_roles": ["transactions.read"]},
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
                "signatures": [],
            },
        ],
        "revoked_trust_material": [],
    }


def _terms(caps: list[str] | None = None, days: int = 30) -> AgreementTerms:
    now = _now()
    return AgreementTerms(
        capabilities=caps if caps is not None else ["transactions.read", "balances.read"],
        scope={"delegation": False},
        valid_from=now,
        valid_until=now + timedelta(days=days),
        freshness_commitment=0,
    )


def _make_agreement(
    offerer: str = "alpha",
    responder: str = "beta",
    caps: list[str] | None = None,
    days: int = 30,
) -> tuple[AgreementRecord, nacl.signing.SigningKey, str, nacl.signing.SigningKey, str]:
    """Return (agreement, offerer_sk, offerer_pub_b64, responder_sk, responder_pub_b64)."""
    offerer_kp = generate_keypair()
    responder_kp = generate_keypair()
    graph = _active_graph(offerer, responder)
    terms = _terms(caps, days)
    now = _now()
    offer = build_offer(
        offerer, responder, terms, graph, offerer_kp.private_key,
        issued_by="offerer-key",
        expires_at=now + timedelta(hours=24),
        now=now,
    )
    counter = build_counter(offer, terms, graph, responder_kp.private_key, issued_by="responder-key", now=now)
    record = accept_counter(counter, offer, offerer_kp.private_key, issued_by="offerer-key", now=now)
    return record, offerer_kp.private_key, offerer_kp.public_key_b64, responder_kp.private_key, responder_kp.public_key_b64


def _make_delegation(
    parent: AgreementRecord | DelegatedAgreementRecord,
    delegator_id: str,
    delegate_id: str,
    delegator_key,
    delegate_key,
    delegator_pub: str,
    delegate_pub: str,
    caps: list[str] | None = None,
    days: int = 20,
    *,
    now: datetime | None = None,
) -> DelegatedAgreementRecord:
    """Build a finalized (dual-signed) delegation from parent.

    ``now`` is pinned so callers building multi-hop chains avoid microsecond
    races where the second hop's valid_until > first hop's expires_at.
    """
    ts = now or _now()
    graph_delegator = _active_graph(delegator_id, delegate_id)
    graph_delegate = _active_graph(delegate_id, delegator_id)

    if isinstance(parent, AgreementRecord):
        parent_caps = parent.agreed_terms.capabilities
    else:
        parent_caps = parent.delegated_terms.capabilities

    delegation_caps = caps if caps is not None else parent_caps[:1]  # narrow to first cap

    terms = AgreementTerms(
        capabilities=delegation_caps,
        scope={"delegation": False},
        valid_from=ts,
        valid_until=ts + timedelta(days=days),
        freshness_commitment=0,
    )

    half = build_delegation(
        parent, terms, graph_delegator, delegator_key,
        delegator_sovereign_id=delegator_id,
        delegate_sovereign_id=delegate_id,
        issued_by="delegator-key",
        now=ts,
    )
    return cosign_delegation(half, graph_delegate, delegate_key, issued_by="delegate-key", now=ts)


# ---------------------------------------------------------------------------
# Chain of length 1
# ---------------------------------------------------------------------------


class TestSingleHopRoundTrip:
    def test_build_delegation_produces_half_signed(self):
        agreement, offerer_sk, offerer_pub, _, _ = _make_agreement()
        delegate_kp = generate_keypair()
        graph = _active_graph("alpha", "delegate-x")
        now = _now()
        half = build_delegation(
            agreement, _terms(["transactions.read"], days=20),
            graph, offerer_sk,
            delegator_sovereign_id="alpha",
            delegate_sovereign_id="delegate-x",
            issued_by="offerer-key",
            now=now,
        )
        assert len(half.signatures) == 1
        assert half.parent_id == agreement.agreement_id
        assert half.parent_kind == "agreement"

    def test_cosign_delegation_produces_dual_signed(self):
        agreement, offerer_sk, offerer_pub, _, _ = _make_agreement()
        delegate_kp = generate_keypair()
        graph_d = _active_graph("alpha", "delegate-x")
        graph_del = _active_graph("delegate-x", "alpha")
        now = _now()
        half = build_delegation(
            agreement, _terms(["transactions.read"], days=20),
            graph_d, offerer_sk,
            delegator_sovereign_id="alpha",
            delegate_sovereign_id="delegate-x",
            issued_by="offerer-key",
            now=now,
        )
        finalized = cosign_delegation(half, graph_del, delegate_kp.private_key, issued_by="delegate-key", now=now)
        assert len(finalized.signatures) == 2

    def test_single_hop_chain_verifies(self):
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement()
        delegate_kp = generate_keypair()
        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
        )
        chain = DelegationChain(root=agreement, hops=[finalized])
        result = verify_delegation_chain(
            chain,
            root_offerer_public_keys=[offerer_pub],
            root_responder_public_keys=[responder_pub],
            per_hop_keys={
                "alpha": [offerer_pub],
                "delegate-x": [delegate_kp.public_key_b64],
            },
        )
        assert result.accepted, f"Expected accepted, got {result.reason}"
        assert result.chain_length == 1
        assert result.failed_at_hop is None

    def test_terms_digest_populated(self):
        agreement, offerer_sk, offerer_pub, _, _ = _make_agreement()
        delegate_kp = generate_keypair()
        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
        )
        expected = terms_digest(agreement.agreed_terms)
        assert finalized.parent_terms_digest == expected

    def test_delegate_evidence_populated_after_cosign(self):
        agreement, offerer_sk, _, _, _ = _make_agreement()
        delegate_kp = generate_keypair()
        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            "dummy", delegate_kp.public_key_b64,
        )
        assert finalized.delegate_evidence  # non-empty dict
        assert "verdict" in finalized.delegate_evidence

    def test_parent_id_and_kind_for_agreement_root(self):
        agreement, offerer_sk, _, _, _ = _make_agreement()
        delegate_kp = generate_keypair()
        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            "dummy", delegate_kp.public_key_b64,
        )
        assert finalized.parent_id == agreement.agreement_id
        assert finalized.parent_kind == "agreement"


# ---------------------------------------------------------------------------
# Chain of length 2
# ---------------------------------------------------------------------------


class TestTwoHopChain:
    def test_two_hop_chain_verifies(self):
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement()
        hop1_delegate_kp = generate_keypair()
        hop2_delegate_kp = generate_keypair()
        ts = _now()

        hop1 = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, hop1_delegate_kp.private_key,
            offerer_pub, hop1_delegate_kp.public_key_b64,
            caps=["transactions.read"],
            days=20,
            now=ts,
        )
        hop2 = _make_delegation(
            hop1, "delegate-x", "delegate-y",
            hop1_delegate_kp.private_key, hop2_delegate_kp.private_key,
            hop1_delegate_kp.public_key_b64, hop2_delegate_kp.public_key_b64,
            caps=["transactions.read"],
            days=15,  # narrower than hop1's 20 days
            now=ts,
        )

        chain = DelegationChain(root=agreement, hops=[hop1, hop2])
        result = verify_delegation_chain(
            chain,
            root_offerer_public_keys=[offerer_pub],
            root_responder_public_keys=[responder_pub],
            per_hop_keys={
                "alpha": [offerer_pub],
                "delegate-x": [hop1_delegate_kp.public_key_b64],
                "delegate-y": [hop2_delegate_kp.public_key_b64],
            },
        )
        assert result.accepted, f"Expected accepted, got {result.reason} at hop {result.failed_at_hop}"
        assert result.chain_length == 2

    def test_second_hop_parent_links_to_first(self):
        agreement, offerer_sk, offerer_pub, _, _ = _make_agreement()
        hop1_kp = generate_keypair()
        hop2_kp = generate_keypair()
        ts = _now()

        hop1 = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, hop1_kp.private_key,
            offerer_pub, hop1_kp.public_key_b64,
            caps=["transactions.read"], days=20, now=ts,
        )
        hop2 = _make_delegation(
            hop1, "delegate-x", "delegate-y",
            hop1_kp.private_key, hop2_kp.private_key,
            hop1_kp.public_key_b64, hop2_kp.public_key_b64,
            caps=["transactions.read"], days=15, now=ts,
        )
        assert hop2.parent_id == hop1.delegation_id
        assert hop2.parent_kind == "delegation"

    def test_two_hop_terms_digest_chain(self):
        agreement, offerer_sk, offerer_pub, _, _ = _make_agreement()
        hop1_kp = generate_keypair()
        hop2_kp = generate_keypair()
        ts = _now()

        hop1 = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, hop1_kp.private_key,
            offerer_pub, hop1_kp.public_key_b64,
            caps=["transactions.read"], days=20, now=ts,
        )
        hop2 = _make_delegation(
            hop1, "delegate-x", "delegate-y",
            hop1_kp.private_key, hop2_kp.private_key,
            hop1_kp.public_key_b64, hop2_kp.public_key_b64,
            caps=["transactions.read"], days=15, now=ts,
        )
        assert hop1.parent_terms_digest == terms_digest(agreement.agreed_terms)
        assert hop2.parent_terms_digest == terms_digest(hop1.delegated_terms)


# ---------------------------------------------------------------------------
# Scope enforcement
# ---------------------------------------------------------------------------


class TestScopeEnforcement:
    def test_build_delegation_rejects_widening(self):
        agreement, offerer_sk, _, _, _ = _make_agreement(caps=["transactions.read"])
        delegate_kp = generate_keypair()
        graph = _active_graph("alpha", "delegate-x")
        with pytest.raises(ValueError, match="exceed parent scope"):
            build_delegation(
                agreement,
                _terms(["transactions.read", "balances.read"], days=20),
                graph, offerer_sk,
                delegator_sovereign_id="alpha",
                delegate_sovereign_id="delegate-x",
                issued_by="offerer-key",
            )

    def test_verify_chain_rejects_scope_escalation_at_hop(self):
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement(
            caps=["transactions.read", "balances.read"]
        )
        delegate_kp = generate_keypair()

        # Manually build a delegation with wider caps to test verify
        graph_d = _active_graph("alpha", "delegate-x")
        graph_del = _active_graph("delegate-x", "alpha")
        now = _now()
        narrow_terms = _terms(["transactions.read"], days=20)
        half = build_delegation(
            agreement, narrow_terms, graph_d, offerer_sk,
            delegator_sovereign_id="alpha",
            delegate_sovereign_id="delegate-x",
            issued_by="offerer-key",
            now=now,
        )
        finalized = cosign_delegation(half, graph_del, delegate_kp.private_key, issued_by="delegate-key", now=now)

        # Tamper: replace delegated_terms with wider caps
        tampered = finalized.model_copy(update={
            "delegated_terms": _terms(["transactions.read", "balances.read", "admin.write"], days=20)
        })

        chain = DelegationChain(root=agreement, hops=[tampered])
        result = verify_delegation_chain(
            chain,
            root_offerer_public_keys=[offerer_pub],
            root_responder_public_keys=[responder_pub],
            per_hop_keys={
                "alpha": [offerer_pub],
                "delegate-x": [delegate_kp.public_key_b64],
            },
        )
        assert not result.accepted
        assert result.reason == "scope_escalation"
        assert result.failed_at_hop == 1

    def test_exact_subset_is_allowed(self):
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement(
            caps=["transactions.read", "balances.read"]
        )
        delegate_kp = generate_keypair()
        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
            caps=["transactions.read"],  # strict subset
        )
        chain = DelegationChain(root=agreement, hops=[finalized])
        result = verify_delegation_chain(
            chain,
            root_offerer_public_keys=[offerer_pub],
            root_responder_public_keys=[responder_pub],
            per_hop_keys={
                "alpha": [offerer_pub],
                "delegate-x": [delegate_kp.public_key_b64],
            },
        )
        assert result.accepted

    def test_empty_caps_subset_is_allowed(self):
        """Empty capability set is a valid (degenerate) subset."""
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement(
            caps=["transactions.read"]
        )
        delegate_kp = generate_keypair()
        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
            caps=[],
        )
        chain = DelegationChain(root=agreement, hops=[finalized])
        result = verify_delegation_chain(
            chain,
            root_offerer_public_keys=[offerer_pub],
            root_responder_public_keys=[responder_pub],
            per_hop_keys={
                "alpha": [offerer_pub],
                "delegate-x": [delegate_kp.public_key_b64],
            },
        )
        assert result.accepted

    def test_non_party_delegator_rejected(self):
        agreement, offerer_sk, _, _, _ = _make_agreement()
        delegate_kp = generate_keypair()
        graph = _active_graph("outsider", "delegate-x")
        with pytest.raises(ValueError, match="not a party"):
            build_delegation(
                agreement,
                _terms(["transactions.read"], days=20),
                graph, offerer_sk,
                delegator_sovereign_id="outsider",
                delegate_sovereign_id="delegate-x",
                issued_by="outsider-key",
            )


# ---------------------------------------------------------------------------
# Validity enforcement
# ---------------------------------------------------------------------------


class TestValidityEnforcement:
    def test_build_delegation_rejects_validity_escalation(self):
        agreement, offerer_sk, _, _, _ = _make_agreement(days=30)
        delegate_kp = generate_keypair()
        graph = _active_graph("alpha", "delegate-x")
        with pytest.raises(ValueError, match="valid_until.*exceeds parent"):
            build_delegation(
                agreement,
                _terms(["transactions.read"], days=60),  # wider than parent 30 days
                graph, offerer_sk,
                delegator_sovereign_id="alpha",
                delegate_sovereign_id="delegate-x",
                issued_by="offerer-key",
            )

    def test_verify_chain_rejects_validity_escalation(self):
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement(days=30)
        delegate_kp = generate_keypair()

        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
            caps=["transactions.read"],
            days=20,
        )
        # Tamper expires_at to exceed parent
        far_future = _now() + timedelta(days=365)
        tampered = finalized.model_copy(update={"expires_at": far_future})

        chain = DelegationChain(root=agreement, hops=[tampered])
        result = verify_delegation_chain(
            chain,
            root_offerer_public_keys=[offerer_pub],
            root_responder_public_keys=[responder_pub],
            per_hop_keys={
                "alpha": [offerer_pub],
                "delegate-x": [delegate_kp.public_key_b64],
            },
        )
        assert not result.accepted
        assert result.reason == "validity_escalation"
        assert result.failed_at_hop == 1


# ---------------------------------------------------------------------------
# Digest mismatch
# ---------------------------------------------------------------------------


class TestDigestMismatch:
    def test_tampered_parent_terms_digest(self):
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement()
        delegate_kp = generate_keypair()

        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
        )
        tampered = finalized.model_copy(update={"parent_terms_digest": "a" * 64})

        chain = DelegationChain(root=agreement, hops=[tampered])
        result = verify_delegation_chain(
            chain,
            root_offerer_public_keys=[offerer_pub],
            root_responder_public_keys=[responder_pub],
            per_hop_keys={
                "alpha": [offerer_pub],
                "delegate-x": [delegate_kp.public_key_b64],
            },
        )
        assert not result.accepted
        assert result.reason == "terms_digest_mismatch"
        assert result.failed_at_hop == 1

    def test_parent_id_mismatch_detected(self):
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement()
        delegate_kp = generate_keypair()

        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
        )
        tampered = finalized.model_copy(update={"parent_id": "00000000-0000-0000-0000-000000000000"})

        chain = DelegationChain(root=agreement, hops=[tampered])
        result = verify_delegation_chain(
            chain,
            root_offerer_public_keys=[offerer_pub],
            root_responder_public_keys=[responder_pub],
            per_hop_keys={
                "alpha": [offerer_pub],
                "delegate-x": [delegate_kp.public_key_b64],
            },
        )
        assert not result.accepted
        assert result.reason == "parent_id_mismatch"


# ---------------------------------------------------------------------------
# Signature requirements
# ---------------------------------------------------------------------------


class TestSignatureRequirements:
    def test_no_keys_provided_rejects_with_missing_delegator(self):
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement()
        delegate_kp = generate_keypair()
        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
        )
        chain = DelegationChain(root=agreement, hops=[finalized])
        # Provide no per_hop_keys
        result = verify_delegation_chain(
            chain,
            root_offerer_public_keys=[offerer_pub],
            root_responder_public_keys=[responder_pub],
            per_hop_keys=None,
        )
        assert not result.accepted
        assert result.reason == "missing_delegator_signature"

    def test_wrong_delegator_key_rejected(self):
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement()
        delegate_kp = generate_keypair()
        wrong_kp = generate_keypair()

        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
        )
        chain = DelegationChain(root=agreement, hops=[finalized])
        result = verify_delegation_chain(
            chain,
            root_offerer_public_keys=[offerer_pub],
            root_responder_public_keys=[responder_pub],
            per_hop_keys={
                "alpha": [wrong_kp.public_key_b64],  # wrong key
                "delegate-x": [delegate_kp.public_key_b64],
            },
        )
        assert not result.accepted
        assert result.reason == "invalid_delegator_signature"

    def test_wrong_delegate_key_rejected(self):
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement()
        delegate_kp = generate_keypair()
        wrong_kp = generate_keypair()

        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
        )
        chain = DelegationChain(root=agreement, hops=[finalized])
        result = verify_delegation_chain(
            chain,
            root_offerer_public_keys=[offerer_pub],
            root_responder_public_keys=[responder_pub],
            per_hop_keys={
                "alpha": [offerer_pub],
                "delegate-x": [wrong_kp.public_key_b64],  # wrong key
            },
        )
        assert not result.accepted
        assert result.reason == "invalid_delegate_signature"

    def test_empty_hops_rejected(self):
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement()
        chain = DelegationChain(root=agreement, hops=[])
        result = verify_delegation_chain(
            chain,
            root_offerer_public_keys=[offerer_pub],
            root_responder_public_keys=[responder_pub],
        )
        assert not result.accepted
        assert result.reason == "empty_chain"

    def test_invalid_root_agreement_rejected(self):
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement()
        delegate_kp = generate_keypair()
        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
        )
        chain = DelegationChain(root=agreement, hops=[finalized])
        wrong_kp = generate_keypair()
        result = verify_delegation_chain(
            chain,
            root_offerer_public_keys=[wrong_kp.public_key_b64],  # wrong root key
            root_responder_public_keys=[responder_pub],
            per_hop_keys={
                "alpha": [offerer_pub],
                "delegate-x": [delegate_kp.public_key_b64],
            },
        )
        assert not result.accepted
        assert result.reason == "root_agreement_invalid"


# ---------------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------------


class TestTamperDetection:
    def test_tampered_delegated_terms_invalidates_signatures(self):
        """Tampered delegated_terms → both signatures invalid → invalid_delegator_signature."""
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement()
        delegate_kp = generate_keypair()
        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
        )
        tampered = finalized.model_copy(update={
            "delegated_terms": _terms(["transactions.read"], days=20)
            if finalized.delegated_terms.capabilities != ["transactions.read"]
            else _terms(["balances.read"], days=20)
        })
        chain = DelegationChain(root=agreement, hops=[tampered])
        result = verify_delegation_chain(
            chain,
            root_offerer_public_keys=[offerer_pub],
            root_responder_public_keys=[responder_pub],
            per_hop_keys={
                "alpha": [offerer_pub],
                "delegate-x": [delegate_kp.public_key_b64],
            },
        )
        assert not result.accepted
        # Either scope_escalation (caught before sig check) or invalid signature
        assert result.reason in ("scope_escalation", "invalid_delegator_signature")

    def test_tampered_graph_digest_invalidates_signatures(self):
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement()
        delegate_kp = generate_keypair()
        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
        )
        tampered = finalized.model_copy(update={"graph_digest": "b" * 64})
        chain = DelegationChain(root=agreement, hops=[tampered])
        result = verify_delegation_chain(
            chain,
            root_offerer_public_keys=[offerer_pub],
            root_responder_public_keys=[responder_pub],
            per_hop_keys={
                "alpha": [offerer_pub],
                "delegate-x": [delegate_kp.public_key_b64],
            },
        )
        assert not result.accepted
        assert result.reason == "invalid_delegator_signature"


# ---------------------------------------------------------------------------
# Transport independence
# ---------------------------------------------------------------------------


class TestTransportIndependence:
    def test_json_round_trip_single_hop(self):
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement()
        delegate_kp = generate_keypair()
        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
        )
        # Serialize + deserialize
        raw = finalized.model_dump_json()
        recovered = DelegatedAgreementRecord.model_validate_json(raw)
        # Canonical form should be identical
        assert finalized.to_canonical_json() == recovered.to_canonical_json()

    def test_json_round_trip_chain_verifies(self):
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement()
        delegate_kp = generate_keypair()
        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
        )
        # Round-trip both root and hop
        root_rt = AgreementRecord.model_validate_json(agreement.model_dump_json())
        hop_rt = DelegatedAgreementRecord.model_validate_json(finalized.model_dump_json())
        chain = DelegationChain(root=root_rt, hops=[hop_rt])
        result = verify_delegation_chain(
            chain,
            root_offerer_public_keys=[offerer_pub],
            root_responder_public_keys=[responder_pub],
            per_hop_keys={
                "alpha": [offerer_pub],
                "delegate-x": [delegate_kp.public_key_b64],
            },
        )
        assert result.accepted, f"JSON round-trip failed: {result.reason}"


# ---------------------------------------------------------------------------
# CLI: trust delegate create
# ---------------------------------------------------------------------------


class TestCliDelegateCreate:
    def test_create_produces_half_signed_file(self, tmp_path: Path):
        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement()
        offerer_kp = generate_keypair()

        # Write agreement
        agreement_file = tmp_path / "agreement.json"
        agreement_file.write_text(agreement.model_dump_json(), encoding="utf-8")

        # Write signing key
        key_file = tmp_path / "delegator.key"
        from genesis_mesh.crypto import generate_keypair as gkp
        kp = gkp()
        key_file.write_text(kp.private_key_b64 + "\n", encoding="utf-8")

        # Write graph
        graph_file = tmp_path / "graph.json"
        graph_file.write_text(
            json.dumps(_active_graph("alpha", "delegate-x")), encoding="utf-8"
        )

        output_file = tmp_path / "delegation.json"
        runner = CliRunner()
        result = runner.invoke(delegate, [
            "create",
            "--agreement", str(agreement_file),
            "--from", "alpha",
            "--to", "delegate-x",
            "--capability", "transactions.read",
            "--valid-until", (_now() + timedelta(days=20)).isoformat(),
            "--graph", str(graph_file),
            "--signing-key", str(key_file),
            "--key-id", "delegator-key",
            "--output", str(output_file),
        ])
        assert result.exit_code == 0, result.output
        assert output_file.exists()
        rec = DelegatedAgreementRecord.model_validate_json(output_file.read_text())
        assert len(rec.signatures) == 1
        assert "HALF-SIGNED" in result.output

    def test_widening_exits_nonzero(self, tmp_path: Path):
        agreement, _, _, _, _ = _make_agreement(caps=["transactions.read"])

        agreement_file = tmp_path / "agreement.json"
        agreement_file.write_text(agreement.model_dump_json(), encoding="utf-8")

        from genesis_mesh.crypto import generate_keypair as gkp
        kp = gkp()
        key_file = tmp_path / "key.key"
        key_file.write_text(kp.private_key_b64 + "\n", encoding="utf-8")

        graph_file = tmp_path / "graph.json"
        graph_file.write_text(json.dumps(_active_graph("alpha", "delegate-x")), encoding="utf-8")

        output_file = tmp_path / "del.json"
        runner = CliRunner()
        result = runner.invoke(delegate, [
            "create",
            "--agreement", str(agreement_file),
            "--from", "alpha",
            "--to", "delegate-x",
            "--capability", "transactions.read",
            "--capability", "admin.write",  # not in agreement
            "--valid-until", (_now() + timedelta(days=20)).isoformat(),
            "--graph", str(graph_file),
            "--signing-key", str(key_file),
            "--output", str(output_file),
        ])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# CLI: trust delegate cosign
# ---------------------------------------------------------------------------


class TestCliDelegateCosign:
    def test_cosign_produces_dual_signed_file(self, tmp_path: Path):
        agreement, offerer_sk, offerer_pub, _, _ = _make_agreement()
        from genesis_mesh.crypto import generate_keypair as gkp

        delegator_kp = gkp()
        delegate_kp = gkp()

        graph_d = _active_graph("alpha", "delegate-x")
        now = _now()
        half = build_delegation(
            agreement,
            _terms(["transactions.read"], days=20),
            graph_d, delegator_kp.private_key,
            delegator_sovereign_id="alpha",
            delegate_sovereign_id="delegate-x",
            issued_by="delegator-key",
            now=now,
        )

        delegation_file = tmp_path / "half.json"
        delegation_file.write_text(half.model_dump_json(), encoding="utf-8")

        key_file = tmp_path / "delegate.key"
        key_file.write_text(delegate_kp.private_key_b64 + "\n", encoding="utf-8")

        graph_file = tmp_path / "graph.json"
        graph_file.write_text(json.dumps(_active_graph("delegate-x", "alpha")), encoding="utf-8")

        output_file = tmp_path / "final.json"
        runner = CliRunner()
        result = runner.invoke(delegate, [
            "cosign",
            "--delegation", str(delegation_file),
            "--graph", str(graph_file),
            "--signing-key", str(key_file),
            "--key-id", "delegate-key",
            "--output", str(output_file),
        ])
        assert result.exit_code == 0, result.output
        assert output_file.exists()
        rec = DelegatedAgreementRecord.model_validate_json(output_file.read_text())
        assert len(rec.signatures) == 2
        assert "DUAL-SIGNED" in result.output


# ---------------------------------------------------------------------------
# CLI: trust delegate verify
# ---------------------------------------------------------------------------


class TestCliDelegateVerify:
    def test_verify_valid_chain_exits_zero(self, tmp_path: Path):
        from genesis_mesh.crypto import generate_keypair as gkp

        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement()
        delegate_kp = gkp()

        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
        )

        agreement_file = tmp_path / "agreement.json"
        agreement_file.write_text(agreement.model_dump_json(), encoding="utf-8")
        delegation_file = tmp_path / "delegation.json"
        delegation_file.write_text(finalized.model_dump_json(), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(delegate, [
            "verify",
            "--agreement", str(agreement_file),
            "--delegation", str(delegation_file),
            "--offerer-public-key", offerer_pub,
            "--responder-public-key", responder_pub,
            "--key", f"alpha:{offerer_pub}",
            "--key", f"delegate-x:{delegate_kp.public_key_b64}",
        ])
        assert result.exit_code == 0, result.output
        assert "OK" in result.output

    def test_verify_wrong_key_exits_one(self, tmp_path: Path):
        from genesis_mesh.crypto import generate_keypair as gkp

        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement()
        delegate_kp = gkp()
        wrong_kp = gkp()

        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
        )

        agreement_file = tmp_path / "agreement.json"
        agreement_file.write_text(agreement.model_dump_json(), encoding="utf-8")
        delegation_file = tmp_path / "delegation.json"
        delegation_file.write_text(finalized.model_dump_json(), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(delegate, [
            "verify",
            "--agreement", str(agreement_file),
            "--delegation", str(delegation_file),
            "--offerer-public-key", offerer_pub,
            "--responder-public-key", responder_pub,
            "--key", f"alpha:{offerer_pub}",
            "--key", f"delegate-x:{wrong_kp.public_key_b64}",  # wrong
        ])
        assert result.exit_code == 1
        assert "FAIL" in result.output

    def test_verify_json_output_format(self, tmp_path: Path):
        from genesis_mesh.crypto import generate_keypair as gkp

        agreement, offerer_sk, offerer_pub, responder_sk, responder_pub = _make_agreement()
        delegate_kp = gkp()

        finalized = _make_delegation(
            agreement, "alpha", "delegate-x",
            offerer_sk, delegate_kp.private_key,
            offerer_pub, delegate_kp.public_key_b64,
        )

        agreement_file = tmp_path / "agreement.json"
        agreement_file.write_text(agreement.model_dump_json(), encoding="utf-8")
        delegation_file = tmp_path / "delegation.json"
        delegation_file.write_text(finalized.model_dump_json(), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(delegate, [
            "verify",
            "--agreement", str(agreement_file),
            "--delegation", str(delegation_file),
            "--offerer-public-key", offerer_pub,
            "--responder-public-key", responder_pub,
            "--key", f"alpha:{offerer_pub}",
            "--key", f"delegate-x:{delegate_kp.public_key_b64}",
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["accepted"] is True
        assert data["reason"] == "accepted"
        assert "chain_length" in data
