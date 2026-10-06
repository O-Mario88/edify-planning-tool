"""The stream endpoint is bounded (AEGIS review, 2026-09-12): a cap of open
streams per account and a rate of stream opens per address."""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.realtime.views import stream


def _request(user_id="cap-owner", addr="10.0.0.9"):
    request = RequestFactory().get("/api/realtime/stream", REMOTE_ADDR=addr)
    request.user = SimpleNamespace(id=user_id, is_authenticated=True)
    return request


class StreamCapTests(SimpleTestCase):
    def setUp(self):
        from apps.core.throttling import reset_throttle_state

        reset_throttle_state()

    @override_settings(REALTIME_STREAMS_PER_USER=2)
    def test_an_account_at_its_cap_is_refused_with_429(self):
        with patch("apps.realtime.views.bus.subscription_count", return_value=2):
            response = stream(_request())
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "30")
        self.assertIn(
            b"already holds 2 open streams", b"".join(response.streaming_content)
        )

    @override_settings(REALTIME_STREAMS_PER_USER=2)
    def test_below_the_cap_the_stream_opens(self):
        with patch("apps.realtime.views.bus.subscription_count", return_value=1):
            response = stream(_request())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/event-stream")

    @override_settings(REALTIME_STREAM_OPENS_PER_MINUTE=2)
    def test_an_account_opening_streams_in_a_loop_is_rate_limited(self):
        with patch("apps.realtime.views.bus.subscription_count", return_value=0):
            codes = [stream(_request(addr="10.0.0.7")).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    @override_settings(REALTIME_STREAM_OPENS_PER_MINUTE=2)
    def test_colleagues_behind_one_address_are_not_refused_for_each_other(self):
        """An office shares an address, and every page that shows a plan opens
        a stream (2026-10-05): each account has the rate to itself."""
        with patch("apps.realtime.views.bus.subscription_count", return_value=0):
            codes = [
                stream(_request(user_id=f"office-{n}", addr="10.0.0.8")).status_code
                for n in range(5)
            ]
        self.assertEqual(codes, [200] * 5)

    @override_settings(REALTIME_STREAM_OPENS_PER_MINUTE=2)
    def test_one_address_is_still_bounded_at_ten_times_the_account_rate(self):
        with patch("apps.realtime.views.bus.subscription_count", return_value=0):
            codes = [
                stream(_request(user_id=f"flood-{n}", addr="10.0.0.6")).status_code
                for n in range(21)
            ]
        self.assertEqual(codes, [200] * 20 + [429])
