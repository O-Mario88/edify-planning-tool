"""Pages must not cross the network uncompressed.

The reported symptom was "the live website is so slow to respond to clicks and
taps, it loads very slowly". Part of that was measurable and had nothing to do
with the database: nothing compressed HTML at all. WhiteNoise compressed the
static files, so the CSS and JS were fine — but the pages themselves, and every
HTMX fragment that replaces part of one, went out at full size. Analytics was
511 KB, Schools 330 KB, the dashboard 212 KB. Over these ten pages the platform
shipped 2.5 MB where 340 KB would do.

That is why it showed up as "slow to respond to clicks": in an HTMX app a click
IS a page fetch, so an uncompressed response is felt on every interaction
rather than only at first load.

The reason it cannot simply be Django's GZipMiddleware is streaming. That
middleware compresses StreamingHttpResponse too, which would buffer the
server-sent event stream (apps.realtime) until the compressor flushed — live
updates would stop arriving — and would re-buffer the streamed CSV exports in
memory, which is the one thing streaming them exists to avoid.
"""

from __future__ import annotations

from django.test import Client, TestCase

from apps.accounts.models import User
from apps.core.rbac import EdifyRole


class ResponsesAreCompressedTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="gzip@edify.test",
            password="password123",
            name="Gzip Tester",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            is_active=True,
        )

    def _client(self, *, accepts_gzip: bool) -> Client:
        client = (
            Client(HTTP_ACCEPT_ENCODING="gzip, deflate")
            if accepts_gzip
            else Client(HTTP_ACCEPT_ENCODING="identity")
        )
        client.force_login(self.user)
        return client

    def test_the_middleware_is_installed_ahead_of_body_writers(self):
        from django.conf import settings

        middleware = list(settings.MIDDLEWARE)
        self.assertIn("apps.core.middleware.StreamSafeGZipMiddleware", middleware)
        gzip_at = middleware.index("apps.core.middleware.StreamSafeGZipMiddleware")
        # GZipMiddleware must sit before anything that reads or writes the body.
        # After WhiteNoise on purpose: static files are served and compressed
        # by WhiteNoise itself and never reach this.
        self.assertGreater(
            gzip_at, middleware.index("whitenoise.middleware.WhiteNoiseMiddleware")
        )
        self.assertLess(
            gzip_at, middleware.index("django.middleware.common.CommonMiddleware")
        )

    def test_a_page_is_compressed_when_the_browser_accepts_it(self):
        response = self._client(accepts_gzip=True).get("/my-plan", follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Content-Encoding"), "gzip")

    def test_it_actually_gets_smaller(self):
        """A Content-Encoding header that saves nothing is decoration."""
        compressed = self._client(accepts_gzip=True).get("/my-plan", follow=True)
        plain = self._client(accepts_gzip=False).get("/my-plan", follow=True)
        self.assertLess(
            len(compressed.content),
            len(plain.content) // 2,
            "HTML should compress by well over half; it did not",
        )

    def test_a_client_that_cannot_decompress_still_gets_the_page(self):
        response = self._client(accepts_gzip=False).get("/my-plan", follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.headers.get("Content-Encoding"))


class StreamsAreNeverCompressedTest(TestCase):
    """The guard that makes compression safe to turn on at all."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="sse@edify.test",
            password="password123",
            name="SSE Tester",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            is_active=True,
        )

    def test_the_sse_endpoint_still_returns_a_stream_for_the_guard_to_skip(self):
        """The guard below is only worth anything while this stays streaming.

        Hitting /api/realtime/stream from a TestCase is not the way to check
        it: the view calls connections.close_all() (deliberately — an SSE
        connection must not hold a Postgres connection open for its lifetime),
        which tears down the test transaction and its session. So this asserts
        the shape the guard depends on, and the live endpoint was verified
        against the real server: 200, text/event-stream, streaming=True, no
        Content-Encoding.
        """
        import inspect

        from apps.realtime import views as realtime_views

        source = inspect.getsource(realtime_views.stream)
        self.assertIn("StreamingHttpResponse", source)
        self.assertIn("text/event-stream", source)

    def test_the_middleware_returns_streams_untouched(self):
        """Directly, so the rule holds for every streaming response and not
        just the one endpoint the test above happens to hit."""
        from django.http import StreamingHttpResponse

        from apps.core.middleware import StreamSafeGZipMiddleware

        middleware = StreamSafeGZipMiddleware(lambda request: None)
        streaming = StreamingHttpResponse(
            (f"data: {i}\n\n" for i in range(50)), content_type="text/event-stream"
        )
        request = (
            Client()
            .request(**{"PATH_INFO": "/x", "HTTP_ACCEPT_ENCODING": "gzip"})
            .wsgi_request
        )
        returned = middleware.process_response(request, streaming)
        self.assertIs(returned, streaming)
        self.assertNotIn("Content-Encoding", returned.headers)
