"""Health checking for mesh nodes."""

import asyncio
import logging
from enum import Enum
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
import time


logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Node health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheck:
    """Individual health check result."""
    name: str
    status: HealthStatus
    message: str
    last_check: float
    details: Optional[Dict] = None


class HealthChecker:
    """
    Performs deep health checks on mesh node.

    Checks:
    - Certificate validity and expiry
    - Peer connectivity
    - Routing table state
    - CRL freshness
    - Component status
    """

    # Configuration for connectivity probing
    PROBE_SAMPLE_SIZE = 3  # Max peers to probe
    PROBE_TIMEOUT = 5.0  # Timeout per probe in seconds
    DEGRADED_SUCCESS_RATIO = 0.5  # Below this → DEGRADED

    def __init__(
        self,
        node_id: str,
        get_certificate_status: Callable,
        get_peer_stats: Callable,
        get_routing_stats: Callable,
        get_crl_status: Optional[Callable] = None,
        probe_peer: Optional[Callable] = None
    ):
        """
        Initialize health checker.

        Args:
            node_id: Local node ID
            get_certificate_status: Function to get certificate status
            get_peer_stats: Function to get peer statistics
            get_routing_stats: Function to get routing statistics
            get_crl_status: Function to get CRL status (optional)
            probe_peer: Async function(peer_id) -> float|None that pings a
                        peer and returns RTT in seconds, or None on failure.
                        When not provided, connectivity check is skipped.
        """
        self.node_id = node_id
        self.get_certificate_status = get_certificate_status
        self.get_peer_stats = get_peer_stats
        self.get_routing_stats = get_routing_stats
        self.get_crl_status = get_crl_status
        self.probe_peer = probe_peer

        self.checks: Dict[str, HealthCheck] = {}
        self._last_full_check = 0.0

    async def check_health(self, deep: bool = False) -> HealthStatus:
        """
        Check overall health.

        Args:
            deep: Perform deep checks (slower)

        Returns:
            Overall health status
        """
        checks = await self.run_all_checks(deep=deep)

        # Determine overall status
        if any(c.status == HealthStatus.UNHEALTHY for c in checks.values()):
            return HealthStatus.UNHEALTHY
        elif any(c.status == HealthStatus.DEGRADED for c in checks.values()):
            return HealthStatus.DEGRADED
        elif all(c.status == HealthStatus.HEALTHY for c in checks.values()):
            return HealthStatus.HEALTHY
        else:
            return HealthStatus.UNKNOWN

    async def run_all_checks(self, deep: bool = False) -> Dict[str, HealthCheck]:
        """
        Run all health checks.

        Args:
            deep: Perform deep checks

        Returns:
            Dictionary of check results
        """
        now = time.time()

        # Basic checks (always run)
        await self._check_certificate()
        await self._check_peers()
        await self._check_routing()

        # Deep checks (optional)
        if deep:
            await self._check_crl()
            await self._check_connectivity()

        self._last_full_check = now
        return self.checks

    async def _check_certificate(self):
        """Check certificate status."""
        try:
            cert_status = self.get_certificate_status()

            if not cert_status.get("has_certificate"):
                self.checks["certificate"] = HealthCheck(
                    name="certificate",
                    status=HealthStatus.UNHEALTHY,
                    message="No certificate",
                    last_check=time.time()
                )
                return

            if cert_status.get("is_expired"):
                self.checks["certificate"] = HealthCheck(
                    name="certificate",
                    status=HealthStatus.UNHEALTHY,
                    message="Certificate expired",
                    last_check=time.time(),
                    details=cert_status
                )
                return

            percent_remaining = cert_status.get("percent_remaining", 0)

            if percent_remaining < 10:
                status = HealthStatus.UNHEALTHY
                message = "Certificate expiring soon"
            elif percent_remaining < 25:
                status = HealthStatus.DEGRADED
                message = "Certificate should renew soon"
            else:
                status = HealthStatus.HEALTHY
                message = f"Certificate valid ({percent_remaining:.1f}% remaining)"

            self.checks["certificate"] = HealthCheck(
                name="certificate",
                status=status,
                message=message,
                last_check=time.time(),
                details=cert_status
            )

        except Exception as e:
            logger.error(f"Error checking certificate: {e}")
            self.checks["certificate"] = HealthCheck(
                name="certificate",
                status=HealthStatus.UNKNOWN,
                message=f"Check failed: {e}",
                last_check=time.time()
            )

    async def _check_peers(self):
        """Check peer connectivity."""
        try:
            stats = self.get_peer_stats()

            total = stats.get("total_peers", 0)
            connected = stats.get("connected_peers", 0)
            anchors = stats.get("anchor_peers", 0)

            if connected == 0:
                status = HealthStatus.UNHEALTHY
                message = "No connected peers"
            elif anchors == 0:
                status = HealthStatus.DEGRADED
                message = "No anchor connections"
            elif connected < 3:
                status = HealthStatus.DEGRADED
                message = f"Low peer count ({connected})"
            else:
                status = HealthStatus.HEALTHY
                message = f"{connected} peers connected ({anchors} anchors)"

            self.checks["peers"] = HealthCheck(
                name="peers",
                status=status,
                message=message,
                last_check=time.time(),
                details=stats
            )

        except Exception as e:
            logger.error(f"Error checking peers: {e}")
            self.checks["peers"] = HealthCheck(
                name="peers",
                status=HealthStatus.UNKNOWN,
                message=f"Check failed: {e}",
                last_check=time.time()
            )

    async def _check_routing(self):
        """Check routing table status."""
        try:
            stats = self.get_routing_stats()

            total_routes = stats.get("total_routes", 0)
            direct_neighbors = stats.get("direct_neighbors", 0)

            if direct_neighbors == 0:
                status = HealthStatus.UNHEALTHY
                message = "No direct neighbors"
            elif total_routes == 0:
                status = HealthStatus.DEGRADED
                message = "Empty routing table"
            else:
                status = HealthStatus.HEALTHY
                message = f"{total_routes} routes ({direct_neighbors} direct)"

            self.checks["routing"] = HealthCheck(
                name="routing",
                status=status,
                message=message,
                last_check=time.time(),
                details=stats
            )

        except Exception as e:
            logger.error(f"Error checking routing: {e}")
            self.checks["routing"] = HealthCheck(
                name="routing",
                status=HealthStatus.UNKNOWN,
                message=f"Check failed: {e}",
                last_check=time.time()
            )

    async def _check_crl(self):
        """Check CRL status."""
        if not self.get_crl_status:
            return

        try:
            crl_status = self.get_crl_status()

            if not crl_status.get("has_crl"):
                status = HealthStatus.DEGRADED
                message = "No CRL loaded"
            elif crl_status.get("is_expired"):
                status = HealthStatus.DEGRADED
                message = "CRL expired"
            else:
                status = HealthStatus.HEALTHY
                sequence = crl_status.get("sequence", 0)
                message = f"CRL up to date (seq {sequence})"

            self.checks["crl"] = HealthCheck(
                name="crl",
                status=status,
                message=message,
                last_check=time.time(),
                details=crl_status
            )

        except Exception as e:
            logger.error(f"Error checking CRL: {e}")
            self.checks["crl"] = HealthCheck(
                name="crl",
                status=HealthStatus.UNKNOWN,
                message=f"Check failed: {e}",
                last_check=time.time()
            )

    async def _check_connectivity(self):
        """
        Check actual connectivity by probing a sample of peers.

        Probes up to PROBE_SAMPLE_SIZE peers and maps the success ratio
        to a health status:
        - UNHEALTHY: zero peers reachable
        - DEGRADED: success ratio below DEGRADED_SUCCESS_RATIO
        - HEALTHY: otherwise
        """
        probe_peer = self.probe_peer
        if not probe_peer:
            # No probe callback available — skip rather than lie
            logger.debug("Connectivity check skipped: no probe_peer callback")
            return

        try:
            stats = self.get_peer_stats()
            peer_ids: List[str] = stats.get("connected_peer_ids", [])

            if not peer_ids:
                self.checks["connectivity"] = HealthCheck(
                    name="connectivity",
                    status=HealthStatus.UNHEALTHY,
                    message="No peers available to probe",
                    last_check=time.time(),
                    details={"probed": 0, "succeeded": 0}
                )
                return

            # Sample a bounded subset
            import random
            sample = random.sample(peer_ids, min(self.PROBE_SAMPLE_SIZE, len(peer_ids)))

            # Probe concurrently with timeout
            async def _probe_with_timeout(pid: str):
                """Probe one peer and normalize timeout or error as failure."""
                try:
                    rtt = await asyncio.wait_for(
                        probe_peer(pid),
                        timeout=self.PROBE_TIMEOUT
                    )
                    return pid, rtt
                except (asyncio.TimeoutError, Exception):
                    return pid, None

            results = await asyncio.gather(*[_probe_with_timeout(pid) for pid in sample])

            succeeded = [(pid, rtt) for pid, rtt in results if rtt is not None]
            failed = [(pid, rtt) for pid, rtt in results if rtt is None]
            success_ratio = len(succeeded) / len(results) if results else 0.0
            rtts = [rtt for _, rtt in succeeded]
            median_rtt = sorted(rtts)[len(rtts) // 2] if rtts else None

            details = {
                "probed": len(results),
                "succeeded": len(succeeded),
                "failed": len(failed),
                "success_ratio": round(success_ratio, 2),
                "median_rtt_ms": round(median_rtt * 1000, 1) if median_rtt else None,
                "timeout_count": len(failed),
            }

            if len(succeeded) == 0:
                status = HealthStatus.UNHEALTHY
                message = f"All {len(results)} probed peers unreachable"
            elif success_ratio < self.DEGRADED_SUCCESS_RATIO:
                status = HealthStatus.DEGRADED
                message = (
                    f"Connectivity degraded: {len(succeeded)}/{len(results)} peers reachable "
                    f"(median RTT {details['median_rtt_ms']}ms)"
                )
            else:
                status = HealthStatus.HEALTHY
                message = (
                    f"{len(succeeded)}/{len(results)} peers reachable "
                    f"(median RTT {details['median_rtt_ms']}ms)"
                )

            self.checks["connectivity"] = HealthCheck(
                name="connectivity",
                status=status,
                message=message,
                last_check=time.time(),
                details=details
            )

        except Exception as e:
            logger.error(f"Error checking connectivity: {e}")
            self.checks["connectivity"] = HealthCheck(
                name="connectivity",
                status=HealthStatus.UNKNOWN,
                message=f"Connectivity check failed: {e}",
                last_check=time.time()
            )

    def get_health_summary(self) -> dict:
        """Get health check summary."""
        overall = self.check_health_sync()

        return {
            "status": overall.value,
            "node_id": self.node_id,
            "checks": {
                name: {
                    "status": check.status.value,
                    "message": check.message,
                    "last_check": check.last_check,
                }
                for name, check in self.checks.items()
            },
            "last_full_check": self._last_full_check,
        }

    def check_health_sync(self) -> HealthStatus:
        """Synchronous health check (uses cached results)."""
        if not self.checks:
            return HealthStatus.UNKNOWN

        if any(c.status == HealthStatus.UNHEALTHY for c in self.checks.values()):
            return HealthStatus.UNHEALTHY
        elif any(c.status == HealthStatus.DEGRADED for c in self.checks.values()):
            return HealthStatus.DEGRADED
        elif all(c.status == HealthStatus.HEALTHY for c in self.checks.values()):
            return HealthStatus.HEALTHY
        else:
            return HealthStatus.UNKNOWN

    def is_healthy(self) -> bool:
        """Check if node is healthy (cached)."""
        return self.check_health_sync() == HealthStatus.HEALTHY
