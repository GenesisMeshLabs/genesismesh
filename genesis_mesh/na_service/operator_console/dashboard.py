"""Read-only sovereign health and trust dashboard."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any

from ...trust import build_connectome_view
from ...trust.treaty_lifecycle import treaty_lifecycle
from .rendering import node_counts, page_document

FRESH_FEED_HOURS = 24
STALE_FEED_HOURS = 72
PRIVATE_DETAIL_TERMS = ("private", "secret", "signature", "token")


def _parse_datetime(value: object) -> datetime | None:
    """Parse a persisted datetime as UTC when possible."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _human_datetime(value: object) -> str:
    """Render a datetime for operator-readable dashboard rows."""
    parsed = _parse_datetime(value)
    if parsed is None:
        return "" if not value else str(value)
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def _readiness(service) -> dict[str, str]:
    """Return local readiness without calling the HTTP route."""
    try:
        service.db.conn.execute("SELECT 1").fetchone()
        if not service.genesis_block or not service.na_private_key:
            return {"status": "not_ready", "db_path": service.db.db_path}
        return {"status": "ready", "db_path": service.db.db_path}
    except Exception as exc:
        return {"status": "not_ready", "db_path": service.db.db_path, "error": str(exc)}


def _treaty_items(service) -> list[dict[str, Any]]:
    """Return treaty lifecycle rows safe for dashboard output."""
    items = []
    for row in service.db.list_recognition_treaties():
        treaty = row["treaty"]
        lifecycle = treaty_lifecycle(row)
        items.append({
            "treaty_id": treaty.treaty_id,
            "issuer_sovereign_id": treaty.issuer_sovereign_id,
            "subject_sovereign_id": treaty.subject_sovereign_id,
            "status": row["status"],
            "lifecycle_state": lifecycle["state"],
            "expiry_risk": lifecycle["expiry_risk"],
            "valid_from": treaty.valid_from.isoformat(),
            "expires_at": treaty.expires_at.isoformat(),
            "valid_from_display": _human_datetime(treaty.valid_from.isoformat()),
            "expires_at_display": _human_datetime(treaty.expires_at.isoformat()),
            "revoked_at": row["revoked_at"],
            "revocation_reason": row["revocation_reason"],
        })
    risk_order = {"high": 0, "expired": 1, "medium": 2, "low": 3}
    return sorted(items, key=lambda item: (risk_order.get(item["expiry_risk"], 9), item["expires_at"]))


def _treaty_summary(treaties: list[dict[str, Any]]) -> dict[str, int]:
    """Summarize treaty lifecycle states."""
    states = {"active": 0, "expiring_soon": 0, "expired": 0, "revoked": 0, "replaced": 0}
    for treaty in treaties:
        state = str(treaty["lifecycle_state"])
        states[state] = states.get(state, 0) + 1
    return {
        "total": len(treaties),
        **states,
        "warning_count": states.get("expiring_soon", 0) + states.get("expired", 0),
    }


def _revocation_feed_items(service) -> list[dict[str, Any]]:
    """Return imported revocation feed freshness rows."""
    now = datetime.now(timezone.utc)
    items = []
    for row in service.db.list_sovereign_revocation_feeds():
        feed = row["feed"]
        imported_at = _parse_datetime(row["imported_at"])
        age_hours = None if imported_at is None else max(0, int((now - imported_at).total_seconds() // 3600))
        if age_hours is None:
            freshness = "unknown"
        elif age_hours <= FRESH_FEED_HOURS:
            freshness = "fresh"
        elif age_hours <= STALE_FEED_HOURS:
            freshness = "watch"
        else:
            freshness = "stale"
        items.append({
            "feed_id": feed.feed_id,
            "issuer_sovereign_id": feed.issuer_sovereign_id,
            "sequence": feed.sequence,
            "revoked_count": len(feed.revoked_attestation_ids),
            "imported_at": row["imported_at"],
            "imported_at_display": _human_datetime(row["imported_at"]),
            "age_hours": age_hours,
            "freshness": freshness,
        })
    return sorted(items, key=lambda item: (item["issuer_sovereign_id"], item["sequence"]))


def _feed_summary(feeds: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize imported revocation feeds."""
    freshness = "none"
    if feeds:
        if any(feed["freshness"] == "stale" for feed in feeds):
            freshness = "stale"
        elif any(feed["freshness"] in {"watch", "unknown"} for feed in feeds):
            freshness = "watch"
        else:
            freshness = "fresh"
    return {
        "count": len(feeds),
        "freshness": freshness,
        "stale_count": sum(1 for feed in feeds if feed["freshness"] == "stale"),
        "watch_count": sum(1 for feed in feeds if feed["freshness"] in {"watch", "unknown"}),
    }


def _is_safe_detail(key: str) -> bool:
    """Return whether an audit detail key is safe for operator surfaces."""
    lowered = key.lower()
    return not any(term in lowered for term in PRIVATE_DETAIL_TERMS)


def _short_value(value: object) -> str:
    """Render identifiers compactly without hiding their useful shape."""
    if isinstance(value, bool):
        return "accepted" if value else "rejected"
    if isinstance(value, list):
        return ", ".join(_short_value(item) for item in value)
    text = str(value)
    if len(text) >= 28 and "-" in text:
        return f"{text[:8]}...{text[-6:]}"
    if len(text) > 42:
        return f"{text[:36]}..."
    return text


def _label(key: str) -> str:
    return key.replace("_", " ").capitalize()


def _audit_summary(event_type: str, details: dict[str, Any]) -> dict[str, Any]:
    """Create a human-readable summary for trust-relevant audit details."""
    detail_map = {
        "recognition_treaty_issued": [
            ("Treaty", "treaty_id"),
            ("From", "issuer_sovereign_id"),
            ("To", "subject_sovereign_id"),
            ("Roles", "allowed_roles"),
        ],
        "recognition_treaty_revoked": [
            ("Treaty", "treaty_id"),
            ("Reason", "reason"),
        ],
        "recognition_treaty_verified": [
            ("Treaty", "treaty_id"),
            ("From", "issuer_sovereign_id"),
            ("To", "subject_sovereign_id"),
            ("Result", "accepted"),
            ("Reason", "reason"),
        ],
        "treaty_attestation_verified": [
            ("Attestation", "attestation_id"),
            ("Treaty", "treaty_id"),
            ("Result", "accepted"),
            ("Reason", "reason"),
        ],
        "sovereign_revocation_feed_imported": [
            ("Feed", "feed_id"),
            ("Issuer", "issuer_sovereign_id"),
            ("Sequence", "sequence"),
            ("Revoked IDs", "revoked_count"),
        ],
        "sovereign_revocation_feed_rejected": [
            ("Feed", "feed_id"),
            ("Issuer", "issuer_sovereign_id"),
            ("Sequence", "sequence"),
            ("Reason", "reason"),
        ],
    }
    titles = {
        "recognition_treaty_issued": "Treaty issued",
        "recognition_treaty_revoked": "Treaty revoked",
        "recognition_treaty_verified": "Treaty verified",
        "treaty_attestation_verified": "Attestation checked against treaty",
        "sovereign_revocation_feed_imported": "Revocation feed imported",
        "sovereign_revocation_feed_rejected": "Revocation feed rejected",
    }
    fields = []
    for label, key in detail_map.get(event_type, []):
        if key in details and details[key] not in (None, ""):
            fields.append({"label": label, "value": _short_value(details[key])})
    if not fields:
        fields = [
            {"label": _label(key), "value": _short_value(value)}
            for key, value in details.items()
        ]
    result = details.get("accepted")
    if isinstance(result, bool):
        state = "accepted" if result else "rejected"
    elif "rejected" in event_type:
        state = "rejected"
    elif "revoked" in event_type:
        state = "revoked"
    else:
        state = "recorded"
    return {
        "title": titles.get(event_type, event_type.replace("_", " ")),
        "state": state,
        "fields": fields,
    }


def _safe_recent_changes(service) -> list[dict[str, Any]]:
    """Return recent trust-relevant audit events with human-readable details."""
    trust_terms = ("recognition", "attestation", "revocation", "policy")
    events = [
        event for event in service.db.list_audit_events()
        if any(term in str(event.get("event_type", "")) for term in trust_terms)
    ]
    changes = []
    for event in reversed(events[-8:]):
        details = event.get("details") or {}
        safe_details = {
            key: value
            for key, value in details.items()
            if _is_safe_detail(str(key))
        }
        changes.append({
            "event_type": event.get("event_type", ""),
            "created_at": event.get("created_at", ""),
            "created_at_display": _human_datetime(event.get("created_at")),
            "details": safe_details,
            "summary": _audit_summary(str(event.get("event_type", "")), safe_details),
        })
    return changes


def build_dashboard_model(service) -> dict[str, Any]:
    """Build the dashboard model used by both HTML and JSON routes."""
    active_nodes, tracked_nodes = node_counts(service)
    connectome = build_connectome_view(service.db.export_recognition_graph())
    treaties = _treaty_items(service)
    feeds = _revocation_feed_items(service)
    treaty_summary = _treaty_summary(treaties)
    feed_summary = _feed_summary(feeds)
    warnings = []
    if treaty_summary["expiring_soon"]:
        warnings.append(f"{treaty_summary['expiring_soon']} treaty is expiring soon.")
    if treaty_summary["expired"]:
        warnings.append(f"{treaty_summary['expired']} treaty is expired.")
    if treaty_summary["revoked"] or treaty_summary["replaced"]:
        warnings.append("Historical revoked or replaced treaty material is present.")
    if feed_summary["stale_count"]:
        warnings.append(f"{feed_summary['stale_count']} revocation feed looks stale.")
    return {
        "sovereign": {
            "id": service.genesis_block.network_name,
            "version": service.genesis_block.network_version,
        },
        "readiness": _readiness(service),
        "nodes": {"active": active_nodes, "tracked": tracked_nodes},
        "connectome_summary": connectome["summary"],
        "treaty_summary": treaty_summary,
        "treaties": treaties,
        "revocation_feed_summary": feed_summary,
        "revocation_feeds": feeds,
        "recent_changes": _safe_recent_changes(service),
        "warnings": warnings,
        "links": {
            "dashboard_json": "/dashboard.json",
            "connectome": "/connectome",
            "connectome_json": "/connectome.json",
            "recognition_treaties": "/recognition-treaties",
            "recognition_graph": "/recognition-graph",
            "api_reference": "/api-reference",
            "cli_reference": "/cli-reference",
        },
    }


def _status_class(value: str) -> str:
    """Return the visual class for a compact status badge."""
    css = "status-ok" if value in {"ready", "fresh", "active", "low"} else "status-watch"
    if value in {"expired", "revoked", "stale", "not_ready", "high", "rejected"}:
        css = "status-risk"
    return css


def _status_badge(value: str) -> str:
    """Render a compact status badge."""
    css = _status_class(value)
    return f'<span class="status-badge {css}">{escape(value.replace("_", " "))}</span>'


def _treaty_table(treaties: list[dict[str, Any]]) -> str:
    """Render treaty lifecycle rows or a useful empty state."""
    if not treaties:
        return """
            <div class="empty-state">
                <strong>No recognition treaties yet.</strong>
                <span>Use federation bootstrap or a signed treaty command to create the first direct-recognition edge.</span>
            </div>
        """
    rows = "\n".join(
        "<tr>"
        f"<td><code>{escape(treaty['treaty_id'])}</code></td>"
        f"<td>{escape(treaty['issuer_sovereign_id'])} -> {escape(treaty['subject_sovereign_id'])}</td>"
        f"<td>{_status_badge(str(treaty['lifecycle_state']))}</td>"
        f"<td>{_status_badge(str(treaty['expiry_risk']))}</td>"
        f"<td>{escape(treaty['valid_from_display'])}</td>"
        f"<td>{escape(treaty['expires_at_display'])}</td>"
        "</tr>"
        for treaty in treaties
    )
    return f"""
        <table class="data-table">
            <thead><tr><th>Treaty</th><th>Path</th><th>Lifecycle</th><th>Expiry risk</th><th>Valid from</th><th>Expires at</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    """


def _feed_table(feeds: list[dict[str, Any]]) -> str:
    """Render imported revocation feed rows or an empty state."""
    if not feeds:
        return """
            <div class="empty-state">
                <strong>No imported sovereign revocation feeds.</strong>
                <span>This is normal for a fresh sovereign. Imported feed status appears here after recognition and feed import.</span>
            </div>
        """
    rows = "\n".join(
        "<tr>"
        f"<td>{escape(feed['issuer_sovereign_id'])}</td>"
        f"<td><code>{escape(feed['feed_id'])}</code></td>"
        f"<td>{escape(str(feed['sequence']))}</td>"
        f"<td>{escape(str(feed['revoked_count']))}</td>"
        f"<td>{escape(feed['imported_at_display'])}</td>"
        f"<td>{_status_badge(str(feed['freshness']))}</td>"
        "</tr>"
        for feed in feeds
    )
    return f"""
        <table class="data-table">
            <thead><tr><th>Issuer</th><th>Feed</th><th>Sequence</th><th>Revoked IDs</th><th>Imported</th><th>Freshness</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    """


def _changes_table(changes: list[dict[str, Any]]) -> str:
    """Render recent trust-state audit events."""
    if not changes:
        return """
            <div class="empty-state">
                <strong>No recent trust-state changes.</strong>
                <span>Trust-relevant audit events appear here after treaty, attestation, policy, or revocation activity.</span>
            </div>
        """
    def summary_markup(change: dict[str, Any]) -> str:
        summary = change["summary"]
        fields = "".join(
            "<span>"
            f"<strong>{escape(field['label'])}</strong> "
            f"{escape(field['value'])}"
            "</span>"
            for field in summary["fields"]
        )
        return (
            '<div class="audit-summary">'
            f"<strong>{escape(summary['title'])}</strong>"
            f'<span class="status-badge {_status_class(str(summary["state"]))}">'
            f'{escape(str(summary["state"]).replace("_", " "))}</span>'
            f'<div class="audit-fields">{fields}</div>'
            "</div>"
        )

    rows = "\n".join(
        "<tr>"
        f"<td>{escape(change['created_at_display'])}</td>"
        f"<td>{escape(change['event_type'])}</td>"
        f"<td>{summary_markup(change)}</td>"
        "</tr>"
        for change in changes
    )
    return f"""
        <table class="data-table">
            <thead><tr><th>Time</th><th>Event</th><th>Audit summary</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    """


def render_dashboard(service) -> str:
    """Render the sovereign health and trust dashboard."""
    model = build_dashboard_model(service)
    warnings = model["warnings"]
    warning_markup = (
        "".join(f'<li>{escape(warning)}</li>' for warning in warnings)
        if warnings
        else "<li>No trust warnings detected from local state.</li>"
    )
    body = f"""
        <div class="hero">
            <h1>Sovereign Health and Trust</h1>
            <p class="lead">
                Read-only view of local sovereign health, treaty lifecycle risk,
                revocation feed freshness, and recent trust-state changes.
            </p>
            <div class="hero-meta">
                <span>{escape(model['sovereign']['id'])}</span>
                <span>{escape(model['readiness']['status']).title()}</span>
                <span>{escape(model['sovereign']['version'])}</span>
            </div>
            <div class="stats" aria-label="Dashboard summary">
                <div class="stat"><span>Active Edges</span><strong>{model['connectome_summary']['active_edge_count']}</strong></div>
                <div class="stat"><span>Treaty Warnings</span><strong>{model['treaty_summary']['warning_count']}</strong></div>
                <div class="stat"><span>Revocation Feeds</span><strong>{model['revocation_feed_summary']['count']}</strong></div>
                <div class="stat"><span>Active Nodes</span><strong>{model['nodes']['active']}</strong></div>
            </div>
        </div>

        <section>
            <div class="section-head">
                <h2>Trust Warnings</h2>
                <p>Derived from local treaty lifecycle and revocation-feed state.</p>
            </div>
            <div class="dashboard-grid">
                <div class="signal-card">
                    <strong>Health</strong>
                    {_status_badge(model['readiness']['status'])}
                    <span class="muted">Database: {escape(model['readiness']['db_path'])}</span>
                </div>
                <div class="signal-card">
                    <strong>Revocation feeds</strong>
                    {_status_badge(model['revocation_feed_summary']['freshness'])}
                    <span class="muted">{model['revocation_feed_summary']['count']} imported feeds</span>
                </div>
                <div class="signal-card signal-card-wide">
                    <strong>Operator notes</strong>
                    <ul class="signal-list">{warning_markup}</ul>
                </div>
            </div>
        </section>

        <section>
            <div class="section-head">
                <h2>Treaty Lifecycle</h2>
                <p><a href="/recognition-treaties">Raw treaties</a> · <a href="/connectome">Connectome</a></p>
            </div>
            {_treaty_table(model['treaties'])}
        </section>

        <section>
            <div class="section-head">
                <h2>Revocation Feed Freshness</h2>
                <p>Fresh: {FRESH_FEED_HOURS}h. Watch: {STALE_FEED_HOURS}h. Older feeds are stale.</p>
            </div>
            {_feed_table(model['revocation_feeds'])}
        </section>

        <section>
            <div class="section-head">
                <h2>Recent Trust Changes</h2>
                <p>Sanitized audit events; use managed audit export for full local records.</p>
            </div>
            {_changes_table(model['recent_changes'])}
        </section>

        <section>
            <div class="section-head">
                <h2>Verification Links</h2>
                <p>Automation and source-of-truth surfaces.</p>
            </div>
            <div class="pill-row">
                <a class="action-link" href="/dashboard.json">Dashboard JSON</a>
                <a class="action-link" href="/connectome.json">Connectome JSON</a>
                <a class="action-link" href="/recognition-graph">Recognition Graph</a>
                <a class="action-link" href="/api-reference">API Reference</a>
                <a class="action-link" href="/cli-reference">CLI Reference</a>
            </div>
        </section>

        <div class="notice">
            This dashboard is read-only. It cannot create, mutate, authorize, or
            revoke trust. Signed treaties and revocation feeds remain the source
            of trust.
        </div>
    """
    return page_document("Genesis Mesh Sovereign Dashboard", "Dashboard", body)
