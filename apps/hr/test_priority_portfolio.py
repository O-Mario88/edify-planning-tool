from datetime import date

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.professional_development.models import ProfessionalDevelopmentRequest
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

from .models import PerformancePriority, PerformanceReview
from .priority_portfolio import priority_portfolio


class PriorityPortfolioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="portfolio@test.org",
            name="Portfolio Owner",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="test-password",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.create(user=cls.user, country="Uganda")
        region = Region.objects.create(name="Portfolio Region")
        district = District.objects.create(name="Portfolio District", region=region)
        cls.school = School.objects.create(
            school_id="PORT-1",
            name="Portfolio School",
            region=region,
            district=district,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(staff=cls.staff, school_id=cls.school.id)
        current = SsaRecord.objects.create(
            school=cls.school,
            date_of_ssa=timezone.now(),
            fy="2027",
            quarter="Q1",
            verification_status="confirmed",
            uploaded_by=cls.user.id,
        )
        SsaScore.objects.create(
            ssa_record=current, intervention="leadership", score=4
        )
        old = SsaRecord.objects.create(
            school=cls.school,
            date_of_ssa=timezone.now(),
            fy="2026",
            quarter="Q4",
            verification_status="confirmed",
            uploaded_by=cls.user.id,
        )
        SsaScore.objects.create(
            ssa_record=old, intervention="financial_health", score=1
        )
        review = PerformanceReview.objects.create(
            staff=cls.staff,
            period="FY2027",
            fy="2027",
            due_date=date(2027, 6, 30),
        )
        PerformancePriority.objects.create(
            review=review,
            outcome_statement="Build a stronger field coaching habit",
            measures_of_success="Coach monthly",
            weight=20,
        )
        for fy, course in (("2027", "Leadership certificate"), ("2026", "Old course")):
            ProfessionalDevelopmentRequest.objects.create(
                staff_id=cls.staff.id,
                fy=fy,
                staff_name=cls.user.name,
                course_name=course,
                course_category="leadership",
                start_date=date(2027, 1, 1),
                end_date=date(2027, 1, 2),
            )

    def test_sources_are_grouped_and_financial_year_scoped(self):
        groups = priority_portfolio(
            user=self.user,
            fy="2027",
            strategic_milestones=[
                {
                    "allocationId": "allocation-1",
                    "milestone": "Verified coaching visits",
                    "priority": "School quality",
                    "remaining": 3,
                    "fyPlan": 10,
                }
            ],
        )
        by_key = {group["key"]: group["rows"] for group in groups}
        self.assertEqual(by_key["planning"][0]["title"], "Verified coaching visits")
        self.assertEqual(by_key["ssa"][0]["title"], "Leadership")
        self.assertNotIn("Financial Health", {row["title"] for row in by_key["ssa"]})
        self.assertEqual(
            by_key["manual"][0]["title"], "Build a stronger field coaching habit"
        )
        self.assertEqual(by_key["pd"][0]["title"], "Leadership certificate")
        self.assertNotIn("Old course", {row["title"] for row in by_key["pd"]})

    def test_planning_feed_uses_approved_allocation_before_period_phasing(self):
        groups = priority_portfolio(
            user=self.user,
            fy="2027",
            strategic_milestones=[
                {
                    "allocationId": "allocation-1",
                    "milestone": "Verified coaching visits",
                    "priority": "School quality",
                    "allocatedTarget": 10,
                    "fyPlan": 0,
                    "fyActual": 0,
                    "remaining": 0,
                }
            ],
        )

        planning = next(group for group in groups if group["key"] == "planning")
        self.assertEqual(planning["rows"][0]["meta"], "10 remaining of 10")
