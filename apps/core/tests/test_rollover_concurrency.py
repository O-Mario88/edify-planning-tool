import threading
from types import SimpleNamespace
from unittest.mock import patch

from django.http import HttpResponse
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from apps.core.middleware import FiscalYearRolloverMiddleware


@override_settings(FISCAL_YEAR_ROLLOVER_ENABLED=True)
class RolloverConcurrencyTest(SimpleTestCase):
    def setUp(self):
        self.guard = FiscalYearRolloverMiddleware(lambda request: HttpResponse("ok"))
        self.request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True))

    def _finish(self):
        if self.guard.worker is not None:
            self.guard.worker.join(3)
            self.assertFalse(self.guard.worker.is_alive())

    def test_no_request_waits_for_the_rollover_and_it_runs_once(self):
        """The rollover runs off the request: the sign-in that notices it is
        missing returns at once, like every other one, and a second sign-in
        while it runs does not start another (2026-09-24 A+ audit: it was a
        9-12 s transaction inside the first request of each process)."""
        entered, release = threading.Event(), threading.Event()
        calls = []

        def rollover(**kwargs):
            calls.append(kwargs)
            entered.set()
            release.wait(3)

        with patch(
            "apps.hr.fiscal_year_rollover.ensure_current_fiscal_year",
            side_effect=rollover,
        ):
            try:
                self.assertEqual(self.guard(self.request).status_code, 200)
                self.assertTrue(entered.wait(2), "the rollover never started")
                # Both answered while the rollover is still running.
                self.assertEqual(self.guard(self.request).status_code, 200)
                self.assertTrue(self.guard.worker.is_alive())
                self.assertEqual(len(calls), 1)
            finally:
                release.set()
                self._finish()
        self.assertEqual(calls, [{"initiated_by": "web-self-heal"}])

    def test_a_completed_rollover_is_not_repeated(self):
        with patch("apps.hr.fiscal_year_rollover.ensure_current_fiscal_year") as run:
            self.guard(self.request)
            self._finish()
            self.guard(self.request)
            self._finish()
            run.assert_called_once()

    def test_failure_releases_guard_and_obeys_retry_backoff(self):
        with patch(
            "apps.hr.fiscal_year_rollover.ensure_current_fiscal_year",
            side_effect=RuntimeError("unavailable"),
        ) as run:
            self.assertEqual(self.guard(self.request).status_code, 200)
            self._finish()
            self.assertEqual(self.guard(self.request).status_code, 200)
            self._finish()
            self.assertEqual(run.call_count, 1)
        self.guard.retry_after = 0
        with patch("apps.hr.fiscal_year_rollover.ensure_current_fiscal_year") as run:
            self.assertEqual(self.guard(self.request).status_code, 200)
            self._finish()
            run.assert_called_once()

    def test_anonymous_requests_never_start_it(self):
        anonymous = SimpleNamespace(user=SimpleNamespace(is_authenticated=False))
        with patch("apps.hr.fiscal_year_rollover.ensure_current_fiscal_year") as run:
            self.guard(anonymous)
            self.assertIsNone(self.guard.worker)
            run.assert_not_called()


@override_settings(FISCAL_YEAR_ROLLOVER_ENABLED=True)
class RolloverThreadCommitsTest(TransactionTestCase):
    """The real rollover, run by the middleware's thread on its own database
    connection, commits and is visible to the request side afterwards."""

    def test_the_background_rollover_completes_the_year(self):
        from apps.core.fy import get_operational_fy
        from apps.hr.models import FiscalYearRollover

        fy = get_operational_fy()
        self.assertFalse(
            FiscalYearRollover.objects.filter(
                fy=fy, completed_at__isnull=False
            ).exists()
        )
        guard = FiscalYearRolloverMiddleware(lambda request: HttpResponse("ok"))
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True))
        self.assertEqual(guard(request).status_code, 200)
        guard.worker.join(60)
        self.assertFalse(guard.worker.is_alive())
        self.assertEqual(guard.checked_fy, fy)
        self.assertTrue(
            FiscalYearRollover.objects.filter(
                fy=fy, completed_at__isnull=False
            ).exists()
        )
        # Done for this process: later sign-ins start nothing.
        guard(request)
        self.assertFalse(guard.worker.is_alive())
