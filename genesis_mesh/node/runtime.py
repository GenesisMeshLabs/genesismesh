"""Async peer-to-peer runtime for Genesis Mesh nodes."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import requests
import websockets

from ..audit.logger import AuditLogger
from ..crypto import verify_model_signature
from ..gossip.crl_gossip import CRLGossip
from ..models.certificates import JoinCertificate
from ..models.revocation import CertificateRevocationList
from ..monitoring.health import HealthChecker
from ..monitoring.metrics import MetricsCollector
from ..routing.protocol import RoutingProtocol
from ..routing.router import MeshRouter
from ..routing.table import RoutingTable
from ..transport.connection import Connection, ConnectionPool
from ..transport.protocol import MeshMessage, PeerInfo
from ..transport.websocket_transport import (
    accept_websocket_with_noise,
    connect_websocket_with_noise,
)
from .cert_manager import CertificateManager
from .control_handler import ControlMessageHandler
from .dispatcher import RuntimeMessageDispatcher
from .discovery import PeerDiscovery
from .peer_identity import RuntimePeerIdentity
from .peer_manager import PeerManager
from .rbac import RBACEnforcer


logger = logging.getLogger(__name__)


class _ExpectedWebSocketProbeFilter(logging.Filter):
    """Suppress noisy logs from browsers probing a peer WebSocket port."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Return False for expected non-WebSocket HTTP probes."""
        message = record.getMessage()
        if "connection rejected (426 Upgrade Required)" in message:
            return False
        if "opening handshake failed" not in message:
            return True
        exc_info = record.exc_info
        if not exc_info:
            return True
        exc_type = exc_info[0]
        if exc_type is None:
            return True
        return not issubclass(exc_type, websockets.exceptions.InvalidUpgrade)


def _peer_websocket_logger() -> logging.Logger:
    """Return the logger used by the peer WebSocket server."""
    ws_logger = logging.getLogger("genesis_mesh.peer_websocket")
    if not any(isinstance(f, _ExpectedWebSocketProbeFilter) for f in ws_logger.filters):
        ws_logger.addFilter(_ExpectedWebSocketProbeFilter())
    return ws_logger


class MeshNodeRuntime:
    """Owns the async P2P subsystems for a joined mesh node."""

    def __init__(
        self,
        node,
        na_endpoint: str,
        listen_host: str = "0.0.0.0",
        listen_port: int = 0,
    ):
        """Create a runtime around a joined `MeshNode`."""
        self.node = node
        self.na_endpoint = na_endpoint.rstrip("/")
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.node_id = node.node_keypair.public_key_b64

        self.connection_pool = ConnectionPool()
        self.peer_manager = PeerManager(self.node_id)
        self.routing_table = RoutingTable(self.node_id)
        self.router = MeshRouter(
            self.node_id,
            self.routing_table,
            self.connection_pool.get_connection,
        )
        self._peer_certs_by_id: dict[str, JoinCertificate] = {}
        self._peer_certs_by_node_id: dict[str, JoinCertificate] = {}
        self.routing_protocol = RoutingProtocol(
            self.node_id,
            self.routing_table,
            self.connection_pool.broadcast,
            is_revoked_sender=self._is_peer_revoked,
        )
        self.crl_gossip = CRLGossip(
            self.node_id,
            self._get_public_key,
            self.connection_pool.broadcast,
        )
        self.peer_identity = RuntimePeerIdentity(
            self.node,
            self.node_id,
            self.crl_gossip,
            self._peer_certs_by_id,
            self._peer_certs_by_node_id,
        )
        bootstrap_anchors = [
            anchor.endpoint for anchor in self.node.genesis_block.bootstrap_anchors
        ]
        self.peer_discovery = PeerDiscovery(
            self.node_id,
            self.peer_manager,
            bootstrap_anchors,
            on_peer_discovered=self._connect_discovered_peer,
            local_peer_info_factory=self._local_peer_info,
            sign_peer_info=self._sign_peer_info,
            verify_peer_info=self._verify_peer_info,
        )
        self.audit_logger = AuditLogger(self.node_id)
        self.metrics = MetricsCollector(
            self.node_id,
            self.node.genesis_block.network_name,
        )
        self.cert_manager = CertificateManager(
            node_id=self.node_id,
            get_certificate=lambda: self.node.join_certificate,
            renew_certificate=self._renew_certificate,
            on_certificate_renewed=self._on_certificate_renewed,
        )
        self.health_checker = HealthChecker(
            self.node_id,
            self._get_certificate_status,
            self.peer_manager.get_stats,
            self.routing_table.get_stats,
            self._get_crl_status,
        )
        self.control_handler = ControlMessageHandler(
            self.node_id,
            RBACEnforcer(),
            self._get_public_key,
            audit_logger=self.audit_logger,
        )
        self.dispatcher = RuntimeMessageDispatcher(self)

        self._server = None
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the runtime and all P2P subsystems."""
        if self._running:
            return
        if not self.node.join_certificate:
            raise ValueError("MeshNodeRuntime requires a join certificate")

        await self._bootstrap_crl()

        self._server = await websockets.serve(
            self._accept_peer,
            self.listen_host,
            self.listen_port,
            logger=_peer_websocket_logger(),
        )
        self._running = True

        await self.router.start()
        await self.routing_table.start()
        await self.routing_protocol.start()
        await self.peer_discovery.start()
        await self.crl_gossip.start()
        await self.cert_manager.start()
        self._monitor_task = asyncio.create_task(self._monitor_loop())

        await self._bootstrap_anchors()
        logger.info("Mesh node runtime started")

    async def stop(self):
        """Stop the runtime and close all peer connections."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        await self.cert_manager.stop()
        await self.crl_gossip.stop()
        await self.peer_discovery.stop()
        await self.routing_protocol.stop()
        await self.routing_table.stop()
        await self.router.stop()
        await self.connection_pool.close_all()

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        logger.info("Mesh node runtime stopped")

    @property
    def bound_port(self) -> Optional[int]:
        """Return the actual bound server port, useful when listen_port=0."""
        if not self._server or not self._server.sockets:
            return None
        return self._server.sockets[0].getsockname()[1]

    async def _accept_peer(self, websocket):
        """Accept, authenticate, and register one inbound peer connection."""
        try:
            static_keypair = self._noise_keypair()
            transport, remote_cert_b64, remote_static_pub = await accept_websocket_with_noise(
                websocket,
                static_keypair,
                self._local_cert_b64(),
            )
            cert = self._validate_peer_cert(remote_cert_b64, remote_static_pub)
            connection = await self._register_peer(cert, transport)
            if connection._receive_task:
                await connection._receive_task
        except Exception as exc:
            logger.warning("Rejected inbound peer connection: %s", exc)
            self.audit_logger.log_authentication_failure("unknown", str(exc))
            try:
                await websocket.close()
            except Exception:
                pass

    async def _bootstrap_anchors(self):
        """Connect to bootstrap anchors listed in the genesis block."""
        for anchor in self.node.genesis_block.bootstrap_anchors:
            if self._is_na_endpoint(anchor.endpoint):
                logger.info(
                    "Skipping bootstrap anchor %s because it matches the Network Authority endpoint",
                    anchor.endpoint,
                )
                continue
            try:
                await self._connect_endpoint(anchor.endpoint)
            except Exception as exc:
                message = str(exc)
                if "HTTP 404" in message:
                    logger.warning(
                        "Bootstrap anchor %s returned HTTP 404; endpoint is likely not a peer "
                        "WebSocket endpoint. Runtime will continue without this optional anchor.",
                        anchor.endpoint,
                    )
                elif "timed out" in message.lower():
                    logger.warning(
                        "Bootstrap anchor %s timed out during peer handshake. Runtime will "
                        "continue without this optional anchor.",
                        anchor.endpoint,
                    )
                else:
                    logger.warning(
                        "Failed to connect optional bootstrap anchor %s: %s. Runtime will continue.",
                        anchor.endpoint,
                        exc,
                    )

    async def _connect_discovered_peer(self, peer_info: PeerInfo):
        """Connect to a peer learned from discovery gossip."""
        await self._connect_endpoint(peer_info.endpoint)

    async def _connect_endpoint(self, endpoint: str):
        """Open an authenticated outbound connection to an endpoint."""
        uri = self._endpoint_to_uri(endpoint)
        transport, remote_cert_b64, remote_static_pub = await connect_websocket_with_noise(
            uri,
            self._noise_keypair(),
            self._local_cert_b64(),
        )
        cert = self._validate_peer_cert(remote_cert_b64, remote_static_pub)
        await self._register_peer(cert, transport, endpoint=endpoint)

    async def _register_peer(self, cert: JoinCertificate, transport, endpoint: str = "") -> Connection:
        """Register an authenticated peer with connection, peer, and routing state."""
        peer_id = cert.node_public_key
        connection = Connection(
            peer_id=peer_id,
            transport=transport,
            on_message=self.dispatcher.handle,
            on_close=self._on_connection_closed,
            local_node_id=self.node_id,
        )
        await self.connection_pool.add_connection(connection)
        peer_info = PeerInfo(
            node_id=peer_id,
            endpoint=endpoint,
            roles=cert.roles,
            cert_id=cert.cert_id,
            certificate_b64=self.peer_identity.certificate_b64(cert),
        )
        await self.peer_manager.add_peer(peer_info, connection=connection)
        self._peer_certs_by_id[cert.cert_id] = cert
        self._peer_certs_by_node_id[cert.node_public_key] = cert
        await self.routing_table.add_neighbor(peer_id, metric=1)
        await connection.start()
        connection.set_established()
        self.audit_logger.log_connection_established(peer_id, endpoint)
        return connection

    async def _on_connection_closed(self, connection: Connection):
        """Remove direct routing state when a peer connection closes."""
        await self.routing_table.remove_neighbor(connection.peer_id)

    async def _handle_inbound_message(self, message: MeshMessage, connection: Connection):
        """Compatibility wrapper for the runtime message dispatcher."""
        await self.dispatcher.handle(message, connection)

    async def _monitor_loop(self):
        """Periodically refresh health checks and metrics snapshots."""
        try:
            while self._running:
                await self._refresh_monitoring_snapshot()
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass

    async def _refresh_monitoring_snapshot(self):
        """Update in-memory monitoring state from runtime subsystems."""
        try:
            connection_stats = self.connection_pool.get_stats()
            self.metrics.update_connection_metrics(
                total=connection_stats["total_connections"],
                established=connection_stats["established"],
                failed=sum(
                    1
                    for conn in self.connection_pool.connections.values()
                    if conn.state.value == "failed"
                ),
            )

            peer_stats = self.peer_manager.get_stats()
            self.metrics.update_peer_metrics(
                total=peer_stats.get("total_peers", 0),
                connected=peer_stats.get("connected_peers", 0),
                anchors=peer_stats.get("anchor_peers", 0),
                blacklisted=peer_stats.get("blacklisted_peers", 0),
                avg_reputation=peer_stats.get("avg_reputation", 0.0),
            )

            routing_stats = self.routing_table.get_stats()
            self.metrics.update_routing_metrics(
                total_routes=routing_stats.get("total_routes", 0),
                direct_routes=routing_stats.get("direct_neighbors", 0),
                avg_metric=routing_stats.get("avg_metric", 0.0),
            )

            cert = self.node.join_certificate
            if cert:
                self.metrics.update_certificate_expiry(
                    max((cert.expires_at - datetime.now(timezone.utc)).total_seconds(), 0.0)
                )

            crl = self.crl_gossip.get_current_crl()
            if crl:
                self.metrics.update_crl_metrics(
                    crl.sequence,
                    len(crl.revoked_certificates),
                )

            await self.health_checker.run_all_checks(deep=True)
        except Exception as exc:
            logger.warning("Runtime monitoring snapshot failed: %s", exc)

    def _validate_peer_cert(
        self,
        remote_cert_b64: str,
        remote_static_pub: bytes,
    ) -> JoinCertificate:
        """Validate a peer certificate and bind it to the Noise static key."""
        return self.peer_identity.validate_peer_cert(remote_cert_b64, remote_static_pub)

    def _local_peer_info(self) -> PeerInfo:
        """Return the local peer announcement before signing."""
        host = self.listen_host
        if host in {"", "0.0.0.0", "::"}:
            host = "127.0.0.1"
        endpoint = f"{host}:{self.bound_port or self.listen_port}"
        return self.peer_identity.local_peer_info(endpoint)

    def _sign_peer_info(self, peer_info: PeerInfo) -> PeerInfo:
        """Sign a local peer announcement with the node identity key."""
        return self.peer_identity.sign_peer_info(peer_info)

    def _verify_peer_info(self, peer_info: PeerInfo) -> tuple[bool, list[str]]:
        """Verify a peer announcement and return roles from its certificate."""
        return self.peer_identity.verify_peer_info(peer_info)

    def _is_peer_revoked(self, node_id: str) -> bool:
        """Return whether a known peer node ID maps to a revoked certificate."""
        return self.peer_identity.is_peer_revoked(node_id)

    async def _bootstrap_crl(self):
        """Fetch and verify the current CRL from the Network Authority."""
        try:
            response = await asyncio.to_thread(
                requests.get,
                f"{self.na_endpoint}/crl",
                timeout=10,
            )
        except requests.RequestException:
            return

        if not response.ok:
            return

        crl = CertificateRevocationList.model_validate(response.json())
        issuer_key = self._get_public_key(crl.issuer)
        if not issuer_key or not crl.signatures:
            raise ValueError("CRL is missing issuer key or signature")
        if not verify_model_signature(crl, crl.signatures[0], issuer_key):
            raise ValueError("CRL signature verification failed")
        self.crl_gossip.set_crl(crl)

    def _local_cert_b64(self) -> str:
        """Return the local join certificate encoded for a Noise payload."""
        return self.peer_identity.local_cert_b64()

    def _noise_keypair(self):
        """Return the local Noise static keypair derived from the node key."""
        return self.peer_identity.noise_keypair()

    def _get_public_key(self, key_id: str) -> Optional[str]:
        """Resolve known key IDs to public keys for signature verification."""
        local_cert = self.node.join_certificate
        if local_cert and key_id == local_cert.issued_by:
            return self.node.genesis_block.network_authority.public_key
        if key_id == self.node.genesis_block.network_authority.public_key:
            return self.node.genesis_block.network_authority.public_key
        if key_id == "na-2025-q1":
            return self.node.genesis_block.network_authority.public_key
        if key_id == self.node_id:
            return self.node.node_keypair.public_key_b64
        return None

    def _is_na_endpoint(self, endpoint: str) -> bool:
        """Return whether a bootstrap endpoint points at the NA HTTP API."""
        parsed = urlparse(self.na_endpoint)
        if not parsed.hostname:
            return False
        na_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return endpoint == f"{parsed.hostname}:{na_port}"

    def _renew_certificate(self):
        """Renew the node certificate through the existing NA client."""
        if not self.node.renew_certificate(self.na_endpoint):
            raise ValueError("Certificate renewal failed")
        return self.node.join_certificate

    async def _on_certificate_renewed(self, cert: JoinCertificate):
        """Handle certificate renewal notifications from `CertificateManager`."""
        logger.info("Runtime observed renewed certificate %s", cert.cert_id)

    def _get_certificate_status(self) -> dict:
        """Return health-check friendly certificate status."""
        cert = self.node.join_certificate
        if not cert:
            return {"has_certificate": False, "error": "No certificate"}
        lifetime = max((cert.expires_at - cert.issued_at).total_seconds(), 1.0)
        remaining = max((cert.expires_at - datetime.now(timezone.utc)).total_seconds(), 0.0)
        return {
            "has_certificate": True,
            "certificate_id": cert.cert_id,
            "is_expired": not cert.is_valid(),
            "percent_remaining": min((remaining / lifetime) * 100.0, 100.0),
        }

    def _get_crl_status(self) -> dict:
        """Return health-check friendly CRL status."""
        crl = self.crl_gossip.get_current_crl()
        if not crl:
            return {"has_crl": False}
        return {
            "has_crl": True,
            "sequence": crl.sequence,
            "revoked_count": len(crl.revoked_certificates),
        }

    @staticmethod
    def _endpoint_to_uri(endpoint: str) -> str:
        """Convert a host:port endpoint into a WebSocket URI."""
        if endpoint.startswith(("ws://", "wss://")):
            return endpoint
        return f"ws://{endpoint}"
