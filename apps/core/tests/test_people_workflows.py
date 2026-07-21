"""The three workflows that were registers over empty tables.

Recruitment had no writer and, critically, no path at all from an accepted
candidate to an account — HR re-keyed the person by hand. Performance was one
flat row with no priorities, so the outcomes agreed in January were
unrecoverable in December. And an employee-relations case could not record
whom it concerned, which is why the register was unscopeable.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSupervisorAssignment,
    User,
    UserInvitation,
)
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import EdifyRole
from apps.hr import (
    employee_relations_service as er,
    onboarding_service as onb,
    performance_service as perf,
    recruitment_service as rec,
)
from apps.hr.models import ApplicationStage, VacancyStatus


def _user(email, name, role, country="Uganda", with_profile=True):
    u = User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
        status="active",
    )
    if with_profile:
        StaffProfile.objects.create(user=u, country=country)
    return u


class RecruitmentChainTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hr = _user("rc-hr@t.org", "HR One", "HumanResources")
        cls.cd = _user("rc-cd@t.org", "CD One", EdifyRole.COUNTRY_DIRECTOR.value)
        cls.foreign_hr = _user("rc-khr@t.org", "Kenya HR", "HumanResources", "Kenya")

    def _open_vacancy(self):
        v = rec.request_vacancy(
            {"country": "Uganda", "role": EdifyRole.CCEO.value, "department": "Field"},
            self.hr,
        )
        return rec.approve_vacancy(v.id, self.cd, reason="Budgeted")

    def test_a_vacancy_needs_leadership_approval(self):
        v = rec.request_vacancy(
            {"country": "Uganda", "role": EdifyRole.CCEO.value}, self.hr
        )
        self.assertEqual(v.status, VacancyStatus.PENDING_APPROVAL)
        with self.assertRaises(Forbidden):
            rec.approve_vacancy(v.id, self.hr)  # HR requested it

    def test_hr_cannot_recruit_for_another_country(self):
        with self.assertRaises(Forbidden):
            rec.request_vacancy(
                {"country": "Kenya", "role": EdifyRole.CCEO.value}, self.hr
            )

    def test_the_pipeline_cannot_skip_stages(self):
        vacancy = self._open_vacancy()
        app = rec.record_application(
            {"vacancy_id": vacancy.id, "name": "Asha", "email": "asha@x.org"}, self.hr
        )
        with self.assertRaises(BadRequest):
            rec.advance_application(app.id, self.hr, to_stage=ApplicationStage.OFFER)

    def test_a_rejection_requires_a_reason(self):
        vacancy = self._open_vacancy()
        app = rec.record_application(
            {"vacancy_id": vacancy.id, "name": "Bea", "email": "bea@x.org"}, self.hr
        )
        with self.assertRaises(BadRequest):
            rec.advance_application(
                app.id, self.hr, to_stage=ApplicationStage.REJECTED
            )

    def _to_accepted(self, vacancy, email="cara@x.org"):
        app = rec.record_application(
            {"vacancy_id": vacancy.id, "name": "Cara", "email": email}, self.hr
        )
        for stage, reason in [
            (ApplicationStage.SCREENING, ""),
            (ApplicationStage.INTERVIEW, ""),
            (ApplicationStage.REFERENCE_CHECK, ""),
            (ApplicationStage.OFFER, "Strongest candidate"),
            (ApplicationStage.ACCEPTED, ""),
        ]:
            app = rec.advance_application(
                app.id, self.hr, to_stage=stage, reason=reason
            )
        return app

    def test_hiring_provisions_the_account_and_opens_onboarding(self):
        """The handoff that did not exist in any form."""
        vacancy = self._open_vacancy()
        app = self._to_accepted(vacancy)

        result = rec.hire(app.id, self.hr, provisioning={})

        app.refresh_from_db()
        self.assertEqual(app.stage, ApplicationStage.HIRED)
        self.assertIsNotNone(
            app.provisioned_user_id,
            "an account must be reconcilable back to the hire that created it",
        )
        user = User.objects.get(id=result["userId"])
        self.assertEqual(user.email, "cara@x.org")
        self.assertEqual(user.status, "pending_invited")
        self.assertTrue(UserInvitation.objects.filter(user=user).exists())
        self.assertIsNotNone(result["onboardingPlanId"])
        self.assertTrue(AuditLog.objects.filter(action="hr.candidate_hired").exists())

    def test_a_candidate_cannot_be_provisioned_twice(self):
        vacancy = self._open_vacancy()
        app = self._to_accepted(vacancy, email="dee@x.org")
        rec.hire(app.id, self.hr, provisioning={})
        with self.assertRaises(BadRequest):
            rec.hire(app.id, self.hr, provisioning={})

    def test_only_an_accepted_offer_can_be_provisioned(self):
        vacancy = self._open_vacancy()
        app = rec.record_application(
            {"vacancy_id": vacancy.id, "name": "Eve", "email": "eve@x.org"}, self.hr
        )
        with self.assertRaises(BadRequest):
            rec.hire(app.id, self.hr, provisioning={})


class OnboardingAndProbationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hr = _user("ob-hr@t.org", "HR Two", "HumanResources")
        cls.newbie = _user("ob-new@t.org", "New Person", EdifyRole.CCEO.value)
        cls.sp = cls.newbie.staff_profile

    def test_a_plan_has_dated_tasks_so_overdue_can_exist(self):
        plan = onb.open_onboarding(self.sp, self.hr)
        self.assertTrue(plan.tasks.exists())
        self.assertTrue(all(t.due_date for t in plan.tasks.all()))
        self.assertIsNotNone(plan.target_completion_date)

    def test_overdue_is_detectable(self):
        plan = onb.open_onboarding(
            self.sp, self.hr, start_date=date.today() - timedelta(days=200)
        )
        self.assertTrue(plan.is_overdue)
        self.assertEqual(onb.overdue_onboarding().count(), 1)
        self.assertGreater(onb.overdue_tasks().count(), 0)

    def test_closing_onboarding_activates_the_profile(self):
        """The writer `onboarding_state` never had — and the reason nobody on
        a live deployment could be nominated to cover leave."""
        plan = onb.open_onboarding(self.sp, self.hr)
        self.assertEqual(self.sp.onboarding_state, "pending")
        onb.close_onboarding(plan.id, self.hr, force=True)
        self.sp.refresh_from_db()
        self.assertEqual(self.sp.onboarding_state, "active")

    def test_closing_refuses_while_tasks_are_open(self):
        plan = onb.open_onboarding(self.sp, self.hr)
        with self.assertRaises(BadRequest):
            onb.close_onboarding(plan.id, self.hr)

    def test_closing_opens_probation(self):
        from apps.hr.models import ReviewType

        plan = onb.open_onboarding(self.sp, self.hr)
        onb.close_onboarding(plan.id, self.hr, force=True)
        self.assertTrue(
            self.sp.performance_reviews.filter(
                review_type=ReviewType.PROBATION
            ).exists(),
            "probation had no representation in the schema at all",
        )

    def test_a_probation_decision_needs_a_reason_and_is_audited(self):
        from apps.hr.models import ProbationDecision

        plan = onb.open_onboarding(self.sp, self.hr)
        onb.close_onboarding(plan.id, self.hr, force=True)
        review = self.sp.performance_reviews.first()
        with self.assertRaises(BadRequest):
            onb.decide_probation(
                review.id, self.hr, decision=ProbationDecision.CONFIRMED, reason=" "
            )
        onb.decide_probation(
            review.id, self.hr, decision=ProbationDecision.CONFIRMED, reason="Strong"
        )
        self.assertTrue(
            AuditLog.objects.filter(action="hr.probation_confirmed").exists()
        )


class PerformanceWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hr = _user("pf-hr@t.org", "HR Three", "HumanResources")
        cls.manager = _user(
            "pf-pl@t.org", "Lead", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        cls.employee = _user("pf-cceo@t.org", "Worker", EdifyRole.CCEO.value)
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.employee.staff_profile,
            supervisor=cls.manager.staff_profile,
        )

    def _cycle(self):
        return perf.open_cycle(
            self.employee.staff_profile,
            self.hr,
            fy="2026",
            due_date=date.today() + timedelta(days=180),
        )

    def _priorities(self, n=5):
        return [
            {
                "outcome_statement": f"Outcome {i}",
                "measures_of_success": "A measure",
                "baseline": "0",
                "target": "10",
                "weight": 20,
                "milestones": [{"description": f"Milestone {i}"}],
            }
            for i in range(1, n + 1)
        ]

    def test_priorities_are_first_class_rows_with_milestones(self):
        review = self._cycle()
        perf.set_priorities(review.id, self.employee, self._priorities())
        review.refresh_from_db()
        self.assertEqual(review.priorities.count(), 5)
        self.assertEqual(review.priorities.first().milestones.count(), 1)

    def test_weights_must_total_one_hundred(self):
        review = self._cycle()
        bad = self._priorities(3)  # 3 x 20 = 60
        with self.assertRaises(BadRequest):
            perf.set_priorities(review.id, self.employee, bad)

    def test_the_employee_cannot_agree_their_own_priorities(self):
        review = self._cycle()
        perf.set_priorities(review.id, self.employee, self._priorities())
        with self.assertRaises(Forbidden):
            perf.agree_priorities(review.id, self.employee)
        perf.agree_priorities(review.id, self.manager)

    def test_the_employee_cannot_assess_or_calibrate_themselves(self):
        review = self._cycle()
        perf.set_priorities(review.id, self.employee, self._priorities())
        perf.agree_priorities(review.id, self.manager)
        perf.submit_reflection(review.id, self.employee, reflection="My year")
        with self.assertRaises(Forbidden):
            perf.submit_assessment(review.id, self.employee, assessment="Great")
        perf.submit_assessment(review.id, self.manager, assessment="Solid", rating="Strong")
        with self.assertRaises(Forbidden):
            perf.calibrate(review.id, self.employee, result="Strong")

    def test_only_the_employee_writes_their_own_reflection(self):
        review = self._cycle()
        perf.set_priorities(review.id, self.employee, self._priorities())
        perf.agree_priorities(review.id, self.manager)
        with self.assertRaises(Forbidden):
            perf.submit_reflection(review.id, self.manager, reflection="On their behalf")

    def test_the_four_channels_stay_separate(self):
        review = self._cycle()
        perf.set_priorities(review.id, self.employee, self._priorities())
        perf.agree_priorities(review.id, self.manager)
        perf.submit_reflection(review.id, self.employee, reflection="Employee words")
        perf.submit_assessment(
            review.id, self.manager, assessment="Manager words", rating="Strong"
        )
        perf.calibrate(review.id, self.hr, result="Strong", note="Cohort note")
        review.refresh_from_db()
        self.assertEqual(review.employee_reflection, "Employee words")
        self.assertEqual(review.manager_feedback, "Manager words")
        self.assertEqual(review.calibration_note, "Cohort note")
        # System evidence is computed, never typed.
        perf.refresh_system_evidence(review.id, self.hr)
        review.refresh_from_db()
        self.assertIsNotNone(review.system_evidence)
        self.assertIn("source", review.system_evidence)

    def test_only_the_employee_acknowledges_and_it_closes_the_cycle(self):
        from apps.hr.models import ReviewStage

        review = self._cycle()
        perf.set_priorities(review.id, self.employee, self._priorities())
        perf.agree_priorities(review.id, self.manager)
        perf.submit_reflection(review.id, self.employee, reflection="r")
        perf.submit_assessment(review.id, self.manager, assessment="a")
        perf.calibrate(review.id, self.hr, result="Strong")
        with self.assertRaises(Forbidden):
            perf.acknowledge(review.id, self.manager)
        perf.acknowledge(review.id, self.employee)
        review.refresh_from_db()
        self.assertEqual(review.stage, ReviewStage.CLOSED)

    def test_an_employee_can_see_their_own_review(self):
        review = self._cycle()
        self.assertTrue(
            perf.visible_reviews(self.employee).filter(id=review.id).exists(),
            "the role being reviewed could not open the page at all",
        )

    def test_an_unrelated_employee_cannot(self):
        other = _user("pf-other@t.org", "Other", EdifyRole.CCEO.value)
        review = self._cycle()
        self.assertFalse(perf.visible_reviews(other).filter(id=review.id).exists())


class EmployeeRelationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hr = _user("er-hr@t.org", "HR Four", "HumanResources")
        cls.other_hr = _user("er-hr2@t.org", "HR Five", "HumanResources")
        cls.kenya_hr = _user("er-khr@t.org", "Kenya HR", "HumanResources", "Kenya")
        cls.subject = _user("er-subj@t.org", "Subject", EdifyRole.CCEO.value)

    def _case(self, principal=None, confidential=True):
        return er.open_case(
            {
                "subject_staff_id": self.subject.staff_profile.id,
                "case_type": "conduct",
                "description": "A concern was raised.",
                "is_confidential": confidential,
            },
            principal or self.hr,
        )

    def test_a_case_records_whom_it_concerns(self):
        case = self._case()
        self.assertEqual(case.subject_staff_id, self.subject.staff_profile.id)
        self.assertEqual(case.country, "Uganda")

    def test_another_country_cannot_see_it(self):
        self._case()
        self.assertEqual(er.visible_cases(self.kenya_hr).count(), 0)

    def test_a_confidential_case_is_invisible_to_other_hr(self):
        self._case(confidential=True)
        self.assertEqual(
            er.visible_cases(self.other_hr).count(),
            0,
            "case EXISTENCE is itself restricted, so this filters rows",
        )

    def test_a_non_confidential_case_is_visible_in_country(self):
        self._case(confidential=False)
        self.assertEqual(er.visible_cases(self.other_hr).count(), 1)

    def test_reading_a_case_is_audited(self):
        case = self._case()
        er.get_case(case.id, self.hr)
        self.assertTrue(AuditLog.objects.filter(action="hr.er_accessed").exists())

    def test_the_subject_cannot_act_on_their_own_case(self):
        from apps.hr.models import ERCaseStatus

        subject_hr = _user("er-selfhr@t.org", "Self HR", "HumanResources")
        case = er.open_case(
            {
                "subject_staff_id": subject_hr.staff_profile.id,
                "case_type": "conduct",
                "description": "d",
                "is_confidential": False,
            },
            self.hr,
        )
        with self.assertRaises(Forbidden):
            er.advance_case(case.id, subject_hr, to_status=ERCaseStatus.TRIAGE)

    def test_the_case_workflow_cannot_skip_stages(self):
        from apps.hr.models import ERCaseStatus

        case = self._case()
        with self.assertRaises(BadRequest):
            er.advance_case(case.id, self.hr, to_status=ERCaseStatus.RESOLVED)

    def test_escalation_creates_a_case_rather_than_flipping_a_status(self):
        from apps.hr.models import (
            PerformanceImprovementPlan,
            RecoveryPlanType,
            RecoveryStatus,
        )

        plan = PerformanceImprovementPlan.objects.create(
            staff=self.subject.staff_profile,
            plan_type=RecoveryPlanType.FORMAL,
            status=RecoveryStatus.ACTIVE,
            cause="conduct",
            action_plan="Support plan",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=60),
        )
        case = er.escalate_recovery_plan(plan.id, self.hr, reason="Repeated conduct")
        plan.refresh_from_db()
        self.assertEqual(plan.escalated_case_id, case.id)
        self.assertEqual(plan.status, RecoveryStatus.ESCALATED)
        self.assertEqual(case.subject_staff_id, self.subject.staff_profile.id)

    def test_an_informal_plan_cannot_escalate_to_conduct(self):
        from apps.hr.models import (
            PerformanceImprovementPlan,
            RecoveryPlanType,
            RecoveryStatus,
        )

        plan = PerformanceImprovementPlan.objects.create(
            staff=self.subject.staff_profile,
            plan_type=RecoveryPlanType.INFORMAL,
            status=RecoveryStatus.ACTIVE,
            cause="capacity",
            action_plan="Support",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=30),
        )
        with self.assertRaises(BadRequest):
            er.escalate_recovery_plan(plan.id, self.hr, reason="x")

    def test_cause_includes_the_non_blaming_categories(self):
        from apps.hr.models import RecoveryCause

        for expected in ("capacity", "workload", "availability", "data_quality",
                         "manager_support"):
            self.assertIn(
                expected,
                RecoveryCause.values,
                "the old taxonomy listed only causes that attach blame",
            )
