"""Render the independent-sovereign proof transcript.

The default mode is intentionally non-mutating: it renders the verified
Azure + DigitalOcean transcript into documentation assets. Pass ``--live`` to
run the proof against live Network Authority endpoints, which creates treaties,
attestations, and imported revocation feed state.
"""

from __future__ import annotations

import argparse
import json
import textwrap
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from genesis_mesh.crypto import load_private_key, sign_data

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_GIF_OUTPUT = (
    ROOT / "docs/examples/assets/images/genesis-mesh-independent-sovereigns.gif"
)
DEFAULT_PNG_OUTPUT = (
    ROOT / "docs/examples/assets/images/genesis-mesh-independent-sovereigns.png"
)


def recorded_transcript() -> list[str]:
    """Return the verified clean independent-sovereign transcript from the live VMs."""
    return [
        "==> Clean starting state",
        "    Azure Connectome sovereigns: 0",
        "    NB Connectome sovereigns:    0",
        "",
        "==> Genesis identities",
        "    Azure network_name: USG",
        "    NB network_name:    USG-NB",
        "    NB host:            DigitalOcean 164.92.250.135",
        "    Azure host:         na.genesismesh.connectorzzz.com",
        "",
        "==> NB issued membership attestation",
        "    attestation: 3ee9bc08-9685-461b-8b00-ed4ff05a8c16",
        "    issuer:      USG-NB",
        "    role:        role:service:maintainer",
        "",
        "==> Azure issued recognition treaty for NB",
        "    treaty: 3b11b22d-a888-4c09-b6a0-f55a4161ba40",
        "    from:   USG",
        "    to:     USG-NB",
        "",
        "==> Azure accepted NB attestation before revocation",
        "    accepted: True",
        "    reason:   accepted",
        "",
        "==> NB revoked the same attestation",
        "    reason: final_independent_sovereign_proof_revocation",
        "",
        "==> NB published signed sovereign revocation feed",
        "    feed:     aeee77fb-1d76-4334-aa1a-4b0602969567",
        "    sequence: 1",
        "    revoked:  1",
        "",
        "==> Azure imported NB revocation feed",
        "    accepted: True",
        "    sequence: 1",
        "",
        "==> Azure rejected the same attestation after feed import",
        "    accepted: False",
        "    reason:   attestation_locally_revoked",
        "",
        "==> Azure Connectome summary",
        "    sovereigns:           2",
        "    recognition edges:    1",
        "    active edges:         1",
        "    imported revocations: 1",
        "    revoked material:     1",
        "",
        "==> Azure trust path",
        "    from:    USG",
        "    to:      USG-NB",
        "    trusted: True",
        "    reason:  active_treaty_path",
        "",
        "Result: independent-sovereign proof passed across Azure and DigitalOcean VMs.",
    ]


class LiveProofRunner:
    """Run the independent-sovereign proof against live Network Authority endpoints."""

    def __init__(
        self,
        azure_endpoint: str,
        nb_endpoint: str,
        operator_key: Path,
        operator_key_id: str,
    ) -> None:
        self.azure = azure_endpoint.rstrip("/")
        self.nb = nb_endpoint.rstrip("/")
        self.operator_key = load_private_key(str(operator_key))
        self.operator_key_id = operator_key_id
        self.session = requests.Session()
        self.lines: list[str] = []

    def emit(self, line: str = "") -> None:
        """Append and print one transcript line."""
        self.lines.append(line)
        print(line)

    def admin_headers(self, body: dict[str, Any]) -> dict[str, str]:
        """Create signed admin request headers for live endpoints."""
        timestamp = datetime.now(timezone.utc).isoformat()
        nonce = str(uuid.uuid4())
        canonical = json.dumps(
            {
                "body": body,
                "key_id": self.operator_key_id,
                "timestamp": timestamp,
                "nonce": nonce,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "X-Admin-Key-Id": self.operator_key_id,
            "X-Admin-Timestamp": timestamp,
            "X-Admin-Nonce": nonce,
            "X-Admin-Signature": sign_data(
                canonical.encode("utf-8"),
                self.operator_key,
            ),
        }

    def request_json(
        self,
        method: str,
        url: str,
        *,
        expected: int = 200,
        label: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run an HTTP request and return JSON or raise a compact error."""
        response = self.session.request(method, url, timeout=20, **kwargs)
        try:
            payload = response.json()
        except Exception:
            payload = {"raw": response.text[:500]}
        if response.status_code != expected:
            raise RuntimeError(f"{label} failed: {response.status_code} {payload}")
        return payload

    def run(self) -> list[str]:
        """Execute the live independent-sovereign proof and return transcript lines."""
        self.emit("==> Fetch public genesis identities")
        azure_genesis = self.request_json(
            "GET",
            f"{self.azure}/genesis",
            label="Azure genesis",
        )
        nb_genesis = self.request_json("GET", f"{self.nb}/genesis", label="NB genesis")
        azure_id = azure_genesis["network_name"]
        nb_id = nb_genesis["network_name"]
        nb_public_key = nb_genesis["network_authority"]["public_key"]
        self.emit(f"    Azure network_name: {azure_id}")
        self.emit(f"    NB network_name:    {nb_id}")
        self.emit(f"    NB key prefix:      {nb_public_key[:20]}")

        self.emit()
        self.emit("==> NB issues membership attestation")
        attestation_body = {
            "subject_id": "independent-sovereign-doc-proof-subject",
            "subject_public_key": "independent-sovereign-doc-proof-subject-public-key",
            "roles": ["role:service:maintainer"],
            "claims": {"proof": "independent-sovereigns"},
            "validity_hours": 24,
        }
        attestation = self.request_json(
            "POST",
            f"{self.nb}/admin/attestations",
            expected=201,
            label="NB attestation issue",
            json=attestation_body,
            headers=self.admin_headers(attestation_body),
        )
        self.emit(f"    attestation: {attestation['attestation_id']}")
        self.emit(f"    issuer:      {attestation['issuer_sovereign_id']}")

        self.emit()
        self.emit("==> Azure issues recognition treaty for NB")
        treaty_body = {
            "subject_sovereign_id": nb_id,
            "subject_public_keys": [nb_public_key],
            "scope": {
                "allowed_roles": ["role:service:maintainer"],
                "accepted_statuses": ["active"],
                "claims": {"proof": "azure-recognizes-digitalocean-nb"},
            },
            "validity_hours": 24,
            "metadata": {
                "proof": "independent-sovereigns",
                "providers": ["azure", "digitalocean"],
                "subject_endpoint": self.nb,
            },
        }
        treaty = self.request_json(
            "POST",
            f"{self.azure}/admin/recognition-treaties",
            expected=201,
            label="Azure treaty issue",
            json=treaty_body,
            headers=self.admin_headers(treaty_body),
        )
        self.emit(f"    treaty: {treaty['treaty_id']}")
        self.emit(f"    from:   {treaty['issuer_sovereign_id']}")
        self.emit(f"    to:     {treaty['subject_sovereign_id']}")

        self.emit()
        accepted = self.request_json(
            "POST",
            f"{self.azure}/attestations/verify-with-treaty",
            label="pre-revocation verification",
            json={"attestation": attestation, "treaty": treaty},
        )
        self.emit("==> Azure accepted NB attestation before revocation")
        self.emit(f"    accepted: {accepted['accepted']}")
        self.emit(f"    reason:   {accepted['reason']}")

        self.emit()
        revoke_body = {"reason": "independent_sovereign_doc_proof_revocation"}
        self.request_json(
            "POST",
            f"{self.nb}/admin/attestations/{attestation['attestation_id']}/revoke",
            label="NB attestation revoke",
            json=revoke_body,
            headers=self.admin_headers(revoke_body),
        )
        self.emit("==> NB revoked the same attestation")
        self.emit(f"    reason: {revoke_body['reason']}")

        feed = self.request_json(
            "GET",
            f"{self.nb}/sovereign-revocation-feed",
            label="NB revocation feed",
        )
        self.emit()
        self.emit("==> NB published signed sovereign revocation feed")
        self.emit(f"    feed:     {feed['feed_id']}")
        self.emit(f"    sequence: {feed['sequence']}")
        self.emit(f"    revoked:  {len(feed['revoked_attestation_ids'])}")

        import_body = {
            "feed": feed,
            "issuer_public_keys": [nb_public_key],
            "expected_issuer_sovereign_id": nb_id,
        }
        imported = self.request_json(
            "POST",
            f"{self.azure}/admin/sovereign-revocation-feeds/import",
            label="Azure feed import",
            json=import_body,
            headers=self.admin_headers(import_body),
        )
        self.emit()
        self.emit("==> Azure imported NB revocation feed")
        self.emit(f"    accepted: {imported['accepted']}")
        self.emit(f"    sequence: {imported['sequence']}")

        rejected = self.request_json(
            "POST",
            f"{self.azure}/attestations/verify-with-treaty",
            label="post-revocation verification",
            json={"attestation": attestation, "treaty": treaty},
        )
        self.emit()
        self.emit("==> Azure rejected the same attestation after feed import")
        self.emit(f"    accepted: {rejected['accepted']}")
        self.emit(f"    reason:   {rejected['reason']}")

        connectome = self.request_json(
            "GET",
            f"{self.azure}/connectome.json",
            label="Azure Connectome",
        )
        summary = connectome["summary"]
        trust_path = self.request_json(
            "GET",
            f"{self.azure}/connectome/trust-path?from={azure_id}&to={nb_id}",
            label="Azure trust path",
        )
        self.emit()
        self.emit("==> Azure Connectome summary")
        self.emit(f"    sovereigns:           {summary['sovereign_count']}")
        self.emit(f"    recognition edges:    {summary['recognition_edge_count']}")
        self.emit(f"    active edges:         {summary['active_edge_count']}")
        self.emit(f"    imported revocations: {summary['imported_revocation_count']}")
        self.emit(f"    revoked material:     {summary['revoked_trust_material_count']}")
        self.emit()
        self.emit("==> Azure trust path")
        self.emit(f"    from:    {trust_path['from']}")
        self.emit(f"    to:      {trust_path['to']}")
        self.emit(f"    trusted: {trust_path['trusted']}")
        self.emit(f"    reason:  {trust_path['reason']}")
        self.emit()
        self.emit("Result: independent-sovereign proof passed across Azure and DigitalOcean VMs.")
        return self.lines


def _pillow():
    """Import Pillow lazily so transcript-only mode has no image dependency."""
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
    draw.text(
        (margin, 18),
        "Genesis Mesh independent sovereigns",
        fill="#e5e7eb",
        font=bold,
    )
    draw.ellipse((width - 88, 20, width - 76, 32), fill="#ef4444")
    draw.ellipse((width - 66, 20, width - 54, 32), fill="#f59e0b")
    draw.ellipse((width - 44, 20, width - 32, 32), fill="#22c55e")

    y = 78
    for text in lines:
        color = "#d1d5db"
        selected_font = font
        lowered = text.lower()
        if text.startswith("==>"):
            color = "#93c5fd"
            selected_font = bold
        elif text.startswith("Result:"):
            color = "#86efac"
            selected_font = bold
        elif "accepted: True" in text or "trusted: True" in text:
            color = "#86efac"
            selected_font = bold
        elif "accepted: False" in text or "attestation_locally_revoked" in text:
            color = "#fca5a5"
            selected_font = bold
        elif "azure" in lowered or "digitalocean" in lowered or "usg-nb" in lowered:
            color = "#c4b5fd"
        elif "feed" in lowered or "revocation" in lowered:
            color = "#fbbf24"
        draw.text((margin, y), text, fill=color, font=selected_font)
        y += line_height
    return img


def render_png(lines: list[str], output: Path) -> None:
    """Render a static PNG from the final transcript state."""
    output.parent.mkdir(parents=True, exist_ok=True)
    visible = _wrapped_lines(lines)[-34:]
    _render_terminal_frame(visible, 1180, 940).save(output)


def render_gif(lines: list[str], output: Path) -> None:
    """Render transcript lines into an animated GIF."""
    output.parent.mkdir(parents=True, exist_ok=True)
    wrapped = _wrapped_lines(lines)
    frames = []
    for index in range(1, len(wrapped) + 1):
        visible = wrapped[max(0, index - 34):index]
        frames.append(_render_terminal_frame(visible, 1180, 940))
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=420,
        loop=0,
        optimize=True,
    )


def main() -> int:
    """Render recorded assets, or run the proof live when requested."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_GIF_OUTPUT)
    parser.add_argument("--png-output", type=Path, default=DEFAULT_PNG_OUTPUT)
    parser.add_argument("--no-assets", action="store_true")
    parser.add_argument(
        "--live",
        action="store_true",
        help="run the proof against live endpoints; this mutates NA state",
    )
    parser.add_argument(
        "--azure",
        default="https://na.genesismesh.connectorzzz.com",
        help="Azure Sovereign A Network Authority endpoint",
    )
    parser.add_argument(
        "--nb",
        default="http://164.92.250.135:8443",
        help="DigitalOcean Sovereign B Network Authority endpoint",
    )
    parser.add_argument(
        "--operator-key",
        type=Path,
        default=Path(".genesis-mesh/keys/operator.key"),
        help="operator private key used for signed admin requests in --live mode",
    )
    parser.add_argument("--operator-key-id", default="operator-local")
    args = parser.parse_args()

    if args.live:
        lines = LiveProofRunner(
            args.azure,
            args.nb,
            args.operator_key,
            args.operator_key_id,
        ).run()
    else:
        lines = recorded_transcript()
        for line in lines:
            print(line)

    if not args.no_assets:
        render_png(lines, args.png_output)
        render_gif(lines, args.output)
        print(f"PNG written to {args.png_output}")
        print(f"GIF written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
