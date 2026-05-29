"""Tests for Connection post-handshake behavior."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from genesis_mesh.transport.connection import Connection, ConnectionState
from genesis_mesh.transport.protocol import MeshMessage, MessageType


def _make_connection(peer_id: str = "peer-1", local_node_id: str = "node-local") -> Connection:
    """Create a Connection with a mock transport."""
    transport = MagicMock()
    transport.close = AsyncMock()
    transport.send = AsyncMock()
    return Connection(peer_id=peer_id, transport=transport, local_node_id=local_node_id)


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


@pytest.mark.asyncio
async def test_handle_message_does_not_establish_connection():
    """Connection establishment is owned by the Noise/runtime layer."""
    conn = _make_connection()
    conn.state = ConnectionState.HANDSHAKING

    message = MeshMessage(
        message_type=MessageType.DATA,
        sender_id="remote-peer",
        payload={},
    )

    with patch.object(conn, "set_established", wraps=conn.set_established) as mock_set:
        await conn._handle_message(message)
        mock_set.assert_not_called()

    assert conn.state == ConnectionState.HANDSHAKING
    assert conn._ping_task is None


@pytest.mark.asyncio
async def test_ping_response_uses_local_node_id():
    """PONG messages should use the configured local node ID."""
    conn = _make_connection(local_node_id="node-a")
    ping = MeshMessage(
        message_type=MessageType.PING,
        sender_id="remote-peer",
        recipient_id="node-a",
        payload={"timestamp": time.time()},
    )

    await conn._handle_message(ping)

    pong = await conn._send_queue.get()
    assert pong.message_type == MessageType.PONG
    assert pong.sender_id == "node-a"
    assert pong.recipient_id == "remote-peer"
