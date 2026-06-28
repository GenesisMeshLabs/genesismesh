"""Tests for Trust Path Performance and Atlas Pruning (v0.46)."""

from __future__ import annotations

import base64
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nacl.signing
import pytest
from click.testing import CliRunner

from genesis_mesh.cli.atlas_ops import atlas
from genesis_mesh.models.atlas import (
    GraphPruningPolicy,
    PrunedAtlasExport,
    TrustPathCache,
)
from genesis_mesh.trust.atlas import (
    build_trust_path_cache,
    cache_trust_path,
    lookup_trust_path,
    prune_graph,
)

_NOW = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)


def _sk() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()


def _simple_graph(edges: list[dict] | None = None) -> dict:
    """Minimal graph with two active edges: A-B, B-C."""
    return {
        "sovereigns": [
            {"id": "sovereign-a"},
            {"id": "sovereign-b"},
            {"id": "sovereign-c"},
        ],
        "recognition_edges": edges or [
            {"from": "sovereign-a", "to": "sovereign-b",
             "status": "active", "treaty_id": "t-ab"},
            {"from": "sovereign-b", "to": "sovereign-c",
             "status": "active", "treaty_id": "t-bc"},
        ],
        "exported_at": _NOW.isoformat(),
    }


def _policy(
    expiry_secs: int = 86400,
    revoked_certs: bool = True,
    empty_scopes: bool = True,
    max_age: int = 86400 * 365,
    op_id: str = "operator-a",
) -> GraphPruningPolicy:
    return GraphPruningPolicy(
        operator_sovereign_id=op_id,
        prune_expired_treaties_after_seconds=expiry_secs,
        prune_revoked_certificates=revoked_certs,
        prune_empty_scopes=empty_scopes,
        max_graph_age_seconds=max_age,
    )


# ---------------------------------------------------------------------------
# cache_trust_path
# ---------------------------------------------------------------------------


def test_cache_path_found() -> None:
    sk = _sk()
    g = _simple_graph()
    entry = cache_trust_path("sovereign-a", "sovereign-c", g, "op-1", sk, now=_NOW)
    assert entry.verdict == "allow"
    assert entry.hop_count == 2
    assert entry.path_sovereign_ids == ["sovereign-a", "sovereign-b", "sovereign-c"]
    assert entry.signature is not None


def test_cache_path_not_found() -> None:
    sk = _sk()
    g = _simple_graph()
    entry = cache_trust_path("sovereign-a", "sovereign-x", g, "op-1", sk, now=_NOW)
    assert entry.verdict == "no_path"
    assert entry.hop_count == 0
    assert entry.path_sovereign_ids == []


def test_cache_path_ttl_set() -> None:
    sk = _sk()
    g = _simple_graph()
    entry = cache_trust_path("sovereign-a", "sovereign-b", g, "op-1", sk,
                             path_ttl_seconds=60, now=_NOW)
    assert entry.valid_until == _NOW + timedelta(seconds=60)


def test_cache_path_same_source_target() -> None:
    sk = _sk()
    g = _simple_graph()
    entry = cache_trust_path("sovereign-a", "sovereign-a", g, "op-1", sk, now=_NOW)
    assert entry.verdict == "allow"
    assert entry.hop_count == 0
    assert entry.path_sovereign_ids == ["sovereign-a"]


# ---------------------------------------------------------------------------
# lookup_trust_path
# ---------------------------------------------------------------------------


def test_lookup_warm_cache() -> None:
    sk = _sk()
    g = _simple_graph()
    cache = build_trust_path_cache(
        [("sovereign-a", "sovereign-b")], g, "op-1", sk, path_ttl_seconds=300, now=_NOW
    )
    entry = lookup_trust_path(cache, "sovereign-a", "sovereign-b", at_time=_NOW)
    assert entry is not None
    assert entry.verdict == "allow"


def test_lookup_cache_miss_wrong_pair() -> None:
    sk = _sk()
    g = _simple_graph()
    cache = build_trust_path_cache(
        [("sovereign-a", "sovereign-b")], g, "op-1", sk, now=_NOW
    )
    result = lookup_trust_path(cache, "sovereign-a", "sovereign-c", at_time=_NOW)
    assert result is None


def test_lookup_expired_entry_miss() -> None:
    sk = _sk()
    g = _simple_graph()
    cache = build_trust_path_cache(
        [("sovereign-a", "sovereign-b")], g, "op-1", sk, path_ttl_seconds=60, now=_NOW
    )
    future = _NOW + timedelta(seconds=120)
    result = lookup_trust_path(cache, "sovereign-a", "sovereign-b", at_time=future)
    assert result is None


def test_lookup_empty_cache() -> None:
    sk = _sk()
    g = _simple_graph()
    cache = build_trust_path_cache([], g, "op-1", sk, now=_NOW)
    assert lookup_trust_path(cache, "sovereign-a", "sovereign-b") is None


# ---------------------------------------------------------------------------
# build_trust_path_cache
# ---------------------------------------------------------------------------


def test_build_cache_signed() -> None:
    sk = _sk()
    g = _simple_graph()
    cache = build_trust_path_cache(
        [("sovereign-a", "sovereign-b"), ("sovereign-b", "sovereign-c")],
        g, "op-1", sk, now=_NOW,
    )
    assert cache.signature is not None
    assert len(cache.entries) == 2


def test_build_cache_graph_digest_matches() -> None:
    import hashlib  # noqa: PLC0415
    sk = _sk()
    g = _simple_graph()
    cache = build_trust_path_cache([("sovereign-a", "sovereign-b")], g, "op-1", sk, now=_NOW)
    expected = hashlib.sha256(
        json.dumps(g, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert cache.graph_digest == expected


# ---------------------------------------------------------------------------
# prune_graph
# ---------------------------------------------------------------------------


def test_prune_expired_treaty() -> None:
    sk = _sk()
    expired_at = (_NOW - timedelta(days=2)).isoformat()
    g = _simple_graph(edges=[
        {"from": "a", "to": "b", "status": "active",
         "treaty_id": "t1", "valid_until": expired_at, "edge_type": "treaty"},
        {"from": "b", "to": "c", "status": "active",
         "treaty_id": "t2", "edge_type": "treaty"},
    ])
    g["exported_at"] = _NOW.isoformat()
    policy = _policy(expiry_secs=3600)
    pruned, export = prune_graph(g, policy, "op-1", sk, now=_NOW)
    assert len(pruned["recognition_edges"]) == 1
    assert export.removed_edge_count == 1
    assert export.audit_entries[0].removal_reason == "expired_treaty"
    assert export.signature is not None


def test_prune_revoked_certificate() -> None:
    sk = _sk()
    g = _simple_graph(edges=[
        {"from": "a", "to": "b", "status": "revoked",
         "treaty_id": "t1", "edge_type": "certificate"},
        {"from": "b", "to": "c", "status": "active",
         "treaty_id": "t2", "edge_type": "treaty"},
    ])
    g["exported_at"] = _NOW.isoformat()
    policy = _policy(revoked_certs=True)
    pruned, export = prune_graph(g, policy, "op-1", sk, now=_NOW)
    assert len(pruned["recognition_edges"]) == 1
    assert export.audit_entries[0].removal_reason == "revoked_cert"


def test_prune_empty_scope() -> None:
    sk = _sk()
    g = _simple_graph(edges=[
        {"from": "a", "to": "b", "status": "active",
         "treaty_id": "t1", "scope_ids": [], "edge_type": "treaty"},
        {"from": "b", "to": "c", "status": "active",
         "treaty_id": "t2", "edge_type": "treaty"},
    ])
    g["exported_at"] = _NOW.isoformat()
    policy = _policy(empty_scopes=True)
    pruned, export = prune_graph(g, policy, "op-1", sk, now=_NOW)
    assert len(pruned["recognition_edges"]) == 1
    assert export.audit_entries[0].removal_reason == "empty_scope"


def test_prune_audit_log_complete() -> None:
    sk = _sk()
    g = _simple_graph(edges=[
        {"from": "a", "to": "b", "status": "revoked",
         "treaty_id": "t1", "edge_type": "certificate"},
        {"from": "b", "to": "c", "status": "revoked",
         "treaty_id": "t2", "edge_type": "certificate"},
    ])
    g["exported_at"] = _NOW.isoformat()
    policy = _policy()
    _, export = prune_graph(g, policy, "op-1", sk, now=_NOW)
    assert export.removed_edge_count == 2
    assert len(export.audit_entries) == 2


def test_prune_digest_changes() -> None:
    sk = _sk()
    g = _simple_graph(edges=[
        {"from": "a", "to": "b", "status": "revoked",
         "treaty_id": "t1", "edge_type": "certificate"},
    ])
    g["exported_at"] = _NOW.isoformat()
    policy = _policy()
    _, export = prune_graph(g, policy, "op-1", sk, now=_NOW)
    assert export.original_graph_digest != export.pruned_graph_digest


def test_prune_stale_graph_raises() -> None:
    sk = _sk()
    old_time = _NOW - timedelta(hours=25)
    g = _simple_graph()
    g["exported_at"] = old_time.isoformat()
    policy = _policy(max_age=3600)
    with pytest.raises(ValueError, match="old"):
        prune_graph(g, policy, "op-1", sk, now=_NOW)


def test_prune_nothing_to_prune() -> None:
    sk = _sk()
    g = _simple_graph()
    g["exported_at"] = _NOW.isoformat()
    policy = _policy()
    pruned, export = prune_graph(g, policy, "op-1", sk, now=_NOW)
    assert export.removed_edge_count == 0
    assert len(pruned["recognition_edges"]) == 2


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_atlas_cache() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "op.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")

        g = _simple_graph()
        graph_path = p / "graph.json"
        graph_path.write_text(json.dumps(g), encoding="utf-8")

        pairs_path = p / "pairs.json"
        pairs_path.write_text(
            json.dumps([["sovereign-a", "sovereign-b"], ["sovereign-a", "sovereign-c"]]),
            encoding="utf-8",
        )
        out = p / "cache.json"

        runner = CliRunner()
        result = runner.invoke(atlas, [
            "cache",
            "--graph", str(graph_path),
            "--pairs", str(pairs_path),
            "--operator-sovereign", "op-1",
            "--signing-key", str(key_path),
            "--output", str(out),
        ])
        assert result.exit_code == 0, result.output
        cache = TrustPathCache.model_validate_json(out.read_text())
        assert len(cache.entries) == 2
        assert cache.signature is not None


def test_cli_atlas_lookup_hit() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "op.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")

        g = _simple_graph()
        cache = build_trust_path_cache(
            [("sovereign-a", "sovereign-b")], g, "op-1", sk, now=_NOW
        )
        cache_path = p / "cache.json"
        cache_path.write_text(cache.model_dump_json(indent=2), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(atlas, [
            "lookup",
            "--cache", str(cache_path),
            "--from", "sovereign-a",
            "--to", "sovereign-b",
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output


def test_cli_atlas_lookup_miss() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        g = _simple_graph()
        cache = build_trust_path_cache([], g, "op-1", sk, now=_NOW)
        cache_path = p / "cache.json"
        cache_path.write_text(cache.model_dump_json(indent=2), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(atlas, [
            "lookup",
            "--cache", str(cache_path),
            "--from", "sovereign-a",
            "--to", "sovereign-x",
        ])
        assert result.exit_code != 0


def test_cli_atlas_prune() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "op.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")

        # Use a date clearly in the past relative to real clock (2024-01-01)
        expired_at = "2024-01-01T00:00:00+00:00"
        real_now = datetime.now(timezone.utc)
        g = {
            "sovereigns": [],
            "recognition_edges": [
                {"from": "a", "to": "b", "status": "active",
                 "treaty_id": "t1", "valid_until": expired_at, "edge_type": "treaty"},
                {"from": "b", "to": "c", "status": "active",
                 "treaty_id": "t2", "edge_type": "treaty"},
            ],
            "exported_at": real_now.isoformat(),  # graph exported just now
        }
        graph_path = p / "graph.json"
        graph_path.write_text(json.dumps(g), encoding="utf-8")
        out_graph = p / "pruned.json"
        out_audit = p / "audit.json"

        runner = CliRunner()
        result = runner.invoke(atlas, [
            "prune",
            "--graph", str(graph_path),
            "--operator-sovereign", "op-1",
            "--signing-key", str(key_path),
            "--output-graph", str(out_graph),
            "--output-audit", str(out_audit),
        ])
        assert result.exit_code == 0, result.output
        audit = PrunedAtlasExport.model_validate_json(out_audit.read_text())
        assert audit.removed_edge_count == 1
        assert audit.signature is not None
