"""Inbound mesh message dispatch for node runtimes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models.control_plane import ControlMessageModel
from ..transport.connection import Connection
from ..transport.protocol import MeshMessage, MessageType

if TYPE_CHECKING:
    from .runtime import MeshNodeRuntime


class RuntimeMessageDispatcher:
    """Route inbound mesh messages to the runtime subsystem that owns them."""

    def __init__(self, runtime: "MeshNodeRuntime"):
        """Bind the dispatcher to a runtime and its subsystems."""
        self.runtime = runtime

    async def handle(self, message: MeshMessage, connection: Connection) -> None:
        """Dispatch an inbound mesh message to the matching subsystem."""
        if message.message_type == MessageType.PEER_REQUEST:
            await self.runtime.peer_discovery.handle_peer_request(message, connection)
        elif message.message_type == MessageType.PEER_RESPONSE:
            await self.runtime.peer_discovery.handle_peer_response(message)
        elif message.message_type == MessageType.PEER_ANNOUNCE:
            await self.runtime.peer_discovery.handle_peer_announce(message)
        elif message.message_type == MessageType.ROUTE_ANNOUNCE:
            await self.runtime.routing_protocol.handle_route_announce(message)
        elif message.message_type == MessageType.ROUTE_UPDATE:
            await self.runtime.routing_protocol.handle_route_update(message)
        elif message.message_type == MessageType.ROUTE_WITHDRAW:
            await self.runtime.routing_protocol.handle_route_withdraw(message)
        elif message.message_type == MessageType.DATA:
            await self.runtime.router.route_message(message)
        elif message.message_type == MessageType.CONTROL_MESSAGE:
            await self._handle_control_message(message)
        elif message.message_type == MessageType.REVOCATION:
            await self._handle_revocation_message(message, connection)

    async def _handle_control_message(self, message: MeshMessage) -> None:
        """Validate revocation state, then dispatch a control message."""
        control_message = ControlMessageModel(**message.payload)
        if (
            self.runtime._is_peer_revoked(message.sender_id)
            or self.runtime._is_peer_revoked(control_message.issuer)
        ):
            self.runtime.metrics.record_control_message(accepted=False)
            self.runtime.audit_logger.log_authorization_denied(
                control_message.issuer,
                control_message.command,
                "revoked identity",
            )
            return

        self.runtime.metrics.record_control_message(accepted=True)
        await self.runtime.control_handler.handle_control_message(control_message)

    async def _handle_revocation_message(
        self,
        message: MeshMessage,
        connection: Connection,
    ) -> None:
        """Dispatch CRL gossip messages by their revocation action."""
        action = message.payload.get("action")
        if action == "announce_sequence":
            await self.runtime.crl_gossip.handle_crl_announce(message, connection)
        elif action == "request_crl":
            await self.runtime.crl_gossip.handle_crl_request(message, connection)
        elif action == "crl_data":
            await self.runtime.crl_gossip.handle_crl_data(message)
        elif action == "emergency_crl":
            await self.runtime.crl_gossip.handle_emergency_crl(message)
