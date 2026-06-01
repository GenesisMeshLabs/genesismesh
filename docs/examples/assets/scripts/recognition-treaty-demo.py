"""Run a local two-sovereign recognition treaty smoke demo.

The demo runs both sovereigns in one Python process so it is fast and
repeatable from a laptop or CI. Each sovereign still has its own genesis block,
Network Authority key, operator key, SQLite database, and treaty state.
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
DEFAULT_GIF_OUTPUT = ROOT / "docs/examples/assets/images/genesis-mesh-recognition-treaty.gif"
DEFAULT_PNG_OUTPUT = ROOT / "docs/examples/assets/images/genesis-mesh-recognition-treaty.png"


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
        network_version="v0.10-demo",
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
    """Execute the recognition treaty flow and return transcript lines."""
    lines: list[str] = []

    def emit(line: str = "") -> None:
        lines.append(line)
        print(line)

    with tempfile.TemporaryDirectory(prefix="gm-treaty-demo-", ignore_cleanup_errors=True) as tmp:
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
            issue = _post_admin(
                client_b,
                "/admin/attestations",
                issue_body,
                operator_b,
                "sovereign-b-operator",
            )
            attestation = _require_status(issue, 201, "attestation issue")
            emit()
            emit("==> Sovereign B issued membership attestation")
            emit(f"    attestation: {attestation['attestation_id']}")
            emit(f"    subject:     {attestation['subject_id']}")
            emit(f"    roles:       {', '.join(attestation['roles'])}")

            treaty_body = {
                "issuer_sovereign_id": "sovereign-a",
                "subject_sovereign_id": "sovereign-b",
                "subject_public_keys": [
                    sovereign_b.genesis_block.network_authority.public_key,
                ],
                "scope": {
                    "allowed_roles": ["role:service:maintainer"],
                    "accepted_statuses": ["active"],
                    "claims": {"purpose": "portable maintainer trust demo"},
                },
                "validity_hours": 24,
                "metadata": {"demo": "recognition-treaty"},
            }
            treaty_response = _post_admin(
                client_a,
                "/admin/recognition-treaties",
                treaty_body,
                operator_a,
                "sovereign-a-operator",
            )
            treaty = _require_status(treaty_response, 201, "treaty issue")
            emit()
            emit("==> Sovereign A issued recognition treaty for Sovereign B")
            emit(f"    treaty: {treaty['treaty_id']}")
            emit(f"    scope:  {', '.join(treaty['scope']['allowed_roles'])}")

            verify = client_a.post(
                "/attestations/verify-with-treaty",
                json={"attestation": attestation, "treaty": treaty},
            )
            verify_data = _require_status(verify, 200, "treaty attestation verification")
            if verify_data["reason"] != "accepted":
                raise RuntimeError(f"expected treaty acceptance, got {verify_data}")
            emit()
            emit("==> Sovereign A accepted B's attestation through the treaty")
            emit(f"    accepted: {verify_data['accepted']}")
            emit(f"    reason:   {verify_data['reason']}")

            revoke_body = {"reason": "trust_boundary_removed"}
            revoke = _post_admin(
                client_a,
                f"/admin/recognition-treaties/{treaty['treaty_id']}/revoke",
                revoke_body,
                operator_a,
                "sovereign-a-operator",
            )
            _require_status(revoke, 200, "treaty revoke")
            emit()
            emit("==> Sovereign A revoked the recognition treaty")
            emit(f"    reason: {revoke_body['reason']}")

            rejected = client_a.post(
                "/attestations/verify-with-treaty",
                json={"attestation": attestation, "treaty": treaty},
            )
            rejected_data = _require_status(rejected, 200, "post-revocation verification")
            if rejected_data["reason"] != "treaty_locally_revoked":
                raise RuntimeError(f"expected treaty revocation rejection, got {rejected_data}")
            emit()
            emit("==> Sovereign A rejected the same attestation after treaty revocation")
            emit(f"    accepted: {rejected_data['accepted']}")
            emit(f"    reason:   {rejected_data['reason']}")

            graph = client_a.get("/recognition-graph")
            graph_data = _require_status(graph, 200, "recognition graph export")
            emit()
            emit("==> Sovereign A exported minimal recognition graph")
            emit(f"    sovereigns:              {len(graph_data['sovereigns'])}")
            emit(f"    recognition_edges:       {len(graph_data['recognition_edges'])}")
            emit(f"    revoked_trust_material:  {len(graph_data['revoked_trust_material'])}")

            emit()
            emit(
                "Result: direct recognition is signed, scoped, explainable, "
                "graph-exportable, and revocable."
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
    draw.text((margin, 18), "Genesis Mesh recognition treaty", fill="#e5e7eb", font=bold)
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
        elif "accepted: True" in text:
            color = "#86efac"
            selected_font = bold
        elif "accepted: False" in text or "treaty_locally_revoked" in text:
            color = "#fca5a5"
            selected_font = bold
        elif "sovereign" in text.lower() or "treaty" in text.lower():
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
