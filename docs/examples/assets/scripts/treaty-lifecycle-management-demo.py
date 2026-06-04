"""Render the treaty lifecycle management transcript."""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_GIF_OUTPUT = (
    ROOT / "docs/examples/assets/images/genesis-mesh-treaty-lifecycle-management.gif"
)
DEFAULT_PNG_OUTPUT = (
    ROOT / "docs/examples/assets/images/genesis-mesh-treaty-lifecycle-management.png"
)


def recorded_transcript() -> list[str]:
    """Return the treaty lifecycle management transcript."""
    return [
        "==> treaty list",
        "    treaty:       6c7f3d5c-0c5c-4c5f-9f7e-7f2a10bb7e91",
        "      from/to:    USG -> USG-NB",
        "      status:     active / active",
        "      expiry:     low at 2026-06-06T13:42:05Z",
        "      roles:      role:service:maintainer",
        "",
        "==> treaty inspect",
        "    scope:",
        "      roles:             role:service:maintainer",
        "      accepted statuses: active",
        "      claims:            {'proof': 'operator-onboarding'}",
        "    metadata: {'subject_endpoint': 'http://164.92.250.135:8443'}",
        "",
        "==> expiring treaty classification",
        "    status:     active / expiring_soon",
        "    expiry:     high at 2026-06-05T15:00:00Z",
        "    operator action: renew or replace before expiry",
        "",
        "==> treaty replace",
        "    old: 6c7f3d5c-0c5c-4c5f-9f7e-7f2a10bb7e91",
        "    new: 8a2f5a98-3e5d-4c61-a975-1d7d0c5f3b6a",
        "    old lifecycle: replaced",
        "    old reason: replaced_by:8a2f5a98-3e5d-4c61-a975-1d7d0c5f3b6a",
        "",
        "==> Connectome recognition edge",
        "    from/to: USG -> USG-NB",
        "    lifecycle: active",
        "    expiry risk: low",
        "    valid from: 2026-06-05 13:42 UTC",
        "    expires at: 2026-06-06 13:42 UTC",
        "",
        "==> revoke without successor",
        "    status: revoked",
        "    reason: relationship_ended",
        "    Connectome active_edge_count: 0",
        "",
        "Result: treaty lifecycle is visible without changing direct-recognition semantics.",
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
    draw.text((margin, 19), "Genesis Mesh treaty lifecycle management", fill="#e8edf4", font=bold)
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
        elif "replaced" in text or "revoked" in text:
            color = "#facc15"
            selected_font = bold
        elif "active / active" in text or "expiry risk: low" in text:
            color = "#86efac"
            selected_font = bold
        elif "expiring_soon" in text or "expiry:     high" in text:
            color = "#fbbf24"
            selected_font = bold
        elif "USG" in text or "treaty" in text.lower():
            color = "#c4b5fd"
        draw.text((margin, y), text, fill=color, font=selected_font)
        y += line_height
    return img


def render_png(lines: list[str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    visible = _wrapped_lines(lines)[-34:]
    _render_terminal_frame(visible, 1180, 850).save(output)


def render_gif(lines: list[str], output: Path) -> None:
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
