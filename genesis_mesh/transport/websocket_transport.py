"""WebSocket transport implementation for mesh networking."""

import asyncio
import logging
from typing import Optional
import websockets
from websockets.server import WebSocketServerProtocol
from websockets.client import WebSocketClientProtocol


logger = logging.getLogger(__name__)


class WebSocketTransport:
    """
    WebSocket-based transport for peer-to-peer communication.

    Supports both client (outbound) and server (inbound) connections.
    """

    def __init__(self, websocket: WebSocketServerProtocol | WebSocketClientProtocol):
        """
        Initialize WebSocket transport.

        Args:
            websocket: WebSocket connection (client or server)
        """
        self.websocket = websocket
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
            data = await self.websocket.recv()
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
