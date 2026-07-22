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


class TargetsSyncTests(EngineFixture):
    """§5/§17 — approval populates My Targets; no second target system."""

    def test_approval_writes_monthly_personal_targets(self):
        from apps.hr.performance_engine import approve_agreement
        from apps.targets.models import MonthlyPersonalTarget, TargetArea

        for key, label, weight in [
            ("school_visits", "School Visits", 30),
            ("ssa_completed", "SSA Completed", 25),
            ("cluster_trainings", "Cluster Trainings", 20),
        ]:
            TargetArea.objects.get_or_create(
                key=key, defaults={"label": label, "weight": weight}
            )
        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        written = approve_agreement(review, self.hr)
        self.assertGreater(written, 0)

        rows = MonthlyPersonalTarget.objects.filter(user_id=self.cceo.id, fy="2026")
        # 12 months per mapped area — the canonical My Targets rows, not a
        # parallel store.
        self.assertEqual(rows.filter(area__key="school_visits").count(), 12)
        annual = sum(r.target for r in rows.filter(area__key="school_visits"))
        self.assertAlmostEqual(annual, 4, delta=1)  # 4 assigned schools

    def test_sync_is_idempotent(self):
        from apps.hr.performance_engine import (
            approve_agreement,
            sync_targets_from_agreement,
        )
        from apps.targets.models import MonthlyPersonalTarget, TargetArea

        TargetArea.objects.get_or_create(
            key="school_visits", defaults={"label": "School Visits", "weight": 30}
        )
        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        approve_agreement(review, self.hr)
        before = MonthlyPersonalTarget.objects.count()
        sync_targets_from_agreement(review, self.hr)
        self.assertEqual(MonthlyPersonalTarget.objects.count(), before)

    def test_only_hr_approves(self):
        from apps.hr.performance_engine import approve_agreement

        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        with self.assertRaises(Forbidden):
            approve_agreement(review, self.cceo)


class PhasedSplitTests(TestCase):
    """A small annual target must not vanish into per-month rounding."""

    def test_the_split_always_sums_to_the_annual_target(self):
        from apps.hr.performance_engine import _phased_split

        for annual in (1, 3, 4, 12, 25, 80, 560):
            months = _phased_split(annual)
            self.assertEqual(len(months), 12)
            self.assertEqual(sum(months), annual, f"{annual} lost units in phasing")

    def test_phasing_is_seasonal_not_flat(self):
        from apps.hr.performance_engine import _phased_split

        months = _phased_split(120)
        q1, q2 = sum(months[0:3]), sum(months[3:6])
        self.assertLess(q1, q2, "Q1 is a 20% quarter, Q2 a 30% one")


class ReopenAndDocumentTests(EngineFixture):
    """§7/§10/§14 — reopen never rewrites history; documents come from the
    locked snapshot."""

    def _signed(self):
        from apps.hr.performance_engine import activate_window, sign_off

        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        activate_window(self.cycle, "q1", self.hr)
        sign_off(review, "q1", self.hr)
        return review

    def test_reopen_requires_a_reason_and_hr(self):
        from apps.hr.performance_engine import reopen_conversation

        review = self._signed()
        with self.assertRaises(Forbidden):
            reopen_conversation(review, "q1", "x", self.cceo)
        with self.assertRaises(BadRequest):
            reopen_conversation(review, "q1", "  ", self.hr)

    def test_reopening_unlocks_but_never_regenerates_the_snapshot(self):
        from apps.hr.performance_engine import reopen_conversation

        review = self._signed()
        snap = review.snapshots.get(window="q1")
        original = snap.data
        taken = snap.taken_at
        # Work lands AFTER sign-off; reopening must not absorb it.
        Activity.objects.create(
            school_id=self.schools[0].id,
            activity_type="school_visit",
            status="ia_verified",
            responsible_staff_id=self.sp.id,
            fy="2026",
            quarter="Q1",
        )
        reopen_conversation(review, "q1", "Manager comment was wrong", self.hr)
        snap.refresh_from_db()
        self.assertIsNone(snap.signed_off_at)
        self.assertEqual(snap.data, original, "history must not be rewritten")
        self.assertEqual(snap.taken_at, taken)

    def test_the_document_is_built_from_the_snapshot(self):
        from apps.hr.performance_engine import conversation_document

        review = self._signed()
        doc = conversation_document(review, "q1", self.hr)
        self.assertEqual(
            doc["priorities"], review.snapshots.get(window="q1").data["priorities"]
        )
        self.assertEqual(len(doc["values"]), 6)
        self.assertTrue(doc["spiritual"])
        self.assertIsNotNone(doc["signed_off_at"])

    def test_return_for_correction_requires_a_reason(self):
        from apps.hr.performance_engine import return_for_correction

        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        with self.assertRaises(BadRequest):
            return_for_correction(review, "", self.hr)
        return_for_correction(review, "Ratings incomplete", self.hr)
        review.refresh_from_db()
        self.assertEqual(review.stage, "manager_assessment")
