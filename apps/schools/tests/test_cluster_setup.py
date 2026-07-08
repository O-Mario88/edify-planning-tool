from __future__ import annotations

from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import StaffProfile, User
from apps.core.enums import SsaIntervention
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty
from apps.clusters.models import Cluster, ClusterSubCounty, SchoolClusterAssignment
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore
from apps.planning.services import plan_builder


class ClusterSetupTest(APITestCase):
    def setUp(self):
        # Create standard geo hierarchy
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(name="Mukono", region=self.region)
        self.sub_county1 = SubCounty.objects.create(
            name="Ntunga", district=self.district
        )
        self.sub_county2 = SubCounty.objects.create(
            name="Ntunga South", district=self.district
        )

        # Create user / planner context
        self.user = User.objects.create_user(
            email="planner@test.edify.org",
            name="Cceo Planner",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.profile = StaffProfile.objects.create(
            user=self.user, title="CCEO", id="STF-001"
        )

        # Create clusters
        self.cluster1 = Cluster.objects.create(
            name="Mukono Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county1,
            cluster_type="mixed",
            status="active",
        )
        ClusterSubCounty.objects.create(
            cluster=self.cluster1, sub_county=self.sub_county1
        )

        self.cluster2 = Cluster.objects.create(
            name="Wakiso Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county2,
            cluster_type="mixed",
            status="active",
        )
        ClusterSubCounty.objects.create(
            cluster=self.cluster2, sub_county=self.sub_county2
        )

    def test_auto_classification_on_create(self):
        """Creating a school automatically assigns it to a cluster covering its sub-county."""
        school = School.objects.create(
            school_id="SCH-901",
            name="Test School Alpha",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county1,
            school_type="client",
        )
        # Should auto-assign to cluster1
        self.assertEqual(school.cluster_id, self.cluster1.id)
        self.assertEqual(school.cluster_status, "clustered")
        self.assertTrue(
            SchoolClusterAssignment.objects.filter(
                school=school, cluster=self.cluster1
            ).exists()
        )

    def test_real_time_reclassification_on_update(self):
        """Updating a school's sub-county reassigns it to the correct cluster in real-time."""
        school = School.objects.create(
            school_id="SCH-902",
            name="Test School Beta",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county1,
            school_type="client",
        )
        self.assertEqual(school.cluster_id, self.cluster1.id)

        # Move to sub_county2
        school.sub_county = self.sub_county2
        school.save()

        # Reload
        school.refresh_from_db()
        self.assertEqual(school.cluster_id, self.cluster2.id)
        self.assertEqual(school.cluster_status, "clustered")
        self.assertFalse(
            SchoolClusterAssignment.objects.filter(
                school=school, cluster=self.cluster1
            ).exists()
        )
        self.assertTrue(
            SchoolClusterAssignment.objects.filter(
                school=school, cluster=self.cluster2
            ).exists()
        )

    def test_reclassification_to_unclustered(self):
        """Updating a school's geography to a sub-county with no cluster clears its assignment."""
        school = School.objects.create(
            school_id="SCH-903",
            name="Test School Gamma",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county1,
            school_type="client",
        )
        self.assertEqual(school.cluster_id, self.cluster1.id)

        # Set sub-county to None/empty or an unclustered sub-county
        unclustered_sub = SubCounty.objects.create(
            name="Ntunga East", district=self.district
        )
        school.sub_county = unclustered_sub
        school.save()

        school.refresh_from_db()
        self.assertIsNone(school.cluster_id)
        self.assertEqual(school.cluster_status, "unclustered")
        self.assertFalse(SchoolClusterAssignment.objects.filter(school=school).exists())

    def test_dynamic_cluster_metrics_and_feed(self):
        """Plan builder feed dynamic metrics are calculated from member schools' latest SSA."""
        # Create member schools in cluster1
        school1 = School.objects.create(
            school_id="SCH-101",
            name="Alpha Acad",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county1,
            school_type="client",
            current_fy_ssa_status="done",
        )
        school2 = School.objects.create(
            school_id="SCH-102",
            name="Beta Acad",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county1,
            school_type="client",
            current_fy_ssa_status="done",
        )

        from apps.accounts.models import StaffSchoolAssignment

        StaffSchoolAssignment.objects.create(staff=self.profile, school_id=school1.id)
        StaffSchoolAssignment.objects.create(staff=self.profile, school_id=school2.id)

        # Create verified SSA records
        now = timezone.now()
        r1 = SsaRecord.objects.create(
            school=school1,
            date_of_ssa=now,
            fy="2026",
            quarter="Q1",
            average_score=6.0,
            verification_status="confirmed",
        )
        r2 = SsaRecord.objects.create(
            school=school2,
            date_of_ssa=now,
            fy="2026",
            quarter="Q1",
            average_score=8.0,
            verification_status="confirmed",
        )

        # Let's add scores
        # We will make financial_health weak on school 1 (score 2.0) and school 2 (score 4.0) -> avg 3.0
        # teaching_environment will be strong (score 8.0) and school 2 (score 9.0) -> avg 8.5
        SsaScore.objects.create(
            ssa_record=r1,
            intervention=SsaIntervention.FINANCIAL_HEALTH.value,
            score=2.0,
        )
        SsaScore.objects.create(
            ssa_record=r1,
            intervention=SsaIntervention.TEACHING_ENVIRONMENT.value,
            score=8.0,
        )

        SsaScore.objects.create(
            ssa_record=r2,
            intervention=SsaIntervention.FINANCIAL_HEALTH.value,
            score=4.0,
        )
        SsaScore.objects.create(
            ssa_record=r2,
            intervention=SsaIntervention.TEACHING_ENVIRONMENT.value,
            score=9.0,
        )

        # Call plan_builder service
        self.client.force_authenticate(user=self.user)
        payload = plan_builder({"fy": "2026"}, self.user)

        self.assertIn("schools", payload)
        self.assertIn("clusters", payload)

        clusters = payload["clusters"]
        cluster_data = next(c for c in clusters if c["clusterId"] == self.cluster1.id)

        # Average of 6.0 and 8.0 is 7.0
        self.assertEqual(cluster_data["averageSsa"], 7.0)
        self.assertEqual(cluster_data["schoolCount"], 2)

        # Weakest is financial_health (average 3.0)
        self.assertEqual(
            cluster_data["weakest"]["intervention"],
            SsaIntervention.FINANCIAL_HEALTH.value,
        )
        self.assertEqual(cluster_data["weakest"]["avg"], 3.0)
