"""The process is warm before it serves, and the heavy statistics library is
loaded only when a statistic is computed (2026-09-12 performance pass)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase, TestCase, override_settings

ROOT = Path(__file__).resolve().parents[3]


class WarmupTest(SimpleTestCase):
    def test_both_server_entry_points_warm_the_process(self):
        for entry in ("config/asgi.py", "config/wsgi.py"):
            with self.subTest(entry=entry):
                self.assertIn(
                    "from config.warmup import warm", (ROOT / entry).read_text()
                )
                self.assertIn("warm()", (ROOT / entry).read_text())

    def test_warm_imports_the_urlconf_and_the_engines(self):
        from config.warmup import WARM_MODULES, warm

        timings = warm()
        self.assertEqual(set(timings), set(WARM_MODULES))
        self.assertIn("config.urls", sys.modules)
        self.assertIn("apps.analytics.platform_engine", sys.modules)

    def test_importing_the_urlconf_does_not_load_scipy(self):
        code = (
            "import django, os, sys; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev'); "
            "django.setup(); import config.urls; import apps.analytics.platform_engine; "
            "print('scipy' in sys.modules)"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertEqual(
            out.stdout.strip().splitlines()[-1], "False", out.stderr[-600:]
        )

    def test_a_statistic_still_computes(self):
        from apps.analytics.platform_engine import _scipy_stats

        self.assertAlmostEqual(_scipy_stats().pearsonr([1, 2, 3], [2, 4, 6])[0], 1.0)


class DashboardCacheTest(TestCase):
    def test_tests_run_with_the_dashboard_cache_off(self):
        from django.conf import settings

        self.assertEqual(settings.DASHBOARD_CACHE_SECONDS, 0)

    @override_settings(DASHBOARD_CACHE_SECONDS=60)
    def test_a_second_load_within_the_window_is_served_from_cache(self):
        from unittest import mock

        from django.core.cache import cache

        from apps.accounts.models import User
        from apps.analytics.cd_dashboard_service import CDDashboardService

        cache.clear()
        user = User.objects.create(
            id="warm-cd",
            email="warm-cd@edify.test",
            name="Warm CD",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )
        with mock.patch.object(
            CDDashboardService, "_get_dashboard", return_value={"kpis": [], "built": 1}
        ) as build:
            first = CDDashboardService.get_dashboard(user, fy="2026")
            second = CDDashboardService.get_dashboard(user, fy="2026")
        self.assertEqual(first, second)
        self.assertEqual(
            build.call_count, 1, "the second load must not rebuild the dashboard"
        )
        cache.clear()
