"""Read-only public HTTP app. No signing keys, admin APIs or writable DB handles."""

from datetime import datetime, timezone
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
import os
import re
import threading
import time

from flask import Flask, Response, abort, g, jsonify, request
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from genesis_mesh.na_service.operator_console.atlas import render_atlas
from genesis_mesh.na_service.operator_console.connectome import render_connectome
from genesis_mesh.na_service.operator_console.rendering import page_document
from genesis_mesh.trust import build_connectome_view
from .store import read_snapshot
from .view import NOTICE, dashboard, graph, render


def create_app(directory: Path, build: str = "unknown") -> Flask:
    app = Flask(__name__, static_folder=None)
    root_key = (directory / "root.pub").read_text(encoding="utf-8").strip()
    read_snapshot(directory / "public.db", root_key)
    software = {"version": version("genesis-mesh"), "build": build if re.fullmatch(r"[a-f0-9]{7,40}", build) else "unknown"}
    cache = {"mtime": None, "snapshot": None}
    lock = threading.Lock()
    # Bounded, per-process request budget. Nginx supplies the shared edge limit.
    budgets: dict[str, tuple[float, int]] = {}

    @app.before_request
    def public_boundary():
        if request.method not in {"GET", "HEAD"}:
            abort(405)
        now = time.monotonic()
        with lock:
            ip = request.remote_addr or "unknown"
            start, count = budgets.get(ip, (now, 0))
            if now - start >= 60:
                start, count = now, 0
            if len(budgets) >= 4096 and ip not in budgets:
                budgets.clear()
            budgets[ip] = (start, count + 1)
            if count >= 120:
                abort(429)
        if request.endpoint in {"asset", "favicon", "healthz"}:
            return None
        mtime = (directory / "public.db").stat().st_mtime_ns
        with lock:
            if mtime != cache["mtime"]:
                cache["snapshot"] = read_snapshot(directory / "public.db", root_key)
                cache["mtime"] = mtime
            g.snapshot = cache["snapshot"]
        return None

    @app.after_request
    def headers(response):
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "public, max-age=15, must-revalidate" if response.status_code == 200 else "no-store"
        if response.status_code == 429:
            response.headers["Retry-After"] = "60"
        return response

    @app.errorhandler(Exception)
    def safe_error(error):
        code = error.code if isinstance(error, HTTPException) else 503
        messages = {400: "Invalid public query", 404: "Public resource not found", 405: "This surface is read-only",
                    429: "Request limit reached", 503: "Public evidence is temporarily unavailable"}
        return jsonify({"error": messages.get(code, "Request could not be completed")}), code

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.get("/readyz")
    def readyz():
        return jsonify({"status": "ready", "storage": "SQLite"})

    @app.get("/")
    @app.get("/dashboard")
    @app.get("/dashboard.json")
    def home():
        try:
            model = dashboard(g.snapshot, request.args, software, datetime.now(timezone.utc))
        except (ValueError, TypeError):
            abort(400)
        if request.path.endswith(".json"):
            return jsonify(model)
        return Response(render(model, root_key), mimetype="text/html")

    @app.get("/genesis")
    def genesis():
        return jsonify(g.snapshot.genesis.model_dump(mode="json"))

    @app.get("/sovereign.json")
    def sovereign():
        block = g.snapshot.genesis
        return jsonify({"sovereign_id": block.network_name, "network_name": block.network_name,
                        "version": "v" + software["version"], "root_public_key": block.root_public_key,
                        "network_authority": block.network_authority.model_dump(mode="json"), "software": software})

    @app.get("/recognition-treaties")
    @app.get("/recognition-treaties/<record_id>")
    def treaties(record_id=None):
        records = g.snapshot.treaties
        if record_id:
            match = next((r for r in records if r.treaty.treaty_id == record_id), None)
            if match is None:
                abort(404)
            return jsonify(match.model_dump(mode="json"))
        # Same pagination as the dashboard; no unrestricted database enumeration.
        try:
            model = dashboard(g.snapshot, request.args, software, datetime.now(timezone.utc))
        except (ValueError, TypeError):
            abort(400)
        ids = {r["treaty_id"] for r in model["treaties"]}
        return jsonify({"treaties": [r.model_dump(mode="json") for r in records if r.treaty.treaty_id in ids], "pagination": model["pagination"]})

    @app.get("/sovereign-revocation-feed")
    @app.get("/feeds/<issuer>")
    def feed(issuer=None):
        value = g.snapshot.feeds.get(issuer or g.snapshot.genesis.network_name)
        if value is None:
            abort(404)
        return jsonify(value.model_dump(mode="json"))

    @app.get("/recognition-graph")
    @app.get("/atlas.json")
    @app.get("/connectome.json")
    @app.get("/atlas")
    @app.get("/connectome")
    def trust_views():
        value = graph(g.snapshot, datetime.now(timezone.utc))
        if request.path == "/atlas":
            return Response(render_atlas(value).replace('<main class="shell operator-console">', '<main class="shell operator-console"><p class="notice">'+NOTICE+'</p>'), mimetype="text/html")
        if request.path == "/connectome":
            return Response(render_connectome(build_connectome_view(value)).replace('<main class="shell operator-console">', '<main class="shell operator-console"><p class="notice">'+NOTICE+'</p>'), mimetype="text/html")
        return jsonify(build_connectome_view(value) if request.path == "/connectome.json" else value)

    @app.get("/evidence.json")
    def evidence():
        response = jsonify(g.snapshot.model_dump(mode="json"))
        response.headers["Content-Disposition"] = 'attachment; filename="evidence.json"'
        return response

    @app.get("/api-reference")
    @app.get("/cli-reference")
    def reference():
        body = f'<h1>Public reference surface</h1><p>{NOTICE}</p><p>Only GET and HEAD are available. Signing, maintenance, full audit exports and backups run locally.</p><ul>'
        for rule in sorted(app.url_map.iter_rules(), key=str):
            if '<' not in rule.rule:
                body += f'<li><a href="{rule.rule}">{rule.rule}</a></li>'
        body += '</ul><p>Offline verification: <code>python -m examples.public_dashboard.verify evidence.json --root-key &lt;pinned-root-key&gt;</code></p>'
        return Response(page_document("Public API reference", "API Docs", body), mimetype="text/html")

    @app.get("/operator-console-static/<name>")
    def asset(name):
        types = {"styles.css": "text/css", "console.js": "application/javascript", "logo.svg": "image/svg+xml", "favicon.svg": "image/svg+xml", "favicon.ico": "image/x-icon"}
        if name not in types:
            abort(404)
        resource = files("genesis_mesh.na_service.operator_console").joinpath("static", name)
        return Response(resource.read_bytes(), mimetype=types[name])

    @app.get("/favicon.svg")
    @app.get("/favicon.ico")
    def favicon():
        return asset(request.path.lstrip("/"))

    return app


def configured_app():
    app = create_app(Path(os.environ["PUBLIC_DEMO_DIR"]), os.environ.get("GENESIS_BUILD_SHA", "unknown"))
    # This entry point binds loopback behind the managed Nginx proxy only.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    return app
