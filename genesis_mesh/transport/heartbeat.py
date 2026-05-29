"""Heartbeat and latency tracking for mesh peer connections."""

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from .protocol import MeshMessage, create_ping, create_pong

if TYPE_CHECKING:
    from .connection import Connection


logger = logging.getLogger(__name__)


class ConnectionHeartbeat:
    """Own periodic ping and ping/pong protocol handling for a connection."""

    def __init__(self, connection: "Connection", interval_seconds: int = 30):
        """Bind heartbeat tracking to a live `Connection` instance."""
        self.connection = connection
        self.interval_seconds = interval_seconds
        self.pending_pings: dict[str, float] = {}
        self.task: asyncio.Task | None = None

    def start(self) -> asyncio.Task:
        """Start the heartbeat loop if it is not already running."""
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self._run())
            logger.debug("Started ping loop for %s", self.connection.peer_id)
        return self.task

    def stop(self) -> None:
        """Cancel the heartbeat loop if it is running."""
        if self.task:
            self.task.cancel()

    async def handle_ping(self, message: MeshMessage) -> None:
        """Respond to an inbound ping from the remote peer."""
        pong = create_pong(
            self.connection.local_node_id,
            message.sender_id,
            message.payload.get("timestamp", time.time()),
        )
        await self.connection.send_message(pong)

    async def handle_pong(self, message: MeshMessage) -> None:
        """Record latency from a pong response."""
        ping_timestamp = message.payload.get("ping_timestamp")
        if ping_timestamp:
            latency = (time.time() - ping_timestamp) * 1000
            self.connection.stats.latency_ms = latency
            logger.debug("Latency to %s: %.2fms", self.connection.peer_id, latency)

    async def _run(self) -> None:
        """Send periodic pings until the connection leaves established state."""
        try:
            while self.connection.state.value == "established":
                try:
                    ping_msg = create_ping(
                        self.connection.local_node_id,
                        self.connection.peer_id,
                    )
                    self.pending_pings[ping_msg.message_id] = time.time()
                    await self.connection.send_message(ping_msg)

                    await asyncio.sleep(self.interval_seconds)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.error("Error in ping loop: %s", exc)
                    await asyncio.sleep(self.interval_seconds)
        except asyncio.CancelledError:
            pass
