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

        self.school = self._school("SCOPE-1", self.mine, self.cceo)
        self._school("SCOPE-2", self.theirs, self.rival)

        self.my_cluster = self._cluster("Mine Cluster", self.mine)
        self.their_cluster = self._cluster("Theirs Cluster", self.theirs)

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

    def _cluster(self, name, district, status="active"):
        return Cluster.objects.create(
            name=name,
            region=self.region,
            district=district,
            cluster_type="mixed",
            status=status,
        )


class TheQuerysetMatchesTheRuleTest(ClusterPickerScopeFixture):
    """`cluster_queryset` is the set form of `cluster_in_scope`. If the two
    disagree, a picker offers what the service will refuse."""

    def test_a_cceo_gets_their_district_and_not_another(self):
        scope = resolve_user_scope(self.cceo_user)

        names = set(cluster_queryset(scope).values_list("name", flat=True))

        self.assertEqual(names, {"Mine Cluster"})

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

    def test_a_user_with_no_geography_sees_nothing_rather_than_everything(self):
        """The old inline version skipped its filter when district_ids was
        empty, so the one person with no schools saw every cluster there is."""
        scope = resolve_user_scope(self.nomad_user)

        self.assertEqual(scope.district_ids, [])
        self.assertEqual(list(cluster_queryset(scope)), [])
        self.assertFalse(cluster_in_scope(scope, self.their_cluster))

    def test_a_country_role_still_sees_all_of_them(self):
        scope = resolve_user_scope(self.admin_user)

        self.assertEqual(cluster_queryset(scope).count(), 2)

    def test_deleted_clusters_are_never_offered(self):
        from django.utils import timezone

        self.my_cluster.deleted_at = timezone.now()
        self.my_cluster.save(update_fields=["deleted_at"])
        scope = resolve_user_scope(self.cceo_user)

        self.assertEqual(list(cluster_queryset(scope)), [])


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
