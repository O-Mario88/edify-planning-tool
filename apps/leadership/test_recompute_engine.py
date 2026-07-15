"""Tests for apps.leadership.services.recompute() -- built in the 2026-07-15
system audit to replace the prior stub (which only re-counted existing
insights instead of generating any from live data).

Each test grounds one detector in real, minimal fixture data and asserts a
real LeadershipDecisionInsight is produced with the expected decision_type
and scope. A final test covers the idempotency contract shared with
apps.budget_intelligence.services.recompute(): unreviewed auto: insights are
regenerated on every call, reviewed ones are preserved.
"""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupportCapacity,
)
from apps.activities.models import Activity, ActivityType
from apps.geography.models import District, Region
from apps.hr.models import EmployeeRelationsCase, PerformanceImprovementPlan
from apps.leadership import services
from apps.leadership.models import (
    DecisionStatus,
    DecisionType,
    LeadershipDecisionInsight,
)
from apps.partners.models import Partner
from apps.schools.models import School
from apps.ssa.models import SsaRecord

User = get_user_model()


class RecruitmentGapDetectorTest(TestCase):
    def test_district_with_many_unmatched_schools_flags_recruitment(self):
        region = Region.objects.create(name="Recruit Region")
        district = District.objects.create(name="Recruit District", region=region)
        for i in range(5):
            School.objects.create(
                school_id=f"REC-{i}",
                name=f"Recruit School {i}",
                region=region,
                district=district,
                account_owner_status="unmatched" if i < 4 else "matched",
            )
        result = services.recompute({"fy": "2026"}, principal=None)
        self.assertGreaterEqual(result["generatedCount"], 1)
        insight = LeadershipDecisionInsight.objects.get(
            decision_type=DecisionType.RECRUITMENT.value, scope_id__startswith="auto:r:"
        )
        self.assertEqual(insight.scope_id, f"auto:r:{district.id}")
        self.assertEqual(insight.metrics["unmatched_schools"], 4)


class StaffCapacityOverloadDetectorTest(TestCase):
    def test_staff_over_capacity_flags_staff_addition(self):
        user = User.objects.create_user(
            email="overload@test.org",
            name="Overload CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="password",
            is_active=True,
        )
        profile = StaffProfile.objects.create(user=user, title="CCEO")
        StaffSupportCapacity.objects.create(
            staff=profile,
            fy="2026",
            max_direct_schools_supported=3,
            set_by_user_id="cd-1",
            set_by_role="CountryDirector",
        )
        region = Region.objects.create(name="Overload Region")
        district = District.objects.create(name="Overload District", region=region)
        for i in range(5):
            school = School.objects.create(
                school_id=f"OVL-{i}",
                name=f"Overload School {i}",
                region=region,
                district=district,
            )
            StaffSchoolAssignment.objects.create(staff=profile, school_id=school.id)

        result = services.recompute({"fy": "2026"}, principal=None)
        self.assertGreaterEqual(result["generatedCount"], 1)
        insight = LeadershipDecisionInsight.objects.get(scope_id=f"auto:o:{profile.id}")
        self.assertEqual(insight.decision_type, DecisionType.STAFF_ADDITION.value)
        self.assertEqual(insight.metrics["assigned_schools"], 5)
        self.assertEqual(insight.metrics["capacity"], 3)


class PartnerPerformanceDetectorTest(TestCase):
    def test_high_return_rate_partner_flags_risk(self):
        partner = Partner.objects.create(name="Risky Partner")
        region = Region.objects.create(name="Partner Region")
        district = District.objects.create(name="Partner District", region=region)
        school = School.objects.create(
            school_id="PTR-1", name="Partner School", region=region, district=district
        )
        for i in range(6):
            Activity.objects.create(
                school=school,
                delivery_type="partner",
                activity_type=ActivityType.SCHOOL_VISIT,
                status="ia_verified" if i >= 2 else "returned",
                fy="2026",
                assigned_partner_id=partner.id,
                ia_verification_status="confirmed" if i >= 2 else "returned",
            )
        result = services.recompute({"fy": "2026"}, principal=None)
        self.assertGreaterEqual(result["generatedCount"], 1)
        insight = LeadershipDecisionInsight.objects.get(
            scope_id=f"auto:pr:{partner.id}"
        )
        self.assertEqual(insight.decision_type, DecisionType.PARTNER.value)
        self.assertEqual(insight.metrics["returned"], 2)


class StaffHrRiskDetectorTest(TestCase):
    def test_active_pip_flags_staff_hr(self):
        user = User.objects.create_user(
            email="pip@test.org",
            name="PIP Staff",
            roles=["CCEO"],
            active_role="CCEO",
            password="password",
            is_active=True,
        )
        profile = StaffProfile.objects.create(user=user, title="CCEO")
        PerformanceImprovementPlan.objects.create(
            staff=profile,
            status="Active",
            cause="execution gap",
            action_plan="Weekly check-ins with supervisor.",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 9, 1),
        )
        result = services.recompute({"fy": "2026"}, principal=None)
        self.assertGreaterEqual(result["generatedCount"], 1)
        insight = LeadershipDecisionInsight.objects.get(
            scope_id=f"auto:hp:{profile.id}"
        )
        self.assertEqual(insight.decision_type, DecisionType.STAFF_HR.value)

    def test_open_critical_case_flags_country_aggregate_not_a_named_individual(self):
        EmployeeRelationsCase.objects.create(
            case_type="Safeguarding Referral",
            severity="critical",
            status="Investigation",
            description="Redacted.",
        )
        result = services.recompute({"fy": "2026"}, principal=None)
        self.assertGreaterEqual(result["generatedCount"], 1)
        insight = LeadershipDecisionInsight.objects.get(scope_id="auto:hr_cases_open")
        self.assertEqual(insight.scope_type, "country")
        self.assertEqual(insight.metrics["critical_cases"], 1)


class RegionalInvestmentDetectorTest(TestCase):
    def test_declining_ssa_flags_needs_support(self):
        region = Region.objects.create(name="Declining Region")
        district = District.objects.create(name="Declining District", region=region)
        school = School.objects.create(
            school_id="DECL-1",
            name="Declining School",
            region=region,
            district=district,
        )
        SsaRecord.objects.create(
            school=school,
            date_of_ssa=timezone.now() - timedelta(days=400),
            fy="2025",
            quarter="Q2",
            average_score=7.5,
        )
        SsaRecord.objects.create(
            school=school,
            date_of_ssa=timezone.now(),
            fy="2026",
            quarter="Q2",
            average_score=4.0,
        )
        result = services.recompute({"fy": "2026"}, principal=None)
        self.assertGreaterEqual(result["generatedCount"], 1)
        insight = LeadershipDecisionInsight.objects.get(scope_id=f"auto:rs:{region.id}")
        self.assertEqual(insight.decision_type, DecisionType.REGIONAL_INVESTMENT.value)
        self.assertEqual(insight.risk_level, "high")


class RecomputeIdempotencyTest(TestCase):
    def setUp(self):
        region = Region.objects.create(name="Idem Region")
        district = District.objects.create(name="Idem District", region=region)
        for i in range(5):
            School.objects.create(
                school_id=f"IDEM-{i}",
                name=f"Idem School {i}",
                region=region,
                district=district,
                account_owner_status="unmatched" if i < 4 else "matched",
            )
        self.district_id = district.id

    def test_rerun_does_not_duplicate_unreviewed_insights(self):
        services.recompute({"fy": "2026"}, principal=None)
        first_count = LeadershipDecisionInsight.objects.filter(
            scope_id=f"auto:r:{self.district_id}"
        ).count()
        services.recompute({"fy": "2026"}, principal=None)
        second_count = LeadershipDecisionInsight.objects.filter(
            scope_id=f"auto:r:{self.district_id}"
        ).count()
        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 1)

    def test_reviewed_insight_survives_rerun(self):
        services.recompute({"fy": "2026"}, principal=None)
        insight = LeadershipDecisionInsight.objects.get(
            scope_id=f"auto:r:{self.district_id}"
        )
        insight.status = DecisionStatus.ACCEPTED.value
        insight.reviewed_at = timezone.now()
        insight.reviewed_by_user_id = "cd-reviewer"
        insight.save()

        services.recompute({"fy": "2026"}, principal=None)

        insight.refresh_from_db()
        self.assertEqual(insight.status, DecisionStatus.ACCEPTED.value)
        self.assertEqual(
            LeadershipDecisionInsight.objects.filter(
                scope_id=f"auto:r:{self.district_id}"
            ).count(),
            1,
        )
