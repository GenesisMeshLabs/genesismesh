"""Generate the supply-chain trust gate demo artifacts and assets."""

from __future__ import annotations

import argparse
import base64
import json
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nacl.signing

from genesis_mesh.crypto import KeyPair, sign_model
from genesis_mesh.models import (
    MembershipAttestation,
    RecognitionTreaty,
    RecognitionTreatyScope,
    SovereignRevocationFeed,
)
from genesis_mesh.trust import (
    DEFAULT_DELEGATED_ROLE,
    DEFAULT_MAINTAINER_ROLE,
    SUPPLY_CHAIN_MAINTAINER_PROFILE,
    verify_supply_chain_maintainer_gate,
)

ROOT = Path(__file__).resolve().parents[4]
ARTIFACT_DIR = ROOT / "docs/examples/assets/supply-chain-trust-gate"
DEFAULT_PNG_OUTPUT = ROOT / "docs/examples/assets/images/genesis-mesh-supply-chain-trust-gate.png"
DEFAULT_GIF_OUTPUT = ROOT / "docs/examples/assets/images/genesis-mesh-supply-chain-trust-gate.gif"
PROJECT_ID = "pypi:demo-package"
REPOSITORY = "https://github.com/example/demo-package"


def _deterministic_key(seed: int) -> KeyPair:
    """Create deterministic demo-only keys from a byte seed."""
    signing_key = nacl.signing.SigningKey(bytes([seed]) * 32)
    return KeyPair(private_key=signing_key, public_key=signing_key.verify_key)


def _build_artifacts() -> tuple[dict[str, Path], str, list[str]]:
    """Create signed JSON artifacts for the CI verifier demo."""
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    project_a_key = _deterministic_key(11)
    project_b_key = _deterministic_key(22)

    attestation = MembershipAttestation(
        attestation_id="demo-maintainer-attestation",
        issuer_sovereign_id="project-a",
        subject_id="alice@example.dev",
        subject_public_key=base64.b64encode(b"alice-demo-public-key").decode("utf-8"),
        roles=[DEFAULT_MAINTAINER_ROLE],
        status="active",
        issued_at=now,
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2036, 1, 1, tzinfo=timezone.utc),
        issued_by="project-a-na",
        claims={
            "profile": SUPPLY_CHAIN_MAINTAINER_PROFILE,
            "project_id": PROJECT_ID,
            "repository": REPOSITORY,
            "delegated_role": DEFAULT_DELEGATED_ROLE,
        },
    )
    attestation.signatures.append(sign_model(attestation, project_a_key.private_key, "project-a-na"))

    treaty = RecognitionTreaty(
        treaty_id="demo-recognition-treaty",
        issuer_sovereign_id="project-b",
        subject_sovereign_id="project-a",
        subject_public_keys=[project_a_key.public_key_b64],
        scope=RecognitionTreatyScope(
            allowed_roles=[DEFAULT_MAINTAINER_ROLE],
            accepted_statuses=["active"],
            claims={
                "profile": SUPPLY_CHAIN_MAINTAINER_PROFILE,
                "project_id": PROJECT_ID,
            },
        ),
        status="active",
        issued_at=now,
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2036, 1, 1, tzinfo=timezone.utc),
        issued_by="project-b-na",
        metadata={"demo": "supply-chain-trust-gate"},
    )
    treaty.signatures.append(sign_model(treaty, project_b_key.private_key, "project-b-na"))

    feed = SovereignRevocationFeed(
        feed_id="demo-revocation-feed",
        issuer_sovereign_id="project-a",
        sequence=2,
        issued_at=now + timedelta(minutes=10),
        revoked_attestation_ids=[attestation.attestation_id],
        revocation_reasons={attestation.attestation_id: "maintainer_key_rotated"},
        issued_by="project-a-na",
    )
    feed.signatures.append(sign_model(feed, project_a_key.private_key, "project-a-na"))

    paths = {
        "attestation": ARTIFACT_DIR / "maintainer-attestation.json",
        "treaty": ARTIFACT_DIR / "recognition-treaty.json",
        "feed": ARTIFACT_DIR / "revocation-feed.json",
        "treaty_key": ARTIFACT_DIR / "treaty-issuer-public-key.txt",
    }
    paths["attestation"].write_text(_json(attestation), encoding="utf-8")
    paths["treaty"].write_text(_json(treaty), encoding="utf-8")
    paths["feed"].write_text(_json(feed), encoding="utf-8")
    paths["treaty_key"].write_text(project_b_key.public_key_b64 + "\n", encoding="utf-8")

    allow = verify_supply_chain_maintainer_gate(
        attestation=attestation,
        treaty=treaty,
        treaty_issuer_public_keys=[project_b_key.public_key_b64],
        project_id=PROJECT_ID,
        repository=REPOSITORY,
    )
    deny = verify_supply_chain_maintainer_gate(
        attestation=attestation,
        treaty=treaty,
        treaty_issuer_public_keys=[project_b_key.public_key_b64],
        project_id=PROJECT_ID,
        repository=REPOSITORY,
        revocation_feeds=[feed],
    )
    lines = [
        "==> Supply-chain trust gate artifacts generated",
        f"    project:      {PROJECT_ID}",
        "    issuer:       project-a",
        "    acceptor:     project-b",
        f"    attestation:  {attestation.attestation_id}",
        f"    treaty:       {treaty.treaty_id}",
        "",
        "==> CI verifies Alice before revocation",
        f"    accepted:     {allow.accepted}",
        f"    reason:       {allow.reason}",
        f"    exit code:    {allow.exit_code}",
        "",
        "==> Project A publishes a signed revocation feed",
        f"    feed:         {feed.feed_id}",
        f"    sequence:     {feed.sequence}",
        "    reason:       maintainer_key_rotated",
        "",
        "==> CI verifies the same attestation after feed import",
        f"    accepted:     {deny.accepted}",
        f"    reason:       {deny.reason}",
        f"    exit code:    {deny.exit_code}",
        "",
        "Result: portable maintainer trust gates a release action, then revocation blocks it.",
    ]
    return paths, project_b_key.public_key_b64, lines


def _json(model) -> str:
    return json.dumps(model.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def _pillow():
    """Import Pillow lazily so the plain demo can still generate JSON fixtures."""
    from PIL import Image, ImageDraw, ImageFont

    return Image, ImageDraw, ImageFont


def _wrapped_lines(lines: list[str]) -> list[str]:
    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(line, width=92, replace_whitespace=False) or [""])
    return wrapped


def _render_terminal_frame(lines: list[str], width: int, height: int):
    Image, ImageDraw, ImageFont = _pillow()
    margin = 28
    line_height = 24
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 17)
        bold = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 17)
    except Exception:
        font = ImageFont.load_default()
        bold = font

    img = Image.new("RGB", (width, height), "#08111f")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width, 54), fill="#111827")
    draw.text((margin, 18), "Genesis Mesh supply-chain trust gate", fill="#e5e7eb", font=bold)
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
        elif "accepted:     True" in text or "exit code:    0" in text:
            color = "#86efac"
            selected_font = bold
        elif "accepted:     False" in text or "exit code:    10" in text:
            color = "#fca5a5"
            selected_font = bold
        elif "project" in text.lower() or "treaty" in text.lower():
            color = "#c4b5fd"
        draw.text((margin, y), text, fill=color, font=selected_font)
        y += line_height
    return img


def render_png(lines: list[str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    visible = _wrapped_lines(lines)[-34:]
    _render_terminal_frame(visible, 1120, 760).save(output)


def render_gif(lines: list[str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    wrapped = _wrapped_lines(lines)
    frames = []
    for index in range(1, len(wrapped) + 1):
        visible = wrapped[max(0, index - 34):index]
        frames.append(_render_terminal_frame(visible, 1120, 760))
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=420,
        loop=0,
        optimize=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_GIF_OUTPUT)
    parser.add_argument("--png-output", type=Path, default=DEFAULT_PNG_OUTPUT)
    parser.add_argument("--no-assets", action="store_true")
    args = parser.parse_args()

    paths, public_key, lines = _build_artifacts()
    for line in lines:
        print(line)
    print()
    print("Verifier command:")
    print(
        "genesis-mesh supply-chain verify "
        f"--attestation {paths['attestation']} "
        f"--treaty {paths['treaty']} "
        f"--treaty-issuer-public-key {public_key} "
        f"--project-id {PROJECT_ID} "
        f"--repository {REPOSITORY}"
    )

    if not args.no_assets:
        render_png(lines, args.png_output)
        render_gif(lines, args.output)
        print(f"PNG written to {args.png_output}")
        print(f"GIF written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
