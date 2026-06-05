"""Server-rendered Connectome operator view."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from math import cos, pi, sin
from typing import Any

from ...trust.treaty_lifecycle import is_lifecycle_active
from .rendering import page_document


def _human_datetime(value: object) -> str:
    """Render ISO datetimes compactly for operator HTML tables."""
    if not value:
        return ""
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def _connectome_graph(view: dict[str, Any]) -> str:
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
        status = str(edge.get("lifecycle_state") or edge.get("status") or "")
        css = (
            "graph-edge graph-edge-revoked"
            if status in {"revoked", "replaced", "expired"}
            else "graph-edge"
        )
        treaty_id = str(edge.get("treaty_id", ""))
        edge_markup.append(
            f'<line class="{css}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"></line>'
        )
        edge_markup.append(
            f'<text class="graph-edge-label" x="{((x1 + x2) / 2):.1f}" y="{((y1 + y2) / 2 - 10):.1f}">'
            f'{escape(status or "edge")} {escape(treaty_id[:8])}</text>'
        )

    node_markup = []
    for sovereign, (x, y) in positions.items():
        node_markup.append(f'<circle class="graph-node" cx="{x:.1f}" cy="{y:.1f}" r="42"></circle>')
        node_markup.append(
            f'<text class="graph-node-label" x="{x:.1f}" y="{(y + 5):.1f}">{escape(sovereign)}</text>'
        )

    return f"""
        <div class="connectome-graph" role="img" aria-label="Sovereign recognition graph">
            <svg viewBox="0 0 {width} {height}" aria-hidden="true">
                {"".join(edge_markup)}
                {"".join(node_markup)}
            </svg>
        </div>
    """


def _edge_is_current(edge: dict[str, Any]) -> bool:
    return edge.get("status") == "active" and is_lifecycle_active({
        "state": edge.get("lifecycle_state", "active"),
    })


def _edge_rows(edges: list[dict[str, Any]], empty_message: str) -> str:
    rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(edge.get('from', '')))}</td>"
        f"<td>{escape(str(edge.get('to', '')))}</td>"
        f"<td>{escape(str(edge.get('status', '')))}</td>"
        f"<td>{escape(str(edge.get('lifecycle_state', '')))}</td>"
        f"<td>{escape(str(edge.get('expiry_risk', '')))}</td>"
        f"<td>{escape(_human_datetime(edge.get('valid_from')))}</td>"
        f"<td>{escape(_human_datetime(edge.get('expires_at')))}</td>"
        f"<td><code>{escape(str(edge.get('treaty_id', '')))}</code></td>"
        "</tr>"
        for edge in edges
    )
    return rows or f'<tr class="empty-row"><td colspan="8">{escape(empty_message)}</td></tr>'


def _recognition_table(
    title: str,
    hint: str,
    rows: str,
    *,
    include_download: bool = False,
) -> str:
    download = (
        ' <a class="action-link" href="/connectome.json">Download Connectome JSON</a>'
        if include_download
        else ""
    )
    return f"""
  <section>
    <div class="section-head">
      <h2>{escape(title)}</h2>
      <p>{escape(hint)}{download}</p>
    </div>
    <table class="data-table">
      <thead>
        <tr>
          <th>From</th>
          <th>To</th>
          <th>Persisted status</th>
          <th>Lifecycle</th>
          <th>Expiry risk</th>
          <th>Valid from</th>
          <th>Expires at</th>
          <th>Treaty</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
"""


def _trust_sections(view: dict[str, Any]) -> str:
    """Render recognition and revocation tables for non-empty trust state."""
    current_edges = [
        edge for edge in view["recognition_edges"]
        if _edge_is_current(edge)
    ]
    historical_edges = [
        edge for edge in view["recognition_edges"]
        if not _edge_is_current(edge)
    ]
    current_rows = _edge_rows(current_edges, "No current recognition edges")
    historical_rows = _edge_rows(historical_edges, "No historical recognition edges")
    revoked_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(item.get('type', '')))}</td>"
        f"<td><code>{escape(str(item.get('id', '')))}</code></td>"
        f"<td>{escape(str(item.get('reason', '')))}</td>"
        f"<td>{escape(_human_datetime(item.get('revoked_at')))}</td>"
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

    return f"""
  {_recognition_table(
        "Current Recognition Edges",
        "Active or expiring-soon treaties that currently contribute trust.",
        current_rows,
        include_download=True,
    )}

  {_recognition_table(
        "Historical Recognition Edges",
        "Expired, revoked, or replaced treaty records retained for audit context.",
        historical_rows,
    )}

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
      <thead>
        <tr>
          <th>Revoked attestation</th>
          <th>Issuer</th>
          <th>Affected accepting sovereigns</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>{blast_rows}</tbody>
    </table>
  </section>
"""


def render_connectome(view: dict[str, Any]) -> str:
    """Render the operator Connectome page."""
    summary = view["summary"]
    graph = _connectome_graph(view)
    has_trust_state = bool(
        view["recognition_edges"]
        or view["revoked_trust_material"]
        or view["revocation_blast_radius"]
    )
    trust_sections = _trust_sections(view)
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
      <div class="stat">
        <span>Active Edges</span>
        <strong>{summary["active_edge_count"]}</strong>
      </div>
      <div class="stat">
        <span>Imported Revocations</span>
        <strong>{summary["imported_revocation_count"]}</strong>
      </div>
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
