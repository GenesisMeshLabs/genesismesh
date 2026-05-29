"""Synchronous persistent runner for legacy MeshNode heartbeat mode."""

import logging
import signal
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .node import MeshNode


logger = logging.getLogger(__name__)


def run_persistent_node(
    node: "MeshNode",
    na_endpoint: str,
    heartbeat_interval: int = 30,
    renewal_threshold_hours: int = 24,
) -> None:
    """Run heartbeats and certificate renewal for a joined node."""
    node._na_endpoint = na_endpoint
    node._running = True

    def signal_handler(signum, frame):
        """Stop the persistent heartbeat loop after a shutdown signal."""
        logger.info("Shutdown signal received")
        node._running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info(
        "Node running in persistent mode (heartbeat every %ss)",
        heartbeat_interval,
    )

    last_heartbeat = 0.0
    heartbeat_failures = 0
    max_failures = 5

    while node._running:
        now = time.time()

        if now - last_heartbeat >= heartbeat_interval:
            if node.send_heartbeat(na_endpoint):
                heartbeat_failures = 0
            else:
                heartbeat_failures += 1
                logger.warning(
                    "Heartbeat failure %s/%s",
                    heartbeat_failures,
                    max_failures,
                )

                if heartbeat_failures >= max_failures:
                    logger.error("Too many heartbeat failures, attempting reconnect...")
                    try:
                        node.join_network(na_endpoint)
                        heartbeat_failures = 0
                    except Exception as exc:
                        logger.error("Reconnect failed: %s", exc)

            last_heartbeat = now

        if node.should_renew_certificate(renewal_threshold_hours):
            logger.info("Certificate nearing expiry, renewing...")
            if not node.renew_certificate(na_endpoint):
                logger.error("Certificate renewal failed")

        time.sleep(1)

    logger.info("Node shutdown complete")
