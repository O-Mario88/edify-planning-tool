"""Partner-facilitated group trainings (owner, 2026-09-26).

"For cluster group trainings assigned to a partner, the facilitation fee part
of the group training cost is for the partner." The owner chose: staff
complete, the partner facilitates; new assignments only; the fee paid
through the partner invoice flow.

So a group training a staff member assigns to a partner is the officer's
work with a facilitating partner, and only its facilitation fee is the
partner's money: stamped with the partner, kept out of every staff money
channel, and invoiced by the partner — 50% up front, the balance once the
training is verified.
"""

from __future__ import annotations

import tempfile
from datetime import date

from django.test import override_settings
from freezegun import freeze_time
from rest_framework.test import APITestCase

from apps.accounts.models import StaffSchoolAssignment
from apps.activities import services as activity_services
from apps.activities.facilitation import (
    FEE_LINE_TYPE,
    facilitates,
    partner_planned_total,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.rbac import EdifyRole
from apps.core.tests.test_partner_and_cluster_flows import PartnerAndClusterFlowTest
from apps.fund_requests.finance_models import PartnerPayment
from apps.fund_requests.finance_services import PartnerPaymentService
from apps.fund_requests.fundable import fundable_lines
from apps.fund_requests.models import AdvanceRequest
from apps.fund_requests.partner_invoices import invoice_basis
from apps.notifications.models import Notification
from apps.partners.models import Partner, PartnerAssignment

_flow = PartnerAndClusterFlowTest


@override_settings(EVIDENCE_STORAGE_DIR=tempfile.mkdtemp(prefix="edify-facilitated-"))
@freeze_time("2026-06-24")
class FacilitatedTrainingTest(APITestCase):
    # The cluster-flow fixture: catalogue, region, IA, a CCEO under a PL, and
    # the cluster-training rate card (facilitation fee 50,000 a day).
    setUp_flow = _flow.setUp
    _user = _flow._user
    _school = _flow._school
    _ssa = _flow._ssa
    _as = _flow._as
    _get = _flow._get
    _post = _flow._post

    def setUp(self):
        self.setUp_flow()
        self.partner_user = self._user(
            "facilitator@flow.test", EdifyRole.PARTNER_FIELD_OFFICER.value
        )
        self.partner = Partner.objects.create(
            name="Facilitating Partner Org",
            user=self.partner_user,
            active_status=True,
            contract_status="active",
            source="local_test_upload",
        )
        self.accountant = self._user(
            "acc@flow.test", EdifyRole.PROGRAM_ACCOUNTANT.value
        )
        school = self._school("FLOW-FAC-1")
        StaffSchoolAssignment.objects.create(staff=self.cceo_staff, school_id=school.id)
        self._ssa(school)
        self._as(self.cceo)
        self.cluster = self._post(
            "/api/clusters/from-school",
            {
                "schoolId": school.school_id,
                "name": "Fac Cluster",
                "clusterType": "mixed",
            },
            201,
        )
        self._post(
            "/api/clusters/assign",
            {"schoolId": school.school_id, "clusterId": self.cluster["id"]},
            200,
        )

    def _schedule(self, **extra) -> Activity:
        with self.captureOnCommitCallbacks(execute=True):
            scheduled = self._post(
                "/api/planning/schedule-cluster-training",
                {
                    "clusterId": self.cluster["id"],
                    "catalogueItemId": "GOVERNMENT_STATUTORY_REQUIREMENTS",
                    "scheduledDate": "2026-07-20T09:00:00+03:00",
                    "plannedMonth": 7,
                    "expectedParticipants": 12,
                    "focusIntervention": "government_requirement",
                    **extra,
                },
                201,
            )
        return Activity.objects.get(id=scheduled["id"])

    def _facilitated(self) -> Activity:
        return self._schedule(assignedPartnerId=self.partner.id, deliveryType="partner")

    def _fee_line(self, activity) -> ActivityScheduleCostLine:
        return ActivityScheduleCostLine.objects.get(
            activity=activity, line_item_type=FEE_LINE_TYPE
        )

    # -- who owns it --------------------------------------------------------

    def test_a_training_assigned_to_a_partner_is_the_officers_work(self):
        activity = self._facilitated()
        self.assertEqual(activity.delivery_type, "staff")
        self.assertEqual(activity.executor_type, "staff")
        self.assertEqual(activity.facilitating_partner_id, self.partner.id)
        self.assertIsNone(activity.assigned_partner_id)
        self.assertEqual(activity.responsible_staff_id, self.cceo_staff.id)
        self.assertEqual(activity.status, "scheduled")
        # No partner handover: the partner does not schedule or complete it.
        self.assertFalse(
            PartnerAssignment.objects.filter(scheduled_activity=activity).exists()
        )

    def test_the_partner_is_told_it_is_facilitating(self):
        self._facilitated()
        notice = Notification.objects.get(
            recipient_id=self.partner_user.id,
            source_event_type="partner_facilitation_booked",
        )
        self.assertIn("Fac Cluster", notice.body)
        self.assertEqual(notice.target_route, "/partner/my-plan")

    def test_only_group_trainings_are_facilitated(self):
        self.assertTrue(facilitates("cluster_training"))
        for other in ("cluster_meeting", "school_visit", "in_school_training"):
            with self.subTest(activity_type=other):
                self.assertFalse(facilitates(other))

    def test_a_partner_scheduling_its_own_work_keeps_partner_delivery(self):
        chosen = activity_services._facilitating_partner_for(
            {"assignedPartnerId": self.partner.id, "deliveryType": "partner"},
            self.partner_user,
            activity_type="cluster_training",
        )
        self.assertIsNone(chosen)

    def test_an_inactive_partner_cannot_facilitate(self):
        self.partner.active_status = False
        self.partner.save(update_fields=["active_status"])
        response = self.client.post(
            "/api/planning/schedule-cluster-training",
            {
                "clusterId": self.cluster["id"],
                "catalogueItemId": "GOVERNMENT_STATUTORY_REQUIREMENTS",
                "scheduledDate": "2026-07-20T09:00:00+03:00",
                "plannedMonth": 7,
                "expectedParticipants": 12,
                "focusIntervention": "government_requirement",
                "assignedPartnerId": self.partner.id,
                "deliveryType": "partner",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_moving_a_staff_training_onto_a_partner_makes_it_the_facilitator(self):
        activity = self._schedule()
        self.assertIsNone(activity.facilitating_partner_id)
        self._post(
            f"/api/activities/{activity.id}/reassign",
            {"deliveryType": "partner", "assignedPartnerId": self.partner.id},
            200,
        )
        activity.refresh_from_db()
        self.assertEqual(activity.delivery_type, "staff")
        self.assertEqual(activity.facilitating_partner_id, self.partner.id)
        self.assertEqual(self._fee_line(activity).partner_id, self.partner.id)

    # -- whose money --------------------------------------------------------

    def test_only_the_facilitation_fee_is_the_partners(self):
        activity = self._facilitated()
        lines = ActivityScheduleCostLine.objects.filter(activity=activity)
        fee = self._fee_line(activity)
        self.assertEqual(fee.partner_id, self.partner.id)
        self.assertGreater(fee.amount, 0)
        others = lines.exclude(id=fee.id)
        self.assertTrue(others.exists())
        self.assertFalse(others.filter(partner_id__isnull=False).exists())
        self.assertEqual(partner_planned_total(activity), fee.amount)

    def test_the_fee_never_reaches_a_staff_money_channel(self):
        activity = self._facilitated()
        fee = self._fee_line(activity)
        staff = fundable_lines(
            ActivityScheduleCostLine.objects.filter(activity=activity)
        )
        self.assertNotIn(fee.id, set(staff.values_list("id", flat=True)))
        self.assertTrue(staff.exists())
        self.assertFalse(AdvanceRequest.objects.filter(budget_line=fee).exists())

    def test_the_partner_invoices_the_fee_and_is_paid_it_in_two_instalments(self):
        activity = self._facilitated()
        fee = self._fee_line(activity).amount

        advance = invoice_basis(self.partner_user, "month", date(2026, 7, 1), "advance")
        [item] = [i for i in advance["items"] if i["activity"].id == activity.id]
        self.assertEqual(item["planned"], fee)
        self.assertEqual(item["payable"], fee // 2)
        self.assertEqual(item["category"], "Training Facilitation Fee")

        PartnerPaymentService.pay_partner(
            activity,
            self.partner.name,
            fee // 2,
            "bank",
            "REF-ADV",
            self.accountant.id,
            payment_type=PartnerPayment.TYPE_ADVANCE,
            notify_partner=False,
        )
        activity.refresh_from_db()
        # The training's own payment state is the officer's.
        self.assertNotIn(activity.payment_status, ("disbursed", "paid"))

        # The balance waits for the Programme Lead's verification.
        clearance = invoice_basis(
            self.partner_user, "month", date(2026, 7, 1), "clearance"
        )
        self.assertFalse(
            [i for i in clearance["items"] if i["activity"].id == activity.id]
        )
        activity.status = "ia_verified"
        activity.save(update_fields=["status"])
        clearance = invoice_basis(
            self.partner_user, "month", date(2026, 7, 1), "clearance"
        )
        [item] = [i for i in clearance["items"] if i["activity"].id == activity.id]
        self.assertEqual(item["payable"], fee - fee // 2)

    def test_the_officers_advance_does_not_block_the_partners_fee(self):
        activity = self._facilitated()
        fee = self._fee_line(activity).amount
        staff_line = (
            ActivityScheduleCostLine.objects.filter(activity=activity)
            .exclude(line_item_type=FEE_LINE_TYPE)
            .exclude(amount=0)
            .first()
        )
        AdvanceRequest.objects.update_or_create(
            activity=activity,
            budget_line=staff_line,
            defaults={
                "amount": staff_line.amount,
                "status": "disbursed",
                "responsible_user_id": self.cceo_staff.id,
                "fy": activity.fy or "2026",
                "quarter": activity.quarter or "Q4",
            },
        )
        payment = PartnerPaymentService.pay_partner(
            activity,
            self.partner.name,
            fee // 2,
            "bank",
            "REF-ADV-2",
            self.accountant.id,
            payment_type=PartnerPayment.TYPE_ADVANCE,
            notify_partner=False,
        )
        self.assertEqual(payment.amount_paid, fee // 2)
