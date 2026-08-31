"""Redis-backed SSE must not perform socket work on the ASGI event loop."""

import asyncio
import queue
import threading
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from apps.realtime.views import stream


class StreamTransportTests(SimpleTestCase):
    def request(self):
        request = RequestFactory().get("/api/realtime/stream")
        request.user = SimpleNamespace(id="stream-owner", is_authenticated=True)
        return request

    async def test_transport_and_disconnect_cleanup_run_off_the_event_loop(self):
        loop_thread = threading.get_ident()

        class Subscription:
            def get_nowait(inner_self):
                self.assertNotEqual(threading.get_ident(), loop_thread)
                return {"type": "activity.updated"}

        subscription = Subscription()

        def subscribe(user_id):
            self.assertNotEqual(threading.get_ident(), loop_thread)
            self.assertEqual(user_id, "stream-owner")
            return subscription

        def unsubscribe(user_id, received):
            self.assertNotEqual(threading.get_ident(), loop_thread)
            self.assertIs(received, subscription)

        with patch("apps.realtime.views.bus") as bus:
            bus.subscribe.side_effect = subscribe
            bus.unsubscribe.side_effect = unsubscribe
            response = stream(self.request())
            iterator = response._iterator
            try:
                self.assertIn(b'"connected"', await iterator.__anext__())
                self.assertIn(b'"activity.updated"', await iterator.__anext__())
            finally:
                await iterator.aclose()
            bus.unsubscribe.assert_called_once_with("stream-owner", subscription)

    async def test_disconnect_during_subscription_does_not_leak_it(self):
        started = threading.Event()
        release = threading.Event()
        subscription = queue.Queue()

        def subscribe(_user_id):
            started.set()
            if not release.wait(timeout=5):
                raise AssertionError("Test did not release subscription setup")
            return subscription

        with patch("apps.realtime.views.bus") as bus:
            bus.subscribe.side_effect = subscribe
            response = stream(self.request())
            iterator = response._iterator
            pending = asyncio.create_task(iterator.__anext__())
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 5))
                pending.cancel()
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await pending
                bus.unsubscribe.assert_called_once_with("stream-owner", subscription)
            finally:
                release.set()
                await iterator.aclose()
