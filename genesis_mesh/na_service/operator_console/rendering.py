"""Server-rendered operator console pages."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

from .chrome import method_badge, render_topbar
from .surfaces import (
    ALL_SURFACES,
    CLI_SURFACES,
    HTTP_SURFACES,
    Surface,
    browser_safe_count,
    surfaces_by_group,
)

ACTIVE_NODE_WINDOW = timedelta(minutes=5)


def node_counts(service) -> tuple[int, int]:
    """Return counts for recently seen and tracked non-revoked nodes."""
    now = datetime.now(timezone.utc)
    active = 0
    tracked = 0

    for node in service.db.list_issued_certs():
        if node.get("status") == "revoked":
            continue

        tracked += 1
        last_seen = node.get("last_heartbeat")
        if not last_seen:
            continue

        try:
            seen_at = datetime.fromisoformat(last_seen)
        except ValueError:
            continue

        if now - seen_at < ACTIVE_NODE_WINDOW:
            active += 1

    return active, tracked


def _surface_summary() -> dict[str, int]:
    """Return a small protocol-surface summary for the console hero."""
    return {
        "http_surface_count": len(HTTP_SURFACES),
        "cli_workflow_count": len(CLI_SURFACES),
        "browser_safe_count": browser_safe_count(),
    }


def _surface_target(surface: Surface) -> str:
    """Render a path, command, or linked safe HTTP surface."""
    target = escape(surface.target)
    if surface.clickable:
        return f'<a class="path" href="{target}">{target}</a>'
    return f'<code class="path">{target}</code>'


def render_surface_table(surfaces: list[Surface]) -> str:
    """Render compact rows for HTTP or CLI surfaces."""
    rows = "\n".join(
        f"""
        <tr>
            <td>{method_badge(surface.method)}</td>
            <td>{_surface_target(surface)}</td>
            <td><strong>{escape(surface.title)}</strong></td>
            <td>
                {escape(surface.purpose)}
                {f'<br><span class="muted">{escape(surface.query_hint)}</span>' if surface.query_hint else ''}
            </td>
            <td><span class="muted">{escape(surface.auth_hint)}</span></td>
        </tr>
        """
        for surface in surfaces
    )
    return f"""
        <table class="data-table compact-table">
            <thead>
                <tr>
                    <th>Method</th>
                    <th>Path / command</th>
                    <th>Surface</th>
                    <th>Purpose</th>
                    <th>Access</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
    """


def _search_toolbar(input_id: str, label: str, scope_id: str, target_selector: str, placeholder: str) -> str:
    """Render a client-side search input for generated reference pages."""
    safe_input_id = escape(input_id)
    safe_scope_id = escape(scope_id)
    return f"""
        <div class="reference-toolbar">
            <label class="sr-only" for="{safe_input_id}">{escape(label)}</label>
            <input
                id="{safe_input_id}"
                class="search-box"
                type="search"
                placeholder="{escape(placeholder)}"
                data-search-input
                data-search-scope="#{safe_scope_id}"
                data-search-target="{escape(target_selector)}"
                data-search-empty="#{safe_scope_id}-empty"
            >
        </div>
    """


def page_document(title: str, active_nav: str, body: str) -> str:
    """Wrap page body in shared document chrome."""
    return f"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(title)}</title>
    <link rel="icon" href="/favicon.svg" type="image/svg+xml">
    <link rel="alternate icon" href="/favicon.ico">
    <link rel="stylesheet" href="/operator-console-static/styles.css">
    <script src="/operator-console-static/console.js" defer></script>
</head>
<body>
    <main class="shell operator-console">
        {render_topbar(active_nav)}
        {body}
    </main>
    <button class="back-to-top" type="button" data-back-to-top aria-label="Back to top" title="Back to top">
        <svg aria-hidden="true" viewBox="0 0 24 24">
            <path d="m6 15 6-6 6 6"/>
        </svg>
    </button>
</body>
</html>"""


def render_homepage(service) -> str:
    """Build the human-facing Network Authority home page."""
    genesis = service.genesis_block
    surface_summary = _surface_summary()

    safe_rows = render_surface_table(surfaces_by_group("safe", curated_only=True))
    node_rows = render_surface_table(surfaces_by_group("node_agent", curated_only=True))
    operator_rows = render_surface_table(surfaces_by_group("operator", curated_only=True))
    managed_rows = render_surface_table(surfaces_by_group("managed", curated_only=True))

    body = f"""
        <div class="hero">
            <h1>Genesis Mesh Network Authority</h1>
            <p class="lead">
                Every Network Authority surface in one compact map: open a safe
                GET, sign an operator command, or run a managed CLI operation.
            </p>
            <div class="stats" aria-label="Network summary">
                <div class="stat"><span>Network</span><strong>{escape(genesis.network_name)}</strong></div>
                <div class="stat"><span>Version</span><strong>{escape(genesis.network_version)}</strong></div>
                <div class="stat"><span>Health</span><strong>Ready</strong></div>
                <div class="stat"><span>HTTP Surfaces</span><strong>{surface_summary["http_surface_count"]}</strong></div>
                <div class="stat"><span>CLI Workflows</span><strong>{surface_summary["cli_workflow_count"]}</strong></div>
                <div class="stat"><span>Browser-safe</span><strong>{surface_summary["browser_safe_count"]}</strong></div>
            </div>
            <div class="pill-row">
                <span class="pill">Surface map</span>
                <span class="pill">Read-only console</span>
                <span class="pill">Signed actions documented only</span>
            </div>
        </div>

        <div class="filter-bar" aria-label="Surface filters">
            <div class="filter-links">
                <button class="filter-link filter-link-strong" type="button" data-surface-filter="all">All surfaces</button>
                <button class="filter-link" type="button" data-surface-filter="safe">Safe GET</button>
                <button class="filter-link" type="button" data-surface-filter="signed">Signed</button>
                <button class="filter-link" type="button" data-surface-filter="cli">CLI</button>
            </div>
            <div class="filter-summary">{len(ALL_SURFACES)} surfaces - {browser_safe_count()} browser-safe</div>
        </div>

        <section id="safe-browser-links" data-surface-section="safe">
            <div class="section-head">
                <h2>Safe Browser Links</h2>
                <p>Representative safe GET surfaces. <a href="/api-reference">View all API routes</a>.</p>
            </div>
            {safe_rows}
        </section>

        <section id="node-agent-runtime" data-surface-section="signed">
            <div class="section-head">
                <h2>Node and Agent Runtime</h2>
                <p>Signed node proof-of-possession surfaces.</p>
            </div>
            {node_rows}
        </section>

        <section id="operator-endpoints" data-surface-section="signed">
            <div class="section-head">
                <h2>Operator Commands</h2>
                <p>Signed HTTP clients or CLI commands, not browser actions.</p>
            </div>
            {operator_rows}
        </section>

        <section id="managed-operations" data-surface-section="cli">
            <div class="section-head">
                <h2>Managed Operations</h2>
                <p>CLI-only service workflows. <a href="/cli-reference">View all CLI commands</a>.</p>
            </div>
            {managed_rows}
        </section>

        <div class="notice">
            This console is read-only. Browser-clickable means safe GET. Signed
            POST/admin operations and CLI-only workflows are documented here,
            not executed here.
        </div>
        <div class="footer">
            Genesis Mesh separates the Network Authority HTTP API from peer
            WebSocket runtime ports. Raw JSON and generated references remain
            available for automation.
        </div>
    """
    return page_document("Genesis Mesh Network Authority", "Console", body)


def render_api_reference(service) -> str:
    """Render a read-only API reference page."""
    body = f"""
        <div class="hero">
            <h1>Network Authority API</h1>
            <p class="lead">
                Generated HTTP surface reference for {escape(service.genesis_block.network_name)}.
                This page intentionally has no try-it or request execution controls.
                Use <a href="/swagger.json">/swagger.json</a> for automation.
            </p>
        </div>
        {_search_toolbar("api-search", "Search API routes", "api-reference-results", "tbody tr", "Search path, method, purpose, or access")}
        <section>
            <div class="section-head">
                <h2>HTTP Surfaces</h2>
                <p>Signed POST routes require operator or node signing outside the browser.</p>
            </div>
            <div id="api-reference-results">
                {render_surface_table(list(HTTP_SURFACES))}
            </div>
            <div id="api-reference-results-empty" class="search-empty">No API surfaces match the current search.</div>
        </section>
        <div class="notice">
            No browser request builder is provided. POST/admin routes are
            documented here, but must be executed by the CLI or a signed HTTP client.
        </div>
    """
    return page_document("Genesis Mesh API Reference", "API Docs", body)


def _click_options_summary(command: Any) -> str:
    """Return a compact summary of visible Click options for one command."""
    try:
        import click
    except Exception:
        return '<span class="muted">None</span>'

    options = []
    for param in command.params:
        if not isinstance(param, click.Option) or param.hidden:
            continue
        flags = ", ".join(param.opts + param.secondary_opts)
        default = "" if param.default is None else str(param.default)
        default_text = f' <span class="muted">default: {escape(default)}</span>' if default else ""
        help_text = f' - {escape(param.help)}' if param.help else ""
        options.append(f"<li><code>{escape(flags)}</code>{help_text}{default_text}</li>")
    if not options:
        return '<span class="muted">None</span>'
    return f'<ul class="option-list">{"".join(options)}</ul>'


def _render_click_command_table(command_entries: list[tuple[str, Any]]) -> str:
    """Render generated Click command metadata as a single searchable table."""
    rows = []
    for command_name, command in command_entries:
        if command_name == "genesis-mesh":
            continue
        help_text = command.help or command.short_help or ""
        rows.append(
            f"""
            <tr>
                <td><code class="path">{escape(command_name)}</code></td>
                <td>{escape(help_text.splitlines()[0] if help_text else "Command group")}</td>
                <td>{_click_options_summary(command)}</td>
            </tr>
            """
        )
    return f"""
        <table class="data-table cli-reference-table">
            <thead>
                <tr>
                    <th>Command</th>
                    <th>Description</th>
                    <th>Options</th>
                </tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
    """


def _walk_click_commands(command: Any, prefix: list[str]) -> list[tuple[str, Any]]:
    """Return Click command tree entries."""
    entries = [(" ".join(prefix), command)]
    commands = getattr(command, "commands", {})
    for name, child in sorted(commands.items()):
        entries.extend(_walk_click_commands(child, [*prefix, name]))
    return entries


def render_cli_reference() -> str:
    """Render generated CLI command reference from Click metadata."""
    from ...cli.main import cli

    command_table = _render_click_command_table(_walk_click_commands(cli, ["genesis-mesh"]))

    body = f"""
        <div class="hero">
            <h1>Genesis Mesh CLI</h1>
            <p class="lead">
                Command and option reference generated from the Click command
                tree. Workflow examples remain curated in the documentation.
            </p>
        </div>
        {_search_toolbar("cli-search", "Search CLI commands", "cli-reference-results", "tbody tr", "Search command, option, description, or default")}
        <div id="cli-reference-results">
            <section>
                <div class="section-head">
                    <h2>Command Reference</h2>
                    <p>
                        Generated command and option metadata. Managed operations
                        are listed here from the same Click command tree.
                    </p>
                </div>
                {command_table}
            </section>
        </div>
        <div id="cli-reference-results-empty" class="search-empty">No CLI commands match the current search.</div>
    """
    return page_document("Genesis Mesh CLI Reference", "CLI Docs", body)
