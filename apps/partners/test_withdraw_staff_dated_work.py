"""Work a staff member dated for a partner can be taken back (owner, 2026-10-05).

"A user scheduled for a partner and he cant withdraw the school from the
partner. It has only view in the action button. Can you add the withdraw
button to that too so that the user can withdraw the school from the partner."

Three things left such a row with View alone. Work a staff member created
for a partner on a day they picked sits at "assigned to partner", a state the
withdrawal read as settled. A Core School's row dropped Withdraw school as
soon as the work carried a date, whoever had put it there. And partner work
whose hand-over record was never written had no withdrawal to open.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest, ConflictError, Forbidden
from apps.core.rbac import EdifyRole
from apps.partners import withdrawal_service as svc
from apps.partners.dating_policy import partner_has_dated
from apps.partners.models import PartnerAssignment
from apps.partners.withdrawal_models import (
    PartnerAssignmentWithdrawal,
    PartnerHold,
    WithdrawalDisposition,
    WithdrawalKind,
    WithdrawalReason,
    WithdrawalState,
)
from apps.planning.test_partner_core_table import _CoreTableFixture
from apps.planning.test_partner_oversight import PartnerOversightFixture

EXPLANATION = "The school asked for its own officer to make this visit instead."


def payload(**over):
    base = {
        "reason_category": WithdrawalReason.INCORRECT_ASSIGNMENT,
        "partner_facing_reason": EXPLANATION,
        "disposition": WithdrawalDisposition.RETURN_TO_PLANNING,
    }
    base.update(over)
    return base


class _StaffDatedFixture(PartnerOversightFixture):
    def staff_dated(self, *, school=None, status="assigned_to_partner", cost=90_000):
        """The partner's activity on a day staff picked, still waiting for
        the partner, with no hand-over record pointing at it."""
        planned = date.today() + timedelta(days=6)
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=school or self.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=planned,
            planned_month=planned.month,
            scheduled_date=timezone.now() + timedelta(days=6),
            status=status,
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
            monitored_by_staff_id=self.cceo.id,
            purpose_type="training_follow_up",
            focus_intervention="financial_health",
        )
        if cost:
            ActivityScheduleCostLine.objects.create(
                activity=activity,
                cost_setting_key="partner_visit_lump_sum",
                label="Partner visit",
                unit_cost=cost,
                quantity=1,
                amount=cost,
            )
        return activity


class WhoseDateItIsTest(_StaffDatedFixture):
    def test_work_still_waiting_for_the_partner_is_not_the_partner_s_date(self):
        self.assertFalse(partner_has_dated(self.staff_dated()))

    def test_a_date_marked_as_staff_s_is_not_the_partner_s(self):
        activity = self.staff_dated(status="partner_scheduled")
        activity.partner_date_set_by = "staff"
        self.assertFalse(partner_has_dated(activity))

    def test_the_partner_s_own_scheduling_is(self):
        self.assertTrue(partner_has_dated(self.staff_dated(status="partner_scheduled")))

    def test_work_waiting_for_the_partner_can_be_taken_back(self):
        """It fell through to "blocked": the one record the partner had not
        touched was the one nobody could withdraw."""
        handover = self.assign()
        handover.scheduled_activity = self.staff_dated()
        self.assertEqual(svc.resolve_kind(handover), WithdrawalKind.RECALL_SCHEDULED)


class WorkWithNoHandoverRecordTest(_StaffDatedFixture):
    def test_the_preview_writes_nothing(self):
        activity = self.staff_dated()

        preview = svc.preview_activity(self.cceo_user, activity.id)

        self.assertEqual(preview["kind"], WithdrawalKind.RECALL_SCHEDULED)
        self.assertEqual(preview["kind_label"], svc.WITHDRAW_FROM_PARTNER)
        self.assertEqual(preview["assignment_id"], "")
        self.assertEqual(preview["activity_id"], activity.id)
        self.assertFalse(preview["partner_has_dated"])
        self.assertEqual(preview["planned_cost"], 90_000)
        self.assertEqual(preview["budget_removed"], 90_000)
        self.assertEqual(preview["school"], "School A")
        self.assertEqual(preview["partner"], "Partner X")
        self.assertFalse(PartnerAssignment.objects.exists())

    def test_withdrawing_cancels_the_work_and_records_the_handover(self):
        activity = self.staff_dated()

        withdrawal = svc.withdraw_activity(activity.id, payload(), self.cceo_user)

        activity.refresh_from_db()
        self.assertEqual(activity.status, "cancelled")
        handover = PartnerAssignment.objects.get()
        self.assertEqual(handover.scheduled_activity_id, activity.id)
        self.assertEqual(handover.partner_id, self.partner.id)
        self.assertEqual(handover.school_id, self.school.id)
        self.assertEqual(handover.status, PartnerAssignment.STATUS_RETURNED_TO_STAFF)
        self.assertEqual(handover.purpose_of_visit, "training_follow_up")
        self.assertEqual(handover.notes, svc.ADOPTED_NOTE)
        self.assertEqual(withdrawal.assignment_id, handover.id)
        self.assertEqual(withdrawal.linked_activity_id, activity.id)
        self.assertEqual(withdrawal.state, WithdrawalState.RETURNED_TO_PLANNING)
        self.assertEqual(withdrawal.original_planned_cost, 90_000)

    def test_the_partner_is_not_told_a_school_has_arrived(self):
        """The record is written for work the partner already holds: it is
        not a new assignment, and is not announced as one."""
        activity = self.staff_dated()

        svc.withdraw_activity(activity.id, payload(), self.cceo_user)

        self.assertFalse(AuditLog.objects.filter(action="partner.assigned").exists())
        self.assertTrue(
            AuditLog.objects.filter(action="partner.assignment_withdrawn").exists()
        )

    def test_a_partner_on_hold_can_still_have_work_taken_back(self):
        activity = self.staff_dated()
        PartnerHold.objects.create(
            partner=self.partner,
            reason_category=WithdrawalReason.CAPACITY,
            reason="Held while their capacity is reviewed.",
            requested_by=self.pl_user.id,
            effective_from=date.today(),
            review_on=date.today() + timedelta(days=30),
        )

        svc.withdraw_activity(activity.id, payload(), self.pl_user)

        activity.refresh_from_db()
        self.assertEqual(activity.status, "cancelled")

    def test_an_unfinished_form_leaves_no_handover_record(self):
        activity = self.staff_dated()

        with self.assertRaises(BadRequest):
            svc.withdraw_activity(
                activity.id, payload(partner_facing_reason="short"), self.cceo_user
            )

        self.assertFalse(PartnerAssignment.objects.exists())
        activity.refresh_from_db()
        self.assertEqual(activity.status, "assigned_to_partner")

    def test_a_refused_withdrawal_leaves_no_handover_record(self):
        activity = self.staff_dated()
        accountant, _profile = self._staff(
            "books@p.test", "Books", EdifyRole.PROGRAM_ACCOUNTANT
        )

        with self.assertRaises(Forbidden):
            svc.withdraw_activity(activity.id, payload(), accountant)

        self.assertFalse(PartnerAssignment.objects.exists())
        self.assertFalse(PartnerAssignmentWithdrawal.objects.exists())

    def test_paid_work_is_still_refused(self):
        activity = self.staff_dated(status="ia_verified")
        activity.payment_status = "paid"
        activity.save(update_fields=["payment_status"])

        with self.assertRaises(ConflictError):
            svc.withdraw_activity(activity.id, payload(), self.pl_user)

        self.assertFalse(PartnerAssignment.objects.exists())

    def test_work_that_has_a_handover_is_withdrawn_through_it(self):
        handover = self.assign()
        activity = self.schedule(handover)

        withdrawal = svc.withdraw_activity(activity.id, payload(), self.pl_user)

        self.assertEqual(withdrawal.assignment_id, handover.id)
        self.assertEqual(PartnerAssignment.objects.count(), 1)


class TheRowOffersItTest(_StaffDatedFixture):
    def page(self, user=None, work="visits"):
        self.client.force_login(user or self.cceo_user)
        response = self.client.get(
            f"/partner-oversight/?partner={self.partner.id}&work={work}"
        )
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def row(self, body, activity):
        start = body.index(f'data-partner-activity="{activity.id}"')
        return body[start : body.index('<tr id="partner-row-details-', start)]

    def test_the_row_offers_withdraw_from_partner(self):
        activity = self.staff_dated()

        row = self.row(self.page(), activity)

        self.assertIn("data-activity-withdraw", row)
        self.assertIn(f"/partner-oversight/withdraw?activity_id={activity.id}", row)
        self.assertIn(svc.WITHDRAW_FROM_PARTNER, row)
        self.assertIn("View activity", row)

    def test_finished_work_keeps_view_alone(self):
        activity = self.staff_dated(status="completed")
        activity.payment_status = "paid"
        activity.save(update_fields=["payment_status"])

        row = self.row(self.page(), activity)

        self.assertNotIn("data-activity-withdraw", row)
        self.assertIn("View activity", row)

    def test_the_drawer_is_the_withdrawal_s_own_and_the_cceo_decides(self):
        activity = self.staff_dated()
        self.client.force_login(self.cceo_user)

        response = self.client.get(
            f"/partner-oversight/withdraw?activity_id={activity.id}"
        )

        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn(f'name="activity_id" value="{activity.id}"', body)
        self.assertNotIn('name="assignment_id"', body)
        self.assertIn(svc.WITHDRAW_FROM_PARTNER, body)
        self.assertIn("data-staff-dated", body)
        self.assertNotIn("Send request to Program Lead", body)
        self.assertFalse(PartnerAssignment.objects.exists(), "opening writes nothing")

    def test_confirming_takes_the_work_back(self):
        activity = self.staff_dated()
        self.client.force_login(self.cceo_user)

        response = self.client.post(
            "/partner-oversight/withdraw/submit",
            {"activity_id": activity.id, **payload()},
        )

        self.assertLess(response.status_code, 400)
        activity.refresh_from_db()
        self.assertEqual(activity.status, "cancelled")
        self.assertEqual(
            PartnerAssignment.objects.get().status,
            PartnerAssignment.STATUS_RETURNED_TO_STAFF,
        )

    def test_another_team_s_work_does_not_open(self):
        activity = self.staff_dated()
        self.client.force_login(self.rival_cceo_user)

        response = self.client.get(
            f"/partner-oversight/withdraw?activity_id={activity.id}"
        )

        self.assertEqual(response.status_code, 404)

    def test_another_team_s_work_cannot_be_posted(self):
        activity = self.staff_dated()
        self.client.force_login(self.rival_cceo_user)

        self.client.post(
            "/partner-oversight/withdraw/submit",
            {"activity_id": activity.id, **payload()},
        )

        activity.refresh_from_db()
        self.assertEqual(activity.status, "assigned_to_partner")
        self.assertFalse(PartnerAssignment.objects.exists())

    def test_work_the_partner_dated_still_goes_to_the_program_lead(self):
        """A CCEO asks before taking back a day the partner chose."""
        activity = self.staff_dated(status="partner_scheduled")
        self.client.force_login(self.cceo_user)

        body = self.client.get(
            f"/partner-oversight/withdraw?activity_id={activity.id}"
        ).content.decode()

        self.assertIn("Send request to Program Lead", body)
        self.assertNotIn("data-staff-dated", body)


class TheSchoolRowOffersItTest(_StaffDatedFixture):
    """What a schedule drawer with "Partner agency" chosen wrote: a hand-over
    record and the partner's activity, on a day the staff member picked."""

    def scheduled_for_the_partner(self):
        handover = self.assign()
        activity = self.schedule(handover, status="assigned_to_partner")
        return handover, activity

    def row(self, user=None):
        handover, _activity = self.scheduled_for_the_partner()
        self.client.force_login(user or self.cceo_user)
        body = self.client.get(
            f"/partner-oversight/?partner={self.partner.id}&work=schools"
        ).content.decode()
        start = body.index("data-partner-school-columns")
        table = body[start : body.index("</table>", start)]
        start = table.index(f'data-assignment="{handover.id}"')
        return handover, table[start : table.index('<tr id="partner-row-details-')]

    def test_the_row_offers_withdraw_from_partner(self):
        handover, row = self.row()

        self.assertIn(f"/partner-oversight/withdraw?assignment_id={handover.id}", row)
        self.assertIn(svc.WITHDRAW_FROM_PARTNER, row)

    def test_the_cceo_withdraws_it_and_the_activity_is_cancelled(self):
        handover, activity = self.scheduled_for_the_partner()
        self.client.force_login(self.cceo_user)

        drawer = self.client.get(
            f"/partner-oversight/withdraw?assignment_id={handover.id}"
        ).content.decode()
        self.assertNotIn("Send request to Program Lead", drawer)
        self.assertIn(f'name="assignment_id" value="{handover.id}"', drawer)

        response = self.client.post(
            "/partner-oversight/withdraw/submit",
            {"assignment_id": handover.id, **payload()},
        )

        self.assertLess(response.status_code, 400)
        activity.refresh_from_db()
        handover.refresh_from_db()
        self.assertEqual(activity.status, "cancelled")
        self.assertEqual(handover.status, PartnerAssignment.STATUS_RETURNED_TO_STAFF)


class TheCoreRowOffersItTest(_CoreTableFixture):
    def test_a_day_staff_put_on_it_still_offers_withdraw_school(self):
        handover = self.core_handover()
        activity = self.schedule(handover)
        activity.partner_date_set_by = "staff"
        activity.save(update_fields=["partner_date_set_by"])

        row = self.core_row(self.page(self.cceo_user, work="core"), handover)

        self.assertIn("data-core-withdraw", row)

    def test_work_created_for_the_partner_and_not_scheduled_by_them_does_too(self):
        handover = self.core_handover()
        self.schedule(handover, status="assigned_to_partner")

        row = self.core_row(self.page(self.cceo_user, work="core"), handover)

        self.assertIn("data-core-withdraw", row)

    def test_the_cceo_withdraws_it_without_asking(self):
        handover = self.core_handover()
        activity = self.schedule(handover)
        activity.partner_date_set_by = "staff"
        activity.save(update_fields=["partner_date_set_by"])
        self.client.force_login(self.cceo_user)

        body = self.client.get(
            f"/partner-oversight/withdraw?assignment_id={handover.id}"
        ).content.decode()

        self.assertIn(svc.WITHDRAW_FROM_PARTNER, body)
        self.assertNotIn("Send request to Program Lead", body)

    def test_the_partner_s_own_date_still_withholds_it(self):
        handover = self.core_handover()
        self.schedule(handover)

        row = self.core_row(self.page(self.cceo_user, work="core"), handover)

        self.assertNotIn("data-core-withdraw", row)
