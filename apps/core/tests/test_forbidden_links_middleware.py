"""A link the role cannot follow is not drawn (owner, 2026-09-27: "Forbidden
pages should not be shown completely. only the right roles should see")."""

from types import SimpleNamespace
from unittest import mock

from django.http import HttpResponse, JsonResponse
from django.test import RequestFactory, SimpleTestCase

from apps.core.forbidden_links_middleware import ForbiddenLinksMiddleware

DENIED = ("/planning", "/staff/", "/system-health", "/planning/schedule-modal")


def _can_open(user, url):
    return not url.startswith(DENIED)


class ForbiddenLinksMiddlewareTests(SimpleTestCase):
    def _render(self, html, *, user=None, response=None):
        request = RequestFactory().get("/dashboard")
        request.user = user or SimpleNamespace(is_authenticated=True)
        middleware = ForbiddenLinksMiddleware(
            lambda _request: response or HttpResponse(html)
        )
        with mock.patch("apps.core.permissions.can_open_url", _can_open):
            return middleware(request).content.decode()

    def test_a_control_to_a_forbidden_page_is_removed(self):
        html = self._render(
            '<main><a href="/planning" class="btn btn-ghost h-8">Open Planning</a>'
            '<a href="/my-plan" class="btn">Open My Plan</a></main>'
        )
        self.assertNotIn("Open Planning", html)
        self.assertIn('href="/my-plan"', html)

    def test_tabs_menu_items_and_arrow_links_are_controls(self):
        html = self._render(
            '<a href="/planning" role="tab">Planning</a>'
            '<a href="/planning?x=1" class="row-menu__item">Plan it</a>'
            '<a href="/system-health" class="edify-text-caption">Location data quality →</a>'
            '<a href="/planning" class="app-sidebar__item">Planning</a>'
        )
        self.assertEqual(html, "")

    def test_a_name_keeps_its_words_and_loses_its_link(self):
        html = self._render(
            '<td><a href="/staff/42" class="hover:underline edify-table-link" title="Profile">Paul N.</a></td>'
        )
        self.assertEqual(
            html,
            '<td><span class="hover:underline edify-table-link" title="Profile" '
            "data-edify-link-off>Paul N.</span></td>",
        )

    def test_a_button_that_requests_a_forbidden_drawer_is_removed(self):
        html = self._render(
            '<button type="button" hx-get="/planning/schedule-modal?school_id=1">Schedule</button>'
            '<button type="button" hx-get="/schools/1/add-to-cluster">Add</button>'
        )
        self.assertNotIn("Schedule", html)
        self.assertIn("Add</button>", html)

    def test_scripts_anonymous_users_and_other_responses_are_untouched(self):
        script = '<script>const t = \'<a href="/planning" class="btn">x</a>\';</script>'
        self.assertEqual(self._render(script), script)
        anonymous = SimpleNamespace(is_authenticated=False)
        link = '<a href="/planning" class="btn">Open</a>'
        self.assertEqual(self._render(link, user=anonymous), link)
        data = JsonResponse({"html": link})
        self.assertIn("Open", self._render("", response=data))
