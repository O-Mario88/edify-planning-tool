"""Which clusters have a group training and a meeting planned (owner, 2026-09-28).

"CCEOs don't have the cluster group training planned table like cluster
meeting. can you add that to make sure they can know which cluster has been
planned and which ones have not been planned."
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.clusters.planning_status import cluster_planning_status
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.schools.models import School


class ClusterPlanningStatusTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Status Region")
        cls.district = District.objects.create(
            name="Status District", region=cls.region
        )
        cls.user = User.objects.create(
            email="status-cceo@edify.org",
            name="Status CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.create(user=cls.user, title="CCEO")
        cls.day = date.today() + timedelta(days=10)
        cls.fy = get_operational_fy(cls.day)
        cls.trained, cls.met, cls.idle = (
            Cluster.objects.create(
                name=name,
                region=cls.region,
                district=cls.district,
                responsible_staff_id=cls.staff.id,
            )
            for name in ("Alpha Cluster", "Beta Cluster", "Gamma Cluster")
        )
        for cluster in (cls.trained, cls.met, cls.idle):
            school = School.objects.create(
                school_id=f"ST-{cluster.name[:1]}",
                name=f"{cluster.name} School",
                region=cls.region,
                district=cls.district,
                account_owner_id=cls.staff.id,
            )
            School.objects.filter(id=school.id).update(
                cluster_id=cluster.id, cluster_status="clustered"
            )
            StaffSchoolAssignment.objects.create(staff=cls.staff, school_id=school.id)
        cls.training = cls._session(cls.trained, "cluster_training")
        cls._session(cls.met, "cluster_meeting")
        # A cancelled training is no plan.
        cls._session(cls.idle, "cluster_training", status="cancelled")

    @classmethod
    def _session(cls, cluster, activity_type, status="scheduled"):
        return Activity.objects.create(
            cluster=cluster,
            activity_type=activity_type,
            status=status,
            fy=cls.fy,
            planned_date=cls.day,
            responsible_staff_id=cls.staff.id,
        )

    def test_each_cluster_says_what_is_planned_and_what_is_not(self):
        status = cluster_planning_status(self.user, fy=get_operational_fy())
        rows = {row.name: row for row in status["rows"]}
        self.assertEqual(set(rows), {"Alpha Cluster", "Beta Cluster", "Gamma Cluster"})
        self.assertTrue(rows["Alpha Cluster"].training.is_planned)
        self.assertFalse(rows["Alpha Cluster"].meeting.is_planned)
        self.assertTrue(rows["Beta Cluster"].meeting.is_planned)
        self.assertFalse(rows["Beta Cluster"].training.is_planned)
        self.assertEqual(rows["Gamma Cluster"].training.label, "Not planned")
        self.assertEqual(rows["Gamma Cluster"].schools, 1)
        self.assertEqual(status["trainings_missing"], 2)
        self.assertEqual(status["meetings_missing"], 2)
        # Nothing planned at all comes first: it is the work.
        self.assertEqual(status["rows"][0].name, "Gamma Cluster")

    def test_my_plan_shows_the_status_card_and_the_group_training_row(self):
        self.client.force_login(self.user)
        response = self.client.get("/my-plan", {"fy": self.fy, "period": "fy"})
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("data-cluster-planning-status", html)
        self.assertIn(f'data-cluster-status="{self.idle.id}"', html)
        self.assertIn("Group Trainings Planned", html)
        ids = {row["id"] for row in response.context["group_trainings"]}
        self.assertEqual(ids, {self.training.id})
