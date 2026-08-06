"""The unassigned-action queue: send, dedupe, drain, auto-resolve, return.

Each test names a way the old behaviour failed. The old "Send to <staff>" wrote
one Notification and left the school on the card, so the queue never drained,
two people could send the same thing, nothing carried a due date, and nothing
ever closed. These are those failures, executed.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.planning.action_models import ActionState, TeamAction
from apps.planning.action_service import (
    ActionError,
    ResponsibleActorService,
    acknowledge,
    cancel,
    escalate,
    mark_overdue_actions,
    resolve_due_actions,
    resolve_manually,
    return_to_sender,
    send_action,
)
from apps.planning.urgent_attention import (
    condition_key,
    monthly_urgent_schools,
    resolve_urgent_issue,
)
from apps.schools.models import School
from apps.ssa.models import SsaRecord


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


class ActionFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="AQ Region")
        cls.district = District.objects.create(name="AQ District", region=region)
        cls.fy = "2026"

        cls.cceo = _user("aq-cceo@t.org", EdifyRole.CCEO.value)
        cls.cceo_sp = StaffProfile.objects.create(user=cls.cceo, country="Uganda")
        cls.pl = _user("aq-pl@t.org", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        cls.pl_sp = StaffProfile.objects.create(user=cls.pl, country="Uganda")
        cls.cd = _user("aq-cd@t.org", EdifyRole.COUNTRY_DIRECTOR.value)
        cls.cd_sp = StaffProfile.objects.create(user=cls.cd, country="Uganda")

        StaffSupervisorAssignment.objects.create(
            supervisee=cls.cceo_sp, supervisor=cls.pl_sp
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.pl_sp, supervisor=cls.cd_sp
        )

    def _school(self, sid, *, assign_to=None):
        school = School.objects.create(
            name=f"AQ {sid}",
            school_id=sid,
            region_id=self.district.region_id,
            district_id=self.district.id,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(
            staff=assign_to or self.cceo_sp, school_id=school.id
        )
        return school

    def _plan(self, school, activity_type="school_visit", status="scheduled", day=15):
        return Activity.objects.create(
            school_id=school.id,
            activity_type=activity_type,
            status=status,
            responsible_staff_id=self.cceo_sp.id,
            fy=self.fy,
            quarter="Q4",
            planned_date=timezone.make_aware(timezone.datetime(2026, 7, day, 9, 0)),
        )

    def _issue(self, school, acts=None):
        return resolve_urgent_issue(school, self.fy, acts or [])

    def _send(self, school, **kw):
        return send_action(
            sender=self.pl,
            school=school,
            issue=self._issue(school),
            fy=self.fy,
            month_of_fy=7,
            **kw,
        )


class ConditionKeyTests(ActionFixture):
    def test_key_identifies_the_condition_not_the_assignee(self):
        """Reassigning a school must not create a second identity for the same
        problem — that is exactly how a duplicate action would slip through."""
        school = self._school("AQ-K1")
        before = self._issue(school)["condition_key"]

        other = StaffProfile.objects.create(
            user=_user("aq-cceo2@t.org", EdifyRole.CCEO.value), country="Uganda"
        )
        StaffSchoolAssignment.objects.filter(school_id=school.id).delete()
        StaffSchoolAssignment.objects.create(staff=other, school_id=school.id)

        self.assertEqual(self._issue(school)["condition_key"], before)

    def test_two_different_issues_at_one_school_are_two_conditions(self):
        school = self._school("AQ-K2")
        self.assertNotEqual(
            condition_key(school.id, "no_ssa", self.fy),
            condition_key(school.id, "no_visit", self.fy),
        )

    def test_same_issue_in_a_new_fy_is_a_new_condition(self):
        school = self._school("AQ-K3")
        self.assertNotEqual(
            condition_key(school.id, "no_ssa", "2026"),
            condition_key(school.id, "no_ssa", "2027"),
        )

    def test_resolver_stamps_every_row_with_its_key(self):
        school = self._school("AQ-K4")
        issue = self._issue(school, [self._plan(school)])
        self.assertEqual(
            issue["condition_key"], condition_key(school.id, "no_ssa", self.fy)
        )


class ResponsibleActorTests(ActionFixture):
    def test_resolves_the_assigned_staff_member(self):
        school = self._school("AQ-R1")
        staff, role = ResponsibleActorService.for_school(school.id)
        self.assertEqual(staff.id, self.cceo_sp.id)
        self.assertEqual(role, EdifyRole.CCEO.value)

    def test_unassigned_school_has_no_responsible_actor(self):
        school = School.objects.create(
            name="AQ orphan",
            school_id="AQ-R2",
            region_id=self.district.region_id,
            district_id=self.district.id,
            school_type="client",
        )
        staff, _ = ResponsibleActorService.for_school(school.id)
        self.assertIsNone(staff)

    def test_send_refuses_rather_than_inventing_a_recipient(self):
        """An accountability record against nobody is worse than no record."""
        school = School.objects.create(
            name="AQ orphan 2",
            school_id="AQ-R3",
            region_id=self.district.region_id,
            district_id=self.district.id,
            school_type="client",
        )
        with self.assertRaises(ActionError) as ctx:
            self._send(school)
        self.assertIn("no assigned staff member", str(ctx.exception))
        self.assertEqual(TeamAction.objects.count(), 0)


class SendTests(ActionFixture):
    def test_send_creates_one_action_with_owner_route_and_due_date(self):
        school = self._school("AQ-S1")
        action = self._send(school)

        self.assertEqual(action.recipient_id, self.cceo.id)
        self.assertEqual(action.sender_id, self.pl.id)
        self.assertEqual(action.issue_type, "no_ssa")
        self.assertEqual(action.state, ActionState.OPEN)
        self.assertIsNotNone(action.due_date)
        self.assertGreater(action.due_date, timezone.localdate())
        # Straight to the work, not to a dashboard to search from.
        self.assertIn(school.school_id, action.workflow_route)

    def test_send_notifies_the_recipient_with_the_route(self):
        school = self._school("AQ-S2")
        action = self._send(school)
        note = Notification.objects.get(
            recipient_id=self.cceo.id, source_event_type="school_action_assigned"
        )
        self.assertEqual(note.context_id, action.id)
        self.assertTrue(note.action_required)
        self.assertEqual(note.target_route, action.workflow_route)
        self.assertEqual(note.status, "unread")

    def test_send_creates_a_contextual_message_thread(self):
        from apps.messaging.models import Message

        school = self._school("AQ-S3")
        self._send(school, note="Please prioritise, the head teacher is expecting you.")
        msg = Message.objects.filter(context_type="School", context_id=school.id).last()
        self.assertIsNotNone(msg)
        self.assertIn("head teacher", msg.body)

    def test_send_writes_an_audit_event(self):
        from apps.audit.models import AuditLog

        school = self._school("AQ-S4")
        action = self._send(school)
        self.assertTrue(
            AuditLog.objects.filter(
                action="school_action.sent", subject_id=action.id
            ).exists()
        )

    def test_critical_gets_a_shorter_due_date_than_high(self):
        crit = self._send(self._school("AQ-S5"))
        school = self._school("AQ-S6")
        SsaRecord.objects.create(
            school=school,
            fy=self.fy,
            date_of_ssa=timezone.now(),
            average_score=4.0,
            verification_status="confirmed",
        )
        Activity.objects.create(
            school_id=school.id,
            activity_type="training",
            status="ia_verified",
            responsible_staff_id=self.cceo_sp.id,
            fy=self.fy,
            quarter="Q4",
        )
        high = self._send(school)
        self.assertEqual(high.issue_type, "no_visit")
        self.assertLess(crit.due_date, high.due_date)

    def test_unknown_issue_type_is_refused_not_silently_routed_nowhere(self):
        school = self._school("AQ-S7")
        with self.assertRaises(ActionError):
            send_action(
                sender=self.pl,
                school=school,
                issue={"key": "invented", "condition_key": "x", "severity": "high"},
                fy=self.fy,
            )


class DeduplicationTests(ActionFixture):
    def test_second_send_of_the_same_condition_is_refused(self):
        school = self._school("AQ-D1")
        first = self._send(school)
        with self.assertRaises(ActionError) as ctx:
            self._send(school)
        self.assertIn("Already sent", str(ctx.exception))
        self.assertEqual(
            TeamAction.objects.filter(condition_key=first.condition_key).count(), 1
        )

    def test_the_database_refuses_a_duplicate_even_without_the_pre_check(self):
        """The pre-check loses a genuine race; the partial unique index is what
        actually guarantees one owner per condition."""
        from django.db import IntegrityError, transaction

        school = self._school("AQ-D2")
        first = self._send(school)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeamAction.objects.create(
                condition_key=first.condition_key,
                issue_type="no_ssa",
                school_id=school.id,
                fy=self.fy,
                sender_id=self.pl.id,
                sender_role="ProgramLead",
                recipient_id=self.cceo.id,
                recipient_role="CCEO",
                requested_action="x",
                workflow_route="/x",
                detected_at=timezone.now(),
            )

    def test_a_closed_condition_may_be_sent_again(self):
        """Recurrence is normal. The constraint must not make a school that
        regressed permanently unassignable."""
        school = self._school("AQ-D3")
        first = self._send(school)
        first.state = ActionState.RESOLVED
        first.resolved_at = timezone.now()
        first.save()

        second = self._send(school)
        self.assertNotEqual(second.id, first.id)
        self.assertEqual(second.supersedes_id, first.id)


class QueueDrainTests(ActionFixture):
    """The whole point: an assigned school leaves the unassigned card."""

    def _card(self):
        return monthly_urgent_schools(self.cceo, fy=self.fy, month=7)

    def test_school_appears_while_unassigned(self):
        school = self._school("AQ-Q1")
        self._plan(school)
        self.assertIn(school.id, [r["school_id"] for r in self._card()["rows"]])

    def test_school_leaves_the_card_once_sent(self):
        school = self._school("AQ-Q2")
        self._plan(school)
        self._send(school)
        card = self._card()
        self.assertNotIn(school.id, [r["school_id"] for r in card["rows"]])
        self.assertEqual(card["assigned_count"], 1)

    def test_the_count_matches_what_the_card_shows(self):
        """A total that still counted assigned schools would tell the user the
        queue had not moved."""
        a, b = self._school("AQ-Q3"), self._school("AQ-Q4")
        self._plan(a)
        self._plan(b)
        self.assertEqual(self._card()["total_schools"], 2)
        self._send(a)
        self.assertEqual(self._card()["total_schools"], 1)

    def test_a_returned_school_comes_back_to_the_queue(self):
        school = self._school("AQ-Q5")
        self._plan(school)
        action = self._send(school)
        return_to_sender(action, self.cceo, "This school is not in my portfolio.")
        self.assertIn(school.id, [r["school_id"] for r in self._card()["rows"]])

    def test_a_cancelled_action_returns_the_school_to_the_queue(self):
        school = self._school("AQ-Q6")
        self._plan(school)
        action = self._send(school)
        cancel(action, self.pl, "Sent in error.")
        self.assertIn(school.id, [r["school_id"] for r in self._card()["rows"]])

    def test_an_overdue_school_stays_off_the_unassigned_queue(self):
        """Overdue means someone owns it and is late — not that it is
        unassigned. Putting it back would erase that history."""
        school = self._school("AQ-Q7")
        self._plan(school)
        action = self._send(school)
        action.due_date = timezone.localdate() - timedelta(days=2)
        action.save()
        mark_overdue_actions()
        self.assertNotIn(school.id, [r["school_id"] for r in self._card()["rows"]])


class AutoResolutionTests(ActionFixture):
    def test_no_ssa_action_closes_when_a_confirmed_ssa_appears(self):
        school = self._school("AQ-A1")
        action = self._send(school)

        self.assertEqual(resolve_due_actions()["resolved"], 0)

        SsaRecord.objects.create(
            school=school,
            fy=self.fy,
            date_of_ssa=timezone.now(),
            average_score=4.0,
            verification_status="confirmed",
        )
        self.assertEqual(resolve_due_actions()["resolved"], 1)

        action.refresh_from_db()
        self.assertEqual(action.state, ActionState.RESOLVED)
        self.assertTrue(action.resolved_by_system)

    def test_an_unverified_ssa_does_not_close_the_action(self):
        """The condition is a *confirmed* SSA. Closing on a draft would drain
        the queue without the work having been assured."""
        school = self._school("AQ-A2")
        self._send(school)
        SsaRecord.objects.create(
            school=school,
            fy=self.fy,
            date_of_ssa=timezone.now(),
            average_score=4.0,
            verification_status="pending",
        )
        self.assertEqual(resolve_due_actions()["resolved"], 0)

    def test_an_ssa_in_a_different_fy_does_not_close_the_action(self):
        school = self._school("AQ-A3")
        self._send(school)
        SsaRecord.objects.create(
            school=school,
            fy="2025",
            date_of_ssa=timezone.now(),
            average_score=4.0,
            verification_status="confirmed",
        )
        self.assertEqual(resolve_due_actions()["resolved"], 0)

    def test_no_visit_action_closes_only_on_a_verified_visit(self):
        school = self._school("AQ-A4")
        SsaRecord.objects.create(
            school=school,
            fy=self.fy,
            date_of_ssa=timezone.now(),
            average_score=4.0,
            verification_status="confirmed",
        )
        Activity.objects.create(
            school_id=school.id,
            activity_type="training",
            status="ia_verified",
            responsible_staff_id=self.cceo_sp.id,
            fy=self.fy,
            quarter="Q4",
        )
        action = self._send(school)
        self.assertEqual(action.issue_type, "no_visit")

        visit = Activity.objects.create(
            school_id=school.id,
            activity_type="school_visit",
            status="scheduled",
            responsible_staff_id=self.cceo_sp.id,
            fy=self.fy,
            quarter="Q4",
        )
        self.assertEqual(resolve_due_actions()["resolved"], 0, "scheduled is not done")

        visit.status = "ia_verified"
        visit.save()
        self.assertEqual(resolve_due_actions()["resolved"], 1)

    def test_resolution_notifies_the_sender(self):
        school = self._school("AQ-A5")
        self._send(school)
        SsaRecord.objects.create(
            school=school,
            fy=self.fy,
            date_of_ssa=timezone.now(),
            average_score=4.0,
            verification_status="confirmed",
        )
        resolve_due_actions()
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.pl.id, source_event_type="school_action_resolved"
            ).exists()
        )

    def test_the_sweep_is_idempotent(self):
        school = self._school("AQ-A6")
        self._send(school)
        SsaRecord.objects.create(
            school=school,
            fy=self.fy,
            date_of_ssa=timezone.now(),
            average_score=4.0,
            verification_status="confirmed",
        )
        self.assertEqual(resolve_due_actions()["resolved"], 1)
        self.assertEqual(resolve_due_actions()["resolved"], 0)

    def test_a_resolved_condition_never_returns_to_the_unassigned_card(self):
        """The *condition* is fixed and must not be re-queued.

        The school itself may well come back — under whatever it is missing
        next. That is the card doing its job, not the resolved action leaking
        back, so this asserts on the condition key rather than the school.
        """
        school = self._school("AQ-A7")
        self._plan(school)
        action = self._send(school)
        resolved_key = action.condition_key

        SsaRecord.objects.create(
            school=school,
            fy=self.fy,
            date_of_ssa=timezone.now(),
            average_score=4.0,
            verification_status="confirmed",
        )
        resolve_due_actions()

        card = monthly_urgent_schools(self.cceo, fy=self.fy, month=7)
        keys = [r["condition_key"] for r in card["rows"]]
        self.assertNotIn(resolved_key, keys)

    def test_the_next_problem_surfaces_once_the_first_is_fixed(self):
        """Fixing the SSA does not make a school with no completed support
        healthy — it makes the next gap visible, which is the point."""
        school = self._school("AQ-A8")
        self._plan(school)
        first = self._send(school)
        self.assertEqual(first.issue_type, "no_ssa")

        SsaRecord.objects.create(
            school=school,
            fy=self.fy,
            date_of_ssa=timezone.now(),
            average_score=4.0,
            verification_status="confirmed",
        )
        resolve_due_actions()

        card = monthly_urgent_schools(self.cceo, fy=self.fy, month=7)
        row = next(r for r in card["rows"] if r["school_id"] == school.id)
        self.assertEqual(row["key"], "no_visit_or_training")
        self.assertNotEqual(row["condition_key"], first.condition_key)

        # And it is assignable again, because it is a different condition.
        second = self._send(school)
        self.assertEqual(second.issue_type, "no_visit_or_training")


class ManualResolutionTests(ActionFixture):
    def test_a_system_verifiable_condition_cannot_be_closed_by_hand(self):
        """Otherwise the queue can be cleared without a school being helped."""
        school = self._school("AQ-M1")
        action = self._send(school)
        with self.assertRaises(ActionError) as ctx:
            resolve_manually(action, self.cceo, "Done, trust me.")
        self.assertIn("cannot be marked resolved by hand", str(ctx.exception))
        action.refresh_from_db()
        self.assertEqual(action.state, ActionState.OPEN)

    def test_acknowledging_does_not_resolve_anything(self):
        school = self._school("AQ-M2")
        action = self._send(school)
        acknowledge(action, self.cceo)
        action.refresh_from_db()
        self.assertEqual(action.state, ActionState.ACKNOWLEDGED)
        self.assertTrue(action.is_active)


class OverdueAndEscalationTests(ActionFixture):
    def test_past_due_actions_become_overdue_and_both_parties_hear(self):
        school = self._school("AQ-O1")
        action = self._send(school)
        action.due_date = timezone.localdate() - timedelta(days=1)
        action.save()

        self.assertEqual(mark_overdue_actions()["overdue"], 1)
        action.refresh_from_db()
        self.assertEqual(action.state, ActionState.OVERDUE)
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.cceo.id, source_event_type="school_action_overdue"
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.pl.id,
                source_event_type="school_action_overdue_sender",
            ).exists()
        )

    def test_an_action_due_today_is_not_yet_overdue(self):
        school = self._school("AQ-O2")
        action = self._send(school)
        action.due_date = timezone.localdate()
        action.save()
        self.assertEqual(mark_overdue_actions()["overdue"], 0)

    def test_escalation_goes_up_the_senders_reporting_line(self):
        school = self._school("AQ-O3")
        action = self._send(school)
        escalate(action, self.pl)
        action.refresh_from_db()
        self.assertEqual(action.escalated_to_id, self.cd.id)
        self.assertEqual(action.state, ActionState.ESCALATED)

    def test_escalation_does_not_move_ownership(self):
        school = self._school("AQ-O4")
        action = self._send(school)
        escalate(action, self.pl)
        action.refresh_from_db()
        self.assertEqual(action.recipient_id, self.cceo.id)


class ReturnAndCancelTests(ActionFixture):
    def test_returning_requires_a_reason(self):
        school = self._school("AQ-T1")
        action = self._send(school)
        with self.assertRaises(ActionError):
            return_to_sender(action, self.cceo, "   ")

    def test_returning_tells_the_sender_why(self):
        school = self._school("AQ-T2")
        action = self._send(school)
        return_to_sender(action, self.cceo, "Wrong school — not mine.")
        note = Notification.objects.get(
            recipient_id=self.pl.id, source_event_type="school_action_returned"
        )
        self.assertIn("Wrong school", note.body)

    def test_only_the_sender_may_cancel(self):
        school = self._school("AQ-T3")
        action = self._send(school)
        with self.assertRaises(ActionError) as ctx:
            cancel(action, self.cceo, "Not doing it.")
        self.assertIn("Only the person who sent", str(ctx.exception))

    def test_history_survives_a_return(self):
        """The record must remain queryable — that is the difference between an
        action and a notification."""
        school = self._school("AQ-T4")
        action = self._send(school)
        return_to_sender(action, self.cceo, "Not my portfolio.")
        stored = TeamAction.objects.get(id=action.id)
        self.assertEqual(stored.state, ActionState.RETURNED)
        self.assertEqual(stored.returned_reason, "Not my portfolio.")
        self.assertEqual(stored.recipient_id, self.cceo.id)
