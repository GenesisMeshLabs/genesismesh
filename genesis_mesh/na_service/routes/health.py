"""Health and node-observability routes for the Network Authority."""

import logging
from datetime import datetime, timedelta

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)


def create_health_blueprint(service) -> Blueprint:
    """Create the health blueprint bound to a Network Authority service."""
    bp = Blueprint("na_health", __name__)

    @bp.route("/health", methods=["GET"])
    def health():
        """Return legacy health metadata."""
        return jsonify(
            {
                "status": "healthy",
                "network": service.genesis_block.network_name,
                "version": service.genesis_block.network_version,
            }
        )

    @bp.route("/healthz", methods=["GET"])
    def healthz():
        """Return process liveness without dependency checks."""
        return jsonify({"status": "ok"})

    @bp.route("/readyz", methods=["GET"])
    def readyz():
        """Return readiness after checking DB, genesis, and NA key state."""
        try:
            service.db.conn.execute("SELECT 1").fetchone()
            if not service.genesis_block or not service.na_private_key:
                return jsonify({"status": "not_ready"}), 503
            return jsonify({"status": "ready"})
        except Exception as exc:
            logger.error("Readiness check failed: %s", exc)
            return jsonify({"status": "not_ready", "error": str(exc)}), 503

    @bp.route("/nodes", methods=["GET"])
    def list_nodes():
        """Return recently heartbeating nodes from the compatibility mirror."""
        now = datetime.utcnow()
        stale_threshold = timedelta(minutes=5)
        active_nodes = {}

        for cert_id, info in service.connected_nodes.items():
            last_hb = datetime.fromisoformat(info["last_heartbeat"])
            if now - last_hb < stale_threshold:
                active_nodes[cert_id] = info

        service.connected_nodes = active_nodes
        return jsonify({"count": len(active_nodes), "nodes": active_nodes})

    return bp
