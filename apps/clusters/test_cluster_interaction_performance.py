"""Query-shape regressions for the interactive cluster surfaces."""

from datetime import date
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.clusters.services import cluster_detail, cluster_schools
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


class ClusterInteractionQueryShapeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(
            id="cluster-interaction-cd",
            email="cluster-interaction-cd@edify.org",
            name="Cluster Interaction CD",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )
        StaffProfile.objects.create(
            id="cluster-interaction-staff", user=cls.user, title="CD"
        )
        cls.region = Region.objects.create(name="Interaction Region")
        cls.district = District.objects.create(
            name="Interaction District", region=cls.region
        )
        cls.sub_county = SubCounty.objects.create(
            name="Interaction Sub-County", district=cls.district
        )
        cls.cluster = Cluster.objects.create(
            name="Interaction Cluster",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            status="active",
        )
        cls.first_school = cls._make_school(0)
        Activity.objects.create(
            school=cls.first_school,
            cluster=cls.cluster,
            activity_type="coaching_visit",
            fy="2026",
            quarter="Q1",
            status="ia_verified",
            planned_date=date(2026, 7, 3),
        )
        Activity.objects.create(
            school=cls.first_school,
            cluster=cls.cluster,
            activity_type="in_school_training",
            fy="2026",
            quarter="Q1",
            status="ia_verified",
            planned_date=date(2026, 7, 8),
        )

    @classmethod
    def _make_school(cls, index):
        school = School.objects.create(
            school_id=f"INTERACTION-{index}",
            name=f"Interaction School {index}",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
        )
        # Membership reconciliation is deliberately bypassed in this focused
        # service fixture; the query surface reads the canonical cluster key.
        School.objects.filter(id=school.id).update(
            cluster_id=cls.cluster.id, cluster_status="clustered"
        )
        school.refresh_from_db()
        return school

    def _query_count(self, service):
        service(self.cluster.id, self.user)
        with CaptureQueriesContext(connection) as queries:
            service(self.cluster.id, self.user)
        return len(queries.captured_queries)

    def test_roster_queries_do_not_grow_per_school(self):
        small = self._query_count(cluster_schools)
        for index in range(1, 21):
            self._make_school(index)
        large = self._query_count(cluster_schools)

        self.assertEqual(
            small,
            large,
            f"roster grew from {small} to {large} queries when schools were added",
        )

    def test_cluster_summary_queries_do_not_grow_per_school(self):
        small = self._query_count(cluster_detail)
        for index in range(1, 21):
            self._make_school(index)
        large = self._query_count(cluster_detail)

        self.assertEqual(
            small,
            large,
            f"detail grew from {small} to {large} queries when schools were added",
        )

    def test_prefetched_activity_dates_are_preserved(self):
        school = cluster_schools(self.cluster.id, self.user)[0]
        self.assertEqual(school["lastVisitDate"], "2026-07-03")
        self.assertEqual(school["lastTrainingDate"], "2026-07-08")

    def test_cluster_profile_populates_roster_and_student_impact(self):
        from django.utils import timezone

        from apps.ssa.models import SsaRecord, SsaScore

        School.objects.filter(id=self.first_school.id).update(
            enrollment=420, planning_readiness="ready_for_support_planning"
        )
        second_school = self._make_school(1)
        School.objects.filter(id=second_school.id).update(enrollment=80)
        ssa = SsaRecord.objects.create(
            school=self.first_school,
            date_of_ssa=timezone.now(),
            fy="2026",
            quarter="Q1",
            average_score=6.4,
            verification_status="confirmed",
            uploaded_by=self.user.id,
        )
        SsaScore.objects.create(ssa_record=ssa, intervention="leadership", score=6.4)

        detail = cluster_detail(self.cluster.id, self.user)
        self.assertEqual(detail["schoolCount"], 2)
        self.assertEqual(detail["studentImpact"], 500)

        self.client.force_login(self.user)
        response = self.client.get(f"/clusters/{self.cluster.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "500 Students Impacted")
        self.assertContains(response, "6.4/10")
        self.assertContains(response, "2026-07-03")
        self.assertContains(response, "2026-07-08")
        self.assertContains(response, "Ready for Support Planning")

    @patch(
        "apps.frontend.views.cluster_views.ClusterImpactService.get_impact_data",
        side_effect=AssertionError("unused impact panel work must stay lazy"),
    )
    @patch(
        "apps.frontend.views.cluster_views.ClusterCostPreviewService.preview_cost",
        side_effect=AssertionError("unused cost preview work must stay lazy"),
    )
    def test_cluster_directory_does_not_build_hidden_panels(
        self, _cost_preview, _impact
    ):
        self.client.force_login(self.user)
        response = self.client.get("/clusters")
        self.assertEqual(response.status_code, 200)
