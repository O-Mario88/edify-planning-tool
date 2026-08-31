from django.test import SimpleTestCase

from scripts.concurrent_read_probe import BROWSER_HEADERS


class ConcurrentReadProbeTransportTests(SimpleTestCase):
    def test_probe_requests_the_compressed_transport_supported_browsers_use(self):
        self.assertEqual(BROWSER_HEADERS["Accept-Encoding"], "gzip")
        self.assertIn("edify-staging-probe", BROWSER_HEADERS["User-Agent"])
