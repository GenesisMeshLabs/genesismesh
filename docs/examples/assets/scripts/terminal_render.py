"""Shared terminal-frame rendering for Genesis Mesh demo scripts.

Each demo script imports this module, runs protocol operations, collects a
transcript (list of strings), then calls ``render_gif`` and ``render_png``.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

_FONT = "C:/Windows/Fonts/consola.ttf"
_BOLD = "C:/Windows/Fonts/consolab.ttf"
_FONT_SIZE = 17

BG = "#07111f"
HDR = "#111827"
C_DEFAULT = "#d1d5db"
C_STEP = "#93c5fd"
C_OK = "#86efac"
C_ERROR = "#fca5a5"
C_DIM = "#9ca3af"
C_SIGN = "#c4b5fd"
C_WARN = "#fbbf24"


def _fonts():
    try:
        return (
            ImageFont.truetype(_FONT, _FONT_SIZE),
            ImageFont.truetype(_BOLD, _FONT_SIZE),
        )
    except Exception:
        f = ImageFont.load_default()
        return f, f


def _line_color(line: str) -> tuple[str, bool]:
    if line.startswith("==>"):
        return C_STEP, True
    if "VERIFIED" in line or line.startswith("OK:") or " ✓" in line:
        return C_OK, True
    if (
        "BLOCKED" in line
        or line.startswith("ERROR:")
        or "FAILED" in line
        or "REJECTED" in line
        or line.startswith("  [FAIL]")
    ):
        return C_ERROR, True
    if line.startswith("  sig:") or line.startswith("SIGNED:") or "digest:" in line.lower():
        return C_SIGN, False
    if line.startswith("WARNING:") or line.startswith("  [WARN]"):
        return C_WARN, False
    if line.startswith("  ") or line.startswith("    "):
        return C_DIM, False
    return C_DEFAULT, False


def _frame(visible: list[str], title: str, width: int, height: int) -> "Image.Image":
    font, bold = _fonts()
    margin, lh = 28, 24
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width, 54), fill=HDR)
    draw.text((margin, 18), title, fill="#e5e7eb", font=bold)
    draw.ellipse((width - 88, 20, width - 76, 32), fill="#ef4444")
    draw.ellipse((width - 66, 20, width - 54, 32), fill="#f59e0b")
    draw.ellipse((width - 44, 20, width - 32, 32), fill="#22c55e")
    y = 78
    for line in visible:
        if y + lh > height - 8:
            break
        color, use_bold = _line_color(line)
        draw.text((margin, y), line, fill=color, font=bold if use_bold else font)
        y += lh
    return img


def _wrap(transcript: list[str], max_w: int = 92) -> list[str]:
    out: list[str] = []
    for line in transcript:
        if not line:
            out.append("")
        else:
            wrapped = textwrap.wrap(line, max_w, replace_whitespace=False)
            out.extend(wrapped if wrapped else [""])
    return out


def _dims(n_lines: int, width: int) -> tuple[int, int]:
    visible = min(n_lines, 46)
    height = max(500, 78 + visible * 24 + 28)
    return visible, height


def render_gif(transcript: list[str], title: str, output: Path, width: int = 1120) -> None:
    if not PIL_AVAILABLE:
        print("PIL not available; skipping GIF render")
        return
    wrapped = _wrap(transcript)
    visible, height = _dims(len(wrapped), width)
    frames = [
        _frame(wrapped[max(0, i - visible) : i], title, width, height)
        for i in range(1, len(wrapped) + 1)
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        str(output),
        save_all=True,
        append_images=frames[1:],
        duration=380,
        loop=0,
        optimize=True,
    )


def render_png(transcript: list[str], title: str, output: Path, width: int = 1120) -> None:
    if not PIL_AVAILABLE:
        return
    wrapped = _wrap(transcript)
    visible, height = _dims(len(wrapped), width)
    _frame(wrapped[-visible:], title, width, height).save(str(output))
