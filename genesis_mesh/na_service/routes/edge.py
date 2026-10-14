"""Edge nodes (v1.7.0, Stage 6, beta): routes.

Edge agents (requests their node key signs, bound to a purpose and this NA):
  POST /node/boundary/evaluate         a decision under an attestation issued to the node
  POST /node/state                     the node, its executor key, its attestations and grants
  POST /node/evidence/resource-head    the head of a resource under the node's resource prefix

Operators (operator-signed headers):
  GET  /admin/edge-nodes               edge nodes, newest enrolment first (read tier)

Edge invites (``/admin/invite``), enrolment (``/join``), heartbeats,
renewals and revocation (``/admin/revoke``) extend the existing routes.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, request

from ...crypto.node_auth import NODE_PURPOSES
from ..errors import RateLimitError, UnauthorizedError, request_json_object

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService


def create_edge_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    """Create the node-scoped routes an edge agent calls and the operators' edge node view."""
    bp = Blueprint("edge", __name__)
    edge_service = service.edge_service

    def _node(route: str) -> tuple[dict, dict, dict]:
        """Rate limit, then authenticate a node-scoped request: (body, certificate row, edge node row)."""
        if not service.rate_limiter.allow(f"node_addr:{request.remote_addr or 'unknown'}",
                                          service.rate_limits.node_address, 60):
            raise RateLimitError()
        data = request_json_object()
        cert, edge = edge_service.authenticate(data, NODE_PURPOSES[route])
        if not service.rate_limiter.allow(f"node:{edge['node_public_key']}", service.rate_limits.node, 60):
            raise RateLimitError()
        return data, cert, edge

    @bp.route("/node/boundary/evaluate", methods=["POST"])
    def node_boundary_evaluate():
        """A signed decision under an attestation issued to the node (the node is the requester)."""
        data, _, edge = _node("/node/boundary/evaluate")
        decision, proof = edge_service.evaluate(data, edge)
        # The same signed records, serialized as /admin/boundary/evaluate does.
        return jsonify({"decision": json.loads(decision.model_dump_json()),
                        "justification_proof": json.loads(proof.model_dump_json())}), 201

    @bp.route("/node/state", methods=["POST"])
    def node_state():
        """The node, its executor key, the attestations issued to it and the grants its key bears."""
        _, cert, edge = _node("/node/state")
        return jsonify(edge_service.state(cert, edge))

    @bp.route("/node/evidence/resource-head", methods=["POST"])
    def node_resource_head():
        """Where the next record of a resource under the node's prefix must link."""
        data, _, edge = _node("/node/evidence/resource-head")
        return jsonify(edge_service.resource_head(data, edge))

    @bp.route("/admin/edge-nodes", methods=["GET"])
    def list_edge_nodes():
        """Edge nodes: ?status=online|offline|revoked, ?node_sovereign_id=, ?limit=1..500, ?before=."""
        if not service.rate_limiter.allow(f"admin:{request.remote_addr or 'unknown'}",
                                          service.rate_limits.admin, 60):
            raise RateLimitError()
        ok, err = service._verify_admin_request({}, required_tier="read")
        if not ok:
            raise UnauthorizedError(err or "Unauthorized", code="admin_auth_failed")
        status = request.args.get("status") or None
        limit = request.args.get("limit") or None
        before = request.args.get("before") or None
        node_sovereign_id = request.args.get("node_sovereign_id") or None
        return jsonify(edge_service.list_edge_nodes(status, limit, before, node_sovereign_id))

    return bp
