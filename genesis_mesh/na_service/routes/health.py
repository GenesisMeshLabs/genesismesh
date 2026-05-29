"""Health and node-observability routes for the Network Authority."""

import json
import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, Response, jsonify

logger = logging.getLogger(__name__)


def _recent_active_nodes(service) -> dict:
    """Return recently heartbeating, non-revoked nodes from persisted state."""
    now = datetime.now(timezone.utc)
    stale_threshold = timedelta(minutes=5)
    active_nodes = {}

    for row in service.db.list_issued_certs():
        if row.get("status") == "revoked" or not row.get("last_heartbeat"):
            continue

        last_hb = datetime.fromisoformat(row["last_heartbeat"])
        if last_hb.tzinfo is None:
            last_hb = last_hb.replace(tzinfo=timezone.utc)
        if now - last_hb < stale_threshold:
            active_nodes[row["cert_id"]] = {
                "node_public_key": row["node_public_key"],
                "roles": json.loads(row.get("roles_json") or "[]"),
                "status": row.get("heartbeat_status") or row.get("status"),
                "last_heartbeat": row["last_heartbeat"],
                "remote_addr": row.get("remote_addr"),
                "expires_at": row.get("expires_at"),
            }

    return active_nodes


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
            return jsonify({"status": "ready", "db_path": service.db.db_path})
        except Exception as exc:
            logger.error("Readiness check failed: %s", exc)
            return jsonify({
                "status": "not_ready",
                "db_path": service.db.db_path,
                "error": str(exc),
            }), 503

    @bp.route("/nodes", methods=["GET"])
    def list_nodes():
        """Return recently heartbeating nodes from persisted certificate state."""
        active_nodes = _recent_active_nodes(service)

        return jsonify({"count": len(active_nodes), "nodes": active_nodes})

    @bp.route("/metrics", methods=["GET"])
    def metrics():
        """Expose Network Authority operational counters in Prometheus text format."""
        issued_certs = service.db.list_issued_certs()
        active_nodes = _recent_active_nodes(service)
        revoked_count = sum(1 for cert in issued_certs if cert.get("status") == "revoked")
        crl = service.db.get_active_crl()
        crl_sequence = crl.sequence if crl else 0
        policy_versions = len(service.db.list_policy_versions())

        lines = [
            "# HELP genesis_mesh_na_issued_certs_total Total certificates issued by the Network Authority.",
            "# TYPE genesis_mesh_na_issued_certs_total gauge",
            f"genesis_mesh_na_issued_certs_total {len(issued_certs)}",
            "# HELP genesis_mesh_na_active_nodes Current recently active nodes.",
            "# TYPE genesis_mesh_na_active_nodes gauge",
            f"genesis_mesh_na_active_nodes {len(active_nodes)}",
            "# HELP genesis_mesh_na_revoked_certs_total Total certificates marked revoked.",
            "# TYPE genesis_mesh_na_revoked_certs_total gauge",
            f"genesis_mesh_na_revoked_certs_total {revoked_count}",
            "# HELP genesis_mesh_na_crl_sequence Active certificate revocation list sequence.",
            "# TYPE genesis_mesh_na_crl_sequence gauge",
            f"genesis_mesh_na_crl_sequence {crl_sequence}",
            "# HELP genesis_mesh_na_policy_versions_total Persisted policy versions.",
            "# TYPE genesis_mesh_na_policy_versions_total gauge",
            f"genesis_mesh_na_policy_versions_total {policy_versions}",
        ]
        return Response("\n".join(lines) + "\n", mimetype="text/plain; version=0.0.4")

    return bp
