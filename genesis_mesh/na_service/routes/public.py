"""Public read-only Network Authority routes."""

from datetime import datetime, timedelta, timezone
from html import escape

from flask import Blueprint, Response, jsonify, request

from .operator_ui import OPERATOR_CONSOLE_CSS

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
            _route_card("GET", "/health", "Health Summary", "Expanded service health summary.", clickable=True),
            _route_card("GET", "/healthz", "Liveness", "Process-level health probe.", clickable=True),
            _route_card("GET", "/readyz", "Readiness", "Database and migration readiness.", clickable=True),
            _route_card("GET", "/metrics", "Metrics", "Prometheus-compatible runtime metrics.", clickable=True),
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

    sovereign_routes = "\n".join(
        [
            _route_card(
                "GET",
                "/recognition-graph",
                "Recognition Graph",
                "Source graph for sovereign trust explanations.",
                clickable=True,
            ),
            _route_card(
                "GET",
                "/connectome",
                "Connectome",
                "Human-readable sovereign recognition and revocation view.",
                clickable=True,
            ),
            _route_card(
                "GET",
                "/connectome.json",
                "Connectome JSON",
                "Machine-readable Connectome summary.",
                clickable=True,
            ),
            _route_card(
                "GET",
                "/connectome/trust-path",
                "Trust Path",
                "Explain recognition between two sovereigns by query string.",
            ),
            _route_card(
                "GET",
                "/recognition-treaties",
                "Recognition Treaties",
                "List persisted sovereign recognition treaties.",
                clickable=True,
            ),
            _route_card(
                "GET",
                "/sovereign-revocation-feed",
                "Sovereign Revocation Feed",
                "Export revocations issued by a sovereign.",
                clickable=True,
            ),
            _route_card(
                "GET",
                "/recognition-policy",
                "Recognition Policy",
                "Current policy for portable trust acceptance.",
                clickable=True,
            ),
            _route_card(
                "GET",
                "/attestations",
                "Membership Attestations",
                "List issued portable membership attestations.",
                clickable=True,
            ),
        ],
    )

    node_routes = "\n".join(
        [
            _route_card("POST", "/join", "Join", "Issue a certificate from a single-use invite."),
            _route_card("POST", "/heartbeat", "Heartbeat", "Update authenticated node liveness."),
            _route_card("POST", "/renew", "Renew", "Renew a non-revoked node certificate."),
        ],
    )

    discovery_routes = "\n".join(
        [
            _route_card("GET", "/agents", "Agent Discovery", "List registered agent descriptors.", clickable=True),
            _route_card("POST", "/agents", "Register Agent", "Publish an authenticated agent descriptor."),
            _route_card("GET", "/agents/{node_public_key}", "Agent Lookup", "Read one agent descriptor."),
            _route_card("DELETE", "/agents/{node_public_key}", "Remove Agent", "Delete an authenticated descriptor."),
        ],
    )

    admin_routes = "\n".join(
        [
            _route_card("POST", "/admin/invite", "Invite", "Create a scoped enrollment token."),
            _route_card("POST", "/admin/revoke", "Revoke", "Publish a new signed CRL."),
            _route_card("POST", "/admin/policy", "Policy Publish", "Activate a signed policy version."),
            _route_card("GET", "/admin/policy/history", "Policy History", "Inspect persisted policy versions."),
            _route_card("POST", "/admin/policy/rollback", "Policy Rollback", "Reactivate a previous policy."),
            _route_card("POST", "/admin/attestations", "Issue Attestation", "Issue portable membership evidence."),
            _route_card(
                "POST",
                "/admin/attestations/{attestation_id}/revoke",
                "Revoke Attestation",
                "Publish sovereign-level attestation revocation.",
            ),
            _route_card(
                "POST",
                "/admin/recognition-policy",
                "Recognition Policy",
                "Set portable trust acceptance policy.",
            ),
            _route_card(
                "POST",
                "/admin/recognition-treaties",
                "Issue Treaty",
                "Create a direct-recognition treaty for another sovereign.",
            ),
            _route_card(
                "POST",
                "/admin/recognition-treaties/{treaty_id}/revoke",
                "Revoke Treaty",
                "End a persisted recognition treaty.",
            ),
            _route_card(
                "POST",
                "/admin/sovereign-revocation-feeds/import",
                "Import Revocation Feed",
                "Import revoked trust material from a recognized sovereign.",
            ),
        ],
    )

    managed_ops = "\n".join(
        [
            _route_card("CLI", "genesis-mesh managed backup", "Backup", "Create a consistent online NA DB backup."),
            _route_card("CLI", "genesis-mesh managed restore", "Restore", "Restore a validated backup while the NA is stopped."),
            _route_card("CLI", "genesis-mesh managed audit-export", "Audit Export", "Export redacted audit events."),
        ],
    )

    return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Genesis Mesh Network Authority</title>
    <style>
{OPERATOR_CONSOLE_CSS}
    </style>
</head>
<body>
    <main class="shell operator-console">
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
                <h2>Sovereign Trust Routes</h2>
                <p>Recognition, attestation, and revocation surfaces.</p>
            </div>
            <div class="route-grid">{sovereign_routes}</div>
        </section>

        <section>
            <div class="section-head">
                <h2>Node Routes</h2>
                <p>Used by enrolled nodes and protected by node proof-of-possession.</p>
            </div>
            <div class="route-grid">{node_routes}</div>
        </section>

        <section>
            <div class="section-head">
                <h2>Agent Discovery Routes</h2>
                <p>Advertise and inspect node-bound agent descriptors.</p>
            </div>
            <div class="route-grid">{discovery_routes}</div>
        </section>

        <section id="operator-endpoints">
            <div class="section-head">
                <h2>Operator Routes</h2>
                <p>Require operator signature headers and replay-protected nonces.</p>
            </div>
            <div class="route-grid">{admin_routes}</div>
        </section>

        <section>
            <div class="section-head">
                <h2>Managed Operations</h2>
                <p>CLI-only service operations; not browser-callable endpoints.</p>
            </div>
            <div class="route-grid">{managed_ops}</div>
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
