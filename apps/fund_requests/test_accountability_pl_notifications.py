"""The Program Lead's accountability decision reaches the person it is about.

When the PL approves or returns an advance accountability (or a self-funded
reimbursement claim), the responsible user is told — as an in-app notification
that opens the weekly request the advance belongs to, and as an SMS when they
have a phone on file. These pin the event names the rest of the platform
keys on (`accountability_pl_approved` / `accountability_pl_returned`), the
route, and the off-device copy.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import resolve
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.rbac import EdifyRole
from apps.core.sms import SmsService
from apps.fund_requests import advance_service
from apps.fund_requests.models import (
    AdvanceRequest,
    AdvanceRequestStatus,
    WeeklyFundRequest,
    WeeklyFundRequestLine,
)
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.notifications.services import SMS_MAX_LENGTH
from apps.schools.models import School

User = get_user_model()

FY = "2026"
PHONE = "+256700000042"


class AccountabilityPlNotificationsTest(TestCase):
    def setUp(self):
        region = Region.objects.create(name="PLN Region")
        district = District.objects.create(name="PLN District", region=region)
        school = School.objects.create(
            school_id="PLN-SCH", name="PLN School", region=region, district=district
        )

        def _user(email, name, role, phone=None):
            u = User.objects.create_user(
                email=email,
                name=name,
                roles=[role],
                active_role=role,
                password="x",
                is_active=True,
                phone=phone,
            )
            sp = StaffProfile.objects.create(user=u, title=role)
            return u, sp

        self.cceo, self.cceo_sp = _user(
            "cceo@pln.org", "Ana CCEO", EdifyRole.CCEO.value, phone=PHONE
        )
        self.pl, self.pl_sp = _user(
            "pl@pln.org", "Peter PL", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo_sp
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
            ia_verification_status="confirmed",
        )
        self.line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            cost_setting_key="staff_visit_transport_primary",
            label="Transport",
            unit_cost=100_000,
            quantity=1,
            amount=100_000,
            responsible_user=self.cceo.id,
        )
        week_start = date(2026, 7, 6)
        self.wfr = WeeklyFundRequest.objects.create(
            fy=FY,
            week_start_date=week_start,
            week_end_date=week_start + timedelta(days=6),
            responsible_user=self.cceo.id,
            total_amount=100_000,
            status="disbursed",
        )
        WeeklyFundRequestLine.objects.create(
            weekly_fund_request=self.wfr,
            activity_budget_line=self.line,
            line_item_type="transport",
            description="Transport",
            quantity=1,
            unit_cost=100_000,
            total_cost=100_000,
        )

    def _advance(self, **overrides) -> AdvanceRequest:
        fields = {
            "activity": self.activity,
            "budget_line": self.line,
            "responsible_user_id": self.cceo.id,
            "fy": FY,
            "quarter": "Q3",
            "amount": 100_000,
            "advance_type": "advance",
            "status": AdvanceRequestStatus.ACCOUNTABILITY_PL_PENDING,
            "disbursed_amount": 100_000,
            "disbursed_at": timezone.now(),
            "accounted_amount": 100_000,
            "returned_amount": 0,
            "accountability_netsuite_id": "EXP-2026-PLN-1",
            "accountability_submitted_at": timezone.now(),
        }
        fields.update(overrides)
        return AdvanceRequest.objects.create(**fields)

    def _owner_notice(self, event: str) -> Notification:
        return Notification.objects.get(
            recipient_id=self.cceo.id, source_event_type=event
        )

    # ── The in-app notification, with a route that opens the week ──────────
    def test_pl_approval_notifies_the_owner_on_the_weekly_request(self):
        adv = self._advance()
        advance_service.pl_approve_accountability(adv.id, self.pl)

        n = self._owner_notice("accountability_pl_approved")
        self.assertEqual(n.context_type, "AdvanceRequest")
        self.assertEqual(n.context_id, adv.id)
        self.assertEqual(n.target_route, f"/fund-requests/weekly/{self.wfr.id}")
        self.assertEqual(n.action_label, "View Accountability")
        # The route is a real page, not a guess.
        self.assertEqual(resolve(n.target_route).kwargs.get("request_id"), self.wfr.id)

    def test_pl_return_notifies_the_owner_with_the_reason(self):
        adv = self._advance()
        advance_service.pl_return_accountability(
            adv.id, {"reason": "Receipt missing"}, self.pl
        )

        n = self._owner_notice("accountability_pl_returned")
        self.assertIn("Receipt missing", n.body)
        self.assertEqual(n.target_route, f"/fund-requests/weekly/{self.wfr.id}")
        self.assertEqual(n.action_label, "Fix Accountability")
        self.assertEqual(resolve(n.target_route).kwargs.get("request_id"), self.wfr.id)
        adv.refresh_from_db()
        self.assertEqual(adv.status, AdvanceRequestStatus.DISBURSED)

    def test_reimbursement_claim_decisions_reach_the_owner_too(self):
        approve = self._advance(
            advance_type="self_funded",
            status=AdvanceRequestStatus.REIMBURSEMENT_PL_PENDING,
            disbursed_amount=None,
            disbursed_at=None,
            accountability_netsuite_id="EXP-2026-PLN-2",
        )
        advance_service.pl_approve_accountability(approve.id, self.pl)
        n = self._owner_notice("accountability_pl_approved")
        self.assertIn("reimbursement claim", n.body)
        self.assertEqual(n.target_route, f"/fund-requests/weekly/{self.wfr.id}")

        # A second claim on another line, returned.
        other_line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            cost_setting_key="staff_visit_lunch",
            label="Lunch",
            unit_cost=15_000,
            quantity=1,
            amount=15_000,
            responsible_user=self.cceo.id,
        )
        returned = self._advance(
            budget_line=other_line,
            amount=15_000,
            advance_type="self_funded",
            status=AdvanceRequestStatus.REIMBURSEMENT_PL_PENDING,
            disbursed_amount=None,
            disbursed_at=None,
            accounted_amount=15_000,
            accountability_netsuite_id="EXP-2026-PLN-3",
        )
        advance_service.pl_return_accountability(
            returned.id, {"reason": "Wrong amount"}, self.pl
        )
        n = self._owner_notice("accountability_pl_returned")
        self.assertEqual(n.context_id, returned.id)
        # This line was never compiled into a week: the list is the honest
        # landing, not a detail page that does not exist.
        self.assertEqual(n.target_route, "/fund-requests/weekly")
        returned.refresh_from_db()
        self.assertEqual(
            returned.status, AdvanceRequestStatus.SELF_FUNDED_PENDING_REIMBURSEMENT
        )

    def test_route_falls_back_to_the_list_without_a_weekly_line(self):
        WeeklyFundRequestLine.objects.all().delete()
        adv = self._advance()
        advance_service.pl_approve_accountability(adv.id, self.pl)
        n = self._owner_notice("accountability_pl_approved")
        self.assertEqual(n.target_route, "/fund-requests/weekly")
        self.assertIsNotNone(resolve(n.target_route))

    # ── The off-device copy ────────────────────────────────────────────────
    def test_pl_decisions_go_out_by_sms_after_commit(self):
        adv = self._advance()
        with patch.object(SmsService, "send", return_value={"delivered": True}) as send:
            with self.captureOnCommitCallbacks(execute=True):
                advance_service.pl_approve_accountability(adv.id, self.pl)
                send.assert_not_called()
        send.assert_called_once()
        msg = send.call_args.args[0]
        self.assertEqual(msg.to, PHONE)
        self.assertTrue(
            msg.text.startswith("Accountability approved by your Program Lead. "),
            msg.text,
        )
        self.assertTrue(msg.text.endswith(f" /fund-requests/weekly/{self.wfr.id}"))
        self.assertLessEqual(len(msg.text), SMS_MAX_LENGTH)

        # The PL, who has no phone on file, is never messaged about their own
        # decision; the Accountant's "ready for review" notice is not a money
        # event for the recipient either.
        self.assertEqual(send.call_count, 1)

    def test_return_sms_is_skipped_when_the_owner_opted_out(self):
        self.cceo.sms_money_alerts = False
        self.cceo.save(update_fields=["sms_money_alerts"])
        adv = self._advance()
        with patch.object(SmsService, "send") as send:
            with self.captureOnCommitCallbacks(execute=True):
                advance_service.pl_return_accountability(
                    adv.id, {"reason": "Receipt missing"}, self.pl
                )
        send.assert_not_called()
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.cceo.id,
                source_event_type="accountability_pl_returned",
            ).exists()
        )
