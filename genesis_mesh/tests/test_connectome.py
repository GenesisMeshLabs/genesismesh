"""Tests for Connectome trust-graph view helpers."""

from __future__ import annotations

from genesis_mesh.trust import build_connectome_view, explain_trust_path


def _graph() -> dict:
    """Return a compact recognition graph fixture."""
    return {
        "sovereigns": [
            {"sovereign_id": "sovereign-c"},
            {"sovereign_id": "sovereign-a"},
            {"sovereign_id": "sovereign-b"},
        ],
        "recognition_edges": [
            {
                "from": "sovereign-a",
                "to": "sovereign-b",
                "treaty_id": "treaty-a-b",
                "status": "active",
                "valid_from": "2026-01-01T00:00:00+00:00",
                "expires_at": "2026-01-02T00:00:00+00:00",
            },
            {
                "from": "sovereign-b",
                "to": "sovereign-c",
                "treaty_id": "treaty-b-c",
                "status": "active",
                "valid_from": "2026-01-01T00:00:00+00:00",
                "expires_at": "2026-01-02T00:00:00+00:00",
            },
            {
                "from": "sovereign-c",
                "to": "sovereign-a",
                "treaty_id": "treaty-c-a",
                "status": "revoked",
                "valid_from": "2026-01-01T00:00:00+00:00",
                "expires_at": "2026-01-02T00:00:00+00:00",
            },
        ],
        "active_treaties": [],
        "revoked_trust_material": [
            {
                "type": "membership_attestation",
                "id": "attestation-1",
                "issuer_sovereign_id": "sovereign-b",
                "feed_id": "feed-1",
                "sequence": 1,
                "reason": "key_compromise",
                "revoked_at": "2026-01-01T12:00:00+00:00",
            },
            {
                "type": "recognition_treaty",
                "id": "treaty-c-a",
                "reason": "relationship_ended",
                "revoked_at": "2026-01-01T13:00:00+00:00",
            },
        ],
    }


def test_build_connectome_view_summarizes_graph():
    """The Connectome view summarizes edges and revocation blast radius."""
    view = build_connectome_view(_graph())

    assert view["summary"] == {
        "sovereign_count": 3,
        "recognition_edge_count": 3,
        "active_edge_count": 2,
        "revoked_edge_count": 1,
        "revoked_trust_material_count": 2,
        "imported_revocation_count": 1,
    }
    assert view["sovereigns"][0] == {"sovereign_id": "sovereign-a"}
    assert view["revocation_blast_radius"] == [{
        "type": "membership_attestation",
        "id": "attestation-1",
        "issuer_sovereign_id": "sovereign-b",
        "affected_accepting_sovereigns": ["sovereign-a"],
        "feed_id": "feed-1",
        "sequence": 1,
        "reason": "key_compromise",
        "revoked_at": "2026-01-01T12:00:00+00:00",
    }]


def test_explain_trust_path_finds_active_path():
    """Trust-path explanation follows active recognition edges."""
    result = explain_trust_path(_graph(), "sovereign-a", "sovereign-c")

    assert result["trusted"] is True
    assert result["reason"] == "active_treaty_path"
    assert result["hop_count"] == 2
    assert [edge["treaty_id"] for edge in result["path"]] == [
        "treaty-a-b",
        "treaty-b-c",
    ]


def test_explain_trust_path_reports_revoked_direct_edge():
    """A revoked direct treaty explains why direct recognition is inactive."""
    result = explain_trust_path(_graph(), "sovereign-c", "sovereign-a")

    assert result["trusted"] is False
    assert result["reason"] == "direct_treaty_revoked"
    assert result["path"][0]["treaty_id"] == "treaty-c-a"


def test_explain_trust_path_reports_missing_path():
    """Unknown trust paths are reported without raising."""
    result = explain_trust_path(_graph(), "sovereign-c", "sovereign-b")

    assert result["trusted"] is False
    assert result["reason"] == "no_active_treaty_path"
    assert result["path"] == []
