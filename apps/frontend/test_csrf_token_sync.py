from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


ROOT = Path(settings.BASE_DIR)


class CsrfTokenSynchronizationContractTest(SimpleTestCase):
    def setUp(self):
        self.base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
        self.script = (ROOT / "static/js/csrf-sync.js").read_text(encoding="utf-8")

    def test_cookie_is_readable_by_the_token_synchronizer(self):
        self.assertFalse(settings.CSRF_COOKIE_HTTPONLY)

    def test_synchronizer_loads_before_frontend_code_that_posts(self):
        csrf_sync = self.base.index("js/csrf-sync.js")
        defect_beacon = self.base.index("js/platform-defect-beacon.js")
        self.assertLess(csrf_sync, defect_beacon)

    def test_native_and_htmx_posts_receive_the_current_cookie_token(self):
        self.assertIn('document.addEventListener(\n    "submit"', self.script)
        self.assertIn('document.addEventListener("htmx:configRequest"', self.script)
        self.assertIn('event.detail.headers["X-CSRFToken"] = token;', self.script)
        self.assertIn('field.value = token;', self.script)

    def test_restored_and_swapped_pages_are_resynchronized(self):
        self.assertIn('window.addEventListener("pageshow"', self.script)
        self.assertIn('document.addEventListener("htmx:load"', self.script)

