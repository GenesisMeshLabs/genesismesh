"""Shared HTML chrome for Network Authority operator pages."""

from __future__ import annotations

from html import escape


def render_topbar(active: str) -> str:
    """Render shared operator-console top navigation."""
    items = [
        ("Console", "/"),
        ("Dashboard", "/dashboard"),
        ("Connectome", "/connectome"),
        ("API Docs", "/api-reference"),
        ("CLI Docs", "/cli-reference"),
        ("Operator Docs", "https://genesismesh.connectorzzz.com/operators/"),
    ]
    links = "\n".join(
        f'<a class="nav-link{" nav-link-active" if label == active else ""}" href="{href}">{label}</a>'
        for label, href in items
    )
    return f"""
        <nav class="topbar" aria-label="Operator navigation">
            <a class="brand" href="/" aria-label="Genesis Mesh console">
                <span class="brand-mark" aria-hidden="true">
                    <img src="/operator-console-static/logo.svg" alt="">
                </span>
                <span class="brand-text">
                    <strong>Genesis Mesh NA</strong>
                    <span>Operator surface</span>
                </span>
            </a>
            <div class="nav-links">{links}</div>
            <button class="theme-toggle" type="button" data-theme-toggle aria-label="Toggle dark and light mode" title="Toggle theme">
                <svg class="theme-icon theme-icon-dark" aria-hidden="true" viewBox="0 0 24 24">
                    <path d="M21 14.8A8.5 8.5 0 0 1 9.2 3a7 7 0 1 0 11.8 11.8Z"/>
                </svg>
                <svg class="theme-icon theme-icon-light" aria-hidden="true" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="4"/>
                    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>
                </svg>
            </button>
        </nav>
    """


def method_badge(method: str) -> str:
    """Render a method or CLI badge."""
    safe_method = escape(method)
    return f'<span class="method method-{safe_method.lower()}">{safe_method}</span>'
