"""A cluster's status must be a status a cluster can have.

There are two similarly-named vocabularies and they describe different things:

* `ClusterStatus` — unclustered / clustered / needs_review — is a **school's**
  clustering state, stored on `School.cluster_status`;
* `ClusterRecordStatus` — active / needs_review / inactive — is the **cluster
  record's** own state, stored on `Cluster.status`.

The seed wrote "clustered" into `Cluster.status`. Django does not enforce
choices at the database level, so 15 clusters saved without complaint and then
matched nothing: every cluster surface selects active/needs_review, so a
country with 16 clusters showed one. Nothing errored, which is what made it
survive — the list simply looked short.

These tests pin the vocabulary rather than the symptom, so the next value
written into the wrong column fails here instead of quietly hiding a cluster.
"""

from __future__ import annotations

from django.test import TestCase

from apps.clusters.models import Cluster
from apps.core.enums import ClusterRecordStatus, ClusterStatus
from apps.geography.models import District, Region

VALID = {choice.value for choice in ClusterRecordStatus}


class TheTwoVocabulariesAreDistinctTest(TestCase):
    def test_clustered_is_a_school_state_and_not_a_cluster_record_state(self):
        """The confusion this whole file exists to prevent."""
        self.assertIn(ClusterStatus.CLUSTERED.value, {c.value for c in ClusterStatus})
        self.assertNotIn(ClusterStatus.CLUSTERED.value, VALID)

    def test_the_model_declares_the_record_vocabulary(self):
        field = Cluster._meta.get_field("status")

        self.assertEqual({value for value, _ in field.choices}, VALID)


class NoClusterCarriesAnInvalidStatusTest(TestCase):
    """Runs against whatever the test database contains, so a fixture or a
    migration that reintroduces the bad value is caught here."""

    def setUp(self):
        self.region = Region.objects.create(name="Vocab Region")
        self.district = District.objects.create(
            name="Vocab District", region=self.region
        )

    def _cluster(self, name, status):
        return Cluster.objects.create(
            name=name,
            region=self.region,
            district=self.district,
            cluster_type="mixed",
            status=status,
        )

    def test_a_valid_status_is_accepted(self):
        cluster = self._cluster("Good", ClusterRecordStatus.ACTIVE)

        self.assertIn(cluster.status, VALID)

    def test_full_clean_rejects_a_school_state(self):
        """`full_clean` is where the choices actually bite. The seed used
        `objects.create`, which does not call it — which is exactly why the
        wrong value reached the database in the first place."""
        from django.core.exceptions import ValidationError

        cluster = Cluster(
            name="Bad",
            region=self.region,
            district=self.district,
            cluster_type="mixed",
            status=ClusterStatus.CLUSTERED.value,
        )

        with self.assertRaises(ValidationError) as caught:
            cluster.full_clean()

        self.assertIn("status", caught.exception.message_dict)

    def test_every_cluster_in_the_database_uses_the_record_vocabulary(self):
        self._cluster("A", ClusterRecordStatus.ACTIVE)
        self._cluster("B", ClusterRecordStatus.NEEDS_REVIEW)
        self._cluster("C", ClusterRecordStatus.INACTIVE)

        offenders = [
            (c.name, c.status) for c in Cluster.objects.all() if c.status not in VALID
        ]

        self.assertEqual(offenders, [], f"clusters with an invalid status: {offenders}")


class TheSeedProducesVisibleClustersTest(TestCase):
    """The bug's actual consequence: a cluster nobody can see.

    `list_clusters` selects active/needs_review, so a cluster saved with any
    other value is absent from every cluster surface while still counting in
    `Cluster.objects.count()` — the shape that made this look like a short
    list rather than a defect.
    """

    def setUp(self):
        self.region = Region.objects.create(name="Seed Region")
        self.district = District.objects.create(
            name="Seed District", region=self.region
        )

    def test_a_cluster_with_a_school_state_would_be_invisible(self):
        from apps.clusters.services import list_clusters
        from apps.accounts.models import StaffProfile, User
        from apps.core.rbac import EdifyRole

        user = User.objects.create(
            email="cd@vocab.test",
            name="Vocab CD",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            is_active=True,
        )
        StaffProfile.objects.create(user=user, title="CD")

        Cluster.objects.create(
            name="Visible",
            region=self.region,
            district=self.district,
            cluster_type="mixed",
            status=ClusterRecordStatus.ACTIVE,
        )
        Cluster.objects.create(
            name="Invisible",
            region=self.region,
            district=self.district,
            cluster_type="mixed",
            status=ClusterStatus.CLUSTERED.value,
        )

        listed = {c["name"] for c in list_clusters(user)}

        self.assertIn("Visible", listed)
        self.assertNotIn(
            "Invisible",
            listed,
            "a cluster saved with a school state is absent from every surface",
        )
        self.assertEqual(Cluster.objects.count(), 2, "yet both exist in the table")


class ACreatedClusterKeepsItsOwnerTest(TestCase):
    """Creating a cluster asks who owns it.

    `create_cluster` has always accepted `responsibleStaffId`, and the edit
    drawer has always sent it — but the create form never rendered the field
    and `create_cluster_view` never read it, so every cluster was born
    ownerless and could only gain an owner by being edited afterwards. That is
    why `Cluster.responsible_staff_id` was null on every row.
    """

    def setUp(self):
        from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
        from apps.core.rbac import EdifyRole
        from apps.geography.models import SubCounty
        from apps.schools.models import School

        self.region = Region.objects.create(name="Owner Region")
        self.district = District.objects.create(
            name="Owner District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Owner Sub County", district=self.district
        )

        self.admin = User.objects.create(
            email="admin@owner.test",
            name="Owner Admin",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            is_active=True,
        )
        StaffProfile.objects.create(user=self.admin, title="Admin")

        self.cceo = User.objects.create(
            email="cceo@owner.test",
            name="Owner CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
        )
        self.cceo_profile = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        school = School.objects.create(
            school_id="OWN-1",
            name="Owner School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_profile, school_id=school.id
        )

    def test_the_create_drawer_offers_the_field(self):
        self.client.force_login(self.admin)

        body = self.client.get(
            f"/clusters/create-drawer?district_id={self.district.id}"
        ).content.decode()

        self.assertIn('name="responsible_staff_id"', body)
        self.assertIn("Owner CCEO", body)

    def test_the_chosen_owner_is_stored(self):
        self.client.force_login(self.admin)

        self.client.post(
            "/clusters/create",
            {
                "name": "Owned Cluster",
                "district_id": self.district.id,
                "sub_county_ids": [self.sub_county.id],
                "cluster_type": "mixed",
                "responsible_staff_id": self.cceo.user_id,
            },
        )

        cluster = Cluster.objects.filter(name="Owned Cluster").first()
        self.assertIsNotNone(cluster, "the cluster was not created")
        self.assertEqual(cluster.responsible_staff_id, self.cceo.user_id)

    def test_creating_without_an_owner_is_still_allowed(self):
        """The field is optional — a cluster may be made before anyone owns it."""
        self.client.force_login(self.admin)

        self.client.post(
            "/clusters/create",
            {
                "name": "Unowned Cluster",
                "district_id": self.district.id,
                "sub_county_ids": [self.sub_county.id],
                "cluster_type": "mixed",
                "responsible_staff_id": "",
            },
        )

        cluster = Cluster.objects.filter(name="Unowned Cluster").first()
        self.assertIsNotNone(cluster)
        self.assertIsNone(cluster.responsible_staff_id)
