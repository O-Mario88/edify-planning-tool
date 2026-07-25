from __future__ import annotations

from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffGeographyAssignment,
    StaffProfile,
    StaffSchoolAssignment,
    User,
)
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.navigation import build_analytics_sections, build_sidebar_for_user
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


class SsaPerformancePageTest(TestCase):
    def setUp(self):
        self.fy = get_operational_fy()
        self.quarter = get_quarter_for_date()
        self.north = Region.objects.create(name="SSA North")
        self.south = Region.objects.create(name="SSA South")
        self.kitgum = District.objects.create(name="Kitgum SSA", region=self.north)
        self.gulu = District.objects.create(name="Gulu SSA", region=self.south)
        self.own_school = self._school("SSA-OWN", "Bright Future P/S", self.kitgum)
        self.other_school = self._school("SSA-OTHER", "Outside Scope P/S", self.gulu)

        self.cceo = self._user("ssa-cceo@edify.test", EdifyRole.CCEO.value)
        self.cceo_staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_staff, school_id=self.own_school.id
        )

    def _user(self, email: str, role: str) -> User:
        return User.objects.create_user(
            email=email,
            name=email.split("@")[0],
            roles=[role],
            active_role=role,
            password="password123",
            is_active=True,
        )

    def _school(self, code: str, name: str, district: District) -> School:
        return School.objects.create(
            school_id=code,
            name=name,
            region=district.region,
            district=district,
            current_fy_ssa_status="done",
        )

    def _ssa(
        self,
        school: School,
        average: float,
        *,
        status: str = "confirmed",
        days_ago: int = 0,
        weak_score: float | None = None,
    ) -> SsaRecord:
        record = SsaRecord.objects.create(
            school=school,
            fy=self.fy,
            quarter=self.quarter,
            date_of_ssa=timezone.now() - timedelta(days=days_ago),
            average_score=average,
            verification_status=status,
        )
        for intervention in SsaIntervention:
            score = (
                weak_score
                if intervention == SsaIntervention.TEACHING_ENVIRONMENT
                and weak_score is not None
                else average
            )
            SsaScore.objects.create(
                ssa_record=record, intervention=intervention.value, score=score
            )
        return record

    def test_cceo_page_uses_latest_confirmed_record_inside_own_scope(self):
        self._ssa(self.own_school, 4.0, days_ago=30)
        self._ssa(self.own_school, 8.0, days_ago=5, weak_score=3.0)
        self._ssa(self.own_school, 1.0, status="pending", days_ago=0)
        self._ssa(self.other_school, 2.0, days_ago=1)

        client = Client()
        client.force_login(self.cceo)
        response = client.get(f"/ssa?fy={self.fy}&quarter={self.quarter}")

        self.assertEqual(response.status_code, 200)
        dashboard = response.context["dashboard"]
        self.assertEqual(dashboard["kpis"]["total_schools"], 1)
        self.assertEqual(dashboard["kpis"]["assessed"], 1)
        self.assertEqual(dashboard["kpis"]["average_score"], 8.0)
        self.assertEqual(dashboard["kpis"]["high_risk"], 1)
        self.assertEqual(dashboard["urgent_schools"][0]["name"], "Bright Future P/S")
        self.assertNotContains(response, "Outside Scope P/S")

    def test_rvp_receives_assigned_region_aggregates_without_school_identity(self):
        self._ssa(self.own_school, 7.0, weak_score=3.0)
        self._ssa(self.other_school, 2.0, weak_score=1.0)
        rvp = self._user("ssa-rvp@edify.test", EdifyRole.REGIONAL_VICE_PRESIDENT.value)
        staff = StaffProfile.objects.create(user=rvp, title="RVP")
        StaffGeographyAssignment.objects.create(staff=staff, region_id=self.north.id)

        client = Client()
        client.force_login(rvp)
        response = client.get(f"/ssa?fy={self.fy}&quarter={self.quarter}")

        self.assertEqual(response.status_code, 200)
        dashboard = response.context["dashboard"]
        self.assertEqual(dashboard["kpis"]["total_schools"], 1)
        self.assertEqual(dashboard["kpis"]["average_score"], 7.0)
        self.assertFalse(dashboard["scope"]["can_view_school_details"])
        self.assertEqual(dashboard["urgent_schools"], [])
        self.assertNotContains(response, "Bright Future P/S")
        self.assertNotContains(response, "Outside Scope P/S")

    def test_every_role_has_ssa_performance_navigation(self):
        """Every role can still reach SSA Performance.

        It is no longer its own sidebar link — it is a section of the Analytics
        workspace — so the guarantee is that every role is offered the section,
        that the page opens, and that the sidebar marks the workspace as where
        the user currently is.
        """
        client = Client()
        for role in EdifyRole:
            user = self._user(f"{role.name.lower()}@ssa-nav.test", role.value)
            sections = build_analytics_sections(user, "/ssa")
            active_sidebar = {
                item["label"]
                for section in build_sidebar_for_user(user, "/ssa")
                for item in section["items"]
                if item["active"]
            }
            with self.subTest(role=role.value):
                self.assertIn("/ssa", {s["url"] for s in sections})
                self.assertEqual(
                    [s["label"] for s in sections if s["active"]],
                    ["SSA Performance"],
                )
                # Whatever the workspace entry is called for this role, it is
                # the thing highlighted while the user is on /ssa.
                self.assertTrue(active_sidebar)
                client.force_login(user)
                self.assertEqual(client.get("/ssa").status_code, 200)
                client.logout()

    def test_trend_starts_at_the_axis_not_part_way_across(self):
        """The window is seven years; a deployment with three years of
        confirmed SSA was drawing its line in the right-hand quarter behind
        four empty columns, which reads as a performance gap rather than years
        before anyone was collecting."""
        current = int(self.fy)
        for offset in (0, 1, 2):
            SsaRecord.objects.create(
                school=self.own_school,
                fy=str(current - offset),
                quarter=self.quarter,
                date_of_ssa=timezone.now() - timedelta(days=offset * 365),
                average_score=6.0,
                verification_status="confirmed",
            )

        client = Client()
        client.force_login(self.cceo)
        trend = client.get(f"/ssa?fy={self.fy}").context["dashboard"]["trend"]

        self.assertTrue(trend["has_data"])
        # No empty columns before the first measured year.
        self.assertIsNotNone(trend["points"][0]["value"])
        # And that first point sits on the left edge of the plot area.
        self.assertEqual(trend["points"][0]["x"], 48)
        self.assertTrue(trend["polyline"].startswith("48"))

    def test_trend_keeps_leading_years_once_they_are_measured(self):
        """Trimming is only for years that were never collected. A real gap at
        the start of the window is a finding and stays visible."""
        oldest = str(int(self.fy) - 6)
        SsaRecord.objects.create(
            school=self.own_school,
            fy=oldest,
            quarter=self.quarter,
            date_of_ssa=timezone.now() - timedelta(days=6 * 365),
            average_score=4.0,
            verification_status="confirmed",
        )
        self._ssa(self.own_school, 7.0)

        client = Client()
        client.force_login(self.cceo)
        trend = client.get(f"/ssa?fy={self.fy}").context["dashboard"]["trend"]

        self.assertEqual(len(trend["points"]), 7)
        self.assertEqual(trend["points"][0]["fy"], oldest)

    def test_export_obeys_role_capability(self):
        self._ssa(self.own_school, 7.0)
        client = Client()
        client.force_login(self.cceo)
        denied = client.get(f"/ssa/export?fy={self.fy}&quarter={self.quarter}")
        self.assertEqual(denied.status_code, 403)

        admin = self._user("ssa-admin@edify.test", EdifyRole.ADMIN.value)
        client.force_login(admin)
        allowed = client.get(f"/ssa/export?fy={self.fy}&quarter={self.quarter}")
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed["Content-Type"], "text/csv")
        self.assertContains(allowed, "Bright Future P/S")
