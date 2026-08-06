"""INC-000001: adding a school to a cluster returned a 500.

The drawer's "create a new cluster" branch wrapped its service call and
re-rendered with the reason. The "add to an existing cluster" branch three
lines below did not, so every rejection the domain raises arrived as a server
error instead of a sentence.

There are four of them, and none is exotic:

  * the school's district does not match the cluster's;
  * the cluster was retired between the drawer rendering and the form being
    submitted — a real race, because the drawer lists clusters;
  * the school is outside the actor's scope;
  * the cluster is outside the actor's scope.

A 500 here is worse than the refusal it replaced. The user cannot tell whether
the assignment happened, and the honest answer — "that school is in a different
district" — was already computed and then thrown away.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.clusters.models import Cluster, ClusterSubCounty
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School

User = get_user_model()


class AddToClusterErrorsAreShownNotThrownTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="INC1 Region")
        self.district = District.objects.create(
            name="INC1 District", region=self.region
        )
        self.other_district = District.objects.create(
            name="INC1 Other District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="INC1 Sub County", district=self.district
        )

        self.user = User.objects.create(
            id="inc1-admin",
            email="inc1-admin@edify.org",
            name="INC1 Admin",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        self.profile = StaffProfile.objects.create(
            id="inc1-sp", user=self.user, title="Admin"
        )

        # The production shape: a school with a sub-county, in a district.
        self.school = School.objects.create(
            school_id="INC1-SCH",
            name="INC1 School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
            account_owner_id=self.profile.id,
        )
        StaffSchoolAssignment.objects.get_or_create(
            staff=self.profile, school_id=self.school.id
        )
        self.client.force_login(self.user)

    def _cluster(self, *, district, status="active"):
        cluster = Cluster.objects.create(
            name=f"INC1 Cluster {district.name}",
            region=self.region,
            district=district,
            cluster_type="mixed",
            status=status,
        )
        return cluster

    def _post(self, cluster):
        return self.client.post(
            f"/schools/{self.school.id}/add-to-cluster",
            {"cluster_action_type": "existing", "existing_cluster_id": cluster.id},
        )

    def test_a_cluster_in_another_district_is_refused_not_crashed(self):
        """The likeliest production trigger. A school may only join a cluster
        in its own district, and saying so is the whole job."""
        cluster = self._cluster(district=self.other_district)
        response = self._post(cluster)

        self.assertNotEqual(
            response.status_code,
            500,
            "a domain rejection must not reach the user as a server error",
        )
        self.assertEqual(response.status_code, 200)
        self.school.refresh_from_db()
        self.assertNotEqual(
            self.school.cluster_id,
            cluster.id,
            "a refused assignment must not have been applied",
        )

    def test_the_refusal_explains_itself(self):
        cluster = self._cluster(district=self.other_district)
        body = self._post(cluster).content.decode().lower()
        self.assertIn(
            "district",
            body,
            "the user needs the reason, which the service already computed",
        )

    def test_a_cluster_retired_after_the_drawer_rendered_is_refused_cleanly(self):
        """The race the drawer creates by listing clusters: one is withdrawn
        between render and submit."""
        cluster = self._cluster(district=self.district)
        Cluster.objects.filter(id=cluster.id).update(status="inactive")

        response = self._post(cluster)
        self.assertNotEqual(response.status_code, 500)
        self.school.refresh_from_db()
        self.assertNotEqual(self.school.cluster_id, cluster.id)

    def test_the_working_path_still_works(self):
        """A refusal path that swallowed real assignments would be its own
        incident."""
        cluster = self._cluster(district=self.district)
        ClusterSubCounty.objects.create(cluster=cluster, sub_county=self.sub_county)

        response = self._post(cluster)
        self.assertEqual(response.status_code, 200)
        self.school.refresh_from_db()
        self.assertEqual(self.school.cluster_id, cluster.id)
        self.assertEqual(self.school.cluster_status, "clustered")

    def test_the_drawer_renders_for_the_production_school_shape(self):
        """GET, for a school that has a sub-county and a covering cluster —
        the shape the local development database happens not to contain."""
        cluster = self._cluster(district=self.district)
        ClusterSubCounty.objects.create(cluster=cluster, sub_county=self.sub_county)

        response = self.client.get(f"/schools/{self.school.id}/add-to-cluster")
        self.assertEqual(response.status_code, 200)

    def test_the_cluster_directory_branch_renders(self):
        """The branch no local database exercises.

        show_cluster_directory is only true when a school HAS a sub-county and
        NO cluster covers it. Every school in the development database lacks a
        sub-county, so this path — including its schools_count annotation —
        never runs locally, which is precisely how a defect in it would reach
        production unseen.
        """
        # A cluster in the district that does NOT cover this sub-county, so the
        # directory is offered rather than an automatic match.
        other_sub_county = SubCounty.objects.create(
            name="INC1 Elsewhere", district=self.district
        )
        cluster = self._cluster(district=self.district)
        ClusterSubCounty.objects.create(cluster=cluster, sub_county=other_sub_county)

        response = self.client.get(f"/schools/{self.school.id}/add-to-cluster")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["show_cluster_directory"])
        # The annotation is evaluated here, not at queryset construction.
        self.assertEqual(
            [c.schools_count for c in response.context["all_clusters"]], [0]
        )
