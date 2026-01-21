"""Routing protocol implementation."""

import asyncio
import logging
from typing import Optional, Callable

from ..transport.protocol import (
    MeshMessage,
    MessageType,
    RouteInfo,
    create_route_announce
)
from .table import RoutingTable, Route


logger = logging.getLogger(__name__)


class RoutingProtocol:
    """
    Handles routing protocol operations.

    Implements a distance-vector routing protocol with:
    - Periodic route announcements
    - Sequence numbers for loop prevention
    - Route invalidation on topology changes
    """

    def __init__(
        self,
        node_id: str,
        routing_table: RoutingTable,
        broadcast_func: Callable
    ):
        """
        Initialize routing protocol.

        Args:
            node_id: Local node ID
            routing_table: Routing table instance
            broadcast_func: Function to broadcast messages
        """
        self.node_id = node_id
        self.routing_table = routing_table
        self.broadcast_func = broadcast_func

        self._announce_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """Start routing protocol."""
        if self._running:
            return

        self._running = True
        self._announce_task = asyncio.create_task(self._announce_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Routing protocol started")

    async def stop(self):
        """Stop routing protocol."""
        self._running = False

        if self._announce_task:
            self._announce_task.cancel()
            try:
                await self._announce_task
            except asyncio.CancelledError:
                pass

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        logger.info("Routing protocol stopped")

    async def _announce_loop(self):
        """Periodically announce routes to neighbors."""
        try:
            # Initial announcement after short delay
            await asyncio.sleep(5)

            while self._running:
                try:
                    await self._announce_routes()
                    await asyncio.sleep(30)  # Announce every 30 seconds

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in announce loop: {e}")
                    await asyncio.sleep(30)

        except asyncio.CancelledError:
            pass

    async def _cleanup_loop(self):
        """Periodically clean up stale routes."""
        try:
            while self._running:
                try:
                    await asyncio.sleep(60)  # Cleanup every minute
                    await self.routing_table.cleanup_stale_routes()

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in cleanup loop: {e}")
                    await asyncio.sleep(60)

        except asyncio.CancelledError:
            pass

    async def _announce_routes(self):
        """Announce our routing table to neighbors."""
        routes = self.routing_table.get_routes_to_announce()

        if not routes:
            logger.debug("No routes to announce")
            return

        # Convert to RouteInfo objects
        route_infos = []
        for route in routes:
            route_info = RouteInfo(
                destination=route.destination,
                next_hop=self.node_id,  # We are the next hop from neighbor's perspective
                metric=route.metric,
                sequence=route.sequence,
                timestamp=route.timestamp
            )
            route_infos.append(route_info)

        # Create and broadcast announcement
        message = create_route_announce(self.node_id, route_infos)

        try:
            await self.broadcast_func(message)
            logger.debug(f"Announced {len(route_infos)} routes")
        except Exception as e:
            logger.error(f"Failed to announce routes: {e}")

    async def handle_route_announce(self, message: MeshMessage):
        """
        Handle incoming route announcement.

        Args:
            message: Route announcement message
        """
        routes_data = message.payload.get("routes", [])
        logger.debug(f"Received {len(routes_data)} routes from {message.sender_id}")

        updated_count = 0

        for route_data in routes_data:
            try:
                route_info = RouteInfo(**route_data)

                # Ignore routes to ourselves
                if route_info.destination == self.node_id:
                    continue

                # Ignore routes through ourselves (would create loop)
                if route_info.next_hop == self.node_id:
                    continue

                # Update routing table
                updated = await self.routing_table.update_route(
                    destination=route_info.destination,
                    next_hop=message.sender_id,  # Sender is the next hop
                    metric=route_info.metric,
                    sequence=route_info.sequence,
                    learned_from=message.sender_id
                )

                if updated:
                    updated_count += 1

            except Exception as e:
                logger.error(f"Error processing route: {e}")

        if updated_count > 0:
            logger.info(f"Updated {updated_count} routes from {message.sender_id}")

    async def handle_route_update(self, message: MeshMessage):
        """Handle route update message."""
        # Same logic as route announce for now
        await self.handle_route_announce(message)

    async def handle_route_withdraw(self, message: MeshMessage):
        """
        Handle route withdrawal.

        Args:
            message: Route withdraw message
        """
        destinations = message.payload.get("destinations", [])
        logger.info(f"Received route withdraw for {len(destinations)} destinations from {message.sender_id}")

        # Remove routes learned from this peer
        for destination in destinations:
            route = self.routing_table.get_route(destination)
            if route and route.learned_from == message.sender_id:
                # In a full implementation, we'd mark route as invalid
                # For now, just let it expire naturally
                logger.debug(f"Route to {destination} via {message.sender_id} withdrawn")

    async def trigger_update(self):
        """Trigger an immediate route announcement."""
        await self._announce_routes()
