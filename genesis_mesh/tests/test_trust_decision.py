"""Tests for the trust decision engine and TrustEvidence records."""

from __future__ import annotations

from datetime import datetime, timezone

from genesis_mesh.crypto import generate_keypair
from genesis_mesh.trust import (
    evaluate_trust_decision,
    build_trust_evidence,
    graph_digest_from_export,
    verify_trust_evidence,
)
from genesis_mesh.trust.decision import TrustDecision
from genesis_mesh.trust.evidence import EvidenceVerificationResult
from genesis_mesh.models.evidence import TrustEvidence


# ---------------------------------------------------------------------------
# Graph fixtures
# ---------------------------------------------------------------------------

def _active_graph() -> dict:
    """Minimal graph with one active treaty: sovereign-a -> sovereign-b."""
    return {
        "sovereigns": [
            {"sovereign_id": "sovereign-a"},
            {"sovereign_id": "sovereign-b"},
        ],
        "recognition_edges": [
            {
                "from": "sovereign-a",
                "to": "sovereign-b",
                "treaty_id": "treaty-a-b",
                "status": "active",
                "lifecycle_state": "active",
                "expiry_risk": False,
                "valid_from": "2026-01-01T00:00:00+00:00",
                "expires_at": "2027-01-01T00:00:00+00:00",
            }
        ],
        "active_treaties": [
            {
                "treaty_id": "treaty-a-b",
                "issuer_sovereign_id": "sovereign-a",
                "subject_sovereign_id": "sovereign-b",
                "scope": {"allowed_roles": [], "accepted_statuses": ["active"], "claims": {}},
                "status": "active",
                "issued_at": "2026-01-01T00:00:00+00:00",
                "valid_from": "2026-01-01T00:00:00+00:00",
                "expires_at": "2027-01-01T00:00:00+00:00",
                "issued_by": "na-local",
                "subject_public_keys": [],
                "metadata": {},
                "signatures": [],
            }
        ],
        "revoked_trust_material": [],
    }


def _scoped_graph(allowed_roles: list[str]) -> dict:
    g = _active_graph()
    g["active_treaties"][0]["scope"]["allowed_roles"] = allowed_roles
    return g


def _expiring_graph() -> dict:
    g = _active_graph()
    g["recognition_edges"][0]["lifecycle_state"] = "expiring_soon"
    g["recognition_edges"][0]["expiry_risk"] = True
    return g


def _revocation_pressure_graph() -> dict:
    g = _active_graph()
    g["revoked_trust_material"] = [
        {
            "type": "membership_attestation",
            "id": "attest-1",
            "issuer_sovereign_id": "sovereign-b",
            "feed_id": "feed-1",
            "sequence": 1,
            "reason": "key_compromise",
            "revoked_at": "2026-06-01T00:00:00+00:00",
        }
    ]
    return g


def _no_path_graph() -> dict:
    g = _active_graph()
    g["recognition_edges"][0]["status"] = "revoked"
    g["recognition_edges"][0]["lifecycle_state"] = "revoked"
    g["active_treaties"] = []
    return g


def _multi_hop_graph() -> dict:
    """Two-hop path: sovereign-a -> sovereign-b -> sovereign-c."""
    return {
        "sovereigns": [
            {"sovereign_id": "sovereign-a"},
            {"sovereign_id": "sovereign-b"},
            {"sovereign_id": "sovereign-c"},
        ],
        "recognition_edges": [
            {
                "from": "sovereign-a", "to": "sovereign-b",
                "treaty_id": "treaty-a-b", "status": "active",
                "lifecycle_state": "active", "expiry_risk": False,
                "valid_from": "2026-01-01T00:00:00+00:00",
                "expires_at": "2027-01-01T00:00:00+00:00",
            },
            {
                "from": "sovereign-b", "to": "sovereign-c",
                "treaty_id": "treaty-b-c", "status": "active",
                "lifecycle_state": "active", "expiry_risk": False,
                "valid_from": "2026-01-01T00:00:00+00:00",
                "expires_at": "2027-01-01T00:00:00+00:00",
            },
        ],
        "active_treaties": [
            {
                "treaty_id": "treaty-a-b",
                "issuer_sovereign_id": "sovereign-a",
                "subject_sovereign_id": "sovereign-b",
                "scope": {"allowed_roles": ["role:service:maintainer"], "accepted_statuses": ["active"], "claims": {}},
                "status": "active",
                "issued_at": "2026-01-01T00:00:00+00:00",
                "valid_from": "2026-01-01T00:00:00+00:00",
                "expires_at": "2027-01-01T00:00:00+00:00",
                "issued_by": "na-local", "subject_public_keys": [], "metadata": {}, "signatures": [],
            },
            {
                "treaty_id": "treaty-b-c",
                "issuer_sovereign_id": "sovereign-b",
                "subject_sovereign_id": "sovereign-c",
                "scope": {"allowed_roles": ["role:service:maintainer"], "accepted_statuses": ["active"], "claims": {}},
                "status": "active",
                "issued_at": "2026-01-01T00:00:00+00:00",
                "valid_from": "2026-01-01T00:00:00+00:00",
                "expires_at": "2027-01-01T00:00:00+00:00",
                "issued_by": "na-local", "subject_public_keys": [], "metadata": {}, "signatures": [],
            },
        ],
        "revoked_trust_material": [],
    }


# ---------------------------------------------------------------------------
# Decision engine — verdict tests
# ---------------------------------------------------------------------------

class TestEvaluateTrustDecision:

    def test_allow_on_active_path(self):
        d = evaluate_trust_decision(_active_graph(), "sovereign-a", "sovereign-b")
        assert d.verdict == "allow"
        assert d.trusted is True
        assert d.hop_count == 1
        assert d.reason == "active_treaty_path"
        assert d.signals[0].code == "active_treaty_path"
        assert d.signals[0].severity == "info"

    def test_block_on_no_path(self):
        d = evaluate_trust_decision(_no_path_graph(), "sovereign-a", "sovereign-b")
        assert d.verdict == "block"
        assert d.trusted is False
        assert d.hop_count == 0

    def test_block_on_unknown_sovereigns(self):
        d = evaluate_trust_decision(_active_graph(), "sovereign-x", "sovereign-y")
        assert d.verdict == "block"
        assert d.trusted is False

    def test_warn_on_expiring_treaty(self):
        d = evaluate_trust_decision(_expiring_graph(), "sovereign-a", "sovereign-b")
        assert d.verdict == "warn"
        assert any(s.code == "treaty_expiring_soon" for s in d.signals)

    def test_escalate_on_revocation_pressure(self):
        d = evaluate_trust_decision(_revocation_pressure_graph(), "sovereign-a", "sovereign-b")
        assert d.verdict == "escalate"
        assert any(s.code == "recognition_under_revocation_pressure" for s in d.signals)

    def test_block_on_role_not_in_scope(self):
        g = _scoped_graph(["role:allowed"])
        d = evaluate_trust_decision(g, "sovereign-a", "sovereign-b",
                                    requested_roles=["role:not-allowed"])
        assert d.verdict == "block"
        assert any(s.code == "scope_not_in_treaty" for s in d.signals)

    def test_allow_when_role_matches_scope(self):
        g = _scoped_graph(["role:service:maintainer"])
        d = evaluate_trust_decision(g, "sovereign-a", "sovereign-b",
                                    requested_roles=["role:service:maintainer"])
        assert d.verdict == "allow"

    def test_allow_when_scope_is_open(self):
        """Empty allowed_roles means any role is permitted."""
        g = _scoped_graph([])
        d = evaluate_trust_decision(g, "sovereign-a", "sovereign-b",
                                    requested_roles=["role:anything"])
        assert d.verdict == "allow"

    def test_block_beats_warn(self):
        """Scope block on an expiring treaty: block wins."""
        g = _expiring_graph()
        g["active_treaties"][0]["scope"]["allowed_roles"] = ["role:allowed"]
        d = evaluate_trust_decision(g, "sovereign-a", "sovereign-b",
                                    requested_roles=["role:other"])
        assert d.verdict == "block"

    def test_multi_hop_allow(self):
        d = evaluate_trust_decision(_multi_hop_graph(), "sovereign-a", "sovereign-c",
                                    requested_roles=["role:service:maintainer"])
        assert d.verdict == "allow"
        assert d.hop_count == 2

    def test_multi_hop_role_blocked_at_one_hop(self):
        """A role blocked at any hop blocks the whole path."""
        d = evaluate_trust_decision(_multi_hop_graph(), "sovereign-a", "sovereign-c",
                                    requested_roles=["role:other"])
        assert d.verdict == "block"

    def test_evaluated_at_is_utc_iso(self):
        d = evaluate_trust_decision(_active_graph(), "sovereign-a", "sovereign-b")
        dt = datetime.fromisoformat(d.evaluated_at)
        assert dt.tzinfo is not None

    def test_custom_now(self):
        now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        d = evaluate_trust_decision(_active_graph(), "sovereign-a", "sovereign-b", now=now)
        assert "2026-06-01" in d.evaluated_at

    def test_to_dict_is_serialisable(self):
        import json
        d = evaluate_trust_decision(_active_graph(), "sovereign-a", "sovereign-b")
        blob = json.dumps(d.to_dict())
        assert '"verdict"' in blob


# ---------------------------------------------------------------------------
# TrustEvidence build and verify
# ---------------------------------------------------------------------------

class TestTrustEvidence:

    def _make_evidence(self, graph=None, roles=None):
        g = graph or _active_graph()
        kp = generate_keypair()
        digest = graph_digest_from_export(g)
        decision = evaluate_trust_decision(g, "sovereign-a", "sovereign-b",
                                           requested_roles=roles)
        ev = build_trust_evidence(
            decision,
            issuer_sovereign_id="sovereign-a",
            graph_digest=digest,
            issued_by="na-test",
            signing_key=kp.private_key,
        )
        return ev, digest, [kp.public_key_b64]

    def test_evidence_has_expected_fields(self):
        ev, digest, _ = self._make_evidence()
        assert ev.verdict == "allow"
        assert ev.source_sovereign_id == "sovereign-a"
        assert ev.target_sovereign_id == "sovereign-b"
        assert ev.issuer_sovereign_id == "sovereign-a"
        assert ev.graph_digest == digest
        assert len(ev.signatures) == 1
        assert ev.issued_by == "na-test"
        assert ev.evidence_id  # non-empty UUID

    def test_verify_signature_roundtrip(self):
        ev, _, pub_keys = self._make_evidence()
        result = verify_trust_evidence(ev, pub_keys)
        assert result.accepted is True
        assert result.reason == "accepted"

    def test_verify_with_digest_binding(self):
        ev, digest, pub_keys = self._make_evidence()
        result = verify_trust_evidence(ev, pub_keys, expected_graph_digest=digest)
        assert result.accepted is True

    def test_reject_on_wrong_public_key(self):
        ev, _, _ = self._make_evidence()
        other = generate_keypair()
        result = verify_trust_evidence(ev, [other.public_key_b64])
        assert result.accepted is False
        assert result.reason == "invalid_signature"

    def test_reject_on_missing_signature(self):
        ev, _, pub_keys = self._make_evidence()
        ev.signatures.clear()
        result = verify_trust_evidence(ev, pub_keys)
        assert result.accepted is False
        assert result.reason == "missing_signature"

    def test_reject_on_digest_mismatch(self):
        ev, _, pub_keys = self._make_evidence()
        result = verify_trust_evidence(ev, pub_keys, expected_graph_digest="0" * 64)
        assert result.accepted is False
        assert result.reason == "graph_digest_mismatch"

    def test_tampered_evidence_rejected(self):
        ev, _, pub_keys = self._make_evidence()
        tampered = ev.model_copy(update={"hop_count": 99})
        result = verify_trust_evidence(tampered, pub_keys)
        assert result.accepted is False
        assert result.reason == "invalid_signature"

    def test_serialise_roundtrip(self):
        ev, _, pub_keys = self._make_evidence()
        reloaded = TrustEvidence.model_validate_json(ev.model_dump_json(indent=2))
        result = verify_trust_evidence(reloaded, pub_keys)
        assert result.accepted is True

    def test_block_verdict_captured(self):
        ev, _, pub_keys = self._make_evidence(graph=_no_path_graph())
        assert ev.verdict == "block"
        assert ev.trusted is False
        result = verify_trust_evidence(ev, pub_keys)
        assert result.accepted is True  # signature valid regardless of verdict

    def test_graph_digest_is_deterministic(self):
        g = _active_graph()
        assert graph_digest_from_export(g) == graph_digest_from_export(g)
        assert len(graph_digest_from_export(g)) == 64  # SHA-256 hex

    def test_different_graphs_produce_different_digests(self):
        assert graph_digest_from_export(_active_graph()) != graph_digest_from_export(_no_path_graph())

    def test_result_to_dict(self):
        import json
        ev, _, pub_keys = self._make_evidence()
        result = verify_trust_evidence(ev, pub_keys)
        blob = json.dumps(result.to_dict())
        assert '"accepted"' in blob
        assert '"evidence_id"' in blob
