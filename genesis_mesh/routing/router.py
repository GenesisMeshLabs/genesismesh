"""Mesh router implementation."""

import asyncio
import logging
from typing import Optional, Callable, Dict

from ..transport.protocol import MeshMessage, MessageType
from ..transport.connection import Connection
from .table import RoutingTable, Route


logger = logging.getLogger(__name__)


class MeshRouter:
    """
    Handles packet forwarding and routing in the mesh network.

    Responsibilities:
    - Forward DATA messages to next hop
    - Handle routing protocol messages
    - Update routing table based on received routes
    - Prevent routing loops
    """

    def __init__(
        self,
        node_id: str,
        routing_table: RoutingTable,
        get_connection: Callable[[str], Optional[Connection]]
    ):
        """
        Initialize mesh router.

        Args:
            node_id: Local node ID
            routing_table: Routing table instance
            get_connection: Function to get connection by peer ID
        """
        self.node_id = node_id
        self.routing_table = routing_table
        self.get_connection = get_connection

        # Track message IDs to prevent loops
        self._seen_messages: Dict[str, float] = {}
        self._seen_cleanup_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start router background tasks."""
        self._seen_cleanup_task = asyncio.create_task(self._cleanup_seen_messages())
        logger.info("Mesh router started")

    async def stop(self):
        """Stop router background tasks."""
        if self._seen_cleanup_task:
            self._seen_cleanup_task.cancel()
            try:
                await self._seen_cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("Mesh router stopped")

    async def route_message(self, message: MeshMessage) -> bool:
        """
        Route a message to its destination.

        Args:
            message: Message to route

        Returns:
            True if message was forwarded, False otherwise
        """
        # Check if message is for us
        if message.recipient_id == self.node_id:
            return True  # Message delivered locally

        # Broadcast messages
        if message.recipient_id is None:
            return await self._broadcast_message(message)

        # Check for routing loops (message ID already seen)
        if message.message_id in self._seen_messages:
            logger.debug(f"Dropping duplicate message {message.message_id}")
            return False

        # Mark message as seen
        import time
        self._seen_messages[message.message_id] = time.time()

        # Check TTL
        if not message.decrement_ttl():
            logger.warning(f"Dropping message {message.message_id}: TTL expired")
            return False

        # Look up route
        route = self.routing_table.get_route(message.recipient_id)
        if not route:
            logger.warning(f"No route to destination {message.recipient_id}")
            return False

        # Get connection to next hop
        connection = self.get_connection(route.next_hop)
        if not connection:
            logger.warning(f"No connection to next hop {route.next_hop}")
            return False

        # Forward message
        try:
            await connection.send_message(message)
            logger.debug(
                f"Forwarded message {message.message_id} to {route.next_hop} "
                f"(dest={message.recipient_id}, ttl={message.ttl})"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to forward message: {e}")
            return False

    async def _broadcast_message(self, message: MeshMessage) -> bool:
        """
        Broadcast a message to all neighbors except the sender.

        Args:
            message: Message to broadcast

        Returns:
            True if broadcast to at least one peer
        """
        # Check for loops
        if message.message_id in self._seen_messages:
            return False

        import time
        self._seen_messages[message.message_id] = time.time()

        # Check TTL
        if not message.decrement_ttl():
            return False

        # Get all neighbors except sender
        neighbors = [
            peer_id for peer_id in self.routing_table.neighbors.keys()
            if peer_id != message.sender_id
        ]

        if not neighbors:
            return False

        # Send to all neighbors
        success_count = 0
        for peer_id in neighbors:
            connection = self.get_connection(peer_id)
            if connection:
                try:
                    await connection.send_message(message)
                    success_count += 1
                except Exception as e:
                    logger.error(f"Failed to broadcast to {peer_id}: {e}")

        logger.debug(f"Broadcasted message {message.message_id} to {success_count} peers")
        return success_count > 0

    async def send_to(self, destination: str, data: bytes) -> bool:
        """
        Send data to a destination node.

        Args:
            destination: Destination node ID
            data: Data to send

        Returns:
            True if sent successfully
        """
        from ..transport.protocol import create_data_message

        message = create_data_message(
            sender_id=self.node_id,
            recipient_id=destination,
            data=data
        )

        return await self.route_message(message)

    async def _cleanup_seen_messages(self):
        """Clean up old seen message IDs."""
        try:
            while True:
                await asyncio.sleep(60)  # Cleanup every minute

                import time
                now = time.time()
                stale_age = 300  # 5 minutes

                stale_ids = [
                    msg_id for msg_id, timestamp in self._seen_messages.items()
                    if (now - timestamp) > stale_age
                ]

                for msg_id in stale_ids:
                    del self._seen_messages[msg_id]

                if stale_ids:
                    logger.debug(f"Cleaned up {len(stale_ids)} seen message IDs")

        except asyncio.CancelledError:
            pass

    def get_stats(self) -> dict:
        """Get router statistics."""
        return {
            "seen_messages": len(self._seen_messages),
            "routing_table": self.routing_table.get_stats(),
        }
