"""Journey 13 — PIP, walked end to end.

Journey 13 of the mandate's twenty-two: Concern, Verified context, Manager
proposal, HR fairness review, Employee discussion, Check-ins, Support,
Outcome, Appeal.

This is the only journey whose subject is a person's employment rather than a
school's programme, and its steps are almost entirely **due-process controls**
rather than workflow. A PIP that can be started on nobody's authority, on no
recorded reason, or by the same person who raised the concern, is not a
slightly-wrong feature — it is an unfair process with consequences for
someone's job.

Coverage here was one test, and it was about the informal path
(`test_support_flag_creates_informal_recovery_never_pip`). The formal chain —
recommend, activate, outcome, escalate — had none, in a workflow where the
controls are the entire point.

Three of those controls are worth naming because each is a separation the
platform states explicitly:

- **Never automatic** (§15, §20). No score reaches `recommend_pip` on its own.
  A person's numbers being poor is not, by itself, a formal process.
- **A recommendation records its reason.** That is the "verified context"
  step: the manager must say what this is founded on, and it is stored on the
  plan as `cause_evidence`.
- **The proposer does not authorise.** A manager recommends and creates a
  *draft*; only HR activates. That is the same separation-of-duties principle
  that keeps IA verification apart from payment authority.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import EdifyRole
from apps.hr.models import PerformanceImprovementPlan, RecoveryPlanType
from apps.hr.performance_engine import activate_pip, pip_outcome, recommend_pip

REASON = (
    "Three consecutive quarters below the agreed school-visit commitment, "
    "discussed at the Q2 and Q3 conversations."
)


def _person(uid, email, name, role):
    user = User.objects.create(
        id=uid, email=email, name=name, roles=[role], active_role=role, is_active=True
    )
    profile = StaffProfile.objects.create(
        user=user, staff_number=uid.upper(), country="Uganda", title=role
    )
    return user, profile


class PipJourneyTest(TestCase):
    """Concern → proposal → HR authorises → outcome → escalation."""

    @classmethod
    def setUpTestData(cls):
        cls.employee, cls.employee_sp = _person(
            "pip-emp", "pip-emp@edify.org", "PIP Employee", EdifyRole.CCEO.value
        )
        cls.manager, cls.manager_sp = _person(
            "pip-mgr",
            "pip-mgr@edify.org",
            "PIP Manager",
            EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        )
        cls.hr, _ = _person(
            "pip-hr", "pip-hr@edify.org", "PIP HR", EdifyRole.HUMAN_RESOURCES.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.manager_sp, supervisee=cls.employee_sp
        )

    def test_a_manager_proposes_and_only_hr_authorises(self):
        # ── 1-3. Concern, verified context, manager proposal ──────────────
        plan = recommend_pip(self.employee_sp, REASON, self.manager)
        self.assertEqual(
            plan.status,
            "draft",
            "a manager's recommendation created something already in force — "
            "recommending and authorising must be two decisions",
        )
        self.assertEqual(plan.plan_type, RecoveryPlanType.FORMAL)
        self.assertEqual(
            plan.cause_evidence,
            REASON,
            "the recommendation did not keep what it was founded on, so the "
            "employee cannot see the case against them",
        )
        self.assertEqual(plan.recommended_by_id, self.manager.id)

        # ── 4. HR fairness review — the proposer cannot authorise ─────────
        # The separation that makes this a review rather than a formality.
        with self.assertRaises(Forbidden):
            activate_pip(plan, self.manager, action_plan="Weekly coaching.")
        plan.refresh_from_db()
        self.assertEqual(
            plan.status,
            "draft",
            "the manager who proposed the PIP activated it themselves",
        )

        activate_pip(plan, self.hr, action_plan="Weekly coaching and a co-visit.")
        plan.refresh_from_db()
        self.assertEqual(plan.status, "active")
        self.assertEqual(plan.authorized_by_id, self.hr.id)
        self.assertIsNotNone(
            plan.authorized_at,
            "an active PIP records no moment of authorisation",
        )
        self.assertNotEqual(
            plan.authorized_by_id,
            plan.recommended_by_id,
            "the same person recommended and authorised the plan",
        )

        # ── 5-7. Check-ins and support, laid out at activation ────────────
        self.assertTrue(
            plan.milestones.exists(),
            "an active PIP has no milestones, so there is nothing for the "
            "employee to be measured against or supported towards",
        )

        # ── 8. Outcome — an HR decision, never a score ────────────────────
        with self.assertRaises(Forbidden):
            pip_outcome(plan, "completed", "Improved.", self.manager)
        pip_outcome(plan, "completed", "Sustained improvement.", self.hr)
        plan.refresh_from_db()
        self.assertEqual(plan.status, "completed")
        self.assertEqual(plan.outcome, "completed")
        self.assertIsNotNone(plan.closed_at)

    def test_a_recommendation_without_a_recorded_reason_is_refused(self):
        """Verified context. A PIP founded on nothing is founded on nobody."""
        with self.assertRaises(BadRequest):
            recommend_pip(self.employee_sp, "   ", self.manager)
        self.assertFalse(
            PerformanceImprovementPlan.objects.filter(staff=self.employee_sp).exists(),
            "a PIP was created despite its reason being refused",
        )

    def test_an_active_pip_cannot_be_activated_again(self):
        """No second authorisation of a plan already in force."""
        plan = recommend_pip(self.employee_sp, REASON, self.manager)
        activate_pip(plan, self.hr, action_plan="Weekly coaching.")
        plan.refresh_from_db()
        first_authorised_at = plan.authorized_at

        with self.assertRaises(BadRequest):
            activate_pip(plan, self.hr, action_plan="Different plan entirely.")
        plan.refresh_from_db()
        self.assertEqual(
            plan.authorized_at,
            first_authorised_at,
            "re-activating rewrote when the PIP was authorised",
        )

    def test_escalation_creates_a_case_somebody_can_actually_see(self):
        """9. Appeal — escalation must leave a case with an owner.

        A confidential case is visible only to its owner or investigator, so
        one created with neither vanishes the moment it is raised — invisible
        even to the HR officer who escalated it. That was a live defect in the
        2026-08-20 HR audit; this holds the fix.
        """
        plan = recommend_pip(self.employee_sp, REASON, self.manager)
        activate_pip(plan, self.hr, action_plan="Weekly coaching.")
        pip_outcome(
            plan, "escalated", "No improvement across the plan period.", self.hr
        )
        plan.refresh_from_db()

        self.assertEqual(plan.status, "escalated")
        case = plan.escalated_case
        self.assertIsNotNone(case, "escalating the PIP created no case")
        self.assertEqual(case.subject_staff_id, self.employee_sp.id)
        self.assertEqual(
            case.case_owner_id,
            self.hr.id,
            "the escalated case has no owner, so a confidential case is "
            "invisible to everyone including the person who raised it",
        )
        self.assertEqual(case.raised_by_id, self.hr.id)
        self.assertTrue(
            (case.description or "").strip(),
            "the case carries no description of why it was escalated",
        )

    def test_an_unknown_outcome_is_refused(self):
        """The outcome vocabulary is closed: complete, extend, escalate."""
        plan = recommend_pip(self.employee_sp, REASON, self.manager)
        activate_pip(plan, self.hr, action_plan="Weekly coaching.")
        with self.assertRaises(BadRequest):
            pip_outcome(plan, "dismissed", "Ended it.", self.hr)
        plan.refresh_from_db()
        self.assertEqual(
            plan.status,
            "active",
            "an unrecognised outcome still moved the plan out of active",
        )
