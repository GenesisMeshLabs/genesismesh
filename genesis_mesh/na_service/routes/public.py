"""Public read-only Network Authority routes."""

from __future__ import annotations

from importlib.resources import files

from flask import Blueprint, Response, abort, jsonify, request

from ..operator_console.dashboard import build_dashboard_model, render_dashboard
from ..operator_console.openapi import build_swagger_spec
from ..operator_console.rendering import (
    render_api_reference,
    render_cli_reference,
    render_homepage,
)


def _public_base_url() -> str:
    """Return the externally visible base URL, honoring common proxy headers."""
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme).split(",", 1)[0].strip()
    host = request.headers.get("X-Forwarded-Host", request.host).split(",", 1)[0].strip()
    return f"{scheme}://{host}".rstrip("/")


def create_public_blueprint(service) -> Blueprint:
    """Create public metadata routes for genesis and policy documents."""
    bp = Blueprint("na_public", __name__)

    def operator_console_asset(name: str, mimetype: str) -> Response:
        """Return a packaged operator-console asset by exact filename."""
        allowed_assets = {"console.js", "favicon.ico", "favicon.svg", "logo.svg", "styles.css"}
        if name not in allowed_assets:
            abort(404)
        asset = files("genesis_mesh.na_service.operator_console").joinpath("static", name)
        if not asset.is_file():
            abort(404)
        return Response(asset.read_bytes(), mimetype=mimetype)

    @bp.route("/favicon.svg", methods=["GET"])
    def favicon_svg():
        """Return the SVG favicon used by browser tabs and bookmarks."""
        return operator_console_asset("favicon.svg", "image/svg+xml")

    @bp.route("/favicon.ico", methods=["GET"])
    def favicon_ico():
        """Return the ICO favicon fallback."""
        return operator_console_asset("favicon.ico", "image/x-icon")

    @bp.route("/operator-console-static/logo.svg", methods=["GET"])
    def operator_console_logo():
        """Return the operator-console logo asset."""
        return operator_console_asset("logo.svg", "image/svg+xml")

    @bp.route("/operator-console-static/styles.css", methods=["GET"])
    def operator_console_styles():
        """Return the operator-console shared stylesheet."""
        return operator_console_asset("styles.css", "text/css")

    @bp.route("/operator-console-static/console.js", methods=["GET"])
    def operator_console_script():
        """Return the operator-console shared browser behavior."""
        return operator_console_asset("console.js", "application/javascript")

    @bp.route("/", methods=["GET"])
    def home():
        """Return the human-facing Network Authority landing page."""
        return Response(render_homepage(service), mimetype="text/html")

    @bp.route("/dashboard", methods=["GET"])
    def dashboard():
        """Return the read-only sovereign health and trust dashboard."""
        return Response(render_dashboard(service), mimetype="text/html")

    @bp.route("/dashboard.json", methods=["GET"])
    def dashboard_json():
        """Return machine-readable dashboard state."""
        return jsonify(build_dashboard_model(service))

    @bp.route("/swagger.json", methods=["GET"])
    def swagger_json():
        """Return generated OpenAPI-compatible metadata."""
        return jsonify(build_swagger_spec(service, _public_base_url()))

    @bp.route("/api-reference", methods=["GET"])
    def api_reference():
        """Return a read-only generated API reference page."""
        return Response(render_api_reference(service), mimetype="text/html")

    @bp.route("/cli-reference", methods=["GET"])
    def cli_reference():
        """Return a generated CLI reference page."""
        return Response(render_cli_reference(), mimetype="text/html")

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
                "swagger": f"{base_url}/swagger.json",
                "api_reference": f"{base_url}/api-reference",
                "cli_reference": f"{base_url}/cli-reference",
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
