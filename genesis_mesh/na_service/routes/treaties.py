"""Recognition treaty routes for cross-sovereign trust."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from html import escape
from math import cos, pi, sin
from typing import TYPE_CHECKING

from flask import Blueprint, Response, jsonify, request

from ...crypto import sign_model
from ...models import (
    MembershipAttestation,
    RecognitionTreaty,
    RecognitionTreatyScope,
    SovereignRevocationFeed,
)
from ...trust import (
    build_connectome_view,
    explain_trust_path,
    verify_attestation_with_treaty,
    verify_recognition_treaty,
    verify_sovereign_revocation_feed,
)
from ..operator_console.rendering import page_document

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService


def _json_model(model) -> dict:
    """Convert a Pydantic model to JSON-safe primitives."""
    return json.loads(model.model_dump_json())


def _row_payload(row: dict) -> dict:
    """Render a persisted treaty row for HTTP responses."""
    return {
        "treaty": _json_model(row["treaty"]),
        "status": row["status"],
        "revoked_at": row["revoked_at"],
        "revocation_reason": row["revocation_reason"],
    }


def _revoked_treaty_ids(service: "NetworkAuthorityService", treaty_id: str) -> set[str]:
    """Return local DB revocation input for a posted treaty."""
    stored = service.db.get_recognition_treaty(treaty_id)
    if stored and stored["status"] == "revoked":
        return {treaty_id}
    return set()


def _subject_public_keys_for_issuer(
    service: "NetworkAuthorityService",
    issuer_sovereign_id: str,
) -> list[str]:
    """Return public keys accepted for a treaty subject sovereign."""
    rows = service.db.list_recognition_treaties(
        subject_sovereign_id=issuer_sovereign_id,
        status="active",
    )
    keys = {
        public_key
        for row in rows
        for public_key in row["treaty"].subject_public_keys
    }
    return sorted(keys)


def _connectome_graph(view: dict) -> str:
    """Render a compact SVG recognition graph for the Connectome page."""
    sovereign_ids = {
        str(item.get("sovereign_id", ""))
        for item in view.get("sovereigns", [])
        if item.get("sovereign_id")
    }
    for edge in view.get("recognition_edges", []):
        sovereign_ids.add(str(edge.get("from", "")))
        sovereign_ids.add(str(edge.get("to", "")))
    sovereigns = sorted(item for item in sovereign_ids if item)

    if not sovereigns:
        return """
            <div class="connectome-graph graph-empty">
                <div>
                    <strong>No sovereign recognition graph yet.</strong><br>
                    Issue or import a recognition treaty to create the first edge.
                </div>
            </div>
        """

    width = 900
    height = 360
    radius = 118 if len(sovereigns) > 2 else 150
    center_x = width / 2
    center_y = height / 2
    positions: dict[str, tuple[float, float]] = {}
    if len(sovereigns) == 1:
        positions[sovereigns[0]] = (center_x, center_y)
    elif len(sovereigns) == 2:
        positions[sovereigns[0]] = (center_x - 210, center_y)
        positions[sovereigns[1]] = (center_x + 210, center_y)
    else:
        for index, sovereign in enumerate(sovereigns):
            angle = (2 * pi * index / len(sovereigns)) - (pi / 2)
            positions[sovereign] = (
                center_x + radius * cos(angle),
                center_y + radius * sin(angle),
            )

    edge_markup = []
    for edge in view.get("recognition_edges", []):
        source = str(edge.get("from", ""))
        target = str(edge.get("to", ""))
        if source not in positions or target not in positions:
            continue
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        status = str(edge.get("status", ""))
        treaty_id = str(edge.get("treaty_id", ""))
        css_class = "graph-edge graph-edge-revoked" if status == "revoked" else "graph-edge"
        edge_markup.append(
            f'<line class="{css_class}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"></line>'
        )
        edge_markup.append(
            f'<text class="graph-edge-label" x="{((x1 + x2) / 2):.1f}" y="{((y1 + y2) / 2 - 10):.1f}">'
            f'{escape(status or "edge")} {escape(treaty_id[:8])}</text>'
        )

    node_markup = []
    for sovereign, (x, y) in positions.items():
        node_markup.append(f'<circle class="graph-node" cx="{x:.1f}" cy="{y:.1f}" r="46"></circle>')
        node_markup.append(
            f'<text class="graph-node-label" x="{x:.1f}" y="{(y + 5):.1f}">{escape(sovereign)}</text>'
        )

    return f"""
        <div class="connectome-graph" role="img" aria-label="Sovereign recognition graph">
            <svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
                {"".join(edge_markup)}
                {"".join(node_markup)}
            </svg>
        </div>
    """


def _connectome_html(view: dict) -> str:
    """Render the operator Connectome page."""
    summary = view["summary"]
    graph = _connectome_graph(view)
    has_trust_state = bool(
        view["recognition_edges"]
        or view["revoked_trust_material"]
        or view["revocation_blast_radius"]
    )
    edge_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(edge.get('from', '')))}</td>"
        f"<td>{escape(str(edge.get('to', '')))}</td>"
        f"<td>{escape(str(edge.get('status', '')))}</td>"
        f"<td>{escape(str(edge.get('valid_from', '')))}</td>"
        f"<td>{escape(str(edge.get('expires_at', '')))}</td>"
        f"<td><code>{escape(str(edge.get('treaty_id', '')))}</code></td>"
        "</tr>"
        for edge in view["recognition_edges"]
    ) or '<tr class="empty-row"><td colspan="6">No recognition edges</td></tr>'
    revoked_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(item.get('type', '')))}</td>"
        f"<td><code>{escape(str(item.get('id', '')))}</code></td>"
        f"<td>{escape(str(item.get('reason', '')))}</td>"
        f"<td>{escape(str(item.get('revoked_at', '')))}</td>"
        "</tr>"
        for item in view["revoked_trust_material"]
    ) or '<tr class="empty-row"><td colspan="4">No revoked trust material</td></tr>'
    blast_rows = "\n".join(
        "<tr>"
        f"<td><code>{escape(str(item.get('id', '')))}</code></td>"
        f"<td>{escape(str(item.get('issuer_sovereign_id', '')))}</td>"
        f"<td>{escape(', '.join(item.get('affected_accepting_sovereigns', [])))}</td>"
        f"<td>{escape(str(item.get('reason', '')))}</td>"
        "</tr>"
        for item in view["revocation_blast_radius"]
    ) or '<tr class="empty-row"><td colspan="4">No imported revocation blast radius</td></tr>'

    trust_sections = f"""
  <section>
    <div class="section-head">
      <h2>Recognition Edges</h2>
      <p><a class="action-link" href="/connectome.json">Download Connectome JSON</a></p>
    </div>
    <table class="data-table">
      <thead><tr><th>From</th><th>To</th><th>Status</th><th>Valid from</th><th>Expires at</th><th>Treaty</th></tr></thead>
      <tbody>{edge_rows}</tbody>
    </table>
  </section>

  <section>
    <div class="section-head">
      <h2>Revoked Trust Material</h2>
      <p>Trust material imported or revoked by sovereign feeds.</p>
    </div>
    <table class="data-table">
      <thead><tr><th>Type</th><th>ID</th><th>Reason</th><th>Revoked at</th></tr></thead>
      <tbody>{revoked_rows}</tbody>
    </table>
  </section>

  <section>
    <div class="section-head">
      <h2>Revocation Blast Radius</h2>
      <p>Accepting sovereigns affected by imported revocations.</p>
    </div>
    <table class="data-table">
      <thead><tr><th>Revoked attestation</th><th>Issuer</th><th>Affected accepting sovereigns</th><th>Reason</th></tr></thead>
      <tbody>{blast_rows}</tbody>
    </table>
  </section>
"""
    if not has_trust_state:
        trust_sections = """
  <section>
    <div class="section-head">
      <h2>Trust State</h2>
      <p><a class="action-link" href="/connectome.json">Download Connectome JSON</a></p>
    </div>
    <div class="empty-state">
      <strong>No recognition or revocation state yet.</strong>
      <span>
        This sovereign has not imported treaties, recognized another sovereign,
        or imported revocation material. Once trust state exists, recognition
        edges, revoked material, and blast radius tables appear here.
      </span>
    </div>
  </section>
"""

    body = f"""
  <div class="hero">
    <h1>Genesis Mesh Connectome</h1>
    <p class="lead">
      Operator view of sovereign recognition edges, revoked trust material, and
      imported revocation blast radius. This page is derived from
      <a href="/recognition-graph">/recognition-graph</a>; it is not a separate
      source of trust.
    </p>
    <div class="stats" aria-label="Connectome summary">
      <div class="stat"><span>Sovereigns</span><strong>{summary["sovereign_count"]}</strong></div>
      <div class="stat"><span>Recognition Edges</span><strong>{summary["recognition_edge_count"]}</strong></div>
      <div class="stat"><span>Active Edges</span><strong>{summary["active_edge_count"]}</strong></div>
      <div class="stat"><span>Imported Revocations</span><strong>{summary["imported_revocation_count"]}</strong></div>
    </div>
  </div>

  <section>
    <div class="section-head">
      <h2>Sovereign Graph</h2>
      <p>Direct recognition edges derived from the recognition graph.</p>
    </div>
    {graph}
  </section>

  {trust_sections}

  <div class="notice">
    The Connectome explains current trust state. It does not create, mutate, or
    authorize recognition; signed treaties and revocation feeds remain the
    source of trust.
  </div>
"""
    return page_document("Genesis Mesh Connectome", "Connectome", body)


def create_treaty_blueprint(service: "NetworkAuthorityService") -> Blueprint:
    """Create routes for issuing, revoking, reading, and verifying treaties."""
    bp = Blueprint("recognition_treaties", __name__)

    @bp.route("/admin/recognition-treaties", methods=["POST"])
    def issue_treaty():
        """Issue a signed direct-recognition treaty for another sovereign."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            return jsonify({"error": "Rate limit exceeded"}), 429

        data = request.get_json() or {}
        ok, error = service._verify_admin_request(data)
        if not ok:
            return jsonify({"error": error}), 401

        subject_sovereign_id = data.get("subject_sovereign_id")
        subject_public_keys = data.get("subject_public_keys") or []
        if not subject_sovereign_id or not isinstance(subject_public_keys, list):
            return jsonify({"error": "subject_sovereign_id and subject_public_keys are required"}), 400
        if not subject_public_keys:
            return jsonify({"error": "subject_public_keys must not be empty"}), 400

        try:
            scope = RecognitionTreatyScope.model_validate(data.get("scope") or {})
        except Exception:
            return jsonify({"error": "Invalid treaty scope"}), 400

        if scope.allowed_roles:
            valid_roles, role_error = service._validate_roles(scope.allowed_roles)
            if not valid_roles:
                return jsonify({"error": role_error}), 400

        validity_hours = int(data.get("validity_hours", 168))
        if validity_hours <= 0:
            return jsonify({"error": "validity_hours must be greater than zero"}), 400

        now = datetime.now(timezone.utc)
        treaty = RecognitionTreaty(
            treaty_id=str(uuid.uuid4()),
            issuer_sovereign_id=data.get(
                "issuer_sovereign_id",
                service.genesis_block.network_name,
            ),
            subject_sovereign_id=subject_sovereign_id,
            subject_public_keys=subject_public_keys,
            scope=scope,
            status="active",
            issued_at=now,
            valid_from=now,
            expires_at=now + timedelta(hours=validity_hours),
            issued_by=service.key_id,
            metadata=data.get("metadata") or {},
            signatures=[],
        )
        treaty.signatures.append(sign_model(treaty, service.na_private_key, service.key_id))
        service.db.save_recognition_treaty(treaty)
        service.db.add_audit_event("recognition_treaty_issued", {
            "treaty_id": treaty.treaty_id,
            "issuer_sovereign_id": treaty.issuer_sovereign_id,
            "subject_sovereign_id": treaty.subject_sovereign_id,
            "allowed_roles": treaty.scope.allowed_roles,
        })

        return jsonify(_json_model(treaty)), 201

    @bp.route("/admin/recognition-treaties/<treaty_id>/revoke", methods=["POST"])
    def revoke_treaty(treaty_id: str):
        """Revoke a locally issued or imported recognition treaty."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            return jsonify({"error": "Rate limit exceeded"}), 429

        data = request.get_json() or {}
        ok, error = service._verify_admin_request(data)
        if not ok:
            return jsonify({"error": error}), 401

        reason = data.get("reason", "unspecified")
        if not service.db.revoke_recognition_treaty(treaty_id, reason):
            return jsonify({"error": "Recognition treaty not found"}), 404

        service.db.add_audit_event("recognition_treaty_revoked", {
            "treaty_id": treaty_id,
            "reason": reason,
        })
        return jsonify({"treaty_id": treaty_id, "status": "revoked"}), 200

    @bp.route("/recognition-treaties/<treaty_id>", methods=["GET"])
    def get_treaty(treaty_id: str):
        """Return a persisted recognition treaty by ID."""
        row = service.db.get_recognition_treaty(treaty_id)
        if not row:
            return jsonify({"error": "Recognition treaty not found"}), 404
        return jsonify(_row_payload(row))

    @bp.route("/recognition-treaties", methods=["GET"])
    def list_treaties():
        """List persisted recognition treaties."""
        rows = service.db.list_recognition_treaties(
            issuer_sovereign_id=request.args.get("issuer_sovereign_id"),
            subject_sovereign_id=request.args.get("subject_sovereign_id"),
            status=request.args.get("status"),
        )
        return jsonify({
            "count": len(rows),
            "recognition_treaties": [_row_payload(row) for row in rows],
        })

    @bp.route("/recognition-treaties/verify", methods=["POST"])
    def verify_treaty():
        """Verify a signed recognition treaty."""
        data = request.get_json() or {}
        try:
            treaty = RecognitionTreaty.model_validate(data.get("treaty"))
            issuer_public_keys = data.get("issuer_public_keys") or [
                service.genesis_block.network_authority.public_key
            ]
        except Exception:
            return jsonify({"error": "Invalid recognition treaty"}), 400

        result = verify_recognition_treaty(
            treaty,
            issuer_public_keys,
            expected_issuer_sovereign_id=data.get("expected_issuer_sovereign_id"),
            expected_subject_sovereign_id=data.get("expected_subject_sovereign_id"),
            revoked_treaty_ids=_revoked_treaty_ids(service, treaty.treaty_id),
        )
        service.db.add_audit_event("recognition_treaty_verified", {
            "treaty_id": treaty.treaty_id,
            "issuer_sovereign_id": treaty.issuer_sovereign_id,
            "subject_sovereign_id": treaty.subject_sovereign_id,
            "accepted": result.accepted,
            "reason": result.reason,
        })
        return jsonify({
            "accepted": result.accepted,
            "reason": result.reason,
            "treaty_id": result.treaty_id,
            "issuer_sovereign_id": result.issuer_sovereign_id,
            "subject_sovereign_id": result.subject_sovereign_id,
        })

    @bp.route("/attestations/verify-with-treaty", methods=["POST"])
    def verify_attestation_with_treaty_route():
        """Verify a membership attestation using a recognition treaty."""
        data = request.get_json() or {}
        try:
            attestation = MembershipAttestation.model_validate(data.get("attestation"))
            treaty = RecognitionTreaty.model_validate(data.get("treaty"))
            treaty_issuer_public_keys = data.get("treaty_issuer_public_keys") or [
                service.genesis_block.network_authority.public_key
            ]
        except Exception:
            return jsonify({"error": "Invalid attestation or recognition treaty"}), 400

        result = verify_attestation_with_treaty(
            attestation,
            treaty,
            treaty_issuer_public_keys,
            revoked_treaty_ids=_revoked_treaty_ids(service, treaty.treaty_id),
            revoked_attestation_ids=service.db.get_imported_revoked_attestation_ids(
                attestation.issuer_sovereign_id,
            ),
        )
        service.db.add_audit_event("treaty_attestation_verified", {
            "treaty_id": treaty.treaty_id,
            "attestation_id": attestation.attestation_id,
            "accepted": result.accepted,
            "reason": result.reason,
        })
        return jsonify({
            "accepted": result.accepted,
            "reason": result.reason,
            "treaty_id": result.treaty_id,
            "attestation_id": result.attestation_id,
            "issuer_sovereign_id": result.issuer_sovereign_id,
            "subject_sovereign_id": result.subject_sovereign_id,
        })

    @bp.route("/admin/sovereign-revocation-feeds/import", methods=["POST"])
    def import_sovereign_revocation_feed():
        """Import a signed revocation feed from a recognized sovereign."""
        remote_addr = request.remote_addr or "unknown"
        if not service.rate_limiter.allow(f"admin:{remote_addr}", 30, 60):
            return jsonify({"error": "Rate limit exceeded"}), 429

        data = request.get_json() or {}
        ok, error = service._verify_admin_request(data)
        if not ok:
            return jsonify({"error": error}), 401

        try:
            feed = SovereignRevocationFeed.model_validate(data.get("feed"))
        except Exception:
            return jsonify({"error": "Invalid sovereign revocation feed"}), 400

        issuer_public_keys = data.get("issuer_public_keys")
        if issuer_public_keys is None:
            issuer_public_keys = _subject_public_keys_for_issuer(
                service,
                feed.issuer_sovereign_id,
            )
        if not isinstance(issuer_public_keys, list) or not issuer_public_keys:
            return jsonify({
                "accepted": False,
                "reason": "missing_issuer_public_keys",
                "issuer_sovereign_id": feed.issuer_sovereign_id,
            }), 400

        latest_sequence = service.db.get_latest_sovereign_revocation_sequence(
            feed.issuer_sovereign_id,
        )
        result = verify_sovereign_revocation_feed(
            feed,
            issuer_public_keys,
            expected_issuer_sovereign_id=data.get("expected_issuer_sovereign_id"),
            min_sequence=latest_sequence,
        )
        if not result.accepted:
            status = 409 if result.reason == "stale_sequence" else 400
            service.db.add_audit_event("sovereign_revocation_feed_rejected", {
                "feed_id": feed.feed_id,
                "issuer_sovereign_id": feed.issuer_sovereign_id,
                "sequence": feed.sequence,
                "reason": result.reason,
            })
            return jsonify({
                "accepted": False,
                "reason": result.reason,
                "feed_id": feed.feed_id,
                "issuer_sovereign_id": feed.issuer_sovereign_id,
                "sequence": feed.sequence,
            }), status

        try:
            service.db.save_sovereign_revocation_feed(feed)
        except ValueError as exc:
            if str(exc) == "stale_sequence":
                return jsonify({
                    "accepted": False,
                    "reason": "stale_sequence",
                    "feed_id": feed.feed_id,
                    "issuer_sovereign_id": feed.issuer_sovereign_id,
                    "sequence": feed.sequence,
                }), 409
            raise

        service.db.add_audit_event("sovereign_revocation_feed_imported", {
            "feed_id": feed.feed_id,
            "issuer_sovereign_id": feed.issuer_sovereign_id,
            "sequence": feed.sequence,
            "revoked_count": len(feed.revoked_attestation_ids),
        })
        return jsonify({
            "accepted": True,
            "reason": "accepted",
            "feed_id": feed.feed_id,
            "issuer_sovereign_id": feed.issuer_sovereign_id,
            "sequence": feed.sequence,
            "revoked_count": len(feed.revoked_attestation_ids),
        })

    @bp.route("/recognition-graph", methods=["GET"])
    def recognition_graph():
        """Export minimal sovereign recognition graph data."""
        return jsonify(service.db.export_recognition_graph())

    @bp.route("/connectome.json", methods=["GET"])
    def connectome_json():
        """Return an operator-facing Connectome view as JSON."""
        return jsonify(build_connectome_view(service.db.export_recognition_graph()))

    @bp.route("/connectome/trust-path", methods=["GET"])
    def connectome_trust_path():
        """Explain whether one sovereign currently recognizes another."""
        source = request.args.get("from") or request.args.get("source")
        target = request.args.get("to") or request.args.get("target")
        if not source or not target:
            return jsonify({"error": "from/source and to/target are required"}), 400
        return jsonify(explain_trust_path(
            service.db.export_recognition_graph(),
            source,
            target,
        ))

    @bp.route("/connectome", methods=["GET"])
    def connectome_page():
        """Render a self-contained operator Connectome page."""
        view = build_connectome_view(service.db.export_recognition_graph())
        return Response(_connectome_html(view), mimetype="text/html")

    return bp
