"""Financial-integrity regressions across the funding channels (2026-07 audit).

Four confirmed defects, one file:

  F1 — the period (services.disburse) and dashboard disbursement paths flipped
       AdvanceRequests to DISBURSED via bulk .update() without writing
       disbursed_amount, so every budget rollup summing the ledger's
       disbursed_amount reported UGX 0 for money released through them.
  D4 — submit() accepted a "weekly" period with no week (and "monthly" with no
       month), fell back to the bare-fy period key, and _filter_period then
       applied NO period filter: one request silently swallowed the entire
       FY's national planned spend, one Accountant click from flipping every
       advance in the FY to disbursed.
  P1 — PartnerPaymentService.pay_partner wrote a caller-supplied amount
       verbatim, with no relation to the activity's costed budget lines.
  D1 — fy_totals_all_fund_types summed monthly FundRequest totals PLUS
       WeeklyFundRequest totals — two snapshots of the SAME cost lines — so
       the Accountant's headline KPIs double-counted every line requested
       through both channels. The totals now read the AdvanceRequest ledger,
       which is 1:1 with cost lines and channel-agnostic.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.fund_requests import disbursement_dashboard_service, services
from apps.fund_requests.finance_services import (
    FinanceBlockedReasonService,
    PartnerPaymentService,
)
from apps.fund_requests.models import (
    AdvanceRequest,
    Disbursement,
    FundRequest,
    FundRequestItem,
    PartnerPayment,
    WeeklyFundRequest,
    WeeklyFundRequestLine,
)
from apps.geography.models import District, Region
from apps.schools.models import School

MONTH = 4  # any fixed in-FY month; every fixture below pins to it


class _ChannelFixture(TestCase):
    """One planned+costed activity whose single budget line is visible to the
    period channel (FundRequest), the weekly channel (WeeklyFundRequest) and
    the shared AdvanceRequest ledger."""

    AMOUNT = 120_000

    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        region = Region.objects.create(name="Audit Chan Region")
        district = District.objects.create(name="Audit Chan District", region=region)
        cls.school = School.objects.create(
            school_id="SCH-AUDIT-CHAN",
            name="Audit Chan Primary",
            region=region,
            district=district,
        )
        cls.owner = cls._person("owner", "CCEO")
        cls.accountant = cls._person("acct", "Accountant")
        planned = date.today()
        cls.activity = Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            fy=cls.fy,
            month=MONTH,
            school=cls.school,
            responsible_staff_id=cls.owner.id,
            planned_date=planned,
            scheduled_date=planned,
        )
        cls.line = ActivityScheduleCostLine.objects.create(
            activity=cls.activity,
            responsible_user=cls.owner.id,
            planned_date=planned,
            description="Transport",
            unit_cost=cls.AMOUNT,
            quantity=1,
            amount=cls.AMOUNT,
        )
        cls.advance = AdvanceRequest.objects.create(
            activity=cls.activity,
            budget_line=cls.line,
            responsible_user_id=cls.owner.id,
            fy=cls.fy,
            quarter="Q1",
            month=MONTH,
            week=1,
            amount=cls.AMOUNT,
            status="pending_responsible_confirmation",
        )

    @classmethod
    def _person(cls, key, role):
        user = User.objects.create(
            id=f"afc-{key}"[:30],
            email=f"afc-{key}@edify.org",
            name=f"AFC {key}",
            roles=[role],
            active_role=role,
            is_active=True,
        )
        StaffProfile.objects.create(id=f"afcs-{key}"[:30], user=user, title=role)
        return user

    def _monthly_request(self, status, scope="own"):
        fr = FundRequest.objects.create(
            fy=self.fy,
            period="monthly",
            period_key=f"{self.fy}-M{MONTH}",
            scope=scope,
            submitted_by_user_id=self.owner.id,
            submitted_by_role="CCEO",
            total_amount=self.AMOUNT,
            activity_count=1,
            status=status,
        )
        FundRequestItem.objects.create(
            fund_request=fr,
            activity_id=self.activity.id,
            activity_schedule_cost_line_id=self.line.id,
            amount=self.AMOUNT,
            period="monthly",
            period_key=fr.period_key,
        )
        return fr

    def _weekly_request(self, status):
        monday = date(int(self.fy), MONTH, 6)
        wfr = WeeklyFundRequest.objects.create(
            fy=self.fy,
            week_start_date=monday,
            week_end_date=monday + timedelta(days=6),
            responsible_user=self.owner.id,
            total_amount=self.AMOUNT,
            status=status,
        )
        WeeklyFundRequestLine.objects.create(
            weekly_fund_request=wfr,
            activity_budget_line=self.line,
            line_item_type="transport",
            description="Transport",
            quantity=1,
            unit_cost=self.AMOUNT,
            total_cost=self.AMOUNT,
        )
        return wfr


class PeriodDisburseWritesTheLedgerAmountTest(_ChannelFixture):
    """F1 — services.disburse's bulk advance flip must write disbursed_amount."""

    def test_bulk_flip_records_the_money_it_moved(self):
        self.advance.status = "confirmed_for_advance"
        self.advance.save(update_fields=["status", "updated_at"])
        fr = self._monthly_request("approved")

        services.disburse(
            fr.id, {"method": "Cash", "reference": "R-1"}, self.accountant
        )

        self.advance.refresh_from_db()
        self.assertEqual(self.advance.status, "disbursed")
        self.assertEqual(
            self.advance.disbursed_amount,
            self.AMOUNT,
            "the flipped advance must carry the released amount — a null here "
            "makes every disbursed rollup read UGX 0 for this channel",
        )
        self.assertEqual(self.advance.disbursed_by_user_id, self.accountant.id)


class PlannedFundingRequiresAnApprovedLedgerTest(_ChannelFixture):
    """A period/weekly parent may never move money around the shared ledger."""

    def test_period_disbursement_refuses_a_missing_advance(self):
        self.advance.delete()
        fr = self._monthly_request("approved")

        with self.assertRaisesMessage(BadRequest, "missing an approved advance"):
            services.disburse(fr.id, {}, self.accountant)

        fr.refresh_from_db()
        self.assertEqual(fr.status, "approved")

    def test_period_disbursement_refuses_every_non_payable_advance_state(self):
        fr = self._monthly_request("approved")
        for status in (
            "self_funded_pending_reimbursement",
            "not_requested",
            "returned",
            "cancelled",
            "disbursed",
        ):
            with self.subTest(status=status):
                self.advance.status = status
                self.advance.save(update_fields=["status", "updated_at"])
                with self.assertRaisesMessage(
                    BadRequest, "missing an approved advance"
                ):
                    services.disburse(fr.id, {}, self.accountant)
                fr.refresh_from_db()
                self.assertEqual(fr.status, "approved")

    def test_approval_routes_the_pending_ledger_for_period_release(self):
        """Approval — not disbursement — is what clears a pending advance.

        The period channel used to release advances still in
        pending_responsible_confirmation, meaning nobody with authority had
        cleared those lines. services.approve() now routes the request's
        pending advances to submitted_to_accountant, and the guard releases
        only cleared statuses."""
        admin = self._person("admin", "Admin")
        fr = self._monthly_request("submitted")

        services.approve(fr.id, {}, admin)
        self.advance.refresh_from_db()
        self.assertEqual(self.advance.status, "submitted_to_accountant")

        services.disburse(fr.id, {}, self.accountant)
        self.advance.refresh_from_db()
        self.assertEqual(self.advance.status, "disbursed")
        self.assertEqual(self.advance.disbursed_amount, self.AMOUNT)

    def test_period_disbursement_refuses_a_pending_ledger(self):
        """An approved-status request whose advances are still pending (the
        approval never routed them — e.g. a row built around approve()) must
        fail closed instead of releasing unconfirmed money."""
        fr = self._monthly_request("approved")

        with self.assertRaisesMessage(BadRequest, "missing an approved advance"):
            services.disburse(fr.id, {}, self.accountant)

        self.advance.refresh_from_db()
        self.assertEqual(self.advance.status, "pending_responsible_confirmation")

    def test_monthly_disbursement_requires_receipt_before_accountability(self):
        """Same receipt-before-accountability law as the weekly channel: a
        line paid through a monthly fund plan cannot be accounted for until
        the owner confirms the plan's funds actually arrived."""
        from django.utils import timezone as _tz

        from apps.fund_requests import advance_service

        self.advance.status = "disbursed"
        self.advance.disbursed_amount = self.AMOUNT
        self.advance.save(
            update_fields=["status", "disbursed_amount", "updated_at"]
        )
        fr = self._monthly_request("disbursed")

        with self.assertRaisesMessage(BadRequest, "Confirm receipt"):
            advance_service.submit_accountability(
                self.advance.id,
                {"amountSpent": self.AMOUNT, "netsuiteId": "NS-M-1"},
                self.owner,
            )

        fr.receipt_confirmed_at = _tz.now()
        fr.save(update_fields=["receipt_confirmed_at", "updated_at"])
        advance_service.submit_accountability(
            self.advance.id,
            {"amountSpent": self.AMOUNT, "netsuiteId": "NS-M-1"},
            self.owner,
        )
        self.advance.refresh_from_db()
        self.assertEqual(self.advance.status, "accountability_pl_pending")

    def test_accountant_return_routes_the_ledger_back_to_pending(self):
        """Returning a sent plan un-clears its advances, so nothing on it
        stays releasable while the owner corrects it."""
        self.advance.status = "submitted_to_accountant"
        self.advance.save(update_fields=["status", "updated_at"])
        fr = self._monthly_request("sent_to_accountant")

        disbursement_dashboard_service.return_item(
            self.accountant, fr.id, {"reason": "fix the venue line"}
        )

        self.advance.refresh_from_db()
        self.assertEqual(self.advance.status, "pending_responsible_confirmation")

    def test_second_period_request_for_the_same_line_is_refused(self):
        self.advance.status = "confirmed_for_advance"
        self.advance.save(update_fields=["status", "updated_at"])
        own = self._monthly_request("approved", scope="own")
        team = self._monthly_request("approved", scope="team")

        services.disburse(own.id, {}, self.accountant)
        with self.assertRaisesMessage(BadRequest, "already had money released"):
            services.disburse(team.id, {}, self.accountant)

        team.refresh_from_db()
        self.assertEqual(team.status, "approved")

    def test_period_disbursement_refuses_items_with_no_cost_line_linkage(self):
        """The guard must run even when NO item carries a cost line.

        `services.disburse` used to call the guard only `if line_ids`, so a
        request whose items were all unlinked skipped the shared ledger
        entirely and released money with no traceable Planning source. The
        dashboard and weekly channels always call it; this one now does too."""
        fr = self._monthly_request("approved")
        fr.items.update(activity_schedule_cost_line_id="")

        with self.assertRaisesMessage(BadRequest, "no approved budget-line ledger"):
            services.disburse(fr.id, {}, self.accountant)

        fr.refresh_from_db()
        self.assertEqual(fr.status, "approved")
        self.advance.refresh_from_db()
        self.assertEqual(
            self.advance.status,
            "pending_responsible_confirmation",
            "an unlinked request must not touch the shared ledger at all",
        )

    def test_dashboard_disbursement_refuses_a_missing_advance(self):
        self.advance.delete()
        fr = self._monthly_request("sent_to_accountant")

        with self.assertRaisesMessage(BadRequest, "missing an approved advance"):
            disbursement_dashboard_service.disburse(self.accountant, fr.id, {})

        fr.refresh_from_db()
        self.assertEqual(fr.status, "sent_to_accountant")

    def test_weekly_disbursement_refuses_a_missing_advance(self):
        from apps.fund_requests import weekly_service

        self.advance.delete()
        weekly = self._weekly_request("confirmed_for_advance")

        with self.assertRaisesMessage(BadRequest, "missing an approved advance"):
            weekly_service.disburse(weekly.id, {}, self.accountant)

        weekly.refresh_from_db()
        self.assertEqual(weekly.status, "confirmed_for_advance")


class DashboardDisburseWritesTheLedgerAmountTest(_ChannelFixture):
    """F1/F2 — the dashboard path must write disbursed_amount and only write
    Disbursement audit rows for money it actually moved."""

    def test_dashboard_flip_records_amount_and_audit_rows(self):
        self.advance.status = "confirmed_for_advance"
        self.advance.save(update_fields=["status", "updated_at"])
        fr = self._monthly_request("sent_to_accountant")

        disbursement_dashboard_service.disburse(self.accountant, fr.id, {})

        self.advance.refresh_from_db()
        self.assertEqual(self.advance.status, "disbursed")
        self.assertEqual(self.advance.disbursed_amount, self.AMOUNT)
        self.assertEqual(self.advance.disbursed_by_user_id, self.accountant.id)
        self.assertEqual(Disbursement.objects.filter(activity=self.activity).count(), 1)


class SubmitRefusesPeriodlessRequestsTest(_ChannelFixture):
    """D4 — a weekly request needs a week, a monthly one a month; the bare-fy
    fallback silently matched the whole FY's planned spend."""

    def test_weekly_without_week_is_refused(self):
        with self.assertRaisesMessage(BadRequest, "requires an explicit week"):
            services.submit({"period": "weekly", "fy": self.fy}, self.owner)

    def test_monthly_without_month_is_refused(self):
        with self.assertRaisesMessage(BadRequest, "requires an explicit month"):
            services.submit({"period": "monthly", "fy": self.fy}, self.owner)

    def test_a_caller_supplied_bare_fy_period_key_is_refused_too(self):
        # periodKey bypasses _period_key, so _filter_period must also refuse.
        with self.assertRaises(BadRequest):
            services.submit(
                {"period": "weekly", "fy": self.fy, "periodKey": self.fy},
                self.owner,
            )

    def test_monthly_with_a_month_still_works(self):
        result = services.submit(
            {"period": "monthly", "fy": self.fy, "month": MONTH}, self.owner
        )
        self.assertEqual(result["periodKey"], f"{self.fy}-M{MONTH}")

    def test_the_weekly_cron_no_longer_files_an_fy_wide_request(self):
        from apps.realtime.jobs import _do_weekly_fund_request

        _do_weekly_fund_request()
        self.assertEqual(FundRequest.objects.count(), 0)

    def test_scoped_upsert_survives_own_and_team_rows_side_by_side(self):
        # M6 — the scope-blind lookup raised MultipleObjectsReturned the
        # moment both scopes existed for one submitter/period.
        self._monthly_request("submitted", scope="own")
        team = self._monthly_request("submitted", scope="team")

        result = services.submit(
            {"period": "monthly", "fy": self.fy, "month": MONTH}, self.owner
        )

        self.assertEqual(result["scope"], "own")
        team.refresh_from_db()
        self.assertEqual(team.scope, "team", "the sibling scope must not be rewritten")


class PartnerPaymentClampsToThePlannedBudgetTest(_ChannelFixture):
    """P1 — pay_partner must clamp to the activity's costed lines, the same
    contract weekly_service.disburse enforces."""

    def _pay(self, amount):
        with patch.object(
            FinanceBlockedReasonService, "get_blocked_reasons", return_value=[]
        ):
            return PartnerPaymentService.pay_partner(
                activity=self.activity,
                partner_name="Edify Partner",
                amount=amount,
                method="Bank Transfer",
                reference="PP-1",
                user_id=self.accountant.id,
                netsuite_id="NS-AUDIT-1",
            )

    def test_zero_and_negative_amounts_are_refused(self):
        for amount in (0, -5_000):
            with self.subTest(amount=amount):
                with self.assertRaises(BadRequest):
                    self._pay(amount)

    def test_amounts_above_the_planned_total_are_refused(self):
        with self.assertRaisesMessage(BadRequest, str(self.AMOUNT)):
            self._pay(self.AMOUNT + 1)

    def test_the_planned_total_itself_is_payable(self):
        # The staff-channel advance would trip the cross-channel guard; a
        # partner-delivered activity carries none (see sync_for_activity).
        self.advance.delete()
        with patch(
            "apps.fund_requests.finance_services.ClosureEligibilityService.is_eligible",
            return_value=False,
        ):
            pay = self._pay(self.AMOUNT)
        self.assertEqual(pay.amount_paid, self.AMOUNT)
        self.assertEqual(PartnerPayment.objects.count(), 1)


class HeadlineTotalsDoNotDoubleCountTest(_ChannelFixture):
    """D1 — one cost line on both a weekly and a monthly request must appear
    once in the headline money, while the queue keeps one row per request."""

    def test_fy_totals_count_the_shared_cost_line_once(self):
        self._monthly_request("submitted")
        self._weekly_request("pending_responsible_confirmation")

        totals = disbursement_dashboard_service.fy_totals_all_fund_types(self.fy)

        self.assertEqual(
            totals["awaiting_approval"],
            self.AMOUNT,
            "the same budget line requested through two channels is still "
            "one line of money, not two",
        )
        # The queue really does hold one record per channel.
        self.assertEqual(totals["record_count"], 2)
        self.assertEqual(totals["awaiting_approval_count"], 2)

    def test_month_overview_counts_the_shared_cost_line_once(self):
        self._monthly_request("submitted")
        self._weekly_request("pending_responsible_confirmation")

        overview = disbursement_dashboard_service.month_overview_all_fund_types(
            self.fy, MONTH
        )
        self.assertEqual(overview["waiting_for_approval"], self.AMOUNT)

    def test_disbursed_totals_come_from_the_ledger(self):
        self.advance.status = "confirmed_for_advance"
        self.advance.save(update_fields=["status", "updated_at"])
        fr = self._monthly_request("approved")
        services.disburse(fr.id, {}, self.accountant)

        totals = disbursement_dashboard_service.fy_totals_all_fund_types(self.fy)
        self.assertEqual(totals["disbursed"], self.AMOUNT)
        overview = disbursement_dashboard_service.month_overview_all_fund_types(
            self.fy, MONTH
        )
        self.assertEqual(overview["disbursed"], self.AMOUNT)
