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


class ConversationWindowTests(EngineFixture):
    """§7/§8/§10 — locked outside a window; snapshots freeze the numbers."""

    def _agree(self):
        return build_draft_agreement(self.sp, self.cycle, self.hr)

    def test_the_form_is_locked_outside_a_window(self):
        from apps.hr.performance_engine import save_employee_input

        review = self._agree()
        with self.assertRaises(Forbidden):
            save_employee_input(
                review.priorities.first(), {"employee_rating": "met"}, self.cceo
            )

    def test_only_hr_activates_and_activation_freezes_the_numbers(self):
        from apps.hr.performance_engine import activate_window, live_progress

        review = self._agree()
        with self.assertRaises(Forbidden):
            activate_window(self.cycle, "q1", self.cceo)
        activate_window(self.cycle, "q1", self.hr)

        snap = review.snapshots.get(window="q1")
        visits_row = next(
            r for r in snap.data["priorities"] if r["metric_key"] == "direct_visits"
        )
        self.assertEqual(visits_row["actual"], 0)

        # Verified work AFTER activation moves the live number but NEVER the
        # snapshot the conversation is held against.
        Activity.objects.create(
            school_id=self.schools[0].id,
            activity_type="school_visit",
            status="ia_verified",
            responsible_staff_id=self.sp.id,
            fy="2026",
            quarter="Q1",
        )
        visits = review.priorities.get(metric_key="direct_visits")
        self.assertEqual(live_progress(visits)["actual"], 1)
        snap.refresh_from_db()
        frozen = next(
            r for r in snap.data["priorities"] if r["metric_key"] == "direct_visits"
        )
        self.assertEqual(frozen["actual"], 0, "a snapshot must never move")

    def test_rating_columns_stay_separate_and_scoped(self):
        from apps.accounts.models import StaffSupervisorAssignment
        from apps.hr.performance_engine import (
            activate_window,
            save_employee_input,
            save_manager_input,
        )

        review = self._agree()
        activate_window(self.cycle, "q1", self.hr)
        priority = review.priorities.first()

        # The employee cannot write the manager's column…
        with self.assertRaises(Forbidden):
            save_manager_input(priority, {"manager_rating": "exceeds"}, self.cceo)
        # …and an unrelated PL cannot either.
        stranger = _user("pe-stranger@t.org", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        StaffProfile.objects.create(user=stranger, country="Uganda")
        with self.assertRaises(Forbidden):
            save_manager_input(priority, {"manager_rating": "exceeds"}, stranger)

        save_employee_input(
            priority,
            {"employee_rating": "met", "employee_reflection": "…"},
            self.cceo,
        )
        pl = _user("pe-pl@t.org", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        sp_pl = StaffProfile.objects.create(user=pl, country="Uganda")
        StaffSupervisorAssignment.objects.create(supervisee=self.sp, supervisor=sp_pl)
        save_manager_input(priority, {"manager_rating": "exceeds"}, pl)
        priority.refresh_from_db()
        self.assertEqual(priority.employee_rating, "met")
        self.assertEqual(priority.manager_rating, "exceeds")
        self.assertIsNone(priority.functional_manager_rating)


class FormTaxonomyTests(EngineFixture):
    def test_the_six_values_and_spiritual_row_are_seeded_manual(self):
        from apps.hr.performance_engine import EDIFY_VALUES

        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        names = set(
            review.value_commitments.filter(kind="value").values_list(
                "value_name", flat=True
            )
        )
        self.assertEqual(names, set(EDIFY_VALUES))
        self.assertTrue(review.value_commitments.filter(kind="spiritual").exists())

    def test_capital_is_mixed_no_metric(self):
        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        capital = review.priorities.get(strategic_alignment="Program Quality — Capital")
        self.assertIsNone(capital.metric_key)

    def test_functional_manager_is_a_separate_configured_voice(self):
        from apps.hr.performance_engine import (
            activate_window,
            save_functional_manager_input,
        )

        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        activate_window(self.cycle, "q1", self.hr)
        fm = _user("pe-fm@t.org", EdifyRole.COUNTRY_DIRECTOR.value)
        priority = review.priorities.first()
        with self.assertRaises(Forbidden):
            save_functional_manager_input(
                priority, {"functional_manager_rating": "met"}, fm
            )
        review.functional_manager = fm
        review.save(update_fields=["functional_manager"])
        save_functional_manager_input(
            priority, {"functional_manager_rating": "met"}, fm
        )
        priority.refresh_from_db()
        self.assertEqual(priority.functional_manager_rating, "met")

    def test_support_flag_creates_informal_recovery_never_pip(self):
        from apps.hr.models import RecoveryPlanType
        from apps.hr.performance_engine import flag_performance_support

        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        plan = flag_performance_support(review, "Two checkpoints behind", self.hr)
        self.assertEqual(plan.plan_type, RecoveryPlanType.INFORMAL)
        self.assertEqual(plan.status, "draft")
