"""Run a local two-sovereign membership attestation smoke demo.

The demo intentionally runs both sovereigns in one Python process so it is fast
and repeatable in CI or from a laptop. Each sovereign still has its own genesis
block, Network Authority key, operator key, SQLite database, and local
recognition policy.
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

from genesis_mesh.crypto import KeyPair, generate_keypair, sign_data, sign_model
from genesis_mesh.models import (
    GenesisBlock,
    NetworkAuthority,
    PolicyManifestRef,
    RecognitionPolicy,
    RecognizedIssuer,
)
from genesis_mesh.na_service.server import NetworkAuthorityService

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_GIF_OUTPUT = ROOT / "docs/examples/assets/images/genesis-mesh-sovereign-attestation.gif"
DEFAULT_PNG_OUTPUT = ROOT / "docs/examples/assets/images/genesis-mesh-sovereign-attestation.png"


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
        network_version="v0.9-demo",
        root_public_key=na_public_key,
        network_authority=NetworkAuthority(
            public_key=na_public_key,
            valid_from=now,
            valid_to=now + timedelta(days=90),
        ),
        policy_manifest=PolicyManifestRef(hash="sha256:demo", url=None),
    )
    genesis.signatures.append(sign_model(genesis, na_key, "root"))
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


def run_demo() -> list[str]:
    """Execute the two-sovereign attestation flow and return transcript lines."""
    lines: list[str] = []

    def emit(line: str = "") -> None:
        lines.append(line)
        print(line)

    with tempfile.TemporaryDirectory(prefix="gm-sovereign-demo-", ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        sovereign_a, operator_a = _new_sovereign("sovereign-a", tmp_path / "a.db")
        sovereign_b, operator_b = _new_sovereign("sovereign-b", tmp_path / "b.db")
        client_a = sovereign_a.app.test_client()
        client_b = sovereign_b.app.test_client()

        try:
            emit("==> Sovereigns initialized")
            emit("    sovereign-a: independent genesis, NA key, operator key, DB")
            emit("    sovereign-b: independent genesis, NA key, operator key, DB")

            issue_body = {
                "subject_id": "alice",
                "subject_public_key": "alice-public-key",
                "roles": ["role:service:maintainer"],
                "claims": {"project": "demo-package"},
                "validity_hours": 24,
            }
            issue = _post_admin(
                client_a,
                "/admin/attestations",
                issue_body,
                operator_a,
                "sovereign-a-operator",
            )
            if issue.status_code != 201:
                raise RuntimeError(f"issue failed: {issue.status_code} {issue.get_data(as_text=True)}")
            attestation = issue.get_json()
            emit()
            emit("==> Sovereign A issued membership attestation")
            emit(f"    attestation: {attestation['attestation_id']}")
            emit(f"    subject:     {attestation['subject_id']}")
            emit(f"    roles:       {', '.join(attestation['roles'])}")

            policy = RecognitionPolicy(
                local_sovereign_id="sovereign-b",
                recognized_issuers=[
                    RecognizedIssuer(
                        sovereign_id="sovereign-a",
                        public_keys=[sovereign_a.genesis_block.network_authority.public_key],
                        allowed_roles=["role:service:maintainer"],
                    )
                ],
            )
            policy_body = {
                "policy_id": "sovereign-b-recognizes-a",
                "recognition_policy": json.loads(policy.model_dump_json()),
            }
            save_policy = _post_admin(
                client_b,
                "/admin/recognition-policy",
                policy_body,
                operator_b,
                "sovereign-b-operator",
            )
            if save_policy.status_code != 200:
                raise RuntimeError(
                    f"policy save failed: {save_policy.status_code} {save_policy.get_data(as_text=True)}"
                )
            emit()
            emit("==> Sovereign B recognized Sovereign A locally")
            emit("    policy: sovereign-b-recognizes-a")

            accepted = client_b.post("/attestations/verify", json={"attestation": attestation})
            accepted_json = accepted.get_json()
            if accepted_json["reason"] != "accepted":
                raise RuntimeError(f"expected acceptance, got {accepted_json}")
            emit()
            emit("==> Sovereign B verified A's attestation")
            emit(f"    accepted: {accepted_json['accepted']}")
            emit(f"    reason:   {accepted_json['reason']}")

            revoke_body = {"reason": "membership_removed"}
            revoke = _post_admin(
                client_a,
                f"/admin/attestations/{attestation['attestation_id']}/revoke",
                revoke_body,
                operator_a,
                "sovereign-a-operator",
            )
            if revoke.status_code != 200:
                raise RuntimeError(f"revoke failed: {revoke.status_code} {revoke.get_data(as_text=True)}")
            emit()
            emit("==> Sovereign A revoked the attestation")
            emit(f"    reason: {revoke_body['reason']}")

            revoked_policy = policy.model_copy(
                update={"revoked_attestation_ids": {attestation["attestation_id"]}}
            )
            revoked_policy_body = {
                "policy_id": "sovereign-b-recognizes-a",
                "recognition_policy": json.loads(revoked_policy.model_dump_json()),
            }
            save_revoked_policy = _post_admin(
                client_b,
                "/admin/recognition-policy",
                revoked_policy_body,
                operator_b,
                "sovereign-b-operator",
            )
            if save_revoked_policy.status_code != 200:
                raise RuntimeError(
                    "revocation input failed: "
                    f"{save_revoked_policy.status_code} {save_revoked_policy.get_data(as_text=True)}"
                )
            rejected = client_b.post("/attestations/verify", json={"attestation": attestation})
            rejected_json = rejected.get_json()
            if rejected_json["reason"] != "locally_revoked":
                raise RuntimeError(f"expected revocation rejection, got {rejected_json}")
            emit()
            emit("==> Sovereign B rejected the same attestation after revocation input")
            emit(f"    accepted: {rejected_json['accepted']}")
            emit(f"    reason:   {rejected_json['reason']}")

            emit()
            emit("Result: cross-sovereign membership trust is portable and revocable.")
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
    draw.text((margin, 18), "Genesis Mesh sovereign attestation", fill="#e5e7eb", font=bold)
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
        elif "accepted: False" in text or "locally_revoked" in text:
            color = "#fca5a5"
            selected_font = bold
        elif "sovereign" in text.lower() or "attestation" in text.lower():
            color = "#c4b5fd"
        draw.text((margin, y), text, fill=color, font=selected_font)
        y += line_height
    return img


def render_png(lines: list[str], output: Path) -> None:
    """Render a static PNG from the final transcript state."""
    output.parent.mkdir(parents=True, exist_ok=True)
    visible = _wrapped_lines(lines)[-32:]
    _render_terminal_frame(visible, 1120, 880).save(output)


def render_gif(lines: list[str], output: Path) -> None:
    """Render transcript lines into an animated GIF."""
    output.parent.mkdir(parents=True, exist_ok=True)
    wrapped = _wrapped_lines(lines)
    frames = []
    for index in range(1, len(wrapped) + 1):
        visible = wrapped[max(0, index - 32):index]
        frames.append(_render_terminal_frame(visible, 1120, 880))
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
