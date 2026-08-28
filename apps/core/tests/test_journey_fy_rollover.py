"""Journey 22 — Financial-year rollover, walked end to end.

Journey 22 of the mandate's twenty-two: Close September, Lock history, Open
October, Preserve multi-year loans, Carry approved obligations, Generate new
draft planning, Historical reports remain unchanged.

`test_fiscal_year_rollover` already covers five of those seven well — the cycle
closes, the year-end snapshot is taken, the old activity and SSA survive, the
new cycle opens in priority_setting, and the new review opens in
priorities_draft. Three claims had nothing behind them, and they are the three
where a defect would be silent rather than loud:

**Preserve multi-year loans.** The rollover does not reference loans at all, so
they survive by omission. That is fine today and fragile tomorrow: a future
rollover that starts touching financial records would break a multi-year loan's
history with nothing to notice.

**Carry approved obligations.** Money approved but not yet disbursed when the
year closes is a real commitment. If the rollover drops it, someone is owed
money the platform has forgotten.

**Historical reports remain unchanged.** The existing test asserts the old
year's ledger row still *exists*. A row surviving is not the same as a report
reading the same number — the figures are derived, and a rollover that re-bases
a denominator or shifts a credited period leaves every row in place while every
prior-year report quietly changes. This captures the actual reported figures
before the rollover and requires them identical after.
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.fund_requests.models import AdvanceRequest
from apps.hr.fiscal_year_rollover import rollover_fiscal_year
from apps.hr.models import PerformanceCycle, PerformancePriority, PerformanceReview
from apps.schools.models import School
from apps.targets.models import TargetAchievementLedger, TargetArea
from apps.targets.my_targets import MyTargetQueryService, active_target_areas


class FiscalYearRolloverJourneyTest(TestCase):
    """Close → lock → open → preserve → carry → re-plan → unchanged."""

    OLD_FY = "2030"
    NEW_FY = "2031"

    def setUp(self):
        active_target_areas()
        self.user = User.objects.create_user(
            email="fyj-cceo@example.test",
            name="FYJ CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="test-password",
            is_active=True,
            status="active",
        )
        self.staff = StaffProfile.objects.create(
            user=self.user, title="CCEO", onboarding_state="active"
        )
        self.old_cycle = PerformanceCycle.objects.create(fy=self.OLD_FY)
        self.old_review = PerformanceReview.objects.create(
            staff=self.staff,
            period=f"FY{self.OLD_FY}",
            fy=self.OLD_FY,
            due_date=date(2030, 9, 30),
            stage="priorities_agreed",
        )
        PerformancePriority.objects.create(
            review=self.old_review,
            sequence=1,
            outcome_statement="Publish approved change stories",
            metric_key="mscs",
            target_number=2,
            target="2 approved stories",
            weight=100,
        )
        self.school = School.objects.create(
            school_id="FYJ-SCHOOL",
            name="FYJ School",
            current_fy_ssa_status="done",
            planning_readiness="ready_for_support_planning",
        )
        self.old_activity = Activity.objects.create(
            activity_type="school_visit",
            status="ia_verified",
            fy=self.OLD_FY,
            quarter="Q4",
            planned_date=date(2030, 9, 15),
            responsible_staff_id=self.staff.id,
        )
        mscs_area = TargetArea.objects.get(key="mscs")
        TargetAchievementLedger.objects.create(
            user_id=self.user.id,
            area=mscs_area,
            source_type="mscs",
            source_id="fyj-historic-story",
            activity_date=date(2030, 9, 20),
            fy=self.OLD_FY,
            credited_month=12,
            credited_quarter="Q4",
            quantity=1,
        )

        # An obligation: approved in the old year, money not yet out the door.
        self.budget_line = ActivityScheduleCostLine.objects.create(
            activity=self.old_activity,
            school=self.school,
            cost_setting_key="primary_transport_per_day",
            label="Transport",
            unit_cost=250_000,
            quantity=1,
            amount=250_000,
        )
        self.obligation = AdvanceRequest.objects.create(
            activity=self.old_activity,
            budget_line=self.budget_line,
            responsible_user_id=self.user.id,
            fy=self.OLD_FY,
            quarter="Q4",
            amount=250_000,
            status="approved",
            planned_date=date(2030, 9, 25),
        )

    def _old_year_figures(self):
        """The old year's reported numbers, as a page would render them."""
        areas = active_target_areas()
        return {
            "achievements": MyTargetQueryService.monthly_achievements(
                self.user, self.OLD_FY, areas=areas
            ),
            "ledger_rows": sorted(
                TargetAchievementLedger.objects.filter(fy=self.OLD_FY).values_list(
                    "source_id", "quantity", "credited_month", "credited_quarter"
                )
            ),
        }

    def _roll(self):
        return rollover_fiscal_year(
            fy=self.NEW_FY, as_of=date(2030, 10, 1), initiated_by="journey"
        )

    def test_the_year_closes_without_changing_what_the_old_year_reports(self):
        # ── Capture the old year's figures BEFORE anything moves ──────────
        before = self._old_year_figures()
        self.assertTrue(
            before["ledger_rows"],
            "the fixture recorded no old-year achievement, so an "
            "unchanged-figures assertion would hold over nothing",
        )
        self.assertTrue(
            any(any(v for v in series) for series in before["achievements"].values()),
            "the old year reports no achievement at all, so 'unchanged' would "
            "be trivially true",
        )

        # ── 1-3. Close September, lock history, open October ──────────────
        report = self._roll()
        self.old_cycle.refresh_from_db()
        self.assertEqual(self.old_cycle.status, "closed")
        self.assertTrue(
            self.old_review.snapshots.filter(window="year_end").exists(),
            "the year closed without taking its year-end snapshot",
        )
        new_cycle = PerformanceCycle.objects.get(fy=self.NEW_FY)
        self.assertEqual(new_cycle.active_window, "priority_setting")

        # ── 6. Generate new draft planning ────────────────────────────────
        review = PerformanceReview.objects.get(staff=self.staff, fy=self.NEW_FY)
        self.assertEqual(review.stage, "priorities_draft")
        self.assertFalse(report["alreadyCompleted"])

        # ── 7. Historical reports remain unchanged ────────────────────────
        # The claim the existing coverage could not make. A surviving row is
        # not a stable figure: the numbers are derived, and a rollover that
        # re-bases a denominator or shifts a credited period leaves every row
        # in place while every prior-year report quietly changes.
        after = self._old_year_figures()
        self.assertEqual(
            after["ledger_rows"],
            before["ledger_rows"],
            "the old year's ledger rows changed across the rollover",
        )
        self.assertEqual(
            after["achievements"],
            before["achievements"],
            "the old year REPORTS a different figure after the rollover — "
            "every prior-year report and every audit of them is now wrong",
        )

        self.client.force_login(self.user)
        response = self.client.get(f"/my-performance?fy={self.OLD_FY}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Priority Setting Dashboard")

    def test_an_approved_obligation_survives_the_year_end(self):
        """Carry approved obligations — money owed does not expire in October."""
        self._roll()
        self.obligation.refresh_from_db()
        self.assertEqual(
            self.obligation.status,
            "approved",
            "an obligation approved before year end was silently re-statused "
            "by the rollover",
        )
        self.assertEqual(
            self.obligation.amount,
            250_000,
            "the carried obligation's amount changed across the rollover",
        )
        self.assertEqual(
            self.obligation.fy,
            self.OLD_FY,
            "the obligation was re-dated into the new year, so the old year's "
            "committed spend no longer includes it",
        )

    def test_the_rollover_does_not_reach_into_financial_history(self):
        """Preserve multi-year records — pinned, because it holds by omission.

        The rollover does not reference loans or advances at all today. That is
        why they survive, which means nothing would notice if a future rollover
        started touching financial records. This fails the moment one does.
        """
        before = set(
            AdvanceRequest.objects.values_list(
                "id", "status", "amount", "fy", "disbursed_amount"
            )
        )
        self._roll()
        after = set(
            AdvanceRequest.objects.values_list(
                "id", "status", "amount", "fy", "disbursed_amount"
            )
        )
        self.assertEqual(
            after,
            before,
            "the fiscal-year rollover modified advance records. Financial "
            "history spanning a year end must survive it untouched.",
        )
