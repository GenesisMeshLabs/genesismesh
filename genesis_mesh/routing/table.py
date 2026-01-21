"""Routing table management."""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Set
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass
class Route:
    """Represents a route to a destination."""
    destination: str  # Destination node ID
    next_hop: str  # Next hop node ID
    metric: int  # Route metric (hop count or cost)
    sequence: int  # Sequence number for loop prevention
    timestamp: float  # When route was learned
    learned_from: str  # Which peer we learned this from


class RoutingTable:
    """
    Manages routing information for mesh networking.

    Uses distance-vector style routing with sequence numbers
    for loop prevention.
    """

    def __init__(
        self,
        node_id: str,
        max_metric: int = 10,
        route_timeout: float = 300.0  # 5 minutes
    ):
        """
        Initialize routing table.

        Args:
            node_id: Local node ID
            max_metric: Maximum metric (routes beyond this are invalid)
            route_timeout: Route expiration time in seconds
        """
        self.node_id = node_id
        self.max_metric = max_metric
        self.route_timeout = route_timeout

        # Routing table: destination -> Route
        self.routes: Dict[str, Route] = {}

        # Direct neighbors: peer_id -> metric
        self.neighbors: Dict[str, int] = {}

        # Sequence numbers: node_id -> sequence
        self._sequences: Dict[str, int] = {}
        self._local_sequence = 0

        self._lock = asyncio.Lock()

        # Background maintenance
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def add_neighbor(self, peer_id: str, metric: int = 1):
        """
        Add a directly connected neighbor.

        Args:
            peer_id: Neighbor node ID
            metric: Link metric (default 1 for direct connection)
        """
        async with self._lock:
            self.neighbors[peer_id] = metric

            # Add direct route
            self._local_sequence += 1
            self.routes[peer_id] = Route(
                destination=peer_id,
                next_hop=peer_id,
                metric=metric,
                sequence=self._local_sequence,
                timestamp=time.time(),
                learned_from="direct"
            )

            logger.info(f"Added neighbor {peer_id} with metric {metric}")

    async def remove_neighbor(self, peer_id: str):
        """
        Remove a neighbor and invalidate routes through it.

        Args:
            peer_id: Neighbor to remove
        """
        async with self._lock:
            if peer_id in self.neighbors:
                del self.neighbors[peer_id]

            # Remove routes through this neighbor
            to_remove = [
                dest for dest, route in self.routes.items()
                if route.next_hop == peer_id
            ]

            for dest in to_remove:
                del self.routes[dest]
                logger.debug(f"Removed route to {dest} via {peer_id}")

            logger.info(f"Removed neighbor {peer_id}, invalidated {len(to_remove)} routes")

    async def update_route(
        self,
        destination: str,
        next_hop: str,
        metric: int,
        sequence: int,
        learned_from: str
    ) -> bool:
        """
        Update or add a route.

        Args:
            destination: Destination node ID
            next_hop: Next hop to reach destination
            metric: Route metric
            sequence: Route sequence number
            learned_from: Peer we learned this from

        Returns:
            True if route was updated, False otherwise
        """
        async with self._lock:
            # Ignore if destination is ourselves
            if destination == self.node_id:
                return False

            # Ignore if metric too high
            if metric > self.max_metric:
                return False

            # Ignore if next hop not a neighbor
            if next_hop not in self.neighbors:
                logger.debug(f"Ignoring route to {destination}: next_hop {next_hop} not a neighbor")
                return False

            # Check if we should accept this route
            existing = self.routes.get(destination)

            if existing:
                # Accept if higher sequence number
                if sequence > existing.sequence:
                    pass  # Accept
                # Accept if same sequence but better metric
                elif sequence == existing.sequence and metric < existing.metric:
                    pass  # Accept
                # Ignore if worse or same
                else:
                    return False

            # Add route with neighbor's metric
            total_metric = metric + self.neighbors[next_hop]

            if total_metric > self.max_metric:
                return False

            self.routes[destination] = Route(
                destination=destination,
                next_hop=next_hop,
                metric=total_metric,
                sequence=sequence,
                timestamp=time.time(),
                learned_from=learned_from
            )

            # Update sequence tracking
            self._sequences[destination] = sequence

            logger.info(
                f"Updated route to {destination} via {next_hop} "
                f"(metric={total_metric}, seq={sequence})"
            )
            return True

    def get_route(self, destination: str) -> Optional[Route]:
        """
        Get route to destination.

        Args:
            destination: Destination node ID

        Returns:
            Route if exists, None otherwise
        """
        return self.routes.get(destination)

    def get_next_hop(self, destination: str) -> Optional[str]:
        """
        Get next hop for destination.

        Args:
            destination: Destination node ID

        Returns:
            Next hop node ID, or None if no route
        """
        route = self.routes.get(destination)
        return route.next_hop if route else None

    def get_all_routes(self) -> List[Route]:
        """Get all routes."""
        return list(self.routes.values())

    def get_routes_to_announce(self) -> List[Route]:
        """
        Get routes suitable for announcement to peers.

        Excludes direct neighbor routes (they'll learn those themselves).
        """
        return [
            route for route in self.routes.values()
            if route.destination not in self.neighbors
        ]

    async def cleanup_stale_routes(self):
        """Remove expired routes."""
        async with self._lock:
            now = time.time()
            stale = [
                dest for dest, route in self.routes.items()
                if (now - route.timestamp) > self.route_timeout
                and dest not in self.neighbors  # Don't expire direct neighbors
            ]

            for dest in stale:
                del self.routes[dest]
                logger.debug(f"Removed stale route to {dest}")

            if stale:
                logger.info(f"Cleaned up {len(stale)} stale routes")

    def get_local_sequence(self) -> int:
        """Get current local sequence number."""
        return self._local_sequence

    def increment_local_sequence(self) -> int:
        """Increment and return local sequence number."""
        self._local_sequence += 1
        return self._local_sequence

    async def start(self, cleanup_interval: float = 60.0):
        """
        Start routing table maintenance.

        Args:
            cleanup_interval: Interval between cleanup runs in seconds
        """
        if self._running:
            return

        self._running = True
        self._cleanup_task = asyncio.create_task(
            self._maintenance_loop(cleanup_interval)
        )
        logger.info("Routing table maintenance started")

    async def stop(self):
        """Stop routing table maintenance."""
        self._running = False

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        logger.info("Routing table maintenance stopped")

    async def _maintenance_loop(self, interval: float):
        """Periodically clean up stale routes."""
        try:
            while self._running:
                try:
                    await asyncio.sleep(interval)
                    await self.cleanup_stale_routes()

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in routing maintenance: {e}")
                    await asyncio.sleep(interval)

        except asyncio.CancelledError:
            pass

    def get_stats(self) -> dict:
        """Get routing statistics."""
        return {
            "total_routes": len(self.routes),
            "direct_neighbors": len(self.neighbors),
            "destinations": list(self.routes.keys()),
            "avg_metric": sum(r.metric for r in self.routes.values()) / max(len(self.routes), 1),
        }
