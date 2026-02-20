"""Tests for HealthChecker connectivity probing."""

import asyncio
from unittest.mock import MagicMock

import pytest

from genesis_mesh.monitoring.health import HealthChecker, HealthStatus


def _make_checker(
    peer_ids=None,
    probe_peer=None,
    anchor_peers=0,
):
    """Create a HealthChecker with mock dependencies."""
    peer_stats = {
        "total_peers": len(peer_ids) if peer_ids else 0,
        "connected_peers": len(peer_ids) if peer_ids else 0,
        "anchor_peers": anchor_peers,
        "connected_peer_ids": peer_ids or [],
    }

    return HealthChecker(
        node_id="node-test",
        get_certificate_status=lambda: {"has_certificate": True, "is_expired": False, "percent_remaining": 80},
        get_peer_stats=lambda: peer_stats,
        get_routing_stats=lambda: {"total_routes": 5, "direct_neighbors": 2},
        probe_peer=probe_peer,
    )


# ── HEALTHY: all peers reachable ─────────────────────────────────────


@pytest.mark.asyncio
async def test_connectivity_healthy_all_reachable():
    """All probed peers respond → HEALTHY."""
    async def mock_probe(pid):
        return 0.025  # 25ms

    checker = _make_checker(
        peer_ids=["p1", "p2", "p3"],
        probe_peer=mock_probe,
    )

    await checker._check_connectivity()

    check = checker.checks["connectivity"]
    assert check.status == HealthStatus.HEALTHY
    assert check.details["succeeded"] == 3
    assert check.details["failed"] == 0
    assert check.details["median_rtt_ms"] is not None


# ── DEGRADED: some peers unreachable ─────────────────────────────────


@pytest.mark.asyncio
async def test_connectivity_degraded_partial_failure():
    """Only 1 of 3 peers responds → DEGRADED (33% < 50% threshold)."""
    call_count = 0

    async def mock_probe(pid):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return 0.010  # first peer OK
        return None  # others fail

    checker = _make_checker(
        peer_ids=["p1", "p2", "p3"],
        probe_peer=mock_probe,
    )

    await checker._check_connectivity()

    check = checker.checks["connectivity"]
    assert check.status == HealthStatus.DEGRADED
    assert check.details["success_ratio"] < 0.5


# ── UNHEALTHY: zero peers reachable ──────────────────────────────────


@pytest.mark.asyncio
async def test_connectivity_unhealthy_all_fail():
    """All probed peers fail → UNHEALTHY."""
    async def mock_probe(pid):
        return None

    checker = _make_checker(
        peer_ids=["p1", "p2"],
        probe_peer=mock_probe,
    )

    await checker._check_connectivity()

    check = checker.checks["connectivity"]
    assert check.status == HealthStatus.UNHEALTHY
    assert check.details["succeeded"] == 0


@pytest.mark.asyncio
async def test_connectivity_unhealthy_no_peers():
    """No peers available to probe → UNHEALTHY."""
    async def mock_probe(pid):
        return 0.001

    checker = _make_checker(
        peer_ids=[],
        probe_peer=mock_probe,
    )

    await checker._check_connectivity()

    check = checker.checks["connectivity"]
    assert check.status == HealthStatus.UNHEALTHY
    assert "No peers" in check.message


# ── Timeout handling ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connectivity_timeout_counts_as_failure():
    """Probes that time out count as failures."""
    async def mock_probe(pid):
        await asyncio.sleep(999)  # will be cancelled by timeout

    checker = _make_checker(
        peer_ids=["p1", "p2"],
        probe_peer=mock_probe,
    )
    # Use short timeout for testing
    checker.PROBE_TIMEOUT = 0.1

    await checker._check_connectivity()

    check = checker.checks["connectivity"]
    assert check.status == HealthStatus.UNHEALTHY
    assert check.details["timeout_count"] == 2


# ── No probe callback → skip ────────────────────────────────────────


@pytest.mark.asyncio
async def test_connectivity_skipped_without_probe_callback():
    """When no probe_peer callback is provided, connectivity check is skipped."""
    checker = _make_checker(
        peer_ids=["p1", "p2"],
        probe_peer=None,
    )

    await checker._check_connectivity()

    assert "connectivity" not in checker.checks


# ── Probe exception handling ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_connectivity_probe_exception_counts_as_failure():
    """Probes that raise exceptions count as failures."""
    async def mock_probe(pid):
        raise ConnectionError("peer unreachable")

    checker = _make_checker(
        peer_ids=["p1"],
        probe_peer=mock_probe,
    )

    await checker._check_connectivity()

    check = checker.checks["connectivity"]
    assert check.status == HealthStatus.UNHEALTHY
    assert check.details["failed"] == 1


# ── Deep check integration ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_deep_check_includes_connectivity():
    """Deep health check runs connectivity probing."""
    async def mock_probe(pid):
        return 0.015

    checker = _make_checker(
        peer_ids=["p1", "p2", "p3"],
        probe_peer=mock_probe,
        anchor_peers=1,
    )

    status = await checker.check_health(deep=True)
    assert status == HealthStatus.HEALTHY
    assert "connectivity" in checker.checks


@pytest.mark.asyncio
async def test_shallow_check_skips_connectivity():
    """Shallow (non-deep) health check does NOT run connectivity probing."""
    async def mock_probe(pid):
        return 0.015

    checker = _make_checker(
        peer_ids=["p1", "p2"],
        probe_peer=mock_probe,
    )

    await checker.check_health(deep=False)
    assert "connectivity" not in checker.checks
