"""A recommendation is a record now, not only a calculation.

The engine always decided what a school needs; it returned dictionaries that
were recomputed on every request and kept nowhere. So there was no status,
no owner, no expiry, no dedupe key — and no row at all for a recommendation
nobody accepted, which is exactly the one leadership needs to see.

These pin the properties that make it accountable: generation converges, a
need already being worked never reappears, declining to act requires a reason,
and a fresher assessment retires the picture it replaced.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.utils import IntegrityError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.core.exceptions import BadRequest
from apps.core.enums import SsaIntervention
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import (
    LIVE_STATES,
    RecommendationState,
    SsaRecommendation,
    SsaRecord,
    SsaScore,
    condition_key_for,
)
from apps.ssa.recommendation_service import (
    accept,
    defer,
    generate_for_school,
    mark_delivered,
    mark_planned,
    open_recommendations,
    reject,
    supersede_stale,
)

FY = "2026"


class RecommendationFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Rec Region")
        cls.district = District.objects.create(name="Rec District", region=cls.region)
        cls.school = School.objects.create(
            school_id="REC-1",
            name="Recommendation Primary",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        cls.user = User.objects.create_user(
            email="rec@ssa.test",
            password="pw",
            name="Rec Officer",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.create(
            user=cls.user, title="CCEO", country="Uganda"
        )

    def _confirmed_ssa(self, *, scores, when=None):
        record = SsaRecord.objects.create(
            school=self.school,
            fy=FY,
            date_of_ssa=when or timezone.localdate(),
            verification_status="confirmed",
        )
        for intervention, value in scores.items():
            SsaScore.objects.create(
                ssa_record=record, intervention=intervention, score=value
            )
        return record

    def _generate(self):
        return generate_for_school(self.school, fy=FY, principal=self.user)


class GenerationTests(RecommendationFixture):
    def test_no_confirmed_assessment_recommends_nothing_and_says_so(self):
        """Silence and "no needs" are different answers."""
        result = self._generate()
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["skipped"], "no confirmed ssa")
        self.assertEqual(SsaRecommendation.objects.count(), 0)

    def test_a_confirmed_assessment_produces_recorded_needs(self):
        self._confirmed_ssa(
            scores={
                SsaIntervention.LEARNING_ENVIRONMENT: 2.0,
                SsaIntervention.LEADERSHIP: 3.0,
            }
        )
        result = self._generate()
        self.assertGreater(result["created"], 0)
        recommendation = SsaRecommendation.objects.first()
        self.assertEqual(recommendation.state, RecommendationState.GENERATED)
        self.assertEqual(recommendation.school_id, self.school.id)
        self.assertTrue(recommendation.reason, "a rank with no explanation")

    def test_the_reason_explains_the_rank_in_words(self):
        self._confirmed_ssa(scores={SsaIntervention.LEARNING_ENVIRONMENT: 2.0})
        self._generate()
        reason = SsaRecommendation.objects.first().reason
        self.assertIn("Critical", reason)
        self.assertIn("No support has been delivered", reason)

    def test_generation_converges_instead_of_accumulating(self):
        self._confirmed_ssa(scores={SsaIntervention.LEADERSHIP: 2.5})
        first = self._generate()
        before = SsaRecommendation.objects.count()
        second = self._generate()
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["refreshed"], first["created"])
        self.assertEqual(SsaRecommendation.objects.count(), before)

    def test_a_need_already_being_worked_is_not_raised_again(self):
        self._confirmed_ssa(scores={SsaIntervention.LEADERSHIP: 2.5})
        self._generate()
        recommendation = SsaRecommendation.objects.first()
        accept(recommendation, self.user)

        self._generate()
        recommendation.refresh_from_db()
        self.assertEqual(recommendation.state, RecommendationState.ACCEPTED)
        self.assertEqual(
            SsaRecommendation.objects.filter(
                condition_key=recommendation.condition_key
            ).count(),
            1,
        )

    def test_two_live_recommendations_for_one_need_are_impossible(self):
        self._confirmed_ssa(scores={SsaIntervention.LEADERSHIP: 2.5})
        self._generate()
        existing = SsaRecommendation.objects.first()
        with self.assertRaises(IntegrityError):
            SsaRecommendation.objects.create(
                condition_key=existing.condition_key,
                school=self.school,
                ssa_record=existing.ssa_record,
                intervention=existing.intervention,
                fy=FY,
            )


class LifecycleTests(RecommendationFixture):
    def setUp(self):
        self._confirmed_ssa(scores={SsaIntervention.LEADERSHIP: 2.5})
        self._generate()
        self.recommendation = SsaRecommendation.objects.first()

    def test_accepting_gives_it_an_owner(self):
        accept(self.recommendation, self.user)
        self.recommendation.refresh_from_db()
        self.assertEqual(self.recommendation.state, RecommendationState.ACCEPTED)
        self.assertEqual(self.recommendation.owner_id, str(self.user.id))

    def test_deferring_requires_a_reason(self):
        with self.assertRaises(BadRequest):
            defer(self.recommendation, self.user, reason="  ")

    def test_rejecting_requires_a_reason(self):
        with self.assertRaises(BadRequest):
            reject(self.recommendation, self.user, reason="")

    def test_a_deferred_need_is_still_outstanding(self):
        """Postponing is a decision about timing, not about the weakness."""
        defer(self.recommendation, self.user, reason="School closed for exams.")
        self.recommendation.refresh_from_db()
        self.assertIn(self.recommendation.state, LIVE_STATES)
        self.assertIn(self.recommendation, open_recommendations(fy=FY))

    def test_a_rejected_need_leaves_the_queue_with_its_reason_kept(self):
        reject(self.recommendation, self.user, reason="Addressed by the district.")
        self.recommendation.refresh_from_db()
        self.assertNotIn(self.recommendation, open_recommendations(fy=FY))
        self.assertEqual(
            self.recommendation.decision_reason, "Addressed by the district."
        )

    def test_a_closed_recommendation_cannot_be_decided_again(self):
        reject(self.recommendation, self.user, reason="Not this cycle.")
        with self.assertRaises(BadRequest):
            accept(self.recommendation, self.user)

    def test_planning_links_the_activity_that_answers_it(self):
        from apps.activities.models import Activity

        activity = Activity.objects.create(
            activity_type="school_visit",
            status="scheduled",
            school=self.school,
            fy=FY,
        )
        mark_planned(self.recommendation, activity, self.user)
        self.recommendation.refresh_from_db()
        self.assertEqual(self.recommendation.planned_activity_id, activity.id)

    def test_delivery_closes_it_and_a_recurrence_becomes_a_new_need(self):
        mark_delivered(self.recommendation, self.user)
        self.recommendation.refresh_from_db()
        self.assertEqual(self.recommendation.state, RecommendationState.DELIVERED)

        # The weakness returns at the next assessment: a NEW need, linked back.
        self._generate()
        successor = (
            SsaRecommendation.objects.filter(
                condition_key=self.recommendation.condition_key
            )
            .exclude(id=self.recommendation.id)
            .first()
        )
        self.assertIsNotNone(successor)
        self.assertEqual(successor.supersedes_id, self.recommendation.id)


class SupersessionTests(RecommendationFixture):
    def test_a_fresher_assessment_retires_the_picture_it_replaced(self):
        self._confirmed_ssa(
            scores={SsaIntervention.LEADERSHIP: 2.5},
            when=timezone.localdate() - timedelta(days=200),
        )
        self._generate()
        stale = SsaRecommendation.objects.first()
        self.assertIn(stale.state, LIVE_STATES)

        self._confirmed_ssa(scores={SsaIntervention.LEADERSHIP: 7.5})
        retired = supersede_stale(self.school, fy=FY, principal=self.user)

        stale.refresh_from_db()
        self.assertEqual(retired, 1)
        self.assertEqual(stale.state, RecommendationState.SUPERSEDED)
        self.assertIn("newer confirmed assessment", stale.decision_reason)

    def test_the_condition_key_identifies_the_need_not_the_row(self):
        self.assertEqual(
            condition_key_for(school_id="S1", fy="2026", intervention="leadership"),
            "ssa-rec:S1:2026:leadership",
        )
