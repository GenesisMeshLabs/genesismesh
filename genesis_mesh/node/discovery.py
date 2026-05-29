"""Peer discovery protocols."""

import asyncio
import logging
import time
import uuid
from typing import List, Optional, Callable

from ..transport.protocol import (
    MeshMessage,
    MessageType,
    PeerInfo,
    create_peer_announce
)
from .peer_manager import PeerManager


logger = logging.getLogger(__name__)

MAX_PEERS_PER_DISCOVERY_MESSAGE = 20
ANNOUNCEMENT_MAX_AGE_SECONDS = 300.0
ANNOUNCEMENT_MAX_FUTURE_SKEW_SECONDS = 60.0


class PeerDiscovery:
    """
    Handles peer discovery and exchange.

    Uses gossip-style peer list exchange to discover new peers
    throughout the mesh network.
    """

    def __init__(
        self,
        node_id: str,
        peer_manager: PeerManager,
        bootstrap_anchors: List[str],
        on_peer_discovered: Optional[Callable] = None,
        local_peer_info_factory: Optional[Callable[[], PeerInfo]] = None,
        sign_peer_info: Optional[Callable[[PeerInfo], PeerInfo]] = None,
        verify_peer_info: Optional[Callable[[PeerInfo], tuple[bool, list[str]]]] = None,
    ):
        """
        Initialize peer discovery.

        Args:
            node_id: Local node ID
            peer_manager: Peer manager instance
            bootstrap_anchors: List of bootstrap anchor endpoints (host:port)
            on_peer_discovered: Callback when new peer is discovered
            local_peer_info_factory: Builds the local peer announcement
            sign_peer_info: Signs a peer announcement before it is gossiped
            verify_peer_info: Verifies a received peer announcement and returns roles
        """
        self.node_id = node_id
        self.peer_manager = peer_manager
        self.bootstrap_anchors = bootstrap_anchors
        self.on_peer_discovered = on_peer_discovered
        self.local_peer_info_factory = local_peer_info_factory
        self.sign_peer_info = sign_peer_info
        self.verify_peer_info = verify_peer_info
        self._seen_announcement_nonces: dict[str, set[str]] = {}

        self._discovery_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """Start peer discovery."""
        if self._running:
            return

        self._running = True
        self._discovery_task = asyncio.create_task(self._discovery_loop())
        logger.info("Peer discovery started")

    async def stop(self):
        """Stop peer discovery."""
        self._running = False
        if self._discovery_task:
            self._discovery_task.cancel()
            try:
                await self._discovery_task
            except asyncio.CancelledError:
                pass
        logger.info("Peer discovery stopped")

    async def bootstrap(self, connect_func: Callable):
        """
        Bootstrap by connecting to anchor nodes.

        Args:
            connect_func: Function to establish connections to peers
        """
        logger.info(f"Bootstrapping from {len(self.bootstrap_anchors)} anchors")

        for anchor_endpoint in self.bootstrap_anchors:
            try:
                # Parse endpoint
                parts = anchor_endpoint.split(':')
                if len(parts) != 2:
                    logger.error(f"Invalid anchor endpoint: {anchor_endpoint}")
                    continue

                host, port = parts[0], int(parts[1])

                # Create peer info for anchor
                peer_info = PeerInfo(
                    node_id=f"anchor-{host}",  # Temporary ID until handshake
                    endpoint=anchor_endpoint,
                    roles=["role:anchor"],
                    last_seen=time.time()
                )

                # Add to peer manager
                await self.peer_manager.add_peer(peer_info, is_anchor=True)

                # Attempt connection
                try:
                    await connect_func(anchor_endpoint, peer_info)
                    logger.info(f"Connected to bootstrap anchor: {anchor_endpoint}")
                except Exception as e:
                    logger.warning(f"Failed to connect to anchor {anchor_endpoint}: {e}")

            except Exception as e:
                logger.error(f"Error bootstrapping from {anchor_endpoint}: {e}")

    async def _discovery_loop(self):
        """Periodically request and announce peers."""
        try:
            while self._running:
                try:
                    # Request peer lists from connected peers
                    await self._request_peers()

                    # Announce our known peers to connected peers
                    await self._announce_peers()

                    # Wait before next discovery round
                    await asyncio.sleep(60)  # Discovery every 60 seconds

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in discovery loop: {e}")
                    await asyncio.sleep(60)

        except asyncio.CancelledError:
            pass

    async def _request_peers(self):
        """Request peer lists from connected peers."""
        connected = self.peer_manager.get_connected_peers()

        if not connected:
            logger.debug("No connected peers to request from")
            return

        # Request from anchors first, then regular peers
        anchors = [p for p in connected if p.is_anchor]
        regular = [p for p in connected if not p.is_anchor]

        # Request from all anchors and a few random regular peers
        import random
        targets = anchors + random.sample(regular, min(3, len(regular)))

        for peer_state in targets:
            if peer_state.connection:
                message = MeshMessage(
                    message_type=MessageType.PEER_REQUEST,
                    sender_id=self.node_id,
                    recipient_id=peer_state.info.node_id,
                    payload={}
                )
                try:
                    await peer_state.connection.send_message(message)
                    logger.debug(f"Requested peers from {peer_state.info.node_id}")
                except Exception as e:
                    logger.error(f"Failed to request peers from {peer_state.info.node_id}: {e}")

    async def _announce_peers(self):
        """Announce known peers to connected peers."""
        peers_to_share = self._peers_to_share()

        if not peers_to_share:
            return

        # Create announcement message
        message = create_peer_announce(self.node_id, peers_to_share)

        # Send to all connected peers
        connected = self.peer_manager.get_connected_peers()
        for peer_state in connected:
            if peer_state.connection:
                try:
                    await peer_state.connection.send_message(message)
                    logger.debug(f"Announced {len(peers_to_share)} peers to {peer_state.info.node_id}")
                except Exception as e:
                    logger.error(f"Failed to announce peers to {peer_state.info.node_id}: {e}")

    async def handle_peer_request(self, message: MeshMessage, connection):
        """
        Handle incoming peer request.

        Args:
            message: Peer request message
            connection: Connection that sent the request
        """
        logger.debug(f"Received peer request from {message.sender_id}")

        peers_to_share = self._peers_to_share()

        # Send response
        response = MeshMessage(
            message_type=MessageType.PEER_RESPONSE,
            sender_id=self.node_id,
            recipient_id=message.sender_id,
            payload={"peers": [p.model_dump() for p in peers_to_share]}
        )

        try:
            await connection.send_message(response)
            logger.debug(f"Sent {len(peers_to_share)} peers to {message.sender_id}")
        except Exception as e:
            logger.error(f"Failed to send peer response: {e}")

    async def handle_peer_response(self, message: MeshMessage):
        """
        Handle incoming peer response.

        Args:
            message: Peer response message
        """
        peers_data = message.payload.get("peers", [])[:MAX_PEERS_PER_DISCOVERY_MESSAGE]
        logger.info(f"Received {len(peers_data)} peers from {message.sender_id}")

        # Process each peer
        for peer_data in peers_data:
            try:
                peer_info = PeerInfo(**peer_data)

                # Skip if it's us
                if peer_info.node_id == self.node_id:
                    continue

                validated_peer = self._validate_peer_announcement(peer_info)
                if validated_peer is None:
                    continue
                peer_info = validated_peer

                # Check if already known
                existing = self.peer_manager.get_peer(peer_info.node_id)
                if existing:
                    # Update last_seen
                    existing.info.last_seen = time.time()
                    continue

                # Add new peer
                await self.peer_manager.add_peer(peer_info)

                # Notify callback
                if self.on_peer_discovered:
                    try:
                        await self.on_peer_discovered(peer_info)
                    except Exception as e:
                        logger.error(f"Error in peer discovered callback: {e}")

            except Exception as e:
                logger.error(f"Error processing peer data: {e}")

    async def handle_peer_announce(self, message: MeshMessage):
        """
        Handle incoming peer announcement.

        Args:
            message: Peer announcement message
        """
        # Same logic as handle_peer_response
        await self.handle_peer_response(message)

    def _peers_to_share(self) -> list[PeerInfo]:
        """Return signed peer announcements safe to share through discovery."""
        peers: list[PeerInfo] = []
        local_peer = self._signed_local_peer_info()
        if local_peer:
            peers.append(local_peer)

        known = self.peer_manager.get_peers_for_discovery(
            count=MAX_PEERS_PER_DISCOVERY_MESSAGE
        )
        for peer in known:
            if peer.node_id == self.node_id:
                continue
            if not peer.announcement_signature:
                continue
            peers.append(peer)
            if len(peers) >= MAX_PEERS_PER_DISCOVERY_MESSAGE:
                break
        return peers

    def _signed_local_peer_info(self) -> Optional[PeerInfo]:
        """Build and sign the local peer announcement if callbacks are configured."""
        if not self.local_peer_info_factory or not self.sign_peer_info:
            return None
        peer_info = self.local_peer_info_factory()
        peer_info.announcement_issued_at = time.time()
        peer_info.announcement_nonce = str(uuid.uuid4())
        return self.sign_peer_info(peer_info)

    def _validate_peer_announcement(self, peer_info: PeerInfo) -> Optional[PeerInfo]:
        """Validate a gossiped peer announcement and derive trusted roles."""
        if not self.verify_peer_info:
            logger.warning("Skipping peer %s: discovery verifier not configured", peer_info.node_id)
            return None
        if not peer_info.cert_id:
            logger.warning("Skipping peer %s: missing cert_id", peer_info.node_id)
            return None
        if not peer_info.announcement_signature:
            logger.warning("Skipping peer %s: missing announcement signature", peer_info.node_id)
            return None
        if not peer_info.announcement_issued_at:
            logger.warning("Skipping peer %s: missing announcement timestamp", peer_info.node_id)
            return None
        if not peer_info.announcement_nonce:
            logger.warning("Skipping peer %s: missing announcement nonce", peer_info.node_id)
            return None

        now = time.time()
        age = now - peer_info.announcement_issued_at
        future_skew = peer_info.announcement_issued_at - now
        if age > ANNOUNCEMENT_MAX_AGE_SECONDS or future_skew > ANNOUNCEMENT_MAX_FUTURE_SKEW_SECONDS:
            logger.warning("Skipping peer %s: stale announcement", peer_info.node_id)
            return None

        seen_for_peer = self._seen_announcement_nonces.setdefault(peer_info.node_id, set())
        if peer_info.announcement_nonce in seen_for_peer:
            logger.warning("Skipping peer %s: replayed announcement nonce", peer_info.node_id)
            return None

        verified, trusted_roles = self.verify_peer_info(peer_info)
        if not verified:
            logger.warning("Skipping peer %s: invalid announcement signature", peer_info.node_id)
            return None

        peer_info.roles = trusted_roles
        seen_for_peer.add(peer_info.announcement_nonce)
        return peer_info
