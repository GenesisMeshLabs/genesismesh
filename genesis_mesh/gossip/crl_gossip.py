"""CRL distribution via gossip protocol."""

import asyncio
import logging
from typing import Optional, Callable, Dict
import time

from ..models.revocation import CertificateRevocationList
from ..transport.protocol import MeshMessage, MessageType
from ..crypto import verify_model_signature


logger = logging.getLogger(__name__)


class CRLGossip:
    """
    Distributes Certificate Revocation List via gossip protocol.

    - Nodes periodically announce their CRL sequence number
    - Nodes with older CRL request updates
    - CRLs are verified before acceptance
    - Emergency push for immediate revocations
    """

    def __init__(
        self,
        node_id: str,
        get_public_key: Callable[[str], Optional[str]],
        broadcast_func: Callable
    ):
        """
        Initialize CRL gossip.

        Args:
            node_id: Local node ID
            get_public_key: Function to get public key by key ID
            broadcast_func: Function to broadcast messages
        """
        self.node_id = node_id
        self.get_public_key = get_public_key
        self.broadcast_func = broadcast_func

        self.current_crl: Optional[CertificateRevocationList] = None
        self._crl_cache: Dict[int, CertificateRevocationList] = {}  # sequence -> CRL

        self._gossip_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

        # Cache retention settings
        self._max_cache_entries = 50  # Keep last 50 CRL versions
        self._cache_retention_age = 86400.0  # 24 hours

    async def start(self):
        """Start CRL gossip."""
        if self._running:
            return

        self._running = True
        self._gossip_task = asyncio.create_task(self._gossip_loop())
        self._cleanup_task = asyncio.create_task(self._cache_cleanup_loop())
        logger.info("CRL gossip started with cache cleanup")

    async def stop(self):
        """Stop CRL gossip."""
        self._running = False

        if self._gossip_task:
            self._gossip_task.cancel()
            try:
                await self._gossip_task
            except asyncio.CancelledError:
                pass

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        logger.info("CRL gossip stopped")

    async def _gossip_loop(self):
        """Periodically gossip CRL sequence number."""
        try:
            while self._running:
                try:
                    await self._announce_crl_sequence()
                    await asyncio.sleep(60)  # Gossip every minute

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in CRL gossip loop: {e}")
                    await asyncio.sleep(60)

        except asyncio.CancelledError:
            pass

    async def _announce_crl_sequence(self):
        """Announce our current CRL sequence number."""
        if not self.current_crl:
            return

        message = MeshMessage(
            message_type=MessageType.REVOCATION,
            sender_id=self.node_id,
            payload={
                "action": "announce_sequence",
                "sequence": self.current_crl.sequence,
                "crl_id": self.current_crl.crl_id
            }
        )

        try:
            await self.broadcast_func(message)
            logger.debug(f"Announced CRL sequence: {self.current_crl.sequence}")
        except Exception as e:
            logger.error(f"Failed to announce CRL sequence: {e}")

    async def handle_crl_announce(self, message: MeshMessage, connection):
        """
        Handle CRL sequence announcement from peer.

        Args:
            message: CRL announcement message
            connection: Connection that sent the message
        """
        peer_sequence = message.payload.get("sequence", 0)
        peer_crl_id = message.payload.get("crl_id")

        if not self.current_crl:
            # We don't have a CRL, request it
            await self._request_crl(message.sender_id, connection)
            return

        if peer_sequence > self.current_crl.sequence:
            # Peer has newer CRL, request it
            logger.info(f"Peer {message.sender_id} has newer CRL (seq {peer_sequence} > {self.current_crl.sequence})")
            await self._request_crl(message.sender_id, connection)
        elif peer_sequence < self.current_crl.sequence:
            # We have newer CRL, send it to peer
            logger.info(f"Sending newer CRL to {message.sender_id}")
            await self._send_crl(message.sender_id, connection)

    async def _request_crl(self, peer_id: str, connection):
        """Request CRL from peer."""
        message = MeshMessage(
            message_type=MessageType.REVOCATION,
            sender_id=self.node_id,
            recipient_id=peer_id,
            payload={"action": "request_crl"}
        )

        try:
            await connection.send_message(message)
            logger.debug(f"Requested CRL from {peer_id}")
        except Exception as e:
            logger.error(f"Failed to request CRL: {e}")

    async def _send_crl(self, recipient_id: str, connection):
        """Send our CRL to a peer."""
        if not self.current_crl:
            return

        message = MeshMessage(
            message_type=MessageType.REVOCATION,
            sender_id=self.node_id,
            recipient_id=recipient_id,
            payload={
                "action": "crl_data",
                "crl": self.current_crl.model_dump(mode='json')
            }
        )

        try:
            await connection.send_message(message)
            logger.debug(f"Sent CRL to {recipient_id}")
        except Exception as e:
            logger.error(f"Failed to send CRL: {e}")

    async def handle_crl_request(self, message: MeshMessage, connection):
        """
        Handle CRL request from peer.

        Args:
            message: CRL request message
            connection: Connection that sent request
        """
        logger.debug(f"Received CRL request from {message.sender_id}")
        await self._send_crl(message.sender_id, connection)

    async def handle_crl_data(self, message: MeshMessage) -> bool:
        """
        Handle received CRL data.

        Args:
            message: CRL data message

        Returns:
            True if CRL was accepted, False otherwise
        """
        try:
            crl_data = message.payload.get("crl")
            if not crl_data:
                logger.error("Received CRL data without CRL")
                return False

            # Parse CRL
            crl = CertificateRevocationList(**crl_data)

            # Verify signature
            issuer_pubkey = self.get_public_key(crl.issuer)
            if not issuer_pubkey:
                logger.error(f"Unknown CRL issuer: {crl.issuer}")
                return False

            if not crl.signatures:
                logger.error("CRL has no signature")
                return False

            signature = crl.signatures[0]
            if not verify_model_signature(crl, signature, issuer_pubkey):
                logger.error("Invalid CRL signature")
                return False

            # Check if newer than current
            if self.current_crl and crl.sequence <= self.current_crl.sequence:
                logger.debug(f"Received CRL is not newer (seq {crl.sequence})")
                return False

            # Accept CRL
            self.current_crl = crl
            self._crl_cache[crl.sequence] = crl

            logger.info(
                f"Accepted new CRL (seq {crl.sequence}, "
                f"{len(crl.revoked_certificates)} revocations)"
            )

            # Propagate to other peers
            await self._announce_crl_sequence()

            return True

        except Exception as e:
            logger.error(f"Error processing CRL data: {e}")
            return False

    def is_certificate_revoked(self, cert_id: str) -> bool:
        """
        Check if a certificate is revoked.

        Args:
            cert_id: Certificate ID to check

        Returns:
            True if revoked, False otherwise
        """
        if not self.current_crl:
            return False

        return self.current_crl.is_cert_revoked(cert_id)

    def get_current_crl(self) -> Optional[CertificateRevocationList]:
        """Get current CRL."""
        return self.current_crl

    def set_crl(self, crl: CertificateRevocationList):
        """
        Set the CRL (typically from NA or bootstrap).

        Args:
            crl: CRL to set
        """
        self.current_crl = crl
        self._crl_cache[crl.sequence] = crl
        logger.info(f"Set CRL (seq {crl.sequence})")

    async def push_emergency_revocation(self, crl: CertificateRevocationList):
        """
        Emergency push of new CRL to all peers immediately.

        Args:
            crl: New CRL with revocations
        """
        self.current_crl = crl
        self._crl_cache[crl.sequence] = crl

        # Broadcast immediately
        message = MeshMessage(
            message_type=MessageType.REVOCATION,
            sender_id=self.node_id,
            payload={
                "action": "emergency_crl",
                "crl": crl.model_dump(mode='json')
            }
        )

        try:
            await self.broadcast_func(message)
            logger.warning(f"Emergency CRL push (seq {crl.sequence})")
        except Exception as e:
            logger.error(f"Failed to push emergency CRL: {e}")

    async def handle_emergency_crl(self, message: MeshMessage):
        """Handle emergency CRL push."""
        logger.warning("Received emergency CRL push")
        await self.handle_crl_data(message)

    async def _cache_cleanup_loop(self):
        """Periodically clean up old CRL cache entries."""
        try:
            while self._running:
                try:
                    await asyncio.sleep(3600)  # Cleanup every hour
                    await self._cleanup_crl_cache()

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in CRL cache cleanup: {e}")
                    await asyncio.sleep(3600)

        except asyncio.CancelledError:
            pass

    async def _cleanup_crl_cache(self):
        """Remove old CRL entries from cache."""
        if not self._crl_cache:
            return

        # Keep only the most recent entries
        if len(self._crl_cache) > self._max_cache_entries:
            # Sort by sequence number (descending) and keep newest
            sorted_sequences = sorted(self._crl_cache.keys(), reverse=True)
            sequences_to_keep = sorted_sequences[:self._max_cache_entries]

            # Remove old entries
            sequences_to_remove = [
                seq for seq in self._crl_cache.keys()
                if seq not in sequences_to_keep
            ]

            for seq in sequences_to_remove:
                del self._crl_cache[seq]

            logger.info(
                f"Pruned CRL cache: removed {len(sequences_to_remove)} old entries, "
                f"kept {len(sequences_to_keep)}"
            )

        # Also remove by age (keep current CRL regardless of age)
        current_sequence = self.current_crl.sequence if self.current_crl else None
        old_sequences = []

        for seq, crl in self._crl_cache.items():
            if seq != current_sequence:
                # Check age
                age = time.time() - crl.issued_at.timestamp()
                if age > self._cache_retention_age:
                    old_sequences.append(seq)

        for seq in old_sequences:
            del self._crl_cache[seq]

        if old_sequences:
            logger.debug(f"Removed {len(old_sequences)} aged CRL cache entries")

    def get_cache_stats(self) -> dict:
        """Get CRL cache statistics."""
        return {
            "cache_size": len(self._crl_cache),
            "max_cache_entries": self._max_cache_entries,
            "current_sequence": self.current_crl.sequence if self.current_crl else None,
            "cached_sequences": sorted(self._crl_cache.keys()),
        }
