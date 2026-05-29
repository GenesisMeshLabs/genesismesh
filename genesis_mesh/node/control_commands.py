"""Default command implementations for the node control plane."""

from __future__ import annotations

import asyncio
import logging
import time
from functools import partial
from typing import TYPE_CHECKING

from ..audit.logger import EventType
from ..models.control_plane import ControlCommand, ControlMessageModel

if TYPE_CHECKING:
    from .control_handler import ControlMessageHandler


logger = logging.getLogger(__name__)


def register_control_command_handlers(handler: "ControlMessageHandler") -> None:
    """Register the built-in control command handlers on a dispatcher."""
    handler.register_handler(
        ControlCommand.POLICY_UPDATE,
        partial(handle_policy_update, handler),
    )
    handler.register_handler(
        ControlCommand.REVOKE_CERTIFICATE,
        partial(handle_revoke_certificate, handler),
    )
    handler.register_handler(
        ControlCommand.REVOKE_NODE,
        partial(handle_revoke_node, handler),
    )
    handler.register_handler(
        ControlCommand.UPDATE_BOOTSTRAP,
        partial(handle_update_bootstrap, handler),
    )
    handler.register_handler(
        ControlCommand.SHUTDOWN_NODE,
        partial(handle_shutdown_node, handler),
    )


async def handle_policy_update(
    handler: "ControlMessageHandler",
    message: ControlMessageModel,
) -> str:
    """Apply a signed policy update command."""
    policy_data = message.data.get("policy", {})
    logger.info("Received policy update: %s", policy_data)

    if handler.on_policy_update:
        try:
            await handler.on_policy_update(policy_data)
        except Exception:
            logger.exception("Error applying policy update")
            if handler.audit_logger:
                handler.audit_logger.log_policy_updated(
                    policy_id=policy_data.get("policy_id", "unknown"),
                    issuer=message.issuer,
                )
            raise

    if handler.audit_logger:
        handler.audit_logger.log_policy_updated(
            policy_id=policy_data.get("policy_id", "unknown"),
            issuer=message.issuer,
        )

    logger.info("Policy update applied successfully: %s", policy_data.get("policy_id"))
    return "Policy update applied"


async def handle_revoke_certificate(
    handler: "ControlMessageHandler",
    message: ControlMessageModel,
) -> str:
    """Record a local certificate revocation and invoke callbacks."""
    cert_id = message.data.get("certificate_id")
    reason = message.data.get("reason", "No reason provided")
    if not isinstance(cert_id, str) or not cert_id:
        raise ValueError("certificate_id is required")
    logger.warning("Certificate %s revoked: %s", cert_id, reason)

    handler._revoked_certs[cert_id] = {
        "reason": reason,
        "revoked_at": time.time(),
        "revoked_by": message.issuer,
    }

    if handler.on_cert_revoked:
        try:
            await handler.on_cert_revoked(cert_id, reason)
        except Exception:
            logger.exception("Error in cert revocation callback")

    if handler.audit_logger:
        handler.audit_logger.log_certificate_revoked(
            cert_id=cert_id,
            reason=reason,
            issuer=message.issuer,
        )

    logger.info("Certificate %s added to local revocation cache", cert_id)
    return f"Certificate {cert_id} revoked"


async def handle_revoke_node(
    handler: "ControlMessageHandler",
    message: ControlMessageModel,
) -> str:
    """Record a local node revocation and invoke callbacks."""
    node_id = message.data.get("node_id")
    reason = message.data.get("reason", "No reason provided")
    if not isinstance(node_id, str) or not node_id:
        raise ValueError("node_id is required")
    logger.warning("Node %s revoked: %s", node_id, reason)

    handler._revoked_nodes[node_id] = {
        "reason": reason,
        "revoked_at": time.time(),
        "revoked_by": message.issuer,
    }

    if handler.on_node_revoked:
        try:
            await handler.on_node_revoked(node_id, reason)
        except Exception:
            logger.exception("Error in node revocation callback")

    if handler.audit_logger:
        handler.audit_logger.log_node_blacklisted(
            peer_id=node_id,
            reason=reason,
        )

    logger.info("Node %s blacklisted and disconnected", node_id)
    return f"Node {node_id} revoked"


async def handle_update_bootstrap(
    handler: "ControlMessageHandler",
    message: ControlMessageModel,
) -> str:
    """Apply an updated bootstrap anchor list."""
    anchors = message.data.get("anchors", [])
    logger.info("Updated bootstrap anchors: %s", anchors)

    handler._bootstrap_anchors = anchors

    if handler.on_bootstrap_update:
        try:
            await handler.on_bootstrap_update(anchors)
        except Exception:
            logger.exception("Error updating bootstrap anchors")
            raise

    if handler.audit_logger:
        handler.audit_logger.log_event(
            event_type=EventType.CONTROL_MESSAGE_ACCEPTED,
            action=f"Updated bootstrap anchors: {len(anchors)}",
            result="success",
            actor=message.issuer,
            details={"anchors": anchors},
        )

    logger.info("Bootstrap anchors updated: %s anchors", len(anchors))
    return f"Updated {len(anchors)} bootstrap anchors"


async def handle_shutdown_node(
    handler: "ControlMessageHandler",
    message: ControlMessageModel,
) -> str:
    """Schedule a graceful node shutdown."""
    reason = message.data.get("reason", "No reason provided")
    grace_period = message.data.get("grace_period", 30)
    logger.critical(
        "Received shutdown command: %s (grace period: %ss)",
        reason,
        grace_period,
    )

    if handler.audit_logger:
        handler.audit_logger.log_event(
            event_type=EventType.CONTROL_MESSAGE_ACCEPTED,
            action=f"Shutdown command received: {reason}",
            result="success",
            actor=message.issuer,
            details={"reason": reason, "grace_period": grace_period},
        )

    on_shutdown = handler.on_shutdown
    if on_shutdown:
        async def _do_shutdown() -> None:
            """Wait for the grace period, then invoke the shutdown callback."""
            await asyncio.sleep(grace_period)
            logger.critical(
                "Executing shutdown after %ss grace period",
                grace_period,
            )
            try:
                await on_shutdown(reason)
            except Exception:
                logger.exception("Error during shutdown")

        asyncio.create_task(_do_shutdown())

    return f"Shutdown scheduled in {grace_period}s: {reason}"
