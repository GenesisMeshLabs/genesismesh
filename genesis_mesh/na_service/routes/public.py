"""Public read-only Network Authority routes."""

from datetime import datetime, timedelta, timezone
from html import escape

from flask import Blueprint, Response, jsonify, request

ACTIVE_NODE_WINDOW = timedelta(minutes=5)


def _node_counts(service) -> tuple[int, int]:
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


def _public_base_url() -> str:
    """Return the externally visible base URL, honoring common proxy headers."""
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme).split(",", 1)[0].strip()
    host = request.headers.get("X-Forwarded-Host", request.host).split(",", 1)[0].strip()
    return f"{scheme}://{host}".rstrip("/")


def _route_card(
    method: str,
    path: str,
    title: str,
    description: str,
    *,
    clickable: bool = False,
) -> str:
    """Render a single route link for the Network Authority landing page."""
    safe_path = escape(path)
    safe_title = escape(title)
    safe_description = escape(description)
    safe_method = escape(method)
    inner = f"""
            <span class="method">{safe_method}</span>
            <span class="path">{safe_path}</span>
            <strong>{safe_title}</strong>
            <span>{safe_description}</span>
    """
    if clickable:
        href = safe_path
        return f"""
        <a class="route-card" href="{href}" aria-label="{safe_method} {safe_path}">
{inner}
        </a>
    """
    return f"""
        <div class="route-card route-card-static" aria-label="{safe_method} {safe_path}">
{inner}
        </div>
    """


def _homepage_html(service) -> str:
    """Build the human-facing Network Authority home page."""
    genesis = service.genesis_block
    network_name = escape(genesis.network_name)
    network_version = escape(genesis.network_version)
    active_nodes, registered_nodes = _node_counts(service)

    public_routes = "\n".join(
        [
            _route_card("GET", "/healthz", "Liveness", "Process-level health probe.", clickable=True),
            _route_card("GET", "/readyz", "Readiness", "Database and migration readiness.", clickable=True),
            _route_card(
                "GET",
                "/sovereign.json",
                "Sovereign Metadata",
                "Operator-safe public trust material.",
                clickable=True,
            ),
            _route_card("GET", "/genesis", "Genesis", "Signed network trust root.", clickable=True),
            _route_card("GET", "/policy", "Policy", "Active DB-backed policy manifest.", clickable=True),
            _route_card(
                "GET",
                "/crl",
                "Revocation List",
                "Current signed certificate revocation list.",
                clickable=True,
            ),
            _route_card("GET", "/nodes", "Nodes", "Recently active node inventory.", clickable=True),
        ],
    )

    node_routes = "\n".join(
        [
            _route_card("POST", "/join", "Join", "Issue a certificate from a single-use invite."),
            _route_card("POST", "/heartbeat", "Heartbeat", "Update authenticated node liveness."),
            _route_card("POST", "/renew", "Renew", "Renew a non-revoked node certificate."),
        ],
    )

    admin_routes = "\n".join(
        [
            _route_card("POST", "/admin/invite", "Invite", "Create a scoped enrollment token."),
            _route_card("POST", "/admin/revoke", "Revoke", "Publish a new signed CRL."),
            _route_card("POST", "/admin/policy", "Policy Publish", "Activate a signed policy version."),
            _route_card("GET", "/admin/policy/history", "Policy History", "Inspect persisted policy versions."),
            _route_card("POST", "/admin/policy/rollback", "Policy Rollback", "Reactivate a previous policy."),
        ],
    )

    return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Genesis Mesh Network Authority</title>
    <style>
        :root {{
            color-scheme: dark;
            --bg: #0b0f14;
            --panel: #121922;
            --panel-strong: #17212d;
            --line: #2a3646;
            --text: #e7edf5;
            --muted: #9fb0c3;
            --accent: #6ee7b7;
            --accent-2: #7dd3fc;
            --warn: #facc15;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.5;
        }}
        a {{ color: inherit; }}
        .shell {{
            width: min(1160px, calc(100% - 32px));
            margin: 0 auto;
            padding: 44px 0 56px;
        }}
        .hero {{
            border: 1px solid var(--line);
            border-radius: 8px;
            background: linear-gradient(135deg, #111923 0%, #0e151d 58%, #13211d 100%);
            padding: clamp(24px, 5vw, 44px);
        }}
        .kicker {{
            display: inline-flex;
            gap: 8px;
            align-items: center;
            color: var(--accent);
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0;
            text-transform: uppercase;
        }}
        .status-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--accent);
            box-shadow: 0 0 18px rgba(110, 231, 183, 0.85);
        }}
        h1 {{
            margin: 16px 0 12px;
            max-width: 780px;
            font-size: clamp(2.1rem, 6vw, 4.3rem);
            line-height: 1.04;
            letter-spacing: 0;
        }}
        .lead {{
            max-width: 760px;
            margin: 0;
            color: var(--muted);
            font-size: 1.05rem;
        }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            margin-top: 28px;
        }}
        .stat {{
            border: 1px solid var(--line);
            border-radius: 8px;
            background: rgba(18, 25, 34, 0.72);
            padding: 16px;
        }}
        .stat span {{
            display: block;
            color: var(--muted);
            font-size: 0.82rem;
        }}
        .stat strong {{
            display: block;
            margin-top: 4px;
            font-size: 1.2rem;
        }}
        section {{ margin-top: 28px; }}
        .section-head {{
            display: flex;
            justify-content: space-between;
            gap: 18px;
            align-items: end;
            margin-bottom: 12px;
        }}
        .section-head h2 {{
            margin: 0;
            font-size: 1.05rem;
            letter-spacing: 0;
        }}
        .section-head p {{
            margin: 0;
            color: var(--muted);
            font-size: 0.92rem;
        }}
        .route-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(235px, 1fr));
            gap: 12px;
        }}
        .route-card {{
            min-height: 150px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            padding: 17px;
            text-decoration: none;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: var(--panel);
            transition: border-color 140ms ease, background 140ms ease, transform 140ms ease;
        }}
        a.route-card:hover {{
            border-color: var(--accent-2);
            background: var(--panel-strong);
            transform: translateY(-1px);
        }}
        .route-card-static {{
            cursor: default;
        }}
        .method {{
            width: fit-content;
            border: 1px solid rgba(125, 211, 252, 0.35);
            border-radius: 999px;
            padding: 2px 8px;
            color: var(--accent-2);
            font-size: 0.72rem;
            font-weight: 800;
        }}
        .path {{
            color: var(--text);
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
            font-size: 0.92rem;
        }}
        .route-card strong {{ font-size: 1rem; }}
        .route-card span:last-child {{
            color: var(--muted);
            font-size: 0.9rem;
        }}
        .notice {{
            margin-top: 28px;
            border: 1px solid rgba(250, 204, 21, 0.36);
            border-radius: 8px;
            background: rgba(250, 204, 21, 0.08);
            padding: 16px;
            color: #f8eaa3;
        }}
        .footer {{
            margin-top: 28px;
            color: var(--muted);
            font-size: 0.9rem;
        }}
        @media (max-width: 720px) {{
            .shell {{ width: min(100% - 24px, 1160px); padding-top: 24px; }}
            .section-head {{ display: block; }}
            .section-head p {{ margin-top: 4px; }}
        }}
    </style>
</head>
<body>
    <main class="shell">
        <div class="hero">
            <div class="kicker"><span class="status-dot"></span> Network Authority online</div>
            <h1>Genesis Mesh Network Authority</h1>
            <p class="lead">
                Operator control plane for invite enrollment, certificate issuance,
                revocation, policy distribution, and production health checks.
            </p>
            <div class="stats" aria-label="Network summary">
                <div class="stat"><span>Network</span><strong>{network_name}</strong></div>
                <div class="stat"><span>Version</span><strong>{network_version}</strong></div>
                <div class="stat"><span>Active Nodes</span><strong>{active_nodes}</strong></div>
                <div class="stat"><span>Tracked Nodes</span><strong>{registered_nodes}</strong></div>
            </div>
        </div>

        <section>
            <div class="section-head">
                <h2>Public And Health Routes</h2>
                <p>Safe to open from a browser or monitoring probe.</p>
            </div>
            <div class="route-grid">{public_routes}</div>
        </section>

        <section>
            <div class="section-head">
                <h2>Node Routes</h2>
                <p>Used by enrolled nodes and protected by node proof-of-possession.</p>
            </div>
            <div class="route-grid">{node_routes}</div>
        </section>

        <section id="operator-endpoints">
            <div class="section-head">
                <h2>Operator Routes</h2>
                <p>Require operator signature headers and replay-protected nonces.</p>
            </div>
            <div class="route-grid">{admin_routes}</div>
        </section>

        <div class="notice">
            This page is a human-readable console only. Use the `genesis-mesh`
            CLI or signed HTTP clients for operator and node write operations.
        </div>
        <div class="footer">
            Genesis Mesh separates the Network Authority HTTP API from peer
            WebSocket runtime ports. Browser access belongs here, not on peer
            transport sockets.
        </div>
    </main>
</body>
</html>"""


def create_public_blueprint(service) -> Blueprint:
    """Create public metadata routes for genesis and policy documents."""
    bp = Blueprint("na_public", __name__)

    @bp.route("/", methods=["GET"])
    def home():
        """Return the human-facing Network Authority landing page."""
        return Response(_homepage_html(service), mimetype="text/html")

    @bp.route("/genesis", methods=["GET"])
    def get_genesis():
        """Return the genesis block."""
        return jsonify(service.genesis_block.model_dump(mode="json"))

    @bp.route("/sovereign.json", methods=["GET"])
    def sovereign_metadata():
        """Return operator-safe public metadata for this sovereign."""
        genesis = service.genesis_block
        base_url = _public_base_url()
        return jsonify({
            "sovereign_id": genesis.network_name,
            "network_name": genesis.network_name,
            "network_version": genesis.network_version,
            "endpoint": base_url,
            "network_authority": {
                "public_key": genesis.network_authority.public_key,
                "valid_from": genesis.network_authority.valid_from.isoformat(),
                "valid_to": genesis.network_authority.valid_to.isoformat(),
            },
            "root_public_key": genesis.root_public_key,
            "policy_manifest": genesis.policy_manifest.model_dump(mode="json"),
            "bootstrap_anchor_count": len(genesis.bootstrap_anchors),
            "supported_surfaces": {
                "genesis": f"{base_url}/genesis",
                "recognition_treaties": f"{base_url}/recognition-treaties",
                "sovereign_revocation_feed": f"{base_url}/sovereign-revocation-feed",
                "connectome": f"{base_url}/connectome.json",
            },
        })

    @bp.route("/policy", methods=["GET"])
    def get_policy():
        """Return the active signed policy manifest."""
        policy = service.db.get_active_policy()
        if policy is None:
            policy = service._get_default_policy()
            service.db.save_policy(policy, active=True)
        return jsonify(policy.model_dump(mode="json"))

    return bp
