"""Connection management for mesh networking."""

import asyncio
import logging
import time
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass
from enum import Enum

from .protocol import MeshMessage, MessageType


logger = logging.getLogger(__name__)


class ConnectionState(str, Enum):
    """Connection lifecycle states."""
    CONNECTING = "connecting"
    HANDSHAKING = "handshaking"
    ESTABLISHED = "established"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


@dataclass
class ConnectionStats:
    """Connection statistics."""
    messages_sent: int = 0
    messages_received: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    last_activity: float = 0
    latency_ms: Optional[float] = None
    errors: int = 0
    dropped_messages: int = 0
    queue_size: int = 0


class Connection:
    """
    Represents a connection to a peer node.

    Handles message sending/receiving, state management, and health tracking.
    """

    def __init__(
        self,
        peer_id: str,
        transport: Any,
        on_message: Optional[Callable] = None,
        on_close: Optional[Callable] = None,
        max_queue_size: int = 1000,
        drop_on_full: bool = True
    ):
        """
        Initialize connection.

        Args:
            peer_id: Remote peer node ID
            transport: Transport implementation (WebSocket, QUIC, etc.)
            on_message: Callback for received messages
            on_close: Callback when connection closes
            max_queue_size: Maximum size of send queue (default: 1000)
            drop_on_full: Drop messages when queue is full (default: True)
        """
        self.peer_id = peer_id
        self.transport = transport
        self.on_message = on_message
        self.on_close = on_close
        self.max_queue_size = max_queue_size
        self.drop_on_full = drop_on_full

        self.state = ConnectionState.CONNECTING
        self.stats = ConnectionStats()
        self.connected_at: Optional[float] = None
        self._send_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._receive_task: Optional[asyncio.Task] = None
        self._send_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None
        self._pending_pings: Dict[str, float] = {}
        self._dropped_messages = 0

    async def start(self):
        """Start connection tasks."""
        self._receive_task = asyncio.create_task(self._receive_loop())
        self._send_task = asyncio.create_task(self._send_loop())
        # Note: ping_task will be started when connection is established
        logger.info(f"Connection to {self.peer_id} started")

    async def send_message(self, message: MeshMessage, priority: bool = False):
        """
        Send a message to the peer with backpressure handling.

        Args:
            message: Message to send
            priority: If True, wait for queue space; if False and drop_on_full=True,
                     drop the message when queue is full

        Raises:
            asyncio.QueueFull: If priority=False and drop_on_full=False and queue is full
        """
        try:
            if priority or not self.drop_on_full:
                # High priority or configured to wait - block until queue has space
                await self._send_queue.put(message)
            else:
                # Try to send without blocking
                self._send_queue.put_nowait(message)
        except asyncio.QueueFull:
            if priority or not self.drop_on_full:
                # Should not happen for priority messages, but log anyway
                logger.warning(
                    f"Send queue full for {self.peer_id}, blocking until space available"
                )
                await self._send_queue.put(message)
            else:
                # Drop message due to backpressure
                self._dropped_messages += 1
                logger.warning(
                    f"Dropped message to {self.peer_id} due to full send queue "
                    f"(queue size: {self._send_queue.qsize()}, total dropped: {self._dropped_messages})"
                )
                # Update error stats
                self.stats.errors += 1
                raise

    def set_established(self):
        """
        Explicitly mark connection as established.

        This should be called after successful handshake completion.
        Starts the ping loop for latency monitoring.
        """
        if self.state == ConnectionState.ESTABLISHED:
            return

        old_state = self.state
        self.state = ConnectionState.ESTABLISHED
        self.connected_at = time.time()
        logger.info(f"Connection to {self.peer_id} marked as established")

        # Start ping loop
        if not self._ping_task:
            self._ping_task = asyncio.create_task(self._ping_loop())
            logger.debug(f"Started ping loop for {self.peer_id}")

    async def close(self):
        """Close the connection gracefully."""
        if self.state in (ConnectionState.CLOSING, ConnectionState.CLOSED):
            return

        logger.info(f"Closing connection to {self.peer_id}")
        self.state = ConnectionState.CLOSING

        # Cancel tasks
        if self._receive_task:
            self._receive_task.cancel()
        if self._send_task:
            self._send_task.cancel()
        if self._ping_task:
            self._ping_task.cancel()

        # Close transport
        try:
            await self.transport.close()
        except Exception as e:
            logger.error(f"Error closing transport: {e}")

        self.state = ConnectionState.CLOSED

        # Notify callback
        if self.on_close:
            try:
                await self.on_close(self)
            except Exception as e:
                logger.error(f"Error in close callback: {e}")

    async def _receive_loop(self):
        """Receive messages from transport."""
        try:
            while self.state not in (ConnectionState.CLOSING, ConnectionState.CLOSED):
                try:
                    data = await self.transport.receive()
                    if data is None:
                        break

                    message = MeshMessage.from_bytes(data)
                    self.stats.messages_received += 1
                    self.stats.bytes_received += len(data)
                    self.stats.last_activity = time.time()

                    await self._handle_message(message)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error receiving message from {self.peer_id}: {e}")
                    self.stats.errors += 1
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            pass
        finally:
            await self.close()

    async def _send_loop(self):
        """Send queued messages."""
        try:
            while self.state not in (ConnectionState.CLOSING, ConnectionState.CLOSED):
                try:
                    message = await asyncio.wait_for(
                        self._send_queue.get(),
                        timeout=1.0
                    )

                    data = message.to_bytes()
                    await self.transport.send(data)

                    self.stats.messages_sent += 1
                    self.stats.bytes_sent += len(data)
                    self.stats.last_activity = time.time()

                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error sending message to {self.peer_id}: {e}")
                    self.stats.errors += 1
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            pass

    async def _ping_loop(self):
        """Periodically ping peer to measure latency."""
        try:
            while self.state == ConnectionState.ESTABLISHED:
                try:
                    from .protocol import create_ping
                    ping_msg = create_ping("local", self.peer_id)
                    self._pending_pings[ping_msg.message_id] = time.time()
                    await self.send_message(ping_msg)

                    await asyncio.sleep(30)  # Ping every 30 seconds
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in ping loop: {e}")
                    await asyncio.sleep(30)

        except asyncio.CancelledError:
            pass

    async def _handle_message(self, message: MeshMessage):
        """Handle received message."""
        # Handle protocol messages
        if message.message_type == MessageType.PING:
            await self._handle_ping(message)
        elif message.message_type == MessageType.PONG:
            await self._handle_pong(message)
        elif message.message_type == MessageType.HANDSHAKE_ACK:
            # Transition to ESTABLISHED state
            old_state = self.state
            self.state = ConnectionState.ESTABLISHED
            self.connected_at = time.time()
            logger.info(f"Connection to {self.peer_id} established")

            # Start ping loop now that connection is established
            if old_state != ConnectionState.ESTABLISHED and not self._ping_task:
                self._ping_task = asyncio.create_task(self._ping_loop())
                logger.debug(f"Started ping loop for {self.peer_id}")

        # Forward to application callback
        if self.on_message:
            try:
                await self.on_message(message, self)
            except Exception as e:
                logger.error(f"Error in message callback: {e}")

    async def _handle_ping(self, message: MeshMessage):
        """Respond to ping."""
        from .protocol import create_pong
        pong = create_pong(
            "local",
            message.sender_id,
            message.payload.get("timestamp", time.time())
        )
        await self.send_message(pong)

    async def _handle_pong(self, message: MeshMessage):
        """Process pong response."""
        ping_timestamp = message.payload.get("ping_timestamp")
        if ping_timestamp:
            latency = (time.time() - ping_timestamp) * 1000  # Convert to ms
            self.stats.latency_ms = latency
            logger.debug(f"Latency to {self.peer_id}: {latency:.2f}ms")

    def get_stats_snapshot(self) -> ConnectionStats:
        """
        Get a snapshot of connection statistics.

        Returns:
            ConnectionStats with current values
        """
        # Update dynamic stats
        self.stats.dropped_messages = self._dropped_messages
        self.stats.queue_size = self._send_queue.qsize()
        return self.stats


class ConnectionPool:
    """
    Manages multiple peer connections.

    Provides connection pooling, health tracking, and connection limits.
    """

    def __init__(self, max_connections: int = 50):
        """
        Initialize connection pool.

        Args:
            max_connections: Maximum concurrent connections
        """
        self.max_connections = max_connections
        self.connections: Dict[str, Connection] = {}
        self._lock = asyncio.Lock()

    async def add_connection(self, connection: Connection) -> bool:
        """
        Add a connection to the pool.

        Args:
            connection: Connection to add

        Returns:
            True if added, False if pool is full
        """
        async with self._lock:
            if len(self.connections) >= self.max_connections:
                logger.warning("Connection pool full, rejecting connection")
                return False

            self.connections[connection.peer_id] = connection
            logger.info(f"Added connection to {connection.peer_id} (total: {len(self.connections)})")
            return True

    async def remove_connection(self, peer_id: str):
        """Remove a connection from the pool."""
        async with self._lock:
            if peer_id in self.connections:
                connection = self.connections.pop(peer_id)
                await connection.close()
                logger.info(f"Removed connection to {peer_id} (total: {len(self.connections)})")

    def get_connection(self, peer_id: str) -> Optional[Connection]:
        """Get a connection by peer ID."""
        return self.connections.get(peer_id)

    async def broadcast(self, message: MeshMessage, exclude: Optional[set] = None):
        """
        Broadcast a message to all connected peers.

        Args:
            message: Message to broadcast
            exclude: Set of peer IDs to exclude
        """
        exclude = exclude or set()
        tasks = []

        for peer_id, conn in self.connections.items():
            if peer_id not in exclude and conn.state == ConnectionState.ESTABLISHED:
                tasks.append(conn.send_message(message))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close_all(self):
        """Close all connections."""
        tasks = [conn.close() for conn in self.connections.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.connections.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for all connections."""
        total_dropped = 0
        total_queue_size = 0

        connection_stats = {}
        for peer_id, conn in self.connections.items():
            stats = conn.get_stats_snapshot()
            total_dropped += stats.dropped_messages
            total_queue_size += stats.queue_size

            connection_stats[peer_id] = {
                "state": conn.state.value,
                "messages_sent": stats.messages_sent,
                "messages_received": stats.messages_received,
                "latency_ms": stats.latency_ms,
                "errors": stats.errors,
                "dropped_messages": stats.dropped_messages,
                "queue_size": stats.queue_size,
            }

        return {
            "total_connections": len(self.connections),
            "established": sum(
                1 for c in self.connections.values()
                if c.state == ConnectionState.ESTABLISHED
            ),
            "total_dropped_messages": total_dropped,
            "total_queue_size": total_queue_size,
            "connections": connection_stats
        }
