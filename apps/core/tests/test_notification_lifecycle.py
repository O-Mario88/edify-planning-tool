"""A notification is a piece of work, and work ends.

Before this, nothing in the platform ever closed a notification. To-Dos are
derived live from workflow state and vanish the moment the work is done;
notifications were persisted with no resolution rule at all, so approving a
leave request cleared the task and left the notice unread forever — and a job
then promoted it to "urgent" at 48 hours, which is why the urgent count
carried no information.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Leave, StaffProfile, User
from apps.core.rbac import EdifyRole
from apps.notifications.models import Notification
from apps.notifications.services import (
    NotificationLinkResolver,
    WorkflowNotificationService,
    resolve_condition,
)


def _user(email, name, role):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
        status="active",
    )


class DeduplicationTests(TestCase):
    """One live notification per unresolved condition."""

    def setUp(self):
        self.user = _user("dd@t.org", "Dee", EdifyRole.CCEO.value)

    def _fire(self):
        return WorkflowNotificationService.trigger(
            event_type="activity_submitted_for_review",
            category="activity",
            priority="high",
            title="Awaiting review",
            body="A completion needs review.",
            context_type="Activity",
            context_id="act-1",
            recipients=[self.user.id],
        )

    def test_refiring_the_same_condition_does_not_stack_rows(self):
        self._fire()
        self._fire()
        self._fire()
        rows = Notification.objects.filter(recipient_id=self.user.id)
        self.assertEqual(
            rows.count(),
            1,
            "a 30-day-overdue item must be one notification with a count, not 30",
        )
        self.assertEqual(rows.first().reminder_count, 2)
        self.assertIsNotNone(rows.first().last_reminded_at)

    def test_a_refire_resurfaces_a_read_notification(self):
        self._fire()
        Notification.objects.update(status="read", read_at=timezone.now())
        self._fire()
        self.assertEqual(
            Notification.objects.first().status,
            "unread",
            "a re-fire is new information",
        )

    def test_a_resolved_condition_starts_a_fresh_notification(self):
        self._fire()
        resolve_condition("activity_submitted_for_review", "Activity", "act-1")
        self._fire()
        self.assertEqual(Notification.objects.count(), 2)


class ResolutionTests(TestCase):
    def setUp(self):
        self.user = _user("res@t.org", "Ray", EdifyRole.CCEO.value)
        WorkflowNotificationService.trigger(
            event_type="activity_submitted_for_review",
            category="activity",
            priority="high",
            title="Awaiting review",
            body="b",
            context_type="Activity",
            context_id="act-9",
            recipients=[self.user.id],
        )

    def test_resolving_closes_the_notification(self):
        n = resolve_condition("activity_submitted_for_review", "Activity", "act-9")
        self.assertEqual(n, 1)
        row = Notification.objects.get()
        self.assertIsNotNone(row.resolved_at)
        self.assertFalse(row.action_required)

    def test_resolved_notifications_leave_the_counts(self):
        from apps.notifications.services import counts, unread_count

        # `User.user_id` is a read-only property that already returns id.
        principal = self.user
        self.assertEqual(unread_count(principal)["count"], 1)
        resolve_condition("activity_submitted_for_review", "Activity", "act-9")
        self.assertEqual(unread_count(principal)["count"], 0)
        self.assertEqual(counts(principal)["total"], 0)

    def test_unknown_event_or_missing_context_is_a_no_op(self):
        self.assertEqual(resolve_condition("nope", "Activity", "act-9"), 0)
        self.assertEqual(
            resolve_condition("activity_submitted_for_review", None, None), 0
        )


class LeaveResolutionTests(TestCase):
    """Deciding a leave request closes the approver's notice."""

    def test_approving_leave_closes_the_pending_request_notice(self):
        staff = _user("lr-staff@t.org", "Staffer", EdifyRole.CCEO.value)
        sp = StaffProfile.objects.create(user=staff, country="Uganda")
        approver = _user("lr-pl@t.org", "Lead", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        leave = Leave.objects.create(
            staff=sp,
            type="personal_time_off",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=1),
            days=1,
            status="pending",
        )
        WorkflowNotificationService.trigger(
            event_type="leave_requested",
            category="leave",
            priority="high",
            title="Leave request needs approval",
            body="b",
            context_type="Leave",
            context_id=leave.id,
            recipients=[approver.id],
        )
        self.assertEqual(
            Notification.objects.filter(resolved_at__isnull=True).count(), 1
        )

        from apps.hr.leave_services import LeaveNotificationService

        leave.status = "approved"
        leave.save(update_fields=["status"])
        LeaveNotificationService.notify_leave_approved(leave)

        self.assertEqual(
            Notification.objects.filter(
                source_event_type="leave_requested", resolved_at__isnull=True
            ).count(),
            0,
            "the approver was told to act; they acted",
        )


class DeepLinkTests(TestCase):
    """A notification that knows the record must open the record."""

    def test_ia_is_not_sent_to_a_page_it_cannot_open(self):
        route, _ = NotificationLinkResolver.resolve(
            "activity_submitted_for_review", "Activity", "a1", "ImpactAssessment"
        )
        self.assertEqual(
            route,
            "/ia/dashboard/",
            "/pl/review-queue is gated on `planning`, which IA does not hold",
        )

    def test_project_coordinator_is_routed(self):
        route, _ = NotificationLinkResolver.resolve(
            "critical_school_ssa", "School", "s1", "ProjectCoordinator"
        )
        self.assertNotEqual(route, "/dashboard")

    def test_context_type_matching_is_case_insensitive(self):
        upper, _ = NotificationLinkResolver.resolve("x", "Activity", "a7", "CCEO")
        lower, _ = NotificationLinkResolver.resolve("x", "activity", "a7", "CCEO")
        self.assertEqual(upper, lower)
        self.assertEqual(lower, "/my-plan/a7")

    def test_record_ids_are_carried_into_the_route(self):
        cases = [
            ("School", "sc1", "/schools/sc1"),
            ("Cluster", "cl1", "/clusters/cl1"),
            ("Activity", "ac1", "/my-plan/ac1"),
            ("Project", "pr1", "/projects/pr1"),
            ("WeeklyFundRequest", "wf1", "/fund-requests/weekly/wf1"),
        ]
        for ctx, cid, expected in cases:
            route, _ = NotificationLinkResolver.resolve("unmapped", ctx, cid, "CCEO")
            self.assertEqual(route, expected, f"{ctx} must reach its own record")

    def test_country_budget_reaches_its_own_surface(self):
        route, _ = NotificationLinkResolver.resolve(
            "country_budget_submitted", "MonthlyWorkPlanBudget", "b1", "CountryDirector"
        )
        self.assertEqual(route, "/country-budget")

    def test_leave_approver_link_carries_the_request(self):
        route, _ = NotificationLinkResolver.resolve(
            "unmapped", "Leave", "lv1", "Program Lead"
        )
        self.assertIn("lv1", route)


class EscalationBoundingTests(TestCase):
    """The overdue sweep created a row per RVP per run, forever."""

    def test_rvp_escalation_notices_go_through_the_canonical_service(self):
        import inspect

        from apps.flags import escalation_service

        source = inspect.getsource(escalation_service._notify_rvps)
        self.assertIn("WorkflowNotificationService.trigger", source)
        self.assertNotIn(
            "Notification.objects.create",
            source,
            "a raw insert has no dedupe, no audit row and no realtime publish",
        )
