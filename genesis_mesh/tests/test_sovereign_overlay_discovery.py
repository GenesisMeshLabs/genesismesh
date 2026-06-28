"""Tests for Sovereign Overlay Discovery (v0.44)."""

from __future__ import annotations

import base64
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nacl.signing
import pytest
from click.testing import CliRunner

from genesis_mesh.cli.decision_ops import trust
from genesis_mesh.models.overlay_discovery import (
    DiscoveryCacheEntry,
    DiscoveryFeed,
    DiscoveryGossipMessage,
    OverlayDiscoveryRecord,
)
from genesis_mesh.trust.overlay_discovery import (
    build_discovery_feed,
    create_discovery_record,
    gossip_should_forward,
    merge_discovery_records,
    verify_discovery_record,
)

_NOW = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)


def _sk() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()


def _pub_b64(sk: nacl.signing.SigningKey) -> str:
    return base64.b64encode(bytes(sk.verify_key)).decode()


def _record(
    sk: nacl.signing.SigningKey | None = None,
    sovereign_id: str = "agent-a",
    endpoints: list[str] | None = None,
    sequence_no: int = 1,
    now: datetime | None = None,
    valid_for_hours: int = 24,
) -> OverlayDiscoveryRecord:
    sk = sk or _sk()
    return create_discovery_record(
        sovereign_id=sovereign_id,
        na_public_key_b64=_pub_b64(sk),
        endpoints=endpoints or ["http://agent-a.mesh:8443"],
        capabilities_hash="abc123",
        signing_key=sk,
        sequence_no=sequence_no,
        valid_for_hours=valid_for_hours,
        now=now or _NOW,
    )


# ---------------------------------------------------------------------------
# create_discovery_record
# ---------------------------------------------------------------------------


def test_create_sets_fields() -> None:
    sk = _sk()
    r = _record(sk, sovereign_id="agent-a", sequence_no=3)
    assert r.sovereign_id == "agent-a"
    assert r.sequence_no == 3
    assert r.signature is not None


def test_create_valid_until_is_announced_plus_hours() -> None:
    r = _record(now=_NOW, valid_for_hours=12)
    assert r.valid_until == _NOW + timedelta(hours=12)


def test_create_endpoints_preserved() -> None:
    eps = ["http://host:8443", "overlay://abc"]
    r = _record(endpoints=eps)
    assert r.endpoints == eps


def test_create_empty_endpoints_raises() -> None:
    sk = _sk()
    with pytest.raises(ValueError, match="endpoints"):
        create_discovery_record(
            sovereign_id="agent-a",
            na_public_key_b64=_pub_b64(sk),
            endpoints=[],
            capabilities_hash="abc",
            signing_key=sk,
        )


# ---------------------------------------------------------------------------
# verify_discovery_record
# ---------------------------------------------------------------------------


def test_verify_valid_record() -> None:
    r = _record(now=_NOW)
    ok, reason = verify_discovery_record(r, at_time=_NOW + timedelta(minutes=1))
    assert ok
    assert reason == "valid"


def test_verify_missing_signature() -> None:
    r = _record()
    r = r.model_copy(update={"signature": None})
    ok, reason = verify_discovery_record(r)
    assert not ok
    assert reason == "missing_signature"


def test_verify_tampered_endpoint_fails() -> None:
    r = _record(now=_NOW)
    r = r.model_copy(update={"endpoints": ["http://evil.mesh:9999"]})
    ok, reason = verify_discovery_record(r, at_time=_NOW + timedelta(minutes=1))
    assert not ok
    assert reason == "invalid_signature"


def test_verify_expired() -> None:
    r = _record(now=_NOW, valid_for_hours=1)
    ok, reason = verify_discovery_record(r, at_time=_NOW + timedelta(hours=2))
    assert not ok
    assert reason == "expired"


def test_verify_superseded_lower_seq() -> None:
    r = _record(now=_NOW, sequence_no=1)
    ok, reason = verify_discovery_record(r, at_time=_NOW + timedelta(minutes=1), known_sequence_no=3)
    assert not ok
    assert reason == "superseded"


def test_verify_equal_seq_not_superseded() -> None:
    r = _record(now=_NOW, sequence_no=5)
    ok, reason = verify_discovery_record(r, at_time=_NOW + timedelta(minutes=1), known_sequence_no=5)
    assert ok
    assert reason == "valid"


# ---------------------------------------------------------------------------
# merge_discovery_records
# ---------------------------------------------------------------------------


def test_merge_new_sovereign_added() -> None:
    r = _record(sovereign_id="agent-b", now=_NOW)
    updated, changed = merge_discovery_records([], [r], now=_NOW)
    assert len(updated) == 1
    assert "agent-b" in changed


def test_merge_higher_seq_supersedes() -> None:
    r1 = _record(sovereign_id="agent-a", sequence_no=1, now=_NOW)
    r2 = _record(sovereign_id="agent-a", sequence_no=5, now=_NOW)
    cache, _ = merge_discovery_records([], [r1], now=_NOW)
    updated, changed = merge_discovery_records(cache, [r2], now=_NOW)
    assert updated[0].record.sequence_no == 5
    assert "agent-a" in changed


def test_merge_same_seq_idempotent() -> None:
    r = _record(sovereign_id="agent-a", sequence_no=3, now=_NOW)
    cache, _ = merge_discovery_records([], [r], now=_NOW)
    updated, changed = merge_discovery_records(cache, [r], now=_NOW)
    assert changed == []
    assert len(updated) == 1


def test_merge_lower_seq_ignored() -> None:
    r5 = _record(sovereign_id="agent-a", sequence_no=5, now=_NOW)
    r1 = _record(sovereign_id="agent-a", sequence_no=1, now=_NOW)
    cache, _ = merge_discovery_records([], [r5], now=_NOW)
    updated, changed = merge_discovery_records(cache, [r1], now=_NOW)
    assert changed == []
    assert updated[0].record.sequence_no == 5


def test_merge_empty_incoming_unchanged() -> None:
    r = _record(now=_NOW)
    cache, _ = merge_discovery_records([], [r], now=_NOW)
    updated, changed = merge_discovery_records(cache, [], now=_NOW)
    assert changed == []
    assert len(updated) == 1


def test_merge_multiple_sovereigns() -> None:
    ra = _record(sovereign_id="agent-a", now=_NOW)
    rb = _record(sovereign_id="agent-b", now=_NOW)
    rc = _record(sovereign_id="agent-c", now=_NOW)
    updated, changed = merge_discovery_records([], [ra, rb, rc], now=_NOW)
    assert len(updated) == 3
    assert set(changed) == {"agent-a", "agent-b", "agent-c"}


# ---------------------------------------------------------------------------
# gossip_should_forward
# ---------------------------------------------------------------------------


def test_gossip_forward_under_max() -> None:
    msg = DiscoveryGossipMessage(
        records=[], origin_sovereign_id="agent-a",
        hop_count=3, max_hops=5, sent_at=_NOW,
    )
    assert gossip_should_forward(msg) is True


def test_gossip_no_forward_at_max() -> None:
    msg = DiscoveryGossipMessage(
        records=[], origin_sovereign_id="agent-a",
        hop_count=5, max_hops=5, sent_at=_NOW,
    )
    assert gossip_should_forward(msg) is False


def test_gossip_no_forward_over_max() -> None:
    msg = DiscoveryGossipMessage(
        records=[], origin_sovereign_id="agent-a",
        hop_count=10, max_hops=5, sent_at=_NOW,
    )
    assert gossip_should_forward(msg) is False


# ---------------------------------------------------------------------------
# build_discovery_feed
# ---------------------------------------------------------------------------


def test_build_feed_signed() -> None:
    sk = _sk()
    r = _record(now=_NOW)
    feed = build_discovery_feed([r], "operator-a", sk, now=_NOW)
    assert feed.signature is not None
    assert len(feed.entries) == 1
    assert feed.operator_sovereign_id == "operator-a"


def test_build_feed_valid_until() -> None:
    sk = _sk()
    feed = build_discovery_feed([], "operator-a", sk, valid_for_hours=3, now=_NOW)
    assert feed.valid_until == _NOW + timedelta(hours=3)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_announce() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "sov.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
        out = p / "record.json"

        runner = CliRunner()
        result = runner.invoke(trust, [
            "discover", "announce",
            "--sovereign-id", "agent-a",
            "--na-public-key", _pub_b64(sk),
            "--endpoint", "http://agent-a.mesh:8443",
            "--capabilities-hash", "cafecafe",
            "--signing-key", str(key_path),
            "--output", str(out),
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output
        r = OverlayDiscoveryRecord.model_validate_json(out.read_text())
        assert r.signature is not None


def test_cli_verify_valid() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "sov.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")
        record_path = p / "record.json"
        r = _record(sk, now=_NOW)
        record_path.write_text(r.model_dump_json(indent=2), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(trust, [
            "discover", "verify",
            "--record", str(record_path),
        ])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output


def test_cli_verify_tampered_fails() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        r = _record(sk, now=_NOW)
        r = r.model_copy(update={"endpoints": ["http://evil:9999"]})
        record_path = p / "record.json"
        record_path.write_text(r.model_dump_json(indent=2), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(trust, [
            "discover", "verify",
            "--record", str(record_path),
        ])
        assert result.exit_code != 0


def test_cli_feed() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        key_path = p / "op.key"
        key_path.write_text(base64.b64encode(bytes(sk)).decode(), encoding="utf-8")

        r = _record(now=_NOW)
        r_path = p / "r.json"
        r_path.write_text(r.model_dump_json(indent=2), encoding="utf-8")
        out = p / "feed.json"

        runner = CliRunner()
        result = runner.invoke(trust, [
            "discover", "feed",
            "--record", str(r_path),
            "--operator-sovereign", "operator-a",
            "--signing-key", str(key_path),
            "--output", str(out),
        ])
        assert result.exit_code == 0, result.output
        feed = DiscoveryFeed.model_validate_json(out.read_text())
        assert feed.signature is not None
        assert len(feed.entries) == 1


def test_cli_merge() -> None:
    sk = _sk()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        r = _record(sk, sovereign_id="agent-b", now=_NOW)
        r_path = p / "incoming.json"
        r_path.write_text(r.model_dump_json(indent=2), encoding="utf-8")
        cache_out = p / "cache.json"

        runner = CliRunner()
        result = runner.invoke(trust, [
            "discover", "merge",
            "--cache", str(p / "nonexistent.json"),
            "--incoming", str(r_path),
            "--output", str(cache_out),
        ])
        assert result.exit_code == 0, result.output
        assert "agent-b" in result.output
        raw = json.loads(cache_out.read_text())
        assert len(raw) == 1
