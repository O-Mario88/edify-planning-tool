"""A test run never uses the application's cache (controls audit G-02,
2026-09-14): parallel workers shared one Redis and a suite's cache.clear()
flushed the development server's sessions."""

from __future__ import annotations

import os
import subprocess
import sys

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase

_PROBE = (
    "import sys; sys.argv=['manage.py','test']; sys.path.insert(0,'.');"
    "import django; django.setup();"
    "from django.conf import settings;"
    "print(settings.CACHES['default']['BACKEND'])"
)


class TestCacheIsolationTest(SimpleTestCase):
    def test_this_run_has_a_private_per_process_cache(self):
        backend = settings.CACHES["default"]
        if os.environ.get("EDIFY_TEST_REDIS_URL"):
            self.skipTest("this run was given a dedicated test Redis")
        self.assertEqual(
            backend["BACKEND"], "django.core.cache.backends.locmem.LocMemCache"
        )
        cache.set("g02-sentinel", "worker")
        self.assertEqual(cache.get("g02-sentinel"), "worker")

    def _settings_in_a_test_process(self, **env):
        return subprocess.run(
            [sys.executable, "-c", _PROBE],
            cwd=settings.BASE_DIR,
            env={
                **os.environ,
                "DJANGO_SETTINGS_MODULE": "config.settings.dev",
                **env,
            },
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_the_application_redis_is_refused_as_the_test_redis(self):
        url = "redis://127.0.0.1:6379/0"
        run = self._settings_in_a_test_process(REDIS_URL=url, EDIFY_TEST_REDIS_URL=url)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("must not be the application's REDIS_URL", run.stderr)

    def test_a_test_process_ignores_the_application_redis(self):
        run = self._settings_in_a_test_process(
            REDIS_URL="redis://127.0.0.1:6379/0", EDIFY_TEST_REDIS_URL=""
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("LocMemCache", run.stdout)
