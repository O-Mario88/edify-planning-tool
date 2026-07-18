"""Regression tests: DashboardMetricsService must never fall back to
fabricated numbers (no-mock-data rule). Covers:
  - target_achievement honest 0%% when nothing was planned this month
    (was a hardcoded 72).
  - operational_health is a real computed composite (was a hardcoded 93).
  - No fabricated trend badges ("+4%%"/"+6%%"/"+12%%"/"+5%%").
  - Program Lead KPI card reuses the canonical PLAnalyticsService team-target
    formula under the "Team Execution Progress %%" label (was a locally
    fabricated "Team Target Achievement" + hardcoded "8/10" CCEOs On Track).
  - CD/RVP/Admin "Budget Utilization" is a real disbursed/approved query
    (was a hardcoded "78%%").
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.command_center.dashboard_service import DashboardMetricsService
from apps.core.fy import get_operational_fy
from apps.fund_requests.models import WeeklyFundRequest

User = get_user_model()


def _kpi(items, label):
    return next((i for i in items if i["label"] == label), None)


class HonestFallbacksTest(TestCase):
    """No activities/schools in scope this month -> honest zeroes, not the
    old hardcoded 72 / 93."""

    def setUp(self):
        self.user = User.objects.create(
            id="cceo-dash-fix-1",
            email="cceo-dash-fix@edify.org",
            name="CCEO Dash Fix",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        StaffProfile.objects.create(
            id="staff-cceo-dash-fix-1", user=self.user, title="CCEO"
        )

    def test_target_achievement_and_operational_health_are_honest_zero(self):
        metrics = DashboardMetricsService.get_dashboard_metrics(self.user)
        self.assertEqual(metrics["kpis"]["target_achievement"], 0)
        self.assertNotEqual(metrics["kpis"]["target_achievement"], 72)
        self.assertEqual(metrics["signals"]["operational_health"], 0)
        self.assertNotEqual(metrics["signals"]["operational_health"], 93)

    def test_cceo_kpi_card_has_no_fabricated_trend(self):
        metrics = DashboardMetricsService.get_dashboard_metrics(self.user)
        card = _kpi(metrics["kpi_strip_items"], "My Target Achievement")
        self.assertIsNotNone(card)
        self.assertNotIn("trend", card)


class ProgramLeadKpiTest(TestCase):
    """The Program Lead KPI strip must reuse the canonical
    PLAnalyticsService._team_target() formula, not a locally fabricated
    number under the "Team Target Achievement" label reserved for the
    canonical figure, and must not show a hardcoded CCEOs-On-Track count."""

    def setUp(self):
        self.user = User.objects.create(
            id="pl-dash-fix-1",
            email="pl-dash-fix@edify.org",
            name="PL Dash Fix",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True,
        )
        StaffProfile.objects.create(
            id="staff-pl-dash-fix-1", user=self.user, title="Program Lead"
        )

    def test_uses_canonical_team_target_formula_and_real_cceo_count(self):
        fake_scope = type(
            "FakeScope", (), {"cceos": [{"staff_id": f"s{i}"} for i in range(10)]}
        )()
        with (
            patch(
                "apps.analytics.pl_analytics_service.resolve_pl_scope",
                return_value=fake_scope,
            ),
            patch(
                "apps.analytics.pl_analytics_service.PLAnalyticsService._team_target",
                return_value=(37, 6),
            ),
        ):
            metrics = DashboardMetricsService.get_dashboard_metrics(self.user)

        items = metrics["kpi_strip_items"]
        self.assertIsNone(
            _kpi(items, "Team Target Achievement"),
            "label is reserved for the canonical ledger-weighted figure, "
            "not this execution-cockpit metric",
        )
        progress_card = _kpi(items, "Team Execution Progress %")
        self.assertIsNotNone(progress_card)
        self.assertEqual(progress_card["value"], "37%")
        self.assertEqual(progress_card["raw_value"], 37)
        self.assertNotIn("trend", progress_card)

        on_track_card = _kpi(items, "CCEOs On Track")
        self.assertIsNotNone(on_track_card)
        self.assertEqual(on_track_card["value"], "6 / 10")
        self.assertEqual(on_track_card["raw_value"], 6)
        self.assertNotEqual(on_track_card["value"], "8/10")


class CountryLevelBudgetUtilizationTest(TestCase):
    """CD/RVP/Admin "Budget Utilization" card must be a real disbursed /
    approved query against WeeklyFundRequest, not a hardcoded 78%%."""

    def setUp(self):
        self.user = User.objects.create(
            id="cd-dash-fix-1",
            email="cd-dash-fix@edify.org",
            name="CD Dash Fix",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )
        StaffProfile.objects.create(
            id="staff-cd-dash-fix-1", user=self.user, title="CD"
        )
        self.fy = get_operational_fy()

    def test_budget_utilization_is_computed_not_hardcoded(self):
        # approved=confirmed_for_advance(100)+disbursed(100)=200, disbursed=100 -> 50%.
        WeeklyFundRequest.objects.create(
            fy=self.fy,
            week_start_date="2026-07-06",
            week_end_date="2026-07-12",
            responsible_user="staff-cd-dash-fix-owner-1",
            total_amount=100,
            status="confirmed_for_advance",
        )
        WeeklyFundRequest.objects.create(
            fy=self.fy,
            week_start_date="2026-07-13",
            week_end_date="2026-07-19",
            responsible_user="staff-cd-dash-fix-owner-2",
            total_amount=100,
            disbursed_amount=100,
            status="disbursed",
        )

        metrics = DashboardMetricsService.get_dashboard_metrics(self.user)
        card = _kpi(metrics["kpi_strip_items"], "Budget Utilization")
        self.assertIsNotNone(card)
        self.assertEqual(card["value"], "50%")
        self.assertEqual(card["raw_value"], 50)
        self.assertNotEqual(card["value"], "78%")

    def test_no_fund_requests_is_an_honest_zero(self):
        metrics = DashboardMetricsService.get_dashboard_metrics(self.user)
        card = _kpi(metrics["kpi_strip_items"], "Budget Utilization")
        self.assertEqual(card["value"], "0%")
        self.assertNotEqual(card["value"], "78%")

    def test_country_target_achievement_card_has_no_fabricated_trend(self):
        metrics = DashboardMetricsService.get_dashboard_metrics(self.user)
        card = _kpi(metrics["kpi_strip_items"], "Country Target Achievement")
        self.assertIsNotNone(card)
        self.assertNotIn("trend", card)


class WeakestInterventionsRankingTest(TestCase):
    """The Admin/CD dashboard's "Weakest interventions" panel must actually
    list the LOWEST-scoring interventions.

    ssa_averages is ordered by -avg_val (best first). After the top 3 are
    taken as `best_interventions`, the remainder is still descending, so the
    old `weakest_interventions[:3]` returned the 4th/5th/6th BEST and
    labelled them "Weakest" — while the two genuinely worst interventions
    were never displayed at all.
    """

    def setUp(self):
        from apps.geography.models import District, Region
        from apps.schools.models import School

        self.user = User.objects.create(
            id="admin-weakest-1",
            email="admin-weakest@edify.org",
            name="Admin Weakest",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        region = Region.objects.create(name="Weakest Region")
        district = District.objects.create(name="Weakest District", region=region)
        self.school = School.objects.create(
            school_id="SCH-WEAKEST-1",
            name="Weakest Primary",
            region=region,
            district=district,
        )

    def test_weakest_panel_lists_the_lowest_scoring_interventions(self):
        from datetime import datetime, timezone as dt_tz

        from apps.core.enums import SsaIntervention
        from apps.ssa.models import SsaRecord, SsaScore

        record = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=datetime(2026, 6, 1, tzinfo=dt_tz.utc),
            fy="2026",
            quarter="Q3",
            average_score=5.0,
            verification_status="confirmed",
            uploaded_by=self.user.id,
        )
        # Give all eight interventions distinct, strictly descending scores in
        # canonical enum order: 9.0, 8.0, ... 2.0.
        ordered = list(SsaIntervention)
        for i, interv in enumerate(ordered):
            SsaScore.objects.create(
                ssa_record=record, intervention=interv.value, score=9.0 - i
            )

        metrics = DashboardMetricsService.get_dashboard_metrics(self.user)
        labels = dict(SsaIntervention.choices)

        best_names = [row["name"] for row in metrics["best_interventions"]]
        weakest_names = [row["name"] for row in metrics["weakest_interventions"]]

        # Best = the three highest (9.0, 8.0, 7.0).
        self.assertEqual(best_names, [labels[i.value] for i in ordered[:3]])

        # Weakest = the three lowest (2.0, 3.0, 4.0), worst first — NOT the
        # 4th/5th/6th best (6.0, 5.0, 4.0) the old slice produced.
        self.assertEqual(
            weakest_names, [labels[i.value] for i in reversed(ordered[-3:])]
        )
        weakest_scores = [row["score"] for row in metrics["weakest_interventions"]]
        self.assertEqual(weakest_scores, [2.0, 3.0, 4.0])

        # The two genuinely worst interventions must be present.
        self.assertIn(labels[ordered[-1].value], weakest_names)
        self.assertIn(labels[ordered[-2].value], weakest_names)
