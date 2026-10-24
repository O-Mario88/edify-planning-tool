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
SPLASH_BLUE = (10, 77, 134)  # --brand-primary-hover (#0a4d86), Home's header
DISC_SHARE = 0.71  # the disc's share of the PWA maskable icon's width
FOREGROUND_DISC_SHARE = 0.6  # inside Android's adaptive-icon safe zone


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


def splash(width: int, height: int) -> Image.Image:
    canvas = Image.new("RGB", (width, height), SPLASH_BLUE)
    logo = Image.open(LOGO).convert("RGBA")
    target = round(min(width, height) * 0.32)
    logo = logo.resize(
        (target, round(logo.height * target / logo.width)), Image.LANCZOS
    )
    canvas.paste(logo, ((width - logo.width) // 2, (height - logo.height) // 2), logo)
    return canvas


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
    background = res / "values" / "ic_launcher_background.xml"
    background.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        '    <color name="ic_launcher_background">#2D4862</color>\n</resources>\n'
    )


if __name__ == "__main__":
    main()
