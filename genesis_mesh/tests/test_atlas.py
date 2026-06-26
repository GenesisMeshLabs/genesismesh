"""Tests for Trust Atlas — console renderer, CLI build, and evidence overlay."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from genesis_mesh.cli.atlas_ops import atlas
from genesis_mesh.crypto import generate_keypair
from genesis_mesh.models.evidence import TrustEvidence
from genesis_mesh.na_service.operator_console.atlas import render_atlas, render_atlas_standalone
from genesis_mesh.trust.decision import evaluate_trust_decision
from genesis_mesh.trust.evidence import build_trust_evidence, graph_digest_from_export

from click.testing import CliRunner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _active_graph() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "sovereigns": [{"sovereign_id": "alpha"}, {"sovereign_id": "beta"}],
        "recognition_edges": [
            {
                "from": "alpha",
                "to": "beta",
                "treaty_id": "t-001",
                "status": "active",
                "lifecycle_state": "active",
                "expiry_risk": "low",
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
            }
        ],
        "active_treaties": [
            {
                "treaty_id": "t-001",
                "issuer_sovereign_id": "alpha",
                "subject_sovereign_id": "beta",
                "scope": {"allowed_roles": ["role:read", "role:write"]},
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=180)).isoformat(),
                "signatures": [],
            }
        ],
        "revoked_trust_material": [],
    }


def _empty_graph() -> dict:
    return {
        "sovereigns": [],
        "recognition_edges": [],
        "active_treaties": [],
        "revoked_trust_material": [],
    }


def _expiring_graph() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "sovereigns": [{"sovereign_id": "a"}, {"sovereign_id": "b"}],
        "recognition_edges": [
            {
                "from": "a",
                "to": "b",
                "treaty_id": "t-exp",
                "status": "active",
                "lifecycle_state": "expiring_soon",
                "expiry_risk": "high",
                "valid_from": now.isoformat(),
                "expires_at": (now + timedelta(days=3)).isoformat(),
            }
        ],
        "active_treaties": [],
        "revoked_trust_material": [],
    }


def _revoked_edge_graph() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "sovereigns": [{"sovereign_id": "x"}, {"sovereign_id": "y"}],
        "recognition_edges": [
            {
                "from": "x",
                "to": "y",
                "treaty_id": "t-rev",
                "status": "revoked",
                "lifecycle_state": "revoked",
                "expiry_risk": "none",
                "valid_from": now.isoformat(),
                "expires_at": now.isoformat(),
            }
        ],
        "active_treaties": [],
        "revoked_trust_material": [{"type": "recognition_treaty", "id": "t-rev"}],
    }


def _make_evidence(graph: dict, source: str, target: str) -> tuple[TrustEvidence, str]:
    kp = generate_keypair()
    decision = evaluate_trust_decision(graph, source, target)
    digest = graph_digest_from_export(graph)
    return build_trust_evidence(
        decision,
        issuer_sovereign_id=source,
        graph_digest=digest,
        issued_by="test-key",
        signing_key=kp.private_key,
    ), kp.public_key_b64


# ---------------------------------------------------------------------------
# render_atlas
# ---------------------------------------------------------------------------


class TestRenderAtlas:
    def test_empty_graph_renders_without_error(self):
        html = render_atlas(_empty_graph())
        assert "Trust Atlas" in html
        assert "No sovereigns in graph" in html

    def test_active_graph_shows_sovereigns(self):
        html = render_atlas(_active_graph())
        assert "alpha" in html
        assert "beta" in html

    def test_active_graph_shows_roles(self):
        html = render_atlas(_active_graph())
        assert "role:read" in html
        assert "role:write" in html

    def test_expiring_edge_shows_expiring_label(self):
        html = render_atlas(_expiring_graph())
        assert "expiring_soon" in html

    def test_revoked_edge_appears_in_historical(self):
        html = render_atlas(_revoked_graph := _revoked_edge_graph())
        assert "revoked" in html

    def test_shows_graph_digest(self):
        graph = _active_graph()
        digest = graph_digest_from_export(graph)
        html = render_atlas(graph)
        assert digest[:12] in html

    def test_evidence_section_empty_when_no_evidences(self):
        html = render_atlas(_active_graph())
        assert "No evidence records loaded" in html
        assert "atlas build" in html

    def test_evidence_overlay_shows_verdict(self):
        graph = _active_graph()
        ev, _ = _make_evidence(graph, "alpha", "beta")
        ev_dict = json.loads(ev.model_dump_json())
        html = render_atlas(graph, evidences=[ev_dict])
        assert "ALLOW" in html or "allow" in html.lower()
        assert "Evidence Records" in html

    def test_no_write_paths_in_page(self):
        html = render_atlas(_active_graph())
        assert "<form" not in html
        assert 'method="post"' not in html.lower()

    def test_nav_contains_atlas_link(self):
        html = render_atlas(_active_graph())
        assert "/atlas" in html or "Atlas" in html


# ---------------------------------------------------------------------------
# render_atlas_standalone
# ---------------------------------------------------------------------------


class TestRenderAtlasStandalone:
    def test_is_self_contained_html(self):
        graph = _active_graph()
        digest = graph_digest_from_export(graph)
        html = render_atlas_standalone(graph, [], digest)
        assert "<!doctype html>" in html.lower()
        assert "<style>" in html
        assert "link rel=" not in html
        assert digest[:12] in html

    def test_shows_sovereigns(self):
        graph = _active_graph()
        digest = graph_digest_from_export(graph)
        html = render_atlas_standalone(graph, [], digest)
        assert "alpha" in html
        assert "beta" in html

    def test_evidence_overlay_shown(self):
        graph = _active_graph()
        ev, pub = _make_evidence(graph, "alpha", "beta")
        ev_dict = json.loads(ev.model_dump_json())
        ev_dict["_atlas_verified"] = True
        ev_dict["_atlas_reason"] = "accepted"
        digest = graph_digest_from_export(graph)
        html = render_atlas_standalone(graph, [ev_dict], digest)
        assert "verified" in html

    def test_unverified_evidence_shown_as_unverified(self):
        graph = _active_graph()
        ev, _ = _make_evidence(graph, "alpha", "beta")
        ev_dict = json.loads(ev.model_dump_json())
        ev_dict["_atlas_verified"] = False
        ev_dict["_atlas_reason"] = "missing_signature"
        digest = graph_digest_from_export(graph)
        html = render_atlas_standalone(graph, [ev_dict], digest)
        assert "unverified" in html


# ---------------------------------------------------------------------------
# CLI atlas build
# ---------------------------------------------------------------------------


class TestAtlasBuildCli:
    def test_build_produces_atlas_json_and_html(self, tmp_path):
        graph = _active_graph()
        graph_file = tmp_path / "graph.json"
        graph_file.write_text(json.dumps(graph), encoding="utf-8")
        out_dir = tmp_path / "atlas-out"

        runner = CliRunner()
        result = runner.invoke(atlas, ["build", "--graph", str(graph_file), "--output", str(out_dir)])

        assert result.exit_code == 0, result.output
        assert (out_dir / "atlas.json").exists()
        assert (out_dir / "atlas.html").exists()

    def test_atlas_json_contains_graph_digest(self, tmp_path):
        graph = _active_graph()
        graph_file = tmp_path / "graph.json"
        graph_file.write_text(json.dumps(graph), encoding="utf-8")
        out_dir = tmp_path / "out"

        runner = CliRunner()
        runner.invoke(atlas, ["build", "--graph", str(graph_file), "--output", str(out_dir)])

        data = json.loads((out_dir / "atlas.json").read_text(encoding="utf-8"))
        assert "graph_digest" in data
        assert data["graph_digest"] == graph_digest_from_export(graph)

    def test_build_with_evidence_dir_verifies_and_counts(self, tmp_path):
        graph = _active_graph()
        graph_file = tmp_path / "graph.json"
        graph_file.write_text(json.dumps(graph), encoding="utf-8")

        kp = generate_keypair()
        decision = evaluate_trust_decision(graph, "alpha", "beta")
        digest = graph_digest_from_export(graph)
        ev = build_trust_evidence(
            decision,
            issuer_sovereign_id="alpha",
            graph_digest=digest,
            issued_by="k1",
            signing_key=kp.private_key,
        )
        ev_dir = tmp_path / "evidence"
        ev_dir.mkdir()
        (ev_dir / "ev1.json").write_text(ev.model_dump_json(), encoding="utf-8")

        out_dir = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            atlas,
            [
                "build",
                "--graph", str(graph_file),
                "--output", str(out_dir),
                "--evidence", str(ev_dir),
                "--public-key", kp.public_key_b64,
            ],
        )

        assert result.exit_code == 0, result.output
        data = json.loads((out_dir / "atlas.json").read_text(encoding="utf-8"))
        assert len(data["evidence"]) == 1
        assert data["evidence"][0]["_atlas_verified"] is True

    def test_build_with_wrong_key_marks_unverified(self, tmp_path):
        graph = _active_graph()
        graph_file = tmp_path / "graph.json"
        graph_file.write_text(json.dumps(graph), encoding="utf-8")

        kp_signer = generate_keypair()
        kp_wrong = generate_keypair()
        decision = evaluate_trust_decision(graph, "alpha", "beta")
        digest = graph_digest_from_export(graph)
        ev = build_trust_evidence(
            decision,
            issuer_sovereign_id="alpha",
            graph_digest=digest,
            issued_by="k1",
            signing_key=kp_signer.private_key,
        )
        ev_dir = tmp_path / "ev"
        ev_dir.mkdir()
        (ev_dir / "ev.json").write_text(ev.model_dump_json(), encoding="utf-8")

        out_dir = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            atlas,
            [
                "build",
                "--graph", str(graph_file),
                "--output", str(out_dir),
                "--evidence", str(ev_dir),
                "--public-key", kp_wrong.public_key_b64,
            ],
        )

        assert result.exit_code == 1
        data = json.loads((out_dir / "atlas.json").read_text(encoding="utf-8"))
        assert data["evidence"][0]["_atlas_verified"] is False

    def test_build_with_unparseable_evidence_exits_1(self, tmp_path):
        graph = _active_graph()
        graph_file = tmp_path / "graph.json"
        graph_file.write_text(json.dumps(graph), encoding="utf-8")

        ev_dir = tmp_path / "ev"
        ev_dir.mkdir()
        (ev_dir / "bad.json").write_text('{"not": "evidence"}', encoding="utf-8")

        out_dir = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            atlas,
            ["build", "--graph", str(graph_file), "--output", str(out_dir), "--evidence", str(ev_dir)],
        )
        assert result.exit_code == 1
        data = json.loads((out_dir / "atlas.json").read_text(encoding="utf-8"))
        assert data["unverifiable_count"] == 1

    def test_missing_graph_file_raises_error(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            atlas,
            ["build", "--graph", str(tmp_path / "missing.json"), "--output", str(tmp_path / "out")],
        )
        assert result.exit_code != 0

    def test_invalid_evidence_dir_raises_error(self, tmp_path):
        graph = _active_graph()
        graph_file = tmp_path / "graph.json"
        graph_file.write_text(json.dumps(graph), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            atlas,
            [
                "build",
                "--graph", str(graph_file),
                "--output", str(tmp_path / "out"),
                "--evidence", str(tmp_path / "no-such-dir"),
            ],
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Operator console /atlas route
# ---------------------------------------------------------------------------


class TestAtlasRoute:
    def test_atlas_page_returns_200_html(self, client):
        resp = client.get("/atlas")
        assert resp.status_code == 200
        assert resp.mimetype == "text/html"

    def test_atlas_page_contains_trust_atlas_title(self, client):
        resp = client.get("/atlas")
        body = resp.get_data(as_text=True)
        assert "Trust Atlas" in body

    def test_atlas_json_returns_200_json(self, client):
        resp = client.get("/atlas.json")
        assert resp.status_code == 200
        assert resp.is_json
        data = resp.get_json()
        assert "graph_digest" in data
        assert "sovereigns" in data

    def test_atlas_json_graph_digest_is_sha256_hex(self, client):
        resp = client.get("/atlas.json")
        data = resp.get_json()
        digest = data["graph_digest"]
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)
