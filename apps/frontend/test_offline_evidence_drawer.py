"""The upload drawer opens without signal (owner, 2026-09-26).

"Make the upload drawer open offline too." The service worker keeps one
generic upload drawer, precached at install beside the offline page, and
serves it for /activities/<id>/evidence when the network fails, with the
tapped activity's id put in. Like the offline page it is made for nobody —
the worker still stores no page rendered for a user — and its Submit is
saved by the field outbox and checked by the server when it is sent.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase, TestCase, override_settings

from apps.frontend.templatetags.frontend_filters import field_role

ROOT = Path(settings.BASE_DIR)
PLACEHOLDER = "__EDIFY_ACTIVITY_ID__"


class OfflineEvidenceDrawerTest(TestCase):
    def test_renders_anonymously_for_any_activity(self):
        res = self.client.get("/offline/evidence-drawer")
        self.assertEqual(res.status_code, 200)
        body = res.content.decode()
        self.assertIn(f'hx-post="/activities/{PLACEHOLDER}/evidence/action"', body)
        # Several pages, from the camera or the phone, posted as one form.
        self.assertIn('capture="environment"', body)
        main = body.split('name="evidence_file"', 1)[1].split(">", 1)[0]
        self.assertIn("multiple", main)
        self.assertIn(">Submit</button>", body)
        self.assertIn("no-cache", res["Cache-Control"])

    def test_carries_nothing_from_the_signed_in_session(self):
        user = get_user_model().objects.create_user(
            email="offline-drawer-probe@edify.test",
            password="password123",
            name="Offline Drawer Probe",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.client.force_login(user)
        res = self.client.get("/offline/evidence-drawer")
        body = res.content.decode()
        self.assertNotIn("Offline Drawer Probe", body)
        self.assertNotIn("offline-drawer-probe@edify.test", body)
        self.assertNotIn("csrfmiddlewaretoken", body)
        cookie_token = self.client.cookies.get("csrftoken")
        if cookie_token and cookie_token.value:
            self.assertNotIn(cookie_token.value, body)

    def test_the_salesforce_id_is_for_staff_only(self):
        body = self.client.get("/offline/evidence-drawer").content.decode()
        self.assertIn("staff: document.body.dataset.edifyFieldRole === 'staff'", body)
        field = body.split('name="salesforce_id"', 1)[1].split(">", 1)[0]
        self.assertIn(':disabled="!staff"', field)
        self.assertNotIn("required", field)


class ServiceWorkerServesTheDrawerOfflineTest(TestCase):
    def _worker(self, backend):
        with override_settings(
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {"BACKEND": backend},
            }
        ):
            return self.client.get("/sw.js").content.decode()

    def test_precached_and_served_only_when_the_network_fails(self):
        for backend in (
            "whitenoise.storage.CompressedManifestStaticFilesStorage",
            "django.contrib.staticfiles.storage.StaticFilesStorage",
        ):
            with self.subTest(backend=backend):
                body = self._worker(backend)
                self.assertIn(
                    "const OFFLINE_DRAWER_URL = '/offline/evidence-drawer';", body
                )
                self.assertIn(
                    "c.add(new Request(OFFLINE_DRAWER_URL, { cache: 'reload' }))"
                    ".catch(() => null)",
                    body,
                )
                self.assertIn(
                    "fetch(req).catch(() => caches.match(OFFLINE_DRAWER_URL, "
                    "{ cacheName: OFFLINE_CACHE })",
                    body,
                )
                self.assertIn(f"html.split('{PLACEHOLDER}').join(drawer[1])", body)
                # The saved copy's own headers, as the offline page does.
                self.assertNotIn("text/html", body)

    def test_only_an_id_of_the_expected_shape_is_written_into_the_page(self):
        body = self._worker("django.contrib.staticfiles.storage.StaticFilesStorage")
        self.assertIn(
            r"const DRAWER_PATH = /^\/activities\/([A-Za-z0-9_-]{1,64})\/evidence$/;",
            body,
        )

    def test_the_worker_still_stores_no_page_rendered_for_a_user(self):
        body = self._worker("django.contrib.staticfiles.storage.StaticFilesStorage")
        self.assertNotIn("c.put(req", body)
        self.assertNotIn("cache.put", body)


class OfflineDrawerWiringTest(SimpleTestCase):
    def test_the_page_lets_the_drawer_request_through_offline(self):
        js = (ROOT / "static/js/platform-status.js").read_text()
        self.assertIn(
            r"/^\/activities\/[^/]+\/evidence$/.test(event.detail.pathInfo.requestPath)",
            js,
        )

    def test_the_body_says_whether_the_viewer_is_staff_or_a_partner(self):
        base = (ROOT / "templates/base.html").read_text()
        self.assertIn('data-edify-field-role="{{ request.user|field_role }}"', base)

    def test_field_role(self):
        class _User:
            is_authenticated = True

            def __init__(self, role):
                self.active_role = role

        self.assertEqual(field_role(_User("PartnerFieldOfficer")), "partner")
        self.assertEqual(field_role(_User("PartnerAdmin")), "partner")
        self.assertEqual(field_role(_User("CCEO")), "staff")
        self.assertEqual(field_role(_User("Program Lead")), "staff")
        self.assertEqual(field_role(AnonymousUser()), "")
