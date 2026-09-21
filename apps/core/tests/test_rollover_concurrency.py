import threading
from types import SimpleNamespace
from unittest.mock import patch

from django.http import HttpResponse
from django.test import SimpleTestCase, override_settings

from apps.core.middleware import FiscalYearRolloverMiddleware


@override_settings(FISCAL_YEAR_ROLLOVER_ENABLED=True)
class RolloverConcurrencyTest(SimpleTestCase):
    def test_other_logins_do_not_repeat_or_wait_for_rollover(self):
        entered, release = threading.Event(), threading.Event()
        calls = []

        def rollover(**kwargs):
            calls.append(kwargs)
            entered.set()
            release.wait(3)

        guard = FiscalYearRolloverMiddleware(lambda request: HttpResponse("ok"))
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True))
        with patch(
            "apps.hr.fiscal_year_rollover.ensure_current_fiscal_year",
            side_effect=rollover,
        ):
            first = threading.Thread(target=guard, args=(request,))
            first.start()
            try:
                self.assertTrue(entered.wait(2))
                second = threading.Thread(target=guard, args=(request,))
                second.start()
                second.join(0.5)
                self.assertFalse(
                    second.is_alive(), "a second login waited for rollover"
                )
                self.assertEqual(len(calls), 1)
            finally:
                release.set()
                first.join(3)
                second.join(3)

    def test_failure_releases_guard_and_obeys_retry_backoff(self):
        guard = FiscalYearRolloverMiddleware(lambda request: HttpResponse("ok"))
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True))
        with patch(
            "apps.hr.fiscal_year_rollover.ensure_current_fiscal_year",
            side_effect=RuntimeError("unavailable"),
        ) as run:
            self.assertEqual(guard(request).status_code, 200)
            self.assertEqual(guard(request).status_code, 200)
            self.assertEqual(run.call_count, 1)
        guard.retry_after = 0
        with patch("apps.hr.fiscal_year_rollover.ensure_current_fiscal_year") as run:
            self.assertEqual(guard(request).status_code, 200)
            run.assert_called_once()
