"""The demo seed must produce clusters that can actually be planned into.

Every scheduling surface in the platform is gated on cluster membership: the
Planning page lists only clustered schools, and the cluster scheduler refuses
an empty cluster ("no active schools, so there is nobody to invite"). A seed
that creates clusters but leaves every school unclustered therefore produces a
demo in which no visit, meeting, training or partner assignment can be planned
at all — which presents as "scheduling does not save".
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.clusters.models import Cluster
from apps.clusters.services import active_school_count
from apps.schools.models import School


@override_settings(IS_PRODUCTION=False)
class SeedClusterMembershipTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed", "--demo", stdout=StringIO(), stderr=StringIO())

    def test_seeded_clusters_hold_schools(self):
        populated = [
            c
            for c in Cluster.objects.filter(status="active", deleted_at__isnull=True)
            if active_school_count(c.id) > 0
        ]
        self.assertGreater(
            len(populated),
            0,
            "The demo seed left every cluster empty, so nothing can be planned.",
        )

    def test_seeded_schools_are_clustered(self):
        self.assertGreater(
            School.objects.filter(
                cluster_status="clustered", deleted_at__isnull=True
            ).count(),
            0,
            "No seeded school is clustered, so the Planning page is empty.",
        )

    def test_a_clustered_school_agrees_with_its_cluster(self):
        """Membership is only usable if the pointer and the status agree, and
        the cluster covers the school's own sub-county — the two rules
        ``set_school_cluster_membership`` enforces on every real write."""
        school = School.objects.filter(
            cluster_status="clustered", deleted_at__isnull=True
        ).first()
        self.assertIsNotNone(school)
        cluster = Cluster.objects.get(id=school.cluster_id)
        self.assertEqual(cluster.district_id, school.district_id)
        self.assertTrue(
            cluster.sub_county_id == school.sub_county_id
            or cluster.covered_sub_counties.filter(
                sub_county_id=school.sub_county_id
            ).exists()
        )
