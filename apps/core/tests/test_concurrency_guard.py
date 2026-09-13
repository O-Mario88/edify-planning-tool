"""The web process bounds how many requests use the database at once.

Every ASGI request runs on its own thread with its own connection, so a peak in
simultaneous requests used to become a peak in simultaneous database
connections, and past the cluster's limit every page failed together
(2026-09-13, after the 2026-09-12 connection outage).
"""

from __future__ import annotations

import threading
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.core.concurrency import DatabaseConcurrencyGuardMiddleware


class ConcurrencyGuardTest(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _holding_view(self):
        entered = threading.Event()
        release = threading.Event()

        def view(request):
            entered.set()
            release.wait(5)
            return HttpResponse("done")

        return view, entered, release

    def _hold_one_slot(self, guard, entered):
        result = {}
        thread = threading.Thread(
            target=lambda: result.setdefault(
                "response", guard(self.factory.get("/dashboard"))
            )
        )
        thread.start()
        self.assertTrue(entered.wait(2), "the first request never reached the view")
        return thread, result

    def test_the_guard_is_off_unless_configured(self):
        guard = DatabaseConcurrencyGuardMiddleware(lambda request: HttpResponse("ok"))
        self.assertIsNone(guard.semaphore)
        self.assertEqual(guard(self.factory.get("/dashboard")).status_code, 200)

    @override_settings(WEB_MAX_CONCURRENT_REQUESTS=1, WEB_QUEUE_TIMEOUT_SECONDS=0.2)
    def test_a_request_past_the_limit_is_told_to_retry_not_given_a_database_error(self):
        view, entered, release = self._holding_view()
        guard = DatabaseConcurrencyGuardMiddleware(view)
        thread, first = self._hold_one_slot(guard, entered)
        try:
            refused = guard(self.factory.get("/dashboard"))
            self.assertEqual(refused.status_code, 503)
            self.assertEqual(refused["Retry-After"], "5")
            self.assertIn(b"busy", refused.content)
        finally:
            release.set()
            thread.join(5)
        self.assertEqual(first["response"].status_code, 200)
        # The slot is back: the next request goes straight through.
        self.assertEqual(guard(self.factory.get("/dashboard")).status_code, 200)

    @override_settings(WEB_MAX_CONCURRENT_REQUESTS=1, WEB_QUEUE_TIMEOUT_SECONDS=5)
    def test_a_waiting_request_proceeds_when_a_slot_frees(self):
        view, entered, release = self._holding_view()
        guard = DatabaseConcurrencyGuardMiddleware(view)
        thread, _first = self._hold_one_slot(guard, entered)
        timer = threading.Timer(0.3, release.set)
        timer.start()
        try:
            waited = guard(self.factory.get("/my-plan"))
        finally:
            release.set()
            thread.join(5)
            timer.cancel()
        self.assertEqual(waited.status_code, 200)

    @override_settings(WEB_MAX_CONCURRENT_REQUESTS=1, WEB_QUEUE_TIMEOUT_SECONDS=0.2)
    def test_health_probes_and_the_realtime_stream_never_wait(self):
        view, entered, release = self._holding_view()
        guard = DatabaseConcurrencyGuardMiddleware(view)
        thread, _first = self._hold_one_slot(guard, entered)
        release.set()  # the exempt requests below must not block on the view
        try:
            # The platform health check asks /api/health/ready with a 10s
            # timeout: queued behind a busy process it would fail, and five
            # failures restart a process that was only busy.
            for path in (
                "/api/health/live",
                "/api/health/ready",
                "/api/health",
                "/api/realtime/stream",
            ):
                with self.subTest(path=path):
                    self.assertEqual(guard(self.factory.get(path)).status_code, 200)
        finally:
            thread.join(5)

    @override_settings(WEB_MAX_CONCURRENT_REQUESTS=1, WEB_QUEUE_TIMEOUT_SECONDS=0.2)
    def test_api_and_htmx_clients_get_a_shape_they_can_act_on(self):
        view, entered, release = self._holding_view()
        guard = DatabaseConcurrencyGuardMiddleware(view)
        thread, _first = self._hold_one_slot(guard, entered)
        try:
            api = guard(self.factory.get("/api/activities"))
            self.assertEqual(api.status_code, 503)
            self.assertEqual(api["Content-Type"], "application/json")
            htmx = guard(self.factory.get("/planning", HTTP_HX_REQUEST="true"))
            self.assertEqual(htmx.status_code, 503)
            self.assertIn(b"edify-note", htmx.content)
        finally:
            release.set()
            thread.join(5)

    def test_production_bounds_it_by_default_and_it_sits_before_the_session(self):
        middleware = settings.MIDDLEWARE
        self.assertIn(
            "apps.core.concurrency.DatabaseConcurrencyGuardMiddleware", middleware
        )
        self.assertLess(
            middleware.index(
                "apps.core.concurrency.DatabaseConcurrencyGuardMiddleware"
            ),
            middleware.index("django.contrib.sessions.middleware.SessionMiddleware"),
        )
        prod = (Path(settings.BASE_DIR) / "config/settings/prod.py").read_text()
        self.assertIn('"WEB_MAX_CONCURRENT_REQUESTS"', prod)
