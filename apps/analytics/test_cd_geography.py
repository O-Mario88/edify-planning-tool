"""Geography for everything, not only SSA.

The dashboard's regional list was delivery only, region only, and every other
country number was one national figure. The breakdown below reads delivery,
backlog and money from the same scoped activities as the tiles, region by
region and district by district; the analytics workspace gains a region
filter; Country Planning Oversight gains a district filter.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()


class CdGeographyBreakdownTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.north = Region.objects.create(name="Geo North")
        cls.south = Region.objects.create(name="Geo South")
        cls.d1 = District.objects.create(name="Geo D1", region=cls.north)
        cls.d2 = District.objects.create(name="Geo D2", region=cls.north)
        cls.d3 = District.objects.create(name="Geo D3", region=cls.south)
        cls.cd = User.objects.create_user(
            email="geo-cd@t.org",
            name="Geo CD",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="x",
            is_active=True,
        )
        StaffProfile.objects.create(user=cls.cd, title="CD", country="Uganda")
        cls.cceo = User.objects.create_user(
            email="geo-cceo@t.org",
            name="Geo CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        cls.cceo_sp = StaffProfile.objects.create(user=cls.cceo, title="CCEO")

        def school(sid, district):
            return School.objects.create(
                school_id=sid,
                name=f"School {sid}",
                region=district.region,
                district=district,
                school_type="client",
            )

        cls.s1, cls.s2, cls.s3 = (
            school("GEO-1", cls.d1),
            school("GEO-2", cls.d2),
            school("GEO-3", cls.d3),
        )
        yesterday = timezone.now() - timedelta(days=1)
        fy = "2026"

        def act(school, status, when):
            return Activity.objects.create(
                school=school,
                activity_type="school_visit",
                status=status,
                fy=fy,
                responsible_staff_id=cls.cceo_sp.id,
                scheduled_date=when,
                planned_date=when.date(),
                est_cost_cents=10_000,
            )

        act(cls.s1, "ia_verified", yesterday)  # done
        act(cls.s1, "scheduled", yesterday)  # overdue backlog
        act(cls.s2, "scheduled", timezone.now() + timedelta(days=5))  # upcoming
        act(cls.s3, "ia_verified", yesterday)

    def test_regions_roll_up_delivery_backlog_and_budget_from_their_districts(self):
        from apps.analytics.cd_analytics_service import (
            _country_activities,
            resolve_cd_scope,
        )
        from apps.analytics.cd_dashboard_service import CDDashboardService

        cd = resolve_cd_scope("2026")
        geo = CDDashboardService.geography_breakdown(cd, _country_activities(cd))
        by_name = {r["name"]: r for r in geo["rows"]}
        north = by_name["Geo North"]
        self.assertEqual(north["schools"], 2)
        self.assertEqual(north["planned"], 3)
        self.assertEqual(north["completed"], 1)
        self.assertEqual(north["backlog"], 1)
        self.assertEqual(north["planned_budget"], 30_000)
        districts = {d["name"]: d for d in north["districts"]}
        self.assertEqual(districts["Geo D1"]["backlog"], 1)
        self.assertEqual(districts["Geo D2"]["backlog"], 0)
        south = by_name["Geo South"]
        self.assertEqual(
            (south["planned"], south["completed"], south["backlog"]), (1, 1, 0)
        )
        self.assertEqual(geo["totals"]["planned"], 4)
        # Backlog first, so the region needing attention is on top.
        self.assertEqual(geo["rows"][0]["name"], "Geo North")

    def test_the_dashboard_renders_the_breakdown(self):
        self.client.force_login(self.cd)
        response = self.client.get("/dashboard?fy=2026")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-cd-geography")
        self.assertContains(response, "Geo D1")

    def test_analytics_narrows_to_a_region(self):
        from apps.analytics.cd_analytics_service import (
            _country_activities,
            resolve_cd_scope,
        )

        south = resolve_cd_scope("2026", filters={"region": self.south.id})
        self.assertEqual(set(south.school_ids), {self.s3.id})
        self.assertEqual(_country_activities(south).count(), 1)
        self.client.force_login(self.cd)
        response = self.client.get(
            f"/analytics/country-director?fy=2026&region={self.south.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="region"')


class OversightDistrictFilterTest(TestCase):
    def test_the_country_plan_filters_by_district(self):
        from apps.planning.oversight_service import PlanningOversightItem, apply_filters

        a = PlanningOversightItem(
            stage="staff_scheduled", district_id="d1", district_name="D1"
        )
        b = PlanningOversightItem(
            stage="staff_scheduled", district_id="d2", district_name="D2"
        )
        self.assertEqual(apply_filters([a, b], {"district_id": "d2"}), [b])
        self.assertEqual(apply_filters([a, b], {}), [a, b])
