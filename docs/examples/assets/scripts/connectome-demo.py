"""Run a local Connectome visualization smoke demo.

The demo creates two in-process sovereign Network Authorities, issues a direct
recognition treaty, imports a signed cross-sovereign revocation feed, and
renders the operator Connectome summary as static and animated documentation
assets.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import textwrap
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nacl.encoding
import nacl.signing

from genesis_mesh.crypto import KeyPair, generate_keypair, sign_data
from genesis_mesh.models import GenesisBlock, NetworkAuthority, PolicyManifestRef
from genesis_mesh.na_service.server import NetworkAuthorityService

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_GIF_OUTPUT = ROOT / "docs/examples/assets/images/genesis-mesh-connectome.gif"
DEFAULT_PNG_OUTPUT = ROOT / "docs/examples/assets/images/genesis-mesh-connectome.png"


def _admin_headers(body: dict, operator_keypair: KeyPair, key_id: str) -> dict:
    """Create operator-auth headers for an admin request body."""
    timestamp = datetime.now(timezone.utc).isoformat()
    nonce = str(uuid.uuid4())
    canonical = json.dumps(
        {"body": body, "key_id": key_id, "timestamp": timestamp, "nonce": nonce},
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "X-Admin-Key-Id": key_id,
        "X-Admin-Timestamp": timestamp,
        "X-Admin-Nonce": nonce,
        "X-Admin-Signature": sign_data(
            canonical.encode("utf-8"),
            operator_keypair.private_key,
        ),
    }


def _new_sovereign(name: str, db_path: Path) -> tuple[NetworkAuthorityService, KeyPair]:
    """Create an isolated Network Authority for a sovereign trust domain."""
    na_key = nacl.signing.SigningKey.generate()
    operator_keypair = generate_keypair()
    na_public_key = na_key.verify_key.encode(
        encoder=nacl.encoding.Base64Encoder,
    ).decode("utf-8")
    now = datetime.now(timezone.utc)
    genesis = GenesisBlock(
        network_name=name,
        network_version="v0.12-demo",
        root_public_key=na_public_key,
        network_authority=NetworkAuthority(
            public_key=na_public_key,
            valid_from=now,
            valid_to=now + timedelta(days=90),
        ),
        policy_manifest=PolicyManifestRef(hash="sha256:demo", url=None),
    )
    service = NetworkAuthorityService(
        genesis_block=genesis,
        na_private_key=na_key,
        key_id=f"{name}-na-key",
        db_path=str(db_path),
        operator_public_keys={f"{name}-operator": operator_keypair.public_key_b64},
    )
    service.app.config["TESTING"] = True
    return service, operator_keypair


def _post_admin(client, path: str, body: dict, operator: KeyPair, key_id: str):
    """Post an operator-authenticated admin request."""
    return client.post(path, json=body, headers=_admin_headers(body, operator, key_id))


def _require_status(response, expected: int, label: str) -> dict:
    """Return JSON response data or raise a compact demo error."""
    data = response.get_json()
    if response.status_code != expected:
        raise RuntimeError(f"{label} failed: {response.status_code} {data}")
    return data


def _seed_connectome(
    tmp_path: Path,
) -> tuple[NetworkAuthorityService, NetworkAuthorityService, list[str]]:
    """Create two sovereigns and seed Connectome treaty and revocation data."""
    lines: list[str] = []

    def emit(line: str = "") -> None:
        lines.append(line)
        print(line)

    sovereign_a, operator_a = _new_sovereign("sovereign-a", tmp_path / "a.db")
    sovereign_b, operator_b = _new_sovereign("sovereign-b", tmp_path / "b.db")
    client_a = sovereign_a.app.test_client()
    client_b = sovereign_b.app.test_client()

    emit("==> Sovereign Connectome demo")
    emit("    sovereign-a observes recognition and imported revocation state")
    emit("    sovereign-b issues and revokes one membership attestation")

    attestation_body = {
        "issuer_sovereign_id": "sovereign-b",
        "subject_id": "alice",
        "subject_public_key": "alice-public-key",
        "roles": ["role:service:maintainer"],
        "claims": {"project": "connectome-demo"},
        "validity_hours": 24,
    }
    attestation = _require_status(
        _post_admin(
            client_b,
            "/admin/attestations",
            attestation_body,
            operator_b,
            "sovereign-b-operator",
        ),
        201,
        "attestation issue",
    )
    treaty_body = {
        "issuer_sovereign_id": "sovereign-a",
        "subject_sovereign_id": "sovereign-b",
        "subject_public_keys": [
            sovereign_b.genesis_block.network_authority.public_key,
        ],
        "scope": {
            "allowed_roles": ["role:service:maintainer"],
            "accepted_statuses": ["active"],
            "claims": {"purpose": "connectome demo"},
        },
        "validity_hours": 24,
        "metadata": {"demo": "connectome"},
    }
    treaty = _require_status(
        _post_admin(
            client_a,
            "/admin/recognition-treaties",
            treaty_body,
            operator_a,
            "sovereign-a-operator",
        ),
        201,
        "treaty issue",
    )
    emit()
    emit("==> Direct recognition treaty created")
    emit("    from: sovereign-a")
    emit("    to:   sovereign-b")
    emit(f"    id:   {treaty['treaty_id']}")

    revoke_body = {"reason": "key_compromise"}
    _require_status(
        _post_admin(
            client_b,
            f"/admin/attestations/{attestation['attestation_id']}/revoke",
            revoke_body,
            operator_b,
            "sovereign-b-operator",
        ),
        200,
        "attestation revoke",
    )
    feed = _require_status(
        client_b.get("/sovereign-revocation-feed?issuer_sovereign_id=sovereign-b"),
        200,
        "revocation feed",
    )
    import_body = {"feed": feed}
    _require_status(
        _post_admin(
            client_a,
            "/admin/sovereign-revocation-feeds/import",
            import_body,
            operator_a,
            "sovereign-a-operator",
        ),
        200,
        "feed import",
    )
    emit()
    emit("==> Sovereign B revocation feed imported by Sovereign A")
    emit(f"    feed sequence: {feed['sequence']}")
    emit(f"    revoked attestations: {len(feed['revoked_attestation_ids'])}")

    connectome = _require_status(
        client_a.get("/connectome.json"),
        200,
        "connectome json",
    )
    summary = connectome["summary"]
    emit()
    emit("==> Connectome summary")
    emit(f"    sovereigns:              {summary['sovereign_count']}")
    emit(f"    recognition edges:       {summary['recognition_edge_count']}")
    emit(f"    active edges:            {summary['active_edge_count']}")
    emit(f"    imported revocations:    {summary['imported_revocation_count']}")

    trust_path = _require_status(
        client_a.get("/connectome/trust-path?from=sovereign-a&to=sovereign-b"),
        200,
        "trust path",
    )
    emit()
    emit("==> Direct trust path")
    emit(f"    from:    {trust_path['from']}")
    emit(f"    to:      {trust_path['to']}")
    emit(f"    trusted: {trust_path['trusted']}")
    emit(f"    reason:  {trust_path['reason']}")

    blast = connectome["revocation_blast_radius"][0]
    emit()
    emit("==> Revocation blast radius")
    emit(f"    revoked attestation: {blast['id']}")
    emit(f"    issuer:              {blast['issuer_sovereign_id']}")
    emit(
        "    affected acceptors:  "
        + ", ".join(blast["affected_accepting_sovereigns"])
    )
    emit(f"    reason:              {blast['reason']}")

    page = client_a.get("/connectome")
    if page.status_code != 200 or page.mimetype != "text/html":
        raise RuntimeError("connectome page did not render")
    emit()
    emit("==> Operator page rendered")
    emit("    GET /connectome -> 200 text/html")
    emit("    GET /connectome.json -> machine-readable graph view")
    emit()
    emit(
        "Result: the Connectome exposes recognition edges, trust paths, "
        "and cross-sovereign revocation impact without becoming a new "
        "source of trust."
    )
    return sovereign_a, sovereign_b, lines


def run_demo() -> list[str]:
    """Execute the Connectome flow and return transcript lines."""
    with tempfile.TemporaryDirectory(prefix="gm-connectome-", ignore_cleanup_errors=True) as tmp:
        sovereign_a, sovereign_b, lines = _seed_connectome(Path(tmp))
        try:
            return lines
        finally:
            sovereign_a.db.conn.close()
            sovereign_b.db.conn.close()


def serve_demo(host: str, port: int) -> None:
    """Seed a Connectome demo and serve Sovereign A for browser inspection."""
    with tempfile.TemporaryDirectory(
        prefix="gm-connectome-server-",
        ignore_cleanup_errors=True,
    ) as tmp:
        sovereign_a, sovereign_b, _lines = _seed_connectome(Path(tmp))
        try:
            print()
            print("Connectome browser demo is ready.")
            print(f"  page:       http://{host}:{port}/connectome")
            print(f"  graph JSON: http://{host}:{port}/connectome.json")
            print(
                "  trust path: "
                f"http://{host}:{port}/connectome/trust-path?from=sovereign-a&to=sovereign-b"
            )
            print()
            print("Press Ctrl+C to stop the server.")
            sovereign_a.app.run(
                host=host,
                port=port,
                debug=False,
                use_reloader=False,
            )
        finally:
            sovereign_a.db.conn.close()
            sovereign_b.db.conn.close()


def _pillow():
    """Import Pillow lazily so plain demo execution has no image dependency."""
    from PIL import Image, ImageDraw, ImageFont

    return Image, ImageDraw, ImageFont


def _wrapped_lines(lines: list[str]) -> list[str]:
    """Wrap transcript lines for terminal rendering."""
    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(line, width=92, replace_whitespace=False) or [""])
    return wrapped


def _render_terminal_frame(lines: list[str], width: int, height: int):
    """Render a terminal-style frame for a transcript window."""
    Image, ImageDraw, ImageFont = _pillow()
    margin = 28
    line_height = 24
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 17)
        bold = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 17)
    except Exception:
        font = ImageFont.load_default()
        bold = font

    img = Image.new("RGB", (width, height), "#07111f")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width, 54), fill="#111827")
    draw.text((margin, 18), "Genesis Mesh Connectome", fill="#e5e7eb", font=bold)
    draw.ellipse((width - 88, 20, width - 76, 32), fill="#ef4444")
    draw.ellipse((width - 66, 20, width - 54, 32), fill="#f59e0b")
    draw.ellipse((width - 44, 20, width - 32, 32), fill="#22c55e")

    y = 78
    for text in lines:
        color = "#d1d5db"
        selected_font = font
        if text.startswith("==>"):
            color = "#93c5fd"
            selected_font = bold
        elif text.startswith("Result:"):
            color = "#86efac"
            selected_font = bold
        elif "trusted: True" in text or "200 text/html" in text:
            color = "#86efac"
            selected_font = bold
        elif "revoked" in text.lower() or "blast" in text.lower():
            color = "#fca5a5"
        elif "sovereign" in text.lower() or "connectome" in text.lower():
            color = "#c4b5fd"
        draw.text((margin, y), text, fill=color, font=selected_font)
        y += line_height
    return img


def render_png(lines: list[str], output: Path) -> None:
    """Render a static PNG from the final transcript state."""
    output.parent.mkdir(parents=True, exist_ok=True)
    visible = _wrapped_lines(lines)[-34:]
    _render_terminal_frame(visible, 1120, 940).save(output)


def render_gif(lines: list[str], output: Path) -> None:
    """Render transcript lines into an animated GIF."""
    output.parent.mkdir(parents=True, exist_ok=True)
    wrapped = _wrapped_lines(lines)
    frames = []
    for index in range(1, len(wrapped) + 1):
        visible = wrapped[max(0, index - 34):index]
        frames.append(_render_terminal_frame(visible, 1120, 940))
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=420,
        loop=0,
        optimize=True,
    )


def main() -> int:
    """Execute the demo and optionally render documentation assets."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_GIF_OUTPUT)
    parser.add_argument("--png-output", type=Path, default=DEFAULT_PNG_OUTPUT)
    parser.add_argument("--no-assets", action="store_true")
    parser.add_argument(
        "--serve",
        action="store_true",
        help="serve the seeded Connectome page for local browser inspection",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.serve:
        serve_demo(args.host, args.port)
        return 0

    lines = run_demo()
    if not args.no_assets:
        render_png(lines, args.png_output)
        render_gif(lines, args.output)
        print(f"PNG written to {args.png_output}")
        print(f"GIF written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
