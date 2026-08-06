"""The login limit must mean what settings says, at any instance count.

The throttle counted in a module-level Python dict. At one process that is
exactly right, and production runs one Daphne instance today — so this was not
a live defect. It was a latent one: raising `instance_count` in .do/app.yaml is
a single line, and it would have turned "10 login attempts per minute" into 10
per minute *per instance* with nothing logged and nothing failing.

These tests pin the two halves of the fix:

  * with no shared cache, the in-process window still enforces the limit
    (the behaviour that was already correct must not regress);
  * with a shared cache, counting moves there and is atomic under real
    concurrent threads — the case a read-modify-write counter gets wrong.

LocMemCache is per-process, which is precisely why the production code refuses
to count in it. Within one test process, though, it is shared across threads,
so it is a faithful stand-in for proving the counting logic itself.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from apps.core import throttling
from apps.core.throttling import _hit, _window, reset_throttle_state


class InProcessWindowTest(SimpleTestCase):
    """The fallback path — no shared cache available."""

    def setUp(self):
        reset_throttle_state()
        self.patcher = mock.patch.object(
            throttling, "_cache_is_shared", return_value=False
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_the_limit_is_enforced(self):
        allowed = [_hit("route:1.2.3.4", window_ms=60_000, limit=5) for _ in range(8)]
        self.assertEqual(
            allowed.count(True), 5, "exactly the configured number get through"
        )
        self.assertEqual(allowed.count(False), 3)

    def test_distinct_clients_do_not_share_a_budget(self):
        for _ in range(5):
            _hit("route:10.0.0.1", window_ms=60_000, limit=5)
        self.assertTrue(
            _hit("route:10.0.0.2", window_ms=60_000, limit=5),
            "one address exhausting its limit must not block another",
        )


class SharedCacheWindowTest(SimpleTestCase):
    """The path taken once Redis is provisioned."""

    def setUp(self):
        reset_throttle_state()
        cache.clear()
        self.patcher = mock.patch.object(
            throttling, "_cache_is_shared", return_value=True
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(cache.clear)

    def test_the_limit_is_enforced_in_the_cache(self):
        allowed = [_hit("route:5.6.7.8", window_ms=60_000, limit=5) for _ in range(8)]
        self.assertEqual(allowed.count(True), 5)
        self.assertEqual(allowed.count(False), 3)

    def test_the_in_process_dict_is_not_used_when_a_shared_cache_exists(self):
        """Otherwise the count would be split across two places and neither
        would be the truth."""
        _window._hits.clear()  # noqa: SLF001
        for _ in range(3):
            _hit("route:9.9.9.9", window_ms=60_000, limit=5)
        self.assertEqual(
            len(_window._hits),  # noqa: SLF001
            0,
            "hits must be counted in one place, not two",
        )

    def test_concurrent_requests_cannot_both_pass_the_last_slot(self):
        """The race a read-modify-write counter loses.

        Twenty threads released together against a limit of five: an atomic
        counter admits exactly five, a read-then-write counter admits more.
        """
        threads = 20
        limit = 5
        barrier = threading.Barrier(threads)
        results: list[bool] = []
        lock = threading.Lock()

        def worker(_i):
            barrier.wait(timeout=30)
            ok = _hit("route:burst", window_ms=60_000, limit=limit)
            with lock:
                results.append(ok)

        with ThreadPoolExecutor(max_workers=threads) as pool:
            list(pool.map(worker, range(threads)))

        self.assertEqual(
            results.count(True),
            limit,
            f"exactly {limit} may pass under concurrency, got {results.count(True)}",
        )

    def test_a_broken_cache_falls_back_instead_of_locking_everyone_out(self):
        """A degraded cache must not become an outage on the login route."""
        with mock.patch.object(
            throttling, "_shared_hit", side_effect=lambda k, **kw: _window.hit(k, **kw)
        ):
            self.assertTrue(_hit("route:degraded", window_ms=60_000, limit=2))

        with mock.patch(
            "django.core.cache.cache.add", side_effect=RuntimeError("down")
        ):
            self.assertTrue(
                _hit("route:degraded-2", window_ms=60_000, limit=2),
                "a cache failure must fall back to the in-process window",
            )


class ResetHelperTest(SimpleTestCase):
    """The test helper has to clear whichever backing is live, or suites leak
    throttle state into each other depending on whether Redis is running."""

    def test_reset_clears_the_shared_cache_too(self):
        with mock.patch.object(throttling, "_cache_is_shared", return_value=True):
            cache.clear()
            for _ in range(5):
                _hit("route:reset-me", window_ms=60_000, limit=5)
            self.assertFalse(_hit("route:reset-me", window_ms=60_000, limit=5))

            reset_throttle_state(["route:reset-me"])
            self.assertTrue(
                _hit("route:reset-me", window_ms=60_000, limit=5),
                "after a reset the key must start from zero again",
            )
        cache.clear()
