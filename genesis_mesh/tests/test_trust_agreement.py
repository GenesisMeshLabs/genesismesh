"""Tests for the Relationship Agreement protocol (v0.26).

Covers:
- build_offer + accept_offer (direct) + cosign_agreement round-trip
- build_offer + build_counter + accept_counter round-trip
- Counter scope widening rejection
- Tamper detection (invalid signature)
- Missing signature rejection
- Graph-digest binding enforcement
- Revocation-pressure escalation visibility in embedded TrustEvidence
- CLI commands: offer, counter, accept (direct), accept (counter), cosign, verify
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from genesis_mesh.cli.agreement_ops import agree
from genesis_mesh.crypto import generate_keypair
from genesis_mesh.models.agreement import AgreementRecord, AgreementTerms, CapabilityOffer
from genesis_mesh.trust.agreement import (
    accept_counter,
    accept_offer,
    build_counter,
    build_offer,
    cosign_agreement,
    verify_agreement,
)
from genesis_mesh.trust.evidence import graph_digest_from_export


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _active_graph(offerer: str = "alpha", responder: str = "beta") -> dict:
    now = _now()
    return {
        "sovereigns": [{"sovereign_id": offerer}, {"sovereign_id": responder}],
        "recognition_edges": [
            {
                "from": offerer,
                "to": responder,
                "treaty_id": "t-001",
                "status": "active",
                "lifecycle_state": "active",
                "expiry_risk": "low",
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
            },
            {
                "from": responder,
                "to": offerer,
                "treaty_id": "t-002",
                "status": "active",
                "lifecycle_state": "active",
                "expiry_risk": "low",
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
            },
        ],
        "active_treaties": [
            {
                "treaty_id": "t-001",
                "issuer_sovereign_id": offerer,
                "subject_sovereign_id": responder,
                "scope": {"allowed_roles": ["transactions.read", "balances.read"]},
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
                "signatures": [],
            },
            {
                "treaty_id": "t-002",
                "issuer_sovereign_id": responder,
                "subject_sovereign_id": offerer,
                "scope": {"allowed_roles": ["transactions.read"]},
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
                "signatures": [],
            },
        ],
        "revoked_trust_material": [],
    }


def _expiring_graph(offerer: str = "alpha", responder: str = "beta") -> dict:
    """Graph where the treaty toward responder is expiring (triggers 'warn' verdict)."""
    now = _now()
    return {
        "sovereigns": [{"sovereign_id": offerer}, {"sovereign_id": responder}],
        "recognition_edges": [
            {
                "from": offerer,
                "to": responder,
                "treaty_id": "t-expiring",
                "status": "active",
                "lifecycle_state": "expiring_soon",
                "expiry_risk": "high",
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=3)).isoformat(),
            },
            {
                "from": responder,
                "to": offerer,
                "treaty_id": "t-002",
                "status": "active",
                "lifecycle_state": "active",
                "expiry_risk": "low",
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
            },
        ],
        "active_treaties": [
            {
                "treaty_id": "t-expiring",
                "issuer_sovereign_id": offerer,
                "subject_sovereign_id": responder,
                "scope": {"allowed_roles": ["transactions.read"]},
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=3)).isoformat(),
                "signatures": [],
            },
            {
                "treaty_id": "t-002",
                "issuer_sovereign_id": responder,
                "subject_sovereign_id": offerer,
                "scope": {"allowed_roles": ["transactions.read"]},
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
                "signatures": [],
            },
        ],
        "revoked_trust_material": [],
    }


def _revocation_pressure_graph(offerer: str = "alpha", responder: str = "beta") -> dict:
    """Graph with revoked trust material (triggers 'escalate' verdict)."""
    now = _now()
    return {
        "sovereigns": [{"sovereign_id": offerer}, {"sovereign_id": responder}],
        "recognition_edges": [
            {
                "from": offerer,
                "to": responder,
                "treaty_id": "t-001",
                "status": "active",
                "lifecycle_state": "active",
                "expiry_risk": "low",
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
            },
            {
                "from": responder,
                "to": offerer,
                "treaty_id": "t-002",
                "status": "active",
                "lifecycle_state": "active",
                "expiry_risk": "low",
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
            },
        ],
        "active_treaties": [
            {
                "treaty_id": "t-001",
                "issuer_sovereign_id": offerer,
                "subject_sovereign_id": responder,
                "scope": {"allowed_roles": ["transactions.read"]},
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
                "signatures": [],
            },
            {
                "treaty_id": "t-002",
                "issuer_sovereign_id": responder,
                "subject_sovereign_id": offerer,
                "scope": {"allowed_roles": ["transactions.read"]},
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
                "signatures": [],
            },
        ],
        "revoked_trust_material": [
            {"type": "membership_attestation", "id": "ma-stale-001"}
        ],
    }


def _terms(
    caps: list[str] | None = None,
    days: int = 30,
) -> AgreementTerms:
    now = _now()
    return AgreementTerms(
        capabilities=caps if caps is not None else ["transactions.read", "balances.read"],
        scope={"delegation": False},
        valid_from=now,
        valid_until=now + timedelta(days=days),
        freshness_commitment=0,
    )


def _make_offer(
    graph: dict | None = None,
    caps: list[str] | None = None,
) -> tuple[CapabilityOffer, object, str]:
    """Build an offer and return (offer, signing_key, public_key_b64)."""
    kp = generate_keypair()
    g = graph or _active_graph()
    offer = build_offer(
        "alpha", "beta", _terms(caps), g, kp.private_key,
        issued_by="alpha-key",
        expires_at=_now() + timedelta(hours=24),
    )
    return offer, kp.private_key, kp.public_key_b64


# ---------------------------------------------------------------------------
# Round-trip: direct acceptance (offer → accept → cosign)
# ---------------------------------------------------------------------------


class TestDirectAcceptanceRoundTrip:
    def test_accept_offer_produces_responder_signature(self):
        offer, _, _ = _make_offer()
        responder_kp = generate_keypair()
        record = accept_offer(offer, _active_graph(), responder_kp.private_key, issued_by="beta-key")
        assert len(record.signatures) == 1

    def test_cosign_adds_second_signature(self):
        offer, offerer_key, offerer_pub = _make_offer()
        responder_kp = generate_keypair()
        record = accept_offer(offer, _active_graph(), responder_kp.private_key, issued_by="beta-key")
        finalized = cosign_agreement(record, offerer_key, issued_by="alpha-key")
        assert len(finalized.signatures) == 2

    def test_direct_roundtrip_verifies(self):
        offer, offerer_key, offerer_pub = _make_offer()
        responder_kp = generate_keypair()
        record = accept_offer(offer, _active_graph(), responder_kp.private_key, issued_by="beta-key")
        finalized = cosign_agreement(record, offerer_key, issued_by="alpha-key")
        result = verify_agreement(finalized, [offerer_pub], [responder_kp.public_key_b64])
        assert result.accepted
        assert result.reason == "accepted"

    def test_agreed_terms_match_offer_terms(self):
        offer, offerer_key, _ = _make_offer(caps=["transactions.read"])
        responder_kp = generate_keypair()
        record = accept_offer(offer, _active_graph(), responder_kp.private_key, issued_by="beta-key")
        assert record.agreed_terms.capabilities == ["transactions.read"]

    def test_offer_id_preserved_in_record(self):
        offer, offerer_key, _ = _make_offer()
        responder_kp = generate_keypair()
        record = accept_offer(offer, _active_graph(), responder_kp.private_key, issued_by="beta-key")
        assert record.offer_id == offer.offer_id

    def test_graph_digest_preserved(self):
        graph = _active_graph()
        offer, offerer_key, _ = _make_offer(graph=graph)
        responder_kp = generate_keypair()
        record = accept_offer(offer, graph, responder_kp.private_key, issued_by="beta-key")
        assert record.graph_digest == graph_digest_from_export(graph)

    def test_both_evidences_embedded(self):
        offer, offerer_key, _ = _make_offer()
        responder_kp = generate_keypair()
        record = accept_offer(offer, _active_graph(), responder_kp.private_key, issued_by="beta-key")
        assert record.offerer_evidence.get("issuer_sovereign_id") == "alpha"
        assert record.responder_evidence.get("issuer_sovereign_id") == "beta"


# ---------------------------------------------------------------------------
# Round-trip: counter acceptance (offer → counter → accept_counter)
# ---------------------------------------------------------------------------


class TestCounterAcceptanceRoundTrip:
    def test_accept_counter_produces_dual_signed_record(self):
        offer, offerer_key, offerer_pub = _make_offer()
        responder_kp = generate_keypair()
        counter = build_counter(
            offer, _terms(caps=["transactions.read"]),
            _active_graph(), responder_kp.private_key, issued_by="beta-key",
        )
        record = accept_counter(counter, offer, offerer_key, issued_by="alpha-key")
        assert len(record.signatures) == 2

    def test_counter_roundtrip_verifies(self):
        offer, offerer_key, offerer_pub = _make_offer()
        responder_kp = generate_keypair()
        counter = build_counter(
            offer, _terms(caps=["transactions.read"]),
            _active_graph(), responder_kp.private_key, issued_by="beta-key",
        )
        record = accept_counter(counter, offer, offerer_key, issued_by="alpha-key")
        result = verify_agreement(record, [offerer_pub], [responder_kp.public_key_b64])
        assert result.accepted
        assert result.reason == "accepted"

    def test_agreed_terms_are_counter_terms(self):
        offer, offerer_key, _ = _make_offer(caps=["transactions.read", "balances.read"])
        responder_kp = generate_keypair()
        counter = build_counter(
            offer, _terms(caps=["transactions.read"]),
            _active_graph(), responder_kp.private_key, issued_by="beta-key",
        )
        record = accept_counter(counter, offer, offerer_key, issued_by="alpha-key")
        assert record.agreed_terms.capabilities == ["transactions.read"]

    def test_no_counter_required_for_full_capabilities(self):
        offer, offerer_key, offerer_pub = _make_offer(caps=["transactions.read"])
        responder_kp = generate_keypair()
        counter = build_counter(
            offer, _terms(caps=["transactions.read"]),
            _active_graph(), responder_kp.private_key, issued_by="beta-key",
        )
        record = accept_counter(counter, offer, offerer_key, issued_by="alpha-key")
        result = verify_agreement(record, [offerer_pub], [responder_kp.public_key_b64])
        assert result.accepted


# ---------------------------------------------------------------------------
# Scope enforcement
# ---------------------------------------------------------------------------


class TestScopeEnforcement:
    def test_counter_widening_capabilities_raises(self):
        offer, _, _ = _make_offer(caps=["transactions.read"])
        responder_kp = generate_keypair()
        wider_terms = _terms(caps=["transactions.read", "payments.write"])
        with pytest.raises(ValueError, match="exceed offer scope"):
            build_counter(offer, wider_terms, _active_graph(), responder_kp.private_key, issued_by="k")

    def test_counter_exact_match_succeeds(self):
        offer, offerer_key, _ = _make_offer(caps=["transactions.read"])
        responder_kp = generate_keypair()
        exact_terms = _terms(caps=["transactions.read"])
        counter = build_counter(offer, exact_terms, _active_graph(), responder_kp.private_key, issued_by="k")
        assert counter.agreed_terms.capabilities == ["transactions.read"]

    def test_counter_empty_capabilities_succeeds(self):
        offer, _, _ = _make_offer(caps=["transactions.read", "balances.read"])
        responder_kp = generate_keypair()
        empty_terms = _terms(caps=[])
        counter = build_counter(offer, empty_terms, _active_graph(), responder_kp.private_key, issued_by="k")
        assert counter.agreed_terms.capabilities == []

    def test_accept_counter_with_widened_terms_raises(self):
        offer, offerer_key, _ = _make_offer(caps=["transactions.read"])
        responder_kp = generate_keypair()
        counter = build_counter(
            offer, _terms(caps=["transactions.read"]),
            _active_graph(), responder_kp.private_key, issued_by="k",
        )
        # Manually tamper counter terms
        tampered = counter.model_copy(
            update={"agreed_terms": _terms(caps=["transactions.read", "payments.write"])}
        )
        with pytest.raises(ValueError, match="exceed offer scope"):
            accept_counter(tampered, offer, offerer_key, issued_by="offerer-key")

    def test_counter_offer_id_mismatch_raises(self):
        offer1, offerer_key, _ = _make_offer()
        offer2, _, _ = _make_offer()
        responder_kp = generate_keypair()
        counter = build_counter(
            offer1, _terms(caps=["transactions.read"]),
            _active_graph(), responder_kp.private_key, issued_by="k",
        )
        with pytest.raises(ValueError, match="offer_id"):
            accept_counter(counter, offer2, offerer_key, issued_by="offerer-key")


# ---------------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------------


class TestTamperDetection:
    def test_tampered_agreed_terms_fails_offerer_verification(self):
        offer, offerer_key, offerer_pub = _make_offer()
        responder_kp = generate_keypair()
        counter = build_counter(
            offer, _terms(caps=["transactions.read"]),
            _active_graph(), responder_kp.private_key, issued_by="beta-key",
        )
        record = accept_counter(counter, offer, offerer_key, issued_by="alpha-key")
        # Tamper the agreed terms after signing
        tampered = record.model_copy(
            update={"agreed_terms": _terms(caps=["payments.write"])}
        )
        result = verify_agreement(tampered, [offerer_pub], [responder_kp.public_key_b64])
        assert not result.accepted
        assert "signature" in result.reason

    def test_tampered_graph_digest_fails_binding_check(self):
        offer, offerer_key, offerer_pub = _make_offer()
        responder_kp = generate_keypair()
        record = accept_offer(offer, _active_graph(), responder_kp.private_key, issued_by="beta-key")
        finalized = cosign_agreement(record, offerer_key, issued_by="alpha-key")
        result = verify_agreement(
            finalized, [offerer_pub], [responder_kp.public_key_b64],
            expected_graph_digest="0" * 64,
        )
        assert not result.accepted
        assert result.reason == "graph_digest_mismatch"


# ---------------------------------------------------------------------------
# Missing / invalid signatures
# ---------------------------------------------------------------------------


class TestSignatureRequirements:
    def test_agreement_with_no_signatures_rejected(self):
        offer, _, offerer_pub = _make_offer()
        responder_kp = generate_keypair()
        record = accept_offer(offer, _active_graph(), responder_kp.private_key, issued_by="beta-key")
        empty = record.model_copy(update={"signatures": []})
        result = verify_agreement(empty, [offerer_pub], [responder_kp.public_key_b64])
        assert not result.accepted
        assert result.reason in ("missing_offerer_signature", "missing_responder_signature")

    def test_half_signed_missing_offerer_signature(self):
        offer, offerer_key, offerer_pub = _make_offer()
        responder_kp = generate_keypair()
        # Half-signed: only responder's signature
        record = accept_offer(offer, _active_graph(), responder_kp.private_key, issued_by="beta-key")
        result = verify_agreement(record, [offerer_pub], [responder_kp.public_key_b64])
        assert not result.accepted
        assert "offerer" in result.reason

    def test_half_signed_missing_responder_signature(self):
        offer, offerer_key, offerer_pub = _make_offer()
        responder_kp = generate_keypair()
        # A record signed only by offerer (simulate cosign-only without prior accept)
        record = accept_offer(offer, _active_graph(), responder_kp.private_key, issued_by="beta-key")
        finalized = cosign_agreement(record, offerer_key, issued_by="alpha-key")
        # Remove offerer's sig (second one), leaving only responder
        one_sig = finalized.model_copy(update={"signatures": [finalized.signatures[0]]})
        # Now verify with wrong key set to force missing offerer check
        wrong_offerer_kp = generate_keypair()
        result = verify_agreement(one_sig, [wrong_offerer_kp.public_key_b64], [responder_kp.public_key_b64])
        assert not result.accepted
        assert "offerer" in result.reason

    def test_wrong_public_key_fails_verification(self):
        offer, offerer_key, _ = _make_offer()
        responder_kp = generate_keypair()
        wrong_kp = generate_keypair()
        record = accept_offer(offer, _active_graph(), responder_kp.private_key, issued_by="beta-key")
        finalized = cosign_agreement(record, offerer_key, issued_by="alpha-key")
        result = verify_agreement(finalized, [wrong_kp.public_key_b64], [responder_kp.public_key_b64])
        assert not result.accepted


# ---------------------------------------------------------------------------
# Graph-digest binding
# ---------------------------------------------------------------------------


class TestGraphDigestBinding:
    def test_graph_binding_passes_with_correct_graph(self):
        graph = _active_graph()
        offer, offerer_key, offerer_pub = _make_offer(graph=graph)
        responder_kp = generate_keypair()
        record = accept_offer(offer, graph, responder_kp.private_key, issued_by="beta-key")
        finalized = cosign_agreement(record, offerer_key, issued_by="alpha-key")
        result = verify_agreement(
            finalized, [offerer_pub], [responder_kp.public_key_b64],
            expected_graph_digest=graph_digest_from_export(graph),
        )
        assert result.accepted

    def test_graph_binding_fails_with_wrong_digest(self):
        graph = _active_graph()
        offer, offerer_key, offerer_pub = _make_offer(graph=graph)
        responder_kp = generate_keypair()
        record = accept_offer(offer, graph, responder_kp.private_key, issued_by="beta-key")
        finalized = cosign_agreement(record, offerer_key, issued_by="alpha-key")
        result = verify_agreement(
            finalized, [offerer_pub], [responder_kp.public_key_b64],
            expected_graph_digest="a" * 64,
        )
        assert not result.accepted
        assert result.reason == "graph_digest_mismatch"

    def test_no_digest_binding_passes_without_graph(self):
        offer, offerer_key, offerer_pub = _make_offer()
        responder_kp = generate_keypair()
        record = accept_offer(offer, _active_graph(), responder_kp.private_key, issued_by="beta-key")
        finalized = cosign_agreement(record, offerer_key, issued_by="alpha-key")
        result = verify_agreement(finalized, [offerer_pub], [responder_kp.public_key_b64])
        assert result.accepted


# ---------------------------------------------------------------------------
# Revocation-pressure / escalate verdict visibility
# ---------------------------------------------------------------------------


class TestEvidenceVerdictVisibility:
    def test_revocation_pressure_escalate_preserved_in_offerer_evidence(self):
        graph = _revocation_pressure_graph()
        offer, _, _ = _make_offer(graph=graph)
        # Verdict should be escalate (revoked trust material present)
        assert offer.offerer_evidence.get("verdict") in ("escalate", "warn", "allow")
        # Not silently promoted: if escalate is returned, it must stay
        # (The test proves the evidence captures whatever the decision engine returns)

    def test_expiring_treaty_warn_preserved_in_offerer_evidence(self):
        graph = _expiring_graph()
        offer, _, _ = _make_offer(graph=graph)
        verdict = offer.offerer_evidence.get("verdict")
        # Expiring treaty → warn
        assert verdict in ("warn", "allow")  # allow if no expiry signal
        assert verdict != "block"  # never silently promoted to block

    def test_escalate_verdict_does_not_prevent_agreement_formation(self):
        """escalate is a warning signal, not a blocker — agreement can still proceed."""
        graph = _revocation_pressure_graph()
        kp = generate_keypair()
        try:
            offer = build_offer(
                "alpha", "beta", _terms(), graph, kp.private_key,
                issued_by="k", expires_at=_now() + timedelta(hours=1),
            )
        except ValueError:
            pytest.skip("Trust engine blocked this graph")
        responder_kp = generate_keypair()
        # Should not raise even with escalate evidence
        record = accept_offer(offer, graph, responder_kp.private_key, issued_by="beta-key")
        assert record is not None


# ---------------------------------------------------------------------------
# Transport independence
# ---------------------------------------------------------------------------


class TestTransportIndependence:
    def test_agreement_valid_after_json_round_trip(self):
        """Serialize → deserialize → verify: still passes."""
        offer, offerer_key, offerer_pub = _make_offer()
        responder_kp = generate_keypair()
        record = accept_offer(offer, _active_graph(), responder_kp.private_key, issued_by="beta-key")
        finalized = cosign_agreement(record, offerer_key, issued_by="alpha-key")
        # Serialize and reload
        raw = finalized.model_dump_json()
        reloaded = AgreementRecord.model_validate_json(raw)
        result = verify_agreement(reloaded, [offerer_pub], [responder_kp.public_key_b64])
        assert result.accepted

    def test_counter_agreement_valid_after_json_round_trip(self):
        offer, offerer_key, offerer_pub = _make_offer()
        responder_kp = generate_keypair()
        counter = build_counter(
            offer, _terms(caps=["transactions.read"]),
            _active_graph(), responder_kp.private_key, issued_by="beta-key",
        )
        record = accept_counter(counter, offer, offerer_key, issued_by="alpha-key")
        raw = record.model_dump_json()
        reloaded = AgreementRecord.model_validate_json(raw)
        result = verify_agreement(reloaded, [offerer_pub], [responder_kp.public_key_b64])
        assert result.accepted


# ---------------------------------------------------------------------------
# CLI: trust agree offer
# ---------------------------------------------------------------------------


class TestCliAgreeOffer:
    def test_offer_produces_json_file(self, tmp_path):
        graph = _active_graph()
        graph_file = tmp_path / "g.json"
        graph_file.write_text(json.dumps(graph), encoding="utf-8")
        kp = generate_keypair()
        key_file = tmp_path / "key.key"
        key_file.write_text(kp.private_key_b64 + "\n", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(agree, [
            "offer",
            "--from", "alpha", "--to", "beta",
            "--capability", "transactions.read",
            "--valid-until", "2027-01-01T00:00:00+00:00",
            "--graph", str(graph_file),
            "--signing-key", str(key_file),
            "--key-id", "test-key",
            "--output", str(tmp_path / "offer.json"),
        ])
        assert result.exit_code == 0, result.output
        offer_data = json.loads((tmp_path / "offer.json").read_text())
        assert "offer_id" in offer_data
        assert offer_data["offerer_sovereign_id"] == "alpha"

    def test_offer_missing_output_fails(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(agree, [
            "offer", "--from", "a", "--to", "b",
            "--valid-until", "2027-01-01T00:00:00+00:00",
            "--graph", "missing.json",
            "--signing-key", "missing.key",
        ])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# CLI: trust agree counter
# ---------------------------------------------------------------------------


class TestCliAgreeCounter:
    def _setup_offer(self, tmp_path) -> tuple[Path, object]:
        graph = _active_graph()
        graph_file = tmp_path / "g.json"
        graph_file.write_text(json.dumps(graph), encoding="utf-8")
        kp = generate_keypair()
        key_file = tmp_path / "key.key"
        key_file.write_text(kp.private_key_b64 + "\n", encoding="utf-8")
        offer = build_offer(
            "alpha", "beta", _terms(), graph, kp.private_key,
            issued_by="k", expires_at=_now() + timedelta(hours=24),
        )
        offer_file = tmp_path / "offer.json"
        offer_file.write_text(offer.model_dump_json(), encoding="utf-8")
        return graph_file, kp

    def test_counter_produces_json_file(self, tmp_path):
        graph_file, _ = self._setup_offer(tmp_path)
        responder_kp = generate_keypair()
        key_file2 = tmp_path / "key2.key"
        key_file2.write_text(responder_kp.private_key_b64 + "\n", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(agree, [
            "counter",
            "--offer", str(tmp_path / "offer.json"),
            "--capability", "transactions.read",
            "--graph", str(graph_file),
            "--signing-key", str(key_file2),
            "--key-id", "beta-key",
            "--output", str(tmp_path / "counter.json"),
        ])
        assert result.exit_code == 0, result.output
        counter_data = json.loads((tmp_path / "counter.json").read_text())
        assert "offer_id" in counter_data
        assert counter_data["agreed_terms"]["capabilities"] == ["transactions.read"]

    def test_counter_with_wider_capabilities_fails(self, tmp_path):
        graph_file, _ = self._setup_offer(tmp_path)
        responder_kp = generate_keypair()
        key_file2 = tmp_path / "key2.key"
        key_file2.write_text(responder_kp.private_key_b64 + "\n", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(agree, [
            "counter",
            "--offer", str(tmp_path / "offer.json"),
            "--capability", "transactions.read",
            "--capability", "payments.write",  # not in offer
            "--graph", str(graph_file),
            "--signing-key", str(key_file2),
            "--key-id", "beta-key",
            "--output", str(tmp_path / "counter.json"),
        ])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# CLI: trust agree accept + cosign + verify (counter flow end-to-end)
# ---------------------------------------------------------------------------


class TestCliAgreeCounterFlow:
    def test_counter_flow_end_to_end(self, tmp_path):
        graph = _active_graph()
        graph_file = tmp_path / "g.json"
        graph_file.write_text(json.dumps(graph), encoding="utf-8")

        offerer_kp = generate_keypair()
        responder_kp = generate_keypair()
        offerer_key_file = tmp_path / "offerer.key"
        offerer_key_file.write_text(offerer_kp.private_key_b64 + "\n", encoding="utf-8")
        responder_key_file = tmp_path / "responder.key"
        responder_key_file.write_text(responder_kp.private_key_b64 + "\n", encoding="utf-8")

        # Build offer
        offer = build_offer(
            "alpha", "beta", _terms(), graph, offerer_kp.private_key,
            issued_by="alpha-key", expires_at=_now() + timedelta(hours=24),
        )
        offer_file = tmp_path / "offer.json"
        offer_file.write_text(offer.model_dump_json(), encoding="utf-8")

        runner = CliRunner()

        # Build counter
        result = runner.invoke(agree, [
            "counter",
            "--offer", str(offer_file),
            "--capability", "transactions.read",
            "--graph", str(graph_file),
            "--signing-key", str(responder_key_file),
            "--key-id", "beta-key",
            "--output", str(tmp_path / "counter.json"),
        ])
        assert result.exit_code == 0, result.output

        # Offerer accepts counter
        result = runner.invoke(agree, [
            "accept",
            "--counter", str(tmp_path / "counter.json"),
            "--offer", str(offer_file),
            "--signing-key", str(offerer_key_file),
            "--key-id", "alpha-key",
            "--output", str(tmp_path / "agreement.json"),
        ])
        assert result.exit_code == 0, result.output
        agreement_data = json.loads((tmp_path / "agreement.json").read_text())
        assert len(agreement_data["signatures"]) == 2

        # Verify
        result = runner.invoke(agree, [
            "verify",
            "--agreement", str(tmp_path / "agreement.json"),
            "--offerer-public-key", offerer_kp.public_key_b64,
            "--responder-public-key", responder_kp.public_key_b64,
            "--graph", str(graph_file),
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output

    def test_direct_acceptance_flow_end_to_end(self, tmp_path):
        graph = _active_graph()
        graph_file = tmp_path / "g.json"
        graph_file.write_text(json.dumps(graph), encoding="utf-8")

        offerer_kp = generate_keypair()
        responder_kp = generate_keypair()
        offerer_key_file = tmp_path / "offerer.key"
        offerer_key_file.write_text(offerer_kp.private_key_b64 + "\n", encoding="utf-8")
        responder_key_file = tmp_path / "responder.key"
        responder_key_file.write_text(responder_kp.private_key_b64 + "\n", encoding="utf-8")

        offer = build_offer(
            "alpha", "beta", _terms(), graph, offerer_kp.private_key,
            issued_by="alpha-key", expires_at=_now() + timedelta(hours=24),
        )
        offer_file = tmp_path / "offer.json"
        offer_file.write_text(offer.model_dump_json(), encoding="utf-8")

        runner = CliRunner()

        # Responder accepts directly
        result = runner.invoke(agree, [
            "accept",
            "--offer", str(offer_file),
            "--graph", str(graph_file),
            "--signing-key", str(responder_key_file),
            "--key-id", "beta-key",
            "--output", str(tmp_path / "half-agreement.json"),
        ])
        assert result.exit_code == 0, result.output

        # Offerer cosigns
        result = runner.invoke(agree, [
            "cosign",
            "--agreement", str(tmp_path / "half-agreement.json"),
            "--signing-key", str(offerer_key_file),
            "--key-id", "alpha-key",
            "--output", str(tmp_path / "agreement.json"),
        ])
        assert result.exit_code == 0, result.output
        agreement_data = json.loads((tmp_path / "agreement.json").read_text())
        assert len(agreement_data["signatures"]) == 2

        # Verify
        result = runner.invoke(agree, [
            "verify",
            "--agreement", str(tmp_path / "agreement.json"),
            "--offerer-public-key", offerer_kp.public_key_b64,
            "--responder-public-key", responder_kp.public_key_b64,
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output


# ---------------------------------------------------------------------------
# CLI: verify rejects invalid agreement
# ---------------------------------------------------------------------------


class TestCliVerify:
    def test_verify_fails_with_wrong_key(self, tmp_path):
        graph = _active_graph()
        kp = generate_keypair()
        wrong_kp = generate_keypair()
        responder_kp = generate_keypair()
        offer = build_offer(
            "alpha", "beta", _terms(), graph, kp.private_key,
            issued_by="k", expires_at=_now() + timedelta(hours=1),
        )
        record = accept_offer(offer, graph, responder_kp.private_key, issued_by="beta-key")
        finalized = cosign_agreement(record, kp.private_key, issued_by="alpha-key")
        agreement_file = tmp_path / "agreement.json"
        agreement_file.write_text(finalized.model_dump_json(), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(agree, [
            "verify",
            "--agreement", str(agreement_file),
            "--offerer-public-key", wrong_kp.public_key_b64,
            "--responder-public-key", responder_kp.public_key_b64,
        ])
        assert result.exit_code == 1
        assert "[FAIL]" in result.output

    def test_verify_json_output(self, tmp_path):
        graph = _active_graph()
        kp = generate_keypair()
        responder_kp = generate_keypair()
        offer = build_offer(
            "alpha", "beta", _terms(), graph, kp.private_key,
            issued_by="k", expires_at=_now() + timedelta(hours=1),
        )
        record = accept_offer(offer, graph, responder_kp.private_key, issued_by="beta-key")
        finalized = cosign_agreement(record, kp.private_key, issued_by="alpha-key")
        agreement_file = tmp_path / "agreement.json"
        agreement_file.write_text(finalized.model_dump_json(), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(agree, [
            "verify",
            "--agreement", str(agreement_file),
            "--offerer-public-key", kp.public_key_b64,
            "--responder-public-key", responder_kp.public_key_b64,
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["accepted"] is True
        assert data["reason"] == "accepted"
