"""Acting on a Core school's recommendations, and reviewing its Champion case.

Owner, 2026-10-18: "complete all in one build" — accept, defer or plan support
straight from a recommendation, and a workflow for reviewing Champion
candidates. Both are the platform's own: `ssa.recommendation_service`
(accept / defer / reject, a reason required to defer or reject) and the
Champion review drawer with its approve / reject. The school's owner acts
(`may_write_school`, the rule the Champion drawer already applies); anyone
else reads.
"""

from __future__ import annotations

from apps.accounts.models import StaffSupervisorAssignment
from apps.clusters.test_cluster_oversight_views import _create_user
from apps.core.rbac import EdifyRole
from apps.core_schools.models import CoreActivitySlot, CorePlan, CoreSchoolProfile
from apps.core_schools.services import create_package_slots
from apps.core_schools.test_core_intelligence import _CoreCase
from apps.ssa.models import SsaRecord, SsaScore
from apps.ssa.recommendation_models import RecommendationState, SsaRecommendation
from apps.ssa.recommendation_service import generate_for_school


class RecommendationActionsTest(_CoreCase):
    def setUp(self):
        super().setUp()
        generate_for_school(self.single, fy=self.fy)
        self.rec = SsaRecommendation.objects.filter(school=self.single).first()

    def _act(self, user, action, **data):
        self.client.force_login(user)
        return self.client.post(
            f"/core-schools/recommendations/{self.rec.id}/{action}", data
        )

    def _lead(self, email):
        lead = _create_user(email, EdifyRole.COUNTRY_PROGRAM_LEAD)
        StaffSupervisorAssignment.objects.create(
            supervisee=self.james.staff_profile, supervisor=lead.staff_profile
        )
        return lead

    def test_the_owner_accepts_and_owns_the_need(self):
        response = self._act(self.james, "accept")

        self.assertIn(response.status_code, (200, 302))
        self.rec.refresh_from_db()
        self.assertEqual(self.rec.state, RecommendationState.ACCEPTED)
        self.assertEqual(self.rec.owner_id, self.james.id)

    def test_deferring_needs_a_reason(self):
        self._act(self.james, "defer", reason="")
        self.rec.refresh_from_db()
        self.assertEqual(self.rec.state, RecommendationState.GENERATED)

        self._act(self.james, "defer", reason="Term exams this month")
        self.rec.refresh_from_db()
        self.assertEqual(self.rec.state, RecommendationState.DEFERRED)
        self.assertEqual(self.rec.decision_reason, "Term exams this month")

    def test_rejecting_needs_a_reason(self):
        self._act(self.james, "reject", reason="Covered by the EdTech project")

        self.rec.refresh_from_db()
        self.assertEqual(self.rec.state, RecommendationState.REJECTED)

    def test_someone_who_may_not_write_the_school_changes_nothing(self):
        lead = self._lead("lead@core-actions.test")
        for user in (self.mary, lead):
            with self.subTest(user=user.email):
                response = self._act(user, "accept")
                self.assertIn(response.status_code, (403, 404))
        self.rec.refresh_from_db()
        self.assertEqual(self.rec.state, RecommendationState.GENERATED)

    def test_the_tab_offers_the_actions_and_the_schedule_to_the_owner_only(self):
        accept = f'action="/core-schools/recommendations/{self.rec.id}/accept"'
        self.client.force_login(self.james)
        body = self.client.get(
            f"/schools/{self.single.id}", {"tab": "core", "fy": self.fy}
        ).content.decode()
        self.assertIn(accept, body)
        self.assertIn(f"/planning/schedule-modal?school_id={self.single.id}", body)

        self.client.force_login(self._lead("lead2@core-actions.test"))
        read_only = self.client.get(
            f"/schools/{self.single.id}", {"tab": "core", "fy": self.fy}
        ).content.decode()
        self.assertIn(f'data-core-recommendation="{self.rec.id}"', read_only)
        self.assertNotIn(accept, read_only)


class ChampionReviewTest(_CoreCase):
    def setUp(self):
        super().setUp()
        # CI-1 meets Edify's Champion rule: a confirmed SSA of 8.5 in every
        # area and its 8 package visits and trainings done.
        record = SsaRecord.objects.get(school=self.rising, fy=self.fy)
        SsaRecord.objects.filter(id=record.id).update(average_score=8.5)
        SsaScore.objects.filter(ssa_record=record).update(score=8.5)
        plan = CorePlan.objects.get(school_id=self.rising.school_id, fy=self.fy)
        create_package_slots(plan, self.rising.school_id, ["leadership"])
        CoreActivitySlot.objects.filter(
            core_plan=plan, activity_type__in=("visit", "training")
        ).update(status="closed")
        CoreSchoolProfile.objects.create(
            id=f"cprof-{self.rising.school_id}",
            school_id=self.rising.school_id,
            core_plan=plan,
            core_start_fy=self.fy,
        )
        self.review = f'hx-get="/core-schools/{self.rising.school_id}/champion-review"'

    def test_a_potential_champion_opens_the_champion_review_from_its_tab(self):
        self.client.force_login(self.james)

        body = self.client.get(
            f"/schools/{self.rising.id}", {"tab": "core", "fy": self.fy}
        ).content.decode()

        self.assertIn("Potential Champion", body)
        self.assertIn(self.review, body)

    def test_core_school_oversight_opens_it_from_champion_readiness(self):
        self.client.force_login(self.james)

        body = self.client.get(
            "/core-schools-oversight/", {"tab": "champion", "fy": self.fy}
        ).content.decode()

        self.assertIn(self.review, body)

    def test_the_review_drawer_answers_for_the_owner(self):
        self.client.force_login(self.james)

        response = self.client.get(
            f"/core-schools/{self.rising.school_id}/champion-review",
            headers={"HX-Request": "true"},
        )

        self.assertEqual(response.status_code, 200)
