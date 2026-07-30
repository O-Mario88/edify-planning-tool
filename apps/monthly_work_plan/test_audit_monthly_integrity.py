"""Financial-integrity audit regression tests (M8 / M2 / M7 / B4 + repair).

Covers:
* M8 — ``_transition`` enforces the legal lifecycle map under lock; a draft
  envelope can no longer jump straight to sent_to_accountant (the hole that
  produced a submitted month with zero snapshots).
* Locked-month snapshot invariant — a LOCKED-status budget without a
  MonthlyBudgetSubmissionSnapshot fails integrity.
* ``repair_monthly_budget_totals`` — dry-run vs --apply on a drifted live
  month and a locked month with no snapshot.
* B4 — approving a budget amendment moves the draft weekly/monthly fund
  request money from the vacated period to the destination period.
"""

from __future__ import annotations

from datetime import date
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.core.exceptions import BadRequest
from apps.monthly_work_plan import country_budget_service as svc
from apps.monthly_work_plan import services
from apps.monthly_work_plan.models import (
    MonthlyBudgetSubmissionSnapshot,
    MonthlyWorkPlanBudget,
    MonthlyWorkPlanBudgetStatus,
)

User = get_user_model()


class _Principal:
    def __init__(self, user):
        self.user_id = user.id
        self.active_role = user.active_role
        self.staff_profile_id = None


def _make_budget(month_key="2026-04", status="draft_generated", **kw):
    return MonthlyWorkPlanBudget.objects.create(
        fy="2026",
        month_key=month_key,
        country_id="Uganda",
        status=status,
        **kw,
    )


class TransitionGuardTest(TestCase):
    """M8 — only legal lifecycle edges may pass through _transition."""

    def setUp(self):
        self.cd = User.objects.create(
            id="cd-m8",
            email="cd-m8@edify.org",
            name="CD M8",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )
        self.cd_p = _Principal(self.cd)

    def test_draft_cannot_jump_to_sent_to_accountant(self):
        b = _make_budget(status=MonthlyWorkPlanBudgetStatus.DRAFT_GENERATED)
        with self.assertRaises(BadRequest):
            services.mark_sent_to_accountant(b.id, self.cd_p)
        b.refresh_from_db()
        self.assertEqual(b.status, MonthlyWorkPlanBudgetStatus.DRAFT_GENERATED)

    def test_draft_cannot_jump_to_approved(self):
        b = _make_budget(status=MonthlyWorkPlanBudgetStatus.DRAFT_GENERATED)
        with self.assertRaises(BadRequest):
            services._transition(
                b.id, MonthlyWorkPlanBudgetStatus.APPROVED_BY_RVP, self.cd_p
            )

    def test_submitted_to_rvp_is_never_a_transition_target(self):
        """The only legal submit path is the guarded send_to_rvp (snapshot)."""
        b = _make_budget(status=MonthlyWorkPlanBudgetStatus.DRAFT_GENERATED)
        with self.assertRaises(BadRequest):
            services._transition(
                b.id, MonthlyWorkPlanBudgetStatus.SUBMITTED_TO_RVP, self.cd_p
            )

    def test_legal_chain_still_passes(self):
        b = _make_budget(status=MonthlyWorkPlanBudgetStatus.SUBMITTED_TO_RVP)
        b = services._transition(
            b.id,
            MonthlyWorkPlanBudgetStatus.APPROVED_BY_RVP,
            self.cd_p,
            field="rvp_reviewed_at",
            actor_field="rvp_reviewed_by_user_id",
        )
        self.assertEqual(b.status, MonthlyWorkPlanBudgetStatus.APPROVED_BY_RVP)
        result = services.mark_sent_to_accountant(b.id, self.cd_p)
        self.assertEqual(result.status, MonthlyWorkPlanBudgetStatus.SENT_TO_ACCOUNTANT)
        self.assertIsNotNone(result.sent_to_accountant_at)

    def test_submit_to_rvp_routes_through_guarded_path_and_snapshots(self):
        """services.submit_to_rvp must produce an immutable snapshot (M8)."""
        b = _make_budget(status=MonthlyWorkPlanBudgetStatus.DRAFT_GENERATED)
        data = services.submit_to_rvp(b.id, self.cd_p)
        self.assertEqual(data["status"], "submitted_to_rvp")
        b.refresh_from_db()
        self.assertEqual(b.status, MonthlyWorkPlanBudgetStatus.SUBMITTED_TO_RVP)
        self.assertEqual(b.snapshots.count(), 1)
        self.assertEqual(b.submission_version, 1)


class LockedMonthSnapshotCheckTest(TestCase):
    """A LOCKED-status month with zero snapshots must fail integrity."""

    LABEL = "Locked month has an immutable submission snapshot"

    def _check(self, budget):
        checks = svc._integrity_checks([], [], budget)
        return next(c for c in checks if c["label"] == self.LABEL)

    def test_locked_month_without_snapshot_fails(self):
        b = _make_budget(status="submitted_to_rvp")
        check = self._check(b)
        self.assertEqual(check["status"], "failed")
        self.assertIn("no submission snapshot", check["detail"])

    def test_locked_month_with_snapshot_passes(self):
        b = _make_budget(status="submitted_to_rvp", submission_version=1)
        MonthlyBudgetSubmissionSnapshot.objects.create(
            monthly_budget=b,
            version=1,
            fy=b.fy,
            month_key=b.month_key,
            submitted_at=timezone.now(),
        )
        self.assertEqual(self._check(b)["status"], "passed")

    def test_live_month_passes(self):
        b = _make_budget(status="draft_generated")
        self.assertEqual(self._check(b)["status"], "passed")


class RepairCommandTest(TestCase):
    """repair_monthly_budget_totals: dry-run reports, --apply repairs."""

    def _run(self, *args):
        out = StringIO()
        call_command("repair_monthly_budget_totals", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_reports_but_does_not_write(self):
        drifted = _make_budget(
            month_key="2026-04",
            status="draft_generated",
            program_total=999_999,
            total_amount=999_999,
        )
        hole = _make_budget(month_key="2026-05", status="sent_to_accountant")
        output = self._run()
        self.assertIn("DRY RUN", output)
        self.assertIn("drifted=1", output)
        self.assertIn("repaired=0", output)
        self.assertIn("reverted=0", output)
        self.assertIn("would revert", output)
        drifted.refresh_from_db()
        hole.refresh_from_db()
        self.assertEqual(drifted.program_total, 999_999)
        self.assertEqual(hole.status, "sent_to_accountant")

    def test_apply_repairs_drift_and_reverts_snapshotless_locked_month(self):
        drifted = _make_budget(
            month_key="2026-04",
            status="draft_generated",
            program_total=999_999,
            total_amount=999_999,
        )
        hole = _make_budget(month_key="2026-05", status="sent_to_accountant")
        # A properly-snapshotted locked month must NOT be touched.
        legit = _make_budget(
            month_key="2026-06", status="approved_by_rvp", submission_version=1
        )
        MonthlyBudgetSubmissionSnapshot.objects.create(
            monthly_budget=legit, version=1, fy=legit.fy, month_key=legit.month_key
        )

        output = self._run("--apply")
        self.assertIn("scanned=3", output)
        self.assertIn("drifted=1", output)
        self.assertIn("repaired=1", output)
        self.assertIn("reverted=1", output)

        drifted.refresh_from_db()
        self.assertEqual(drifted.program_total, 0)
        self.assertEqual(drifted.total_amount, 0)
        hole.refresh_from_db()
        self.assertEqual(hole.status, "draft_generated")
        legit.refresh_from_db()
        self.assertEqual(legit.status, "approved_by_rvp")


class AmendmentDraftRequestResyncTest(TestCase):
    """B4 — approving an amendment moves draft weekly/monthly request money
    from the vacated period to the destination period."""

    OLD_DAY = date(2026, 7, 15)  # Wednesday
    OLD_WEEK = date(2026, 7, 13)  # its Monday
    NEW_DAY = date(2026, 8, 12)  # Wednesday
    NEW_WEEK = date(2026, 8, 10)  # its Monday

    def setUp(self):
        from apps.accounts.models import StaffProfile
        from apps.activities.models import Activity, ActivityScheduleCostLine
        from apps.core.calendar_policy import CalendarBlock, PublicHoliday
        from apps.geography.models import District, Region
        from apps.schools.models import School

        # Keep the amendment dates schedulable even if reference data seeded
        # holidays/blackouts around them.
        PublicHoliday.objects.filter(date__in=[self.OLD_DAY, self.NEW_DAY]).delete()
        CalendarBlock.objects.filter(
            start_date__lte=self.NEW_DAY, end_date__gte=self.OLD_DAY
        ).delete()

        self.cceo = User.objects.create_user(
            email="cceo-b4@test.org",
            name="B4 CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="password",
            is_active=True,
        )
        StaffProfile.objects.create(user=self.cceo, title="CCEO")
        self.accountant = User.objects.create_user(
            email="acct-b4@test.org",
            name="B4 Accountant",
            roles=["Accountant"],
            active_role="Accountant",
            password="password",
            is_active=True,
        )
        self.acct_p = _Principal(self.accountant)

        region = Region.objects.create(name="B4 Region")
        district = District.objects.create(name="B4 District", region=region)
        school = School.objects.create(
            school_id="B4-SCH",
            name="B4 School",
            region=region,
            district=district,
        )

        self.activity = Activity.objects.create(
            activity_type="school_visit",
            school=school,
            fy="2026",
            quarter="Q4",
            responsible_staff_id=self.cceo.id,
            status="scheduled",
            delivery_type="staff",
            planned_date=self.OLD_DAY,
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 7, 15, 9, 0)),
            month=7,
            week_start_date=self.OLD_WEEK,
            week_end_date=date(2026, 7, 19),
        )
        self.line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            cost_setting_key="transport",
            label="Transport",
            unit_cost=80_000,
            quantity=1,
            amount=80_000,
            currency="UGX",
            responsible_user=self.cceo.id,
            fiscal_year="2026",
            month=7,
            planned_date=self.OLD_DAY,
            week_start_date=self.OLD_WEEK,
            week_end_date=date(2026, 7, 19),
        )

    def _weekly(self, week_start):
        from apps.fund_requests.models import WeeklyFundRequest

        return WeeklyFundRequest.objects.filter(
            responsible_user=self.cceo.id, week_start_date=week_start
        ).first()

    def _monthly(self, month):
        from apps.fund_requests.models import FundRequest, FundRequestPeriod

        return FundRequest.objects.filter(
            submitted_by_user_id=self.cceo.id,
            period=FundRequestPeriod.MONTHLY,
            period_key=f"2026-M{month}",
            scope="own",
        ).first()

    def test_approved_amendment_moves_draft_request_money(self):
        from apps.budget.amendment_service import approve_amendment
        from apps.budget.models import BudgetAmendment
        from apps.fund_requests.monthly_service import (
            sync_monthly_drafts_for_activity,
        )
        from apps.fund_requests.weekly_service import generate_weekly_fund_request

        # Seed the OLD period's draft weekly + monthly requests.
        generate_weekly_fund_request(self.cceo.id, self.OLD_WEEK.isoformat())
        sync_monthly_drafts_for_activity(self.activity)
        old_weekly = self._weekly(self.OLD_WEEK)
        self.assertIsNotNone(old_weekly)
        self.assertEqual(old_weekly.total_amount, 80_000)
        old_monthly = self._monthly(7)
        self.assertIsNotNone(old_monthly)
        self.assertEqual(old_monthly.total_amount, 80_000)

        amendment = BudgetAmendment.objects.create(
            activity=self.activity,
            original_date=self.OLD_DAY,
            new_date=self.NEW_DAY,
            original_amount=80_000,
            original_fy="2026",
            original_quarter="Q4",
            new_fy="2026",
            new_quarter="Q4",
            reason="School closed for renovation.",
            requested_by=self.cceo.id,
        )
        approve_amendment(amendment.id, {"note": "ok"}, self.acct_p)

        # The vacated week's draft no longer holds the money.
        old_weekly = self._weekly(self.OLD_WEEK)
        self.assertTrue(
            old_weekly is None or old_weekly.total_amount == 0,
            "vacated draft week kept the money",
        )
        # The destination week gained it.
        new_weekly = self._weekly(self.NEW_WEEK)
        self.assertIsNotNone(new_weekly, "destination week never gained the money")
        self.assertEqual(new_weekly.total_amount, 80_000)

        # Monthly drafts follow the same movement.
        old_monthly = self._monthly(7)
        self.assertTrue(old_monthly is None or old_monthly.total_amount == 0)
        new_monthly = self._monthly(8)
        self.assertIsNotNone(new_monthly)
        self.assertEqual(new_monthly.total_amount, 80_000)

        # And the cost line itself moved period, identity intact.
        self.line.refresh_from_db()
        self.assertEqual(self.line.planned_date, self.NEW_DAY)
        self.assertEqual(self.line.month, 8)
        self.assertEqual(self.line.week_start_date, self.NEW_WEEK)
