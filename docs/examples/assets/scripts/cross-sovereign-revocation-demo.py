"""Run a local cross-sovereign revocation propagation smoke demo.

The demo runs two sovereign Network Authorities in one process. Sovereign A
accepts a membership attestation from Sovereign B through a recognition treaty,
then stops accepting it after importing B's signed revocation feed.
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
DEFAULT_GIF_OUTPUT = (
    ROOT / "docs/examples/assets/images/genesis-mesh-cross-sovereign-revocation.gif"
)
DEFAULT_PNG_OUTPUT = (
    ROOT / "docs/examples/assets/images/genesis-mesh-cross-sovereign-revocation.png"
)


def _admin_headers(body: dict, operator_keypair: KeyPair, key_id: str) -> dict:
    """Create operator-auth headers for an admin request body."""
    timestamp = datetime.now(timezone.utc).isoformat()
    nonce = str(uuid.uuid4())
    canonical = json.dumps(
        {
            "body": body,
            "key_id": key_id,
            "timestamp": timestamp,
            "nonce": nonce,
        },
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
        network_version="v0.11-demo",
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


def run_demo() -> list[str]:
    """Execute the revocation propagation flow and return transcript lines."""
    lines: list[str] = []

    def emit(line: str = "") -> None:
        lines.append(line)
        print(line)

    with tempfile.TemporaryDirectory(prefix="gm-revocation-feed-", ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        sovereign_a, operator_a = _new_sovereign("sovereign-a", tmp_path / "a.db")
        sovereign_b, operator_b = _new_sovereign("sovereign-b", tmp_path / "b.db")
        client_a = sovereign_a.app.test_client()
        client_b = sovereign_b.app.test_client()

        try:
            emit("==> Sovereigns initialized")
            emit("    sovereign-a: accepting sovereign")
            emit("    sovereign-b: issuing sovereign")

            issue_body = {
                "issuer_sovereign_id": "sovereign-b",
                "subject_id": "alice",
                "subject_public_key": "alice-public-key",
                "roles": ["role:service:maintainer"],
                "claims": {"project": "demo-package"},
                "validity_hours": 24,
            }
            attestation = _require_status(
                _post_admin(
                    client_b,
                    "/admin/attestations",
                    issue_body,
                    operator_b,
                    "sovereign-b-operator",
                ),
                201,
                "attestation issue",
            )
            emit()
            emit("==> Sovereign B issued membership attestation")
            emit(f"    attestation: {attestation['attestation_id']}")
            emit(f"    subject:     {attestation['subject_id']}")

            treaty_body = {
                "issuer_sovereign_id": "sovereign-a",
                "subject_sovereign_id": "sovereign-b",
                "subject_public_keys": [
                    sovereign_b.genesis_block.network_authority.public_key,
                ],
                "scope": {
                    "allowed_roles": ["role:service:maintainer"],
                    "accepted_statuses": ["active"],
                    "claims": {"purpose": "cross-sovereign revocation demo"},
                },
                "validity_hours": 24,
                "metadata": {"demo": "cross-sovereign-revocation"},
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
            emit("==> Sovereign A recognized Sovereign B through active treaty")
            emit(f"    treaty: {treaty['treaty_id']}")

            accepted = _require_status(
                client_a.post(
                    "/attestations/verify-with-treaty",
                    json={"attestation": attestation, "treaty": treaty},
                ),
                200,
                "pre-revocation verification",
            )
            if not accepted["accepted"]:
                raise RuntimeError(f"expected pre-revocation acceptance, got {accepted}")
            emit()
            emit("==> Sovereign A accepted B's attestation before feed import")
            emit(f"    accepted: {accepted['accepted']}")
            emit(f"    reason:   {accepted['reason']}")

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
            emit()
            emit("==> Sovereign B published signed revocation feed")
            emit(f"    feed sequence: {feed['sequence']}")
            emit(f"    revoked IDs:   {len(feed['revoked_attestation_ids'])}")

            import_body = {"feed": feed}
            imported = _require_status(
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
            emit("==> Sovereign A imported B's revocation feed")
            emit(f"    accepted: {imported['accepted']}")
            emit(f"    sequence: {imported['sequence']}")

            rejected = _require_status(
                client_a.post(
                    "/attestations/verify-with-treaty",
                    json={"attestation": attestation, "treaty": treaty},
                ),
                200,
                "post-feed verification",
            )
            if rejected["reason"] != "attestation_locally_revoked":
                raise RuntimeError(f"expected propagated revocation rejection, got {rejected}")
            emit()
            emit("==> Sovereign A rejected the same attestation after feed import")
            emit(f"    accepted: {rejected['accepted']}")
            emit(f"    reason:   {rejected['reason']}")

            graph_data = _require_status(
                client_a.get("/recognition-graph"),
                200,
                "recognition graph export",
            )
            propagated = [
                item for item in graph_data["revoked_trust_material"]
                if item["type"] == "membership_attestation"
            ]
            emit()
            emit("==> Recognition graph includes propagated revoked attestation")
            emit(f"    propagated revocations: {len(propagated)}")
            emit(f"    recognition_edges:      {len(graph_data['recognition_edges'])}")

            emit()
            emit(
                "Result: cross-sovereign trust can be accepted, revoked by the "
                "issuer, imported by the acceptor, and enforced without revoking "
                "the treaty itself."
            )
            return lines
        finally:
            sovereign_a.db.conn.close()
            sovereign_b.db.conn.close()


def _pillow():
    """Import Pillow lazily so the plain demo has no image dependency."""
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
    draw.text((margin, 18), "Genesis Mesh cross-sovereign revocation", fill="#e5e7eb", font=bold)
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
        elif "accepted: True" in text or "imported" in text.lower():
            color = "#86efac"
            selected_font = bold
        elif "accepted: False" in text or "attestation_locally_revoked" in text:
            color = "#fca5a5"
            selected_font = bold
        elif "sovereign" in text.lower() or "feed" in text.lower():
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
    args = parser.parse_args()

    lines = run_demo()
    if not args.no_assets:
        render_png(lines, args.png_output)
        render_gif(lines, args.output)
        print(f"PNG written to {args.png_output}")
        print(f"GIF written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
