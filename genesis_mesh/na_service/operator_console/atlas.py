"""Server-rendered Trust Atlas operator view."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any

from .rendering import page_document


def _human_datetime(value: object) -> str:
    if not value:
        return ""
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _treaty_scope_map(graph: dict[str, Any]) -> dict[str, list[str]]:
    """Map treaty_id -> allowed_roles from active_treaties in the graph."""
    result: dict[str, list[str]] = {}
    for treaty in graph.get("active_treaties", []):
        tid = str(treaty.get("treaty_id", ""))
        scope = treaty.get("scope") or {}
        roles = scope.get("allowed_roles") or []
        if tid:
            result[tid] = roles
    return result


def _edge_lifecycle(edge: dict[str, Any]) -> str:
    state = str(edge.get("lifecycle_state", ""))
    status = str(edge.get("status", ""))
    if state == "expiring_soon":
        return "expiring_soon"
    if status != "active" or state in {"expired", "revoked", "replaced"}:
        return "inactive"
    return "active"


def _status_pill(label: str, kind: str) -> str:
    css = {"active": "status-active", "expiring_soon": "status-warn", "inactive": "status-revoked"}.get(kind, "")
    return f'<span class="pill {css}">{escape(label)}</span>'


def _rel_row(edge: dict[str, Any], scope_map: dict[str, list[str]]) -> str:
    tid = str(edge.get("treaty_id", ""))
    roles = scope_map.get(tid, [])
    scope_text = ", ".join(escape(r) for r in roles) if roles else '<em class="muted">all roles</em>'
    lifecycle = _edge_lifecycle(edge)
    state_label = str(edge.get("lifecycle_state", edge.get("status", "unknown")))
    return (
        "<tr>"
        f"<td><code>{escape(str(edge.get('from', '')))}</code></td>"
        f"<td><code>{escape(str(edge.get('to', '')))}</code></td>"
        f"<td>{_status_pill(state_label, lifecycle)}</td>"
        f"<td>{scope_text}</td>"
        f"<td><span class=\"muted\">{escape(_human_datetime(edge.get('expires_at')))}</span></td>"
        "</tr>"
    )


def _rel_table(title: str, hint: str, rows: str) -> str:
    return f"""
  <section>
    <div class="section-head">
      <h2>{escape(title)}</h2>
      <p>{escape(hint)}</p>
    </div>
    <table class="data-table">
      <thead>
        <tr>
          <th>From</th><th>To</th><th>Status</th><th>Allowed roles</th><th>Expires</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
"""


def _evidence_section(evidences: list[dict[str, Any]]) -> str:
    if not evidences:
        return """
  <section>
    <div class="section-head">
      <h2>Trust Evidence Overlay</h2>
      <p>No evidence records loaded. Provide evidence files via
      <code>genesis-mesh atlas build --evidence &lt;dir&gt;</code> for static snapshots.</p>
    </div>
    <div class="empty-state">
      <strong>No TrustEvidence overlay.</strong>
      <span>
        Run <code>genesis-mesh atlas build --graph &lt;file&gt; --output &lt;dir&gt;
        --evidence &lt;dir&gt;</code> to generate a static Atlas with evidence overlay.
      </span>
    </div>
  </section>
"""
    def _verdict_kind(verdict: str) -> str:
        return {"allow": "active", "warn": "expiring_soon"}.get(verdict, "inactive")

    rows = "\n".join(
        "<tr>"
        f"<td><code>{escape(str(ev.get('evidence_id', ''))[:8])}…</code></td>"
        f"<td><code>{escape(str(ev.get('source_sovereign_id', '')))}</code></td>"
        f"<td><code>{escape(str(ev.get('target_sovereign_id', '')))}</code></td>"
        f"<td>{_status_pill(str(ev.get('verdict', '')).upper(), _verdict_kind(str(ev.get('verdict', ''))))}</td>"
        f"<td>{escape(str(ev.get('reason', '')))}</td>"
        f"<td>{escape(_human_datetime(ev.get('issued_at')))}</td>"
        "</tr>"
        for ev in evidences
    )
    count = len(evidences)
    noun = "record" if count == 1 else "records"
    return f"""
  <section>
    <div class="section-head">
      <h2>Trust Evidence Overlay ({count} {noun})</h2>
      <p>TrustEvidence records supplied to this Atlas view.</p>
    </div>
    <table class="data-table">
      <thead>
        <tr>
          <th>Evidence ID</th><th>From</th><th>To</th>
          <th>Verdict</th><th>Reason</th><th>Issued at</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
"""


def render_atlas(graph: dict[str, Any], evidences: list[dict[str, Any]] | None = None) -> str:
    """Render the operator Atlas page from a recognition graph export."""
    from ...trust.evidence import graph_digest_from_export

    sovereigns = graph.get("sovereigns", [])
    edges = graph.get("recognition_edges", [])
    scope_map = _treaty_scope_map(graph)
    active_edges = [e for e in edges if _edge_lifecycle(e) != "inactive"]
    inactive_edges = [e for e in edges if _edge_lifecycle(e) == "inactive"]
    expiring = [e for e in active_edges if _edge_lifecycle(e) == "expiring_soon"]
    evidence_list = evidences or []
    graph_digest = graph_digest_from_export(graph)

    if sovereigns:
        sov_rows = "\n".join(
            f"<tr><td><code>{escape(str(s.get('sovereign_id', '')))}</code></td></tr>"
            for s in sovereigns
        )
    else:
        sov_rows = '<tr class="empty-row"><td>No sovereigns in graph</td></tr>'

    active_rows = (
        "\n".join(_rel_row(e, scope_map) for e in active_edges)
        or '<tr class="empty-row"><td colspan="5">No active relationships</td></tr>'
    )
    inactive_rows = (
        "\n".join(_rel_row(e, scope_map) for e in inactive_edges)
        or '<tr class="empty-row"><td colspan="5">No historical relationships</td></tr>'
    )

    body = f"""
  <div class="hero">
    <h1>Trust Atlas</h1>
    <p class="lead">
      Read-only explorer of the recognition graph — sovereigns, trust relationships,
      and their scopes — derived from signed protocol data.
      Source: <a href="/recognition-graph">/recognition-graph</a>.
    </p>
    <div class="stats" aria-label="Atlas summary">
      <div class="stat"><span>Sovereigns</span><strong>{len(sovereigns)}</strong></div>
      <div class="stat"><span>Active Relationships</span><strong>{len(active_edges)}</strong></div>
      <div class="stat"><span>Expiring Soon</span><strong>{len(expiring)}</strong></div>
      <div class="stat"><span>Evidence Records</span><strong>{len(evidence_list)}</strong></div>
    </div>
  </div>

  <section>
    <div class="section-head">
      <h2>Sovereigns ({len(sovereigns)})</h2>
      <p>All sovereigns referenced in the recognition graph.</p>
    </div>
    <table class="data-table">
      <thead><tr><th>Sovereign ID</th></tr></thead>
      <tbody>{sov_rows}</tbody>
    </table>
  </section>

  {_rel_table(
      f"Active Trust Relationships ({len(active_edges)})",
      "Recognition treaties currently contributing trust. "
      "Scope is the set of allowed roles from the treaty.",
      active_rows,
  )}

  {_rel_table(
      f"Historical Relationships ({len(inactive_edges)})",
      "Expired, revoked, or replaced treaties retained for audit context.",
      inactive_rows,
  )}

  {_evidence_section(evidence_list)}

  <div class="notice">
    Graph digest: <code>{escape(graph_digest)}</code><br>
    Atlas describes the graph; it does not rank or score participants. No write paths.
    <a href="/connectome">View Connectome</a> &middot;
    <a href="/recognition-graph">Raw graph JSON</a>
  </div>
"""
    return page_document("Trust Atlas", "Atlas", body)


_STANDALONE_CSS = """
body { font-family: system-ui, sans-serif; margin: 0; background: #0f1117; color: #e2e8f0; }
.shell { max-width: 1100px; margin: 0 auto; padding: 2rem 1rem; }
h1 { font-size: 1.75rem; margin-bottom: .25rem; }
h2 { font-size: 1.15rem; margin: 2rem 0 .5rem; border-bottom: 1px solid #2d3748; padding-bottom: .25rem; }
.lead { color: #94a3b8; margin-bottom: 1.5rem; }
.stats { display: flex; gap: 1.5rem; flex-wrap: wrap; margin-bottom: 1.5rem; }
.stat { background: #1e2433; border-radius: 6px; padding: .75rem 1.25rem; }
.stat span { display: block; font-size: .75rem; color: #64748b; text-transform: uppercase; }
.stat strong { font-size: 1.5rem; }
table { border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }
th { text-align: left; padding: .5rem .75rem; border-bottom: 2px solid #2d3748; font-size: .8rem; text-transform: uppercase; color: #94a3b8; }
td { padding: .5rem .75rem; border-bottom: 1px solid #1e2433; font-size: .875rem; }
code { font-family: monospace; background: #1e2433; border-radius: 3px; padding: .15rem .35rem; }
.pill { display: inline-block; border-radius: 999px; padding: .15rem .55rem; font-size: .75rem; font-weight: 600; }
.status-active { background: #064e3b; color: #6ee7b7; }
.status-warn { background: #451a03; color: #fcd34d; }
.status-revoked { background: #1f1f2e; color: #94a3b8; }
.muted { color: #64748b; }
em.muted { font-style: normal; }
.notice { font-size: .8rem; color: #64748b; border-top: 1px solid #2d3748; padding-top: 1rem; margin-top: 2rem; }
a { color: #60a5fa; }
"""


def render_atlas_standalone(
    graph: dict[str, Any],
    evidences: list[dict[str, Any]],
    graph_digest: str,
) -> str:
    """Render a self-contained static Atlas HTML page for CLI build output."""
    sovereigns = graph.get("sovereigns", [])
    edges = graph.get("recognition_edges", [])
    scope_map = _treaty_scope_map(graph)
    active_edges = [e for e in edges if _edge_lifecycle(e) != "inactive"]
    inactive_edges = [e for e in edges if _edge_lifecycle(e) == "inactive"]
    expiring = [e for e in active_edges if _edge_lifecycle(e) == "expiring_soon"]

    if sovereigns:
        sov_rows = "\n".join(
            f"<tr><td><code>{escape(str(s.get('sovereign_id', '')))}</code></td></tr>"
            for s in sovereigns
        )
    else:
        sov_rows = "<tr><td><em>No sovereigns</em></td></tr>"

    def _plain_rel_row(edge: dict[str, Any]) -> str:
        tid = str(edge.get("treaty_id", ""))
        roles = scope_map.get(tid, [])
        scope_text = ", ".join(escape(r) for r in roles) if roles else '<em class="muted">all roles</em>'
        lifecycle = _edge_lifecycle(edge)
        state_label = str(edge.get("lifecycle_state", edge.get("status", "unknown")))
        return (
            "<tr>"
            f"<td><code>{escape(str(edge.get('from', '')))}</code></td>"
            f"<td><code>{escape(str(edge.get('to', '')))}</code></td>"
            f"<td>{_status_pill(state_label, lifecycle)}</td>"
            f"<td>{scope_text}</td>"
            f"<td><span class=\"muted\">{escape(_human_datetime(edge.get('expires_at')))}</span></td>"
            "</tr>"
        )

    active_rows = "\n".join(_plain_rel_row(e) for e in active_edges) or "<tr><td colspan='5'><em>None</em></td></tr>"
    inactive_rows = "\n".join(_plain_rel_row(e) for e in inactive_edges) or "<tr><td colspan='5'><em>None</em></td></tr>"

    def _verdict_kind(verdict: str) -> str:
        return {"allow": "active", "warn": "expiring_soon"}.get(verdict, "inactive")

    if evidences:
        ev_rows = "\n".join(
            "<tr>"
            f"<td><code>{escape(str(ev.get('evidence_id', ''))[:8])}…</code></td>"
            f"<td><code>{escape(str(ev.get('source_sovereign_id', '')))}</code></td>"
            f"<td><code>{escape(str(ev.get('target_sovereign_id', '')))}</code></td>"
            f"<td>{_status_pill(str(ev.get('verdict', '')).upper(), _verdict_kind(str(ev.get('verdict', ''))))}</td>"
            f"<td>{escape(str(ev.get('reason', '')))}</td>"
            f"<td>{'<span class=\"pill status-active\">verified</span>' if ev.get('_atlas_verified') else '<span class=\"pill status-revoked\">unverified</span>'}</td>"
            f"<td>{escape(_human_datetime(ev.get('issued_at')))}</td>"
            "</tr>"
            for ev in evidences
        )
        ev_section = f"""
<h2>Trust Evidence Overlay ({len(evidences)} record{"s" if len(evidences) != 1 else ""})</h2>
<table>
  <thead>
    <tr>
      <th>Evidence ID</th><th>From</th><th>To</th>
      <th>Verdict</th><th>Reason</th><th>Sig</th><th>Issued at</th>
    </tr>
  </thead>
  <tbody>{ev_rows}</tbody>
</table>
"""
    else:
        ev_section = "<h2>Trust Evidence Overlay</h2><p class='muted'>No evidence records. See <code>genesis-mesh atlas build --evidence &lt;dir&gt;</code>.</p>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Trust Atlas</title>
  <style>{_STANDALONE_CSS}</style>
</head>
<body>
<div class="shell">
  <h1>Trust Atlas</h1>
  <p class="lead">Read-only recognition graph snapshot. Derived from signed protocol data only.</p>
  <div class="stats">
    <div class="stat"><span>Sovereigns</span><strong>{len(sovereigns)}</strong></div>
    <div class="stat"><span>Active Relationships</span><strong>{len(active_edges)}</strong></div>
    <div class="stat"><span>Expiring Soon</span><strong>{len(expiring)}</strong></div>
    <div class="stat"><span>Evidence Records</span><strong>{len(evidences)}</strong></div>
  </div>

  <h2>Sovereigns ({len(sovereigns)})</h2>
  <table>
    <thead><tr><th>Sovereign ID</th></tr></thead>
    <tbody>{sov_rows}</tbody>
  </table>

  <h2>Active Trust Relationships ({len(active_edges)})</h2>
  <table>
    <thead><tr><th>From</th><th>To</th><th>Status</th><th>Allowed roles</th><th>Expires</th></tr></thead>
    <tbody>{active_rows}</tbody>
  </table>

  <h2>Historical Relationships ({len(inactive_edges)})</h2>
  <table>
    <thead><tr><th>From</th><th>To</th><th>Status</th><th>Allowed roles</th><th>Expires</th></tr></thead>
    <tbody>{inactive_rows}</tbody>
  </table>

  {ev_section}

  <div class="notice">
    Graph digest: <code>{escape(graph_digest)}</code><br>
    Atlas describes the graph only. No writes. No ranking.
  </div>
</div>
</body>
</html>"""
