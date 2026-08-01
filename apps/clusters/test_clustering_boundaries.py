"""What may be clustered, and where a clustered school shows up.

Three rules that were each enforced somewhere but not everywhere, so the UI
offered choices the services then refused:

  1. A sub-county an active cluster already covers cannot be clustered again.
     create_cluster refused it with a 400; the create drawer still offered it,
     so the rule was only discoverable by submitting the form.
  2. A school already in a cluster is not a candidate for clustering.
  3. Planning lists clustered schools only. An unclustered school cannot be
     planned — the recommendation engine stops at "Cluster Required" before
     reading a single SSA score — so listing 16,000 of them buried the handful
     that could actually be worked. The full register stays in the School
     Directory, which is where clustering happens.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import User
from apps.clusters.models import Cluster, ClusterSubCounty
from apps.clusters.services import covered_sub_counties
from apps.core.exceptions import BadRequest
from apps.geography.models import District, Region, SubCounty
from apps.planning.planning_service import PlanningDashboardService
from apps.schools.models import School


class ClusteringBoundaryTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Boundary Region")
        cls.district = District.objects.create(
            name="Boundary District", region=cls.region
        )
        cls.taken_sc = SubCounty.objects.create(
            name="Taken Sub County", district=cls.district
        )
        cls.covered_sc = SubCounty.objects.create(
            name="Covered Sub County", district=cls.district
        )
        cls.free_sc = SubCounty.objects.create(
            name="Free Sub County", district=cls.district
        )

        cls.cluster = Cluster.objects.create(
            name="Existing Cluster",
            region=cls.region,
            district=cls.district,
            sub_county=cls.taken_sc,
            status="active",
        )
        # The second shape of occupancy: multi-sub-county coverage.
        ClusterSubCounty.objects.create(
            cluster=cls.cluster, sub_county=cls.covered_sc
        )

        cls.admin = User.objects.create(
            id="clusterbound-admin",
            email="clusterbound@edify.org",
            name="Cluster Boundary Admin",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
            status="active",
        )

    def _school(self, ref, *, clustered: bool):
        """Clustering is derived, not assigned.

        School.save() resolves the school's cluster from whether an active
        cluster covers its sub-county, and nulls cluster_id when none does — so
        a school becomes clustered by sitting in a covered sub-county, and
        setting the fields directly is overwritten on the way to the database.
        """
        return School.objects.create(
            school_id=ref,
            name=f"School {ref}",
            region=self.region,
            district=self.district,
            sub_county=self.taken_sc if clustered else self.free_sc,
        )

    # ── 1. Sub-county occupancy ──────────────────────────────────────────────

    def test_both_shapes_of_coverage_count_as_taken(self):
        covered = covered_sub_counties()
        self.assertEqual(covered.get(str(self.taken_sc.id)), "Existing Cluster")
        self.assertEqual(covered.get(str(self.covered_sc.id)), "Existing Cluster")
        self.assertIsNone(covered.get(str(self.free_sc.id)))

    def test_the_drawer_and_the_validator_agree(self):
        """The drawer disables what create_cluster would refuse. If these ever
        diverge the UI starts offering choices the service rejects, which is
        the bug this pair of assertions exists to prevent."""
        from apps.clusters.services import create_cluster

        covered = covered_sub_counties()
        self.assertIn(str(self.taken_sc.id), covered)

        with self.assertRaises(BadRequest):
            create_cluster(
                {
                    "name": "Second Cluster",
                    "regionId": self.region.id,
                    "districtId": self.district.id,
                    "subCountyIds": [self.taken_sc.id],
                },
                self.admin,
            )

    def test_a_free_sub_county_is_still_clusterable(self):
        """The rule must block the taken ones without blocking the rest."""
        from apps.clusters.services import create_cluster

        result = create_cluster(
            {
                "name": "Free Cluster",
                "regionId": self.region.id,
                "districtId": self.district.id,
                "subCountyIds": [self.free_sc.id],
            },
            self.admin,
        )
        self.assertTrue(result["id"])

    # ── 2. Schools offered for clustering ────────────────────────────────────

    def test_a_clustered_school_is_not_offered_for_clustering(self):
        self._school("BOUND-CLUSTERED", clustered=True)
        self._school("BOUND-FREE", clustered=False)

        candidates = set(
            School.objects.filter(
                district_id=self.district.id,
                cluster_status="unclustered",
                deleted_at__isnull=True,
            ).values_list("school_id", flat=True)
        )
        self.assertIn("BOUND-FREE", candidates)
        self.assertNotIn("BOUND-CLUSTERED", candidates)

    # ── 3. Planning shows clustered schools only ─────────────────────────────

    def test_planning_lists_only_clustered_schools(self):
        self._school("BOUND-PLAN-YES", clustered=True)
        self._school("BOUND-PLAN-NO", clustered=False)

        data = PlanningDashboardService.get_dashboard_data(self.admin, {})
        refs = {str(row["schoolId"]) for row in data["schools"]}
        self.assertIn("BOUND-PLAN-YES", refs)
        self.assertNotIn(
            "BOUND-PLAN-NO",
            refs,
            "an unclustered school cannot be planned and must not fill the page",
        )

    def test_a_stale_status_cannot_smuggle_an_unclustered_school_in(self):
        """cluster_status is a denormalised mirror. Requiring the relationship
        too means drift can hide a school from planning but never admit one
        that is not actually in a cluster."""
        school = self._school("BOUND-STALE", clustered=False)
        School.objects.filter(id=school.id).update(
            cluster_status="clustered", cluster_id=None
        )

        data = PlanningDashboardService.get_dashboard_data(self.admin, {})
        refs = {str(row["schoolId"]) for row in data["schools"]}
        self.assertNotIn("BOUND-STALE", refs)

    def test_the_full_register_stays_in_the_directory(self):
        """Restricting planning must not remove schools from where they are
        found and clustered."""
        self._school("BOUND-DIR-1", clustered=False)
        self._school("BOUND-DIR-2", clustered=True)

        directory = set(
            School.objects.filter(deleted_at__isnull=True).values_list(
                "school_id", flat=True
            )
        )
        self.assertIn("BOUND-DIR-1", directory)
        self.assertIn("BOUND-DIR-2", directory)
