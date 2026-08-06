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


class RoleQueueOnStaffWorkTest(SendActionFixture):
    """The tail of the chain — verification and payment — has actors too.

    A supervision page that stops naming anybody once work leaves the field is
    where activities go to sit: delivered, unverified, unpaid, and on nobody's
    list because the page said the CCEO was responsible and the CCEO had
    already done their part.
    """

    def _ia_officer(self, email="ia@a.test"):
        return self._staff(email, "Verifier", EdifyRole.IMPACT_ASSESSMENT)[0]

    def _submitted_long_ago(self, days=21, *, priced=True):
        """Delivered, evidence in, and sitting in the verification queue.

        Priced by default so the assertions isolate the verification delay. An
        unpriced activity is a real and *separate* condition owned by the field
        team — IA cannot add a cost line — and the two must not be conflated.
        """
        from django.utils import timezone

        from apps.activities.models import ActivityScheduleCostLine

        self.activity.status = "awaiting_ia_verification"
        self.activity.evidence_status = "uploaded"
        self.activity.ia_verification_status = "pending"
        self.activity.submitted_to_ia_at = timezone.now() - timedelta(days=days)
        self.activity.cost_missing = False
        self.activity.save()
        if (
            priced
            and not ActivityScheduleCostLine.objects.filter(
                activity=self.activity
            ).exists()
        ):
            ActivityScheduleCostLine.objects.create(
                activity=self.activity,
                cost_setting_key="school_visit_transport",
                label="Transport",
                unit_cost=12_000,
                quantity=1,
                amount=12_000,
            )

    def _item(self):
        return oversight.build_item_by_reference(activity_id=self.activity.id)

    def test_a_stalled_verification_is_a_risk_owned_by_impact_assessment(self):
        self._submitted_long_ago()

        item = self._item()

        risk = next(r for r in item.risks if r["key"] == "ia_verification_overdue")
        self.assertEqual(risk["responsible_role"], "ImpactAssessment")
        self.assertEqual(risk["owner_name"], "Impact Assessment")

    def test_the_next_action_owner_follows_the_work_past_the_field(self):
        """Not the CCEO — they submitted it, and the queue has it now."""
        self._submitted_long_ago()

        item = self._item()

        self.assertEqual(item.next_action_owner_name, "Impact Assessment")
        self.assertIsNone(item.next_action_owner_id)

    def test_a_costing_gap_still_belongs_to_the_field_team(self):
        """Concurrent conditions keep their own owners.

        Impact Assessment cannot add a cost line, so an unpriced activity in
        their queue is two problems for two people — and the field-owned one
        must not be relabelled as theirs just because the record has moved on.
        """
        self._submitted_long_ago(priced=False)

        item = self._item()

        keys = {r["key"] for r in item.risks}
        self.assertIn("scheduled_without_cost", keys)
        self.assertIn("ia_verification_overdue", keys)
        costing = next(r for r in item.risks if r["key"] == "scheduled_without_cost")
        self.assertEqual(costing["owner_name"], "James")
        self.assertEqual(costing["responsible_role"], "")

    def test_delivered_work_awaiting_verification_is_not_called_overdue(self):
        """It asks the CCEO to do a thing they already did.

        Before the verification detectors existed, the only risk on a
        delivered-but-unverified activity was `activity_overdue` — "complete
        the activity or reschedule it", addressed to the person who completed
        it a fortnight ago.
        """
        self._submitted_long_ago()

        item = self._item()

        self.assertNotIn("activity_overdue", [r["key"] for r in item.risks])

    def test_a_fresh_submission_is_not_yet_a_risk(self):
        self._submitted_long_ago(days=1)

        item = self._item()

        self.assertNotIn("ia_verification_overdue", [r["key"] for r in item.risks])

    def test_a_verified_submission_stops_being_a_risk(self):
        self._submitted_long_ago()
        self.activity.ia_verification_status = "confirmed"
        self.activity.save()

        item = self._item()

        self.assertNotIn("ia_verification_overdue", [r["key"] for r in item.risks])

    def test_the_program_lead_can_ask_the_queue_and_no_team_action_is_opened(self):
        officer = self._ia_officer()
        self._submitted_long_ago()

        from apps.planning import oversight_actions

        notified = oversight_actions.send_risk_to_owner(
            sender=self.pl_user,
            item=self._item(),
            risk_key="ia_verification_overdue",
            note="Two schools are waiting on this",
        )

        self.assertEqual(notified, [officer.id])
        self.assertFalse(TeamAction.objects.exists())
        note = Notification.objects.get(
            recipient_id=officer.id,
            source_event_type="oversight_nudge.ia_verification_overdue",
        )
        self.assertIn("Two schools are waiting on this", note.body)

    def test_the_send_endpoint_routes_a_queue_risk_to_the_queue(self):
        officer = self._ia_officer()
        self._submitted_long_ago()

        response = self.as_pl().post(
            "/team-planning-oversight/send",
            {"risk": "ia_verification_overdue", "activity_id": self.activity.id},
            headers={"HX-Request": "true"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Notification.objects.filter(recipient_id=officer.id).exists())
        self.assertFalse(TeamAction.objects.exists())

    def test_unpaid_verified_work_is_a_risk_owned_by_the_accountant(self):
        accountant = self._staff("acc@a.test", "Cashier", EdifyRole.PROGRAM_ACCOUNTANT)[
            0
        ]
        self.activity.status = "ia_verified"
        self.activity.ia_verification_status = "confirmed"
        self.activity.payment_status = "pending"
        self.activity.cost_missing = False
        self.activity.save()

        item = self._item()
        risk = next(r for r in item.risks if r["key"] == "payment_overdue")
        self.assertEqual(risk["responsible_role"], "Accountant")

        from apps.planning import oversight_actions

        notified = oversight_actions.send_risk_to_owner(
            sender=self.pl_user, item=item, risk_key="payment_overdue"
        )
        self.assertEqual(notified, [accountant.id])

    def test_paid_work_is_not_reported_as_unpaid(self):
        self.activity.status = "ia_verified"
        self.activity.ia_verification_status = "confirmed"
        self.activity.payment_status = "paid"
        self.activity.cost_missing = False
        self.activity.save()

        item = self._item()

        self.assertNotIn("payment_overdue", [r["key"] for r in item.risks])
