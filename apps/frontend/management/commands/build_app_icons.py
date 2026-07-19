"""Generate the PWA icon set from one square source image.

Re-run after replacing ``static/images/app-icon-source.png``:

    python manage.py build_app_icons

Why the source is not used as-is: the artwork arrives as a rounded tile with a
white surround and a drop shadow. Both iOS and Android apply their *own* corner
mask to an app icon, so shipping a pre-rounded image gives you rounding inside
rounding with the white surround showing through the corners. The platforms
want a full-bleed square, so this fills the corners with the tile's own
background colour and drops the surround.

Android adaptive icons crop to a circle inscribed in the square, which would
bite into the logo, so the `maskable` variants scale the artwork into the
safe zone and pad with the same background.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

SOURCE = "images/app-icon-source.png"
OUT_DIR = "icons"

# "any" icons are shown as supplied; the platform rounds them.
ANY_SIZES = [192, 512]
# iOS home screen. iOS masks the corners itself.
APPLE_SIZE = 180
# Android adaptive. Content must sit inside the safe zone.
MASKABLE_SIZES = [192, 512]
FAVICONS = [16, 32, 48]
# Fraction of the frame the artwork occupies in a maskable icon. The spec's
# safe zone is a circle of 80% diameter; 0.78 keeps a little margin.
SAFE_ZONE = 0.78


class Command(BaseCommand):
    help = "Generate PWA/app icons from static/images/app-icon-source.png"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", default=None, help="Override the source image path"
        )

    def handle(self, *args, **options):
        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover
            raise CommandError("Pillow is required: pip install Pillow") from exc

        static_dir = Path(settings.STATICFILES_DIRS[0])
        src_path = Path(options["source"]) if options["source"] else static_dir / SOURCE
        if not src_path.exists():
            raise CommandError(
                f"No source icon at {src_path}. Save a square PNG there "
                f"(1024x1024 ideal, 512 minimum) and re-run."
            )

        img = Image.open(src_path).convert("RGB")
        tile, bg = self._extract_tile(img)
        out = static_dir / OUT_DIR
        out.mkdir(parents=True, exist_ok=True)
        written = []

        for size in ANY_SIZES:
            p = out / f"icon-{size}.png"
            tile.resize((size, size), Image.LANCZOS).save(p, optimize=True)
            written.append(p)

        for size in MASKABLE_SIZES:
            p = out / f"icon-maskable-{size}.png"
            self._maskable(tile, bg, size, Image).save(p, optimize=True)
            written.append(p)

        p = out / f"apple-touch-icon.png"
        tile.resize((APPLE_SIZE, APPLE_SIZE), Image.LANCZOS).save(p, optimize=True)
        written.append(p)

        for size in FAVICONS:
            p = out / f"favicon-{size}.png"
            tile.resize((size, size), Image.LANCZOS).save(p, optimize=True)
            written.append(p)

        ico = out / "favicon.ico"
        tile.resize((64, 64), Image.LANCZOS).save(
            ico, sizes=[(16, 16), (32, 32), (48, 48)]
        )
        written.append(ico)

        for p in written:
            self.stdout.write(
                f"  {p.relative_to(static_dir)}  {p.stat().st_size / 1024:.1f} KB"
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"  {len(written)} icons written · background #{bg[0]:02x}{bg[1]:02x}{bg[2]:02x}"
            )
        )

    # ── helpers ──────────────────────────────────────────────────────────────
    def _extract_tile(self, img):
        """Crop to the artwork and square off its rounded corners.

        The bounding box of non-white pixels includes the drop shadow, which
        makes it taller than it is wide, so the square is taken from the width
        and anchored at the top of the tile rather than centred on the box.
        """
        from PIL import Image

        w, h = img.size
        px = img.load()

        # Bound the crop by DARK pixels, not by non-white ones. A non-white
        # bound includes the drop shadow, which is grey rather than white, and
        # the shadow is uneven -- about 30px at the top against 82px at the
        # bottom. Bounding on non-white therefore left a pale band along the
        # bottom edge that no symmetric crop could remove. The tile itself is
        # the only dark region, so its own bounds are exact.
        def dark(p, t=170):
            return (p[0] + p[1] + p[2]) / 3 < t

        step = max(1, min(w, h) // 400)
        cols = [x for x in range(0, w, step) if any(dark(px[x, y]) for y in range(0, h, step))]
        rows = [y for y in range(0, h, step) if any(dark(px[x, y]) for x in range(0, w, step))]
        if not cols or not rows:
            # Nothing dark to find -- treat the image as already full-bleed.
            side = min(w, h)
            return img.crop((0, 0, side, side)), px[side // 2, side // 2]

        x0, x1, y0, y1 = cols[0], cols[-1], rows[0], rows[-1]
        # Largest square inside the dark bounds, centred on them.
        side = min(x1 - x0 + 1, y1 - y0 + 1)
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        left = max(0, min(cx - side // 2, w - side))
        top = max(0, min(cy - side // 2, h - side))
        tile = img.crop((left, top, left + side, top + side))

        # Take the most common non-light colour across the tile interior rather
        # than sampling a point. Both obvious points are wrong: a corner inset
        # lands outside the rounding in the white surround, and the left edge
        # at mid-height lands in the tile's soft shadow edge. Mid-height also
        # cuts through the white wordmark. The mode over the interior is
        # immune to all three.
        bg = self._background(tile, side)

        # Flood the surround away from each corner rather than masking a
        # rounded rectangle over it. The tile's edge is a gradient -- the drop
        # shadow measures ~30px at the top and ~82px at the bottom -- so no
        # single inset or corner radius clears it: too small leaves a white
        # halo ringing the icon, too large bites into the artwork. The flood
        # follows the actual edge. The white wordmark is enclosed by dark
        # pixels, so the fill cannot reach it.
        from PIL import ImageDraw

        flat = tile.copy()
        for corner in ((0, 0), (side - 1, 0), (0, side - 1), (side - 1, side - 1)):
            ImageDraw.floodfill(flat, corner, bg, thresh=90)
        return flat, bg

    def _background(self, tile, side):
        """Dominant non-light colour of the tile interior.

        The artwork is white on a dark ground, so filtering out light pixels
        leaves the ground itself; the mode of what remains is the fill colour.
        """
        import collections

        px = tile.load()
        lo, hi = int(side * 0.10), int(side * 0.90)
        step = max(1, side // 120)
        counts = collections.Counter()
        for x in range(lo, hi, step):
            for y in range(lo, hi, step):
                c = px[x, y]
                if (c[0] + c[1] + c[2]) / 3 < 170:  # skip the white artwork
                    counts[c] += 1
        if not counts:
            return px[side // 2, side // 2]
        return counts.most_common(1)[0][0]

    def _maskable(self, tile, bg, size, Image):
        """Scale the artwork into the adaptive-icon safe zone."""
        canvas = Image.new("RGB", (size, size), bg)
        inner = max(1, int(size * SAFE_ZONE))
        art = tile.resize((inner, inner), Image.LANCZOS)
        off = (size - inner) // 2
        canvas.paste(art, (off, off))
        return canvas
