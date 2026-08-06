"""Sending a corrective action from an oversight page, end to end.

What matters here is that supervision produces a *responsibility* — a tracked
record with an owner, a route and a due date, plus the notification and To-Do
that make it findable — and that it never produces a change to the work itself.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import Client, TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.planning import oversight_service as oversight
from apps.planning.action_models import ACTIVE_STATES, TeamAction
from apps.schools.models import School

SEND_URL = "/team-planning-oversight/send"


class SendActionFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.region = Region.objects.create(id="r1", name="Central")
        cls.district = District.objects.create(
            id="d1", name="Kampala", region=cls.region
        )
        cls.pl_user, cls.pl = cls._staff(
            "pl@a.test", "Team Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.james_user, cls.james = cls._staff("j@a.test", "James", EdifyRole.CCEO)
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.james, supervisor=cls.pl
        )

        cls.school = School.objects.create(
            school_id="s1",
            name="Alpha Primary",
            district=cls.district,
            region=cls.region,
        )
        StaffSchoolAssignment.objects.create(staff=cls.james, school_id=cls.school.id)

        # Overdue and unpriced: two real conditions to send about.
        cls.activity = Activity.objects.create(
            activity_type="school_visit",
            school=cls.school,
            fy=cls.fy,
            quarter="Q1",
            planned_date=date.today() - timedelta(days=20),
            planned_month=(date.today() - timedelta(days=20)).month,
            status="scheduled",
            responsible_staff_id=cls.james.id,
            cost_missing=True,
        )

    @classmethod
    def _staff(cls, email, name, role):
        user = User.objects.create(
            email=email,
            name=name,
            roles=[role.value],
            active_role=role.value,
            is_active=True,
        )
        return user, StaffProfile.objects.create(user=user, title=name)

    def as_pl(self) -> Client:
        client = Client()
        client.force_login(self.pl_user)
        return client


class SendToCceoTest(SendActionFixture):
    def test_sending_creates_a_tracked_responsibility(self):
        response = self.as_pl().post(
            SEND_URL,
            {
                "risk": "activity_overdue",
                "activity_id": self.activity.id,
                "note": "Please close this out.",
            },
        )

        self.assertIn(response.status_code, (200, 302))
        action = TeamAction.objects.get(issue_type="activity_overdue")
        self.assertEqual(action.recipient_id, self.james_user.id)
        self.assertEqual(action.sender_id, self.pl_user.id)
        self.assertTrue(action.workflow_route, "a responsibility needs a route")
        self.assertIsNotNone(action.due_date)
        self.assertIn(action.state, ACTIVE_STATES)

    def test_sending_notifies_the_recipient(self):
        self.as_pl().post(
            SEND_URL, {"risk": "activity_overdue", "activity_id": self.activity.id}
        )

        notification = Notification.objects.filter(
            recipient_id=self.james_user.id, context_type="TeamAction"
        ).first()
        self.assertIsNotNone(notification, "an untold responsibility is not one")
        self.assertTrue(notification.target_route)

    def test_sending_changes_nothing_about_the_activity(self):
        """The whole point: a supervisor may ask, never do it for them."""
        before = Activity.objects.get(id=self.activity.id)
        snapshot = (before.status, before.planned_date, before.responsible_staff_id)

        self.as_pl().post(
            SEND_URL, {"risk": "activity_overdue", "activity_id": self.activity.id}
        )

        after = Activity.objects.get(id=self.activity.id)
        self.assertEqual(
            (after.status, after.planned_date, after.responsible_staff_id), snapshot
        )

    def test_the_same_condition_cannot_be_sent_twice(self):
        client = self.as_pl()
        client.post(
            SEND_URL, {"risk": "activity_overdue", "activity_id": self.activity.id}
        )
        client.post(
            SEND_URL, {"risk": "activity_overdue", "activity_id": self.activity.id}
        )

        self.assertEqual(
            TeamAction.objects.filter(issue_type="activity_overdue").count(),
            1,
            "a repeated click must not double the ask",
        )

    def test_a_condition_that_is_not_true_cannot_be_sent(self):
        healthy = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=date.today() + timedelta(days=30),
            planned_month=(date.today() + timedelta(days=30)).month,
            status="scheduled",
            responsible_staff_id=self.james.id,
        )

        self.as_pl().post(
            SEND_URL, {"risk": "activity_overdue", "activity_id": healthy.id}
        )

        self.assertFalse(
            TeamAction.objects.filter(related_activity_id=healthy.id).exists()
        )

    def test_a_record_outside_the_team_cannot_be_sent_about(self):
        outsider_user, outsider = self._staff("out@a.test", "Outsider", EdifyRole.CCEO)
        foreign = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=date.today() - timedelta(days=20),
            planned_month=(date.today() - timedelta(days=20)).month,
            status="scheduled",
            responsible_staff_id=outsider.id,
        )

        self.as_pl().post(
            SEND_URL, {"risk": "activity_overdue", "activity_id": foreign.id}
        )

        self.assertFalse(
            TeamAction.objects.filter(related_activity_id=foreign.id).exists()
        )


class AutoResolutionTest(SendActionFixture):
    def test_the_action_closes_itself_once_the_condition_clears(self):
        """Resolution is observed, not declared.

        The recipient does not close this by saying so; they close it by doing
        the work, and the sweep notices.
        """
        from apps.planning.action_service import resolve_due_actions

        self.as_pl().post(
            SEND_URL, {"risk": "activity_overdue", "activity_id": self.activity.id}
        )
        action = TeamAction.objects.get(issue_type="activity_overdue")
        self.assertIn(action.state, ACTIVE_STATES)

        # The CCEO does the work.
        self.activity.status = "closed"
        self.activity.save(update_fields=["status"])

        resolve_due_actions()

        action.refresh_from_db()
        self.assertNotIn(action.state, ACTIVE_STATES)
        self.assertTrue(action.resolved_by_system)

    def test_the_action_stays_open_while_the_condition_holds(self):
        from apps.planning.action_service import resolve_due_actions

        self.as_pl().post(
            SEND_URL, {"risk": "activity_overdue", "activity_id": self.activity.id}
        )

        resolve_due_actions()

        action = TeamAction.objects.get(issue_type="activity_overdue")
        self.assertIn(action.state, ACTIVE_STATES)


class DetailDrawerTest(SendActionFixture):
    def test_the_drawer_shows_the_lineage_for_a_record_in_scope(self):
        response = self.as_pl().get(
            f"/team-planning-oversight/detail?activity_id={self.activity.id}"
        )

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Alpha Primary", body)
        self.assertIn("Ownership", body)
        self.assertIn("Cost lineage", body)

    def test_the_drawer_refuses_a_record_outside_the_team(self):
        outsider_user, outsider = self._staff("o2@a.test", "Outsider", EdifyRole.CCEO)
        foreign = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=date.today(),
            status="scheduled",
            responsible_staff_id=outsider.id,
        )

        response = self.as_pl().get(
            f"/team-planning-oversight/detail?activity_id={foreign.id}"
        )

        self.assertEqual(response.status_code, 404)


class RiskAnnotationTest(SendActionFixture):
    def test_the_page_reports_the_risk_as_measured(self):
        items = oversight.build_items(self.pl_user, fy=self.fy)
        summary = oversight.summarize(items)

        self.assertGreaterEqual(summary["at_risk"], 1)
        keys = {r["key"] for i in items for r in i.risks}
        self.assertIn("activity_overdue", keys)
        self.assertIn("scheduled_without_cost", keys)
