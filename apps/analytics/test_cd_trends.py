"""Every CD tile carries last year's delta, and the workload tile is real.

The strip had no trend anywhere, so a director could not tell progress from
slippage; "Staff Productivity" was the country activity completion rate and
said nothing about staff. Tiles now compare with the same period a year
earlier, the country chart carries last year's completions, and the workload
tile reads the governed StaffSupportCapacity (owner, 2026-09-03).
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupportCapacity,
)
from apps.activities.models import Activity
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()


class CdTrendTilesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Trend Region")
        district = District.objects.create(name="Trend District", region=region)
        cls.cd = User.objects.create_user(
            email="trend-cd@t.org",
            name="Trend CD",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="x",
            is_active=True,
        )
        StaffProfile.objects.create(user=cls.cd, title="CD", country="Uganda")
        cceo = User.objects.create_user(
            email="trend-cceo@t.org",
            name="Trend CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        cls.cceo_sp = StaffProfile.objects.create(user=cceo, title="CCEO")
        cls.schools = [
            School.objects.create(
                school_id=f"TR-{i}", name=f"Trend {i}", region=region, district=district
            )
            for i in range(1, 4)
        ]
        # Last year: one school served. This year: three.
        last_year = timezone.now() - timedelta(days=365)
        Activity.objects.create(
            school=cls.schools[0],
            activity_type="school_visit",
            status="ia_verified",
            fy="2025",
            responsible_staff_id=cls.cceo_sp.id,
            scheduled_date=last_year,
            planned_date=last_year.date(),
        )
        for school in cls.schools:
            Activity.objects.create(
                school=school,
                activity_type="school_visit",
                status="ia_verified",
                fy="2026",
                responsible_staff_id=cls.cceo_sp.id,
                scheduled_date=timezone.now() - timedelta(days=1),
                planned_date=(timezone.now() - timedelta(days=1)).date(),
            )

    def _tiles(self):
        from apps.analytics.cd_dashboard_service import CDDashboardService

        data = CDDashboardService.get_dashboard(self.cd, fy="2026")
        return {t["label"]: t for t in data["kpi_strip_items"]}, data

    def test_active_schools_carries_last_years_delta(self):
        tiles, _ = self._tiles()
        tile = tiles["Active Schools Served"]
        self.assertEqual(tile["value"], "3")
        self.assertEqual(tile["trend"]["direction"], "up")
        self.assertIn("+2", tile["trend"]["value"])
        self.assertIn("FY2025", tile["trend"]["value"])

    def test_the_country_chart_carries_last_years_completions(self):
        _, data = self._tiles()
        chart = data["country_performance"]
        self.assertEqual(chart["prior_fy"], "2025")
        self.assertEqual(len(chart["prior_completed"]), 12)
        self.assertEqual(sum(chart["prior_completed"]), 1)

    def test_the_workload_tile_reads_governed_capacity(self):
        for school in self.schools:
            StaffSchoolAssignment.objects.create(
                staff=self.cceo_sp, school_id=school.id
            )
        tiles, _ = self._tiles()
        self.assertEqual(tiles["Staff Over Capacity"]["value"], "0 of 1")
        StaffSupportCapacity.objects.create(
            staff=self.cceo_sp,
            fy="2026",
            max_direct_schools_supported=2,
            set_by_user_id=self.cd.id,
            set_by_role="CountryDirector",
        )
        tiles, _ = self._tiles()
        tile = tiles["Staff Over Capacity"]
        self.assertEqual(tile["value"], "1 of 1")
        self.assertEqual(tile["link"], "/staff")
        self.assertNotIn("Staff Productivity", tiles)

    def test_the_dashboard_renders_the_trend(self):
        self.client.force_login(self.cd)
        response = self.client.get("/dashboard?fy=2026&view=operations")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "vs FY2025")
        self.assertContains(response, "Completed FY2025")
