"""Render the operator onboarding exchange transcript.

The default mode is non-mutating: it renders a captured transcript for the
trust-bundle and federation-bootstrap readiness flow. Pass ``--live`` to run
the public, non-mutating smoke workflow against the live Azure and DigitalOcean
Network Authorities.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_GIF_OUTPUT = (
    ROOT / "docs/examples/assets/images/genesis-mesh-operator-onboarding-exchange.gif"
)
DEFAULT_PNG_OUTPUT = (
    ROOT / "docs/examples/assets/images/genesis-mesh-operator-onboarding-exchange.png"
)
DEFAULT_AZURE_ENDPOINT = "https://na.genesismesh.connectorzzz.com"
DEFAULT_NB_ENDPOINT = "http://164.92.250.135:8443"


def recorded_transcript() -> list[str]:
    """Return the verified operator-onboarding exchange transcript."""
    return [
        "==> Export USG-NB trust bundle",
        "    command: genesis-mesh trust-bundle export --na http://164.92.250.135:8443",
        "    sovereign:  USG-NB",
        "    endpoint:   http://164.92.250.135:8443",
        "    version:    v0.1",
        "    na_key:     sha256:e71aaca716e4115b2ce037e5",
        "    policy:     not_configured",
        "    revocations: ok sequence=1",
        "",
        "==> Inspect bundle offline",
        "    validation: ok",
        "    connectome: edges=0 active=0 treaties=0",
        "",
        "==> Validate bundle against live DigitalOcean endpoint",
        "    bundle source endpoint matches live endpoint",
        "    bundle NA key matches live NA key",
        "    validation: ok",
        "",
        "==> Import bundle as review evidence",
        "    workflow: trust-bundle-import",
        "    trust_granted: false",
        "    next_step: federation bootstrap with --issuer-bundle",
        "",
        "==> Federation bootstrap dry run from Azure to USG-NB",
        "    acceptor: USG / https://na.genesismesh.connectorzzz.com",
        "    issuer:   USG-NB / http://164.92.250.135:8443",
        "    treaty preview role: role:service:maintainer",
        "    accepted statuses: active",
        "    result: No treaty issued (--dry-run)",
        "",
        "Result: trust material can be exchanged, reviewed, and used for bootstrap without granting trust automatically.",
    ]


def run_command(args: list[str]) -> list[str]:
    """Run one CLI command and return stdout lines."""
    result = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )
    return result.stdout.splitlines()


def live_transcript(azure_endpoint: str, nb_endpoint: str, bundle: Path, receipt: Path) -> list[str]:
    """Run the non-mutating live smoke flow and return a transcript."""
    bundle.parent.mkdir(parents=True, exist_ok=True)
    commands = [
        [
            "trust-bundle",
            "export",
            "--na",
            nb_endpoint,
            "--output",
            str(bundle),
        ],
        ["trust-bundle", "inspect", "--bundle", str(bundle)],
        ["trust-bundle", "validate", "--bundle", str(bundle), "--na", nb_endpoint],
        [
            "trust-bundle",
            "import",
            "--bundle",
            str(bundle),
            "--na",
            nb_endpoint,
            "--output",
            str(receipt),
        ],
        [
            "federation",
            "bootstrap",
            "--acceptor",
            azure_endpoint,
            "--issuer-bundle",
            str(bundle),
            "--dry-run",
        ],
    ]

    transcript: list[str] = []
    for command in commands:
        transcript.append(f"==> genesis-mesh {' '.join(command)}")
        transcript.extend(f"    {line}" for line in run_command(["genesis-mesh", *command]))
        transcript.append("")
    transcript.append("Result: live non-mutating operator-onboarding exchange smoke passed.")
    return transcript


def _pillow():
    """Import Pillow lazily so live smoke can run without rendering assets."""
    from PIL import Image, ImageDraw, ImageFont

    return Image, ImageDraw, ImageFont


def _wrapped_lines(lines: list[str]) -> list[str]:
    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(line, width=94, replace_whitespace=False) or [""])
    return wrapped


def _render_terminal_frame(lines: list[str], width: int, height: int):
    Image, ImageDraw, ImageFont = _pillow()
    margin = 30
    line_height = 24
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 17)
        bold = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 17)
    except Exception:
        font = ImageFont.load_default()
        bold = font

    img = Image.new("RGB", (width, height), "#0a0d12")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width, 58), fill="#10161d")
    draw.text((margin, 19), "Genesis Mesh operator onboarding exchange", fill="#e8edf4", font=bold)
    draw.ellipse((width - 90, 22, width - 78, 34), fill="#ef4444")
    draw.ellipse((width - 68, 22, width - 56, 34), fill="#eab308")
    draw.ellipse((width - 46, 22, width - 34, 34), fill="#22c55e")

    y = 82
    for text in lines:
        color = "#d1d5db"
        selected_font = font
        if text.startswith("==>"):
            color = "#60a5fa"
            selected_font = bold
        elif text.startswith("Result:"):
            color = "#86efac"
            selected_font = bold
        elif "trust_granted: false" in text or "No treaty issued" in text:
            color = "#facc15"
            selected_font = bold
        elif "validation: ok" in text or "matches live" in text:
            color = "#86efac"
            selected_font = bold
        elif "USG" in text or "bundle" in text.lower():
            color = "#c4b5fd"
        draw.text((margin, y), text, fill=color, font=selected_font)
        y += line_height
    return img


def render_png(lines: list[str], output: Path) -> None:
    """Render a static transcript image."""
    output.parent.mkdir(parents=True, exist_ok=True)
    visible = _wrapped_lines(lines)[-34:]
    _render_terminal_frame(visible, 1180, 850).save(output)


def render_gif(lines: list[str], output: Path) -> None:
    """Render an animated transcript image."""
    output.parent.mkdir(parents=True, exist_ok=True)
    wrapped = _wrapped_lines(lines)
    frames = []
    for index in range(1, len(wrapped) + 1):
        visible = wrapped[max(0, index - 34):index]
        frames.append(_render_terminal_frame(visible, 1180, 850))
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=420,
        loop=0,
        optimize=True,
    )


def main() -> int:
    """Run the example and optionally render documentation assets."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--azure", default=DEFAULT_AZURE_ENDPOINT)
    parser.add_argument("--nb", default=DEFAULT_NB_ENDPOINT)
    parser.add_argument("--bundle", type=Path, default=Path("operator-onboarding-trust-bundle.json"))
    parser.add_argument("--receipt", type=Path, default=Path("operator-onboarding-trust-bundle-receipt.json"))
    parser.add_argument("--output", type=Path, default=DEFAULT_GIF_OUTPUT)
    parser.add_argument("--png-output", type=Path, default=DEFAULT_PNG_OUTPUT)
    parser.add_argument("--no-assets", action="store_true")
    args = parser.parse_args()

    lines = (
        live_transcript(args.azure, args.nb, args.bundle, args.receipt)
        if args.live
        else recorded_transcript()
    )
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
