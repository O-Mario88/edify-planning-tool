"""Work filed under the day before its own is re-filed (owner, 2026-09-28).

A date picked in the app is stored as local midnight — 21:00 UTC the day
before — and was read in UTC, so work on 1 October went to the old fiscal year
and work on 1 January, April or July to the quarter before. Migration
activities.0060 re-files it; only a value that is exactly the old reading's is
touched.
"""

from __future__ import annotations

import io
from datetime import date, datetime, time
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.activities.fy_boundary_refile import find_misfiled, refile_misfiled
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.models import BudgetAmendment
from apps.fund_requests.models import AdvanceRequest
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord

OCT1 = date(2026, 10, 1)


def _local(day, hour=0):
    return timezone.make_aware(datetime.combine(day, time(hour)))


class FyBoundaryRefileTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Refile Central", country="Uganda")
        district = District.objects.create(name="Refile Wakiso", region=region)
        cls.school = School.objects.create(
            school_id="REFILE-1",
            name="Refile Primary",
            region=region,
            district=district,
        )

    def _activity(self, day, fy, quarter, **extra):
        return Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            status="scheduled",
            scheduled_date=_local(day),
            planned_date=day,
            planned_month=day.month,
            fy=fy,
            fiscal_year=fy,
            quarter=quarter,
            **extra,
        )

    def _line(self, activity, day, fy, quarter, key="visit_transport"):
        return ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key=key,
            label="Transport",
            unit_cost=10_000,
            quantity=1,
            amount=10_000,
            planned_date=day,
            week_start_date=day,
            month=day.month,
            fiscal_year=fy,
            quarter=quarter,
            responsible_user="cceo-1",
        )

    def test_the_new_years_first_day_moves_to_the_new_year(self):
        visit = self._activity(OCT1, "2026", "Q4")
        refile_misfiled(out=lambda _line: None)
        visit.refresh_from_db()
        self.assertEqual(
            (visit.fy, visit.fiscal_year, visit.quarter), ("2027", "2027", "Q1")
        )

    def test_a_quarters_first_day_moves_to_its_quarter_and_keeps_its_year(self):
        for day, old, new in (
            (date(2027, 1, 1), "Q1", "Q2"),
            (date(2027, 4, 1), "Q2", "Q3"),
            (date(2027, 7, 1), "Q3", "Q4"),
        ):
            visit = self._activity(day, "2027", old)
            refile_misfiled(out=lambda _line: None)
            visit.refresh_from_db()
            with self.subTest(day=day):
                self.assertEqual((visit.fy, visit.quarter), ("2027", new))

    def test_right_rows_and_rows_set_on_purpose_are_left_alone(self):
        right = self._activity(OCT1, "2027", "Q1")
        on_purpose = self._activity(OCT1, "2025", "Q3")
        next_day = self._activity(date(2026, 10, 2), "2026", "Q4")
        deleted = self._activity(OCT1, "2026", "Q4", deleted_at=timezone.now())
        self.assertEqual(find_misfiled(), [])
        refile_misfiled(out=lambda _line: None)
        for activity, expected in (
            (right, ("2027", "Q1")),
            (on_purpose, ("2025", "Q3")),
            (next_day, ("2026", "Q4")),
            (deleted, ("2026", "Q4")),
        ):
            activity.refresh_from_db()
            self.assertEqual((activity.fy, activity.quarter), expected)

    def test_advances_amendments_and_ssa_records_are_refiled(self):
        visit = self._activity(OCT1, "2027", "Q1")
        line = self._line(visit, OCT1, "2027", "Q1")
        advance = AdvanceRequest.objects.create(
            activity=visit,
            budget_line=line,
            responsible_user_id="cceo-1",
            fy="2026",
            quarter="Q4",
            amount=10_000,
            planned_date=_local(OCT1),
        )
        # Scheduled mid-morning, the UTC reading was already right; a year on
        # such a row was set on purpose.
        morning = AdvanceRequest.objects.create(
            activity=visit,
            budget_line=self._line(visit, OCT1, "2027", "Q1", key="visit_meals"),
            responsible_user_id="cceo-1",
            fy="2026",
            quarter="Q4",
            amount=10_000,
            planned_date=_local(OCT1, hour=10),
        )
        amendment = BudgetAmendment.objects.create(
            activity=visit,
            original_date=date(2026, 9, 20),
            new_date=OCT1,
            original_amount=10_000,
            original_fy="2026",
            original_quarter="Q4",
            new_fy="2026",
            new_quarter="Q4",
            reason="Moved to the first.",
            requested_by="cceo-1",
        )
        ssa = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=_local(OCT1),
            fy="2026",
            quarter="Q4",
            uploaded_by="t",
        )
        refile_misfiled(out=lambda _line: None)
        for row in (advance, morning, amendment, ssa):
            row.refresh_from_db()
        self.assertEqual((advance.fy, advance.quarter), ("2027", "Q1"))
        self.assertEqual((morning.fy, morning.quarter), ("2026", "Q4"))
        self.assertEqual((amendment.new_fy, amendment.new_quarter), ("2027", "Q1"))
        # The amendment's record of where the activity stood is history.
        self.assertEqual(amendment.original_fy, "2026")
        self.assertEqual((ssa.fy, ssa.quarter), ("2027", "Q1"))

    def test_a_cost_line_that_moves_year_resyncs_its_draft_fund_requests(self):
        visit = self._activity(OCT1, "2027", "Q1")
        line = self._line(visit, OCT1, "2026", "Q4")
        with (
            patch(
                "apps.fund_requests.weekly_service.sync_weekly_requests_for_activity"
            ) as weekly,
            patch(
                "apps.fund_requests.monthly_service.sync_monthly_drafts_for_activity"
            ) as monthly,
        ):
            refile_misfiled(out=lambda _line: None)
        line.refresh_from_db()
        self.assertEqual((line.fiscal_year, line.quarter), ("2027", "Q1"))
        vacated = [("cceo-1", "2026", 10, OCT1)]
        weekly.assert_called_once()
        self.assertEqual(weekly.call_args.kwargs["prior_buckets"], vacated)
        self.assertEqual(monthly.call_args.kwargs["prior_buckets"], vacated)

    def test_nothing_is_resynced_when_no_cost_line_moved(self):
        self._activity(OCT1, "2026", "Q4")
        with patch(
            "apps.fund_requests.weekly_service.sync_weekly_requests_for_activity"
        ) as weekly:
            refile_misfiled(out=lambda _line: None)
        weekly.assert_not_called()

    def test_the_migration_refiles_through_its_historical_models(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        historical = (
            MigrationExecutor(connection)
            .loader.project_state(("activities", "0060_refile_fy_boundary_rows"))
            .apps
        )
        visit = self._activity(OCT1, "2026", "Q4")
        line = self._line(visit, OCT1, "2026", "Q4")
        rows = find_misfiled(historical)
        self.assertEqual(
            {(row.model, row.pk) for row in rows},
            {
                ("activities.Activity", visit.pk),
                ("activities.ActivityScheduleCostLine", str(line.pk)),
            },
        )
        refile_misfiled(rows, registry=historical, out=lambda _line: None)
        visit.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual((visit.fy, visit.quarter), ("2027", "Q1"))
        self.assertEqual((line.fiscal_year, line.quarter), ("2027", "Q1"))
        self.assertEqual(find_misfiled(historical), [])

    def test_the_command_lists_without_writing_and_applies_once(self):
        visit = self._activity(OCT1, "2026", "Q4")
        out = io.StringIO()
        call_command("refile_fy_boundary_rows", stdout=out)
        self.assertIn(f"activities.Activity {visit.pk} (2026-10-01)", out.getvalue())
        self.assertIn("fy 2026 -> 2027", out.getvalue())
        visit.refresh_from_db()
        self.assertEqual(visit.fy, "2026")

        call_command("refile_fy_boundary_rows", "--apply", stdout=io.StringIO())
        visit.refresh_from_db()
        self.assertEqual(visit.fy, "2027")
        out = io.StringIO()
        call_command("refile_fy_boundary_rows", stdout=out)
        self.assertIn("Nothing filed under the day before", out.getvalue())
