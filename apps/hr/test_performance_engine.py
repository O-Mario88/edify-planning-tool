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


class MilestoneAutoPopulationTests(EngineFixture):
    """§2: each metric priority carries a canonical milestone breakdown,
    derived from the same verified sources as the headline progress — never
    typed, and only where a real source exists."""

    def _milestones(self, review, metric_key):
        from apps.hr.performance_engine import milestone_metrics

        p = review.priorities.get(metric_key=metric_key)
        return {m["label"]: m for m in milestone_metrics(p)}

    def test_visit_milestones_split_core_client_and_completion(self):
        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        # One verified visit at a client school, one at a core school.
        School.objects.filter(id=self.schools[0].id).update(school_type="core")
        for i in (0, 1):
            Activity.objects.create(
                school_id=self.schools[i].id,
                activity_type="school_visit",
                status="ia_verified",
                responsible_staff_id=self.sp.id,
                fy="2026",
                quarter="Q4",
            )
        m = self._milestones(review, "direct_visits")
        self.assertEqual(m["Direct Visits completed"]["value"], 2)
        self.assertEqual(m["Core School Visits"]["value"], 1)
        self.assertEqual(m["Client School Visits"]["value"], 1)
        self.assertEqual(m["Direct Visit target"]["value"], 4)
        self.assertEqual(m["Visit completion"]["value"], 50)  # 2 of 4
        self.assertEqual(m["Direct Visits completed"]["kind"], "auto")

    def test_training_milestones_sum_attendance_from_verified_work(self):
        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        Activity.objects.create(
            school_id=self.schools[0].id,
            activity_type="training",
            status="ia_verified",
            responsible_staff_id=self.sp.id,
            teachers_attended=12,
            leaders_attended=3,
            fy="2026",
            quarter="Q4",
        )
        m = self._milestones(review, "trainings")
        self.assertEqual(m["Trainings completed"]["value"], 1)
        self.assertEqual(m["Teachers trained"]["value"], 12)
        self.assertEqual(m["School leaders trained"]["value"], 3)

    def test_ssa_milestones_show_coverage_and_the_gap(self):
        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        from apps.ssa.models import SsaRecord

        # Two of the four assigned schools have a confirmed current-FY SSA.
        for i in (0, 1):
            SsaRecord.objects.create(
                school_id=self.schools[i].id,
                date_of_ssa=timezone.now(),
                fy="2026",
                quarter="Q2",
                average_score=7.0,
                verification_status="confirmed",
            )
        m = self._milestones(review, "ssa_coverage")
        self.assertEqual(m["Schools allocated for SSA"]["value"], 4)
        self.assertEqual(m["Verified SSA completed"]["value"], 2)
        self.assertEqual(m["SSA coverage"]["value"], 50)
        self.assertEqual(m["Missing SSA"]["value"], 2)

    def test_unverified_ssa_does_not_count_toward_milestones(self):
        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        from apps.ssa.models import SsaRecord

        SsaRecord.objects.create(
            school_id=self.schools[0].id,
            date_of_ssa=timezone.now(),
            fy="2026",
            quarter="Q2",
            average_score=9.9,
            verification_status="pending",
        )
        m = self._milestones(review, "ssa_coverage")
        self.assertEqual(m["Verified SSA completed"]["value"], 0)
        self.assertEqual(m["Missing SSA"]["value"], 4)

    def test_capital_priority_has_no_auto_milestones(self):
        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        from apps.hr.performance_engine import milestone_metrics

        capital = review.priorities.filter(
            strategic_alignment__icontains="Capital"
        ).first()
        self.assertIsNotNone(capital)
        self.assertEqual(
            milestone_metrics(capital),
            [],
            "Capital is a mixed/manual row — it carries no derived milestone "
            "figures the manager could mistake for a measured result",
        )

    def test_a_partner_visit_never_appears_as_a_direct_visit_milestone(self):
        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        Activity.objects.create(
            school_id=self.schools[1].id,
            activity_type="school_visit",
            status="ia_verified",
            delivery_type="partner",
            monitored_by_staff_id=self.sp.id,
            fy="2026",
            quarter="Q4",
        )
        m = self._milestones(review, "direct_visits")
        self.assertEqual(m["Direct Visits completed"]["value"], 0)
        self.assertEqual(m["Partner Visits supervised"]["value"], 1)


class ConversationFormViewTests(EngineFixture):
    """The working conversation (§9, §11, §12): who may write which column,
    and the window gate — proven through the HTTP layer, not just the engine."""

    def setUp(self):
        from apps.accounts.models import StaffSupervisorAssignment
        from apps.hr.performance_engine import activate_window, build_draft_agreement

        self.review = build_draft_agreement(self.sp, self.cycle, self.hr)
        # A real reporting line: manager supervises the CCEO.
        self.manager = _user("pe-mgr@t.org", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        self.manager_sp = StaffProfile.objects.create(
            user=self.manager, country="Uganda"
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.manager_sp, supervisee=self.sp
        )
        # HR opens Q1 — this freezes the snapshots and unlocks the form.
        activate_window(self.cycle, "q1", self.hr)
        self.priority = self.review.priorities.filter(
            metric_key="direct_visits"
        ).first()

    def _client(self, user):
        from django.test import Client

        c = Client()
        c.force_login(user)
        return c

    def test_employee_sees_their_own_conversation_form(self):
        r = self._client(self.cceo).get("/performance-conversation")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Save my reflection", r.content.decode())

    def test_employee_saves_their_reflection_and_self_rating(self):
        self._client(self.cceo).post(
            f"/performance-conversation/priority/{self.priority.id}/save",
            {"channel": "employee", "employee_reflection": "Behind on visits due to floods",
             "employee_rating": "met_some"},
        )
        self.priority.refresh_from_db()
        self.assertEqual(self.priority.employee_reflection, "Behind on visits due to floods")
        self.assertEqual(self.priority.employee_rating, "met_some")

    def test_employee_cannot_write_the_manager_column(self):
        r = self._client(self.cceo).post(
            f"/performance-conversation/priority/{self.priority.id}/save",
            {"channel": "manager", "manager_rating": "exceeds"},
        )
        self.assertEqual(r.status_code, 403)
        self.priority.refresh_from_db()
        self.assertIsNone(self.priority.manager_rating)

    def test_an_invalid_rating_is_refused(self):
        self._client(self.cceo).post(
            f"/performance-conversation/priority/{self.priority.id}/save",
            {"channel": "employee", "employee_rating": "amazing"},
        )
        self.priority.refresh_from_db()
        self.assertIsNone(
            self.priority.employee_rating,
            "only the five named ratings may be stored",
        )

    def test_manager_reviews_a_direct_report(self):
        self._client(self.manager).post(
            f"/performance-conversation/priority/{self.priority.id}/save",
            {
                "channel": "manager",
                "staff": self.sp.id,
                "manager_assessment": "Strong recovery plan",
                "manager_rating": "met",
                "agreed_action": "Two catch-up visits in Q2",
            },
        )
        self.priority.refresh_from_db()
        self.assertEqual(self.priority.manager_rating, "met")
        self.assertEqual(self.priority.agreed_action, "Two catch-up visits in Q2")

    def test_a_stranger_cannot_open_someone_elses_conversation(self):
        outsider = _user("pe-out@t.org", EdifyRole.CCEO.value)
        StaffProfile.objects.create(user=outsider, country="Uganda")
        r = self._client(outsider).get(
            f"/performance-conversation?staff={self.sp.id}", follow=False
        )
        # A page GET with no relationship is bounced to the dashboard, never
        # shown the target's conversation.
        self.assertIn(r.status_code, (302, 403))
        if r.status_code == 200:
            self.fail("a stranger was shown another employee's conversation")

    def test_the_form_is_locked_when_no_window_is_open(self):
        from apps.hr.performance_engine import close_window

        close_window(self.cycle, self.hr)
        r = self._client(self.cceo).get("/performance-conversation")
        self.assertIn("The performance form is locked", r.content.decode())
        # And a write is refused by the engine even if posted directly.
        r2 = self._client(self.cceo).post(
            f"/performance-conversation/priority/{self.priority.id}/save",
            {"channel": "employee", "employee_reflection": "sneaking in"},
        )
        self.assertEqual(r2.status_code, 403)

    def test_a_stranger_cannot_sign_off_someone_elses_conversation(self):
        """sign_off is a permanent lock with no engine relationship check —
        the view must refuse an unrelated user posting an arbitrary review id."""
        outsider = _user("pe-signoff-out@t.org", EdifyRole.CCEO.value)
        StaffProfile.objects.create(user=outsider, country="Kenya")
        r = self._client(outsider).post(
            f"/performance-conversation/{self.review.id}/sign-off",
            {"window": "q1"},
        )
        self.assertEqual(r.status_code, 403)
        self.assertFalse(
            self.review.snapshots.get(window="q1").signed_off_at,
            "an unrelated user must never be able to lock a conversation",
        )

    def test_sign_off_locks_the_conversation_and_hides_the_inputs(self):
        self._client(self.cceo).post(
            f"/performance-conversation/{self.review.id}/sign-off",
            {"window": "q1"},
        )
        snap = self.review.snapshots.get(window="q1")
        self.assertIsNotNone(snap.signed_off_at)
        r = self._client(self.cceo).get("/performance-conversation")
        self.assertNotIn("Save my reflection", r.content.decode())
        self.assertIn("Signed off", r.content.decode())


class HRConsoleTests(EngineFixture):
    """§4/§7: HR is the only role that opens the cycle, activates a window,
    approves an agreement or returns one — proven through the console POST."""

    def setUp(self):
        from django.test import Client

        # The CCEO must be an active employee to be swept into the cycle, and
        # HR needs a country-matched profile to hold them in scope.
        self.sp.onboarding_state = "active"
        self.sp.save(update_fields=["onboarding_state"])
        self.hr_sp = StaffProfile.objects.create(user=self.hr, country="Uganda")
        self.hr_client = Client()
        self.hr_client.force_login(self.hr)

    def test_hr_opens_the_cycle_and_drafts_agreements(self):
        from apps.hr.models import PerformanceCycle, PerformanceReview

        # Start clean: the fixture already made a cycle; use a fresh FY.
        PerformanceCycle.objects.filter(fy="2027").delete()
        self.hr_client.post(
            "/hr/performance-cycle/action",
            {"action": "create_cycle", "fy": "2027"},
        )
        self.assertTrue(PerformanceCycle.objects.filter(fy="2027").exists())
        self.assertTrue(
            PerformanceReview.objects.filter(staff=self.sp, fy="2027").exists(),
            "opening the cycle drafts an agreement for each active employee",
        )

    def test_hr_approval_locks_the_agreement_and_writes_targets(self):
        from apps.hr.performance_engine import build_draft_agreement
        from apps.targets.models import MonthlyPersonalTarget

        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        self.hr_client.post(
            "/hr/performance-cycle/action",
            {"action": "approve", "fy": "2026", "review_id": review.id},
        )
        review.refresh_from_db()
        self.assertEqual(review.stage, "priorities_agreed")
        self.assertTrue(
            MonthlyPersonalTarget.objects.filter(
                user_id=self.cceo.id, fy="2026"
            ).exists(),
            "approval populates My Targets — no separate manual target entry",
        )

    def test_activation_from_the_console_freezes_snapshots(self):
        from apps.hr.models import PerformanceCycle, PerformanceSnapshot
        from apps.hr.performance_engine import build_draft_agreement

        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        self.hr_client.post(
            "/hr/performance-cycle/action",
            {"action": "activate_window", "fy": "2026", "window": "q1"},
        )
        cycle = PerformanceCycle.objects.get(fy="2026")
        self.assertEqual(cycle.active_window, "q1")
        self.assertTrue(
            PerformanceSnapshot.objects.filter(review=review, window="q1").exists()
        )

    def test_returning_an_agreement_requires_a_reason(self):
        from apps.hr.performance_engine import approve_agreement, build_draft_agreement

        review = build_draft_agreement(self.sp, self.cycle, self.hr)
        approve_agreement(review, self.hr)
        # No reason → engine refuses, stage unchanged.
        self.hr_client.post(
            "/hr/performance-cycle/action",
            {"action": "return", "fy": "2026", "review_id": review.id, "reason": ""},
        )
        review.refresh_from_db()
        self.assertEqual(review.stage, "priorities_agreed")

    def test_a_non_hr_user_cannot_drive_the_console(self):
        from django.test import Client

        from apps.hr.models import PerformanceCycle

        c = Client()
        c.force_login(self.cceo)
        r = c.post(
            "/hr/performance-cycle/action",
            {"action": "create_cycle", "fy": "2028"},
        )
        self.assertEqual(r.status_code, 403)
        self.assertFalse(PerformanceCycle.objects.filter(fy="2028").exists())


class ConversationDocumentTests(EngineFixture):
    """§17: the record renders from the LOCKED snapshot, is scope-checked, and
    every open is audit-logged."""

    def setUp(self):
        from django.test import Client

        from apps.hr.performance_engine import (
            activate_window,
            build_draft_agreement,
            sign_off,
        )

        self.review = build_draft_agreement(self.sp, self.cycle, self.hr)
        activate_window(self.cycle, "q1", self.hr)
        sign_off(self.review, "q1", self.hr)
        self.emp = Client()
        self.emp.force_login(self.cceo)

    def test_the_employee_can_open_their_own_locked_record(self):
        r = self.emp.get(
            f"/performance-conversation/{self.review.id}/document/q1"
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("Conversation Record", r.content.decode())
        self.assertIn("FY2026", r.content.decode())

    def test_opening_the_record_writes_an_audit_row(self):
        from apps.audit.models import AuditLog

        before = AuditLog.objects.filter(
            action="hr.performance_document_downloaded"
        ).count()
        self.emp.get(f"/performance-conversation/{self.review.id}/document/q1")
        after = AuditLog.objects.filter(
            action="hr.performance_document_downloaded"
        ).count()
        self.assertEqual(after, before + 1)

    def test_a_stranger_cannot_open_the_record(self):
        from django.test import Client

        outsider = _user("pe-doc-out@t.org", EdifyRole.CCEO.value)
        StaffProfile.objects.create(user=outsider, country="Kenya")
        c = Client()
        c.force_login(outsider)
        r = c.get(
            f"/performance-conversation/{self.review.id}/document/q1", follow=False
        )
        self.assertIn(r.status_code, (302, 403))

    def test_a_window_with_no_snapshot_has_no_document(self):
        r = self.emp.get(
            f"/performance-conversation/{self.review.id}/document/year_end",
            follow=True,
        )
        # Bounced back with an error rather than rendering a fabricated record.
        self.assertNotIn("Conversation Record", r.content.decode())


class CalibrationChainTests(EngineFixture):
    """§14/§20: the overall rating cannot be confirmed before SLT calibration,
    and the record cannot archive before the employee acknowledges it."""

    def setUp(self):
        self.review = build_draft_agreement(self.sp, self.cycle, self.hr)

    def test_a_final_rating_cannot_bypass_calibration(self):
        from apps.hr.performance_engine import confirm_final_rating

        # Straight to a final rating with no calibration → refused.
        with self.assertRaises(Forbidden):
            confirm_final_rating(self.review, "exceeds", self.hr)

    def test_the_full_calibration_chain_in_order(self):
        from apps.hr.performance_engine import (
            acknowledge_review,
            archive_review,
            calibrate,
            confirm_final_rating,
            submit_for_calibration,
        )

        submit_for_calibration(self.review, self.hr)
        self.review.refresh_from_db()
        self.assertEqual(self.review.stage, "ready_for_slt_calibration")

        calibrate(self.review, "confirmed", "SLT agreed", self.hr)
        self.review.refresh_from_db()
        self.assertEqual(self.review.stage, "slt_calibrated")
        self.assertEqual(self.review.calibration_result, "confirmed")

        confirm_final_rating(self.review, "met", self.hr)
        self.review.refresh_from_db()
        self.assertEqual(self.review.stage, "final_rating_confirmed")
        self.assertEqual(self.review.rating, "met")

        # Only the employee acknowledges.
        with self.assertRaises(Forbidden):
            acknowledge_review(self.review, self.hr)
        acknowledge_review(self.review, self.cceo)
        self.review.refresh_from_db()
        self.assertEqual(self.review.stage, "employee_acknowledged")
        self.assertIsNotNone(self.review.acknowledged_at)

        archive_review(self.review, self.hr)
        self.review.refresh_from_db()
        self.assertEqual(self.review.stage, "signed_and_archived")

    def test_calibration_requires_hr_and_the_ready_stage(self):
        from apps.hr.performance_engine import calibrate

        with self.assertRaises(Forbidden):
            calibrate(self.review, "confirmed", "", self.cceo)  # not HR
        with self.assertRaises(BadRequest):
            calibrate(self.review, "confirmed", "", self.hr)  # not ready yet

    def test_archive_requires_acknowledgement_first(self):
        from apps.hr.performance_engine import archive_review

        with self.assertRaises(BadRequest):
            archive_review(self.review, self.hr)


class PipWorkflowTests(EngineFixture):
    """§15/§20: a PIP is a deliberate authorized decision, never automatic."""

    def test_recommend_creates_a_draft_only(self):
        from apps.hr.performance_engine import recommend_pip

        plan = recommend_pip(self.sp, "Two quarters materially behind", self.hr)
        self.assertEqual(plan.plan_type, "formal")
        self.assertEqual(plan.status, "draft")
        self.assertEqual(plan.recommended_by_id, self.hr.id)
        self.assertIsNone(plan.authorized_at, "recommending must not activate")

    def test_recommend_requires_a_reason(self):
        from apps.hr.performance_engine import recommend_pip

        with self.assertRaises(BadRequest):
            recommend_pip(self.sp, "   ", self.hr)

    def test_activation_is_hr_authorized_and_lays_out_30_60_90(self):
        from apps.hr.models import RecoveryMilestone
        from apps.hr.performance_engine import activate_pip, recommend_pip

        plan = recommend_pip(self.sp, "Behind on visits", self.hr)
        with self.assertRaises(Forbidden):
            activate_pip(plan, self.cceo)  # not HR
        activate_pip(plan, self.hr, action_plan="Weekly coaching")
        plan.refresh_from_db()
        self.assertEqual(plan.status, "active")
        self.assertIsNotNone(plan.authorized_at)
        self.assertEqual(plan.authorized_by_id, self.hr.id)
        self.assertEqual(RecoveryMilestone.objects.filter(plan=plan).count(), 3)

    def test_escalation_creates_a_conduct_case(self):
        from apps.hr.models import EmployeeRelationsCase
        from apps.hr.performance_engine import (
            activate_pip,
            pip_outcome,
            recommend_pip,
        )

        plan = recommend_pip(self.sp, "Behind", self.hr)
        activate_pip(plan, self.hr)
        pip_outcome(plan, "escalated", "No improvement after 90 days", self.hr)
        plan.refresh_from_db()
        self.assertEqual(plan.status, "escalated")
        self.assertIsNotNone(plan.escalated_case_id)
        self.assertTrue(
            EmployeeRelationsCase.objects.filter(id=plan.escalated_case_id).exists()
        )


class SeparationWorkflowTests(EngineFixture):
    """§15: separation is a restricted, due-process, separation-of-duties
    workflow — never automatic, and the approver may not be the opener."""

    def test_open_requires_hr_and_a_reason(self):
        from apps.hr.performance_engine import open_separation

        with self.assertRaises(Forbidden):
            open_separation(self.sp, {"reason": "x"}, self.cceo)  # not HR
        with self.assertRaises(BadRequest):
            open_separation(self.sp, {"reason": "  "}, self.hr)

    def test_full_due_process_and_separation_of_duties(self):
        from apps.core.rbac import EdifyRole
        from apps.hr.models import SeparationConversation
        from apps.hr.performance_engine import (
            approve_separation,
            hr_review_separation,
            open_separation,
            record_separation_response,
        )

        sep = open_separation(
            self.sp, {"reason": "Gross misconduct — documented"}, self.hr
        )
        self.assertEqual(sep.stage, "awaiting_employee_response")

        # Only the subject employee may respond.
        with self.assertRaises(Forbidden):
            record_separation_response(sep, "not me", self.hr)
        record_separation_response(sep, "My account of events", self.cceo)
        sep.refresh_from_db()
        self.assertEqual(sep.stage, "hr_review")

        hr_review_separation(sep, "Reviewed; policy basis holds", self.hr)
        sep.refresh_from_db()
        self.assertEqual(sep.stage, "awaiting_leadership_approval")

        # The person who OPENED it may not approve it, even as leadership.
        cd = _user("pe-cd@t.org", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=cd, country="Uganda")
        # HR opened it, so HR-as-approver is blocked by role anyway; prove the
        # opener rule by making the opener a CD.
        sep2 = SeparationConversation.objects.create(
            subject_staff=self.sp,
            reason="x",
            opened_by=cd,
            stage="awaiting_leadership_approval",
        )
        with self.assertRaises(Forbidden):
            approve_separation(sep2, cd)  # opener cannot approve

        approve_separation(sep, cd)  # a different authorized leader may
        sep.refresh_from_db()
        self.assertEqual(sep.stage, "approved")
        self.assertEqual(sep.approved_by_id, cd.id)

    def test_a_cceo_cannot_approve_a_separation(self):
        from apps.hr.performance_engine import approve_separation, open_separation

        sep = open_separation(self.sp, {"reason": "x"}, self.hr)
        sep.stage = "awaiting_leadership_approval"
        sep.save(update_fields=["stage"])
        with self.assertRaises(Forbidden):
            approve_separation(sep, self.cceo)


class DocxAndAcknowledgeViewTests(EngineFixture):
    def setUp(self):
        from django.test import Client

        from apps.hr.performance_engine import (
            activate_window,
            build_draft_agreement,
            sign_off,
        )

        self.review = build_draft_agreement(self.sp, self.cycle, self.hr)
        activate_window(self.cycle, "year_end", self.hr)
        sign_off(self.review, "year_end", self.hr)
        self.emp = Client()
        self.emp.force_login(self.cceo)

    def test_docx_download_serves_a_word_document(self):
        r = self.emp.get(
            f"/performance-conversation/{self.review.id}/document/year_end?format=docx"
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/msword")
        self.assertIn("attachment", r["Content-Disposition"])

    def test_employee_acknowledges_a_confirmed_final_rating(self):
        from apps.hr.performance_engine import (
            calibrate,
            confirm_final_rating,
            submit_for_calibration,
        )

        submit_for_calibration(self.review, self.hr)
        calibrate(self.review, "confirmed", "", self.hr)
        confirm_final_rating(self.review, "met", self.hr)
        self.emp.post(
            f"/performance-conversation/{self.review.id}/acknowledge"
        )
        self.review.refresh_from_db()
        self.assertEqual(self.review.stage, "employee_acknowledged")
