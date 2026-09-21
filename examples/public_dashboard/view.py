"""Public projections and server-rendered pagination using the shared visual shell."""

from datetime import datetime, timezone
from html import escape
from urllib.parse import urlencode
from typing import Any

from genesis_mesh.na_service.operator_console.rendering import page_document
from .records import Snapshot, current_issuers, freshness, sensitive_authorization_allowed

NOTICE = "Public reference instance — sanitized demo data, read-only; it cannot change trust state."
DEPLOYMENT = "Single-node public reference instance"


BADGES = {
    "healthy": "status-ok", "fresh": "status-ok", "verified": "status-ok", "ready": "status-ok",
    "warning": "status-watch",
    "degraded": "status-risk", "stale": "status-risk", "failed": "status-risk", "missing": "status-risk",
    # A check that has not run yet is neither a pass nor a warning.
    "not_observed": "status-idle",
}


def badge(state: str) -> str:
    """Render one status as a console status badge, in sentence case."""
    label = state.replace("_", " ")
    return f'<span class="status-badge {BADGES.get(state, "status-idle")}">{label[:1].upper() + label[1:]}</span>'


def lifecycle(record, now: datetime) -> str:
    t = record.treaty
    if t.status == "revoked":
        return "revoked"
    if record.retired or t.expires_at <= now or t.status != "active":
        return "historical"
    if (t.expires_at - now).total_seconds() <= 72 * 3600:
        return "expiring_soon"
    return "active"


def graph(snapshot: Snapshot, now: datetime) -> dict:
    edges = []
    for r in snapshot.treaties:
        t = r.treaty
        state = lifecycle(r, now)
        edges.append({"from": t.issuer_sovereign_id, "to": t.subject_sovereign_id,
            "treaty_id": t.treaty_id, "status": t.status, "lifecycle_state": state,
            "expiry_risk": "medium" if state == "expiring_soon" else "low" if state == "active" else "none",
            "valid_from": t.valid_from.isoformat(), "expires_at": t.expires_at.isoformat()})
    return {"sovereigns": [{"sovereign_id": name} for name in sorted(snapshot.authorities)],
        "recognition_edges": edges,
        "active_treaties": [r.treaty.model_dump(mode="json") for r in snapshot.treaties
                            if lifecycle(r, now) in {"active", "expiring_soon"}],
        "revoked_trust_material": [{"type": "recognition_treaty", "id": r.treaty.treaty_id,
                                   "lifecycle_state": "revoked", "reason": "demo-revocation", "revoked_at": None}
                                  for r in snapshot.treaties if r.treaty.status == "revoked"]}


def dashboard(snapshot: Snapshot, args, version: dict, now: datetime) -> dict:
    size = int(args.get("page_size", 10))
    page = int(args.get("page", 1))
    event_limit = int(args.get("events", 8))
    status = args.get("status", "all")
    sort = args.get("sort", "expiry")
    search = args.get("q", "").strip().lower()
    if size not in {10, 25, 50, 100} or not 1 <= page <= 100000 or not 8 <= event_limit <= 1000:
        raise ValueError("invalid_pagination")
    if status not in {"all", "active", "expiring_soon", "revoked", "historical"} or sort not in {"expiry", "creation"} or len(search) > 128:
        raise ValueError("invalid_filter")
    rows: list[dict[str, Any]] = []
    warnings = []
    for r in snapshot.treaties:
        t = r.treaty
        state = lifecycle(r, now)
        if r.expected_active and not r.retired and t.status == "active":
            if t.expires_at <= now:
                warnings.append(f"Expected active treaty {t.treaty_id} has expired; sensitive authorization is denied.")
            elif state == "expiring_soon":
                warnings.append(f"Treaty for {t.subject_sovereign_id} expires within 72 hours; renew it before expiry.")
        rows.append({"treaty_id": t.treaty_id, "issuer": t.issuer_sovereign_id,
            "authority": t.subject_sovereign_id, "lifecycle": state, "expected_active": r.expected_active,
            "created_at": t.issued_at.isoformat(), "expires_at": t.expires_at.isoformat(),
            "evidence_url": "/recognition-treaties/" + t.treaty_id,
            "feed_url": "/feeds/" + t.subject_sovereign_id})
    counts = {s: sum(r["lifecycle"] == s for r in rows) for s in ["active", "expiring_soon", "revoked", "historical"]}
    selected = [r for r in rows if (status == "all" or r["lifecycle"] == status)
                and (not search or search in r["authority"] or search in r["issuer"] or search in r["treaty_id"])]
    selected.sort(key=lambda r: r["expires_at"] if sort == "expiry" else r["created_at"])
    feeds = []
    for issuer in sorted(current_issuers(snapshot)):
        feed = snapshot.feeds.get(issuer)
        state = freshness(feed.issued_at if feed else None, now)
        feeds.append({"issuer": issuer, "sequence": feed.sequence if feed else None,
            "issued_at": feed.issued_at.isoformat() if feed else None,
            "imported_at": snapshot.imports[issuer].isoformat() if issuer in snapshot.imports else None,
            "freshness": state, "evidence_url": "/feeds/" + issuer})
        if state != "fresh":
            warnings.append(f"Feed for {issuer} is {state}: " +
                ("signed revocation information is over 72 hours old or missing; sensitive authorization is denied."
                 if state in {"stale", "missing"} else "signed revocation information is at least 24 hours old; check the hourly import job."))
    degraded = any(not sensitive_authorization_allowed(snapshot, issuer, now) for issuer in current_issuers(snapshot))
    stale_count = sum(f["freshness"] in {"stale", "missing"} for f in feeds)
    cycle = snapshot.canary
    cycle_freshness = freshness(cycle.completed_at, now) if cycle.status == "verified" else cycle.status
    return {"notice": NOTICE, "deployment": DEPLOYMENT, "storage": "SQLite",
        "last_updated": snapshot.updated_at.isoformat(), "evaluated_at": now.isoformat(),
        "sovereign": {"id": snapshot.genesis.network_name, "version": "v" + version["version"]},
        "software": version, "readiness": {"status": "ready", "storage": "SQLite"},
        "connectome_summary": {"sovereign_count": len(snapshot.authorities),
            "recognition_edge_count": len(snapshot.treaties),
            "active_edge_count": counts["active"] + counts["expiring_soon"],
            "revoked_trust_material_count": counts["revoked"]},
        "trust_posture": "degraded" if degraded else "warning" if warnings else "healthy",
        "trust_cycle_summary": {"status": cycle.status, "freshness": cycle_freshness,
                                "completed_at": cycle.completed_at.isoformat() if cycle.completed_at else None},
        "revocation_feed_summary": {"count": len(feeds), "stale_count": stale_count,
            "freshness": "stale" if stale_count else "warning" if any(f["freshness"] == "warning" for f in feeds) else "fresh"},
        "revocation_feeds": feeds, "treaty_summary": counts, "warnings": warnings,
        "treaties": selected[(page-1)*size:page*size],
        "pagination": {"page": page, "page_size": size, "total": len(selected),
                       "pages": max(1, (len(selected)+size-1)//size), "q": search, "status": status, "sort": sort},
        "recent_changes": [{**event.model_dump(mode="json"), "created_at": event.at.isoformat()}
                           for event in reversed(snapshot.events[-event_limit:])],
        "events_total": len(snapshot.events), "events_limit": event_limit}


def timestamp(value: str | None) -> str:
    if not value:
        return "Not observed"
    dt = datetime.fromisoformat(value)
    seconds = (datetime.now(timezone.utc)-dt).total_seconds()
    hours = int(abs(seconds)/3600)
    relative = f"{hours}h ago" if seconds >= 0 else f"in {hours}h"
    return f'<time datetime="{escape(value)}">{relative} · {dt.strftime("%Y-%m-%d %H:%M:%S UTC")}</time>'


def render(model: dict, root_key: str) -> str:
    p = model["pagination"]
    def options(values, current, label=lambda v: str(v).replace("_", " ").title()):
        return "".join(
            f'<option value="{v}"' + (" selected" if current == v else "") + f">{label(v)}</option>"
            for v in values
        )

    # Shared console control classes; a bare input/select inherits no theme styling.
    filters = f'''<form method="get" class="filter-form">
        <label class="filter-field">Search authority or record ID
            <input class="search-box" name="q" type="search" value="{escape(p['q'])}" maxlength="128"></label>
        <label class="filter-field">Lifecycle
            <select class="filter-select" name="status">{options(["all", "active", "expiring_soon", "revoked", "historical"], p["status"])}</select></label>
        <label class="filter-field">Records
            <select class="filter-select" name="page_size">{options([10, 25, 50, 100], p["page_size"])}</select></label>
        <label class="filter-field">Sort
            <select class="filter-select" name="sort">{options(["expiry", "creation"], p["sort"])}</select></label>
        <button class="filter-link filter-link-strong filter-apply" type="submit">Apply filters</button></form>'''
    rows = ''.join(f'''<tr><td><a href="{r['evidence_url']}">{escape(r['treaty_id'])}</a></td>
        <td>{escape(r['authority'])}</td><td>{r['lifecycle'].replace('_',' ').title()}</td>
        <td>{timestamp(r['created_at'])}</td><td>{timestamp(r['expires_at'])}</td>
        <td><a href="{r['feed_url']}">Signed feed</a> · <a href="/evidence.json">Evidence bundle</a></td></tr>''' for r in model['treaties'])
    feed_rows = ''.join(f'''<tr><td><a href="{f['evidence_url']}">{escape(f['issuer'])}</a></td>
        <td>{f['freshness'].title()}</td><td>{f['sequence']}</td><td>{timestamp(f['issued_at'])}</td>
        <td>{timestamp(f['imported_at'])}</td></tr>''' for f in model['revocation_feeds'])
    events = ''.join(f"<tr><td>{timestamp(e['at'])}</td><td>{escape(e['issuer'])}</td><td>{e['outcome'].title()}</td></tr>" for e in model['recent_changes'])
    warning_items = ''.join(f'<li>⚠ {escape(w)}</li>' for w in model['warnings'])
    warnings = f'<section><h2>Current warnings</h2><ul>{warning_items}</ul></section>' if warning_items else ''
    counts = ' · '.join(s.replace('_', ' ').title() + ': ' + str(n) for s, n in model['treaty_summary'].items())
    nav = ''
    for label, page in [('Previous', p['page']-1), ('Next', p['page']+1)]:
        if 1 <= page <= p['pages']:
            nav += f'<a class="action-link" href="?{escape(urlencode({**{k:p[k] for k in ["q","status","sort","page_size"]}, "page":page}))}">{label}</a> '
    more = ''
    if model['events_total'] > model['events_limit'] and model['events_limit'] < 1000:
        more = f'<a class="action-link" href="?{escape(urlencode({**{k:p[k] for k in ["q","status","sort","page_size","page"]}, "events":min(1000,model["events_limit"]+25)}))}#events">Load more</a>'
    command = f'python -m examples.public_dashboard.verify evidence.json --root-key {root_key}'
    # Hero follows the console pattern: heading, lead, stats, then a pill row of
    # metadata. Five stacked paragraphs pushed the actual status below the fold.
    meta = "".join(
        f'<span class="pill">{escape(text)}</span>'
        for text in [
            model["sovereign"]["id"],
            "Storage: SQLite",
            DEPLOYMENT,
            "Genesis Mesh " + model["sovereign"]["version"],
            "Build " + model["software"]["build"][:7],
        ]
    )
    body = f'''<div class="hero"><h1>Public Reference Trust Dashboard</h1>
        <p class="lead">{NOTICE}</p>
        <div class="stats stats-compact"><div class="stat"><span>Service readiness</span><strong>{badge('ready')}</strong></div>
        <div class="stat"><span>Trust posture</span><strong>{badge(model['trust_posture'])}</strong></div>
        <div class="stat"><span>Daily canary</span><strong>{badge(model['trust_cycle_summary']['freshness'])}</strong></div>
        <div class="stat"><span>Revocation feeds</span><strong>{model['revocation_feed_summary']['stale_count']} of {model['revocation_feed_summary']['count']} stale</strong></div>
        <div class="stat"><span>Treaties</span><strong>{model['treaty_summary']['active']} active</strong></div></div>
        <div class="pill-row">{meta}</div>
        <p class="filter-summary">Last updated: {timestamp(model['last_updated'])} · <a class="action-link" href="/dashboard">Refresh</a></p></div>
        {warnings}
        <section><h2>Treaties</h2>
        {filters}<p class="filter-summary">{p['total']} total results · Page {p['page']} of {p['pages']} · {counts}</p>
        <div class="table-wrap"><table class="data-table"><thead><tr><th>Record / evidence</th><th>Authority</th><th>Lifecycle</th><th>Created</th><th>Expiry</th><th>Related evidence</th></tr></thead>
        <tbody>{rows or '<tr><td colspan="6">No treaties match these filters.</td></tr>'}</tbody></table></div>{nav}
        <p>Historical and revoked treaties remain available for audit. Only expected active relationships affect current trust posture.</p></section>
        <section><h2>Revocation feeds</h2><p>Fresh: under 24 hours. Warning: 24–72 hours. Stale: over 72 hours. Age is measured from the signed issue time, not a repeated download.</p>
        <p class="filter-summary">Feed freshness checks imported revocation information. The daily canary checks cross-authority communication; last successful run: {timestamp(model['trust_cycle_summary']['completed_at'])}</p>
        <div class="table-wrap"><table class="data-table" data-paginate="10"><thead><tr><th>Issuer / signed feed</th><th>Freshness</th><th>Sequence</th><th>Signed heartbeat</th><th>Imported</th></tr></thead><tbody>{feed_rows}</tbody></table></div></section>
        <section id="events"><h2>Recent trust events</h2><table class="data-table" data-paginate="10"><thead><tr><th>UTC time</th><th>Issuer</th><th>Import result</th></tr></thead><tbody>{events or '<tr><td colspan="3">No import events yet.</td></tr>'}</tbody></table>{more}</section>
        <section><h2>Independent verification</h2><p><a class="action-link" href="/evidence.json" download="evidence.json">Download sanitized evidence bundle</a></p>
        <p>From this release checkout with dependencies installed, run offline:</p><pre><code>{escape(command)}</code></pre>
        <p>Pin the root key through a separately trusted channel. Verification proves signatures and integrity; it does not prove independent operation of the demo authorities: this single-node reference uses separately signed demo authorities on the same host.</p></section>'''
    return page_document("Genesis Mesh Public Reference Dashboard", "Dashboard", body)
