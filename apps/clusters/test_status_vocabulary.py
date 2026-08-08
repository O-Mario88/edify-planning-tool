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


class ASchoolOnlyJoinsAClusterInItsOwnDistrictTest(TestCase):
    """Ownership decides *whose* cluster it is; district decides which clusters
    a school can join at all.

    Clusters are built from a district's sub-counties, so a cross-district
    membership is not a stretch of the rule — it contradicts how the cluster
    was defined. `set_school_cluster_membership` enforces it, and the two paths
    that write `cluster_id` without going through it are checked here too.
    """

    def setUp(self):
        from apps.geography.models import SubCounty

        self.region = Region.objects.create(name="Cross Region")
        self.here = District.objects.create(name="Here District", region=self.region)
        self.there = District.objects.create(name="There District", region=self.region)
        self.here_sc = SubCounty.objects.create(name="Here SC", district=self.here)
        self.there_sc = SubCounty.objects.create(name="There SC", district=self.there)

    def _cluster(self, name, district, sub_county):
        return Cluster.objects.create(
            name=name,
            region=self.region,
            district=district,
            sub_county=sub_county,
            cluster_type="mixed",
            status=ClusterRecordStatus.ACTIVE,
        )

    def _school(self, ref, district, sub_county):
        from apps.schools.models import School

        return School.objects.create(
            school_id=ref,
            name=f"School {ref}",
            region=self.region,
            district=district,
            sub_county=sub_county,
            school_type="client",
        )

    def test_the_canonical_setter_refuses_a_cross_district_cluster(self):
        from apps.clusters.services import set_school_cluster_membership
        from apps.core.exceptions import BadRequest

        school = self._school("X-1", self.here, self.here_sc)
        far = self._cluster("Far Cluster", self.there, self.there_sc)

        with self.assertRaises(BadRequest) as caught:
            set_school_cluster_membership(school, far, "tester")

        self.assertIn("own district", str(caught.exception))

    def test_the_setter_accepts_a_cluster_in_the_same_district(self):
        from apps.clusters.services import set_school_cluster_membership

        school = self._school("X-2", self.here, self.here_sc)
        near = self._cluster("Near Cluster", self.here, self.here_sc)

        set_school_cluster_membership(school, near, "tester")

        school.refresh_from_db()
        self.assertEqual(school.cluster_id, near.id)

    def test_auto_clustering_on_save_stays_inside_the_district(self):
        """`School.save()` derives a cluster from the sub-county and writes
        `cluster_id` directly, never reaching the setter above. A cluster in
        another district that somehow covers this sub-county must not be
        picked up."""
        from apps.clusters.models import ClusterSubCounty

        foreign = self._cluster("Foreign Cluster", self.there, self.there_sc)
        # The shape the transitive argument assumes cannot happen: a cluster in
        # There covering a sub-county in Here.
        ClusterSubCounty.objects.create(cluster=foreign, sub_county=self.here_sc)

        school = self._school("X-3", self.here, self.here_sc)
        school.save()
        school.refresh_from_db()

        self.assertNotEqual(
            school.cluster_id,
            foreign.id,
            "auto-clustering crossed a district boundary",
        )

    def test_auto_clustering_still_finds_the_right_cluster(self):
        """The district filter must not stop the normal case working."""
        near = self._cluster("Right Cluster", self.here, self.here_sc)

        school = self._school("X-4", self.here, self.here_sc)
        school.save()
        school.refresh_from_db()

        self.assertEqual(school.cluster_id, near.id)


class ThePortfolioAuditReadsRatherThanGuessesTest(TestCase):
    """The audit's job is to be believed.

    Two ways it stops being useful: reporting a count that is really a scan
    limit, and merging states that call for opposite responses. Both happened
    while writing it — an inactive-owner check reported 16,274 schools at high
    severity when the real finding was "these staff have not accepted their
    invitations yet".
    """

    def setUp(self):
        from apps.accounts.models import StaffProfile, User
        from apps.core.rbac import EdifyRole
        from apps.schools.models import School

        self.region = Region.objects.create(name="Audit Region")
        self.district = District.objects.create(
            name="Audit District", region=self.region
        )

        def staff(email, *, active, status):
            user = User.objects.create(
                email=email,
                name=email.split("@")[0],
                roles=[EdifyRole.CCEO.value],
                active_role=EdifyRole.CCEO.value,
                is_active=active,
                status=status,
            )
            return StaffProfile.objects.create(user=user, title="CCEO")

        self.live = staff("live@audit.test", active=True, status="active")
        self.invited = staff(
            "invited@audit.test", active=False, status="pending_invited"
        )
        self.gone = staff("gone@audit.test", active=False, status="deactivated")

        def school(ref, owner, district=None):
            return School.objects.create(
                school_id=ref,
                name=f"School {ref}",
                region=self.region,
                district=district if district is not None else self.district,
                school_type="client",
                account_owner_id=owner.id if owner else "",
            )

        self.ok = school("AUD-OK", self.live)
        self.pending = school("AUD-PENDING", self.invited)
        self.orphan = school("AUD-GONE", self.gone)

    def _check(self, key):
        from apps.clusters.portfolio_audit import report

        return next(c for c in report()["checks"] if c["key"] == key)

    def test_a_pending_invite_is_not_reported_as_a_departed_owner(self):
        """The distinction the whole split exists for."""
        pending = self._check("school_owner_pending_invite")
        gone = self._check("school_owner_unreachable")

        self.assertEqual(pending["count"], 1)
        self.assertEqual(pending["severity"], "medium")
        self.assertEqual(gone["count"], 1)
        self.assertEqual(gone["severity"], "high")

    def test_a_correctly_owned_school_appears_in_neither(self):
        for key in ("school_owner_pending_invite", "school_owner_unreachable"):
            with self.subTest(check=key):
                subjects = {r["school"] for r in self._check(key)["examples"]}
                self.assertNotIn("AUD-OK", subjects)

    def test_a_school_with_no_district_is_high_and_not_guessable(self):
        from apps.schools.models import School

        School.objects.filter(id=self.ok.id).update(district=None)

        check = self._check("school_without_district")

        self.assertEqual(check["count"], 1)
        self.assertEqual(check["classification"], "manual")

    def test_the_audit_writes_nothing(self):
        """It is a reading. A repair that ran on inspection would be the worst
        possible shape for this."""
        from apps.clusters.portfolio_audit import report
        from apps.schools.models import School

        before = list(
            School.objects.order_by("school_id").values_list(
                "school_id", "account_owner_id", "district_id"
            )
        )

        report()

        self.assertEqual(
            before,
            list(
                School.objects.order_by("school_id").values_list(
                    "school_id", "account_owner_id", "district_id"
                )
            ),
        )
