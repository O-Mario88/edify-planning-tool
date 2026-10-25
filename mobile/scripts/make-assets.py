"""App icons and launch screens for the iOS and Android projects, from the
approved Edify artwork the web app already ships (static/images/).

    ../.venv/bin/python scripts/make-assets.py

Every file it writes already exists in the generated native projects; it keeps
each one's size and replaces its picture, so it can be run again after
`npx cap add` or a Capacitor upgrade.
"""

from pathlib import Path

from PIL import Image, ImageDraw

MOBILE = Path(__file__).resolve().parents[1]
REPO = MOBILE.parent
ARTWORK = REPO / "static" / "images" / "app-icon-source.png"  # disc on black
LOGO = REPO / "static" / "images" / "logo.png"  # white wordmark
ICON_NAVY = (45, 72, 98)  # the PWA icon's background (#2d4862)
# The launch screen is the sidebar's own band (owner, 2026-10-24: Home's header
# takes "the same sidebar background blue"): --edify-sidebar-bg's stops, top
# to bottom — navy-950 (#001d39), #062847 at 56%, navy-800 (#0a4d86).
SPLASH_STOPS = ((0.0, (0, 29, 57)), (0.56, (6, 40, 71)), (1.0, (10, 77, 134)))
DISC_SHARE = 0.71  # the disc's share of the PWA maskable icon's width
FOREGROUND_DISC_SHARE = 0.6  # inside Android's adaptive-icon safe zone
# Android's notification icon is a one-colour silhouette in a 24dp square with
# 2dp of padding, so it is the wordmark's "e" alone: the whole word would be
# too small to read in the status bar. The "e" ends before x=68 in logo.png.
LETTER_E = (0, 0, 68, 123)
NOTIFICATION_ICON_SIZES = {
    "mdpi": 24,
    "hdpi": 36,
    "xhdpi": 48,
    "xxhdpi": 72,
    "xxxhdpi": 96,
}


def disc(size: int) -> Image.Image:
    """The artwork's round badge, `size` px across, on transparency."""
    art = Image.open(ARTWORK).convert("RGBA")
    width = art.width
    row = [art.getpixel((x, width // 2)) for x in range(width)]
    left = next(i for i, p in enumerate(row) if sum(p[:3]) > 60)
    right = width - 1 - next(i for i, p in enumerate(reversed(row)) if sum(p[:3]) > 60)
    badge = art.crop((left, left, right + 1, right + 1)).resize(
        (size, size), Image.LANCZOS
    )
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    badge.putalpha(mask.resize((size, size), Image.LANCZOS))
    return badge


def icon(size: int, *, background=ICON_NAVY, share=DISC_SHARE, round_mask=False):
    canvas = Image.new(
        "RGBA", (size, size), background + (255,) if background else (0, 0, 0, 0)
    )
    badge = disc(round(size * share))
    offset = (size - badge.width) // 2
    canvas.alpha_composite(badge, (offset, offset))
    if round_mask:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        canvas.putalpha(mask)
    return canvas


def band(width: int, height: int) -> Image.Image:
    """The sidebar's gradient, top to bottom."""
    column = Image.new("RGB", (1, height))
    for y in range(height):
        at = y / max(height - 1, 1)
        for (start, low), (end, high) in zip(SPLASH_STOPS, SPLASH_STOPS[1:]):
            if start <= at <= end:
                share = (at - start) / (end - start)
                column.putpixel(
                    (0, y),
                    tuple(round(a + (b - a) * share) for a, b in zip(low, high)),
                )
                break
    return column.resize((width, height), Image.NEAREST)


def splash(width: int, height: int) -> Image.Image:
    canvas = band(width, height)
    logo = Image.open(LOGO).convert("RGBA")
    target = round(min(width, height) * 0.32)
    logo = logo.resize(
        (target, round(logo.height * target / logo.width)), Image.LANCZOS
    )
    canvas.paste(logo, ((width - logo.width) // 2, (height - logo.height) // 2), logo)
    return canvas


def notification_icon(size: int) -> Image.Image:
    """The wordmark's white "e" on transparency, `size` px square. Android
    draws it as a silhouette in the status bar and tints it in the shade."""
    letter = Image.open(LOGO).convert("RGBA").crop(LETTER_E)
    letter = letter.crop(letter.getchannel("A").getbbox())
    inner = round(size * 20 / 24)
    scale = inner / max(letter.size)
    letter = letter.resize(
        (round(letter.width * scale), round(letter.height * scale)), Image.LANCZOS
    )
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(
        letter, ((size - letter.width) // 2, (size - letter.height) // 2)
    )
    return canvas


def notification_icons(res: Path) -> None:
    """res/drawable-<density>/ic_stat_edify.png, named in AndroidManifest.xml
    as Firebase's default notification icon."""
    for density, size in NOTIFICATION_ICON_SIZES.items():
        path = res / f"drawable-{density}" / "ic_stat_edify.png"
        path.parent.mkdir(exist_ok=True)
        notification_icon(size).save(path)
        print(f"{path.relative_to(MOBILE)} {size}x{size}")


def replace(path: Path, make) -> None:
    with Image.open(path) as current:
        size = current.size
    make(size).save(path)
    print(f"{path.relative_to(MOBILE)} {size[0]}x{size[1]}")


def main() -> None:
    ios = MOBILE / "ios" / "App" / "App" / "Assets.xcassets"
    # The App Store icon is opaque, no transparency allowed.
    replace(
        ios / "AppIcon.appiconset" / "AppIcon-512@2x.png",
        lambda s: icon(s[0]).convert("RGB"),
    )
    for path in sorted((ios / "Splash.imageset").glob("*.png")):
        replace(path, lambda s: splash(*s))

    res = MOBILE / "android" / "app" / "src" / "main" / "res"
    for path in sorted(res.glob("mipmap-*/ic_launcher.png")):
        replace(path, lambda s: icon(s[0]))
    for path in sorted(res.glob("mipmap-*/ic_launcher_round.png")):
        replace(path, lambda s: icon(s[0], round_mask=True))
    for path in sorted(res.glob("mipmap-*/ic_launcher_foreground.png")):
        replace(
            path, lambda s: icon(s[0], background=None, share=FOREGROUND_DISC_SHARE)
        )
    for path in sorted(res.glob("drawable*/splash.png")):
        replace(path, lambda s: splash(*s))
    notification_icons(res)
    background = res / "values" / "ic_launcher_background.xml"
    background.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        '    <color name="ic_launcher_background">#2D4862</color>\n</resources>\n'
    )


if __name__ == "__main__":
    main()
