"""Core schools' SSA recommendations, where the people who act on them look.

Owner, 2026-10-17, the Core School Intelligence brief (9): recommendations
from each school's SSA weaknesses and the catalogue's mapped trainings, with a
lifecycle. The platform already records them (`ssa.recommendation_service`:
one live `SsaRecommendation` per need, the recommended catalogue training or
why none is mapped, Generated → Accepted / Deferred → Planned → Delivered).
These hold that the Core School tab and Core School Oversight show those
records — not a second set — and that reading them changes nothing.
"""

from __future__ import annotations

from apps.activities.models import Activity
from apps.core_schools import intelligence
from apps.core_schools.test_core_intelligence import _CoreCase
from apps.ssa.recommendation_models import RecommendationState, SsaRecommendation
from apps.ssa.recommendation_service import generate_for_school


class _RecommendationCase(_CoreCase):
    def setUp(self):
        super().setUp()
        for school in (self.rising, self.single, self.falling):
            generate_for_school(school, fy=self.fy)
        self.live = SsaRecommendation.objects.filter(school=self.single).order_by(
            "rank"
        )


class ReadingTest(_RecommendationCase):
    def test_the_engine_reads_each_school_s_recorded_recommendations(self):
        found = intelligence.recommendations([self.single, self.rising])

        self.assertTrue(self.live.exists())
        self.assertEqual(
            [r.id for r in found[self.single.id]], [r.id for r in self.live]
        )

    def test_a_settled_recommendation_is_not_shown_as_open(self):
        first = self.live.first()
        SsaRecommendation.objects.filter(id=first.id).update(
            state=RecommendationState.DELIVERED
        )

        found = intelligence.recommendations([self.single])[self.single.id]

        self.assertNotIn(first.id, [r.id for r in found])

    def test_reading_them_creates_no_activity_and_changes_no_state(self):
        before = (
            Activity.objects.count(),
            list(SsaRecommendation.objects.values_list("id", "state")),
        )

        intelligence.recommendations([self.rising, self.single, self.falling])

        self.assertEqual(
            before,
            (
                Activity.objects.count(),
                list(SsaRecommendation.objects.values_list("id", "state")),
            ),
        )


class PagesTest(_RecommendationCase):
    def test_the_core_school_tab_lists_the_school_s_recommendations(self):
        self.client.force_login(self.james)

        body = self.client.get(
            f"/schools/{self.single.id}", {"tab": "core", "fy": self.fy}
        ).content.decode()

        for rec in self.live:
            self.assertIn(f'data-core-recommendation="{rec.id}"', body)

    def test_core_school_oversight_lists_them_by_school_in_scope(self):
        self.client.force_login(self.james)

        body = self.client.get(
            "/core-schools-oversight/", {"tab": "recommendations", "fy": self.fy}
        ).content.decode()

        self.assertIn('data-core-recommendation-row="CI-2"', body)
        # Mary's school is not in James's scope.
        self.assertNotIn('data-core-recommendation-row="CI-3"', body)
