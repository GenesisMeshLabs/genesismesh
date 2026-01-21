"""Peer management and lifecycle."""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field

from ..transport.protocol import PeerInfo
from ..transport.connection import Connection, ConnectionState


logger = logging.getLogger(__name__)


@dataclass
class PeerState:
    """Extended peer state tracking."""
    info: PeerInfo
    connection: Optional[Connection] = None
    last_handshake: Optional[float] = None
    failed_attempts: int = 0
    is_anchor: bool = False
    connection_attempts: int = 0
    last_attempt: Optional[float] = None
    blacklisted_until: Optional[float] = None


class PeerManager:
    """
    Manages peer discovery, connection lifecycle, and reputation.

    Responsibilities:
    - Track known peers
    - Manage peer connections
    - Handle peer reputation
    - Coordinate peer discovery
    - Enforce connection limits
    """

    def __init__(
        self,
        node_id: str,
        max_peers: int = 50,
        max_anchors: int = 10,
        blacklist_duration: float = 300.0  # 5 minutes
    ):
        """
        Initialize peer manager.

        Args:
            node_id: Local node ID
            max_peers: Maximum peer connections
            max_anchors: Maximum anchor connections
            blacklist_duration: How long to blacklist misbehaving peers (seconds)
        """
        self.node_id = node_id
        self.max_peers = max_peers
        self.max_anchors = max_anchors
        self.blacklist_duration = blacklist_duration

        self.peers: Dict[str, PeerState] = {}
        self._lock = asyncio.Lock()

    async def add_peer(
        self,
        peer_info: PeerInfo,
        is_anchor: bool = False,
        connection: Optional[Connection] = None
    ) -> bool:
        """
        Add a peer to the known peers list.

        Args:
            peer_info: Peer information
            is_anchor: Whether this is an anchor node
            connection: Existing connection (if any)

        Returns:
            True if peer was added, False otherwise
        """
        async with self._lock:
            if peer_info.node_id == self.node_id:
                return False  # Don't add self

            # Check if blacklisted
            if peer_info.node_id in self.peers:
                state = self.peers[peer_info.node_id]
                if state.blacklisted_until and time.time() < state.blacklisted_until:
                    logger.warning(f"Peer {peer_info.node_id} is blacklisted")
                    return False

            # Check connection limits
            if peer_info.node_id not in self.peers:
                anchor_count = sum(1 for p in self.peers.values() if p.is_anchor)
                peer_count = len(self.peers)

                if is_anchor and anchor_count >= self.max_anchors:
                    logger.warning("Maximum anchor connections reached")
                    return False

                if peer_count >= self.max_peers:
                    logger.warning("Maximum peer connections reached")
                    return False

            # Add or update peer
            if peer_info.node_id in self.peers:
                state = self.peers[peer_info.node_id]
                state.info = peer_info
                if connection:
                    state.connection = connection
                state.is_anchor = is_anchor
            else:
                state = PeerState(
                    info=peer_info,
                    connection=connection,
                    is_anchor=is_anchor,
                    last_handshake=time.time() if connection else None
                )
                self.peers[peer_info.node_id] = state

            logger.info(f"Added peer {peer_info.node_id} (anchor={is_anchor})")
            return True

    async def remove_peer(self, peer_id: str):
        """Remove a peer."""
        async with self._lock:
            if peer_id in self.peers:
                state = self.peers.pop(peer_id)
                if state.connection:
                    await state.connection.close()
                logger.info(f"Removed peer {peer_id}")

    def get_peer(self, peer_id: str) -> Optional[PeerState]:
        """Get peer state by ID."""
        return self.peers.get(peer_id)

    def get_all_peers(self) -> List[PeerState]:
        """Get all peers."""
        return list(self.peers.values())

    def get_connected_peers(self) -> List[PeerState]:
        """Get peers with established connections."""
        return [
            p for p in self.peers.values()
            if p.connection and p.connection.state == ConnectionState.ESTABLISHED
        ]

    def get_anchor_peers(self) -> List[PeerState]:
        """Get anchor peers."""
        return [p for p in self.peers.values() if p.is_anchor]

    async def update_reputation(self, peer_id: str, delta: float):
        """
        Update peer reputation score.

        Args:
            peer_id: Peer to update
            delta: Reputation change (positive or negative)
        """
        async with self._lock:
            if peer_id in self.peers:
                peer = self.peers[peer_id]
                peer.info.reputation = max(0.0, min(1.0, peer.info.reputation + delta))

                # Blacklist if reputation too low
                if peer.info.reputation < 0.1:
                    await self.blacklist_peer(peer_id)

    async def blacklist_peer(self, peer_id: str):
        """
        Blacklist a peer temporarily.

        Args:
            peer_id: Peer to blacklist
        """
        async with self._lock:
            if peer_id in self.peers:
                state = self.peers[peer_id]
                state.blacklisted_until = time.time() + self.blacklist_duration
                if state.connection:
                    await state.connection.close()
                logger.warning(f"Blacklisted peer {peer_id} for {self.blacklist_duration}s")

    async def record_connection_attempt(self, peer_id: str, success: bool):
        """
        Record a connection attempt.

        Args:
            peer_id: Peer ID
            success: Whether attempt was successful
        """
        async with self._lock:
            if peer_id in self.peers:
                state = self.peers[peer_id]
                state.connection_attempts += 1
                state.last_attempt = time.time()

                if not success:
                    state.failed_attempts += 1
                    await self.update_reputation(peer_id, -0.1)

                    # Blacklist after too many failures
                    if state.failed_attempts >= 5:
                        await self.blacklist_peer(peer_id)
                else:
                    state.failed_attempts = 0
                    state.last_handshake = time.time()

    def get_peers_for_discovery(self, count: int = 5) -> List[PeerInfo]:
        """
        Get a random sample of peers for peer exchange.

        Args:
            count: Number of peers to return

        Returns:
            List of peer information
        """
        import random

        # Prefer high-reputation peers
        candidates = [
            p.info for p in self.peers.values()
            if p.info.reputation > 0.5 and not p.blacklisted_until
        ]

        if len(candidates) <= count:
            return candidates

        return random.sample(candidates, count)

    def get_best_peers(self, count: int, role_filter: Optional[str] = None) -> List[PeerState]:
        """
        Get the best peers by reputation and latency.

        Args:
            count: Number of peers to return
            role_filter: Filter by role (e.g., "role:anchor")

        Returns:
            List of peer states
        """
        candidates = self.get_connected_peers()

        if role_filter:
            candidates = [p for p in candidates if role_filter in p.info.roles]

        # Sort by reputation (descending) and latency (ascending)
        candidates.sort(
            key=lambda p: (
                -p.info.reputation,
                p.info.latency_ms if p.info.latency_ms else 99999
            )
        )

        return candidates[:count]

    async def cleanup_stale_peers(self, max_age: float = 3600.0):
        """
        Remove peers that haven't been seen recently.

        Args:
            max_age: Maximum age in seconds
        """
        async with self._lock:
            now = time.time()
            stale_peers = [
                peer_id for peer_id, state in self.peers.items()
                if (now - state.info.last_seen) > max_age
                and (not state.connection or state.connection.state != ConnectionState.ESTABLISHED)
            ]

            for peer_id in stale_peers:
                logger.info(f"Removing stale peer {peer_id}")
                await self.remove_peer(peer_id)

    def get_stats(self) -> dict:
        """Get peer management statistics."""
        connected = self.get_connected_peers()
        anchors = self.get_anchor_peers()

        return {
            "total_peers": len(self.peers),
            "connected_peers": len(connected),
            "anchor_peers": len(anchors),
            "avg_reputation": sum(p.info.reputation for p in self.peers.values()) / max(len(self.peers), 1),
            "blacklisted_peers": sum(
                1 for p in self.peers.values()
                if p.blacklisted_until and time.time() < p.blacklisted_until
            ),
        }
