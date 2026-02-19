"""Tests for Connection duplicate ping loop fix and heartbeat role preservation."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from genesis_mesh.transport.protocol import MeshMessage, MessageType
from genesis_mesh.transport.connection import Connection, ConnectionState


def _make_connection(peer_id: str = "peer-1") -> Connection:
    """Create a Connection with a mock transport."""
    transport = MagicMock()
    transport.close = AsyncMock()
    transport.send = AsyncMock()
    conn = Connection(peer_id=peer_id, transport=transport)
    return conn


# ── set_established: idempotent, single ping loop ────────────────────


@pytest.mark.asyncio
async def test_set_established_starts_ping_loop():
    """set_established should start the ping loop."""
    conn = _make_connection()
    conn.state = ConnectionState.HANDSHAKING

    conn.set_established()

    assert conn.state == ConnectionState.ESTABLISHED
    assert conn._ping_task is not None

    conn._ping_task.cancel()


@pytest.mark.asyncio
async def test_set_established_idempotent():
    """Calling set_established twice should not create a second ping task."""
    conn = _make_connection()
    conn.state = ConnectionState.HANDSHAKING

    conn.set_established()
    first_task = conn._ping_task

    conn.set_established()
    second_task = conn._ping_task

    assert first_task is second_task

    first_task.cancel()


# ── HANDSHAKE_ACK handler uses set_established ───────────────────────


@pytest.mark.asyncio
async def test_handshake_ack_uses_set_established():
    """HANDSHAKE_ACK message should delegate to set_established."""
    conn = _make_connection()
    conn.state = ConnectionState.HANDSHAKING

    ack = MeshMessage(
        message_type=MessageType.HANDSHAKE_ACK,
        sender_id="remote-peer",
        payload={},
    )

    with patch.object(conn, 'set_established', wraps=conn.set_established) as mock_set:
        await conn._handle_message(ack)
        mock_set.assert_called_once()

    assert conn.state == ConnectionState.ESTABLISHED
    assert conn._ping_task is not None


@pytest.mark.asyncio
async def test_handshake_ack_then_set_established_no_double_ping():
    """If HANDSHAKE_ACK arrives and then set_established is called externally,
    only one ping task should exist."""
    conn = _make_connection()
    conn.state = ConnectionState.HANDSHAKING

    ack = MeshMessage(
        message_type=MessageType.HANDSHAKE_ACK,
        sender_id="remote-peer",
        payload={},
    )

    await conn._handle_message(ack)
    first_task = conn._ping_task

    # External call to set_established
    conn.set_established()
    second_task = conn._ping_task

    # Same task — no duplicate
    assert first_task is second_task


@pytest.mark.asyncio
async def test_set_established_then_handshake_ack_no_double_ping():
    """If set_established is called first, a subsequent HANDSHAKE_ACK
    should not create a second ping task."""
    conn = _make_connection()
    conn.state = ConnectionState.HANDSHAKING

    conn.set_established()
    first_task = conn._ping_task

    ack = MeshMessage(
        message_type=MessageType.HANDSHAKE_ACK,
        sender_id="remote-peer",
        payload={},
    )
    await conn._handle_message(ack)
    second_task = conn._ping_task

    assert first_task is second_task
