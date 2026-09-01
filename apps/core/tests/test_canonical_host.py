"""Canonical-host normalisation — INC-2026-08-03-01.

The incident left the apex serving GoDaddy's parked lander while the real
application answered only on ``www``. These tests pin the two behaviours the
repair depends on: every alternate host reaches the canonical one in exactly
ONE redirect, and the middleware stays completely inert until it is armed.

The one-hop property is the whole point. It is also the easiest thing to lose
later by reordering MIDDLEWARE, so it is asserted end-to-end through the real
stack rather than by calling the middleware directly.
"""

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import resolve

CANONICAL = "edifyplanning.app"
ALTERNATE = "www.edifyplanning.app"
HOSTS = [CANONICAL, ALTERNATE, "testserver", "localhost"]


@override_settings(
    CANONICAL_HOST="", ALLOWED_HOSTS=HOSTS, SECURE_SSL_REDIRECT=False, DEBUG=False
)
class CanonicalHostDisabledTests(TestCase):
    """Unset CANONICAL_HOST must change nothing.

    This is what makes the change safe to deploy BEFORE the apex resolves.
    Ship it armed and every visitor is redirected to a host that does not yet
    answer, turning a half-broken domain into a fully broken one.
    """

    def test_alternate_host_is_served_not_redirected(self):
        response = self.client.get("/", HTTP_HOST=ALTERNATE)
        self.assertNotIn(response.status_code, (301, 308))

    def test_canonical_host_is_served(self):
        response = self.client.get("/", HTTP_HOST=CANONICAL)
        self.assertNotIn(response.status_code, (301, 308))


@override_settings(
    CANONICAL_HOST=CANONICAL,
    ALLOWED_HOSTS=HOSTS,
    SECURE_SSL_REDIRECT=False,
    DEBUG=False,
)
class CanonicalHostEnabledTests(TestCase):
    def test_alternate_host_redirects_permanently_to_canonical(self):
        response = self.client.get("/", HTTP_HOST=ALTERNATE)
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], f"http://{CANONICAL}/")

    def test_canonical_host_is_not_redirected(self):
        response = self.client.get("/", HTTP_HOST=CANONICAL)
        self.assertNotIn(response.status_code, (301, 308))

    def test_path_is_preserved(self):
        response = self.client.get("/login", HTTP_HOST=ALTERNATE)
        self.assertEqual(response["Location"], f"http://{CANONICAL}/login")

    def test_query_string_is_preserved(self):
        # A password-reset or invitation link carries its token in the query.
        # Dropping it here would present the user with a bare form and no way
        # to tell why their link "expired".
        response = self.client.get(
            "/login", {"next": "/dashboard", "token": "abc123"}, HTTP_HOST=ALTERNATE
        )
        location = response["Location"]
        self.assertIn("next=%2Fdashboard", location)
        self.assertIn("token=abc123", location)

    def test_post_uses_308_so_the_body_survives(self):
        # 301 on a POST is replayed by the browser as GET: the submitted form
        # silently vanishes. 308 preserves method and body.
        response = self.client.post("/login", {"email": "a@b.c"}, HTTP_HOST=ALTERNATE)
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response["Location"], f"http://{CANONICAL}/login")

    def test_health_probe_is_never_redirected(self):
        # An orchestrator reads 301 as "not ready" and will not follow it, so a
        # redirected probe fails every instance and rolls the deploy back.
        # Use liveness here because readiness intentionally queries PostgreSQL;
        # this middleware test should not require an integration-test database.
        response = self.client.get("/api/health/live", HTTP_HOST=ALTERNATE)
        self.assertNotIn(response.status_code, (301, 308))

    def test_unknown_host_still_gets_disallowed_host(self):
        # An unrecognised Host must reach Django's own 400, not be laundered
        # into a 301 that hides the probe from the logs.
        with self.assertLogs("django.security.DisallowedHost", level="ERROR"):
            response = self.client.get("/", HTTP_HOST="evil.example.com")
        self.assertEqual(response.status_code, 400)


@override_settings(
    CANONICAL_HOST=CANONICAL,
    ALLOWED_HOSTS=HOSTS,
    SECURE_SSL_REDIRECT=True,
    DEBUG=False,
)
class SingleHopTests(TestCase):
    """The requirement: http://www reaches https://apex in ONE redirect.

    Two hops is what happens when CanonicalHostMiddleware sits behind
    SecurityMiddleware — the TLS redirect fires first on the wrong host. This
    test is the guard on that ordering.
    """

    def test_insecure_alternate_host_collapses_to_one_redirect(self):
        response = self.client.get("/", HTTP_HOST=ALTERNATE, secure=False)
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], f"https://{CANONICAL}/")

    def test_insecure_canonical_host_still_upgrades_to_https(self):
        # CanonicalHostMiddleware owns scheme normalisation while enabled so it
        # can preserve methods and keep host+scheme changes to one response.
        response = self.client.get("/", HTTP_HOST=CANONICAL, secure=False)
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], f"https://{CANONICAL}/")

    def test_insecure_canonical_post_preserves_method(self):
        response = self.client.post(
            "/login", {"email": "a@b.c"}, HTTP_HOST=CANONICAL, secure=False
        )
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response["Location"], f"https://{CANONICAL}/login")


class LanderLegacyRouteTests(SimpleTestCase):
    """/lander was GoDaddy's, never ours. After the apex moves here it is ours,
    and the people who reach it are following a link cached during the outage."""

    def test_lander_resolves_to_the_legacy_redirect(self):
        self.assertEqual(resolve("/lander").url_name, "lander-legacy")

    def test_lander_redirects_permanently_to_root(self):
        response = self.client.get("/lander")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/")

    def test_trailing_slash_form_also_redirects(self):
        response = self.client.get("/lander/")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/")
