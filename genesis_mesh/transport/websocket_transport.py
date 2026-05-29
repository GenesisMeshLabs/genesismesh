"""WebSocket transport implementation for mesh networking."""

import asyncio
import logging
from typing import Any, Optional
import websockets

from .noise_handshake import NoiseHandshake, NoiseSession


logger = logging.getLogger(__name__)


class WebSocketTransport:
    """
    WebSocket-based transport for peer-to-peer communication.

    Supports both client (outbound) and server (inbound) connections.
    """

    def __init__(
        self,
        websocket: Any,
        noise_session: Optional[NoiseSession] = None,
    ):
        """
        Initialize WebSocket transport.

        Args:
            websocket: WebSocket connection (client or server)
            noise_session: Optional post-handshake Noise encrypted session
        """
        self.websocket = websocket
        self.noise_session = noise_session
        self._closed = False

    async def send(self, data: bytes):
        """
        Send data over WebSocket.

        Args:
            data: Bytes to send
        """
        if self._closed:
            raise ConnectionError("Transport is closed")

        try:
            if self.noise_session:
                await self.noise_session.send(data)
            else:
                await self.websocket.send(data)
        except websockets.exceptions.ConnectionClosed:
            self._closed = True
            raise ConnectionError("WebSocket connection closed")

    async def receive(self) -> Optional[bytes]:
        """
        Receive data from WebSocket.

        Returns:
            Received bytes, or None if connection closed
        """
        if self._closed:
            return None

        try:
            if self.noise_session:
                data = await self.noise_session.receive()
            else:
                data = await self.websocket.recv()

            if data is None:
                return None
            if isinstance(data, str):
                return data.encode('utf-8')
            return data
        except websockets.exceptions.ConnectionClosed:
            self._closed = True
            return None

    async def close(self):
        """Close the WebSocket connection."""
        if not self._closed:
            self._closed = True
            try:
                if self.noise_session:
                    await self.noise_session.close()
                else:
                    await self.websocket.close()
            except Exception as e:
                logger.error(f"Error closing WebSocket: {e}")

    @property
    def is_closed(self) -> bool:
        """Check if transport is closed."""
        return self._closed


async def connect_websocket(uri: str, timeout: float = 10.0) -> WebSocketTransport:
    """
    Connect to a WebSocket server.

    Args:
        uri: WebSocket URI (ws://host:port or wss://host:port)
        timeout: Connection timeout in seconds

    Returns:
        WebSocketTransport instance

    Raises:
        ConnectionError: If connection fails
    """
    try:
        websocket = await asyncio.wait_for(
            websockets.connect(uri),
            timeout=timeout
        )
        return WebSocketTransport(websocket)
    except asyncio.TimeoutError:
        raise ConnectionError(f"Connection to {uri} timed out")
    except Exception as e:
        raise ConnectionError(f"Failed to connect to {uri}: {e}")


async def connect_websocket_with_noise(
    uri: str,
    static_keypair,
    local_cert_b64: str,
    timeout: float = 10.0,
) -> tuple[WebSocketTransport, str, bytes]:
    """
    Connect to a WebSocket peer and establish a Noise XX encrypted session.

    Returns:
        (transport, remote_cert_b64, remote_static_pub)
    """
    try:
        websocket = await asyncio.wait_for(
            websockets.connect(uri),
            timeout=timeout
        )
        session, remote_cert_b64, remote_static_pub = await NoiseHandshake().perform_initiator(
            websocket,
            static_keypair,
            local_cert_b64,
        )
        return WebSocketTransport(websocket, noise_session=session), remote_cert_b64, remote_static_pub
    except asyncio.TimeoutError:
        raise ConnectionError(f"Connection to {uri} timed out")
    except Exception as e:
        raise ConnectionError(f"Failed to connect to {uri} with Noise: {e}")


async def accept_websocket_with_noise(
    websocket: Any,
    static_keypair,
    local_cert_b64: str,
) -> tuple[WebSocketTransport, str, bytes]:
    """
    Accept an inbound WebSocket and establish a Noise XX encrypted session.

    Returns:
        (transport, remote_cert_b64, remote_static_pub)
    """
    session, remote_cert_b64, remote_static_pub = await NoiseHandshake().perform_responder(
        websocket,
        static_keypair,
        local_cert_b64,
    )
    return WebSocketTransport(websocket, noise_session=session), remote_cert_b64, remote_static_pub
