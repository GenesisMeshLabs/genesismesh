"""Control-plane message handler."""

import asyncio
import logging
from typing import Dict, Callable, Optional, Any, List

from ..models.control_plane import ControlMessageModel, ControlCommand
from .rbac import RBACEnforcer


logger = logging.getLogger(__name__)


class ControlMessageHandler:
    """
    Handles incoming control-plane messages.

    Validates authorization and executes commands.
    """

    def __init__(
        self,
        node_id: str,
        rbac_enforcer: RBACEnforcer,
        get_public_key: Callable[[str], Optional[str]],
        on_policy_update: Optional[Callable] = None,
        on_cert_revoked: Optional[Callable] = None,
        on_node_revoked: Optional[Callable] = None,
        on_bootstrap_update: Optional[Callable] = None,
        on_shutdown: Optional[Callable] = None,
        audit_logger: Optional[Any] = None,
        health_monitor: Optional[Any] = None
    ):
        """
        Initialize control message handler.

        Args:
            node_id: Local node ID
            rbac_enforcer: RBAC enforcer instance
            get_public_key: Function to get public key by key ID
            on_policy_update: Callback for policy updates
            on_cert_revoked: Callback for certificate revocations
            on_node_revoked: Callback for node revocations
            on_bootstrap_update: Callback for bootstrap updates
            on_shutdown: Callback for shutdown requests
            audit_logger: Audit logger instance
            health_monitor: Health monitor instance
        """
        self.node_id = node_id
        self.rbac_enforcer = rbac_enforcer
        self.get_public_key = get_public_key

        # Callbacks for control actions
        self.on_policy_update = on_policy_update
        self.on_cert_revoked = on_cert_revoked
        self.on_node_revoked = on_node_revoked
        self.on_bootstrap_update = on_bootstrap_update
        self.on_shutdown = on_shutdown
        self.audit_logger = audit_logger
        self.health_monitor = health_monitor

        # Command handlers
        self._handlers: Dict[str, Callable] = {}
        self._register_default_handlers()

        # Processed message IDs (prevent replay)
        self._processed_messages: Dict[str, float] = {}

        # Local revocation cache
        self._revoked_certs: Dict[str, Dict[str, Any]] = {}
        self._revoked_nodes: Dict[str, Dict[str, Any]] = {}

        # Bootstrap anchor list
        self._bootstrap_anchors: List[str] = []

        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    def _register_default_handlers(self):
        """Register default command handlers."""
        self.register_handler(ControlCommand.POLICY_UPDATE, self._handle_policy_update)
        self.register_handler(ControlCommand.REVOKE_CERTIFICATE, self._handle_revoke_certificate)
        self.register_handler(ControlCommand.REVOKE_NODE, self._handle_revoke_node)
        self.register_handler(ControlCommand.UPDATE_BOOTSTRAP, self._handle_update_bootstrap)
        self.register_handler(ControlCommand.SHUTDOWN_NODE, self._handle_shutdown_node)

    def register_handler(self, command: str, handler: Callable):
        """
        Register a command handler.

        Args:
            command: Command name
            handler: Handler function (async)
        """
        self._handlers[command] = handler
        logger.debug(f"Registered handler for command: {command}")

    async def handle_control_message(
        self,
        message: ControlMessageModel
    ) -> tuple[bool, Optional[str]]:
        """
        Handle a control message.

        Args:
            message: Control message to handle

        Returns:
            Tuple of (success, error_message)
        """
        # Check for replay attacks
        import time
        if message.message_id in self._processed_messages:
            return False, "Control message already processed (replay attack?)"

        # Get issuer public key
        public_key = self.get_public_key(message.issuer)
        if not public_key:
            return False, f"Unknown issuer: {message.issuer}"

        # Validate message
        is_valid, error = self.rbac_enforcer.validate_control_message(
            message,
            public_key
        )

        if not is_valid:
            logger.warning(f"Invalid control message: {error}")
            return False, error

        # Mark as processed
        self._processed_messages[message.message_id] = time.time()

        # Check if message is targeted at us
        if message.target and message.target != self.node_id:
            logger.debug(f"Control message not for us (target={message.target})")
            return False, "Message not targeted at this node"

        # Get handler
        handler = self._handlers.get(message.command)
        if not handler:
            return False, f"No handler for command: {message.command}"

        # Execute handler
        try:
            result = await handler(message)
            logger.info(
                f"Executed control command {message.command} from {message.issuer}"
            )
            return True, result
        except Exception as e:
            logger.error(f"Error executing control command: {e}")
            return False, str(e)

    async def _handle_policy_update(self, message: ControlMessageModel) -> str:
        """Handle policy update command."""
        policy_data = message.data.get("policy", {})
        logger.info(f"Received policy update: {policy_data}")

        # Apply policy update via callback
        if self.on_policy_update:
            try:
                await self.on_policy_update(policy_data)
            except Exception as e:
                logger.error(f"Error applying policy update: {e}")
                if self.audit_logger:
                    self.audit_logger.log_policy_updated(
                        policy_id=policy_data.get("policy_id", "unknown"),
                        issuer=message.issuer
                    )
                raise

        # Update health status to degraded during policy application
        if self.health_monitor:
            # Policy updates might temporarily affect operations
            pass

        # Log to audit
        if self.audit_logger:
            self.audit_logger.log_policy_updated(
                policy_id=policy_data.get("policy_id", "unknown"),
                issuer=message.issuer
            )

        logger.info(f"Policy update applied successfully: {policy_data.get('policy_id')}")
        return "Policy update applied"

    async def _handle_revoke_certificate(self, message: ControlMessageModel) -> str:
        """Handle certificate revocation."""
        cert_id = message.data.get("certificate_id")
        reason = message.data.get("reason", "No reason provided")
        logger.warning(f"Certificate {cert_id} revoked: {reason}")

        # Add to local revocation cache
        import time
        self._revoked_certs[cert_id] = {
            "reason": reason,
            "revoked_at": time.time(),
            "revoked_by": message.issuer
        }

        # Call revocation callback
        if self.on_cert_revoked:
            try:
                await self.on_cert_revoked(cert_id, reason)
            except Exception as e:
                logger.error(f"Error in cert revocation callback: {e}")

        # Log to audit
        if self.audit_logger:
            self.audit_logger.log_certificate_revoked(
                cert_id=cert_id,
                reason=reason,
                issuer=message.issuer
            )

        logger.info(f"Certificate {cert_id} added to local revocation cache")
        return f"Certificate {cert_id} revoked"

    async def _handle_revoke_node(self, message: ControlMessageModel) -> str:
        """Handle node revocation."""
        node_id = message.data.get("node_id")
        reason = message.data.get("reason", "No reason provided")
        logger.warning(f"Node {node_id} revoked: {reason}")

        # Add to local node blacklist
        import time
        self._revoked_nodes[node_id] = {
            "reason": reason,
            "revoked_at": time.time(),
            "revoked_by": message.issuer
        }

        # Disconnect and blacklist via callback
        if self.on_node_revoked:
            try:
                await self.on_node_revoked(node_id, reason)
            except Exception as e:
                logger.error(f"Error in node revocation callback: {e}")

        # Log to audit
        if self.audit_logger:
            self.audit_logger.log_node_blacklisted(
                peer_id=node_id,
                reason=reason
            )

        logger.info(f"Node {node_id} blacklisted and disconnected")
        return f"Node {node_id} revoked"

    async def _handle_update_bootstrap(self, message: ControlMessageModel) -> str:
        """Handle bootstrap anchor update."""
        anchors = message.data.get("anchors", [])
        logger.info(f"Updated bootstrap anchors: {anchors}")

        # Update local bootstrap list
        self._bootstrap_anchors = anchors

        # Apply bootstrap update via callback
        if self.on_bootstrap_update:
            try:
                await self.on_bootstrap_update(anchors)
            except Exception as e:
                logger.error(f"Error updating bootstrap anchors: {e}")
                raise

        # Log to audit
        if self.audit_logger:
            from ..audit.logger import EventType
            self.audit_logger.log_event(
                event_type=EventType.CONTROL_MESSAGE_ACCEPTED,
                action=f"Updated bootstrap anchors: {len(anchors)}",
                result="success",
                actor=message.issuer,
                details={"anchors": anchors}
            )

        logger.info(f"Bootstrap anchors updated: {len(anchors)} anchors")
        return f"Updated {len(anchors)} bootstrap anchors"

    async def _handle_shutdown_node(self, message: ControlMessageModel) -> str:
        """Handle node shutdown command."""
        reason = message.data.get("reason", "No reason provided")
        grace_period = message.data.get("grace_period", 30)
        logger.critical(f"Received shutdown command: {reason} (grace period: {grace_period}s)")

        # Log to audit before shutdown
        if self.audit_logger:
            from ..audit.logger import EventType
            self.audit_logger.log_event(
                event_type=EventType.CONTROL_MESSAGE_ACCEPTED,
                action=f"Shutdown command received: {reason}",
                result="success",
                actor=message.issuer,
                details={"reason": reason, "grace_period": grace_period}
            )

        # Update health status to unhealthy
        if self.health_monitor:
            # Mark as shutting down
            pass

        # Perform graceful shutdown via callback
        if self.on_shutdown:
            # Schedule shutdown after grace period
            async def _do_shutdown():
                await asyncio.sleep(grace_period)
                logger.critical(f"Executing shutdown after {grace_period}s grace period")
                try:
                    await self.on_shutdown(reason)
                except Exception as e:
                    logger.error(f"Error during shutdown: {e}")

            asyncio.create_task(_do_shutdown())

        return f"Shutdown scheduled in {grace_period}s: {reason}"

    async def start(self, replay_cache_file: Optional[str] = None):
        """
        Start control handler and replay protection cleanup.

        Args:
            replay_cache_file: Path to persist replay cache (optional)
        """
        if self._running:
            return

        self._running = True
        self._replay_cache_file = replay_cache_file

        # Load persisted replay cache if available
        if replay_cache_file:
            await self._load_replay_cache()

        # Start periodic cleanup
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Control handler started with replay protection")

    async def stop(self):
        """Stop control handler and cleanup tasks."""
        self._running = False

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Persist replay cache
        if hasattr(self, '_replay_cache_file') and self._replay_cache_file:
            await self._save_replay_cache()

        logger.info("Control handler stopped")

    async def _cleanup_loop(self):
        """Periodically clean up old replay cache entries."""
        try:
            while self._running:
                try:
                    await asyncio.sleep(300)  # Cleanup every 5 minutes
                    await self.cleanup_processed_messages(max_age=3600.0)

                    # Cap cache size if it grows too large
                    if len(self._processed_messages) > 10000:
                        await self._trim_replay_cache(max_entries=5000)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in cleanup loop: {e}")
                    await asyncio.sleep(300)

        except asyncio.CancelledError:
            pass

    async def cleanup_processed_messages(self, max_age: float = 3600.0):
        """
        Clean up old processed message IDs.

        Args:
            max_age: Maximum age in seconds
        """
        import time
        now = time.time()
        stale_ids = [
            msg_id for msg_id, timestamp in self._processed_messages.items()
            if (now - timestamp) > max_age
        ]

        for msg_id in stale_ids:
            del self._processed_messages[msg_id]

        if stale_ids:
            logger.debug(f"Cleaned up {len(stale_ids)} processed message IDs")

    async def _trim_replay_cache(self, max_entries: int):
        """
        Trim replay cache to max entries by removing oldest.

        Args:
            max_entries: Maximum number of entries to keep
        """
        if len(self._processed_messages) <= max_entries:
            return

        # Sort by timestamp and keep newest
        sorted_items = sorted(
            self._processed_messages.items(),
            key=lambda x: x[1],
            reverse=True
        )

        self._processed_messages = dict(sorted_items[:max_entries])
        logger.info(f"Trimmed replay cache to {max_entries} entries")

    async def _load_replay_cache(self):
        """Load replay cache from disk."""
        try:
            import json
            from pathlib import Path

            cache_file = Path(self._replay_cache_file)
            if cache_file.exists():
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                    self._processed_messages = data.get("processed_messages", {})
                    logger.info(f"Loaded {len(self._processed_messages)} replay cache entries")
        except Exception as e:
            logger.error(f"Error loading replay cache: {e}")

    async def _save_replay_cache(self):
        """Save replay cache to disk."""
        try:
            import json
            from pathlib import Path

            cache_file = Path(self._replay_cache_file)
            cache_file.parent.mkdir(parents=True, exist_ok=True)

            with open(cache_file, 'w') as f:
                json.dump({
                    "processed_messages": self._processed_messages
                }, f, indent=2)

            logger.info(f"Saved {len(self._processed_messages)} replay cache entries")
        except Exception as e:
            logger.error(f"Error saving replay cache: {e}")

    def is_certificate_revoked(self, cert_id: str) -> bool:
        """
        Check if a certificate is revoked.

        Args:
            cert_id: Certificate ID to check

        Returns:
            True if revoked, False otherwise
        """
        return cert_id in self._revoked_certs

    def is_node_revoked(self, node_id: str) -> bool:
        """
        Check if a node is revoked.

        Args:
            node_id: Node ID to check

        Returns:
            True if revoked, False otherwise
        """
        return node_id in self._revoked_nodes

    def get_bootstrap_anchors(self) -> List[str]:
        """
        Get current bootstrap anchor list.

        Returns:
            List of bootstrap anchor addresses
        """
        return self._bootstrap_anchors.copy()
