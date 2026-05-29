"""Health and node-observability routes for the Network Authority."""

import json
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
        """Return recently heartbeating nodes from persisted certificate state."""
        now = datetime.utcnow()
        stale_threshold = timedelta(minutes=5)
        active_nodes = {}

        for row in service.db.list_issued_certs():
            if row.get("status") == "revoked" or not row.get("last_heartbeat"):
                continue

            last_hb = datetime.fromisoformat(row["last_heartbeat"])
            if now - last_hb < stale_threshold:
                active_nodes[row["cert_id"]] = {
                    "node_public_key": row["node_public_key"],
                    "roles": json.loads(row.get("roles_json") or "[]"),
                    "status": row.get("heartbeat_status") or row.get("status"),
                    "last_heartbeat": row["last_heartbeat"],
                    "remote_addr": row.get("remote_addr"),
                    "expires_at": row.get("expires_at"),
                }

        return jsonify({"count": len(active_nodes), "nodes": active_nodes})

    return bp
