from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from apps.core.cache_utils import _MISSING, stampede_safe_get_or_compute


class StampedeSafeCacheTest(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_reuses_the_snapshot_within_its_ttl(self):
        compute = MagicMock(return_value={"value": 1})
        first = stampede_safe_get_or_compute("snapshot", compute, timeout=30)
        second = stampede_safe_get_or_compute("snapshot", compute, timeout=30)
        self.assertEqual(first, second)
        compute.assert_called_once_with()

    def test_zero_timeout_bypasses_cache_for_deterministic_tests(self):
        compute = MagicMock(side_effect=[1, 2])
        self.assertEqual(
            stampede_safe_get_or_compute("uncached", compute, timeout=0), 1
        )
        self.assertEqual(
            stampede_safe_get_or_compute("uncached", compute, timeout=0), 2
        )

    def test_rebuild_lock_is_removed_when_computation_fails(self):
        with self.assertRaises(RuntimeError):
            stampede_safe_get_or_compute(
                "failing",
                lambda: (_ for _ in ()).throw(RuntimeError("boom")),
                timeout=30,
            )
        self.assertTrue(
            stampede_safe_get_or_compute("failing", lambda: True, timeout=30)
        )

    def test_waiter_reuses_the_value_published_by_the_lock_owner(self):
        compute = MagicMock(return_value="duplicate")
        with (
            patch("apps.core.cache_utils.cache.get", side_effect=[_MISSING, "shared"]),
            patch("apps.core.cache_utils.cache.add", return_value=False),
            patch("apps.core.cache_utils.time.sleep"),
            patch(
                "apps.core.cache_utils.time.monotonic",
                side_effect=[0.0, 0.01],
            ),
        ):
            result = stampede_safe_get_or_compute(
                "contended", compute, timeout=30, wait_seconds=1
            )
        self.assertEqual(result, "shared")
        compute.assert_not_called()

    def test_cache_read_failure_degrades_to_authoritative_computation(self):
        with (
            patch("apps.core.cache_utils.cache.get", side_effect=OSError("down")),
            self.assertLogs("apps.core.cache_utils", level="WARNING"),
        ):
            result = stampede_safe_get_or_compute(
                "unavailable", lambda: {"fresh": True}, timeout=30
            )
        self.assertEqual(result, {"fresh": True})

    def test_cache_write_failure_still_returns_the_computed_response(self):
        with (
            patch("apps.core.cache_utils.cache.get", return_value=_MISSING),
            patch("apps.core.cache_utils.cache.add", return_value=True),
            patch("apps.core.cache_utils.cache.set", side_effect=OSError("down")),
            patch("apps.core.cache_utils.cache.delete") as delete,
            self.assertLogs("apps.core.cache_utils", level="WARNING"),
        ):
            result = stampede_safe_get_or_compute(
                "write-failure", lambda: 42, timeout=30
            )
        self.assertEqual(result, 42)
        delete.assert_called_once_with("write-failure:rebuild")
