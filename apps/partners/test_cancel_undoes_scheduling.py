"""Cancelling a Partner's activity undoes the scheduling, as staff's own does.

Owner, 2026-10-08: "cancelled activities should undo the scheduling done and
should apply to both staff and partner cancelled activities."

Cancelling staff's own work already put the school back where it was. A
Partner's did not: the hand-over stayed "scheduled by the partner" on the
cancelled day, pointing at the cancelled activity, so the Partner was refused
when it tried to date the school again and the school was on no list.

What is pinned here: the Partner's date is undone and the hand-over waits
again, whoever cancelled; the Partner can date it afresh; work staff booked
for a Partner is closed with its booking; a withdrawal still decides the
hand-over itself; and the pages that count stop counting what was cancelled.
"""

from __future__ import annotations

import datetime
from unittest.mock import patch

from django.test import Client

from apps.accounts.models import User
from apps.activities import services as activity_services
from apps.activities.models import Activity
from apps.activity_catalogue.services import resolve_item_for_workflow_kind
from apps.audit.models import AuditLog
from apps.core.enums import ActivityType
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.partners import services as partner_services
from apps.partners.models import Partner, PartnerAssignment
from apps.planning.test_standard_support_scheduling import (
    StandardSupportBase,
    _at,
    _schedulable_date,
)

BACKEND = "apps.accounts.auth_backend.LockoutEnforcingModelBackend"
REASON = {"reason": "The school asked for another week."}


def _day(offset: int = 0) -> datetime.date:
    day = _schedulable_date(room=30)
    for _ in range(offset):
        day += datetime.timedelta(days=1)
        while day.weekday() == 6:
            day += datetime.timedelta(days=1)
    return day


class _Fixture(StandardSupportBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.partner_user = User.objects.create_user(
            email="cancel-partner@edify.org",
            name="Partner Field Officer",
            roles=[EdifyRole.PARTNER_FIELD_OFFICER.value],
            active_role=EdifyRole.PARTNER_FIELD_OFFICER.value,
            password="x",
            is_active=True,
        )
        cls.partner = Partner.objects.create(
            name="Cancelling Partner",
            user=cls.partner_user,
            active_status=True,
            contract_status="active",
            source="test",
        )
        cls.workflow = resolve_item_for_workflow_kind(ActivityType.IN_SCHOOL_TRAINING)
        cls.course = cls.item(cls, "SCHOOL_LEADERSHIP")

    def hand_over(self, school=None):
        return partner_services.create_assignment(
            school=school or self.school,
            partner=self.partner,
            assigning_staff_id=self.staff.id,
            monitoring_staff_id=self.staff.id,
            assignment_mode="specific_activity",
            catalogue_item=self.workflow,
            training_course=self.course,
            catalogue_snapshot=self.workflow.snapshot(),
            purpose=self.course.display_name,
            purpose_of_visit="in_school_training",
            expected_activity_type="in_school_training",
        )

    def partner_dates(self, handover, day=0) -> Activity:
        with self.captureOnCommitCallbacks(execute=True):
            result = activity_services.partner_schedule(
                handover.id,
                {
                    "scheduledDate": _at(_day(day)).isoformat(),
                    "deliveryContactName": "Partner Field Officer",
                },
                self.partner_user,
            )
        return Activity.objects.get(id=result["id"])

    def cancel(self, activity, actor, **extra):
        with self.captureOnCommitCallbacks(execute=True):
            return activity_services.cancel(activity.id, REASON, actor, **extra)

    def booked_by_staff(self, **fields) -> tuple[Activity, PartnerAssignment]:
        """Work created already carrying the Partner, with the hand-over the
        platform writes beside it (`_ensure_partner_handover`)."""
        day = _day(2)
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=str(get_operational_fy(day)),
            quarter="Q1",
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
            monitored_by_staff_id=self.staff.id,
            purpose_type="training_follow_up",
            **fields,
        )
        handover = PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            assigning_staff_id=self.staff.id,
            monitoring_staff_id=self.staff.id,
            purpose_of_visit="training_follow_up",
            expected_activity_type="school_visit",
            status=PartnerAssignment.STATUS_PARTNER_SCHEDULED,
            scheduled_activity=activity,
            scheduled_date=fields.get("planned_date"),
        )
        return activity, handover


class ThePartnersDateIsUndoneTest(_Fixture):
    def assert_waiting_again(self, handover, activity):
        handover.refresh_from_db()
        activity.refresh_from_db()
        self.assertEqual(activity.status, "cancelled")
        self.assertEqual(handover.status, PartnerAssignment.STATUS_PENDING_SCHEDULING)
        self.assertIsNone(handover.scheduled_date)
        self.assertIsNone(handover.scheduled_activity_id)
        self.assertFalse(handover.is_released)

    def test_the_partner_cancelling_puts_the_school_back_on_its_list(self):
        handover = self.hand_over()
        activity = self.partner_dates(handover)
        self.assertEqual(
            PartnerAssignment.objects.get(id=handover.id).status, "partner_scheduled"
        )

        result = self.cancel(activity, self.partner_user)

        self.assertEqual(result["partnerHandover"], "reopened")
        self.assert_waiting_again(handover, activity)

    def test_staff_cancelling_it_leaves_the_school_assigned_to_the_partner(self):
        handover = self.hand_over()
        activity = self.partner_dates(handover)

        result = self.cancel(activity, self.user)

        self.assertEqual(result["partnerHandover"], "reopened")
        self.assert_waiting_again(handover, activity)

    def test_the_partner_dates_the_school_again(self):
        """The refusal a Partner met: "This assignment is already scheduled."""
        handover = self.hand_over()
        first = self.partner_dates(handover)
        self.cancel(first, self.partner_user)

        second = self.partner_dates(handover, day=4)

        handover.refresh_from_db()
        self.assertNotEqual(second.id, first.id)
        self.assertEqual(handover.scheduled_activity_id, second.id)
        self.assertEqual(handover.status, "partner_scheduled")
        self.assertEqual(second.training_course_id, self.course.id)
        self.assertEqual(Activity.objects.get(id=first.id).status, "cancelled")

    def test_the_partner_is_told_the_school_is_still_theirs(self):
        handover = self.hand_over()
        activity = self.partner_dates(handover)

        with patch("apps.activities.services._notify_partner_schedule_change") as told:
            self.cancel(activity, self.user)

        body = told.call_args.args[3]
        self.assertIn("has been cancelled", body)
        self.assertIn("still assigned to you", body)

    def test_the_trail_says_what_was_undone(self):
        handover = self.hand_over()
        activity = self.partner_dates(handover)

        self.cancel(activity, self.partner_user)

        entry = AuditLog.objects.get(
            action="partner_assignment.scheduling_reopened", subject_id=handover.id
        )
        self.assertEqual(entry.payload["before"]["activityId"], activity.id)
        self.assertEqual(entry.payload["before"]["status"], "partner_scheduled")

    def test_a_deferred_activity_keeps_its_hand_over(self):
        """Deferred work comes back on a new day itself; nothing is undone."""
        handover = self.hand_over()
        activity = self.partner_dates(handover)

        with self.captureOnCommitCallbacks(execute=True):
            activity_services.defer(activity.id, REASON, self.partner_user)

        handover.refresh_from_db()
        self.assertEqual(handover.status, "partner_scheduled")
        self.assertEqual(handover.scheduled_activity_id, activity.id)


class WorkStaffBookedIsClosedWithItTest(_Fixture):
    def assert_closed(self, handover, result):
        handover.refresh_from_db()
        self.assertEqual(result["partnerHandover"], "closed")
        self.assertEqual(handover.status, PartnerAssignment.STATUS_RETURNED_TO_STAFF)
        self.assertIsNone(handover.scheduled_activity_id)
        # Nothing is left for anybody to decide.
        self.assertTrue(handover.has_left_partner)
        self.assertEqual(
            handover.resolution, PartnerAssignment.RESOLUTION_SUPPORT_CLOSED
        )
        self.assertIn("cancelled", handover.return_reason)

    def test_work_the_partner_never_dated_is_closed(self):
        activity, handover = self.booked_by_staff(status="assigned_to_partner")

        result = self.cancel(activity, self.user)

        self.assert_closed(handover, result)

    def test_a_booked_agency_is_closed_not_handed_a_school_to_date(self):
        day = _day(3)
        activity, handover = self.booked_by_staff(
            status="scheduled",
            executor_type="certified_partner_agency",
            partner_date_set_by="staff",
            planned_date=day,
            scheduled_date=_at(day),
        )

        result = self.cancel(activity, self.user)

        self.assert_closed(handover, result)

    def test_with_another_hand_over_already_waiting_this_one_is_closed(self):
        """One open hand-over per school and partner: it cannot wait beside
        the one that is already there."""
        handover = self.hand_over()
        activity = self.partner_dates(handover)
        other = self.hand_over()

        result = self.cancel(activity, self.partner_user)

        self.assert_closed(handover, result)
        other.refresh_from_db()
        self.assertEqual(other.status, PartnerAssignment.STATUS_PENDING_SCHEDULING)


class AWithdrawalStillDecidesItselfTest(_Fixture):
    def test_a_recall_does_not_reopen_the_hand_over(self):
        handover = self.hand_over()
        activity = self.partner_dates(handover)

        result = self.cancel(activity, self.user, already_authorised=True)

        handover.refresh_from_db()
        self.assertEqual(result["partnerHandover"], "")
        self.assertEqual(handover.status, "partner_scheduled")
        self.assertEqual(handover.scheduled_activity_id, activity.id)


class CancelledWorkStopsCountingTest(_Fixture):
    """The places a schedule-then-cancel crawl of every page found still
    counting or listing work that was called off (2026-10-08)."""

    def client_for(self, user):
        client = Client()
        client.force_login(user, backend=BACKEND)
        return client

    def cancelled_staff_visit(self) -> Activity:
        day = _day(1)
        return Activity.objects.create(
            activity_type="follow_up_visit",
            school=self.school,
            fy=str(get_operational_fy(day)),
            quarter="Q1",
            planned_date=day,
            scheduled_date=_at(day),
            responsible_staff_id=self.staff.id,
            status="cancelled",
        )

    def test_the_partner_s_pages_stop_listing_the_school_and_the_work(self):
        handover = self.hand_over()
        activity = self.partner_dates(handover)
        self.cancel(activity, self.partner_user)
        client = self.client_for(self.partner_user)

        schools = client.get("/partner/schools")
        self.assertEqual(schools.status_code, 200)
        self.assertEqual(schools.context["total"], 0)

        log = client.get("/partner/activities")
        self.assertEqual(log.context["total"], 0)
        # It waits for the Partner again, on the list it schedules from.
        self.assertEqual([a.id for a in log.context["assignments"]], [handover.id])
        asked = client.get("/partner/activities?status=cancelled")
        self.assertEqual([a.id for a in asked.context["activities"]], [activity.id])

    def test_the_closure_queue_does_not_wait_on_cancelled_work(self):
        cancelled = self.cancelled_staff_visit()

        response = self.client_for(self.user).get("/activities/closure")

        self.assertEqual(response.status_code, 200)
        listed = {
            activity.id
            for key in (
                "ready",
                "finance_pending",
                "accountability_pending",
                "analytics_pending",
                "blocked",
            )
            for activity in response.context[key]
        }
        self.assertNotIn(cancelled.id, listed)

    def test_cancelled_work_is_not_offered_for_a_debrief(self):
        cancelled = self.cancelled_staff_visit()
        live = Activity.objects.create(
            activity_type="follow_up_visit",
            school=self.school,
            fy=cancelled.fy,
            quarter="Q1",
            planned_date=cancelled.planned_date,
            scheduled_date=cancelled.scheduled_date,
            responsible_staff_id=self.staff.id,
            status="scheduled",
        )

        response = self.client_for(self.user).get(
            f"/debriefs/activity-options?fy={cancelled.fy}"
        )

        body = response.content.decode()
        self.assertIn(live.id, body)
        self.assertNotIn(cancelled.id, body)

    def test_the_year_s_total_leaves_cancelled_work_out(self):
        before = self.client_for(self.user).get("/fy").context["total_activities"]

        self.cancelled_staff_visit()

        after = self.client_for(self.user).get("/fy").context["total_activities"]
        self.assertEqual(after, before)

    def test_cancelled_work_is_not_returned_by_ia(self):
        from apps.targets.my_targets import (
            RETURNED_FOR_CORRECTION_STATUSES,
            RETURNED_STATUSES,
        )

        self.assertNotIn("cancelled", RETURNED_FOR_CORRECTION_STATUSES)
        self.assertNotIn("rejected", RETURNED_FOR_CORRECTION_STATUSES)
        # The ledger still reverses the credit of work that was called off.
        self.assertIn("cancelled", RETURNED_STATUSES)

    def test_cancelled_work_is_not_a_blocked_payment(self):
        from apps.fund_requests.finance_services import FinanceBlockedReasonService

        cancelled = self.cancelled_staff_visit()
        live = Activity.objects.create(
            activity_type="follow_up_visit",
            school=self.school,
            fy=cancelled.fy,
            quarter="Q1",
            planned_date=cancelled.planned_date,
            responsible_staff_id=self.staff.id,
            status="scheduled",
        )

        blocked = set(
            FinanceBlockedReasonService.blocked_activities().values_list(
                "id", flat=True
            )
        )

        self.assertIn(live.id, blocked)
        self.assertNotIn(cancelled.id, blocked)
