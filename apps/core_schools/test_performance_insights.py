"""Staff vs Partner Performance redesign — data-honesty guardrails (§19).

Missing data never renders as 0%, benchmarks come from the scoped cohort,
the trend uses real verified periods, and the template composes the
approved 2+2+1 grid."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.core_schools.core_planning_services import (
    CoreAssessmentService,
    CoreStaffPartnerPerformanceService,
)
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord

User = get_user_model()
ROOT = Path(__file__).resolve().parents[2]


class PerformanceInsightsServiceTests(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(
            name="Mukono", region=self.region, district_type="primary"
        )
        self.owner = User.objects.create_user(
            email="owner@pi.org", name="Olive Owner", password="x",
            roles=["CCEO"], active_role="CCEO", is_active=True,
        )
        self.owner_sp = StaffProfile.objects.create(user=self.owner)
        self.school = School.objects.create(
            school_id="PI-1", name="Scored School", school_type="core",
            region=self.region, district=self.district, enrollment=50,
            account_owner_id=self.owner_sp.id,
        )
        self.unscored = School.objects.create(
            school_id="PI-2", name="Unscored School", school_type="core",
            region=self.region, district=self.district, enrollment=50,
            account_owner_id="someone-else",
        )
        SsaRecord.objects.create(
            school=self.school, fy="2026", average_score=6.0,
            date_of_ssa=timezone.make_aware(dt.datetime(2026, 5, 1)),
            verification_status="confirmed", collector_type="staff",
        )

    def _perf(self):
        return CoreStaffPartnerPerformanceService.get_staff_vs_partner_performance(
            School.objects.filter(school_type="core"), "2026"
        )

    def test_org_average_and_vs_avg_come_from_the_scoped_cohort(self):
        perf = self._perf()
        self.assertIsNotNone(perf["org_average"])
        row = next(r for r in perf["staff_insights"] if r["name"] == "Olive Owner")
        self.assertEqual(row["school_count"], 1)
        self.assertFalse(row["insufficient"])
        self.assertAlmostEqual(
            row["vs_avg"], round(row["score"] - perf["org_average"], 1), places=1
        )

    def test_missing_data_is_insufficient_never_zero(self):
        owner2 = User.objects.create_user(
            email="o2@pi.org", name="No Scores", password="x",
            roles=["CCEO"], active_role="CCEO", is_active=True,
        )
        sp2 = StaffProfile.objects.create(user=owner2)
        self.unscored.account_owner_id = sp2.id
        self.unscored.save(update_fields=["account_owner_id"])
        perf = self._perf()
        row = next(r for r in perf["staff_insights"] if r["name"] == "No Scores")
        self.assertTrue(row["insufficient"])
        self.assertIsNone(row["score"])
        # And nobody without schools in scope appears at all.
        User.objects.create_user(
            email="o3@pi.org", name="No Schools", password="x",
            roles=["CCEO"], active_role="CCEO", is_active=True,
        )
        names = {r["name"] for r in self._perf()["staff_insights"]}
        self.assertNotIn("No Schools", names)

    def test_regions_are_scoped_and_verified_only_with_top_region(self):
        other = Region.objects.create(name="Northern")
        # A confirmed record OUTSIDE the cohort's schools must not leak in.
        d2 = District.objects.create(
            name="Gulu", region=other, district_type="primary"
        )
        s2 = School.objects.create(
            school_id="PI-3", name="Client Elsewhere", school_type="client",
            region=other, district=d2, enrollment=10,
        )
        SsaRecord.objects.create(
            school=s2, fy="2026", average_score=9.9,
            date_of_ssa=timezone.make_aware(dt.datetime(2026, 5, 2)),
            verification_status="confirmed", collector_type="staff",
        )
        perf = self._perf()
        names = {r["name"] for r in perf["region_insights"]}
        self.assertIn("Central", names)
        self.assertNotIn("Northern", names)  # no core schools there
        self.assertEqual(perf["top_region"]["name"], "Central")

    def test_trend_uses_real_labelled_verified_periods(self):
        SsaRecord.objects.create(
            school=self.school, fy="2026", average_score=5.0,
            date_of_ssa=timezone.make_aware(dt.datetime(2026, 7, 1)),
            verification_status="confirmed", collector_type="staff",
        )
        # An unverified record must not shape the trend.
        SsaRecord.objects.create(
            school=self.school, fy="2026", average_score=1.0,
            date_of_ssa=timezone.make_aware(dt.datetime(2026, 7, 2)),
            verification_status="pending", collector_type="staff",
        )
        trend = CoreAssessmentService.get_monthly_trend(
            School.objects.filter(school_type="core")
        )
        self.assertEqual([t["label"] for t in trend], ["May 2026", "Jul 2026"])
        self.assertEqual(trend[1]["avg"], 5.0)

    def test_template_composes_the_approved_grid(self):
        src = (ROOT / "templates/partials/core_schools/performance_insights.html").read_text()
        self.assertIn("xl:grid-cols-2", src)
        self.assertIn("xl:col-span-2", src)
        self.assertNotIn("lg:grid-cols-5", src)
        self.assertIn("Insufficient comparable data", src)
        self.assertIn("not a performance rating", src)
        # Gap semantics: score points, never percentage points.
        self.assertIn("score points", src)
