"""Convergence tests: the recommendation surfaces that used to carry their
own divergent logic now delegate to the canonical analytics engine.

Guards the two live correctness bugs the convergence closed:
  • PlanningRecommendationService read *any* latest SSA, so an unverified
    upload could drive an official planning recommendation.
  • Core recommend()'s weakest-four selection sorted by score with no
    tie-break, so a tie at the 4th/5th boundary picked (and persisted) the
    core package non-deterministically.
"""

from __future__ import annotations

from datetime import datetime, timezone as dt_tz

from django.test import TestCase

from apps.clusters.models import Cluster
from apps.core.enums import SsaIntervention
from apps.core_schools.core_planning_services import (
    CoreInterventionRecommendationService,
)
from apps.geography.models import District, Region
from apps.planning.recommendation_services import PlanningRecommendationService
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

ALL = [c[0] for c in SsaIntervention.choices]


class RecommendationConvergenceTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Conv Region")
        self.district = District.objects.create(
            name="Conv District", region=self.region
        )
        self.cluster = Cluster.objects.create(
            name="Conv Cluster",
            region=self.region,
            district=self.district,
            status="active",
        )
        self.school = School.objects.create(
            school_id="CONV-1",
            name="Conv Primary",
            region=self.region,
            district=self.district,
        )
        # School.save() recomputes cluster from geography, so set the canonical
        # pointer directly (a clustered school is a precondition for the
        # planning recommendation to reach its SSA check at all).
        School.objects.filter(id=self.school.id).update(cluster_id=self.cluster.id)
        self.school.refresh_from_db()

    def _record(self, scores, *, status="confirmed"):
        avg = round(sum(scores.values()) / len(scores), 1)
        rec = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=datetime(2026, 6, 1, tzinfo=dt_tz.utc),
            fy="2026",
            quarter="Q3",
            average_score=avg,
            uploaded_by="u1",
            verification_status=status,
        )
        for interv, val in scores.items():
            SsaScore.objects.create(ssa_record=rec, intervention=interv, score=val)
        return rec

    def _all(self, **overrides):
        base = {c: 6.0 for c in ALL}
        base.update(overrides)
        return base

    def test_planning_recommendation_ignores_unverified_ssa(self):
        # Only an UNVERIFIED SSA exists → planning must treat the school as
        # having no usable baseline, not recommend off unverified data.
        self._record(self._all(leadership=2.0), status="pending")
        rec = PlanningRecommendationService.get_recommendation(self.school)
        self.assertEqual(rec["planningReadiness"], "SSA Required")

        # Confirm it once and the recommendation becomes available.
        self._record(self._all(leadership=2.0), status="confirmed")
        rec2 = PlanningRecommendationService.get_recommendation(self.school)
        self.assertEqual(rec2["planningReadiness"], "Ready for Support")

    def test_core_recommend_is_deterministic_at_a_tie_boundary(self):
        # teaching_environment(1) < government_requirement(2) <
        # learning_environment(3) < [financial_health(4) == leadership(4)].
        # The 4th/5th weakest tie; the engine's alphabetical tie-break puts
        # financial_health (alphabetically first) in the 4th slot, stably.
        self._record(
            self._all(
                teaching_environment=1.0,
                government_requirement=2.0,
                learning_environment=3.0,
                financial_health=4.0,
                leadership=4.0,
            )
        )
        reco = CoreInterventionRecommendationService.recommend(self.school)
        codes = [r["code"] for r in reco["rows"]]
        self.assertEqual(
            codes,
            [
                "teaching_environment",
                "government_requirement",
                "learning_environment",
                "financial_health",
            ],
        )
        # Stable across repeated calls (was non-deterministic before).
        again = [
            r["code"]
            for r in CoreInterventionRecommendationService.recommend(self.school)[
                "rows"
            ]
        ]
        self.assertEqual(codes, again)

    def test_core_recommend_never_fabricates_without_confirmed_ssa(self):
        # Only unverified data → no package, never an invented four.
        self._record(self._all(leadership=1.0), status="pending")
        reco = CoreInterventionRecommendationService.recommend(self.school)
        self.assertFalse(reco["available"])
        self.assertEqual(reco["rows"], [])
