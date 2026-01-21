"""Metrics collection for Prometheus."""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from collections import defaultdict


@dataclass
class MeshMetrics:
    """Container for mesh network metrics."""
    # Connection metrics
    total_connections: int = 0
    established_connections: int = 0
    failed_connections: int = 0

    # Message metrics
    messages_sent: int = 0
    messages_received: int = 0
    messages_forwarded: int = 0
    messages_dropped: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0

    # Routing metrics
    total_routes: int = 0
    direct_routes: int = 0
    avg_route_metric: float = 0.0
    routing_table_size: int = 0

    # Peer metrics
    total_peers: int = 0
    connected_peers: int = 0
    anchor_peers: int = 0
    blacklisted_peers: int = 0
    avg_peer_reputation: float = 1.0
    avg_peer_latency_ms: float = 0.0

    # Certificate metrics
    certificate_renewals: int = 0
    certificate_renewal_failures: int = 0
    certificate_expiry_seconds: float = 0.0

    # CRL metrics
    crl_sequence: int = 0
    revoked_certificates: int = 0
    crl_updates: int = 0

    # Control plane metrics
    control_messages_received: int = 0
    control_messages_accepted: int = 0
    control_messages_rejected: int = 0

    # Performance metrics
    uptime_seconds: float = 0.0
    last_update: float = field(default_factory=time.time)

    # Rate metrics (per second)
    messages_per_second: float = 0.0
    bytes_per_second: float = 0.0


class MetricsCollector:
    """
    Collects and exposes metrics for Prometheus.

    Tracks all mesh networking metrics and provides
    Prometheus-formatted output.
    """

    def __init__(self, node_id: str, network_name: str):
        """
        Initialize metrics collector.

        Args:
            node_id: Local node ID
            node_name: Network name
        """
        self.node_id = node_id
        self.network_name = network_name

        self.metrics = MeshMetrics()
        self.start_time = time.time()

        # Rate tracking
        self._last_messages_sent = 0
        self._last_bytes_sent = 0
        self._last_rate_update = time.time()

        # Histograms (simple bucketing)
        self.latency_buckets: Dict[str, List[float]] = defaultdict(list)
        self.message_size_buckets: Dict[str, List[int]] = defaultdict(list)

    def update_connection_metrics(
        self,
        total: int,
        established: int,
        failed: int
    ):
        """Update connection metrics."""
        self.metrics.total_connections = total
        self.metrics.established_connections = established
        self.metrics.failed_connections = failed
        self.metrics.last_update = time.time()

    def record_message_sent(self, size_bytes: int):
        """Record a sent message."""
        self.metrics.messages_sent += 1
        self.metrics.bytes_sent += size_bytes
        self.message_size_buckets["sent"].append(size_bytes)
        self._update_rates()

    def record_message_received(self, size_bytes: int):
        """Record a received message."""
        self.metrics.messages_received += 1
        self.metrics.bytes_received += size_bytes
        self.message_size_buckets["received"].append(size_bytes)
        self._update_rates()

    def record_message_forwarded(self):
        """Record a forwarded message."""
        self.metrics.messages_forwarded += 1

    def record_message_dropped(self):
        """Record a dropped message."""
        self.metrics.messages_dropped += 1

    def update_routing_metrics(
        self,
        total_routes: int,
        direct_routes: int,
        avg_metric: float
    ):
        """Update routing metrics."""
        self.metrics.total_routes = total_routes
        self.metrics.direct_routes = direct_routes
        self.metrics.avg_route_metric = avg_metric
        self.metrics.routing_table_size = total_routes
        self.metrics.last_update = time.time()

    def update_peer_metrics(
        self,
        total: int,
        connected: int,
        anchors: int,
        blacklisted: int,
        avg_reputation: float,
        avg_latency_ms: Optional[float] = None
    ):
        """Update peer metrics."""
        self.metrics.total_peers = total
        self.metrics.connected_peers = connected
        self.metrics.anchor_peers = anchors
        self.metrics.blacklisted_peers = blacklisted
        self.metrics.avg_peer_reputation = avg_reputation
        if avg_latency_ms is not None:
            self.metrics.avg_peer_latency_ms = avg_latency_ms
        self.metrics.last_update = time.time()

    def record_certificate_renewal(self, success: bool):
        """Record a certificate renewal attempt."""
        if success:
            self.metrics.certificate_renewals += 1
        else:
            self.metrics.certificate_renewal_failures += 1

    def update_certificate_expiry(self, seconds_remaining: float):
        """Update certificate expiry time."""
        self.metrics.certificate_expiry_seconds = seconds_remaining

    def update_crl_metrics(self, sequence: int, revoked_count: int):
        """Update CRL metrics."""
        if sequence > self.metrics.crl_sequence:
            self.metrics.crl_updates += 1
        self.metrics.crl_sequence = sequence
        self.metrics.revoked_certificates = revoked_count
        self.metrics.last_update = time.time()

    def record_control_message(self, accepted: bool):
        """Record a control-plane message."""
        self.metrics.control_messages_received += 1
        if accepted:
            self.metrics.control_messages_accepted += 1
        else:
            self.metrics.control_messages_rejected += 1

    def record_latency(self, peer_id: str, latency_ms: float):
        """Record peer latency measurement."""
        self.latency_buckets[peer_id].append(latency_ms)
        # Keep only last 100 measurements per peer
        if len(self.latency_buckets[peer_id]) > 100:
            self.latency_buckets[peer_id] = self.latency_buckets[peer_id][-100:]

    def _update_rates(self):
        """Update rate metrics."""
        now = time.time()
        elapsed = now - self._last_rate_update

        if elapsed >= 1.0:  # Update every second
            msg_diff = self.metrics.messages_sent - self._last_messages_sent
            bytes_diff = self.metrics.bytes_sent - self._last_bytes_sent

            self.metrics.messages_per_second = msg_diff / elapsed
            self.metrics.bytes_per_second = bytes_diff / elapsed

            self._last_messages_sent = self.metrics.messages_sent
            self._last_bytes_sent = self.metrics.bytes_sent
            self._last_rate_update = now

    def get_uptime(self) -> float:
        """Get uptime in seconds."""
        return time.time() - self.start_time

    def get_metrics(self) -> MeshMetrics:
        """Get current metrics snapshot."""
        self.metrics.uptime_seconds = self.get_uptime()
        return self.metrics

    def to_prometheus(self) -> str:
        """
        Export metrics in Prometheus format.

        Returns:
            Prometheus-formatted metrics string
        """
        lines = []
        labels = f'{{node_id="{self.node_id}",network="{self.network_name}"}}'

        # Update uptime
        self.metrics.uptime_seconds = self.get_uptime()

        # Connection metrics
        lines.append(f"# HELP mesh_connections_total Total number of peer connections")
        lines.append(f"# TYPE mesh_connections_total gauge")
        lines.append(f"mesh_connections_total{labels} {self.metrics.total_connections}")

        lines.append(f"mesh_connections_established{labels} {self.metrics.established_connections}")
        lines.append(f"mesh_connections_failed{labels} {self.metrics.failed_connections}")

        # Message metrics
        lines.append(f"# HELP mesh_messages_sent_total Total messages sent")
        lines.append(f"# TYPE mesh_messages_sent_total counter")
        lines.append(f"mesh_messages_sent_total{labels} {self.metrics.messages_sent}")

        lines.append(f"mesh_messages_received_total{labels} {self.metrics.messages_received}")
        lines.append(f"mesh_messages_forwarded_total{labels} {self.metrics.messages_forwarded}")
        lines.append(f"mesh_messages_dropped_total{labels} {self.metrics.messages_dropped}")

        lines.append(f"# HELP mesh_bytes_sent_total Total bytes sent")
        lines.append(f"# TYPE mesh_bytes_sent_total counter")
        lines.append(f"mesh_bytes_sent_total{labels} {self.metrics.bytes_sent}")
        lines.append(f"mesh_bytes_received_total{labels} {self.metrics.bytes_received}")

        # Rate metrics
        lines.append(f"# HELP mesh_messages_per_second Messages per second")
        lines.append(f"# TYPE mesh_messages_per_second gauge")
        lines.append(f"mesh_messages_per_second{labels} {self.metrics.messages_per_second:.2f}")
        lines.append(f"mesh_bytes_per_second{labels} {self.metrics.bytes_per_second:.2f}")

        # Routing metrics
        lines.append(f"# HELP mesh_routes_total Total routes in routing table")
        lines.append(f"# TYPE mesh_routes_total gauge")
        lines.append(f"mesh_routes_total{labels} {self.metrics.total_routes}")
        lines.append(f"mesh_routes_direct{labels} {self.metrics.direct_routes}")
        lines.append(f"mesh_route_metric_avg{labels} {self.metrics.avg_route_metric:.2f}")

        # Peer metrics
        lines.append(f"# HELP mesh_peers_total Total known peers")
        lines.append(f"# TYPE mesh_peers_total gauge")
        lines.append(f"mesh_peers_total{labels} {self.metrics.total_peers}")
        lines.append(f"mesh_peers_connected{labels} {self.metrics.connected_peers}")
        lines.append(f"mesh_peers_anchors{labels} {self.metrics.anchor_peers}")
        lines.append(f"mesh_peers_blacklisted{labels} {self.metrics.blacklisted_peers}")
        lines.append(f"mesh_peer_reputation_avg{labels} {self.metrics.avg_peer_reputation:.2f}")
        lines.append(f"mesh_peer_latency_ms_avg{labels} {self.metrics.avg_peer_latency_ms:.2f}")

        # Certificate metrics
        lines.append(f"# HELP mesh_certificate_renewals_total Certificate renewals")
        lines.append(f"# TYPE mesh_certificate_renewals_total counter")
        lines.append(f"mesh_certificate_renewals_total{labels} {self.metrics.certificate_renewals}")
        lines.append(f"mesh_certificate_renewal_failures_total{labels} {self.metrics.certificate_renewal_failures}")
        lines.append(f"mesh_certificate_expiry_seconds{labels} {self.metrics.certificate_expiry_seconds:.0f}")

        # CRL metrics
        lines.append(f"# HELP mesh_crl_sequence Current CRL sequence number")
        lines.append(f"# TYPE mesh_crl_sequence gauge")
        lines.append(f"mesh_crl_sequence{labels} {self.metrics.crl_sequence}")
        lines.append(f"mesh_crl_revoked_certificates{labels} {self.metrics.revoked_certificates}")
        lines.append(f"mesh_crl_updates_total{labels} {self.metrics.crl_updates}")

        # Control plane metrics
        lines.append(f"# HELP mesh_control_messages_total Control plane messages")
        lines.append(f"# TYPE mesh_control_messages_total counter")
        lines.append(f"mesh_control_messages_received_total{labels} {self.metrics.control_messages_received}")
        lines.append(f"mesh_control_messages_accepted_total{labels} {self.metrics.control_messages_accepted}")
        lines.append(f"mesh_control_messages_rejected_total{labels} {self.metrics.control_messages_rejected}")

        # Uptime
        lines.append(f"# HELP mesh_uptime_seconds Node uptime in seconds")
        lines.append(f"# TYPE mesh_uptime_seconds counter")
        lines.append(f"mesh_uptime_seconds{labels} {self.metrics.uptime_seconds:.0f}")

        return "\n".join(lines) + "\n"

    def get_summary(self) -> dict:
        """Get human-readable metrics summary."""
        m = self.metrics
        return {
            "uptime": f"{self.get_uptime():.0f}s",
            "connections": {
                "total": m.total_connections,
                "established": m.established_connections,
                "failed": m.failed_connections,
            },
            "messages": {
                "sent": m.messages_sent,
                "received": m.messages_received,
                "forwarded": m.messages_forwarded,
                "dropped": m.messages_dropped,
                "rate_per_sec": f"{m.messages_per_second:.1f}",
            },
            "routing": {
                "total_routes": m.total_routes,
                "avg_metric": f"{m.avg_route_metric:.1f}",
            },
            "peers": {
                "total": m.total_peers,
                "connected": m.connected_peers,
                "anchors": m.anchor_peers,
                "avg_reputation": f"{m.avg_peer_reputation:.2f}",
                "avg_latency_ms": f"{m.avg_peer_latency_ms:.1f}",
            },
            "certificate": {
                "renewals": m.certificate_renewals,
                "failures": m.certificate_renewal_failures,
                "expiry_seconds": f"{m.certificate_expiry_seconds:.0f}",
            },
            "crl": {
                "sequence": m.crl_sequence,
                "revoked": m.revoked_certificates,
            },
        }
