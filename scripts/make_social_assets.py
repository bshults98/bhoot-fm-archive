"""Generate social-share PNGs from the ghost favicon design.

Run once (or any time the visuals change):

    python scripts/make_social_assets.py

Outputs into static/:
    og-image.png            1200×630  (Open Graph / Twitter card)
    apple-touch-icon.png     180×180  (iOS home-screen icon)
    favicon-32.png            32×32   (fallback for clients that can't do SVG)

Requires Pillow. Not in production requirements — this is a build-time tool.
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static"
OUT.mkdir(exist_ok=True)


def _radial_bg(size, inner=(22, 6, 8), outer=(7, 7, 11)):
    """Create a radial-gradient background by drawing concentric rings."""
    W, H = size
    img = Image.new("RGB", size, outer)
    px = img.load()
    cx, cy = W / 2, H * 0.42
    max_r = ((max(cx, W - cx)) ** 2 + (max(cy, H - cy)) ** 2) ** 0.5
    for y in range(H):
        for x in range(W):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            t = min(1.0, d / max_r)
            # Quadratic falloff so the centre stays bright but the edges go black.
            t = t * t
            r = int(inner[0] * (1 - t) + outer[0] * t)
            g = int(inner[1] * (1 - t) + outer[1] * t)
            b = int(inner[2] * (1 - t) + outer[2] * t)
            px[x, y] = (r, g, b)
    return img


def _draw_ghost(draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: float):
    """Draw the same one-eyed ghost as the favicon, centred at (cx, cy)."""
    s = scale  # 1.0 → 64 px tall (the favicon's native size)
    # Body: dome + wavy hem. Coordinates are the favicon's, offset to (cx, cy).
    def P(x, y):
        return (cx + (x - 32) * s, cy + (y - 32) * s)

    body = [
        P(12, 30),
        # dome
        *[P(12 + 20 * (1 - (1 - i / 10) ** 2), 30 - 18 * (i / 10))
          for i in range(0, 11)],
        *[P(32 + 20 * (i / 10), 30 - 18 * (1 - (i / 10) ** 2))
          for i in range(0, 11)],
        # straight right side
        P(52, 52),
        # tattered hem (5 scallops)
        P(48, 46), P(44, 52), P(40, 46), P(36, 52),
        P(32, 46), P(28, 52), P(24, 46), P(20, 52),
        P(16, 46), P(12, 52),
    ]
    draw.polygon(body, fill=(232, 228, 220, 240))

    # Glowing red eye — three nested ellipses.
    eye_cx, eye_cy = cx, cy - 2 * s
    rx, ry = 9 * s, 11 * s
    # Outer halo glow drawn on a separate layer for blur.
    glow = Image.new("RGBA", (int(rx * 6), int(ry * 6)), (0, 0, 0, 0))
    g_d = ImageDraw.Draw(glow)
    gcx, gcy = glow.size[0] / 2, glow.size[1] / 2
    g_d.ellipse(
        [gcx - rx * 1.6, gcy - ry * 1.6, gcx + rx * 1.6, gcy + ry * 1.6],
        fill=(255, 50, 60, 180),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=rx * 0.4))
    return glow, (eye_cx, eye_cy, rx, ry)


def _font(size: int, bold: bool = False):
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except OSError:
                continue
    return ImageFont.load_default()


def make_og_image():
    W, H = 1200, 630
    img = _radial_bg((W, H))
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Ghost on the left.
    ghost_cx, ghost_cy = 270, 320
    glow, (ecx, ecy, rx, ry) = _draw_ghost(draw, ghost_cx, ghost_cy, scale=4.2)

    # Composite the glow under the ghost's eye.
    img.paste(glow, (int(ecx - glow.size[0] / 2), int(ecy - glow.size[1] / 2)), glow)
    # Re-draw the ghost on top (we drew into overlay).
    img.paste(overlay, (0, 0), overlay)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    # Eye itself (pupil + highlight) — draw on overlay so blur stays underneath.
    draw.ellipse([ecx - rx, ecy - ry, ecx + rx, ecy + ry], fill=(255, 64, 64, 255))
    draw.ellipse([ecx - rx * 0.45, ecy - ry * 0.55, ecx + rx * 0.45, ecy + ry * 0.55],
                 fill=(10, 0, 0, 255))
    draw.ellipse([ecx - rx * 0.22 - 4, ecy - ry * 0.45 - 4,
                  ecx - rx * 0.22 + 2, ecy - ry * 0.45 + 2],
                 fill=(255, 255, 255, 230))
    # Tiny mouth
    mx, my = ghost_cx, ghost_cy + 12 * 4.2 / 1.0
    draw.ellipse([mx - 9, my - 12, mx + 9, my + 12], fill=(20, 4, 8, 255))

    # Title text — right side.
    tx = 540
    f_title = _font(86, bold=True)
    f_accent = _font(86, bold=False)
    f_sub_en = _font(34, bold=False)
    f_sub_bn = _font(34, bold=False)

    draw.text((tx, 180), "Bhoot FM", font=f_title, fill=(232, 227, 232, 255))
    # Measure "Bhoot FM " width so "Archive" lines up on the next line.
    draw.text((tx, 270), "Archive", font=f_accent, fill=(255, 87, 87, 255))

    draw.text((tx, 388), "Bangla horror radio · 2007–present",
              font=f_sub_en, fill=(200, 188, 184, 235))
    draw.text((tx, 432), "RJ Russell · Radio Foorti 88.0 FM",
              font=f_sub_en, fill=(170, 160, 158, 220))
    draw.text((tx, 488), "every episode, searchable",
              font=_font(28, bold=False), fill=(255, 87, 87, 200))

    # Subtle bottom rule.
    draw.line([(80, H - 60), (W - 80, H - 60)], fill=(80, 28, 36, 220), width=1)

    img.paste(overlay, (0, 0), overlay)
    out = OUT / "og-image.png"
    img.save(out, optimize=True)
    print(f"wrote {out}  ({out.stat().st_size // 1024} KB)")


def make_icon(size: int, name: str):
    """Re-create the favicon as a PNG at the requested size."""
    W = H = size
    img = Image.new("RGBA", (W, H), (7, 7, 11, 255))
    # Rounded dark background.
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, W, H], radius=int(W * 0.18), fill=255)
    bg = Image.new("RGBA", (W, H), (7, 7, 11, 255))
    # Soft inner glow.
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W * 0.1, H * 0.0, W * 0.9, H * 0.8],
               fill=(42, 6, 8, 255))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=W * 0.18))
    bg.paste(glow, (0, 0), glow)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    # Ghost scaled to the icon. The favicon was tuned for 64 px.
    scale = W / 64
    glow_eye, (ecx, ecy, rx, ry) = _draw_ghost(draw, W / 2, H * 0.52, scale)
    bg.paste(overlay, (0, 0), overlay)

    # Eye glow + pupil + highlight.
    bg.paste(glow_eye, (int(ecx - glow_eye.size[0] / 2),
                       int(ecy - glow_eye.size[1] / 2)), glow_eye)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.ellipse([ecx - rx, ecy - ry, ecx + rx, ecy + ry], fill=(255, 64, 64, 255))
    draw.ellipse([ecx - rx * 0.45, ecy - ry * 0.55,
                  ecx + rx * 0.45, ecy + ry * 0.55],
                 fill=(10, 0, 0, 255))
    draw.ellipse([ecx - rx * 0.30, ecy - ry * 0.55,
                  ecx - rx * 0.30 + max(2, scale * 1.5),
                  ecy - ry * 0.55 + max(2, scale * 1.5)],
                 fill=(255, 255, 255, 230))
    bg.paste(overlay, (0, 0), overlay)

    out_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out_img.paste(bg, (0, 0), mask)
    out = OUT / name
    out_img.save(out, optimize=True)
    print(f"wrote {out}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    make_og_image()
    make_icon(180, "apple-touch-icon.png")
    make_icon(32, "favicon-32.png")
