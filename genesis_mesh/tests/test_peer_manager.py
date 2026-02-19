"""Tests for PeerManager deadlock fixes and peer lifecycle."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from genesis_mesh.transport.protocol import PeerInfo
from genesis_mesh.transport.connection import Connection, ConnectionState
from genesis_mesh.node.peer_manager import PeerManager, PeerState


def _make_peer_info(peer_id: str, reputation: float = 1.0) -> PeerInfo:
    """Create a PeerInfo for testing."""
    return PeerInfo(
        node_id=peer_id,
        endpoint=f"127.0.0.1:{5000 + hash(peer_id) % 1000}",
        roles=["role:client"],
        last_seen=time.time(),
        reputation=reputation,
    )


def _make_mock_connection(peer_id: str, state: ConnectionState = ConnectionState.CLOSED) -> Connection:
    """Create a mock Connection."""
    conn = MagicMock(spec=Connection)
    conn.peer_id = peer_id
    conn.state = state
    conn.close = AsyncMock()
    return conn


# ── record_connection_attempt: no deadlock on failure path ────────────


@pytest.mark.asyncio
async def test_record_failed_attempt_does_not_deadlock():
    """
    record_connection_attempt(success=False) calls update_reputation and
    potentially blacklist_peer. Before the fix these were nested lock
    acquisitions that would deadlock. This test proves the call completes
    within a bounded time.
    """
    pm = PeerManager(node_id="local")
    peer = _make_peer_info("peer-1")
    await pm.add_peer(peer)

    # Should complete without hanging (timeout guards against deadlock)
    await asyncio.wait_for(
        pm.record_connection_attempt("peer-1", success=False),
        timeout=2.0,
    )

    state = pm.get_peer("peer-1")
    assert state is not None
    assert state.failed_attempts == 1
    assert state.info.reputation < 1.0  # decreased by -0.1


@pytest.mark.asyncio
async def test_repeated_failures_trigger_blacklist_without_deadlock():
    """
    Five consecutive failures should blacklist the peer.
    The old code deadlocked because record_connection_attempt held _lock,
    then called blacklist_peer which also tried to acquire _lock.
    """
    pm = PeerManager(node_id="local", blacklist_duration=60.0)
    peer = _make_peer_info("peer-1")
    await pm.add_peer(peer)

    for i in range(5):
        await asyncio.wait_for(
            pm.record_connection_attempt("peer-1", success=False),
            timeout=2.0,
        )

    state = pm.get_peer("peer-1")
    assert state is not None
    assert state.blacklisted_until is not None
    assert state.blacklisted_until > time.time()


@pytest.mark.asyncio
async def test_successful_attempt_resets_failures():
    """A successful connection attempt resets failed_attempts."""
    pm = PeerManager(node_id="local")
    peer = _make_peer_info("peer-1")
    await pm.add_peer(peer)

    # Record some failures
    for _ in range(3):
        await pm.record_connection_attempt("peer-1", success=False)

    assert pm.get_peer("peer-1").failed_attempts == 3

    # Successful attempt resets counter
    await pm.record_connection_attempt("peer-1", success=True)
    assert pm.get_peer("peer-1").failed_attempts == 0


# ── update_reputation: no deadlock when triggering blacklist ──────────


@pytest.mark.asyncio
async def test_update_reputation_blacklists_below_threshold():
    """
    update_reputation with a large negative delta should trigger blacklisting
    without deadlocking. The old code called blacklist_peer (which acquires
    _lock) from within update_reputation (which already held _lock).
    """
    pm = PeerManager(node_id="local", blacklist_duration=120.0)
    peer = _make_peer_info("peer-1", reputation=0.15)
    await pm.add_peer(peer)

    # Drop reputation below 0.1 threshold
    await asyncio.wait_for(
        pm.update_reputation("peer-1", -0.1),
        timeout=2.0,
    )

    state = pm.get_peer("peer-1")
    assert state is not None
    assert state.info.reputation < 0.1
    assert state.blacklisted_until is not None


@pytest.mark.asyncio
async def test_update_reputation_no_blacklist_above_threshold():
    """Reputation decrease that stays above threshold should not blacklist."""
    pm = PeerManager(node_id="local")
    peer = _make_peer_info("peer-1", reputation=0.8)
    await pm.add_peer(peer)

    await pm.update_reputation("peer-1", -0.2)

    state = pm.get_peer("peer-1")
    assert state.info.reputation == pytest.approx(0.6)
    assert state.blacklisted_until is None


# ── cleanup_stale_peers: no deadlock on remove path ──────────────────


@pytest.mark.asyncio
async def test_cleanup_stale_peers_does_not_deadlock():
    """
    cleanup_stale_peers iterates peers under _lock and calls remove_peer.
    Before the fix, remove_peer tried to acquire the same lock → deadlock.
    """
    pm = PeerManager(node_id="local")

    # Add a peer with last_seen far in the past
    old_peer = _make_peer_info("stale-1")
    old_peer.last_seen = time.time() - 7200  # 2 hours ago
    await pm.add_peer(old_peer)

    # Add a fresh peer
    fresh_peer = _make_peer_info("fresh-1")
    await pm.add_peer(fresh_peer)

    assert len(pm.peers) == 2

    await asyncio.wait_for(
        pm.cleanup_stale_peers(max_age=3600.0),
        timeout=2.0,
    )

    assert "stale-1" not in pm.peers
    assert "fresh-1" in pm.peers


@pytest.mark.asyncio
async def test_cleanup_stale_peers_closes_connections():
    """Stale peer removal should close the connection."""
    pm = PeerManager(node_id="local")
    conn = _make_mock_connection("stale-1", state=ConnectionState.CLOSED)

    old_peer = _make_peer_info("stale-1")
    old_peer.last_seen = time.time() - 7200
    await pm.add_peer(old_peer, connection=conn)

    await asyncio.wait_for(
        pm.cleanup_stale_peers(max_age=3600.0),
        timeout=2.0,
    )

    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_skips_established_connections():
    """Peers with established connections should not be cleaned up even if old."""
    pm = PeerManager(node_id="local")
    conn = _make_mock_connection("peer-1", state=ConnectionState.ESTABLISHED)

    old_peer = _make_peer_info("peer-1")
    old_peer.last_seen = time.time() - 7200
    await pm.add_peer(old_peer, connection=conn)

    await pm.cleanup_stale_peers(max_age=3600.0)

    assert "peer-1" in pm.peers  # still present


# ── blacklist_peer: connection close on blacklist ─────────────────────


@pytest.mark.asyncio
async def test_blacklist_closes_connection():
    """Blacklisting a peer should close its connection."""
    pm = PeerManager(node_id="local", blacklist_duration=60.0)
    conn = _make_mock_connection("peer-1")

    peer = _make_peer_info("peer-1")
    await pm.add_peer(peer, connection=conn)

    await asyncio.wait_for(
        pm.blacklist_peer("peer-1"),
        timeout=2.0,
    )

    conn.close.assert_awaited_once()
    state = pm.get_peer("peer-1")
    assert state.blacklisted_until is not None


# ── public methods still work standalone ──────────────────────────────


@pytest.mark.asyncio
async def test_remove_peer_standalone():
    """remove_peer() works when called directly (not nested)."""
    pm = PeerManager(node_id="local")
    peer = _make_peer_info("peer-1")
    await pm.add_peer(peer)

    await pm.remove_peer("peer-1")
    assert pm.get_peer("peer-1") is None


@pytest.mark.asyncio
async def test_blacklist_peer_standalone():
    """blacklist_peer() works when called directly (not nested)."""
    pm = PeerManager(node_id="local", blacklist_duration=60.0)
    peer = _make_peer_info("peer-1")
    await pm.add_peer(peer)

    await pm.blacklist_peer("peer-1")
    state = pm.get_peer("peer-1")
    assert state.blacklisted_until is not None


@pytest.mark.asyncio
async def test_update_reputation_standalone():
    """update_reputation() works when called directly (not nested)."""
    pm = PeerManager(node_id="local")
    peer = _make_peer_info("peer-1", reputation=0.5)
    await pm.add_peer(peer)

    await pm.update_reputation("peer-1", 0.2)
    assert pm.get_peer("peer-1").info.reputation == pytest.approx(0.7)


# ── concurrent access ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_failure_recording():
    """Multiple concurrent failure recordings should not deadlock."""
    pm = PeerManager(node_id="local")

    for i in range(10):
        peer = _make_peer_info(f"peer-{i}")
        await pm.add_peer(peer)

    tasks = [
        pm.record_connection_attempt(f"peer-{i}", success=False)
        for i in range(10)
    ]

    # All tasks must complete within timeout (no deadlock)
    await asyncio.wait_for(
        asyncio.gather(*tasks),
        timeout=5.0,
    )

    for i in range(10):
        assert pm.get_peer(f"peer-{i}").failed_attempts == 1
