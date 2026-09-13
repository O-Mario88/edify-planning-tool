"""The Programme Lead's team performance work (Program Lead alignment, 2026-09-13).

The lead participates in the performance reviews and professional coaching of
the CCEOs assigned to them. These tests pin the surfaces that make that a
job the lead can do from the platform, and the refusals that keep it the
lead's job and nobody else's:

* Performance Reviews lists the people the lead reviews, with each
  conversation's progress in the open window and the reviewer the rule
  resolves — not HR's register with HR's console button.
* Recovery plans: the lead recommends for the people they review (never
  themself), follows the plans read-only, and records the check-ins and
  milestones the plan promises. Authorising and deciding stay HR's.
* Professional Development: the team's requests at the supervisor stage are
  decided in place; a reminder reaches only requests in the sender's scope
  and names who sent it; Sign Off is HR's.
* The reviewer To-Dos, the window notice, and conversation authority resolved
  by apps.hr.review_authority — including the manager's sign-off waiting for
  the employee's reflection.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import (
    Leave,
    StaffProfile,
    StaffSupervisorAssignment,
    TemporaryCoverageAssignment,
    User,
)
from apps.core.exceptions import Forbidden
from apps.core.fy import get_operational_fy
from apps.hr.models import (
    PerformanceCycle,
    PerformanceImprovementPlan,
    PerformancePriority,
    PerformanceReview,
    PerformanceSnapshot,
    RecoveryCheckIn,
)
from apps.notifications.models import Notification
from apps.professional_development.models import (
    PDStatus,
    ProfessionalDevelopmentRequest,
)

LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "pl-team-performance",
    }
}


def _person(email, role, *, country="Uganda", name=None):
    user = User.objects.create_user(
        email=email,
        name=name or email.split("@")[0].replace("-", " ").title(),
        roles=[role],
        active_role=role,
        password="pwd-12345678",
        is_active=True,
        status="active",
    )
    profile = StaffProfile.objects.create(
        user=user,
        staff_number=email.split("@")[0].upper(),
        country=country,
        onboarding_state="active",
        title=role,
    )
    return user, profile


def _cells(row):
    return {cell["label"]: cell["value"] for cell in row["cells"]}


def _metrics(response):
    return {m["label"]: str(m["value"]) for m in response.context["metrics"]}


def _messages(response):
    return [str(m) for m in response.context["messages"]] if response.context else []


class TeamFixture(TestCase):
    """A lead who reviews two officers, a second lead with their own officer,
    the Country Director who reviews both leads, HR, and an Impact Assessment
    officer holding an OVERSIGHT link to one officer (not the reporting line)."""

    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.hr, cls.hr_sp = _person("tp-hr@edify.test", "HumanResources")
        cls.cd, cls.cd_sp = _person("tp-cd@edify.test", "CountryDirector")
        cls.lead, cls.lead_sp = _person("tp-lead@edify.test", "Program Lead")
        cls.other_lead, cls.other_lead_sp = _person(
            "tp-other-lead@edify.test", "Program Lead"
        )
        cls.officer_a, cls.officer_a_sp = _person("tp-amara@edify.test", "CCEO")
        cls.officer_b, cls.officer_b_sp = _person("tp-bosco@edify.test", "CCEO")
        cls.stranger, cls.stranger_sp = _person("tp-stranger@edify.test", "CCEO")
        cls.ia, cls.ia_sp = _person("tp-ia@edify.test", "ImpactAssessment")
        for supervisor, supervisee in (
            (cls.lead_sp, cls.officer_a_sp),
            (cls.lead_sp, cls.officer_b_sp),
            (cls.other_lead_sp, cls.stranger_sp),
            (cls.cd_sp, cls.lead_sp),
            (cls.cd_sp, cls.other_lead_sp),
        ):
            StaffSupervisorAssignment.objects.create(
                supervisor=supervisor, supervisee=supervisee
            )
        # Created last so the reporting line is every officer's first link.
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.ia_sp, supervisee=cls.officer_a_sp
        )

    def _review(self, profile, *, stage="priorities_agreed", priorities=2, **extra):
        review = PerformanceReview.objects.create(
            staff=profile,
            period=self.fy,
            fy=self.fy,
            review_type=extra.pop("review_type", "annual_priorities"),
            stage=stage,
            due_date=extra.pop("due_date", date.today() + timedelta(days=60)),
            **extra,
        )
        for sequence in range(1, priorities + 1):
            PerformancePriority.objects.create(
                review=review,
                sequence=sequence,
                outcome_statement=f"Outcome {sequence} for {profile.user.name}",
                weight=100 // max(priorities, 1),
            )
        return review

    def _cycle(self, window="q1"):
        return PerformanceCycle.objects.update_or_create(
            fy=self.fy,
            defaults={
                "active_window": window,
                "window_opened_at": timezone.now(),
                "opened_by": self.hr,
            },
        )[0]

    def _snapshot(self, review, window="q1", **extra):
        return PerformanceSnapshot.objects.create(
            review=review, window=window, data={"priorities": []}, **extra
        )


# ── Performance Reviews ──────────────────────────────────────────────────────


class TeamPerformanceReviewsPageTest(TeamFixture):
    def setUp(self):
        self._cycle("q1")
        # The stale manager field names the OTHER lead; the rule names ours.
        self.review_a = self._review(self.officer_a_sp, manager=self.other_lead_sp)
        self._snapshot(self.review_a)
        first = self.review_a.priorities.order_by("sequence").first()
        first.manager_rating = "met"
        first.employee_reflection = "Visits recovered after the floods."
        first.save()
        PerformanceReview.objects.filter(id=self.review_a.id).update(
            employee_reflection_at=timezone.now()
        )
        self._review(self.stranger_sp)
        self._review(self.lead_sp)

    def test_the_lead_sees_the_people_they_review_and_each_conversation(self):
        self.client.force_login(self.lead)
        page = self.client.get("/performance-reviews")
        self.assertEqual(page.status_code, 200)
        rows = {_cells(r)["CCEO"]: r for r in page.context["rows"]}
        self.assertEqual(
            set(rows), {self.officer_a.name, self.officer_b.name}
        )  # never themself, never another lead's officer

        amara = _cells(rows[self.officer_a.name])
        self.assertEqual(amara["Agreement"], "Priorities agreed")
        self.assertEqual(amara["Open window"], "Q1")
        self.assertEqual(amara["Manager columns"], "1 of 2")
        self.assertEqual(amara["Reflection"], "Saved")
        self.assertEqual(amara["Signed off"], "Not yet")
        self.assertEqual(
            amara["Reviewer"],
            self.lead.name,
            "the reviewer is resolved live, not the stale review.manager",
        )
        self.assertEqual(
            rows[self.officer_a.name]["actions"],
            [
                {
                    "label": "Open conversation",
                    "href": f"/performance-conversation?staff={self.officer_a_sp.id}",
                }
            ],
        )
        bosco = _cells(rows[self.officer_b.name])
        self.assertEqual(bosco["Agreement"], "No agreement")
        self.assertEqual(bosco["Manager columns"], "—")

        metrics = _metrics(page)
        self.assertEqual(metrics["Officers you review"], "2")
        self.assertEqual(metrics["Waiting on you as reviewer"], "1")
        self.assertEqual(metrics["Reviews past due"], "0")
        self.assertNotContains(page, "Open Performance Cycle")
        self.assertNotContains(page, "Manager rating")
        self.assertNotContains(page, "HR overview")

    def test_hr_keeps_its_register_and_the_cd_loses_only_hr_controls(self):
        self.client.force_login(self.hr)
        hr_page = self.client.get("/performance-reviews")
        self.assertContains(hr_page, "Open Performance Cycle")
        self.assertContains(hr_page, "Manager rating")

        self.client.force_login(self.cd)
        cd_page = self.client.get("/performance-reviews")
        self.assertEqual(cd_page.status_code, 200)
        self.assertNotContains(cd_page, "Open Performance Cycle")
        self.assertNotContains(cd_page, "Manager rating")
        self.assertContains(cd_page, self.stranger.name)  # the country register

    def test_the_rows_are_one_rule_and_fixed_cost(self):
        from apps.hr.performance_engine import team_review_rows

        def measure():
            with CaptureQueriesContext(connection) as ctx:
                rows = team_review_rows(self.lead, fy=self.fy)
            return len(ctx.captured_queries), len(rows)

        small, count = measure()
        self.assertEqual(count, 2)
        for i in range(4):
            _, profile = _person(f"tp-extra-{i}@edify.test", "CCEO")
            StaffSupervisorAssignment.objects.create(
                supervisor=self.lead_sp, supervisee=profile
            )
            review = self._review(profile)
            self._snapshot(review)
        large, count = measure()
        self.assertEqual(count, 6)
        self.assertEqual(large, small, "a query per officer crept in")


@override_settings(CACHES=LOCMEM)
class TeamPerformanceReviewsPageBudgetTest(TeamFixture):
    def _page_queries(self):
        self.client.force_login(self.lead)
        self.client.get("/performance-reviews")  # warm per-process caches
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/performance-reviews")
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries)

    def test_the_page_does_not_grow_with_the_team(self):
        self._cycle("q1")
        self._snapshot(self._review(self.officer_a_sp))
        small = self._page_queries()
        for i in range(4):
            _, profile = _person(f"tp-budget-{i}@edify.test", "CCEO")
            StaffSupervisorAssignment.objects.create(
                supervisor=self.lead_sp, supervisee=profile
            )
            self._snapshot(self._review(profile))
        large = self._page_queries()
        self.assertLessEqual(large, small, f"{small} → {large} queries")


# ── Recovery plans ───────────────────────────────────────────────────────────


class RecoveryPlansForTheLeadTest(TeamFixture):
    REASON = "Missed three reporting deadlines despite weekly coaching."

    def setUp(self):
        self.client.force_login(self.lead)

    def _recommend(self, staff_id):
        return self.client.post(
            "/recovery-plans/recommend",
            {"staff_id": staff_id, "cause": "skill", "reason": self.REASON},
            follow=True,
        )

    def test_the_picker_offers_the_people_the_lead_reviews(self):
        drawer = self.client.get("/recovery-plans/new")
        self.assertContains(drawer, f'value="{self.officer_a_sp.id}"')
        self.assertContains(drawer, f'value="{self.officer_b_sp.id}"')
        self.assertNotContains(drawer, f'value="{self.lead_sp.id}"')
        self.assertNotContains(drawer, f'value="{self.stranger_sp.id}"')

    def test_nobody_recommends_a_plan_for_themself_or_outside_their_reviews(self):
        response = self._recommend(self.lead_sp.id)
        self.assertIn("Choose someone you review.", _messages(response))
        self._recommend(self.stranger_sp.id)
        self.assertFalse(PerformanceImprovementPlan.objects.exists())

        from apps.hr.performance_engine import recommend_pip

        with self.assertRaises(Forbidden):
            recommend_pip(self.lead_sp, self.REASON, self.lead)
        with self.assertRaises(Forbidden):
            recommend_pip(self.officer_a_sp, self.REASON, self.other_lead)
        with self.assertRaises(Forbidden):
            recommend_pip(self.officer_a_sp, self.REASON, self.ia)

        self._recommend(self.officer_a_sp.id)
        plan = PerformanceImprovementPlan.objects.get(staff=self.officer_a_sp)
        self.assertEqual(plan.status, "draft")
        self.assertEqual(plan.recommended_by_id, self.lead.id)

    def test_the_lead_follows_a_plan_and_hr_alone_authorises_and_decides(self):
        from apps.hr.performance_engine import activate_pip, recommend_pip

        plan = recommend_pip(self.officer_a_sp, self.REASON, self.lead)
        drawer = self.client.get(f"/recovery-plans/{plan.id}")
        self.assertNotContains(drawer, "Authorise the plan")
        self.assertContains(drawer, "HR authorises this plan")
        self.client.post(
            f"/recovery-plans/{plan.id}/activate", {"action_plan": "Weekly check-ins."}
        )
        plan.refresh_from_db()
        self.assertEqual(plan.status, "draft", "the lead authorised their own plan")

        activate_pip(plan, self.hr, action_plan="Weekly check-ins with the lead.")
        drawer = self.client.get(f"/recovery-plans/{plan.id}")
        self.assertContains(drawer, "Record the check-in")
        self.assertNotContains(drawer, "Record the outcome")

        self.client.force_login(self.hr)
        self.assertContains(
            self.client.get(f"/recovery-plans/{plan.id}"), "Record the outcome"
        )

        page_for_lead = self._page(self.lead)
        self.assertNotContains(page_for_lead, "Open Performance Cycle")

    def _page(self, user):
        self.client.force_login(user)
        return self.client.get("/recovery-plans")

    def test_the_reviewer_records_a_check_in_and_closes_a_milestone(self):
        from apps.audit.models import AuditLog
        from apps.hr.performance_engine import activate_pip, recommend_pip

        plan = recommend_pip(self.officer_a_sp, self.REASON, self.lead)
        activate_pip(plan, self.hr, action_plan="Weekly check-ins.")
        milestone = plan.milestones.order_by("due_date").first()

        self.client.post(
            f"/recovery-plans/{plan.id}/check-in",
            {
                "held_on": date.today().isoformat(),
                "note": "Two of three reports on time.",
                "milestone_id": milestone.id,
            },
        )
        check_in = RecoveryCheckIn.objects.get(plan=plan)
        self.assertEqual(check_in.recorded_by_id, self.lead.id)
        milestone.refresh_from_db()
        self.assertTrue(milestone.is_complete)
        self.assertTrue(
            AuditLog.objects.filter(action="hr.recovery_check_in_recorded").exists()
        )

        future = self.client.post(
            f"/recovery-plans/{plan.id}/check-in",
            {
                "held_on": (date.today() + timedelta(days=3)).isoformat(),
                "note": "Not yet held.",
            },
            follow=True,
        )
        self.assertIn("A check-in cannot be dated in the future.", _messages(future))
        self.assertEqual(RecoveryCheckIn.objects.filter(plan=plan).count(), 1)

        self.client.force_login(self.other_lead)
        self.assertEqual(
            self.client.post(
                f"/recovery-plans/{plan.id}/check-in",
                {"held_on": date.today().isoformat(), "note": "x"},
            ).status_code,
            404,
        )
        self.client.force_login(self.hr)
        refused = self.client.post(
            f"/recovery-plans/{plan.id}/check-in",
            {"held_on": date.today().isoformat(), "note": "HR note"},
            follow=True,
        )
        self.assertIn(
            "Only the employee's reviewer records a check-in.", _messages(refused)
        )
        self.assertEqual(RecoveryCheckIn.objects.filter(plan=plan).count(), 1)

    def test_a_plan_about_the_lead_is_not_on_the_leads_team_register(self):
        from apps.hr.performance_engine import recommend_pip

        plan = recommend_pip(self.lead_sp, self.REASON, self.cd)
        page = self._page(self.lead)
        self.assertEqual(page.context["rows"], [])
        self.assertEqual(self.client.get(f"/recovery-plans/{plan.id}").status_code, 404)


# ── Professional Development ─────────────────────────────────────────────────


class TeamDevelopmentTest(TeamFixture):
    def _request(self, profile, status=PDStatus.SUBMITTED_TO_SUPERVISOR, **extra):
        return ProfessionalDevelopmentRequest.objects.create(
            fy=self.fy,
            staff_id=profile.id,
            staff_name=profile.user.name,
            country="Uganda",
            course_name=extra.pop("course_name", f"Course for {profile.user.name}"),
            course_type="online",
            institution="Coursera",
            course_link="https://coursera.org/x",
            start_date=date.today() + timedelta(days=30),
            end_date=date.today() + timedelta(days=90),
            funding_type="self_funded",
            created_by=profile.user_id,
            status=status,
            submitted_at=timezone.now(),
            **extra,
        )

    def _post(self, **data):
        return self.client.post("/cpd-learning/action", data, follow=True)

    def test_the_team_page_puts_the_requests_waiting_on_the_lead_first(self):
        mine = self._request(self.officer_b_sp)
        self._request(self.stranger_sp)
        self.client.force_login(self.lead)
        page = self.client.get("/cpd-learning")
        self.assertEqual(page.status_code, 200)
        self.assertTemplateUsed(page, "partials/hr/pd_dashboard/team_body.html")
        self.assertEqual(
            [r["request_id"] for r in page.context["supervisor_queue"]], [mine.id]
        )
        self.assertContains(page, "Team Professional Development")
        self.assertContains(page, "Waiting for your approval")
        self.assertContains(page, f"/cpd-learning/return?request_id={mine.id}")
        self.assertNotContains(page, "Role-Based PD Allocation Settings")
        self.assertContains(page, 'aria-label="Performance &amp; Coaching sections"')

    def test_the_lead_approves_and_returns_in_place(self):
        approve = self._request(self.officer_b_sp, course_name="Approve me")
        send_back = self._request(self.officer_b_sp, course_name="Return me")
        theirs = self._request(self.stranger_sp)
        self.client.force_login(self.lead)

        self._post(action="supervisor_approve", request_id=approve.id)
        approve.refresh_from_db()
        self.assertEqual(approve.status, PDStatus.SUBMITTED_TO_HR)

        blank = self._post(action="supervisor_return", request_id=send_back.id)
        self.assertIn("A return reason is required.", _messages(blank))
        send_back.refresh_from_db()
        self.assertEqual(send_back.status, PDStatus.SUBMITTED_TO_SUPERVISOR)
        self._post(
            action="supervisor_return",
            request_id=send_back.id,
            reason="Add the course fee breakdown.",
        )
        send_back.refresh_from_db()
        self.assertEqual(send_back.status, PDStatus.RETURNED_BY_SUPERVISOR)

        refused = self._post(action="supervisor_approve", request_id=theirs.id)
        self.assertTrue(
            any("not the configured supervisor" in m for m in _messages(refused))
        )
        theirs.refresh_from_db()
        self.assertEqual(theirs.status, PDStatus.SUBMITTED_TO_SUPERVISOR)

        drawer = self.client.get(f"/cpd-learning/return?request_id={theirs.id}")
        self.assertContains(drawer, "not waiting for your approval")
        self.assertNotContains(drawer, "Return to the officer")

    def test_a_reminder_stays_in_scope_and_names_its_sender(self):
        mine = self._request(self.officer_b_sp, status=PDStatus.IN_PROGRESS)
        theirs = self._request(self.stranger_sp, status=PDStatus.IN_PROGRESS)
        self.client.force_login(self.lead)

        refused = self._post(action="send_reminder", request_id=theirs.id)
        self.assertIn("Request not found.", _messages(refused))
        self.assertFalse(
            Notification.objects.filter(recipient_id=self.stranger.id).exists()
        )

        self._post(action="send_reminder", request_id=mine.id)
        note = Notification.objects.get(recipient_id=self.officer_b.id)
        self.assertEqual(note.title, "Reminder from your Programme Lead")
        self.assertIn(self.lead.name, note.body)

    def test_sign_off_is_hrs_alone(self):
        ready = self._request(
            self.officer_b_sp,
            status=PDStatus.AWAITING_HR_SIGNOFF,
            marked_complete_at=timezone.now(),
        )
        self.client.force_login(self.lead)
        page = self.client.get("/cpd-learning")
        self.assertNotContains(page, 'value="sign_off"')
        refused = self._post(action="sign_off", request_id=ready.id)
        self.assertIn("Only HR signs off a completed course.", _messages(refused))
        ready.refresh_from_db()
        self.assertEqual(ready.status, PDStatus.AWAITING_HR_SIGNOFF)

        self.client.force_login(self.hr)
        hr_page = self.client.get("/cpd-learning")
        self.assertTemplateUsed(hr_page, "partials/hr/pd_dashboard/body.html")
        self.assertContains(hr_page, 'value="sign_off"')

    def test_the_country_director_decides_a_leads_request_on_their_page(self):
        waiting = self._request(self.lead_sp)
        self.client.force_login(self.cd)
        page = self.client.get("/cpd-learning")
        self.assertEqual(
            [r["request_id"] for r in page.context["supervisor_queue"]], [waiting.id]
        )
        self.assertContains(page, "Waiting for your approval")

    def test_policy_compliance_carries_the_team_performance_strip(self):
        self.client.force_login(self.lead)
        page = self.client.get("/policy-compliance")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'aria-label="Performance &amp; Coaching sections"')

    def test_the_approval_list_is_fixed_cost(self):
        from apps.professional_development.hr_dashboard_service import (
            HRPDDashboardService,
        )

        self._request(self.officer_b_sp)

        def measure():
            with CaptureQueriesContext(connection) as ctx:
                rows = HRPDDashboardService.supervisor_queue(self.lead)
            return len(ctx.captured_queries), len(rows)

        small, count = measure()
        self.assertEqual(count, 1)
        for i in range(5):
            self._request(self.officer_a_sp, course_name=f"Course {i}")
        large, count = measure()
        self.assertEqual(count, 6)
        self.assertEqual(large, small)


# ── Reviewer To-Dos ──────────────────────────────────────────────────────────


class ReviewerTodosTest(TeamFixture):
    def _todos(self, user=None, role="Program Lead"):
        from apps.hr.review_todos import reviewer_todos

        return {
            row["id"]: row
            for row in reviewer_todos(user or self.lead, role, date.today())
        }

    def test_what_a_reviewer_owes_becomes_a_to_do_and_closes_itself(self):
        self._cycle("q1")
        review_a = self._review(
            self.officer_a_sp, due_date=date.today() - timedelta(days=3)
        )
        snapshot = self._snapshot(review_a)
        review_b = self._review(self.officer_b_sp, stage="priorities_manager_review")
        probation = self._review(
            self.officer_b_sp,
            review_type="probation",
            stage="not_started",
            priorities=0,
            due_date=date.today() - timedelta(days=10),
        )

        rows = self._todos()
        hold = rows[f"review-hold-{review_a.id}-q1"]
        self.assertEqual(
            hold["title"], f"Hold the Q1 conversation with {self.officer_a.name}"
        )
        self.assertEqual(hold["status_key"], "overdue", "overdue AND owed is one row")
        self.assertNotIn(f"review-overdue-{review_a.id}", rows)
        self.assertEqual(
            hold["action_url"],
            f"/performance-conversation?staff={self.officer_a_sp.id}",
        )
        agree = rows[f"review-agree-{review_b.id}"]
        self.assertEqual(agree["title"], f"Review {self.officer_b.name}'s priorities")
        self.assertEqual(agree["status_key"], "waiting_me")
        late = rows[f"review-overdue-{probation.id}"]
        self.assertEqual(
            late["title"],
            f"Complete {self.officer_b.name}'s overdue performance review",
        )
        self.assertEqual(len(rows), 3)

        snapshot.signed_off_at = timezone.now()
        snapshot.save(update_fields=["signed_off_at"])
        rows = self._todos()
        self.assertNotIn(f"review-hold-{review_a.id}-q1", rows)
        self.assertIn(f"review-overdue-{review_a.id}", rows)

    def test_the_builder_is_registered_and_quiet_for_those_who_review_nobody(self):
        from apps.command_center.todo_service import MODULE_TODO_BUILDERS

        self.assertIn("apps.hr.review_todos:reviewer_todos", MODULE_TODO_BUILDERS)
        self._review(self.officer_a_sp, stage="priorities_manager_review")
        self.assertEqual(self._todos(self.officer_a, "CCEO"), {})
        self.assertEqual(self._todos(self.hr, "HumanResources"), {})
        self.assertEqual(self._todos(self.other_lead), {})

    def test_the_builder_is_fixed_cost(self):
        from apps.hr.review_todos import reviewer_todos

        self._cycle("q1")
        self._snapshot(self._review(self.officer_a_sp))

        def measure():
            with CaptureQueriesContext(connection) as ctx:
                rows = reviewer_todos(self.lead, "Program Lead", date.today())
            return len(ctx.captured_queries), len(rows)

        small, count = measure()
        self.assertEqual(count, 1)
        for i in range(4):
            _, profile = _person(f"tp-todo-{i}@edify.test", "CCEO")
            StaffSupervisorAssignment.objects.create(
                supervisor=self.lead_sp, supervisee=profile
            )
            self._snapshot(self._review(profile))
        large, count = measure()
        self.assertEqual(count, 5)
        self.assertEqual(large, small)


# ── Conversation authority ───────────────────────────────────────────────────


class ConversationAuthorityTest(TeamFixture):
    def setUp(self):
        self._cycle("q1")
        self.review = self._review(self.officer_a_sp)
        self.snapshot = self._snapshot(self.review)
        self.priority = self.review.priorities.order_by("sequence").first()

    def _sign_off(self, user):
        self.client.force_login(user)
        return self.client.post(
            f"/performance-conversation/{self.review.id}/sign-off",
            {"window": "q1", "staff": self.officer_a_sp.id},
            follow=True,
        )

    def test_an_oversight_link_is_not_the_reporting_line(self):
        self.client.force_login(self.ia)
        page = self.client.get(
            f"/performance-conversation?staff={self.officer_a_sp.id}"
        )
        self.assertNotContains(
            page, "Save manager review", status_code=page.status_code
        )
        signed = self.client.post(
            f"/performance-conversation/{self.review.id}/sign-off", {"window": "q1"}
        )
        self.assertEqual(signed.status_code, 403)

        self.client.force_login(self.lead)
        page = self.client.get(
            f"/performance-conversation?staff={self.officer_a_sp.id}"
        )
        self.assertContains(page, "Save manager review")
        self.assertContains(page, 'href="/performance-reviews"')

    def test_the_managers_sign_off_waits_for_the_employees_reflection(self):
        refused = self._sign_off(self.lead)
        self.assertTrue(
            any("has not saved their reflection" in m for m in _messages(refused))
        )
        self.snapshot.refresh_from_db()
        self.assertIsNone(self.snapshot.signed_off_at)

        # A reflection from before this window's figures were frozen is last
        # window's words, not this conversation's.
        self.priority.employee_reflection = "Last quarter's reflection."
        self.priority.save()
        PerformanceReview.objects.filter(id=self.review.id).update(
            employee_reflection_at=self.snapshot.taken_at - timedelta(days=30)
        )
        self._sign_off(self.lead)
        self.snapshot.refresh_from_db()
        self.assertIsNone(self.snapshot.signed_off_at)

        self.client.force_login(self.officer_a)
        self.client.post(
            f"/performance-conversation/priority/{self.priority.id}/save",
            {"channel": "employee", "employee_reflection": "Back on track in Q1."},
        )
        self.review.refresh_from_db()
        self.assertGreaterEqual(
            self.review.employee_reflection_at, self.snapshot.taken_at
        )

        self._sign_off(self.lead)
        self.snapshot.refresh_from_db()
        self.assertIsNotNone(self.snapshot.signed_off_at)

    def test_hr_and_the_employee_keep_their_sign_off(self):
        from apps.hr.performance_engine import sign_off

        sign_off(self.review, "q1", self.hr)
        self.snapshot.refresh_from_db()
        self.assertIsNotNone(self.snapshot.signed_off_at)

    def test_cover_holds_the_review_while_the_lead_is_away(self):
        now = timezone.now()
        leave = Leave.objects.create(
            staff=self.lead_sp,
            type="personal_time_off",
            start_date=(now - timedelta(days=1)).date().isoformat(),
            end_date=(now + timedelta(days=1)).date().isoformat(),
            days=3,
            status="approved",
        )
        TemporaryCoverageAssignment.objects.create(
            original_staff=self.lead_sp,
            covering_staff=self.other_lead_sp,
            leave_request=leave,
            start_datetime=now - timedelta(days=1),
            end_datetime=now + timedelta(days=1),
            status="active",
        )
        self.client.force_login(self.other_lead)
        page = self.client.get(
            f"/performance-conversation?staff={self.officer_a_sp.id}"
        )
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Save manager review")

        from apps.hr.performance_engine import sign_off

        sign_off(self.review, "q1", self.hr)
        document = self.client.get(
            f"/performance-conversation/{self.review.id}/document/q1"
        )
        self.assertEqual(document.status_code, 200)

    def test_the_reviewer_agrees_submitted_priorities(self):
        review = self._review(self.officer_b_sp, stage="priorities_manager_review")
        self.client.force_login(self.lead)
        page = self.client.get(
            f"/performance-conversation?staff={self.officer_b_sp.id}"
        )
        self.assertContains(page, "Agree these priorities")

        url = f"/performance-conversation/{review.id}/agree-priorities"
        self.client.force_login(self.officer_b)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.other_lead)
        self.assertEqual(self.client.post(url).status_code, 403)
        review.refresh_from_db()
        self.assertEqual(review.stage, "priorities_manager_review")

        self.client.force_login(self.lead)
        self.client.post(url, {"note": "Agreed at our one-to-one."})
        review.refresh_from_db()
        self.assertEqual(review.stage, "priorities_agreed")


# ── The window notice ────────────────────────────────────────────────────────


class WindowOpenedNoticeTest(TeamFixture):
    def test_each_live_reviewer_is_told_the_window_is_open(self):
        from apps.hr.performance_engine import activate_window
        from apps.notifications.services import NotificationLinkResolver

        cycle = self._cycle("none")
        self._review(self.officer_a_sp)
        self._review(self.officer_b_sp)
        self._review(self.lead_sp)
        activate_window(cycle, "q1", self.hr)

        to_lead = Notification.objects.get(
            recipient_id=self.lead.id, source_event_type="performance_window_opened"
        )
        self.assertEqual(to_lead.target_route, "/performance-reviews")
        self.assertIn(self.officer_a.name, to_lead.body)
        self.assertIn(self.officer_b.name, to_lead.body)
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.cd.id, source_event_type="performance_window_opened"
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                recipient_id__in=[self.ia.id, self.other_lead.id],
                source_event_type="performance_window_opened",
            ).exists(),
            "an oversight link, and a lead with nobody in the cycle, get nothing",
        )
        self.assertEqual(
            NotificationLinkResolver.resolve(
                "performance_window_opened",
                "PerformanceCycle",
                f"{self.fy}:q1",
                "RegionalVicePresident",
            )[0],
            "/todos",
        )
