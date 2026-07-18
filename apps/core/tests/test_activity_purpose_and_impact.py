from __future__ import annotations

import datetime
from django.test import TestCase

from apps.accounts.models import StaffProfile, User, StaffSchoolAssignment
from apps.activities.models import Activity
from apps.activities.services import create, calculate_activity_impact
from apps.clusters.models import Cluster
from apps.clusters.services import cluster_weakest_interventions
from apps.core.enums import SsaIntervention
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


class ActivityPurposeAndImpactTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(name="Kampala", region=self.region)
        self.user = User.objects.create_user(
            email="cceo@test.com",
            name="Field CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(user=self.user, title="CCEO")

        self.school = School.objects.create(
            school_id="SCH-99",
            name="Excel Junior Community Primary School",
            region=self.region,
            district=self.district,
            current_fy_ssa_status="done",
        )
        self.cluster = Cluster.objects.create(
            name="Central Cluster", district=self.district, region=self.region
        )

        # Staff School Assignment to bypass target scoping check
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=self.school.id)

        # SsaRecords. verification_status must be set explicitly: the model
        # defaults to PENDING, and every decision surface (cluster rankings,
        # impact, planning gates) is required to ignore unverified records —
        # see apps.ssa.services.latest_applicable_record. These fixtures
        # represent real decision-driving assessments, so they are confirmed.
        # Pre SSA (before activity date: 2026-06-15)
        self.pre_ssa = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc),
            fy="2026",
            quarter="Q4",
            uploaded_by="STF-01",
            average_score=5.0,
            verification_status="confirmed",
        )
        for intervention in SsaIntervention:
            SsaScore.objects.create(
                ssa_record=self.pre_ssa,
                intervention=intervention.value,
                score=4.0 if intervention.value == "leadership" else 5.0,
            )

        # Post SSA (after activity date: 2026-06-15)
        self.post_ssa = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=datetime.datetime(2026, 6, 30, tzinfo=datetime.timezone.utc),
            fy="2026",
            quarter="Q4",
            uploaded_by="STF-01",
            average_score=6.0,
            verification_status="confirmed",
        )
        for intervention in SsaIntervention:
            SsaScore.objects.create(
                ssa_record=self.post_ssa,
                intervention=intervention.value,
                score=3.0 if intervention.value == "leadership" else 5.0,
            )

    def test_visit_creation_allows_optional_purpose_and_focus(self):
        # Purpose and focus help reporting, but they no longer block a visit.
        data = {
            "activityType": "school_visit",
            "schoolId": "SCH-99",
            "scheduledDate": "2026-06-15",
            "responsibleStaffId": self.staff.id,
            "strict_validation": True,
        }
        res = create(data, self.user)
        self.assertIsNotNone(res["id"])
        self.assertIsNone(res["activityPurposeText"])
        self.assertIsNone(res["focusIntervention"])

    def test_impact_delta_calculation(self):
        # We need leadership to improve for this test to match delta calculation test
        # Let's adjust post_ssa score for this test
        leadership_post = self.post_ssa.scores.filter(intervention="leadership").first()
        leadership_post.score = 6.0
        leadership_post.save()

        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            planned_date=datetime.date(2026, 6, 15),
            focus_intervention="leadership",
            activity_purpose_text="Visit for leadership support",
            status="completed",
        )

        impact = calculate_activity_impact(activity)
        self.assertEqual(impact["status"], "Improved")
        self.assertEqual(impact["preScore"], 4.0)
        self.assertEqual(impact["postScore"], 6.0)
        self.assertEqual(impact["delta"], 2.0)
        # The pre/post pair here is 29 days apart — real, but NOT an annual
        # comparison. Callers must be able to tell the difference rather
        # than presenting it as official annual impact (spec §12).
        self.assertEqual(impact["intervalDays"], 29)
        self.assertFalse(impact["annualComparison"])

    def test_activity_impact_ignores_unverified_ssa(self):
        """Official impact must be computed only from CONFIRMED SSA — a
        pending partner-collected upload must never set the before/after
        scores shown on the school-impact page. Both the pre and post
        queries previously filtered on deleted_at alone."""
        leadership_post = self.post_ssa.scores.filter(intervention="leadership").first()
        leadership_post.score = 6.0
        leadership_post.save()

        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            planned_date=datetime.date(2026, 6, 15),
            focus_intervention="leadership",
            activity_purpose_text="Visit for leadership support",
            status="completed",
        )

        # Sanity: measurable while both records are confirmed.
        self.assertEqual(calculate_activity_impact(activity)["status"], "Improved")

        # Un-verify the follow-up: impact must become not-measurable rather
        # than silently reporting a delta from unverified data.
        SsaRecord.objects.filter(id=self.post_ssa.id).update(
            verification_status="pending"
        )
        impact = calculate_activity_impact(activity)
        self.assertEqual(impact["status"], "Not Enough Data")

    def test_cluster_weakest_interventions(self):
        # Use the canonical membership transition. The compatibility join is
        # deliberately not an alternate source of truth for analytics.
        from apps.clusters.services import set_school_cluster_membership

        set_school_cluster_membership(self.school, self.cluster, self.user.id)

        weakest = cluster_weakest_interventions(self.cluster.id, self.user)
        self.assertEqual(len(weakest), 4)
        self.assertEqual(weakest[0]["intervention"], "leadership")
        self.assertEqual(weakest[0]["avg"], 3.0)

    def test_cluster_weakest_interventions_ignores_unverified_ssa(self):
        """Only CONFIRMED SSA may rank a cluster's weakest interventions —
        the same canonical rule every other decision surface obeys
        (apps.ssa.services.latest_applicable_record). This surface used to
        filter on deleted_at alone, so a pending partner-collected upload
        could drive cluster training recommendations while the per-school
        table on the same page excluded it."""
        from apps.clusters.services import set_school_cluster_membership

        set_school_cluster_membership(self.school, self.cluster, self.user.id)
        SsaRecord.objects.filter(school=self.school).update(
            verification_status="pending"
        )

        self.assertEqual(cluster_weakest_interventions(self.cluster.id, self.user), [])

    def test_cluster_weakest_interventions_never_fabricates_scores(self):
        """A cluster with no confirmed SSA must return an empty list, not an
        invented ranking. This previously fell back to the first four
        interventions in enum order with their averages forced to 0.0 —
        fabricating four 'weakest interventions' out of missing data, at a
        score that bands Critical."""
        from apps.clusters.services import (
            cluster_intervention_summary,
            set_school_cluster_membership,
        )

        set_school_cluster_membership(self.school, self.cluster, self.user.id)
        SsaRecord.objects.filter(school=self.school).delete()

        self.assertEqual(cluster_weakest_interventions(self.cluster.id, self.user), [])
        # The scorecard still lists all 8 interventions, but with an honest
        # None rather than a 0.0 that would read as a real, terrible score.
        summary = cluster_intervention_summary(self.cluster.id, self.user)
        self.assertEqual(len(summary), 8)
        self.assertTrue(all(row["avg"] is None for row in summary))
