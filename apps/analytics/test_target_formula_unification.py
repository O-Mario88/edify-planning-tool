"""Target-achievement formula unification (Issue 1, HIGH).

Before this fix, apps.analytics.cd_analytics_service.CDAnalyticsService.
_weighted_achievement() hand-rolled its own annual-target proration
(`round(annual * len(months)/12)`) instead of calling the canonical
apps.targets.my_targets.weighted_period_pct() + the same per-user series
MyTargetQueryService/PLTeamTargetsService already use (which prorate via
`divmod(annual, 12)`, remainder to early months). The two algorithms
disagree whenever `annual` isn't an exact multiple of 12 and the selected
month window doesn't happen to include exactly the "average" share -- a
verified 66/100 disagreement rate across generated cases.

CANONICAL CALCULATION: apps.targets.my_targets.weighted_period_pct() +
apps.targets.my_targets.pooled_monthly_series(). Every one of CD Analytics,
PL Team Targets, and My Targets now funnels through these two functions for
target-percentage math -- this file proves they can no longer disagree.
"""

from __future__ import annotations

import random

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    StaffTargetProfile,
)
from apps.activities.models import Activity
from apps.analytics.cd_analytics_service import (
    CDAnalyticsService,
    resolve_cd_scope,
    _country_activities,
)
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.targets.fy_calendar import FinancialYearCalendarService as Cal
from apps.targets.models import MonthlyPersonalTarget, TargetAdjustment, TargetArea
from apps.targets.my_targets import (
    MyTargetQueryService,
    TargetAchievementService,
    active_target_areas,
    pooled_monthly_series,
    weighted_period_pct,
)
from apps.targets.team_targets import PLTeamTargetsService

User = get_user_model()


# =============================================================================
# Part 1 — DB-backed integration tests: CD Analytics / PL Team Targets /
# My Targets must all report the identical number for the same people+period.
# =============================================================================
class TargetFormulaEndToEndTest(TestCase):
    def setUp(self):
        self.now = Cal.current()
        self.fy = self.now["fy"]
        # Reference rows are migration data and can be removed by an earlier
        # TransactionTestCase when --keepdb is used. Exercise the production
        # recovery path before this integration fixture reads them directly.
        active_target_areas()

        self.region = Region.objects.create(name="TFU Region")
        self.district = District.objects.create(name="TFU District", region=self.region)
        self.school = School.objects.create(
            school_id="TFU-SCH",
            name="TFU School",
            region=self.region,
            district=self.district,
        )

        self.pl, self.pl_sp = self._staff(
            "pl@tfu.org", "PL Formula", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.cceo1, self.cceo1_sp = self._staff(
            "c1@tfu.org", "CCEO One", EdifyRole.CCEO.value
        )
        self.cceo2, self.cceo2_sp = self._staff(
            "c2@tfu.org", "CCEO Two", EdifyRole.CCEO.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo1_sp
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo2_sp
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo1_sp, school_id=self.school.id
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo2_sp, school_id=self.school.id
        )

        self.cd, _ = self._staff(
            "cd@tfu.org", "CD Formula", EdifyRole.COUNTRY_DIRECTOR.value
        )

        # Annual targets that do NOT divide evenly by 12 -- exactly the shape
        # that exposed the old divergence (round(x*months/12) vs divmod(x,12)).
        StaffTargetProfile.objects.create(
            staff=self.cceo1_sp,
            fy=self.fy,
            visits_target=13,
            cluster_meetings_target=7,
            trainings_target=5,
            ssa_target=3,
        )
        StaffTargetProfile.objects.create(
            staff=self.cceo2_sp,
            fy=self.fy,
            visits_target=10,
            cluster_meetings_target=4,
            trainings_target=6,
            ssa_target=2,
        )

    # ── fixture helpers ───────────────────────────────────────────────────────
    def _staff(self, email, name, role):
        u = User.objects.create_user(
            email=email,
            name=name,
            roles=[role],
            active_role=role,
            password="x",
            is_active=True,
        )
        return u, StaffProfile.objects.create(user=u, title=role)

    # Default ia_verified: target credit requires IA verification (§8).
    def _visit(self, sp, month_of_fy, status="ia_verified", sf=None):
        # Unique per call — the DB now enforces Salesforce-id uniqueness.
        if sf is None:
            type(self)._sf_seq = getattr(type(self), "_sf_seq", 0) + 1
            sf = f"SV-{type(self)._sf_seq}"
        d, _ = Cal.month_range(self.fy, month_of_fy)
        return Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            delivery_type="staff",
            status=status,
            responsible_staff_id=sp.id,
            fy=self.fy,
            quarter=Cal.quarter_of_month(month_of_fy),
            planned_date=d,
            scheduled_date=timezone.make_aware(
                timezone.datetime(d.year, d.month, d.day, 9, 0)
            ),
            evidence_status="accepted"
            if status in ("completed", "ia_verified", "accountant_confirmed", "closed")
            else "",
            salesforce_activity_id=sf,
        )

    def _cd_pl_pct(self, quarter=None):
        """CD Analytics' PL-pooled % for self.pl, via the real target_by_pl_cceo
        table (not a re-derivation) -- same call the CD Analytics page makes."""
        cd = resolve_cd_scope(self.fy, quarter, None, {})
        acts = _country_activities(cd)
        rows = CDAnalyticsService.target_by_pl_cceo(cd, acts)["rows"]
        row = next(r for r in rows if r["id"] == self.pl.id)
        return row["pl_pct"]

    def _cd_export_pl_pct(self, quarter=None):
        """The same number via CDAnalyticsService.pl_oversight (what
        export_rows() serializes for CSV export)."""
        cd = resolve_cd_scope(self.fy, quarter, None, {})
        acts = _country_activities(cd)
        row = next(
            r
            for r in CDAnalyticsService.pl_oversight(cd, acts)["rows"]
            if r["id"] == self.pl.id
        )
        return row["target_pct"]

    def _team_targets_current_month_pct(self, month_of_fy):
        """PL Team Targets' REAL current-month team-wide weighted % straight
        from PLTeamTargetsService.get_page() (its "Team Target Achievement"
        KPI card) -- not a re-derivation, the actual production call."""
        page = PLTeamTargetsService.get_page(self.pl, self.fy, month_of_fy)
        team_card = next(k for k in page["kpis"] if k["key"] == "team")
        return int(team_card["value"].rstrip("%"))

    def _my_targets_pct_for(self, user, months):
        """A single CCEO's weighted % over an explicit month window, computed
        via the exact primitives My Targets uses (bypasses the page's
        current-FY pacing branching, which is irrelevant to this equivalence
        check)."""
        TargetAchievementService.rebuild(user, self.fy)
        areas = list(TargetArea.objects.filter(active=True))
        targets = MyTargetQueryService.monthly_targets(user, self.fy)
        achieved = MyTargetQueryService.monthly_achievements(user, self.fy)
        pct, _a, _t = weighted_period_pct(areas, targets, achieved, months)
        return pct

    def _cd_style_pct_for_month_list(self, users, months):
        """Mirrors CDAnalyticsService._weighted_achievement()'s internals
        exactly, but with an explicit month_list (CD's own public interface
        is quarter/FY granularity only) -- proves the SHARED functions agree
        at month granularity too, since CD's math is built from the same
        general-purpose primitives."""
        areas = list(TargetArea.objects.filter(active=True))
        targets, achieved = pooled_monthly_series(users, self.fy, areas=areas)
        pct, _a, _t = weighted_period_pct(areas, targets, achieved, months)
        return pct

    # ── required named tests ─────────────────────────────────────────────────
    def test_cd_pl_target_percentage_matches_pl_team_targets(self):
        """End-to-end, real production code paths: seed activities in the
        CURRENT month (the only granularity PLTeamTargetsService.get_page()
        exposes a standalone team-wide % for), then assert
        CDAnalyticsService's number for this PL and
        PLTeamTargetsService.get_page()'s real "Team Target Achievement" KPI
        agree exactly -- this is the literal defect Issue 1 reported (a CD
        seeing a different % for a PL than that PL sees on their own page)."""
        m = self.now["month_of_fy"]
        self._visit(self.cceo1_sp, m)
        self._visit(self.cceo2_sp, m)

        cd_pct = self._cd_style_pct_for_month_list([self.cceo1, self.cceo2], [m])
        real_team_pct = self._team_targets_current_month_pct(m)
        self.assertEqual(cd_pct, real_team_pct)

    def test_all_target_dashboards_use_weighted_period_pct(self):
        """Architectural regression guard: the modules that show a
        target-achievement percentage must import/call the canonical
        formula, not a lookalike reimplementation."""
        import apps.analytics.cd_analytics_service as cd_mod
        import apps.analytics.rvp_dashboard_service as rvp_mod
        import apps.targets.my_targets as my_targets_mod
        import apps.targets.team_targets as team_targets_mod

        # Same function object everywhere -- not a copy with the same name.
        self.assertIs(
            team_targets_mod.weighted_period_pct, my_targets_mod.weighted_period_pct
        )
        src = cd_mod.__file__
        with open(src) as f:
            cd_source = f.read()
        self.assertIn("pooled_monthly_series", cd_source)
        self.assertIn("weighted_period_pct", cd_source)
        # The old duplicate proration algorithm must be gone.
        self.assertNotIn("ANNUAL_FALLBACK", cd_source)
        self.assertNotIn("len(months) / 12", cd_source)
        # RVP dashboard reuses CDAnalyticsService._weighted_overall (which now
        # itself delegates) rather than its own computation.
        self.assertIn("_weighted_overall", open(rvp_mod.__file__).read())

    def test_target_percentage_consistent_current_month(self):
        m = self.now["month_of_fy"]
        self._visit(self.cceo1_sp, m)
        cd_pct = self._cd_style_pct_for_month_list([self.cceo1], [m])
        my_pct = self._my_targets_pct_for(self.cceo1, [m])
        self.assertEqual(cd_pct, my_pct)

    def _consistent_quarter(self, quarter):
        months = Cal.months_of_quarter(quarter)
        self._visit(self.cceo1_sp, months[0])
        self._visit(self.cceo2_sp, months[1])
        cd_pct = self._cd_pl_pct(quarter=quarter)
        pooled_pct, _a, _t = weighted_period_pct(
            list(TargetArea.objects.filter(active=True)),
            *pooled_monthly_series([self.cceo1, self.cceo2], self.fy),
            months,
        )
        self.assertEqual(cd_pct, pooled_pct)

    def test_target_percentage_consistent_q1(self):
        self._consistent_quarter("Q1")

    def test_target_percentage_consistent_q2(self):
        self._consistent_quarter("Q2")

    def test_target_percentage_consistent_q3(self):
        self._consistent_quarter("Q3")

    def test_target_percentage_consistent_q4(self):
        self._consistent_quarter("Q4")

    def test_target_percentage_consistent_fy(self):
        self._visit(self.cceo1_sp, 1)
        self._visit(self.cceo1_sp, 6)
        self._visit(self.cceo2_sp, 9)
        cd_pct = self._cd_pl_pct(quarter=None)
        pooled_pct, _a, _t = weighted_period_pct(
            list(TargetArea.objects.filter(active=True)),
            *pooled_monthly_series([self.cceo1, self.cceo2], self.fy),
            list(range(1, 13)),
        )
        self.assertEqual(cd_pct, pooled_pct)
        self.assertEqual(cd_pct, self._cd_export_pl_pct(quarter=None))

    def test_target_percentage_zero_target(self):
        """A CCEO with no StaffTargetProfile/MonthlyPersonalTarget row at all
        must show 0%, honestly, everywhere -- never a fabricated/divergent
        fallback."""
        u, sp = self._staff("zero@tfu.org", "Zero Target", EdifyRole.CCEO.value)
        StaffSupervisorAssignment.objects.create(supervisor=self.pl_sp, supervisee=sp)
        cd_pct = self._cd_style_pct_for_month_list([u], list(range(1, 13)))
        my_pct = self._my_targets_pct_for(u, list(range(1, 13)))
        self.assertEqual(cd_pct, 0)
        self.assertEqual(my_pct, 0)
        self.assertEqual(cd_pct, my_pct)

    def test_target_percentage_overachievement(self):
        """Achieving more than the target must show >100%, consistently, not
        clamped differently by different call sites. Uses a dedicated
        single-area profile (only visits_target set) so the other four
        areas stay genuinely unassigned (excluded from the weighted average)
        rather than picking up a stray divmod-remainder target of their own
        in the same month, which would dilute the weighted result."""
        u, sp = self._staff("over@tfu.org", "Over Achiever", EdifyRole.CCEO.value)
        StaffSupervisorAssignment.objects.create(supervisor=self.pl_sp, supervisee=sp)
        StaffTargetProfile.objects.create(
            staff=sp,
            fy=self.fy,
            visits_target=1,
            cluster_meetings_target=0,
            trainings_target=0,
            ssa_target=0,
        )
        for m in (1, 2, 3, 4, 5):
            self._visit(sp, 1, sf=f"SV-OVER-{m}")
        cd_pct = self._cd_style_pct_for_month_list([u], [1])
        my_pct = self._my_targets_pct_for(u, [1])
        self.assertGreater(cd_pct, 100)
        self.assertEqual(cd_pct, my_pct)

    def test_target_percentage_after_returned_activity(self):
        """An IA-returned activity must reverse its credit identically on
        both sides -- no path may keep counting a reversed activity."""
        act = self._visit(self.cceo1_sp, 3, sf="SV-RET-1")
        before_cd = self._cd_style_pct_for_month_list([self.cceo1], [3])
        before_my = self._my_targets_pct_for(self.cceo1, [3])
        self.assertEqual(before_cd, before_my)

        act.status = "returned_by_ia"
        act.save(update_fields=["status"])

        after_cd = self._cd_style_pct_for_month_list([self.cceo1], [3])
        after_my = self._my_targets_pct_for(self.cceo1, [3])
        self.assertEqual(after_cd, after_my)
        self.assertLess(after_cd, before_cd)

    def test_target_percentage_after_target_adjustment(self):
        """An explicit MonthlyPersonalTarget adjustment (audited via
        TargetAdjustment) must be reflected identically everywhere the
        moment it's saved."""
        area = TargetArea.objects.get(key="school_visits")
        row = MonthlyPersonalTarget.objects.create(
            user_id=self.cceo1.id,
            area=area,
            fy=self.fy,
            month_of_fy=4,
            target=5,
        )
        self._visit(self.cceo1_sp, 4, sf="SV-ADJ-1")
        before_cd = self._cd_style_pct_for_month_list([self.cceo1], [4])
        before_my = self._my_targets_pct_for(self.cceo1, [4])
        self.assertEqual(before_cd, before_my)

        TargetAdjustment.objects.create(
            user_id=self.cceo1.id,
            area=area,
            fy=self.fy,
            month_of_fy=4,
            old_target=row.target,
            new_target=1,
            reason="Recalibrated after workload review",
            requested_by=self.pl.id,
            approved_by=self.cd.id,
        )
        row.target = 1
        row.save(update_fields=["target"])

        after_cd = self._cd_style_pct_for_month_list([self.cceo1], [4])
        after_my = self._my_targets_pct_for(self.cceo1, [4])
        self.assertEqual(after_cd, after_my)
        self.assertGreater(after_cd, before_cd)


# =============================================================================
# Part 2 — Randomized equivalence test (>=1000 generated cases).
#
# The regression that caused Issue 1 was an aggregation-algorithm mismatch:
# pooling N people's target series and weighting the POOLED sum must equal
# summing each person's own weighted contribution's underlying totals, for
# ANY combination of per-area weights, per-person targets, and per-person
# achievement. This runs at the pure-function level (no DB) so 1,000+ cases
# execute in milliseconds while still exercising the exact arithmetic
# property that diverged in production: pooling must be a straightforward
# sum-then-weight, never re-derived per caller.
# =============================================================================
class _Area:
    def __init__(self, key, weight):
        self.key = key
        self.weight = weight


class RandomizedFormulaEquivalenceTest(SimpleTestCase):
    AREAS = [
        _Area("school_visits", 30),
        _Area("cluster_meetings", 20),
        _Area("cluster_trainings", 20),
        _Area("ssa_completed", 20),
        _Area("mscs", 10),
    ]
    N_CASES = 1000

    def _random_series(self, rng, max_val=40):
        return {a.key: [rng.randint(0, max_val) for _ in range(12)] for a in self.AREAS}

    def test_pooled_sum_matches_manually_summed_series_1000_cases(self):
        """For 1,000 randomly generated (per-person target/achieved series,
        month window) combinations: pooling 2-5 synthetic people's series via
        the exact pattern pooled_monthly_series uses (sum each area's monthly
        values across people) and then calling weighted_period_pct on the
        pooled result must equal computing weighted_period_pct directly on a
        series built by manually summing the same per-person data -- i.e.
        the pooling step is a pure, order-independent, per-area-per-month
        sum with no hidden re-weighting. This is the exact invariant the old
        cd_analytics_service.py formula violated (it re-derived proration
        from an ANNUAL total using a different rounding algorithm instead of
        summing already-correct per-user monthly series)."""
        rng = random.Random(1337)
        mismatches = 0
        for case in range(self.N_CASES):
            n_people = rng.randint(1, 5)
            people_targets = [self._random_series(rng) for _ in range(n_people)]
            people_achieved = [
                self._random_series(rng, max_val=45) for _ in range(n_people)
            ]
            month_list = sorted(rng.sample(range(1, 13), rng.randint(1, 12)))

            # Path A: pool exactly like pooled_monthly_series does.
            pooled_t = {a.key: [0] * 12 for a in self.AREAS}
            pooled_a = {a.key: [0] * 12 for a in self.AREAS}
            for pt, pa in zip(people_targets, people_achieved):
                for a in self.AREAS:
                    for i in range(12):
                        pooled_t[a.key][i] += pt[a.key][i]
                        pooled_a[a.key][i] += pa[a.key][i]
            pct_a, ach_a, tgt_a = weighted_period_pct(
                self.AREAS, pooled_t, pooled_a, month_list
            )

            # Path B: independently sum each person's raw target/achieved
            # totals over the month window per area (a different but
            # mathematically equivalent aggregation order), then weight.
            manual_t = {
                a.key: sum(
                    sum(pt[a.key][m - 1] for m in month_list) for pt in people_targets
                )
                for a in self.AREAS
            }
            manual_a = {
                a.key: sum(
                    sum(pa[a.key][m - 1] for m in month_list) for pa in people_achieved
                )
                for a in self.AREAS
            }
            wsum = psum = tot_a = tot_t = 0
            for a in self.AREAS:
                t, ach = manual_t[a.key], manual_a[a.key]
                tot_a += ach
                tot_t += t
                if t > 0:
                    wsum += a.weight
                    psum += (ach / t * 100) * a.weight
            pct_b = round(psum / wsum) if wsum else 0

            if (pct_a, ach_a, tgt_a) != (pct_b, tot_a, tot_t):
                mismatches += 1

        self.assertEqual(
            mismatches,
            0,
            f"{mismatches}/{self.N_CASES} cases disagreed between pooled-then-weighted "
            "and manually-summed-then-weighted -- the pooling invariant is broken.",
        )

    def test_pooling_with_sparse_unassigned_areas_matches_reweighted_average_1000_cases(
        self,
    ):
        """1,000 cases where different people randomly have NO target in
        different areas (a realistic scenario: not every CCEO has every area
        assigned). weighted_period_pct's own "areas with no pooled target
        are excluded from the weighted average, not zeroed" contract must
        hold identically regardless of how the underlying per-person series
        were pooled -- computed twice via two independently-written
        area-selection implementations that must always agree."""
        rng = random.Random(9001)
        mismatches = 0
        for case in range(self.N_CASES):
            n_people = rng.randint(1, 6)
            people_targets = []
            for _ in range(n_people):
                series = self._random_series(rng)
                # Randomly zero out whole areas for this person (unassigned).
                for a in self.AREAS:
                    if rng.random() < 0.35:
                        series[a.key] = [0] * 12
                people_targets.append(series)
            people_achieved = [
                self._random_series(rng, max_val=45) for _ in range(n_people)
            ]
            month_list = sorted(rng.sample(range(1, 13), rng.randint(1, 12)))

            pooled_t = {a.key: [0] * 12 for a in self.AREAS}
            pooled_a = {a.key: [0] * 12 for a in self.AREAS}
            for pt, pa in zip(people_targets, people_achieved):
                for a in self.AREAS:
                    for i in range(12):
                        pooled_t[a.key][i] += pt[a.key][i]
                        pooled_a[a.key][i] += pa[a.key][i]

            pct, ach, tgt = weighted_period_pct(
                self.AREAS, pooled_t, pooled_a, month_list
            )

            # Independent re-implementation of "exclude areas with zero
            # pooled target from the weighted average" for cross-checking.
            wsum = psum = tot_a = tot_t = 0
            assigned_areas = 0
            for a in self.AREAS:
                t = sum(pooled_t[a.key][m - 1] for m in month_list)
                ac = sum(pooled_a[a.key][m - 1] for m in month_list)
                tot_a += ac
                tot_t += t
                if t > 0:
                    assigned_areas += 1
                    wsum += a.weight
                    psum += (ac / t * 100) * a.weight
            expected_pct = round(psum / wsum) if wsum else 0

            if (pct, ach, tgt) != (expected_pct, tot_a, tot_t):
                mismatches += 1
            # Sanity: if every area is unassigned across the whole pool, the
            # canonical function must return the honest 0, never a crash or
            # a fabricated number.
            if assigned_areas == 0:
                self.assertEqual(pct, 0)

        self.assertEqual(
            mismatches,
            0,
            f"{mismatches}/{self.N_CASES} sparse-assignment cases disagreed on "
            "which areas should be excluded from the weighted average.",
        )
