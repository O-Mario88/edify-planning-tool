"""`request_cache.scoped()` memoises one direct service call, and no longer.

Inside a request the store already exists and the scope must not touch it;
outside one it opens a store for the call and clears it on the way out, even
when the call raises, so a management command or test never sees a value
computed for an earlier call.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.core import request_cache


class ScopedMemoTest(SimpleTestCase):
    def setUp(self):
        request_cache.end()

    def tearDown(self):
        request_cache.end()

    def test_outside_a_request_the_scope_memoises_and_then_clears(self):
        calls = []

        def compute():
            calls.append(1)
            return "value"

        self.assertIsNone(request_cache.store())
        with request_cache.scoped():
            self.assertEqual(request_cache.memoize("k", compute), "value")
            self.assertEqual(request_cache.memoize("k", compute), "value")
        self.assertEqual(len(calls), 1)
        self.assertIsNone(request_cache.store())
        request_cache.memoize("k", compute)
        self.assertEqual(len(calls), 2, "nothing outlives the scope")

    def test_inside_a_request_the_scope_leaves_the_store_alone(self):
        request_cache.begin()
        request_cache.memoize("held", lambda: "before")
        with request_cache.scoped():
            self.assertEqual(request_cache.memoize("held", lambda: "recomputed"), "before")
        self.assertIsNotNone(request_cache.store())
        self.assertEqual(request_cache.memoize("held", lambda: "recomputed"), "before")

    def test_the_scope_clears_when_the_call_raises(self):
        with self.assertRaises(RuntimeError):
            with request_cache.scoped():
                request_cache.memoize("k", lambda: 1)
                raise RuntimeError("boom")
        self.assertIsNone(request_cache.store())
