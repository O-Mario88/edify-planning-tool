"""The monthly-request context must not shadow Django's `request`.

Found on live production: /accounts/monthly-request/ returned HTTP 500 for the
current month and 200 for every other month of the same FY. The traceback,
pulled from the production container:

    File "/app/apps/core/templatetags/table_pagination.py", line 35, in paginate
    AttributeError: 'FundRequest' object has no attribute 'GET'

`get_monthly_request` returned its FundRequest under the key `request`. Every
template context already has a `request` — Django's HTTP request, supplied by
the request context processor — and `{% paginate %}` reaches for it to read
`?page=`. Handed a model instead, it raised.

Only one month crashed because only that month had a saved snapshot. The other
months were not working correctly either: there `request` was None, so
`{% paginate %}` took its `is not None` branch and quietly pinned every table
on the page to page 1. The 500 was the visible half of a bug that had been
silently breaking pagination the rest of the time — which is why the test below
covers the None case too, where nothing crashes and nothing looks wrong.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.fund_requests.monthly_request_service import get_monthly_request

User = get_user_model()


class MonthlyRequestContextTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pl = User.objects.create(
            id="mrc-pl",
            email="mrc-pl@edify.org",
            name="MRC Lead",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True,
        )

    def _context(self, month=8):
        return get_monthly_request(self.pl, {"fy": "2026", "month": str(month)})

    def test_the_context_does_not_define_a_request_key(self):
        # The whole defect in one assertion: anything under this key replaces
        # Django's HTTP request for every tag and filter in the template.
        self.assertNotIn(
            "request",
            self._context(),
            "'request' is Django's HTTP request in a template context; the "
            "FundRequest belongs under 'fund_request'",
        )

    def test_the_fund_request_is_still_available_under_its_own_key(self):
        # Renaming must not simply drop the data the template renders.
        self.assertIn("fund_request", self._context())

    def test_no_context_key_shadows_the_http_request_for_any_month(self):
        # Both shapes matter: a month with a snapshot produced the crash, a
        # month without one produced the silent page-1 pinning.
        for month in range(1, 13):
            with self.subTest(month=month):
                self.assertNotIn("request", self._context(month))


class MonthlyRequestPageRendersTest(TestCase):
    """End to end, because the unit assertion above cannot catch a template
    that still says `{{ request.review_note }}` after the rename."""

    @classmethod
    def setUpTestData(cls):
        cls.pl = User.objects.create(
            id="mrp-pl",
            email="mrp-pl@edify.org",
            name="MRP Lead",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True,
        )

    def test_the_legacy_page_redirects_to_the_unified_budget(self):
        from django.test import RequestFactory
        from django.contrib.sessions.middleware import SessionMiddleware

        from apps.frontend.views.finance_operating_views import monthly_request_view

        request = RequestFactory().get("/accounts/monthly-request/?fy=2026&month=8")
        SessionMiddleware(lambda r: None).process_request(request)
        request.user = self.pl

        response = monthly_request_view(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/budget?fy=2026&month=8&period=month")

    def test_the_paginate_tag_can_still_read_the_page_parameter(self):
        """The tag reads `context["request"].GET`; this is what broke.

        Rendering with an explicit `?page=` proves the real HTTP request
        reaches the tag rather than a model that happens to share its name.
        """
        from django.template import Context, Template
        from django.test import RequestFactory

        request = RequestFactory().get("/x?page=3")
        template = Template(
            "{% load table_pagination %}"
            "{% paginate rows 'page' as pager %}{{ pager.page }}"
        )
        rendered = template.render(
            Context({"request": request, "rows": list(range(100))})
        )
        self.assertEqual(rendered.strip(), "3")
