"""Render the sovereign health dashboard transcript."""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_GIF_OUTPUT = (
    ROOT / "docs/examples/assets/images/genesis-mesh-sovereign-health-dashboard.gif"
)
DEFAULT_PNG_OUTPUT = (
    ROOT / "docs/examples/assets/images/genesis-mesh-sovereign-health-dashboard.png"
)


def recorded_transcript() -> list[str]:
    """Return the sovereign health dashboard transcript."""
    return [
        "==> open /dashboard",
        "    sovereign:       USG",
        "    readiness:       ready",
        "    active edges:    2",
        "    treaty warnings: 2",
        "    revocation feeds: 1",
        "    active nodes:    0",
        "",
        "==> trust warnings",
        "    2 treaties are expiring soon.",
        "    Historical revoked or replaced treaty material is present.",
        "    Revocation feeds are fresh.",
        "",
        "==> treaty lifecycle",
        "    USG -> USG-NB",
        "      lifecycle: expiring_soon",
        "      expiry risk: high",
        "      expires: 2026-06-05 21:55 UTC",
        "    USG -> USG-LOCAL",
        "      lifecycle: expiring_soon",
        "      expiry risk: high",
        "      expires: 2026-06-05 13:42 UTC",
        "",
        "==> revocation feed freshness",
        "    issuer: USG-NB",
        "    freshness: fresh",
        "    imported: 2026-06-05 00:12 UTC",
        "",
        "==> recent trust changes",
        "    recognition_treaty_issued",
        "    sovereign_revocation_feed_imported",
        "    recognition_treaty_revoked",
        "",
        "==> verification links",
        "    /dashboard.json",
        "    /connectome.json",
        "    /recognition-graph",
        "    /api-reference",
        "    /cli-reference",
        "",
        "Result: one read-only page explains sovereign health and trust state.",
    ]


def _pillow():
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
    draw.text((margin, 19), "Genesis Mesh sovereign health and trust dashboard", fill="#e8edf4", font=bold)
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
        elif "ready" in text or "fresh" in text or "active edges" in text:
            color = "#86efac"
            selected_font = bold
        elif "warning" in text or "expiring_soon" in text or "high" in text:
            color = "#fbbf24"
            selected_font = bold
        elif "/dashboard" in text or "/connectome" in text or "/api-reference" in text:
            color = "#93c5fd"
        elif "USG" in text or "recognition" in text or "revocation" in text:
            color = "#c4b5fd"
        draw.text((margin, y), text, fill=color, font=selected_font)
        y += line_height
    return img


def render_png(lines: list[str], output: Path) -> None:
    """Render a static screenshot."""
    output.parent.mkdir(parents=True, exist_ok=True)
    visible = _wrapped_lines(lines)[-34:]
    _render_terminal_frame(visible, 1180, 850).save(output)


def render_gif(lines: list[str], output: Path) -> None:
    """Render an animated transcript."""
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
    """Print the transcript and optionally regenerate assets."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_GIF_OUTPUT)
    parser.add_argument("--png-output", type=Path, default=DEFAULT_PNG_OUTPUT)
    parser.add_argument("--no-assets", action="store_true")
    args = parser.parse_args()

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
