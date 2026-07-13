"""AnalyticsDashboardService — the generic /analytics cockpit (CCEO/IA/HR/
Accountant/Admin land here). Regression coverage for the fabricated-target-
denominator bug: when nothing configures a real target, the page must show
an honest empty state, never infer "the target" from how much work happens
to exist (which reads as near-100% "achievement" by construction and
violates the no-mock-data rule).
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffTargetProfile
from apps.activities.models import Activity
from apps.analytics.analytics_dashboard_service import AnalyticsDashboardService
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.targets.models import TargetSetting

User = get_user_model()
FY = "2026"


class AnalyticsDashboardTargetDenominatorTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="R")
        self.district = District.objects.create(name="D", region=self.region, district_type="primary")
        self.user = User.objects.create_user(
            email="acct@t.org", name="Accountant One",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value, password="x", is_active=True,
        )
        self.staff = User.objects.create_user(
            email="cceo@t.org", name="CCEO One", roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value, password="x", is_active=True,
        )
        self.staff_sp = StaffProfile.objects.create(user=self.staff, title="CCEO")
        self.school = School.objects.create(
            school_id="S-AD1", name="Analytics School", region=self.region, district=self.district,
        )

    def _act(self, status, evidence="accepted", quarter="Q3"):
        return Activity.objects.create(
            school=self.school, activity_type="school_visit", delivery_type="staff",
            status=status, responsible_staff_id=self.staff_sp.id, fy=FY, quarter=quarter,
            planned_date=date(2026, 4, 10), evidence_status=evidence,
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 4, 10, 9, 0)),
        )

    def _filters(self, **overrides):
        base = {
            "fy": FY, "quarter": "Q3", "region": None, "district": None, "cluster": None,
            "staff": None, "partner": None, "school_type": None, "activity_type": None, "q": None,
        }
        base.update(overrides)
        return base

    def test_no_target_configured_shows_honest_empty_state(self):
        # Plenty of real activity, several already achieved this quarter —
        # a fabricated denominator built from this count would render a
        # coincidentally near-100% "achievement". No TargetSetting and no
        # StaffTargetProfile exist for this FY at all.
        for _ in range(5):
            self._act("ia_verified")
        for _ in range(10):
            self._act("scheduled", evidence="pending")

        self.assertFalse(TargetSetting.objects.filter(fy=FY, is_active=True).exists())
        self.assertFalse(StaffTargetProfile.objects.filter(fy=FY).exists())

        data = AnalyticsDashboardService.get_analytics_data(self.user, self._filters())

        self.assertEqual(data["kpis"]["target_achievement"]["value"], "No Target Set")
        strip = {k["label"]: k for k in data["kpi_strip_items"]}
        self.assertEqual(strip["Overall Target Achievement"]["value"], "No Target Set")
        self.assertIsNone(strip["Overall Target Achievement"]["raw_value"])
        # Never a percentage sign on a fabricated number.
        self.assertNotIn("%", data["kpis"]["target_achievement"]["value"])

    def test_configured_target_still_computes_a_real_percentage(self):
        # A real, explicitly configured target restores the normal path.
        TargetSetting.objects.create(
            fy=FY, target_type="SCHOOL_VISIT", scope_type="country", target_unit="count",
            target_value=8, set_by_user_id=self.user.id, set_by_role="Accountant",
        )
        for _ in range(2):
            self._act("ia_verified")

        data = AnalyticsDashboardService.get_analytics_data(self.user, self._filters())

        self.assertEqual(data["kpis"]["target_achievement"]["value"], "100%")
        strip = {k["label"]: k for k in data["kpi_strip_items"]}
        self.assertEqual(strip["Overall Target Achievement"]["raw_value"], 100)
