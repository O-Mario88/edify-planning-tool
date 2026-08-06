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

from django.core.management import call_command
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
        ClusterSubCounty.objects.create(cluster=cls.cluster, sub_county=cls.covered_sc)

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


class ExplicitAssignmentSurvivesTest(TestCase):
    """A school with no sub-county keeps the cluster it was given.

    School.save() derives a school's cluster from whether an active cluster
    covers its sub-county, and re-runs that whenever the district or sub-county
    changes. When the school has no sub-county the lookup cannot run — and the
    old code read that as "no cluster found" and cleared the assignment.

    This is not an edge case here. The operational register leaves sub-county
    blank for every row, so every school in production has this shape, and a
    district-level cluster holding schools by direct assignment lost them on
    the next edit that touched their district — silently, while the cluster
    went on listing them.
    """

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Survive Region")
        cls.district = District.objects.create(
            name="Survive District", region=cls.region
        )
        cls.other_district = District.objects.create(
            name="Survive Other District", region=cls.region
        )
        cls.sub_county = SubCounty.objects.create(
            name="Survive Sub County", district=cls.district
        )
        cls.cluster = Cluster.objects.create(
            name="Survive Cluster",
            region=cls.region,
            district=cls.district,
            status="active",
        )

    def _assigned_school(self, ref, sub_county=None):
        school = School.objects.create(
            school_id=ref,
            name=f"School {ref}",
            region=self.region,
            district=self.district,
            sub_county=sub_county,
        )
        # Direct assignment, the way the cluster drawer adds a school.
        School.objects.filter(id=school.id).update(
            cluster_id=self.cluster.id, cluster_status="clustered"
        )
        school.refresh_from_db()
        return school

    def test_a_district_change_does_not_uncluster_a_sub_county_less_school(self):
        school = self._assigned_school("SURVIVE-1")

        school.district = self.other_district
        school.save()

        school.refresh_from_db()
        self.assertEqual(school.cluster_id, self.cluster.id)
        self.assertEqual(school.cluster_status, "clustered")

    def test_an_ordinary_save_leaves_the_assignment_alone(self):
        school = self._assigned_school("SURVIVE-2")

        school.name = "Renamed School"
        school.save()

        school.refresh_from_db()
        self.assertEqual(school.cluster_id, self.cluster.id)

    def test_derivation_still_clusters_a_school_whose_sub_county_is_covered(self):
        """The fix must not stop the derivation working where it can."""
        covered = SubCounty.objects.create(
            name="Survive Covered", district=self.district
        )
        ClusterSubCounty.objects.create(cluster=self.cluster, sub_county=covered)

        school = School.objects.create(
            school_id="SURVIVE-3",
            name="School SURVIVE-3",
            region=self.region,
            district=self.district,
            sub_county=covered,
        )

        self.assertEqual(school.cluster_id, self.cluster.id)
        self.assertEqual(school.cluster_status, "clustered")

    def test_a_school_whose_sub_county_is_not_covered_is_still_unclustered(self):
        """And it must still say no when the lookup CAN run and finds nothing —
        that is a real negative answer, not an absent one."""
        school = self._assigned_school("SURVIVE-4", sub_county=self.sub_county)

        school.district = self.other_district
        school.save()

        school.refresh_from_db()
        self.assertIsNone(school.cluster_id)
        self.assertEqual(school.cluster_status, "unclustered")


class DanglingClusterReferenceTest(TestCase):
    """A school must not point at a cluster that no longer exists.

    School.cluster_id is a CharField, not a foreign key, so the database
    cannot refuse a dangling reference and removing a Cluster does not cascade.
    The school kept cluster_status="clustered", so it still passed the Planning
    filter and appeared there with its cluster gone — and the resolver's
    fallback printed the raw identifier as the cluster's name, putting a CUID
    on screen where a name belonged.
    """

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Dangling Region")
        cls.district = District.objects.create(
            name="Dangling District", region=cls.region
        )
        cls.sub_county = SubCounty.objects.create(
            name="Dangling Sub County", district=cls.district
        )
        cls.admin = User.objects.create(
            id="dangling-admin",
            email="dangling@edify.org",
            name="Dangling Admin",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
            status="active",
        )

    def _school_pointing_at(self, cluster_id):
        school = School.objects.create(
            school_id="DANGLE-1",
            name="Dangling School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
        )
        School.objects.filter(id=school.id).update(
            cluster_id=cluster_id, cluster_status="clustered"
        )
        school.refresh_from_db()
        return school

    def test_a_missing_cluster_is_not_rendered_as_a_name(self):
        self._school_pointing_at("cluster-that-was-deleted")

        data = PlanningDashboardService.get_dashboard_data(self.admin, {})
        rows = [r for r in data["schools"] if r["schoolId"] == "DANGLE-1"]
        self.assertTrue(rows, "the row should still be reachable to be diagnosed")
        self.assertEqual(
            rows[0]["clusterName"],
            "Cluster missing",
            "a broken link must say so, not print the raw identifier as a name",
        )

    def test_the_repair_clears_the_link_and_is_idempotent(self):
        self._school_pointing_at("cluster-that-was-deleted")

        call_command("repair_dangling_clusters", "--apply")

        school = School.objects.get(school_id="DANGLE-1")
        self.assertIsNone(school.cluster_id)
        self.assertEqual(school.cluster_status, "unclustered")

        # Second run must be a no-op, not a second mutation.
        call_command("repair_dangling_clusters", "--apply")
        school.refresh_from_db()
        self.assertIsNone(school.cluster_id)

    def test_the_repair_leaves_a_real_link_alone(self):
        """It clears what is broken, not what is merely present."""
        cluster = Cluster.objects.create(
            name="Real Dangling-Test Cluster",
            region=self.region,
            district=self.district,
            status="active",
        )
        school = self._school_pointing_at(cluster.id)

        call_command("repair_dangling_clusters", "--apply")

        school.refresh_from_db()
        self.assertEqual(school.cluster_id, cluster.id)
        self.assertEqual(school.cluster_status, "clustered")

    def test_a_soft_deleted_cluster_counts_as_gone(self):
        from django.utils import timezone

        cluster = Cluster.objects.create(
            name="Withdrawn Cluster",
            region=self.region,
            district=self.district,
            status="active",
        )
        self._school_pointing_at(cluster.id)
        Cluster.objects.filter(id=cluster.id).update(deleted_at=timezone.now())

        call_command("repair_dangling_clusters", "--apply")

        school = School.objects.get(school_id="DANGLE-1")
        self.assertIsNone(
            school.cluster_id,
            "a school must not sit in a cluster that has been withdrawn",
        )
