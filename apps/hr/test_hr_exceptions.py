"""HR Today's queues (§6) — derived, scoped, and self-closing.

The audit's Critical finding: of seventeen HR exception types the mandate
names, thirteen had no detector anywhere in the platform. HR could only find
an expiring work permit, an unreviewed probation or an employee with no
manager by opening the right register and reading it.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    Leave,
    LeaveTypePolicy,
    StaffProfile,
    StaffSupervisorAssignment,
    User,
)
from apps.hr.hr_exceptions import (
    MANAGER_OVERDUE,
    PEOPLE_RISK,
    WAITING_ON_HR,
    build_hr_exceptions,
    grouped_hr_exceptions,
)
from apps.hr.models import OnboardingPlan, PerformanceReview


def _staff(role, email, country="Uganda", state="active"):
    user = User.objects.create_user(
        email=email,
        password="pw",
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        is_active=True,
    )
    return user, StaffProfile.objects.create(
        user=user, title=role, country=country, onboarding_state=state
    )


class HRExceptionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cd, cls.cd_sp = _staff("CountryDirector", "cd@hx.test")
        cls.hr, cls.hr_sp = _staff("HumanResources", "hr@hx.test")
        cls.pl, cls.pl_sp = _staff("Program Lead", "pl@hx.test")
        cls.cceo, cls.cceo_sp = _staff("CCEO", "cceo@hx.test")
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.cceo_sp, supervisor=cls.pl_sp
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.pl_sp, supervisor=cls.cd_sp
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.hr_sp, supervisor=cls.cd_sp
        )
        LeaveTypePolicy.objects.get_or_create(
            leave_type="personal_time_off",
            defaults={"label": "Personal Time Off", "annual_entitlement": 21},
        )

    def _kinds(self, principal, today=None):
        return {i.kind for i in build_hr_exceptions(principal, today or date.today())}

    # ── waiting on HR ────────────────────────────────────────────────────
    def test_an_escalated_leave_reaches_hr_and_leaves_when_decided(self):
        leave = Leave.objects.create(
            staff=self.cceo_sp,
            type="personal_time_off",
            start_date="2026-09-01",
            end_date="2026-09-05",
            days=5,
            days_charged=5,
            status="hr_review",
        )
        self.assertIn("leave_escalated", self._kinds(self.cd))

        leave.status = "approved"
        leave.save(update_fields=["status"])
        # Nothing was ticked off — the condition simply stopped being true.
        self.assertNotIn("leave_escalated", self._kinds(self.cd))

    def test_a_probation_past_its_review_date_is_hrs_to_decide(self):
        OnboardingPlan.objects.create(
            staff=self.cceo_sp,
            status="in_progress",
            probation_review_date=date.today() - timedelta(days=2),
        )
        items = build_hr_exceptions(self.cd)
        match = next(i for i in items if i.kind == "probation_decision_due")
        self.assertEqual(match.group, WAITING_ON_HR)
        self.assertIn("Confirm, extend or end", match.detail)

    # ── manager overdue ──────────────────────────────────────────────────
    def test_a_leave_nobody_has_decided_becomes_a_manager_exception(self):
        leave = Leave.objects.create(
            staff=self.cceo_sp,
            type="personal_time_off",
            start_date="2026-09-01",
            end_date="2026-09-05",
            days=5,
            days_charged=5,
            status="pending",
        )
        Leave.objects.filter(id=leave.id).update(
            created_at=timezone.now() - timedelta(days=6)
        )
        items = build_hr_exceptions(self.cd)
        match = next(i for i in items if i.kind == "leave_decision_overdue")
        self.assertEqual(match.group, MANAGER_OVERDUE)
        self.assertEqual(match.person, self.cceo.name)

    def test_a_leave_submitted_today_is_not_yet_late(self):
        Leave.objects.create(
            staff=self.cceo_sp,
            type="personal_time_off",
            start_date="2026-09-01",
            end_date="2026-09-05",
            days=5,
            days_charged=5,
            status="pending",
        )
        self.assertNotIn("leave_decision_overdue", self._kinds(self.cd))

    def test_an_overdue_review_names_the_employee_and_links_to_it(self):
        PerformanceReview.objects.create(
            staff=self.cceo_sp,
            period="FY2027 Q1",
            fy="2027",
            review_type="quarterly",
            status="Manager Review Pending",
            due_date=date.today() - timedelta(days=20),
        )
        match = next(
            i for i in build_hr_exceptions(self.cd) if i.kind == "review_overdue"
        )
        self.assertEqual(match.person, self.cceo.name)
        self.assertIn(self.cceo_sp.id, match.url)
        self.assertEqual(match.severity, "high")

    # ── people risk ──────────────────────────────────────────────────────
    def test_an_employee_with_no_manager_is_a_people_risk(self):
        _, orphan_sp = _staff("CCEO", "orphan@hx.test")
        match = next(
            i
            for i in build_hr_exceptions(self.cd)
            if i.kind == "no_supervisor" and i.person == "orphan"
        )
        self.assertEqual(match.group, PEOPLE_RISK)

    def test_a_manager_who_cannot_review_reads_differently_from_no_manager(self):
        """An oversight row is not the reporting line, and the queue has to
        say which of the two problems this is — they need different fixes."""
        _, ia_sp = _staff("ImpactAssessment", "ia@hx.test")
        _, subject_sp = _staff("CCEO", "wrongline@hx.test")
        StaffSupervisorAssignment.objects.create(
            supervisee=subject_sp, supervisor=ia_sp
        )
        match = next(
            i
            for i in build_hr_exceptions(self.cd)
            if i.person == "wrongline" and i.kind == "no_supervisor"
        )
        self.assertIn("cannot review them", match.title)

    def test_an_account_with_no_people_record_is_reported_to_hr(self):
        User.objects.create_user(
            email="ghost@hx.test",
            password="pw",
            name="Ghost Account",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        kinds = self._kinds(self.hr)
        self.assertIn("no_people_record", kinds)

    def test_approved_leave_with_nobody_covering_is_flagged(self):
        today = date.today()
        Leave.objects.create(
            staff=self.cceo_sp,
            type="personal_time_off",
            start_date=(today + timedelta(days=3)).isoformat(),
            end_date=(today + timedelta(days=10)).isoformat(),
            days=8,
            days_charged=6,
            status="approved",
            covering_staff=None,
        )
        self.assertIn("leave_without_coverage", self._kinds(self.cd))

    # ── scope ────────────────────────────────────────────────────────────
    def test_another_country_never_appears(self):
        _, kenyan = _staff("CCEO", "kenya@hx.test", country="Kenya")
        Leave.objects.create(
            staff=kenyan,
            type="personal_time_off",
            start_date="2026-09-01",
            end_date="2026-09-05",
            days=5,
            days_charged=5,
            status="hr_review",
        )
        people = {i.person for i in build_hr_exceptions(self.cd)}
        self.assertNotIn("kenya", people)

    def test_a_program_lead_sees_only_their_own_team(self):
        _, other_sp = _staff("CCEO", "notmine@hx.test")
        PerformanceReview.objects.create(
            staff=other_sp,
            period="FY2027 Q1",
            fy="2027",
            review_type="quarterly",
            status="Manager Review Pending",
            due_date=date.today() - timedelta(days=20),
        )
        people = {i.person for i in build_hr_exceptions(self.pl)}
        self.assertNotIn("notmine", people)

    # ── shape ────────────────────────────────────────────────────────────
    def test_the_headline_counts_match_the_queues_beneath_them(self):
        data = grouped_hr_exceptions(self.cd)
        for group in data["groups"]:
            self.assertEqual(data["counts"][group["key"]], len(group["items"]))
        self.assertEqual(data["total"], sum(data["counts"].values()))

    def test_the_cost_does_not_grow_with_headcount(self):
        """An exception queue that costs a query per employee stops working at
        exactly the headcount where HR starts needing it."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as small:
            build_hr_exceptions(self.cd)
        baseline = len(small.captured_queries)

        for index in range(25):
            _, sp = _staff("CCEO", f"bulk{index}@hx.test")
            StaffSupervisorAssignment.objects.create(
                supervisee=sp, supervisor=self.pl_sp
            )
        with CaptureQueriesContext(connection) as large:
            build_hr_exceptions(self.cd)
        self.assertLessEqual(
            len(large.captured_queries),
            baseline + 2,
            "the queue is paying per-employee queries",
        )
