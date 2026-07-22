"""The Priority Engine's mandate rules, each pinned by execution.

Real-time means DERIVED LIVE: a verified activity changes the number on the
next read, with no sync job. Partner work adds weight separately, never as
direct execution. PD rows merge automatically; values and amendments stay
manual.
"""

from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.hr.models import PerformanceCycle
from apps.hr.performance_engine import (
    build_draft_agreement,
    development_rows,
    live_progress,
    request_amendment,
    approve_amendment,
)
from apps.schools.models import School


def _user(email, role):
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
        status="active",
    )


class EngineFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="PE Region")
        cls.district = District.objects.create(name="PE District", region=region)
        cls.cceo = _user("pe-cceo@t.org", EdifyRole.CCEO.value)
        cls.sp = StaffProfile.objects.create(user=cls.cceo, country="Uganda")
        cls.schools = []
        for i in range(4):
            school = School.objects.create(
                name=f"PE {i}",
                school_id=f"PE-{i}",
                region_id=region.id,
                district_id=cls.district.id,
                school_type="client",
            )
            StaffSchoolAssignment.objects.create(staff=cls.sp, school_id=school.id)
            cls.schools.append(school)
        cls.hr = _user("pe-hr@t.org", EdifyRole.HUMAN_RESOURCES.value)
        cls.cycle = PerformanceCycle.objects.create(fy="2026", opened_by=cls.hr)


class DraftBuilderTests(EngineFixture):
    def test_denominators_come_from_the_real_portfolio(self):
        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        ssa = review.priorities.get(metric_key="ssa_coverage")
        self.assertEqual(
            ssa.target_number,
            4,
            "no percentage without a denominator — and the denominator is "
            "the actual assigned-school count, not a typed number",
        )
        self.assertIn("4", ssa.target)

    def test_the_builder_is_idempotent(self):
        first = build_draft_agreement(self.sp, self.cycle, self.hr)
        second = build_draft_agreement(self.sp, self.cycle, self.hr)
        self.assertEqual(first.id, second.id)

    def test_weights_total_one_hundred(self):
        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        self.assertEqual(sum(p.weight for p in review.priorities.all()), 100)


class LiveProgressTests(EngineFixture):
    def test_a_verified_visit_updates_progress_on_the_next_read(self):
        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        visits = review.priorities.get(metric_key="direct_visits")
        self.assertEqual(live_progress(visits)["actual"], 0)
        Activity.objects.create(
            school_id=self.schools[0].id,
            activity_type="school_visit",
            status="ia_verified",
            responsible_staff_id=self.sp.id,
            fy="2026",
            quarter="Q4",
        )
        # No sync step, no job — the next read carries the verified work.
        self.assertEqual(live_progress(visits)["actual"], 1)

    def test_unverified_work_does_not_count(self):
        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        visits = review.priorities.get(metric_key="direct_visits")
        Activity.objects.create(
            school_id=self.schools[0].id,
            activity_type="school_visit",
            status="completion_started",
            responsible_staff_id=self.sp.id,
            fy="2026",
            quarter="Q4",
        )
        self.assertEqual(live_progress(visits)["actual"], 0)

    def test_partner_work_weights_partner_management_not_direct_execution(self):
        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        visits = review.priorities.get(metric_key="direct_visits")
        partner_mgmt = review.priorities.get(metric_key="partner_supported_schools")
        Activity.objects.create(
            school_id=self.schools[1].id,
            activity_type="school_visit",
            status="ia_verified",
            delivery_type="partner",
            monitored_by_staff_id=self.sp.id,
            fy="2026",
            quarter="Q4",
        )
        self.assertEqual(
            live_progress(visits)["actual"],
            0,
            "partner-delivered work must never count as direct execution",
        )
        self.assertEqual(
            live_progress(partner_mgmt)["actual"],
            1,
            "a school reached through a supervised partner adds weight to "
            "the separate partner-management priority",
        )


class DevelopmentMergeTests(EngineFixture):
    def test_pd_rows_appear_automatically_and_manual_rows_append(self):
        from apps.hr.models import DevelopmentPlanItem
        from apps.professional_development.models import (
            ProfessionalDevelopmentRequest,
        )

        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        ProfessionalDevelopmentRequest.objects.create(
            staff_id=self.sp.id,
            staff_name="PE CCEO",
            course_name="Instructional Leadership",
            course_category="leadership",
            requested_amount_cents=100_00,
            status="approved",
            start_date=timezone.now().date(),
            end_date=timezone.now().date(),
        )
        DevelopmentPlanItem.objects.create(
            review=review, description="Shadow a senior PL for one week"
        )
        rows = development_rows(review)
        sources = {r["source"] for r in rows}
        self.assertEqual(sources, {"pd_workflow", "manual"})
        pd_row = next(r for r in rows if r["source"] == "pd_workflow")
        self.assertFalse(pd_row["editable"], "the PD lifecycle stays in the PD app")


class AmendmentTests(EngineFixture):
    def test_amendments_are_manual_reasoned_and_not_self_approved(self):
        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        priority = review.priorities.first()
        with self.assertRaises(BadRequest):
            request_amendment(priority, {"reason": "  "}, self.cceo)
        amendment = request_amendment(
            priority,
            {"reason": "Portfolio grew by 6 schools", "changed_target_number": 10},
            self.cceo,
        )
        with self.assertRaises(Forbidden):
            approve_amendment(amendment, self.cceo)
        approve_amendment(amendment, self.hr)
        priority.refresh_from_db()
        self.assertEqual(priority.target_number, 10)


class MyPerformancePageTests(EngineFixture):
    def test_the_page_renders_live_numbers_for_the_owner(self):
        self.client.force_login(self.cceo)
        r = self.client.get("/my-performance")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("Agreed Priorities", body)
        self.assertIn("4", body)  # the real denominator, not a typed one


class NoProfileBranchTests(TestCase):
    """The guard branch must RUN — the third F821 this audit caught lived in
    an untested branch while 1896 tests stayed green."""

    def test_a_user_without_a_staff_profile_is_refused_not_crashed(self):
        admin = _user("pe-noprofile@t.org", EdifyRole.ADMIN.value)
        self.client.force_login(admin)
        r = self.client.get("/my-performance")
        self.assertNotEqual(r.status_code, 500)
