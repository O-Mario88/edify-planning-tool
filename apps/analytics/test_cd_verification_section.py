"""The CD sees the verification backlog by age and the data-quality checks.

Verification throughput, closure quality and data quality were IA-only
pages; the CD's only signal was a raw pending count with a decorative
"30+ days" label (owner, 2026-09-03).
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


class VerificationSectionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Ver Region")
        district = District.objects.create(name="Ver District", region=region)
        cls.school = School.objects.create(
            school_id="VER-1", name="Ver School", region=region, district=district
        )
        cls.cd = User.objects.create_user(
            email="ver-cd@t.org",
            name="Ver CD",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="x",
            is_active=True,
        )
        StaffProfile.objects.create(user=cls.cd, title="CD", country="Uganda")
        cceo = User.objects.create_user(
            email="ver-cceo@t.org",
            name="Ver CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        sp = StaffProfile.objects.create(user=cceo, title="CCEO")
        now = timezone.now()
        for days in (2, 15, 45):
            Activity.objects.create(
                school=cls.school,
                activity_type="school_visit",
                status="awaiting_ia_verification",
                fy="2026",
                responsible_staff_id=sp.id,
                scheduled_date=now - timedelta(days=days + 1),
                planned_date=(now - timedelta(days=days + 1)).date(),
                submitted_to_ia_at=now - timedelta(days=days),
            )
        Activity.objects.create(
            school=cls.school,
            activity_type="school_visit",
            status="returned_by_ia",
            fy="2026",
            responsible_staff_id=sp.id,
            scheduled_date=now - timedelta(days=3),
            planned_date=(now - timedelta(days=3)).date(),
        )

    def test_the_backlog_is_bucketed_by_age(self):
        from apps.analytics.cd_analytics_service import (
            _country_activities,
            resolve_cd_scope,
        )
        from apps.analytics.cd_dashboard_service import CDDashboardService

        cd = resolve_cd_scope("2026")
        v = CDDashboardService.verification_and_quality(cd, _country_activities(cd))
        self.assertEqual(v["waiting"], 3)
        self.assertEqual(
            v["buckets"], {"under_7": 1, "d7_30": 1, "over_30": 1, "undated": 0}
        )
        self.assertEqual(v["returned"], 1)
        self.assertIn("checks", v)

    def test_the_dashboard_renders_the_section_and_the_cd_may_open_ia_analytics(self):
        self.client.force_login(self.cd)
        response = self.client.get("/dashboard?fy=2026&view=operations")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-cd-verification")
        self.assertContains(response, "1 over 30")
        self.assertEqual(self.client.get("/ia/dashboard/").status_code, 200)
