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

        # SsaRecords
        # Pre SSA (before activity date: 2026-06-15)
        self.pre_ssa = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc),
            fy="2026",
            quarter="Q4",
            uploaded_by="STF-01",
            average_score=5.0,
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
        )
        for intervention in SsaIntervention:
            SsaScore.objects.create(
                ssa_record=self.post_ssa,
                intervention=intervention.value,
                score=3.0 if intervention.value == "leadership" else 5.0,
            )

    def test_visit_creation_validation(self):
        # Visit requires purpose text and focus intervention
        data = {
            "activityType": "school_visit",
            "schoolId": "SCH-99",
            "scheduledDate": "2026-06-15",
            "responsibleStaffId": self.staff.id,
            "strict_validation": True,
        }
        with self.assertRaises(BadRequest) as ctx:
            create(data, self.user)
        self.assertIn("must have a Visit Purpose", str(ctx.exception))

        data["activityPurposeText"] = "Follow up on leadership"
        with self.assertRaises(BadRequest) as ctx:
            create(data, self.user)
        self.assertIn("must have a focus intervention", str(ctx.exception))

        data["focusIntervention"] = "leadership"

        # Mock assert_schedulable to avoid CD Catalog requirement details
        from unittest.mock import patch

        with patch("apps.budget.costing_service.assert_schedulable") as mock_assert:
            res = create(data, self.user)
            self.assertIsNotNone(res["id"])
            self.assertEqual(res["activityPurposeText"], "Follow up on leadership")
            self.assertEqual(res["focusIntervention"], "leadership")

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

    def test_cluster_weakest_interventions(self):
        # Use the canonical membership transition. The compatibility join is
        # deliberately not an alternate source of truth for analytics.
        from apps.clusters.services import set_school_cluster_membership

        set_school_cluster_membership(self.school, self.cluster, self.user.id)

        weakest = cluster_weakest_interventions(self.cluster.id, self.user)
        self.assertEqual(len(weakest), 4)
        self.assertEqual(weakest[0]["intervention"], "leadership")
        self.assertEqual(weakest[0]["avg"], 3.0)
