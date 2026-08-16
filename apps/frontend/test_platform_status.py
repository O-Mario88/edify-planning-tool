"""Static contracts for honest connectivity and session-expiry states."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return ROOT.joinpath(path).read_text(encoding="utf-8")


class PlatformStatusContractTest(SimpleTestCase):
    def test_the_shared_layout_loads_resilience_assets_and_surfaces(self):
        base = _read("templates/base.html")
        login = _read("templates/layouts/login.html")
        status = _read("templates/partials/connectivity_status.html")
        self.assertIn("css/components/platform-status.css", base)
        self.assertIn("js/platform-status.js", base)
        self.assertIn("partials/connectivity_status.html", base)
        self.assertIn("css/components/platform-status.css", login)
        self.assertIn("js/platform-status.js", login)
        self.assertIn("partials/connectivity_status.html", login)
        self.assertIn('id="edify-connectivity-status"', status)
        self.assertIn('role="status"', status)
        self.assertIn('id="edify-session-expired-dialog"', base)
        self.assertIn('aria-labelledby="edify-session-expired-title"', base)
        self.assertIn('aria-describedby="edify-session-expired-description"', base)

    def test_login_uses_a_real_browser_theme_color(self):
        login = _read("templates/layouts/login.html")
        self.assertIn('<meta name="theme-color" content="#2d4862">', login)
        self.assertNotIn('content="var(', login)

    def test_offline_mutations_fail_visibly_without_clearing_the_page(self):
        behavior = _read("static/js/platform-status.js")
        self.assertIn("window.addEventListener('offline'", behavior)
        self.assertIn("window.addEventListener('online'", behavior)
        self.assertIn("document.addEventListener('htmx:beforeRequest'", behavior)
        self.assertIn("event.preventDefault()", behavior)
        self.assertIn("This action was not sent because you are offline", behavior)
        self.assertNotIn("location.reload", behavior)

    def test_an_expired_htmx_session_preserves_the_current_dom(self):
        behavior = _read("static/js/platform-status.js")
        self.assertIn("xhr.status === 401", behavior)
        self.assertIn("responseIsLogin(xhr)", behavior)
        self.assertIn("event.detail.shouldSwap = false", behavior)
        self.assertIn("showSessionExpired()", behavior)

    def test_resilience_surfaces_respect_mobile_motion_and_forced_colors(self):
        styles = _read("static/css/components/platform-status.css")
        self.assertIn("env(safe-area-inset-top)", styles)
        self.assertIn("@media (max-width: 30rem)", styles)
        self.assertIn("@media (prefers-reduced-motion: no-preference)", styles)
        self.assertIn("@media (forced-colors: active)", styles)
