# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pillow==12.3.0"]
# ///
"""Render original README covers. Motion is conceptual, never measurement data."""

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1440, 570
FONT_ROOT = Path("/usr/share/fonts/truetype/dejavu")


def font(size: int, *, serif: bool = False, mono: bool = False, bold: bool = False):
    family = "DejaVuSansMono" if mono else "DejaVuSerif" if serif else "DejaVuSans"
    suffix = "-Bold" if bold else ""
    return ImageFont.truetype(str(FONT_ROOT / f"{family}{suffix}.ttf"), size)


def text(draw, xy, value, size, color, **kw):
    draw.text(xy, value, font=font(size, **kw), fill=color, stroke_width=0)


def spaced(draw, xy, value, size, color, tracking=3):
    x, y = xy
    f = font(size, mono=True)
    for letter in value:
        draw.text((x, y), letter, font=f, fill=color)
        x += draw.textlength(letter, font=f) + tracking


def arrow(draw, x1, y1, x2, y2, color, width=2):
    draw.line((x1, y1, x2, y2), fill=color, width=width)
    angle = math.atan2(y2 - y1, x2 - x1)
    for offset in [-0.65, 0.65]:
        draw.line(
            (x2, y2, x2 - 10 * math.cos(angle + offset), y2 - 10 * math.sin(angle + offset)),
            fill=color,
            width=width,
        )


def cover(project: str):
    trust = project == "trusttrace"
    bg, ink, muted, accent, rule = (
        ("#2B2024", "#FFF4E6", "#C6AAA4", "#EDB777", "#70554E")
        if trust
        else ("#142A2E", "#EEF8F2", "#A3BDBB", "#A8DCCB", "#47656A")
    )
    image = Image.new("RGB", (WIDTH, HEIGHT), bg)
    d = ImageDraw.Draw(image)
    # Strict editorial grid; every lower element belongs to the project diagram.
    d.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline=rule, width=2)
    d.line((66, 99, 1374, 99), fill=rule, width=1)
    spaced(
        d,
        (66, 51),
        "TRUST / REQUIREMENTS / ARCHITECTURE" if trust else "QUALITY / ENERGY / PLACEMENT",
        18,
        muted,
        2,
    )
    text(d, (1105, 51), "INDEPENDENT RESEARCH", 17, muted, mono=True)
    title = "TrustTrace" if trust else "ContinuumBench"
    text(d, (61, 125), title, 104 if trust else 99, ink, serif=trust, bold=not trust)
    text(
        d,
        (68, 263),
        "A visible chain from stakeholder concern to software evidence."
        if trust
        else "Auditable model placement across the computing continuum.",
        29,
        muted,
    )
    if trust:
        labels = [
            ("Concern", "AUTHORED CONTEXT"),
            ("Requirement", "TYPED CONTRACT"),
            ("Decision", "RECORDED CHOICE"),
            ("Component", "SOFTWARE BOUNDARY"),
            ("Scenario", "EXECUTED TEST"),
        ]
        lefts = [68, 336, 604, 872, 1140]
        for i, (label, sub) in enumerate(labels):
            x = lefts[i]
            d.rectangle((x, 358, x + 230, 450), outline=rule, width=1)
            text(d, (x + 18, 374), label, 25, ink)
            text(d, (x + 18, 415), sub, 12, muted, mono=True)
            if i < 4:
                arrow(d, x + 238, 402, lefts[i + 1] - 10, 402, muted)
        d.line((68, 474, 1370, 474), fill=rule, width=1)
        text(d, (68, 511), "CONCEPTUAL TRUST CHAIN", 15, muted, mono=True)
        text(d, (1124, 511), "PROTOTYPE / B10 PENDING", 15, muted, mono=True)
    else:
        # A policy branches to three potential tiers. Only a placement concept is shown.
        lefts = [446, 770, 1094]
        text(d, (68, 363), "Placement", 26, ink, bold=True)
        text(d, (68, 399), "policy", 26, ink, bold=True)
        d.line((280, 402, 363, 402), fill=rule, width=2)
        d.line((363, 338, 363, 470), fill=rule, width=2)
        specs = [
            ("Device", "LOCAL TARGET"),
            ("Emulated edge", "SAME-HOST CONTAINER"),
            ("Cloud", "PROVIDER UNSELECTED"),
        ]
        for i, (label, sub) in enumerate(specs):
            x = lefts[i]
            d.rectangle((x, 365, x + 278, 448), outline=rule, width=1)
            text(d, (x + 18, 379), label, 24, ink)
            text(d, (x + 18, 420), sub, 13, muted, mono=True)
            y = 338 if i == 0 else 350 if i == 1 else 470
            d.line((363, y, x + 139, y), fill=rule, width=1)
            arrow(d, x + 139, y, x + 139, 357 if i < 2 else 456, rule, 1)
        d.line((68, 494, 1372, 494), fill=rule, width=1)
        text(d, (68, 518), "CONCEPTUAL PLACEMENT", 15, muted, mono=True)
        text(d, (1107, 518), "MEASUREMENTS PENDING", 15, muted, mono=True)
    return image, accent, lefts


def render(project: str, output: Path):
    base, accent, lefts = cover(project)
    output.mkdir(parents=True, exist_ok=True)
    base.save(output / "hero-static.png", optimize=True)
    # Palette comes from the poster plus the actual accent used by the animation.
    sample = base.copy()
    ImageDraw.Draw(sample).rectangle((0, 0, 30, 30), fill=accent)
    palette = sample.quantize(colors=192, method=Image.Quantize.MEDIANCUT)
    frames = []
    for frame in range(54):
        image = base.copy()
        d = ImageDraw.Draw(image)
        t = frame / 53
        if project == "trusttrace":
            x = 68 + 1302 * t
            d.line((68, 474, int(x), 474), fill=accent, width=3)
            d.ellipse((x - 5, 469, x + 5, 479), fill=accent)
            selected = min(4, int(t * 5))
            xnode = lefts[selected]
            d.line((xnode, 450, xnode + 230, 450), fill=accent, width=3)
        else:
            selected = min(2, int(t * 3))
            x = lefts[selected]
            d.rectangle((x, 365, x + 278, 448), outline=accent, width=2)
            y = [338, 350, 470][selected]
            arrow(d, 363, y, x + 139, y, accent, 2)
            arrow(d, x + 139, y, x + 139, 357 if selected < 2 else 456, accent, 2)
            phase = (t * 3) % 1
            px = 363 + (x + 139 - 363) * phase
            d.ellipse((px - 4, y - 4, px + 4, y + 4), fill=accent)
        frames.append(image.quantize(palette=palette, dither=Image.Dither.NONE))
    frames[0].save(
        output / "hero.gif",
        save_all=True,
        append_images=frames[1:],
        duration=150,
        loop=1,
        optimize=True,
        disposal=1,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", choices=["trusttrace", "continuum-bench"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--font-dir",
        type=Path,
        default=FONT_ROOT,
        help="Directory containing DejaVu font files; fonts are not redistributed.",
    )
    args = parser.parse_args()
    FONT_ROOT = args.font_dir
    render(args.project, args.output)
