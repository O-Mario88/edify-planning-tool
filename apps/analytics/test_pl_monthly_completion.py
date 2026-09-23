from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from apps.analytics.pl_dashboard_service import ProgramLeadDashboardService


class MonthlyCompletionTest(SimpleTestCase):
    def context(self):
        qs = MagicMock()
        rows = qs.filter.return_value.exclude.return_value.annotate.return_value.values.return_value.annotate.return_value.order_by
        rows.return_value = [
            dict(
                completion_month=date(2026, 8, 1),
                responsible_staff_id="lead",
                monitored_by_staff_id=None,
                total=2,
                done=1,
            ),
            dict(
                completion_month=date(2026, 8, 1),
                responsible_staff_id=None,
                monitored_by_staff_id="s7",
                total=4,
                done=1,
            ),
            dict(
                completion_month=date(2026, 8, 1),
                responsible_staff_id="outside",
                monitored_by_staff_id="s0",
                total=1,
                done=1,
            ),
            dict(
                completion_month=date(2026, 8, 1),
                responsible_staff_id="s1",
                monitored_by_staff_id=None,
                total=1,
                done=0,
            ),
        ]
        team = [dict(staff_id=f"s{i}", name=f"Officer {i}") for i in range(8)]
        ids = {c["staff_id"] for c in team}
        return SimpleNamespace(
            acts=qs,
            fy="2026",
            today=date(2026, 9, 23),
            team=team,
            user=SimpleNamespace(name="Lead"),
            own_ids={"lead"},
            owner=lambda responsible, monitored: (responsible or monitored)
            if (responsible or monitored) in ids
            else None,
        )

    def test_lead_all_officers_and_partner_attribution(self):
        payload = ProgramLeadDashboardService.planning_progress_by_member(
            self.context()
        )
        self.assertEqual(len(payload["series"]), 9)
        august = payload["labels"].index("Aug 26")
        self.assertEqual(payload["series"][0]["data"][august], 50)
        self.assertEqual(payload["series"][-1]["data"][august], 25)
        self.assertIsNone(payload["series"][1]["data"][august])
        self.assertEqual(payload["series"][2]["data"][august], 0)
        self.assertTrue(payload["has_data"])
        self.assertLessEqual(len(payload["labels"]), 6)

    def test_future_fiscal_year_has_no_elapsed_months_or_query(self):
        ctx = self.context()
        ctx.fy = "2030"
        payload = ProgramLeadDashboardService.planning_progress_by_member(ctx)
        self.assertFalse(payload["has_data"])
        self.assertEqual(payload["labels"], [])
        ctx.acts.filter.assert_not_called()

    def test_chart_and_accessible_table_are_rendered(self):
        payload = ProgramLeadDashboardService.planning_progress_by_member(
            self.context()
        )
        html = render_to_string(
            "partials/dashboards/pl/programmes_view.html",
            {"planning_progress_chart": payload, "fy": "2026"},
        )
        self.assertIn('id="plCompletionChart"', html)
        self.assertIn('id="pl-completion-payload"', html)
        self.assertIn("Officer 7", html)
        self.assertIn("50%", html)
        self.assertIn("25%", html)
        self.assertIn("0%", html)

    def test_actual_activity_queryset_accepts_the_grouping(self):
        from apps.activities.models import Activity

        ctx = self.context()
        ctx.acts = Activity.objects.none()
        payload = ProgramLeadDashboardService.planning_progress_by_member(ctx)
        self.assertFalse(payload["has_data"])
        self.assertEqual(len(payload["series"]), 9)
