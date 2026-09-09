import json
import os
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

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
        with override_settings(
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {
                    "BACKEND": (
                        "whitenoise.storage.CompressedManifestStaticFilesStorage"
                    )
                },
            }
        ):
            body = self.client.get("/sw.js").content.decode()
        self.assertIn("req.method !== 'GET'", body)
        self.assertIn("url.origin !== self.location.origin", body)
        self.assertIn("startsWith('/static/')", body)

    def test_nothing_is_cached_when_asset_names_are_not_content_hashed(self):
        """Cache-first is a promise that a URL identifies its bytes.

        Without a hashing storage the names are stable, so the first copy the
        worker sees is the copy it serves past every later edit — which is
        exactly what happened while verifying a stylesheet change: the browser
        kept handing back a pages.css from a previous build.
        """
        with override_settings(
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
                },
            }
        ):
            body = self.client.get("/sw.js").content.decode()
        # The fetch handler still exists for the navigation fallback, but the
        # static branch -- the only thing that stores a request's response --
        # is compiled out.
        self.assertNotIn("startsWith('/static/')", body)
        self.assertNotIn("caches.match(req)", body)
        self.assertNotIn("c.put(req", body)
        self.assertNotIn("html.matchAll", body)

    def test_offline_page_is_precached_and_serves_failed_navigations_in_both_builds(
        self,
    ):
        """The fallback is user-independent, so it is the one page the worker
        may hold -- in the hashed build and the passthrough build alike.

        Precached at install under a cache named for the worker version, so a
        deploy replaces it; served only when the network *fails* a navigation,
        never in place of an answer the app actually gave."""
        for backend in (
            "whitenoise.storage.CompressedManifestStaticFilesStorage",
            "django.contrib.staticfiles.storage.StaticFilesStorage",
        ):
            with (
                self.subTest(backend=backend),
                override_settings(
                    STORAGES={
                        "default": {
                            "BACKEND": "django.core.files.storage.FileSystemStorage"
                        },
                        "staticfiles": {"BACKEND": backend},
                    }
                ),
            ):
                body = self.client.get("/sw.js").content.decode()
            self.assertIn("const OFFLINE_URL = '/offline';", body)
            self.assertIn("const OFFLINE_CACHE = 'edify-offline-' + VERSION;", body)
            self.assertIn("c.add(new Request(OFFLINE_URL, { cache: 'reload' }))", body)
            self.assertIn("req.mode === 'navigate'", body)
            self.assertIn(
                "fetch(req).catch(() => caches.match(OFFLINE_URL, "
                "{ cacheName: OFFLINE_CACHE })",
                body,
            )
            # Activation must spare the fallback's cache or every deploy
            # would delete the page it just precached.
            self.assertIn("k !== CACHE && k !== OFFLINE_CACHE", body)
            self.assertIn('data-navigation-failed="true"', body)
            # Background Sync wakes open pages to replay the outbox.
            self.assertIn("event.tag !== OUTBOX_SYNC_TAG", body)
            self.assertIn("'edify-outbox-replay'", body)

    def test_hashed_build_precaches_the_assets_the_offline_page_links(self):
        """An unstyled fallback reads as a broken app. Content-hashed assets are
        immutable, so precaching the ones the page links is safe there -- and
        only there."""
        with override_settings(
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {
                    "BACKEND": (
                        "whitenoise.storage.CompressedManifestStaticFilesStorage"
                    )
                },
            }
        ):
            body = self.client.get("/sw.js").content.decode()
        self.assertIn("html.matchAll", body)
        self.assertIn("c.add(a).catch(() => null)", body)

    def test_the_cache_name_moves_with_the_assets(self):
        """`activate` deletes every cache that is not the current one, so a
        cache name that never changes is a cache that is never cleared. It was
        pinned to "edify-static-1" by a setting that was never defined."""
        from apps.frontend.views.pwa_views import static_version

        with override_settings(STATIC_ROOT="/nonexistent-for-this-test"):
            self.assertNotEqual(static_version(), "1")

        with mock.patch.dict(os.environ, {"RELEASE_SHA": "abcdef1234567890"}):
            self.assertEqual(static_version(), "abcdef123456")


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
        """The circular silhouette sits on whatever is behind it."""
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

    def test_standard_icons_have_a_true_circular_silhouette(self):
        """Desktop and non-maskable launchers receive an actual circle."""
        from PIL import Image

        for name in ("icon-192.png", "icon-512.png", "favicon-32.png"):
            alpha = Image.open(ICON_DIR / name).convert("RGBA").getchannel("A")
            bbox = alpha.getbbox()
            self.assertIsNotNone(bbox, f"{name} has no visible artwork")
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            self.assertLessEqual(abs(width - height), 2, f"{name} is not round")

            w, h = alpha.size
            # Ten percent in on the diagonal is outside a circle; eighteen
            # percent is inside. A rounded square is opaque at both points.
            self.assertLess(alpha.getpixel((round(w * 0.10), round(h * 0.10))), 64)
            self.assertGreater(alpha.getpixel((round(w * 0.18), round(h * 0.18))), 200)
            for point in (
                (w // 2, round(h * 0.08)),
                (w // 2, round(h * 0.92)),
                (round(w * 0.08), h // 2),
                (round(w * 0.92), h // 2),
            ):
                self.assertGreater(
                    alpha.getpixel(point),
                    200,
                    f"{name} circular edge is missing at {point}",
                )

    def test_ios_and_maskable_icons_stay_opaque(self):
        """These two must NOT be transparent, for different reasons.

        iOS does not honour alpha in a home-screen icon -- it composites
        transparent pixels against black, so a transparent apple-touch-icon
        renders with black corners. A maskable icon is specified to fill its
        frame because the launcher crops a circle out of it, so alpha there
        shows the launcher background through the crop.

        The surround is read from the generator rather than repeated here. It
        was a literal pale blue, which is how it survived being wrong: the
        maskable crop cut through that surround instead of through the
        artwork, so the launcher and the generated splash both drew a white
        ring around the logo. Pinning the constant keeps the two in step and
        leaves the *value* a design decision, not a test fixture.
        """
        from PIL import Image

        from apps.frontend.management.commands.build_app_icons import (
            OPAQUE_SURROUND,
        )

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
                self.assertEqual(
                    px[x, y],
                    OPAQUE_SURROUND,
                    f"{name} corner ({x},{y}) must use the circular-icon surround",
                )


class OfflinePageTest(TestCase):
    """The one page the worker stores, so the one page that must carry no user.

    It is precached by whichever session installs the worker and shown to
    whoever holds the phone afterwards. Anything session-specific in it would
    be handed across users -- which is the exact reason the worker caches no
    other page.
    """

    def test_renders_anonymously_with_the_platform_chrome(self):
        res = self.client.get("/offline")
        self.assertEqual(res.status_code, 200)
        body = res.content.decode()
        self.assertIn('<header class="edify-page-header">', body)
        self.assertIn('class="btn btn-primary h-8"', body)
        self.assertIn("data-offline-retry", body)
        # The queue lives in the phone's IndexedDB; the page leaves slots for
        # field-outbox.js to fill.
        self.assertIn("data-field-outbox-list", body)
        self.assertIn("data-field-outbox-count", body)
        self.assertIn("js/field-outbox.js", body)

    def test_carries_nothing_from_the_signed_in_session(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(
            email="offline-probe@edify.test",
            password="password123",
            name="Offline Probe Person",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.client.force_login(user)
        res = self.client.get("/offline")
        self.assertEqual(res.status_code, 200)
        body = res.content.decode()
        self.assertNotIn("Offline Probe Person", body)
        self.assertNotIn("offline-probe@edify.test", body)
        # base.html stamps the session's CSRF token on <body>; the fallback
        # blanks it so the precached copy carries no session's token.
        token = res.context["csrf_token"] if res.context else ""
        self.assertEqual(token, "")
        self.assertIn('hx-headers=\'{"X-CSRFToken": ""}\'', body)
        cookie_token = self.client.cookies.get("csrftoken")
        if cookie_token and cookie_token.value:
            self.assertNotIn(cookie_token.value, body)


class FieldOutboxWiringTest(SimpleTestCase):
    ROOT = Path(settings.BASE_DIR)

    def _read(self, rel):
        return (self.ROOT / rel).read_text(encoding="utf-8")

    def test_base_loads_the_outbox_with_a_cache_bust(self):
        """Every script in base.html is versioned so a deploy is not served the
        previous build's copy; the outbox is no exception."""
        base = self._read("templates/base.html")
        self.assertRegex(
            base, r"js/field-outbox\.js' %}\?v=\w+\"", "field-outbox.js needs a ?v="
        )
        # After csrf-sync.js, whose token handling it depends on at replay.
        self.assertLess(base.index("js/csrf-sync.js"), base.index("js/field-outbox.js"))

    def test_outbox_is_scoped_to_field_actions_and_replays_with_a_fresh_token(self):
        js = self._read("static/js/field-outbox.js")
        self.assertIn("indexedDB.open(DB_NAME", js)
        self.assertIn("var DB_NAME = 'edify-outbox';", js)
        self.assertIn("var SYNC_TAG = 'edify-outbox';", js)
        for route in (
            "start",
            "complete",
            "evidence",
            "attendance",
            "ssa-upload",
            "salesforce-id",
            "submit",
        ):
            self.assertIn(route, js)
        self.assertIn("/^\\/my-plan\\/[^/]+\\/(complete|accountability)$/", js)
        # Fresh token per replay, read the way csrf-sync.js reads it.
        self.assertIn("'csrftoken'", js)
        self.assertIn("'X-CSRFToken': token", js)
        # 4xx keeps the entry and flags it; only 2xx removes it.
        self.assertIn("entry.status = 'attention'", js)
        self.assertIn("if (res.ok)", js)
        self.assertIn("Saved offline", js)
        # No framework: the file must work on the offline page with nothing else loaded.
        self.assertNotIn("Alpine.", js)
        self.assertNotIn("htmx.ajax", js)

    def test_mobile_shell_carries_the_pending_uploads_badge(self):
        nav = self._read("templates/components/mobile_bottom_nav.html")
        self.assertIn("data-field-outbox-badge", nav)
        self.assertIn("data-field-outbox-count", nav)
        self.assertIn("pending uploads", nav)

    def test_camera_capture_only_where_a_photo_is_accepted(self):
        """Governed forms are PDF-only by rule (apps/evidence/services.py), so
        their inputs must not open a camera; every other evidence input may."""
        expected_capture = {
            "templates/partials/my_plan/complete_drawer.html": 1,
            "templates/partials/my_plan/attendance_drawer.html": 1,
            "templates/partials/my_plan/ssa_upload_drawer.html": 1,
            "templates/partials/my_plan/accountability_drawer.html": 1,
            "templates/partials/my_plan/evidence_drawer.html": 0,
        }
        for rel, count in expected_capture.items():
            with self.subTest(template=rel):
                self.assertEqual(self._read(rel).count('capture="environment"'), count)
        complete = self._read("templates/partials/my_plan/complete_drawer.html")
        for governed in ("training_evidence_file", "visit_evidence_file"):
            tag = complete.split(f'name="{governed}"', 1)[1].split(">", 1)[0]
            self.assertNotIn("capture", tag)
            self.assertNotIn("image/", tag)
