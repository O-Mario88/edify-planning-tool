"""A rejected security token never ends at Django's bare error page.

Reported from production on 2026-10-05: "CSRF verification failed. Request
aborted." Django replaces the CSRF secret every time a sign-in completes, so a
page rendered before that sign-in carries a token the server no longer accepts.
The application shell re-reads the cookie before it posts (csrf-sync.js); the
sign-in pages did not load that script, and the "Session paused" dialog opens
sign-in in a NEW tab — so every idle timeout left behind a sign-in tab whose
form could only ever be refused, with a page that says nothing a person can
act on.

Two things are held here:

  1. The sign-in layout loads the synchronizer, and the synchronizer also runs
     when a tab is returned to, which is the moment a token can have changed.
  2. When a token is refused anyway, the answer says nothing was changed and
     leaves the browser holding a token that works, so trying again succeeds.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase

from apps.core.rbac import EdifyRole

ROOT = Path(settings.BASE_DIR)
EMAIL = "stale-tab@edify.test"
PASSWORD = "password123"
DJANGO_PAGE = "CSRF verification failed"


def _user():
    return get_user_model().objects.create_user(
        email=EMAIL,
        password=PASSWORD,
        name="Stale Tab",
        roles=[EdifyRole.CCEO.value],
        active_role=EdifyRole.CCEO.value,
        is_active=True,
    )


def _sign_in_form(client) -> dict:
    """The sign-in form as a tab holds it: rendered now, posted later."""
    response = client.get("/login")
    return {
        "email": EMAIL,
        "password": PASSWORD,
        "csrfmiddlewaretoken": response.context["csrf_token"],
    }


class StaleSignInTabTest(TestCase):
    """Two sign-in tabs in one browser; the second is used after the first."""

    def setUp(self):
        _user()
        self.browser = Client(enforce_csrf_checks=True)

    def test_second_tab_lands_on_the_dashboard_when_already_signed_in(self):
        second_tab = _sign_in_form(self.browser)
        first_tab = _sign_in_form(self.browser)
        self.assertEqual(self.browser.post("/login", first_tab).status_code, 302)

        response = self.browser.post("/login", second_tab, follow=True)

        self.assertNotContains(response, DJANGO_PAGE)
        self.assertEqual(response.redirect_chain[0][0], "/login")
        self.assertEqual(response.redirect_chain[-1][0], "/dashboard")

    def test_second_tab_is_asked_to_sign_in_again_after_a_sign_out(self):
        second_tab = _sign_in_form(self.browser)
        first_tab = _sign_in_form(self.browser)
        self.browser.post("/login", first_tab)
        self.browser.post(
            "/logout", {"csrfmiddlewaretoken": self.browser.cookies["csrftoken"].value}
        )

        response = self.browser.post("/login", second_tab, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, DJANGO_PAGE)
        self.assertContains(response, "Please sign in again")
        self.assertNotIn("_auth_user_id", self.browser.session)

        # The page it landed on carries a token that works.
        again = dict(second_tab, csrfmiddlewaretoken=response.context["csrf_token"])
        self.assertEqual(self.browser.post("/login", again).status_code, 302)
        self.assertIn("_auth_user_id", self.browser.session)

    def test_a_refused_password_is_never_checked(self):
        """The redirect must not become a way to sign in without a token."""
        self.browser.get("/login")
        response = self.browser.post(
            "/login",
            {"email": EMAIL, "password": PASSWORD, "csrfmiddlewaretoken": "x" * 64},
            follow=True,
        )
        self.assertNotIn("_auth_user_id", self.browser.session)
        self.assertEqual(response.redirect_chain[-1][0], "/login")


class RefusedTokenAnswerTest(TestCase):
    def setUp(self):
        self.user = _user()
        self.browser = Client(enforce_csrf_checks=True)
        self.browser.force_login(self.user)

    def test_a_full_page_post_gets_a_page_a_person_can_act_on(self):
        response = self.browser.post(
            "/logout", {"csrfmiddlewaretoken": "x" * 64}, HTTP_REFERER="/settings"
        )

        self.assertEqual(response.status_code, 403)
        body = response.content.decode()
        self.assertNotIn(DJANGO_PAGE, body)
        self.assertIn("Nothing was changed", body)
        self.assertIn("data-go-back", body)
        # Still signed in: the refusal changed nothing.
        self.assertIn("_auth_user_id", self.browser.session)

    def test_the_answer_leaves_the_browser_holding_a_token(self):
        """ "CSRF cookie not set" must not repeat on the next attempt."""
        self.browser.cookies.pop("csrftoken", None)
        response = self.browser.post("/logout", {})
        self.assertEqual(response.status_code, 403)
        self.assertIn("csrftoken", response.cookies)

        token = response.cookies["csrftoken"].value
        retry = self.browser.post("/logout", {"csrfmiddlewaretoken": token})
        self.assertEqual(retry.status_code, 302)

    def test_an_htmx_post_gets_a_short_answer_not_a_page(self):
        response = self.browser.post("/logout", {}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        self.assertIn("Nothing was changed", response.content.decode())
        self.assertNotIn("<html", response.content.decode())

    def test_a_script_asking_for_json_gets_json(self):
        response = self.browser.post("/logout", {}, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json()["code"], "csrf_failed")

    def test_the_page_repeats_nothing_the_request_carried(self):
        response = self.browser.post(
            "/logout",
            {"note": "typed-by-someone"},
            HTTP_REFERER="https://elsewhere.example/phish",
        )
        body = response.content.decode()
        self.assertNotIn("elsewhere.example", body)
        self.assertNotIn("typed-by-someone", body)
        self.assertIn('href="/dashboard" data-go-back', body)

    def test_someone_signed_out_is_pointed_at_sign_in(self):
        visitor = Client(enforce_csrf_checks=True)
        response = visitor.post("/logout", {})
        self.assertEqual(response.status_code, 403)
        self.assertIn('href="/login" data-go-back', response.content.decode())

    def test_the_refusal_is_logged_with_what_is_needed_to_trace_it(self):
        browser = Client(enforce_csrf_checks=True)
        browser.get("/login")  # the cookie a real browser would be holding
        browser.force_login(self.user)
        with self.assertLogs("edify.security", level="WARNING") as logs:
            browser.post(
                "/logout",
                {"csrfmiddlewaretoken": "x" * 64},
                HTTP_REFERER="https://testserver/settings?tab=security",
            )
        line = logs.output[0]
        self.assertIn("csrf_rejected", line)
        self.assertIn('"path": "/logout"', line)
        self.assertIn('"signed_in": true', line)
        self.assertIn('"cookie": true', line)
        self.assertIn('"referrer": "testserver/settings"', line)
        self.assertNotIn("tab=security", line)
        self.assertNotIn(browser.cookies["csrftoken"].value, line)


class SynchronizerContractTest(SimpleTestCase):
    def setUp(self):
        self.layout = (ROOT / "templates/layouts/login.html").read_text("utf-8")
        self.script = (ROOT / "static/js/csrf-sync.js").read_text("utf-8")

    def test_the_failure_view_is_configured(self):
        self.assertEqual(
            settings.CSRF_FAILURE_VIEW, "apps.frontend.views.csrf_views.csrf_failure"
        )

    def test_sign_in_pages_load_the_synchronizer_before_their_own_script(self):
        self.assertIn("js/csrf-sync.js", self.layout)
        self.assertLess(
            self.layout.index("js/csrf-sync.js"), self.layout.index("js/login.js")
        )

    def test_a_tab_resynchronizes_when_it_is_returned_to(self):
        """form.submit() and fetch() fire no submit event, so the token must
        already be right when someone comes back from signing in elsewhere."""
        self.assertIn('window.addEventListener("focus"', self.script)
        self.assertIn('document.addEventListener("visibilitychange"', self.script)
