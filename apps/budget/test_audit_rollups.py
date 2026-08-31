"""Regression tests for the 2026-07 financial-integrity audit fixes.

Covers:
  • weekly() — no AttributeError on cost-line qty, Monday-anchored week buckets,
    cancelled/rejected/deferred exclusion.
  • cost_preview() — delegates to the canonical costing_service.preview.
  • MonthlyFundAllocationService — cancelled/soft-deleted activities excluded,
    money attributed per (activity, responsible_user) pair.
  • my_plan budget_total — canonical cost-line sum preferred over est_cost_cents.
  • board() — quarter totals use fiscal (Oct-start) quarters; week totals use
    Monday-anchored local weeks that survive the ISO year wrap.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget import costing_service, services
from apps.budget.allocation_service import MonthlyFundAllocationService
from apps.budget.models import CostCatalogue, CostSetting
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School

FY = "2026"


def _user(email, name, role):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
    )


def _aware(y, m, d, hh=9):
    return datetime(y, m, d, hh, 0, tzinfo=dt_timezone.utc)


class _BaseData(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Audit Region")
        cls.district = District.objects.create(name="Audit District", region=cls.region)
        cls.school = School.objects.create(
            school_id="SCH-AUD-1",
            name="Audit School",
            region=cls.region,
            district=cls.district,
        )
        cls.admin = _user("audit-admin@t.org", "Audit Admin", EdifyRole.ADMIN.value)

    @classmethod
    def _activity(
        cls,
        *,
        status="scheduled",
        month=10,
        planned=None,
        sched=None,
        est_cost=0,
        responsible="staff-aud-1",
        deleted_at=None,
        quarter="Q1",
    ):
        return Activity.objects.create(
            activity_type="school_visit",
            school=cls.school,
            delivery_type="staff",
            status=status,
            responsible_staff_id=responsible,
            fy=FY,
            month=month,
            quarter=quarter,
            planned_date=planned,
            week_start_date=(
                planned - timedelta(days=planned.weekday()) if planned else None
            ),
            scheduled_date=sched,
            est_cost_cents=est_cost,
            deleted_at=deleted_at,
        )

    @staticmethod
    def _line(
        activity,
        *,
        amount,
        qty=1,
        owner=None,
        week_start=None,
        month=10,
        key="school_visit_cost_per_school",
    ):
        return ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key=key,
            label="School visit cost",
            unit_cost=amount // max(1, qty),
            quantity=qty,
            amount=amount,
            fiscal_year=FY,
            month=month,
            week_start_date=week_start,
            planned_date=activity.planned_date,
            responsible_user=owner or activity.responsible_staff_id,
        )


class WeeklyRollupTests(_BaseData):
    def test_weekly_returns_and_buckets_by_week_start_date(self):
        """weekly() must not raise (line.qty → line.quantity) and must bucket
        by the Monday-anchored week_start_date, not day-of-month arithmetic."""
        planned = date(2025, 10, 8)  # a Wednesday; its Monday is 2025-10-06
        monday = date(2025, 10, 6)
        a = self._activity(planned=planned, sched=_aware(2025, 10, 8))
        self._line(a, amount=10_000, qty=2, week_start=monday)

        result = services.weekly(self.admin, {"fy": FY, "month": "10"})

        self.assertEqual(result["total"], 10_000)
        self.assertEqual(result["count"], 1)
        self.assertEqual(len(result["weeks"]), 1)
        week = result["weeks"][0]
        # Labelled by its Monday — the same anchor every other surface uses.
        self.assertEqual(week["key"], "2025-10-06")
        self.assertEqual(week["weekStart"], "2025-10-06")
        self.assertEqual(week["amount"], 10_000)
        self.assertEqual(week["count"], 1)
        # The serialized cost line reads .quantity (the old .qty AttributeError).
        self.assertEqual(result["lines"][0]["lines"][0]["qty"], 2)
        self.assertEqual(result["lines"][0]["weekStart"], "2025-10-06")

    def test_weekly_excludes_cancelled_rejected_deferred(self):
        planned = date(2025, 10, 8)
        keep = self._activity(planned=planned, sched=_aware(2025, 10, 8))
        self._line(keep, amount=10_000, week_start=date(2025, 10, 6))
        for status in ("cancelled", "rejected", "deferred"):
            dead = self._activity(
                status=status, planned=planned, sched=_aware(2025, 10, 8)
            )
            self._line(dead, amount=99_000, week_start=date(2025, 10, 6))

        result = services.weekly(self.admin, {"fy": FY, "month": "10"})
        self.assertEqual(result["total"], 10_000)
        self.assertEqual(result["count"], 1)


class CostPreviewParityTests(TestCase):
    """services.cost_preview must be the SAME engine as costing_service.preview
    — one catalogue-resolved rate card, no second unfiltered copy."""

    def setUp(self):
        self.catalogue = costing_service.active_catalogue(FY) or (
            CostCatalogue.objects.create(fy=FY, is_active=True)
        )
        CostSetting.objects.update_or_create(
            key="school_visit_cost_per_school",
            defaults={
                "label": "School visit cost per school",
                "unit_cost": 80_000,
                "fy": FY,
                "catalogue": self.catalogue,
            },
        )

    def test_cost_preview_matches_canonical_preview_for_staff_school_visit(self):
        payload = {
            "activityType": "school_visit",
            "deliveryType": "staff",
            "districtType": "primary",
            "fy": FY,
        }
        legacy = services.cost_preview(payload, None)
        canonical = costing_service.preview(payload)

        self.assertGreater(legacy["amount"], 0)
        self.assertEqual(legacy["amount"], canonical["amount"])
        self.assertEqual(legacy["costMissing"], canonical["costMissing"])
        self.assertEqual(legacy["missingItems"], canonical["missingItems"])
        self.assertEqual(legacy["canSchedule"], canonical["canSchedule"])
        self.assertEqual(
            [(line["key"], line["qty"], line["amount"]) for line in legacy["lines"]],
            [(line["key"], line["qty"], line["amount"]) for line in canonical["lines"]],
        )


class MonthlyAllocationTests(_BaseData):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.staff_user_1 = _user(
            "aud-cceo1@t.org", "Aud CCEO One", EdifyRole.CCEO.value
        )
        cls.staff_user_2 = _user(
            "aud-cceo2@t.org", "Aud CCEO Two", EdifyRole.CCEO.value
        )
        StaffProfile.objects.create(
            user=cls.staff_user_1,
            title="CCEO",
            country="Uganda",
            primary_district_id=cls.district.id,
        )
        StaffProfile.objects.create(
            user=cls.staff_user_2,
            title="CCEO",
            country="Uganda",
            primary_district_id=cls.district.id,
        )

    def test_allocation_excludes_cancelled_and_deleted_activities(self):
        u1 = self.staff_user_1.user_id
        live = self._activity(responsible=u1, planned=date(2025, 10, 8))
        self._line(live, amount=40_000, owner=u1)
        cancelled = self._activity(
            status="cancelled", responsible=u1, planned=date(2025, 10, 9)
        )
        self._line(cancelled, amount=60_000, owner=u1)
        from django.utils import timezone as dj_tz

        deleted = self._activity(
            responsible=u1, planned=date(2025, 10, 10), deleted_at=dj_tz.now()
        )
        self._line(deleted, amount=25_000, owner=u1)

        result = MonthlyFundAllocationService.get_monthly_allocation(
            10, FY, principal=self.admin
        )
        row = next(r for r in result["rows_all"] if r["user_id"] == u1)
        self.assertEqual(row["total_allocation"], 40_000)
        self.assertEqual(
            result["grand_totals"]["total_allocation"]
            - result["grand_totals"]["admin_budget"]["total"],
            40_000,
        )

    def test_multi_owner_activity_money_lands_under_each_owner(self):
        u1 = self.staff_user_1.user_id
        u2 = self.staff_user_2.user_id
        shared = self._activity(responsible=u1, planned=date(2025, 10, 8))
        self._line(shared, amount=30_000, owner=u1)
        self._line(shared, amount=20_000, owner=u2, key="primary_lunch_per_day")

        result = MonthlyFundAllocationService.get_monthly_allocation(
            10, FY, principal=self.admin
        )
        row1 = next(r for r in result["rows_all"] if r["user_id"] == u1)
        row2 = next(r for r in result["rows_all"] if r["user_id"] == u2)
        self.assertEqual(row1["total_allocation"], 30_000)
        self.assertEqual(row2["total_allocation"], 20_000)

    def test_insights_expose_partner_total(self):
        insights = MonthlyFundAllocationService.calculate_insights(
            rows_all=[
                {
                    "user_id": "u-x",
                    "name": "X",
                    "staff_visits": {"count": 1, "unit_cost": 0, "total": 10_000},
                    "partner_visits": {"count": 1, "unit_cost": 0, "total": 7_000},
                    "ssa": {"count": 0, "unit_cost": 0, "total": 0},
                    "cluster_training": {"count": 0, "unit_cost": 0, "total": 0},
                    "partner_in_school_training": {
                        "count": 1,
                        "unit_cost": 0,
                        "total": 3_000,
                    },
                    "total_allocation": 20_000,
                }
            ],
            grand_totals={
                "staff_visits": {"count": 1, "total": 10_000, "unit_cost": 0},
                "partner_visits": {"count": 1, "total": 7_000, "unit_cost": 0},
                "ssa": {"count": 0, "total": 0, "unit_cost": 0},
                "cluster_training": {"count": 0, "total": 0, "unit_cost": 0},
                "partner_in_school_training": {
                    "count": 1,
                    "total": 3_000,
                    "unit_cost": 0,
                },
                "admin_budget": {"planned": 0, "allocated": 0, "total": 0},
                "total_allocation": 20_000,
            },
            total_staff_count=1,
        )
        self.assertEqual(insights["partner_total"], 10_000)


class MyPlanBudgetTotalTests(_BaseData):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cceo = _user("aud-myplan@t.org", "Aud MyPlan", EdifyRole.CCEO.value)

    def test_planning_minimum_never_falls_back_to_operational_estimates(self):
        from apps.my_plan.services import get_frontend_context

        with_lines = self._activity(
            responsible=self.cceo.id,
            planned=date(2025, 10, 8),
            sched=_aware(2025, 10, 8),
            est_cost=999_999,  # stale estimate that must NOT win
        )
        self._line(with_lines, amount=50_000, owner=self.cceo.id)
        no_lines = self._activity(
            responsible=self.cceo.id,
            planned=date(2025, 10, 9),
            sched=_aware(2025, 10, 9),
            est_cost=70_000,  # only source available → fallback
        )

        ctx = get_frontend_context(self.cceo, {"period": "fy", "fy": FY})
        by_id = {row["id"]: row for row in ctx["school_visits_all"]}
        self.assertIsNone(by_id[with_lines.id]["budget_total"])
        self.assertIsNone(by_id[no_lines.id]["budget_total"])
        from apps.budget.services import budget_workspace

        budget = budget_workspace(
            self.cceo, {"fy": FY, "date": "2025-10-08", "period": "fy"}
        )
        self.assertEqual(budget["total"], 50_000)


class BoardFiscalPeriodTests(_BaseData):
    def test_october_activity_lands_in_fiscal_q1(self):
        a = self._activity(
            planned=date(2025, 10, 15), sched=_aware(2025, 10, 15), month=10
        )
        self._line(a, amount=12_000, week_start=date(2025, 10, 13))

        q1 = services.board(self.admin, {"fy": FY, "quarter": "Q1"})
        self.assertEqual(q1["summary"]["periodTotal"], 12_000)
        # The same October money must NOT appear in any other fiscal quarter.
        for q in ("Q2", "Q3", "Q4"):
            other = services.board(self.admin, {"fy": FY, "quarter": q})
            self.assertEqual(other["summary"]["periodTotal"], 0, q)

    def test_this_quarter_total_uses_fiscal_quarters(self):
        a = self._activity(
            planned=date(2025, 10, 15), sched=_aware(2025, 10, 15), month=10
        )
        self._line(a, amount=12_000, week_start=date(2025, 10, 13))

        # A November "today" is fiscal Q1 with the October activity.
        with patch("django.utils.timezone.localdate", return_value=date(2025, 11, 20)):
            result = services.board(self.admin, {"fy": FY})
        self.assertEqual(result["summary"]["thisQuarter"], 12_000)

        # A January "today" is fiscal Q2 — the October money must drop out.
        with patch("django.utils.timezone.localdate", return_value=date(2026, 1, 20)):
            result = services.board(self.admin, {"fy": FY})
        self.assertEqual(result["summary"]["thisQuarter"], 0)

    def test_week_totals_survive_the_iso_year_wrap(self):
        """31 Dec 2025 (ISO week 1 of 2026) and 2 Jan 2026 share a Monday
        (29 Dec) — the old calendar-year + ISO-week-number gate dropped it."""
        a = self._activity(
            planned=date(2026, 1, 2), sched=_aware(2026, 1, 2), month=1, quarter="Q2"
        )
        self._line(a, amount=8_000, week_start=date(2025, 12, 29), month=1)

        with patch("django.utils.timezone.localdate", return_value=date(2025, 12, 31)):
            result = services.board(self.admin, {"fy": FY})
        self.assertEqual(result["summary"]["thisWeek"], 8_000)


class AdminLinesTotalTests(TestCase):
    def test_admin_lines_total_counts_only_active_lines(self):
        """Removed/superseded CD admin lines must not inflate the monthly,
        quarterly, or FY admin totals (matching budget_workspace's filter)."""
        from apps.monthly_work_plan.models import (
            AdminBudgetLine,
            MonthlyWorkPlanBudget,
        )

        budget = MonthlyWorkPlanBudget.objects.create(fy=FY, month_key="2025-10")
        AdminBudgetLine.objects.create(
            monthly_budget=budget,
            cost_category="rent",
            description="Office rent",
            unit_cost=100_000,
            total_cost=100_000,
            created_by_user_id="cd-1",
            status="active",
        )
        AdminBudgetLine.objects.create(
            monthly_budget=budget,
            cost_category="rent",
            description="Removed duplicate",
            unit_cost=900_000,
            total_cost=900_000,
            created_by_user_id="cd-1",
            status="removed",
        )

        self.assertEqual(services._admin_lines_total(FY), 100_000)
        self.assertEqual(services._admin_lines_total(FY, month_key="2025-10"), 100_000)
