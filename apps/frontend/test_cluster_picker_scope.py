"""A cluster picker offers only clusters the caller may actually work.

Schools were scoped everywhere and clusters were not, so a CCEO opening a
picker saw every cluster in the country beside a correctly narrowed school
list. Choosing one of the others moves the school into somebody else's
portfolio — and on the activity form the service then refused the choice, which
is the failure `cluster_in_scope` exists to prevent: a drawer must not offer
what the service rejects.

Three rules, and the second is the one that makes it a rule rather than a
tidier dropdown:

* the list is scoped;
* the *submitted* id is scoped too, because it arrives in a POST body;
* a user with no geography at all sees nothing, not everything.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.clusters.models import Cluster
from apps.core.scoping import cluster_in_scope, cluster_queryset, resolve_user_scope
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School

User = get_user_model()


class ClusterPickerScopeFixture(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Scope Region")
        self.mine = District.objects.create(name="Mine District", region=self.region)
        self.theirs = District.objects.create(
            name="Theirs District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Mine Sub County", district=self.mine
        )

        self.cceo_user, self.cceo = self._staff("cceo@scope.test", "CCEO")
        self.rival_user, self.rival = self._staff("rival@scope.test", "CCEO")
        self.nomad_user, self.nomad = self._staff("nomad@scope.test", "CCEO")
        self.admin_user, self.admin = self._staff("admin@scope.test", "Admin")
        self.pl_user, self.pl = self._staff("pl@scope.test", "Program Lead")

        self.school = self._school("SCOPE-1", self.mine, self.cceo)
        self._school("SCOPE-2", self.theirs, self.rival)

        # Ownership, not geography, is what makes a cluster yours. Both of
        # these sit in a district the CCEO has schools in for the district test
        # below — only the owner differs.
        self.my_cluster = self._cluster("Mine Cluster", self.mine, owner=self.cceo_user)
        self.their_cluster = self._cluster(
            "Theirs Cluster", self.theirs, owner=self.rival_user
        )
        self.same_district_other_owner = self._cluster(
            "Neighbour Cluster", self.mine, owner=self.rival_user
        )
        self.unowned = self._cluster("Unowned Cluster", self.mine)

    def _staff(self, email, role):
        user = User.objects.create(
            email=email,
            name=email.split("@")[0],
            roles=[role],
            active_role=role,
            is_active=True,
        )
        return user, StaffProfile.objects.create(user=user, title=role)

    def _school(self, ref, district, staff):
        school = School.objects.create(
            school_id=ref,
            name=f"School {ref}",
            region=self.region,
            district=district,
            sub_county=self.sub_county if district == self.mine else None,
            school_type="client",
            account_owner_id=staff.id,
        )
        StaffSchoolAssignment.objects.get_or_create(staff=staff, school_id=school.id)
        return school

    def _cluster(self, name, district, status="active", owner=None):
        return Cluster.objects.create(
            name=name,
            region=self.region,
            district=district,
            cluster_type="mixed",
            status=status,
            responsible_staff_id=(owner.user_id if owner else None),
        )


class TheQuerysetMatchesTheRuleTest(ClusterPickerScopeFixture):
    """`cluster_queryset` is the set form of `cluster_in_scope`. If the two
    disagree, a picker offers what the service will refuse."""

    def test_a_cceo_gets_only_the_clusters_they_are_responsible_for(self):
        """Not the district. "Neighbour Cluster" sits in the same district and
        belongs to somebody else, and that is the case the old geographic rule
        got wrong — four CCEOs sharing Mukono each saw all fifteen of its
        clusters and could move a school into any of them."""
        scope = resolve_user_scope(self.cceo_user)

        names = set(cluster_queryset(scope).values_list("name", flat=True))

        # "Unowned Cluster" is here because nobody owns it yet, not because the
        # district grants it — see the unassigned tests below.
        self.assertEqual(names, {"Mine Cluster", "Unowned Cluster"})
        self.assertNotIn("Neighbour Cluster", names)

    def test_sharing_a_district_is_not_sharing_a_cluster(self):
        scope = resolve_user_scope(self.cceo_user)

        self.assertFalse(cluster_in_scope(scope, self.same_district_other_owner))

    def test_an_unassigned_cluster_stays_claimable_in_its_district(self):
        """Ownership binds once it is set, not before.

        Every cluster created before the owner was captured has none, so a
        rule with no carve-out would be retroactive: nobody could schedule
        them and nobody could pick them up. `test_cceo_can_schedule_a_cluster
        _in_their_assigned_district` states the same requirement.
        """
        scope = resolve_user_scope(self.cceo_user)

        self.assertTrue(cluster_in_scope(scope, self.unowned))
        self.assertIn(
            "Unowned Cluster",
            set(cluster_queryset(scope).values_list("name", flat=True)),
        )

    def test_an_unassigned_cluster_elsewhere_is_still_out_of_reach(self):
        """The carve-out is district-bounded, not a hole."""
        far = self._cluster("Far Unowned", self.theirs)
        scope = resolve_user_scope(self.cceo_user)

        self.assertFalse(cluster_in_scope(scope, far))

    def test_a_cluster_holding_their_school_counts_as_theirs(self):
        """How a cluster becomes yours in practice before the column is set."""
        School.objects.filter(id=self.school.id).update(
            cluster_id=self.same_district_other_owner.id
        )
        scope = resolve_user_scope(self.cceo_user)

        self.assertIn(self.same_district_other_owner.id, scope.cluster_ids)
        self.assertTrue(cluster_in_scope(scope, self.same_district_other_owner))

    def test_it_agrees_with_cluster_in_scope_on_every_cluster(self):
        scope = resolve_user_scope(self.cceo_user)
        allowed = set(cluster_queryset(scope).values_list("id", flat=True))

        for cluster in Cluster.objects.all():
            with self.subTest(cluster=cluster.name):
                self.assertEqual(
                    cluster.id in allowed,
                    cluster_in_scope(scope, cluster),
                    "the queryset and the predicate must not disagree",
                )

    def test_a_user_with_no_schools_and_no_clusters_sees_nothing(self):
        """The old inline version skipped its filter when district_ids was
        empty, so the one person with no schools saw every cluster there is —
        including, now, every unassigned one."""
        scope = resolve_user_scope(self.nomad_user)

        self.assertEqual(list(cluster_queryset(scope)), [])
        self.assertFalse(cluster_in_scope(scope, self.their_cluster))
        self.assertFalse(cluster_in_scope(scope, self.unowned))

    def test_a_country_role_still_sees_all_of_them(self):
        scope = resolve_user_scope(self.admin_user)

        self.assertEqual(cluster_queryset(scope).count(), 4)

    def test_a_programme_lead_gets_their_cceos_clusters(self):
        """A PL is responsible for the team's clusters, so the supervisees'
        ids belong in the same owner set rather than a second branch."""
        from apps.accounts.models import StaffSupervisorAssignment

        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo, supervisor=self.pl
        )
        scope = resolve_user_scope(self.pl_user)

        names = set(cluster_queryset(scope).values_list("name", flat=True))

        self.assertIn("Mine Cluster", names)
        self.assertNotIn("Theirs Cluster", names)

    def test_deleted_clusters_are_never_offered(self):
        from django.utils import timezone

        self.my_cluster.deleted_at = timezone.now()
        self.my_cluster.save(update_fields=["deleted_at"])
        scope = resolve_user_scope(self.cceo_user)

        names = set(cluster_queryset(scope).values_list("name", flat=True))

        # Asserts the deleted one is gone, not that the list is empty: the
        # unassigned cluster in this district legitimately remains.
        self.assertNotIn("Mine Cluster", names)
        self.assertFalse(cluster_in_scope(scope, self.my_cluster))


class TheAddToClusterDrawerIsScopedTest(ClusterPickerScopeFixture):
    def test_the_dropdown_lists_only_their_own(self):
        self.client.force_login(self.cceo_user)

        response = self.client.get(f"/schools/{self.school.id}/add-to-cluster")
        body = response.content.decode()

        # Positive control: assertNotIn passes on a 404 or an error page, so
        # the test has to prove the picker rendered at all.
        self.assertEqual(response.status_code, 200)
        self.assertIn("Mine Cluster", body)
        self.assertNotIn("Theirs Cluster", body)

    def test_submitting_another_cceos_cluster_is_refused(self):
        """Narrowing the dropdown is not a rule — the id arrives in a POST."""
        self.client.force_login(self.cceo_user)

        response = self.client.post(
            f"/schools/{self.school.id}/add-to-cluster",
            {
                "cluster_action_type": "existing",
                "existing_cluster_id": self.their_cluster.id,
            },
        )

        self.assertNotEqual(response.status_code, 500)
        self.school.refresh_from_db()
        self.assertNotEqual(self.school.cluster_id, self.their_cluster.id)


class TheActivityPickerIsScopedTest(ClusterPickerScopeFixture):
    """This form scoped its school list and not its cluster list, so the two
    dropdowns on one page disagreed about whose work was being planned."""

    def test_the_cluster_dropdown_is_scoped_like_the_school_one(self):
        self.client.force_login(self.cceo_user)

        response = self.client.get("/planning/schedule?action=training")
        body = response.content.decode()

        # Positive control first: assertNotIn is satisfied by a 404, a redirect
        # or a traceback, so the test must prove the picker rendered.
        self.assertEqual(response.status_code, 200)
        self.assertIn("Mine Cluster", body)
        self.assertNotIn("Theirs Cluster", body)

    def test_a_cluster_id_in_the_query_string_cannot_preselect_out_of_scope(self):
        self.client.force_login(self.cceo_user)

        response = self.client.get(
            f"/planning/schedule?action=training&cluster={self.their_cluster.id}"
        )
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Theirs Cluster", body)


class TheDrawerExplainsAnEmptyPickerTest(ClusterPickerScopeFixture):
    """A CCEO responsible for no cluster sees why, not a blank select.

    Scoping clusters to their owner means a person can legitimately have none,
    and an empty dropdown with no explanation reads as a broken page rather
    than as a fact about assignment.
    """

    def test_a_cceo_with_no_clusters_is_told_why(self):
        # Every cluster owned by somebody else: nothing of theirs, and nothing
        # unassigned to fall back to.
        Cluster.objects.all().update(responsible_staff_id=self.rival_user.user_id)
        self.client.force_login(self.cceo_user)

        response = self.client.get(f"/schools/{self.school.id}/add-to-cluster")
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        # The wording is the eligibility rule's, not the old scope message's.
        self.assertIn("No active cluster owned by", body)
        self.assertNotIn("Mine Cluster", body)

    def test_a_cceo_with_clusters_gets_the_picker_not_the_message(self):
        self.client.force_login(self.cceo_user)

        body = self.client.get(
            f"/schools/{self.school.id}/add-to-cluster"
        ).content.decode()

        self.assertIn("Mine Cluster", body)
        self.assertNotIn("No active cluster owned by", body)


class ACreatedClusterBelongsToItsCreatorTest(ClusterPickerScopeFixture):
    """Otherwise a CCEO builds a cluster that vanishes from their own picker.

    Ownership decides visibility now, so a create that left the column null
    would hand somebody a cluster they could not then use.
    """

    def test_a_cceo_owns_what_they_create(self):
        from apps.geography.models import SubCounty

        sub_county = SubCounty.objects.create(
            name="Create Sub County", district=self.mine
        )
        self.client.force_login(self.cceo_user)

        self.client.post(
            "/clusters/create",
            {
                "name": "Made By CCEO",
                "district_id": self.mine.id,
                "sub_county_ids": [sub_county.id],
                "cluster_type": "mixed",
            },
        )

        cluster = Cluster.objects.filter(name="Made By CCEO").first()
        self.assertIsNotNone(cluster, "the cluster was not created")
        self.assertEqual(cluster.responsible_staff_id, self.cceo_user.user_id)
        self.assertTrue(
            cluster_in_scope(resolve_user_scope(self.cceo_user), cluster),
            "a cluster its creator cannot see is worse than no cluster",
        )
