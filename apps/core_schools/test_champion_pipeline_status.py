"""The champion pipeline's two halves have to agree on what a plan status means.

`upload_follow_up_ssa` — the follow-up assessment that MAKES a school a
champion candidate — moves CorePlan.status off "Active" to "Champion
Candidate" or "Impact Measured". `ChampionEligibilityService.calculate_score`
looked the plan up with `status="Active"` and, finding none, returned
`score 0.0 / eligible False / "No active Core Plan"`. So the single act that
qualifies a school also deleted it from the champion engine, the candidates
page and the review drawer's metrics. Neither function had a test, which is
why the contradiction survived.

"Active", "Impact Measured" and "Champion Candidate" are all stages of a plan
that is still running this year's package; only Archived/Cancelled/Exited end
it. These tests pin that reading from both ends, and keep the controls that
make the fix mean something: a school with no plan, and a school whose plan is
genuinely closed, must both still be ineligible.

They also pin the FY half of the same lookup. Nothing ever closes a finished
package (see apps.system_health.services — the "Package Complete" check has no
writer), so at the 1 Oct rollover a school owns two plans that both read as
live, and `.first()` on an unordered queryset orders by primary key: FY2026's
legacy `cplan-{school}` beats every later FY's `cplan-{school}-{fy}`, so the
stale package would have won every read for ever. The live package is the one
for the operational FY.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import User
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.core_schools import services as core_services
from apps.core_schools.champion_services import ChampionEligibilityService
from apps.core_schools.models import (
    CoreActivitySlot,
    CorePlan,
    CoreSchoolProfile,
    cplan_id,
    cprof_id,
)
from apps.core_schools.services import create_package_slots, upload_follow_up_ssa
from apps.geography.models import District, Region
from apps.schools.models import School

ALL_INTERVENTIONS = [i.value for i in SsaIntervention]


def _scores(value: float) -> list[dict]:
    return [{"intervention": i, "score": value} for i in ALL_INTERVENTIONS]


class ChampionPipelineFixture(TestCase):
    """Onboarded core school, nine-slot package, a confirmed baseline SSA."""

    def setUp(self):
        self.fy = get_operational_fy()
        self.prev_fy = str(int(self.fy) - 1)
        self.region = Region.objects.create(name="Champ Status Region")
        self.district = District.objects.create(
            name="Champ Status District", region=self.region
        )
        self.user = User.objects.create(
            email="ia@champ-status.test",
            name="Ida Assessor",
            roles=["IMPACT_ASSESSMENT"],
            active_role="IMPACT_ASSESSMENT",
            is_active=True,
        )

    def _school(self, school_id: str) -> School:
        return School.objects.create(
            school_id=school_id,
            name=f"School {school_id}",
            school_type="core",
            region=self.region,
            district=self.district,
        )

    def _plan(self, school_id: str, fy: str | None = None, **kwargs) -> CorePlan:
        fy = fy or self.fy
        plan = CorePlan.objects.create(
            id=cplan_id(school_id, fy=fy),
            school_id=school_id,
            fy=fy,
            baseline_average=kwargs.pop("baseline_average", 7.0),
            **kwargs,
        )
        create_package_slots(plan, school_id, ["leadership"])
        return plan

    def _profile(self, school_id: str, plan: CorePlan) -> CoreSchoolProfile:
        return CoreSchoolProfile.objects.create(
            id=cprof_id(school_id),
            school_id=school_id,
            core_plan=plan,
            core_start_fy=plan.fy,
        )

    def _complete_slots(self, plan: CorePlan, how_many: int | None = None) -> None:
        """Mark slots done with the status Activity.save() really mirrors."""
        qs = CoreActivitySlot.objects.filter(core_plan=plan).order_by("id")
        ids = list(qs.values_list("id", flat=True))
        if how_many is not None:
            ids = ids[:how_many]
        CoreActivitySlot.objects.filter(id__in=ids).update(status="closed")

    def _baseline_ssa(self, school: School, value: float = 7.0):
        from apps.ssa.services import upload as ssa_upload

        return ssa_upload(
            {
                "schoolId": school.school_id,
                "dateOfSsa": (timezone.now() - timedelta(days=300)).date().isoformat(),
                "scores": _scores(value),
            },
            self.user,
        )

    def _follow_up(self, plan: CorePlan, value: float) -> dict:
        return upload_follow_up_ssa(
            plan.id,
            {
                "dateOfSsa": timezone.now().date().isoformat(),
                "scores": _scores(value),
            },
            self.user,
        )


class ImpactMeasurementKeepsTheSchoolInTheEngineTest(ChampionPipelineFixture):
    def test_a_champion_candidate_plan_is_still_scored(self):
        """The status the pipeline writes on success must not hide the plan."""
        school = self._school("CH-CAND")
        plan = self._plan(school.school_id)
        self._profile(school.school_id, plan)
        self._complete_slots(plan)
        self._baseline_ssa(school, 7.0)

        result = self._follow_up(plan, 8.5)
        self.assertTrue(result["championCandidate"])
        plan.refresh_from_db()
        self.assertEqual(plan.status, "Champion Candidate")

        metrics = ChampionEligibilityService.calculate_score(school)

        self.assertNotIn(
            "reason",
            metrics,
            "the follow-up SSA that qualifies a school must not hide its plan",
        )
        self.assertTrue(metrics["eligible"], metrics)
        self.assertEqual(metrics["completed_slots"], 9)
        self.assertEqual(metrics["total_slots"], 9)
        self.assertGreater(metrics["score"], 0.0)

    def test_the_candidate_reaches_the_champion_candidates_sweep(self):
        school = self._school("CH-SWEEP")
        plan = self._plan(school.school_id)
        profile = self._profile(school.school_id, plan)
        self._complete_slots(plan)
        self._baseline_ssa(school, 7.0)
        self._follow_up(plan, 8.5)

        candidates = ChampionEligibilityService.evaluate_all()

        self.assertEqual(
            [c["school"].school_id for c in candidates],
            [school.school_id],
            "evaluate_all feeds the champion candidates page",
        )
        profile.refresh_from_db()
        self.assertEqual(profile.champion_status, "Potential Champion")

    def test_candidate_sweep_query_count_is_constant_as_schools_are_added(self):
        """The candidates page must batch the estate instead of scoring N+1.

        This is the regression for the live freeze: the old implementation
        exceeded Django's 9,000-query capture limit and took 23.5 seconds on
        the development clone.  A larger candidate population must add rows,
        not database round trips.
        """

        def eligible_school(school_id: str):
            school = self._school(school_id)
            plan = self._plan(school.school_id)
            self._profile(school.school_id, plan)
            self._complete_slots(plan)
            self._baseline_ssa(school, 7.0)
            self._follow_up(plan, 8.5)

        eligible_school("CH-BATCH-ONE")
        with CaptureQueriesContext(connection) as one_school_queries:
            ChampionEligibilityService.evaluate_all()

        eligible_school("CH-BATCH-TWO")
        eligible_school("CH-BATCH-THREE")
        CoreSchoolProfile.objects.update(champion_status="Not Eligible")
        with CaptureQueriesContext(connection) as three_school_queries:
            candidates = ChampionEligibilityService.evaluate_all()

        self.assertEqual(len(candidates), 3)
        self.assertEqual(len(three_school_queries), len(one_school_queries))
        self.assertLessEqual(len(three_school_queries), 8)

    def test_an_impact_measured_plan_is_still_scored(self):
        """The not-yet-a-candidate branch keeps its metrics too — the review
        drawer shows a real score and a real slot count, not zeros."""
        school = self._school("CH-MEAS")
        plan = self._plan(school.school_id)
        self._profile(school.school_id, plan)
        self._complete_slots(plan, how_many=6)
        self._baseline_ssa(school, 7.0)

        result = self._follow_up(plan, 8.5)
        self.assertFalse(result["championCandidate"])
        plan.refresh_from_db()
        self.assertEqual(plan.status, "Impact Measured")

        metrics = ChampionEligibilityService.calculate_score(school)

        self.assertNotIn("reason", metrics, metrics)
        self.assertEqual(metrics["completed_slots"], 6)
        self.assertEqual(metrics["total_slots"], 9)
        self.assertGreater(metrics["score"], 0.0)
        self.assertFalse(
            metrics["eligible"],
            "an incomplete package is still not a champion — the widened "
            "lookup must not weaken the gate",
        )

    def test_the_plan_list_keeps_a_measured_plan(self):
        """The same "Active"-only reading dropped a measured plan out of
        /api/core/plans."""
        school = self._school("CH-LIST")
        plan = self._plan(school.school_id)
        self._profile(school.school_id, plan)
        self._complete_slots(plan, how_many=2)
        self._baseline_ssa(school, 7.0)
        self._follow_up(plan, 8.5)

        listed = core_services.list_plans(self.user)

        self.assertEqual([p["id"] for p in listed], [plan.id])


class ChampionEligibilityControlsTest(ChampionPipelineFixture):
    """The fix has to keep saying no where no is the right answer."""

    def test_a_school_with_no_core_plan_is_ineligible(self):
        school = self._school("CH-NONE")
        self._baseline_ssa(school, 9.0)

        metrics = ChampionEligibilityService.calculate_score(school)

        self.assertFalse(metrics["eligible"])
        self.assertEqual(metrics["score"], 0.0)
        self.assertEqual(metrics["reason"], "No active Core Plan")

    def test_a_closed_plan_does_not_count_as_the_live_package(self):
        """repair_core_data archives orphaned plans; an archived plan is over."""
        school = self._school("CH-ARCH")
        plan = self._plan(school.school_id, status="Archived")
        self._profile(school.school_id, plan)
        self._complete_slots(plan)
        self._baseline_ssa(school, 9.0)

        metrics = ChampionEligibilityService.calculate_score(school)

        self.assertFalse(metrics["eligible"])
        self.assertEqual(metrics["reason"], "No active Core Plan")

    def test_a_plan_without_a_confirmed_ssa_is_ineligible(self):
        school = self._school("CH-NOSSA")
        plan = self._plan(school.school_id, status="Champion Candidate")
        self._profile(school.school_id, plan)
        self._complete_slots(plan)

        metrics = ChampionEligibilityService.calculate_score(school)

        self.assertFalse(metrics["eligible"])
        self.assertEqual(metrics["reason"], "No SSA recorded")


class ChampionScoreReadsTheOperationalFyPlanTest(ChampionPipelineFixture):
    """The 1 Oct rollover, from the reader's side.

    Nothing ever closes a finished package — the only "complete" statuses in
    the codebase are the ones apps.system_health.services counts, and no
    writer sets them — so from rollover a school owns two plans that both
    read as live. `.first()` on an unordered queryset orders by primary key,
    and FY2026's legacy id (`cplan-{school}`) always sorts before every later
    FY's (`cplan-{school}-{fy}`), so the scorer would have read the stale
    FY2026 package for every core school, for ever.
    """

    def test_last_years_stuck_package_does_not_score_this_year(self):
        school = self._school("CH-ROLL")
        last_year = self._plan(school.school_id, fy="2026")
        self._complete_slots(last_year)
        this_year = self._plan(school.school_id, fy="2027")
        self._complete_slots(this_year, how_many=2)
        self._profile(school.school_id, this_year)
        self._baseline_ssa(school, 9.0)

        with mock.patch.object(
            core_services, "get_operational_fy", return_value="2027"
        ):
            metrics = ChampionEligibilityService.calculate_score(school)

        self.assertEqual(
            metrics["completed_slots"],
            2,
            "the champion score must read this FY's package, not last FY's",
        )
        self.assertFalse(metrics["eligible"])

    def test_the_core_detail_endpoint_reads_the_same_plan(self):
        """get_detail served the slot statuses the drawer shows; a bare
        `.first()` there landed on the same stale legacy plan."""
        school = self._school("CH-DETAIL")
        self._plan(school.school_id, fy="2026")
        this_year = self._plan(school.school_id, fy="2027")
        self._profile(school.school_id, this_year)

        with mock.patch.object(
            core_services, "get_operational_fy", return_value="2027"
        ):
            detail = core_services.get_detail(school.school_id, self.user)

        self.assertEqual(detail["id"], this_year.id)
        self.assertEqual(detail["fy"], "2027")

    def test_a_plan_from_an_earlier_fy_is_still_read_after_rollover(self):
        """A school whose only plan predates the current FY must not fall out
        of the engine entirely — that is the FY2027 hard stop all over again.
        """
        school = self._school("CH-LEGACY")
        plan = self._plan(school.school_id, fy="2026")
        self._complete_slots(plan)
        self._profile(school.school_id, plan)
        self._baseline_ssa(school, 9.0)

        with mock.patch.object(
            core_services, "get_operational_fy", return_value="2027"
        ):
            metrics = ChampionEligibilityService.calculate_score(school)

        self.assertNotIn("reason", metrics, metrics)
        self.assertEqual(metrics["completed_slots"], 9)
