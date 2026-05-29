"""Control-plane dispatcher and replay protection."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional

from ..models.control_plane import ControlMessageModel
from .control_commands import register_control_command_handlers
from .rbac import RBACEnforcer


logger = logging.getLogger(__name__)


class ControlMessageHandler:
    """Validate and dispatch signed control-plane messages for a node."""

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
        health_monitor: Optional[Any] = None,
    ):
        """Create a control message dispatcher.

        Args:
            node_id: Local node ID.
            rbac_enforcer: RBAC validator used for control messages.
            get_public_key: Lookup function for issuer public keys.
            on_policy_update: Optional callback for policy update commands.
            on_cert_revoked: Optional callback for certificate revocations.
            on_node_revoked: Optional callback for node revocations.
            on_bootstrap_update: Optional callback for bootstrap updates.
            on_shutdown: Optional callback for shutdown requests.
            audit_logger: Optional security audit logger.
            health_monitor: Optional node health monitor.
        """
        self.node_id = node_id
        self.rbac_enforcer = rbac_enforcer
        self.get_public_key = get_public_key

        self.on_policy_update = on_policy_update
        self.on_cert_revoked = on_cert_revoked
        self.on_node_revoked = on_node_revoked
        self.on_bootstrap_update = on_bootstrap_update
        self.on_shutdown = on_shutdown
        self.audit_logger = audit_logger
        self.health_monitor = health_monitor

        self._handlers: dict[str, Callable] = {}
        self._processed_messages: dict[str, float] = {}
        self._replay_lock = asyncio.Lock()

        self._revoked_certs: dict[str, dict[str, Any]] = {}
        self._revoked_nodes: dict[str, dict[str, Any]] = {}
        self._bootstrap_anchors: list[str] = []

        self._cleanup_task: Optional[asyncio.Task] = None
        self._replay_cache_file: Optional[str] = None
        self._running = False
        self._keypair: Any = None

        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """Register built-in control command implementations."""
        register_control_command_handlers(self)

    def register_handler(self, command: str, handler: Callable) -> None:
        """Register an async handler for a control command."""
        self._handlers[command] = handler
        logger.debug("Registered handler for command: %s", command)

    async def handle_control_message(
        self,
        message: ControlMessageModel,
    ) -> tuple[bool, Optional[str]]:
        """Validate, de-duplicate, and dispatch a control message."""
        if message.target and message.target != self.node_id:
            logger.debug("Control message not for us (target=%s)", message.target)
            return False, "Message not targeted at this node"

        async with self._replay_lock:
            if message.message_id in self._processed_messages:
                return False, "Control message already processed (replay attack?)"
            self._processed_messages[message.message_id] = time.time()

        public_key = self.get_public_key(message.issuer)
        if not public_key:
            return False, f"Unknown issuer: {message.issuer}"

        is_valid, error = self.rbac_enforcer.validate_control_message(
            message,
            public_key,
        )
        if not is_valid:
            logger.warning("Invalid control message: %s", error)
            return False, error

        handler = self._handlers.get(message.command)
        if not handler:
            return False, f"No handler for command: {message.command}"

        try:
            result = await handler(message)
            logger.info(
                "Executed control command %s from %s",
                message.command,
                message.issuer,
            )
            return True, result
        except Exception as exc:
            logger.exception("Error executing control command")
            return False, str(exc)

    async def start(self, replay_cache_file: Optional[str] = None) -> None:
        """Start replay-cache persistence and cleanup."""
        if self._running:
            return

        self._running = True
        self._replay_cache_file = replay_cache_file

        if replay_cache_file:
            await self._load_replay_cache()

        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Control handler started with replay protection")

    async def stop(self) -> None:
        """Stop replay-cache cleanup and persist current state."""
        self._running = False

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        if self._replay_cache_file:
            await self._save_replay_cache()

        logger.info("Control handler stopped")

    async def _cleanup_loop(self) -> None:
        """Periodically remove stale replay-cache entries."""
        try:
            while self._running:
                try:
                    await asyncio.sleep(300)
                    await self.cleanup_processed_messages(max_age=3600.0)

                    if len(self._processed_messages) > 10000:
                        await self._trim_replay_cache(max_entries=5000)
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.exception("Error in cleanup loop")
                    await asyncio.sleep(300)
        except asyncio.CancelledError:
            pass

    async def cleanup_processed_messages(self, max_age: float = 3600.0) -> None:
        """Remove processed message IDs older than `max_age` seconds."""
        async with self._replay_lock:
            now = time.time()
            stale_ids = [
                msg_id
                for msg_id, timestamp in self._processed_messages.items()
                if (now - timestamp) > max_age
            ]

            for msg_id in stale_ids:
                del self._processed_messages[msg_id]

            if stale_ids:
                logger.debug("Cleaned up %s processed message IDs", len(stale_ids))

    async def _trim_replay_cache(self, max_entries: int) -> None:
        """Keep only the newest `max_entries` replay-cache entries."""
        async with self._replay_lock:
            if len(self._processed_messages) <= max_entries:
                return

            sorted_items = sorted(
                self._processed_messages.items(),
                key=lambda item: item[1],
                reverse=True,
            )
            self._processed_messages = dict(sorted_items[:max_entries])
            logger.info("Trimmed replay cache to %s entries", max_entries)

    async def _load_replay_cache(self) -> None:
        """Load a persisted replay cache from disk."""
        try:
            cache_file = Path(self._replay_cache_file or "")
            if not cache_file.exists():
                return

            with cache_file.open("r", encoding="utf-8") as f:
                data = json.load(f)

            raw = data.get("processed_messages", {})
            if not isinstance(raw, dict):
                logger.warning("Replay cache has invalid format, ignoring")
                return

            validated: dict[str, float] = {}
            for msg_id, timestamp in raw.items():
                if isinstance(msg_id, str) and isinstance(timestamp, (int, float)):
                    validated[msg_id] = float(timestamp)
                else:
                    logger.warning("Skipping invalid replay cache entry: %r", msg_id)

            async with self._replay_lock:
                self._processed_messages = validated
            logger.info("Loaded %s replay cache entries", len(validated))
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.error("Corrupt replay cache file, starting fresh: %s", exc)
        except Exception:
            logger.exception("Error loading replay cache")

    async def _save_replay_cache(self) -> None:
        """Persist the replay cache to disk."""
        try:
            cache_file = Path(self._replay_cache_file or "")
            cache_file.parent.mkdir(parents=True, exist_ok=True)

            async with self._replay_lock:
                snapshot = dict(self._processed_messages)

            with cache_file.open("w", encoding="utf-8") as f:
                json.dump({"processed_messages": snapshot}, f, indent=2)

            logger.info("Saved %s replay cache entries", len(snapshot))
        except Exception:
            logger.exception("Error saving replay cache")

    def is_certificate_revoked(self, cert_id: str) -> bool:
        """Return whether a certificate ID is in the local revocation cache."""
        return cert_id in self._revoked_certs

    def is_node_revoked(self, node_id: str) -> bool:
        """Return whether a node ID is in the local revocation cache."""
        return node_id in self._revoked_nodes

    def get_bootstrap_anchors(self) -> list[str]:
        """Return the current bootstrap anchor list."""
        return self._bootstrap_anchors.copy()
