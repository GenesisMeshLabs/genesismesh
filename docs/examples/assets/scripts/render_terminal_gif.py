"""Render a recorded terminal session as an animated GIF in the docs' house style.

Record the real output of a demo first, then render it:

    python render_terminal_gif.py session.txt out.gif --title "Genesis Mesh -- Pre-Issued Grants"

The session file is the captured output, one line per terminal line. Mark
how lines are coloured and where frames break with these prefixes. A prefix
only styles the line; it never changes the text:

    "==> "  step heading (blue, bold), and a frame break before it
    "$ "    a command that was typed (white)
    "!ok "  a success line (green); the prefix is removed
    "!no "  a refusal or failure line (red); the prefix is removed
    "!dim " a muted line; the prefix is removed
    "!pause" on its own line: a frame break without text

Each frame shows everything up to a break, so the GIF plays the session
step by step. The last frame is held longer.
"""
import argparse
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG = (7, 17, 31)
HEADER = (17, 24, 39)
TITLE = (139, 146, 159)
TEXT = (203, 213, 225)
DIM = (139, 146, 159)
BLUE = (147, 197, 253)
GREEN = (134, 239, 172)
RED = (252, 165, 165)
WHITE = (241, 245, 249)
DOTS = [(239, 68, 68), (244, 158, 46), (44, 196, 101)]

WIDTH = 1120
HEADER_H = 55
LINE_H = 24
PAD_X = 28
PAD_TOP = 18


def font(bold=False, size=15):
    names = ["consolab.ttf" if bold else "consola.ttf", "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"]
    dirs = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", Path("/usr/share/fonts/truetype/dejavu")]
    for d in dirs:
        for n in names:
            if (d / n).exists():
                return ImageFont.truetype(str(d / n), size)
    return ImageFont.load_default()


def parse(text):
    """Return (frames, styled_lines): frames are line counts at each break."""
    lines, breaks = [], []
    for raw in text.splitlines():
        if raw.strip() == "!pause":
            breaks.append(len(lines))
            continue
        style, body = "text", raw
        if raw.startswith("==> "):
            style = "step"
            if lines:
                breaks.append(len(lines))
        elif raw.startswith("$ "):
            style = "cmd"
        for prefix, name in (("!ok ", "ok"), ("!no ", "no"), ("!dim ", "dim")):
            if raw.startswith(prefix):
                style, body = name, raw[len(prefix):]
        lines.append((style, body))
    breaks.append(len(lines))
    frames = sorted(set(b for b in breaks if b > 0))
    return frames, lines


def wrap(body, max_chars):
    if len(body) <= max_chars:
        return [body]
    out = []
    while len(body) > max_chars:
        cut = body.rfind(" ", 0, max_chars)
        cut = cut if cut > max_chars // 2 else max_chars
        out.append(body[:cut])
        body = "    " + body[cut:].lstrip()
    out.append(body)
    return out


def render(session, out, title, step_ms=1400, last_ms=6000):
    frames, lines = parse(Path(session).read_text(encoding="utf-8"))
    regular, bold = font(), font(bold=True)
    char_w = regular.getlength("M")
    max_chars = int((WIDTH - 2 * PAD_X) / char_w)
    visual = []  # (source index, style, text)
    for i, (style, body) in enumerate(lines):
        for part in wrap(body, max_chars):
            visual.append((i, style, part))
    height = HEADER_H + PAD_TOP + LINE_H * len(visual) + PAD_TOP
    colours = {"step": BLUE, "cmd": WHITE, "ok": GREEN, "no": RED, "dim": DIM, "text": TEXT}
    images = []
    for upto in frames:
        im = Image.new("RGB", (WIDTH, height), BG)
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, WIDTH, HEADER_H), fill=HEADER)
        d.text((PAD_X, 18), title, font=bold, fill=WHITE)
        for k, colour in enumerate(DOTS):
            x = WIDTH - 88 + k * 22
            d.ellipse((x - 6, 20, x + 6, 32), fill=colour)
        y = HEADER_H + PAD_TOP
        for i, style, part in visual:
            if i >= upto:
                break
            d.text((PAD_X, y), part, font=bold if style in ("step", "ok", "no") else regular, fill=colours[style])
            y += LINE_H
        images.append(im.convert("P", palette=Image.ADAPTIVE, colors=64))
    durations = [step_ms] * (len(images) - 1) + [last_ms]
    images[0].save(out, save_all=True, append_images=images[1:], duration=durations, loop=0, optimize=True)
    print(f"{out}: {len(images)} frames, {WIDTH}x{height}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session")
    ap.add_argument("out")
    ap.add_argument("--title", required=True)
    ap.add_argument("--step-ms", type=int, default=1400)
    a = ap.parse_args()
    render(a.session, a.out, a.title, a.step_ms)
