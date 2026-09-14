"""Controls audit defects (2026-09-14), expressed as expected behaviour.

The defects are fixed; these probes now guard against their return.
No database or live messaging is used. Permission wrappers are bypassed only for
these isolated view-contract probes; role permissions are tested separately.
"""

import inspect
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import patch

from django.core.paginator import Paginator
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory


# F-01 (batch export ignores selection) is fixed and covered against the
# database by apps.fund_requests.test_money_unit_regression.BatchPaymentsSelectionTest;
# its mocked-queryset probe cannot exercise the id re-check the fix added.


class Buttons(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = None
        self.labels = []

    def handle_starttag(self, tag, attrs):
        if tag == "button":
            self.active = []

    def handle_data(self, data):
        if self.active is not None:
            self.active.append(data)

    def handle_endtag(self, tag):
        if tag == "button" and self.active is not None:
            self.labels.append("".join(self.active).strip())
            self.active = None


def test_directory_gap_is_not_a_button():
    paginator = Paginator(list(range(703)), 15)
    html = render_to_string(
        "partials/schools/table.html",
        {
            "directory_read_only": True,
            "view_models": [],
            "page_obj": paginator.page(2),
            "pages_list": list(
                paginator.get_elided_page_range(2, on_each_side=1, on_ends=1)
            ),
        },
    )
    parser = Buttons()
    parser.feed(html)
    assert "…" not in parser.labels


def test_directory_no_matches_does_not_claim_empty_registry():
    request = RequestFactory().get(
        "/schools", {"district": "Abim", "tab": "unclustered"}
    )
    html = render_to_string(
        "partials/schools/table.html",
        {
            "request": request,
            "directory_read_only": True,
            "view_models": [],
            "total_schools": 3,
            "active_tab": "unclustered",
        },
    )
    assert "No schools uploaded yet." not in html


def test_snapshot_passes_the_requested_period_to_delivery():
    from apps.frontend.views.analytics_views import analytics_schedule_report_view

    request = RequestFactory().post(
        "/analytics/schedule-report", {"categories": ["reach"], "fy": "2025"}
    )
    request.user = SimpleNamespace(id="audit-user", active_role="ImpactAssessment")
    with (
        patch(
            "apps.analytics.report_delivery.send_analytics_snapshot",
            return_value=SimpleNamespace(id="audit-thread"),
        ) as send,
        patch("apps.audit.services.log"),
        patch(
            "apps.frontend.views.analytics_views.render",
            return_value=HttpResponse("ok"),
        ),
    ):
        response = inspect.unwrap(analytics_schedule_report_view)(request)
    assert response.status_code == 200
    assert send.call_args.kwargs.get("filters", {}).get("fy") == "2025"
