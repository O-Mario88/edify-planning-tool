"""Every handoff must tell the next actor.

Fourteen state changes fired no notification and created no To-Do, so the next
person had to discover the work by browsing. The activity chain contained no
notification calls at all, and seven of eight finance events fell through the
resolver onto /dashboard.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.notifications.services import (
    NotificationLinkResolver,
    WorkflowNotificationService,
)
from apps.schools.models import School


def _user(email, name, role):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
    )


class ResolverCoverageTests(TestCase):
    """No workflow event may degrade to 'View Dashboard'."""

    FINANCE_EVENTS = [
        "weekly_fund_request_submitted",
        "weekly_fund_request_approved",
        "weekly_fund_request_returned",
        "weekly_fund_request_ready",
        "weekly_fund_request_disbursed",
        "fund_request_approved",
        "fund_request_disbursed",
        "fund_request_returned",
        "fund_request_sent_to_accountant",
    ]
    ACTIVITY_EVENTS = [
        "activity_submitted_for_review",
        "activity_returned_by_pl",
        "activity_ia_verified",
        "accountability_cleared",
        "reimbursement_due",
    ]

    def test_no_finance_event_lands_on_the_dashboard(self):
        for event in self.FINANCE_EVENTS:
            for role in ("CCEO", "Program Lead", "Accountant", "ProjectCoordinator"):
                route, label = NotificationLinkResolver.resolve(
                    event, "WeeklyFundRequest", "W1", role
                )
                self.assertNotEqual(
                    route,
                    "/dashboard",
                    f"{event} for {role} still falls through to the dashboard",
                )

    def test_no_activity_event_lands_on_the_dashboard(self):
        for event in self.ACTIVITY_EVENTS:
            route, _ = NotificationLinkResolver.resolve(event, "Activity", "A1", "CCEO")
            self.assertNotEqual(route, "/dashboard", f"{event} has no destination")

    def test_accountant_is_sent_to_the_disbursement_dashboard(self):
        route, label = NotificationLinkResolver.resolve(
            "fund_request_approved", "FundRequest", "F1", "Accountant"
        )
        self.assertEqual(route, "/disbursements")
        self.assertEqual(label, "Disburse Funds")

    def test_unknown_event_still_reaches_its_record_type(self):
        """A future event with no branch should reach the right surface, not
        the dashboard."""
        route, _ = NotificationLinkResolver.resolve(
            "some_new_event", "WeeklyFundRequest", "W1", "CCEO"
        )
        self.assertEqual(route, "/fund-requests/weekly")


class RecipientResolutionTests(TestCase):
    """Recipients addressed by StaffProfile id were silently dropped."""

    def test_a_staffprofile_id_still_reaches_the_person(self):
        user = _user("notify-sp@t.org", "Nina", EdifyRole.CCEO.value)
        sp = StaffProfile.objects.create(user=user, title="CCEO", country="Uganda")

        WorkflowNotificationService.trigger(
            event_type="activity_returned_by_pl",
            category="activity",
            priority="high",
            title="Returned",
            body="Fix it",
            context_type="Activity",
            context_id="A1",
            recipients=[sp.id],  # StaffProfile id, not User id
        )
        self.assertTrue(
            Notification.objects.filter(recipient_id=user.id).exists(),
            "a notification addressed by StaffProfile id must still arrive",
        )

    def test_a_user_id_still_works(self):
        user = _user("notify-u@t.org", "Ned", EdifyRole.CCEO.value)
        WorkflowNotificationService.trigger(
            event_type="activity_returned_by_pl",
            category="activity",
            priority="high",
            title="Returned",
            body="Fix it",
            context_type="Activity",
            context_id="A1",
            recipients=[user.id],
        )
        self.assertTrue(Notification.objects.filter(recipient_id=user.id).exists())


class ActivityChainNotificationTests(TestCase):
    """The chain had no notifications at all."""

    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Sig Region")
        district = District.objects.create(name="Sig District", region=region)
        cls.school = School.objects.create(
            name="Sig Primary",
            school_id="SG-1",
            region_id=region.id,
            district_id=district.id,
        )

    def setUp(self):
        self.cceo = _user("cceo-sig@t.org", "Cara", EdifyRole.CCEO.value)
        self.cceo_sp = StaffProfile.objects.create(
            user=self.cceo, title="CCEO", country="Uganda"
        )
        self.pl = _user("pl-sig@t.org", "Pat", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        self.pl_sp = StaffProfile.objects.create(
            user=self.pl, title="PL", country="Uganda"
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_sp, supervisor=self.pl_sp
        )
        self.act = Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="submitted_to_pl",
            fy="2026",
            quarter="Q4",
            responsible_staff_id=self.cceo_sp.id,
            planned_date=timezone.now(),
        )

    def test_pl_return_notifies_the_submitter_with_the_reason(self):
        from apps.pl_review import services

        services.return_activity(self.act.id, {"reason": "Photos unclear"}, self.pl)
        notif = Notification.objects.filter(recipient_id=self.cceo.id).first()
        self.assertIsNotNone(notif, "the submitter must be told their work came back")
        self.assertIn("Photos unclear", notif.body)
        self.assertNotEqual(notif.target_route, "/dashboard")

    def test_pl_confirm_notifies_impact_assessment(self):
        from apps.pl_review import services

        ia = _user("ia-sig@t.org", "Ivy", EdifyRole.IMPACT_ASSESSMENT.value)
        services.confirm(self.act.id, self.pl)
        self.assertTrue(Notification.objects.filter(recipient_id=ia.id).exists())

    def test_supervisor_resolution_spans_both_id_spaces(self):
        from apps.activities.services import _supervisor_user_ids

        self.assertEqual(_supervisor_user_ids(self.act), [self.pl.id])

        user_space = Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="submitted_to_pl",
            fy="2026",
            quarter="Q4",
            responsible_staff_id=self.cceo.id,  # User id this time
            planned_date=timezone.now(),
        )
        self.assertEqual(_supervisor_user_ids(user_space), [self.pl.id])


class MissingTodoProducerTests(TestCase):
    """Four obligations had no derived task."""

    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Todo Region")
        district = District.objects.create(name="Todo District", region=region)
        cls.school = School.objects.create(
            name="Todo Primary",
            school_id="TD-1",
            region_id=region.id,
            district_id=district.id,
        )

    def setUp(self):
        self.cceo = _user("cceo-todo@t.org", "Cara", EdifyRole.CCEO.value)
        self.cceo_sp = StaffProfile.objects.create(
            user=self.cceo, title="CCEO", country="Uganda"
        )
        self.pl = _user("pl-todo@t.org", "Pat", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        self.pl_sp = StaffProfile.objects.create(
            user=self.pl, title="PL", country="Uganda"
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_sp, supervisor=self.pl_sp
        )

    def test_pl_gets_a_review_todo(self):
        from apps.command_center.todo_service import get_todos

        Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="submitted_to_pl",
            fy="2026",
            quarter="Q4",
            responsible_staff_id=self.cceo_sp.id,
            planned_date=timezone.now(),
        )
        titles = [t["title"] for t in get_todos(self.pl)["todos"]]
        self.assertIn("Review Completion", titles)

    def test_an_unrelated_pl_gets_no_review_todo(self):
        from apps.command_center.todo_service import get_todos

        other = _user("pl2-todo@t.org", "Pia", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        StaffProfile.objects.create(user=other, title="PL", country="Uganda")
        Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="submitted_to_pl",
            fy="2026",
            quarter="Q4",
            responsible_staff_id=self.cceo_sp.id,
            planned_date=timezone.now(),
        )
        titles = [t["title"] for t in get_todos(other)["todos"]]
        self.assertNotIn("Review Completion", titles)

    def test_owner_gets_a_partner_delay_todo(self):
        from apps.command_center.todo_service import get_todos

        Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="partner_scheduled",
            delivery_type="partner",
            fy="2026",
            quarter="Q4",
            monitored_by_staff_id=self.cceo_sp.id,
            planned_date=timezone.now() - timedelta(days=6),
        )
        titles = [t["title"] for t in get_todos(self.cceo)["todos"]]
        self.assertIn("Chase Partner Delivery", titles)

    def test_on_time_partner_work_creates_no_delay_todo(self):
        from apps.command_center.todo_service import get_todos

        Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="partner_scheduled",
            delivery_type="partner",
            fy="2026",
            quarter="Q4",
            monitored_by_staff_id=self.cceo_sp.id,
            planned_date=timezone.now() + timedelta(days=6),
        )
        titles = [t["title"] for t in get_todos(self.cceo)["todos"]]
        self.assertNotIn("Chase Partner Delivery", titles)

    def test_accountant_settlement_queues_produce_tasks(self):
        from apps.command_center.todo_service import _accountant_settlement_todos

        # Exercised directly: the four settlement queues had no producer at all.
        rows = _accountant_settlement_todos()
        self.assertIsInstance(rows, list)
        for r in rows:
            self.assertTrue(r["action_url"].startswith("/"))
            self.assertTrue(r["actionable"])
