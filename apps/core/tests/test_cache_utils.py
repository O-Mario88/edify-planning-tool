from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from apps.core.cache_utils import (
    _MISSING,
    build_namespace,
    forget_snapshot,
    snapshot_key,
    stampede_safe_get_or_compute,
)


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
        # The lock lives beside the snapshot it guards, so it carries the same
        # build namespace (see cache_utils.build_namespace) — asserted by shape
        # rather than by literal, because the prefix is the running build's.
        delete.assert_called_once()
        (lock_key,), _ = delete.call_args
        self.assertTrue(
            lock_key.endswith(":write-failure:rebuild"),
            f"lock key was {lock_key!r}",
        )
        self.assertEqual(lock_key.split(":")[0], build_namespace())


class BuildNamespacedCacheTest(SimpleTestCase):
    """A deploy must not serve the previous build's snapshot.

    Owner, 2026-09-18, asking whether a merged change had taken effect on the
    live server: a deploy replaces the code that computes these snapshots and
    leaves the cache holding the old build's answers, so for a whole TTL "the
    change did not take effect" looks exactly like "the deploy did not happen".
    """

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        import apps.core.cache_utils as cache_utils

        self._saved = cache_utils._BUILD_NAMESPACE
        self.addCleanup(setattr, cache_utils, "_BUILD_NAMESPACE", self._saved)

    def _as_build(self, release):
        """Run as a process whose image reports `release`.

        Releases are written as hex, the way real ones are, and deliberately
        without hyphens: `build_indexed_css.cjs` scans apps/ for class-name
        candidates, so a hyphenated fixture lands in the generated
        stylesheet's substring lists. A test string has no business in
        production CSS — including one written inside this explanation, which
        is why the example is described rather than quoted.
        """
        import apps.core.cache_utils as cache_utils

        cache_utils._BUILD_NAMESPACE = None
        return patch(
            "apps.core.build_info.build_info", return_value={"release": release}
        )

    def test_a_new_build_does_not_serve_the_old_builds_snapshot(self):
        compute = MagicMock(
            side_effect=[{"support_ends_at": 7.0}, {"support_ends_at": 8.0}]
        )

        with self._as_build("a1b2c3d4"):
            before = stampede_safe_get_or_compute("dash", compute, timeout=300)
        with self._as_build("e5f6a7b8"):
            after = stampede_safe_get_or_compute("dash", compute, timeout=300)

        self.assertEqual(before, {"support_ends_at": 7.0})
        self.assertEqual(
            after,
            {"support_ends_at": 8.0},
            "the new build served the previous build's cached figures",
        )
        self.assertEqual(compute.call_count, 2)

    def test_the_same_build_still_reuses_its_own_snapshot(self):
        """The control: namespacing must not defeat caching altogether."""
        compute = MagicMock(return_value={"value": 1})

        with self._as_build("c9d0e1f2"):
            stampede_safe_get_or_compute("dash", compute, timeout=300)
            stampede_safe_get_or_compute("dash", compute, timeout=300)

        compute.assert_called_once_with()

    def test_unreadable_build_info_never_breaks_the_page(self):
        """A cache namespace that could break a page would be worse than the
        staleness it prevents."""
        import apps.core.cache_utils as cache_utils

        cache_utils._BUILD_NAMESPACE = None
        with patch(
            "apps.core.build_info.build_info", side_effect=OSError("no image file")
        ):
            value = stampede_safe_get_or_compute(
                "dash", MagicMock(return_value=7), timeout=300
            )

        self.assertEqual(value, 7)


class StampedeWaitTest(SimpleTestCase):
    """Performance rescue, 2026-09-23: a waiter used to give up after three
    seconds and rebuild the snapshot itself, so every snapshot slower than
    that was built once per waiter at the same time."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.clock = 0.0

    def _tick(self):
        self.clock += 1.0
        return self.clock

    def _owner_is_rebuilding(self, key):
        cache.add(f"{snapshot_key(key)}:rebuild", 1, timeout=30)

    def test_a_waiter_outlasts_a_slow_rebuild_instead_of_duplicating_it(self):
        self._owner_is_rebuilding("slow")
        polls = []

        def sleep(_seconds):
            polls.append(1)
            if len(polls) == 6:  # six seconds in, the owner publishes
                cache.set(snapshot_key("slow"), "owner's answer", timeout=30)

        compute = MagicMock(return_value="duplicate")
        with (
            patch("apps.core.cache_utils.time.sleep", side_effect=sleep),
            patch("apps.core.cache_utils.time.monotonic", side_effect=self._tick),
        ):
            result = stampede_safe_get_or_compute("slow", compute, timeout=30)
        self.assertEqual(result, "owner's answer")
        compute.assert_not_called()

    def test_a_waiter_builds_it_when_the_owner_finishes_without_publishing(self):
        self._owner_is_rebuilding("lost")

        def sleep(_seconds):
            cache.delete(f"{snapshot_key('lost')}:rebuild")

        with patch("apps.core.cache_utils.time.sleep", side_effect=sleep):
            result = stampede_safe_get_or_compute("lost", lambda: "mine", timeout=30)
        self.assertEqual(result, "mine")

    def test_the_wait_is_still_bounded(self):
        self._owner_is_rebuilding("stuck")
        with (
            patch("apps.core.cache_utils.time.sleep"),
            patch("apps.core.cache_utils.time.monotonic", side_effect=self._tick),
        ):
            result = stampede_safe_get_or_compute(
                "stuck", lambda: "fallback", timeout=30
            )
        self.assertEqual(result, "fallback")
        self.assertLessEqual(self.clock, 32)


class ForgetSnapshotTest(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_forget_drops_the_namespaced_snapshot(self):
        compute = MagicMock(side_effect=["before", "after"])
        stampede_safe_get_or_compute("queue", compute, timeout=30)
        forget_snapshot("queue")
        self.assertEqual(
            stampede_safe_get_or_compute("queue", compute, timeout=30), "after"
        )

    def test_the_todo_queue_forget_reaches_its_snapshot(self):
        from types import SimpleNamespace

        from apps.command_center.today_actions import forget_queue
        from apps.command_center.todo_service import todo_snapshot_key

        principal = SimpleNamespace(id="u-1", active_role="CCEO")
        compute = MagicMock(side_effect=[["old item"], []])
        key = todo_snapshot_key(principal)
        stampede_safe_get_or_compute(key, compute, timeout=30)
        forget_queue(principal)
        self.assertEqual(stampede_safe_get_or_compute(key, compute, timeout=30), [])
