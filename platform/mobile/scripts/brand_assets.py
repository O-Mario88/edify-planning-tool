"""Draws Edify's app icon, launch images and previews from the authentic logo.

Owner brief, 2026-11-11 ("Mandatory app icon, native launch screen &
authentication experience"): one visual identity across the app icon, launch
screen, sign-in screen and the app itself, built from the approved Edify logo,
never a new one.

The only artwork read is the web app's own logo (static/images/logo.png, the
white "edify" wordmark, 300 x 123). It is small, so its outline is rebuilt
rather than stretched: the anti-aliased edge is interpolated at ten times the
size, softened by about a pixel of the source and cut at half coverage, which
keeps the letterforms and their cut-ins while giving clean edges at any size.
Colours and the wave come from assets/brand/brand.json, which the app reads
too. Run from platform/mobile:

    python scripts/brand_assets.py

Pillow is the only dependency. The outputs are committed; rerun after a
brand change.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

MOBILE = Path(__file__).resolve().parent.parent
REPO = MOBILE.parent.parent
LOGO = REPO / "static" / "images" / "logo.png"
ASSETS = MOBILE / "assets"
BRAND = json.loads((ASSETS / "brand" / "brand.json").read_text())
FONT = (
    MOBILE
    / "node_modules"
    / "@expo-google-fonts"
    / "geist"
    / "700Bold"
    / "Geist_700Bold.ttf"
)

REBUILD_SCALE = 10
SUPERSAMPLE = 4
ICON = 1024
# Android adaptive icons: a 108 dp layer of which the middle 72 dp is seen.
ANDROID_VISIBLE = round(ICON * 72 / 108)
# The wordmark's share of the icon's width, and where its middle sits.
MARK_WIDTH = 0.60
MARK_CENTRE_Y = 0.43
# The web app's navy logo colour (assets/edify-logo-navy.png, sampled).
LOGO_NAVY = "#0a4d86"
IOS_CORNER = 0.2237


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def rebuilt_wordmark() -> Image.Image:
    """The logo's coverage, rebuilt sharp at ten times its size (L mode)."""
    alpha = Image.open(LOGO).convert("RGBA").getchannel("A")
    big = alpha.resize(
        (alpha.width * REBUILD_SCALE, alpha.height * REBUILD_SCALE), Image.LANCZOS
    )
    big = big.filter(ImageFilter.GaussianBlur(REBUILD_SCALE * 1.2))
    mask = big.point(lambda v: 255 if v >= 128 else 0)
    return mask.crop(mask.getbbox())


MASTER = rebuilt_wordmark()


def wordmark(width: int) -> Image.Image:
    """The wordmark's coverage at a width, smoothly anti-aliased."""
    height = round(MASTER.height * width / MASTER.width)
    return MASTER.resize((width, height), Image.LANCZOS)


def solid(size: tuple[int, int], colour: str, mask: Image.Image) -> Image.Image:
    """A colour cut to a mask, on transparent."""
    layer = Image.new("RGBA", size, hex_rgb(colour) + (0,))
    layer.putalpha(mask)
    return layer


def bezier(
    points: dict, x0: float, y0: float, box: float, steps: int = 240
) -> list[tuple[float, float]]:
    (ax, ay), (bx, by), (cx, cy), (dx, dy) = (
        points[k] for k in ("from", "c1", "c2", "to")
    )
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = u**3 * ax + 3 * u * u * t * bx + 3 * u * t * t * cx + t**3 * dx
        y = u**3 * ay + 3 * u * u * t * by + 3 * u * t * t * cy + t**3 * dy
        out.append((x0 + x * box / 1000, y0 + y * box / 1000))
    return out


def draw_waves(
    canvas: Image.Image, x0: float, y0: float, box: float, colours: tuple[str, str]
) -> None:
    """The two waves of the box, carried flat to the canvas's edges and bottom."""
    draw = ImageDraw.Draw(canvas)
    for name, colour in zip(("back", "front"), colours, strict=True):
        curve = bezier(BRAND["waves"][name], x0, y0, box)
        left, right = curve[0], curve[-1]
        shape = [
            (0, left[1]),
            *curve,
            (canvas.width, right[1]),
            (canvas.width, canvas.height),
            (0, canvas.height),
        ]
        draw.polygon(shape, fill=colour)


def place_mark(
    canvas: Image.Image, x0: float, y0: float, box: float, colour: str
) -> None:
    mark = wordmark(round(box * MARK_WIDTH))
    left = round(x0 + (box - mark.width) / 2)
    top = round(y0 + box * MARK_CENTRE_Y - mark.height / 2)
    canvas.alpha_composite(solid(mark.size, colour, mark), (left, top))


def render(size: int, paint) -> Image.Image:
    """Draws at four times the size and scales down, for smooth curves."""
    big = Image.new("RGBA", (size * SUPERSAMPLE, size * SUPERSAMPLE), (0, 0, 0, 0))
    paint(big, SUPERSAMPLE)
    return big.resize((size, size), Image.LANCZOS)


def icon(
    background: str | None,
    waves: tuple[str, str],
    mark: str,
    *,
    android: bool = False,
    with_mark: bool = True,
    with_waves: bool = True,
) -> Image.Image:
    def paint(canvas: Image.Image, k: int) -> None:
        full = ICON * k
        box = (ANDROID_VISIBLE if android else ICON) * k
        offset = (full - box) / 2
        if background:
            ImageDraw.Draw(canvas).rectangle((0, 0, full, full), fill=background)
        if with_waves:
            draw_waves(canvas, offset, offset, box, waves)
        if with_mark:
            place_mark(canvas, offset, offset, box, mark)

    return render(ICON, paint)


def lockup(px_per_dp: int) -> Image.Image:
    """'edify | Planning & Monitoring' in white, drawn as the Home header's."""
    mark = wordmark(round(30 * 300 / 123 * px_per_dp))
    font = ImageFont.truetype(str(FONT), 12 * px_per_dp)
    lines = ["Planning &", "Monitoring"]
    line_height = 15 * px_per_dp
    text_width = max(round(font.getlength(line)) for line in lines)
    gap, rule_height = 10 * px_per_dp, 28 * px_per_dp
    width = mark.width + gap + px_per_dp + gap + text_width
    height = max(mark.height, rule_height, line_height * 2)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.alpha_composite(
        solid(mark.size, BRAND["white"], mark), (0, (height - mark.height) // 2)
    )
    draw = ImageDraw.Draw(canvas)
    rule_x = mark.width + gap
    draw.rectangle(
        (
            rule_x,
            (height - rule_height) // 2,
            rule_x + px_per_dp - 1,
            (height + rule_height) // 2,
        ),
        fill=BRAND["rule"],
    )
    text_top = (height - line_height * 2) // 2
    for i, line in enumerate(lines):
        position = (
            rule_x + px_per_dp + gap,
            text_top + i * line_height + line_height // 2,
        )
        draw.text(position, line, font=font, fill=BRAND["product"], anchor="lm")
    return canvas


def masked(image: Image.Image, shape: str) -> Image.Image:
    """The icon cut to the shape a phone shows it in."""
    k = SUPERSAMPLE
    mask = Image.new("L", (image.width * k, image.height * k), 0)
    bounds = (0, 0, mask.width - 1, mask.height - 1)
    if shape == "circle":
        ImageDraw.Draw(mask).ellipse(bounds, fill=255)
    else:
        ImageDraw.Draw(mask).rounded_rectangle(
            bounds, radius=round(mask.width * IOS_CORNER), fill=255
        )
    out = image.convert("RGBA")
    out.putalpha(mask.resize(image.size, Image.LANCZOS))
    return out


def previews(light: Image.Image, android_full: Image.Image) -> Image.Image:
    """The icon at the sizes phones draw it, on light and dark wallpapers."""
    crop = (ICON - ANDROID_VISIBLE) // 2
    android_seen = android_full.crop(
        (crop, crop, crop + ANDROID_VISIBLE, crop + ANDROID_VISIBLE)
    )
    tiles = [("iOS", size, light, "rounded") for size in (180, 120, 87, 60, 40)]
    tiles += [("Android", size, android_seen, "circle") for size in (192, 144, 96, 48)]
    font = ImageFont.truetype(str(FONT), 20)
    sheet = Image.new("RGBA", (1560, 600))
    for row, (wallpaper, ink) in enumerate(
        (("#eef2f6", "#1c2733"), ("#10161d", "#e8eef4"))
    ):
        band = Image.new("RGBA", (1560, 300), wallpaper)
        draw = ImageDraw.Draw(band)
        x = 30
        for platform, size, source, shape in tiles:
            band.alpha_composite(
                masked(source.resize((size, size), Image.LANCZOS), shape),
                (x, 230 - size),
            )
            label = f"{platform} {size}"
            draw.text((x, 244), label, font=font, fill=ink)
            x += max(size, round(font.getlength(label))) + 34
        sheet.alpha_composite(band, (0, row * 300))
    return sheet


def logo_png(colour: str) -> Image.Image:
    """The in-app wordmark, three times the old 300 px file, same artwork."""
    mark = wordmark(900)
    return solid(mark.size, colour, mark)


def main() -> None:
    waves = (BRAND["waveBack"], BRAND["waveFront"])
    white = BRAND["white"]
    light = icon(BRAND["navy"], waves, white).convert("RGB")
    light.save(ASSETS / "icon.png")
    # iOS dark and tinted icons sit on the system's own dark backdrop.
    icon(None, waves, white).save(ASSETS / "icon-dark.png")
    icon(None, ("#9a9a9a", "#d4d4d4"), white).convert("LA").save(
        ASSETS / "icon-tinted.png"
    )
    # Android: navy and waves behind; the wordmark in front, inside the safe zone.
    background = icon(BRAND["navy"], waves, white, android=True, with_mark=False)
    background.convert("RGB").save(ASSETS / "android-icon-background.png")
    foreground = icon(None, waves, white, android=True, with_waves=False)
    foreground.save(ASSETS / "android-icon-foreground.png")
    foreground.save(ASSETS / "android-icon-monochrome.png")
    android_full = icon(BRAND["navy"], waves, white, android=True)
    # Launch: the lockup on iOS; the wordmark alone where Android 12+ masks
    # the launch image to a circle.
    lockup(6).save(ASSETS / "splash-lockup.png")
    splash = Image.new("RGBA", (ICON, ICON), (0, 0, 0, 0))
    place_mark(splash, 0, ICON * (0.5 - MARK_CENTRE_Y), ICON, white)
    splash.save(ASSETS / "splash-icon.png")
    masked(light.resize((196, 196), Image.LANCZOS), "rounded").save(
        ASSETS / "favicon.png"
    )
    logo_png(white).save(ASSETS / "edify-logo-white.png")
    logo_png(LOGO_NAVY).save(ASSETS / "edify-logo-navy.png")
    previews(light, android_full).save(ASSETS / "brand" / "previews" / "icon-sizes.png")
    print("written:", ", ".join(sorted(p.name for p in ASSETS.glob("*.png"))))


if __name__ == "__main__":
    main()
