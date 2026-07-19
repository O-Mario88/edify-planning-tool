import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase

ICON_DIR = Path(settings.STATICFILES_DIRS[0]) / "icons"


class ManifestTest(TestCase):
    """Chrome will not offer to install without these exact properties."""

    def test_manifest_is_served_with_the_right_content_type(self):
        res = self.client.get("/manifest.webmanifest")
        self.assertEqual(res.status_code, 200)
        # Browsers ignore a manifest served as text/plain or text/html.
        self.assertIn("manifest+json", res["Content-Type"])

    def test_manifest_declares_what_installability_requires(self):
        data = json.loads(self.client.get("/manifest.webmanifest").content)
        self.assertTrue(data["name"])
        self.assertTrue(data["short_name"])
        self.assertEqual(data["start_url"], "/")
        # "browser" display would install as a shortcut, not an app window.
        self.assertIn(data["display"], {"standalone", "fullscreen", "minimal-ui"})
        sizes = {i["sizes"] for i in data["icons"]}
        self.assertIn("192x192", sizes)
        self.assertIn("512x512", sizes)

    def test_manifest_includes_maskable_icons(self):
        """Without these Android crops the circle straight through the logo."""
        data = json.loads(self.client.get("/manifest.webmanifest").content)
        maskable = [i for i in data["icons"] if i.get("purpose") == "maskable"]
        self.assertGreaterEqual(len(maskable), 1)

    def test_every_declared_icon_actually_resolves(self):
        """A manifest that names a missing icon silently blocks installation."""
        data = json.loads(self.client.get("/manifest.webmanifest").content)
        missing = []
        for icon in data["icons"]:
            name = icon["src"].rsplit("/", 1)[-1]
            if not (ICON_DIR / name).exists():
                missing.append(icon["src"])
        self.assertEqual(
            missing, [], f"manifest names icons that do not exist: {missing}"
        )


class ServiceWorkerTest(TestCase):
    def test_worker_is_served_from_the_site_root(self):
        """Scope follows the serving path.

        At /static/js/sw.js the worker would only control /static/js/, so it
        could never control the app. Serving it at /sw.js scopes it to the
        whole origin.
        """
        res = self.client.get("/sw.js")
        self.assertEqual(res.status_code, 200)
        self.assertIn("javascript", res["Content-Type"])
        self.assertEqual(res["Service-Worker-Allowed"], "/")

    def test_worker_only_caches_static_assets(self):
        """This app is authenticated; caching HTML is a correctness bug.

        A cached page could be handed to a different signed-in user and would
        carry a stale CSRF token. The worker must bail out of anything that is
        not a same-origin GET under /static/.
        """
        body = self.client.get("/sw.js").content.decode()
        self.assertIn("req.method !== 'GET'", body)
        self.assertIn("url.origin !== self.location.origin", body)
        self.assertIn("startsWith('/static/')", body)


class PwaHeadTest(SimpleTestCase):
    ROOT = Path(settings.BASE_DIR)

    def _read(self, rel):
        return (self.ROOT / rel).read_text(encoding="utf-8")

    def test_both_layouts_include_the_pwa_head(self):
        """Installability is judged per page, and sign-in is the first one.

        Wiring only the signed-in shell makes the app installable only after
        logging in, which is not a state most users will discover.
        """
        for layout in ("templates/base.html", "templates/layouts/login.html"):
            self.assertIn("partials/pwa_head.html", self._read(layout), layout)

    def test_head_declares_the_ios_icon(self):
        """iOS ignores manifest icons and reads apple-touch-icon instead."""
        head = self._read("templates/partials/pwa_head.html")
        self.assertIn("apple-touch-icon", head)
        self.assertIn('rel="manifest"', head)


class IconAssetTest(SimpleTestCase):
    REQUIRED = [
        "icon-192.png",
        "icon-512.png",
        "icon-maskable-192.png",
        "icon-maskable-512.png",
        "apple-touch-icon.png",
        "favicon.ico",
    ]

    def test_generated_icon_set_is_present(self):
        missing = [n for n in self.REQUIRED if not (ICON_DIR / n).exists()]
        self.assertEqual(
            missing, [], f"run `manage.py build_app_icons`; missing: {missing}"
        )

    def test_all_icons_are_square(self):
        from PIL import Image

        for name in self.REQUIRED:
            if name.endswith(".ico"):
                continue
            w, h = Image.open(ICON_DIR / name).size
            self.assertEqual(w, h, f"{name} is not square")

    def test_standard_icons_have_a_transparent_surround(self):
        """The rounded silhouette sits on whatever is behind it."""
        from PIL import Image

        for name in ("icon-192.png", "icon-512.png", "favicon-32.png"):
            img = Image.open(ICON_DIR / name)
            self.assertEqual(img.mode, "RGBA", f"{name} has no alpha channel")
            px = img.convert("RGBA").load()
            w, h = img.size
            for x, y in ((1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2)):
                # Generous threshold on purpose. Downscaling a rounded edge to
                # 32px averages the anti-aliased boundary into the corner
                # pixel -- favicon-32 lands around alpha 15 with nothing wrong.
                # The regression this guards against is a corner going opaque,
                # so anything far below 255 is the pass condition.
                self.assertLess(
                    px[x, y][3], 64, f"{name} corner ({x},{y}) is not transparent"
                )
            self.assertEqual(
                px[w // 2, h // 2][3], 255, f"{name} centre must stay opaque"
            )

    def test_ios_and_maskable_icons_stay_opaque(self):
        """These two must NOT be transparent, for different reasons.

        iOS does not honour alpha in a home-screen icon -- it composites
        transparent pixels against black, so a transparent apple-touch-icon
        renders with black corners. A maskable icon is specified to fill its
        frame because the launcher crops a circle out of it, so alpha there
        shows the launcher background through the crop.
        """
        from PIL import Image

        for name in (
            "apple-touch-icon.png",
            "icon-maskable-192.png",
            "icon-maskable-512.png",
        ):
            img = Image.open(ICON_DIR / name)
            w, h = img.size
            if img.mode == "RGBA":
                px = img.load()
                for x, y in ((1, 1), (w - 2, h - 2)):
                    self.assertEqual(px[x, y][3], 255, f"{name} must be fully opaque")
            px = img.convert("RGB").load()
            for x, y in ((1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2)):
                r, g, b = px[x, y]
                self.assertLess(
                    (r + g + b) / 3,
                    200,
                    f"{name} corner ({x},{y}) is light -- the white surround "
                    f"is showing through again",
                )
