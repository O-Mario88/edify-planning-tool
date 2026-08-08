"""Heavy feature libraries load only on the workspaces that use them."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return ROOT.joinpath(relative_path).read_text(encoding="utf-8")


class FeatureAssetLoadingContractTest(SimpleTestCase):
    def test_chart_and_calendar_vendors_are_not_global(self):
        base = _read("templates/base.html")

        self.assertIn("{% block feature_head_js %}{% endblock %}", base)
        self.assertNotIn("js/vendor/apexcharts", base)
        self.assertNotIn("js/vendor/fullcalendar", base)

    def test_chart_workspaces_opt_in_to_apexcharts(self):
        pages = (
            "templates/pages/analytics/index.html",
            "templates/pages/analytics/cd_analytics.html",
            "templates/pages/analytics/pl_analytics.html",
            "templates/pages/dashboards/cd.html",
            "templates/pages/dashboards/hr.html",
            "templates/pages/dashboards/pl.html",
            "templates/pages/dashboards/rvp.html",
            "templates/pages/debriefs/dashboard.html",
            "templates/pages/hr/professional_development_dashboard.html",
            "templates/pages/targets/index.html",
        )
        for page in pages:
            with self.subTest(page=page):
                self.assertIn('include "partials/vendor/apexcharts.html"', _read(page))

    def test_calendar_workspaces_opt_in_to_fullcalendar(self):
        for page in (
            "templates/pages/leave/leave_calendar.html",
            "templates/pages/planning/index.html",
        ):
            with self.subTest(page=page):
                self.assertIn(
                    'include "partials/vendor/fullcalendar.html"', _read(page)
                )
