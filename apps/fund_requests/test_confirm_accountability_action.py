"""The Accountant's accountability-review button on /disbursements.

The responsible user submitted accountability (spend, returned, variance,
NetSuite Code) on their disbursed advance; the Accountant reviews it from the
disbursements panel. Clearing routes through approve_accountability's hard
gates — IA verification + NetSuite Code — never a blind status write.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.rbac import EdifyRole
from apps.fund_requests import disbursement_dashboard_service as svc
from apps.fund_requests.models import (
    AdvanceRequest,
    AdvanceRequestStatus,
    WeeklyFundRequest,
    WeeklyFundRequestLine,
)
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()

FY = "2026"


class ConfirmAccountabilityActionTest(TestCase):
    def setUp(self):
        region = Region.objects.create(name="CA Region")
        district = District.objects.create(name="CA District", region=region)
        school = School.objects.create(
            school_id="CA-SCH", name="CA School", region=region, district=district
        )
        self.cceo = User.objects.create_user(
            email="cceo@ca.org",
            name="Cara CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        StaffProfile.objects.create(user=self.cceo, title="CCEO")
        self.accountant = User.objects.create_user(
            email="acct@ca.org",
            name="Alan Accountant",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
            password="x",
            is_active=True,
        )

        self.activity = Activity.objects.create(
            school=school,
            activity_type="school_visit",
            delivery_type="staff",
            status="completed",
            responsible_staff_id=self.cceo.id,
            fy=FY,
            quarter="Q3",
            scheduled_date=timezone.now(),
            salesforce_activity_id="SV-55667788",
        )
        self.line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            cost_setting_key="staff_visit_transport_primary",
            label="Transport",
            unit_cost=50_000,
            quantity=1,
            amount=50_000,
            responsible_user=self.cceo.id,
        )
        # Disbursed weekly request with the advance's accountability SUBMITTED.
        self.wfr = WeeklyFundRequest.objects.create(
            fy=FY,
            week_start_date=date(2026, 7, 6),
            week_end_date=date(2026, 7, 12),
            responsible_user=self.cceo.id,
            total_amount=50_000,
            status="disbursed",
            disbursed_amount=50_000,
            disbursed_at=timezone.now(),
        )
        WeeklyFundRequestLine.objects.create(
            weekly_fund_request=self.wfr,
            activity_budget_line=self.line,
            line_item_type="transport",
            description="Transport",
            quantity=1,
            unit_cost=50_000,
            total_cost=50_000,
        )
        self.adv = AdvanceRequest.objects.create(
            activity=self.activity,
            budget_line=self.line,
            responsible_user_id=self.cceo.id,
            fy=FY,
            quarter="Q3",
            amount=50_000,
            status=AdvanceRequestStatus.ACCOUNTABILITY_PENDING,
            disbursed_amount=50_000,
            accounted_amount=48_000,
            returned_amount=2_000,
            accountability_netsuite_id="EXP-2026-450",
            accountability_submitted_at=timezone.now(),
            last_note="Fuel cheaper than planned.",
        )
        self.client.force_login(self.accountant)

    def test_detail_payload_surfaces_submitted_accountability(self):
        ctx = svc.get_disbursement_dashboard(
            self.accountant, {"fy": FY, "month": 7, "item": f"wfr:{self.wfr.id}"}
        )
        sel = ctx["selected"]
        self.assertTrue(sel["can_confirm_accountability"])
        self.assertEqual(sel["status"], "Awaiting Reconciliation")
        acc = sel["accountability"]
        self.assertEqual(acc["netsuite_id"], "EXP-2026-450")
        self.assertEqual(acc["raw_accounted_total"], 48_000)
        self.assertEqual(acc["raw_returned_total"], 2_000)
        self.assertEqual(acc["variance_note"], "Fuel cheaper than planned.")

    def test_drawer_renders_submitted_code_without_input_field(self):
        resp = self.client.get(
            f"/finance/actions/drawer?action=confirm_accountability&request_id={self.wfr.id}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"EXP-2026-450", resp.content)
        self.assertIn(b"Fuel cheaper than planned.", resp.content)
        # The Accountant reviews — there is no NetSuite input to type into.
        self.assertNotIn(b'name="netsuite_id"', resp.content)

    def test_clear_blocked_without_ia_verification(self):
        resp = self.client.post(
            "/finance/actions/confirm_accountability",
            {"request_id": self.wfr.id},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"IA", resp.content)
        self.adv.refresh_from_db()
        self.wfr.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.ACCOUNTABILITY_PENDING)
        self.assertEqual(self.wfr.status, "disbursed")

    def test_clear_succeeds_after_ia_verification(self):
        self.activity.ia_verification_status = "confirmed"
        self.activity.save(update_fields=["ia_verification_status"])

        resp = self.client.post(
            "/finance/actions/confirm_accountability",
            {"request_id": self.wfr.id},
        )
        self.assertEqual(resp.status_code, 200)

        self.adv.refresh_from_db()
        self.wfr.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.ACCOUNTED)
        self.assertIsNotNone(self.adv.accountability_reviewed_at)
        # The code stays exactly what the responsible user submitted.
        self.assertEqual(self.adv.accountability_netsuite_id, "EXP-2026-450")
        self.assertEqual(self.wfr.status, "accounted")
        self.assertEqual(self.wfr.accountability_netsuite_id, "EXP-2026-450")
        self.assertEqual(self.wfr.accounted_amount, 48_000)
        self.assertEqual(self.wfr.returned_amount, 2_000)
        self.assertIsNotNone(self.wfr.accountability_reviewed_at)

    def test_nothing_pending_is_a_clean_400(self):
        self.adv.status = AdvanceRequestStatus.ACCOUNTED
        self.adv.save(update_fields=["status"])
        resp = self.client.post(
            "/finance/actions/confirm_accountability",
            {"request_id": self.wfr.id},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"No submitted accountability", resp.content)
