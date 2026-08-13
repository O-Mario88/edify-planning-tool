"""The finance-integrity checks must find the defects they claim to find."""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.health import (
    cost_line_period_drift,
    double_funded_budget_lines,
    finance_integrity_health,
    payable_lines_without_approved_advance,
    split_week_cost_lines,
)
from apps.core.fy import get_operational_fy
from apps.fund_requests.models import (
    AdvanceRequest,
    FundRequest,
    FundRequestItem,
    WeeklyFundRequest,
)
from apps.geography.models import District, Region
from apps.schools.models import School


def _monday(offset: int = 0) -> date:
    today = date.today()
    return today - timedelta(days=today.weekday()) + timedelta(weeks=offset)


class FinanceIntegrityHealthTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="FinHealth Region")
        cls.district = District.objects.create(
            name="FinHealth District", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="SCH-FINHEALTH-1",
            name="FinHealth Primary",
            region=cls.region,
            district=cls.district,
        )

    def _activity(self, week):
        return Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            fy=get_operational_fy(week),
            school=self.school,
            planned_date=week,
            scheduled_date=week,
        )

    def _line(self, activity, week, amount=10_000):
        return ActivityScheduleCostLine.objects.create(
            activity=activity,
            responsible_user="finhealth-owner",
            planned_date=week,
            week_start_date=week,
            fiscal_year=activity.fy,
            month=week.month,
            description="Transport",
            unit_cost=amount,
            quantity=1,
            amount=amount,
        )

    # ── a clean estate reports clean ──────────────────────────────────────
    def test_an_aligned_activity_raises_nothing(self):
        week = _monday(1)
        self._line(self._activity(week), week)
        for check in (
            cost_line_period_drift,
            split_week_cost_lines,
            double_funded_budget_lines,
        ):
            with self.subTest(check.__name__):
                self.assertEqual(check()["count"], 0)

    # ── each check finds its own defect ───────────────────────────────────
    def test_it_finds_a_cost_line_in_the_wrong_week(self):
        activity = self._activity(_monday(1))
        self._line(activity, _monday(0))  # a week early — the real drift found

        result = cost_line_period_drift()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["severity"], "high")
        sample = result["samples"][0]
        self.assertEqual(sample["work_week"], _monday(1).isoformat())
        self.assertEqual(sample["money_week"], _monday(0).isoformat())

    def test_it_finds_cost_lines_split_across_weeks(self):
        activity = self._activity(_monday(1))
        self._line(activity, _monday(1))
        self._line(activity, _monday(2))

        self.assertEqual(split_week_cost_lines()["count"], 1)

    def test_the_database_refuses_two_requests_for_one_person_week(self):
        """Stronger than a health check, so there is no health check.

        A first draft of this module carried a `duplicate_weekly_requests`
        check. It could never fire: the constraint below rejects the row. A
        check that cannot fire still occupies a line on a page people scan for
        real problems, and its permanent green implies something is watched
        when nothing is.
        """
        from django.db import IntegrityError, transaction

        week = _monday(1)
        WeeklyFundRequest.objects.create(
            responsible_user="finhealth-owner",
            week_start_date=week,
            week_end_date=week + timedelta(days=6),
            fy=get_operational_fy(week),
            status="pending_responsible_confirmation",
            total_amount=10_000,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            WeeklyFundRequest.objects.create(
                responsible_user="finhealth-owner",
                week_start_date=week,
                week_end_date=week + timedelta(days=6),
                fy=get_operational_fy(week),
                status="pending_responsible_confirmation",
                total_amount=99_000,
            )

    def test_it_finds_a_payable_line_without_an_approved_ledger_row(self):
        week = _monday(1)
        activity = self._activity(week)
        line = self._line(activity, week)
        request = FundRequest.objects.create(
            fy=activity.fy,
            period="monthly",
            period_key=f"{activity.fy}-M{week.month}",
            scope="own",
            submitted_by_user_id="finhealth-owner",
            submitted_by_role="CCEO",
            total_amount=line.amount,
            activity_count=1,
            status="approved",
        )
        FundRequestItem.objects.create(
            fund_request=request,
            activity_id=activity.id,
            activity_schedule_cost_line_id=line.id,
            amount=line.amount,
            period="monthly",
            period_key=request.period_key,
        )

        self.assertEqual(payable_lines_without_approved_advance()["count"], 1)

        AdvanceRequest.objects.create(
            activity=activity,
            budget_line=line,
            responsible_user_id="finhealth-owner",
            fy=activity.fy,
            quarter="Q1",
            month=week.month,
            week=1,
            amount=line.amount,
            status="confirmed_for_advance",
        )
        self.assertEqual(payable_lines_without_approved_advance()["count"], 0)

    # ── the report itself ─────────────────────────────────────────────────
    def test_the_report_carries_every_check_with_an_action(self):
        report = finance_integrity_health()
        keys = {c["key"] for c in report["checks"]}
        self.assertEqual(
            keys,
            {
                "cost_line_period_drift",
                "money_moved_on_cancelled_work",
                "split_week_cost_lines",
                "double_funded_budget_lines",
                "partner_lines_in_staff_funding",
                "payable_lines_without_approved_advance",
                "dangling_fund_request_items",
            },
        )
        for check in report["checks"]:
            with self.subTest(check["key"]):
                self.assertTrue(check["recommended_action"].strip())

    def test_it_reports_rather_than_repairs(self):
        """Moving money underneath an approved request is worse than the drift.
        Repair belongs to the controlled workflow, with a dry run."""
        activity = self._activity(_monday(1))
        line = self._line(activity, _monday(0))

        cost_line_period_drift()

        line.refresh_from_db()
        self.assertEqual(line.week_start_date, _monday(0), "the check mutated data")
