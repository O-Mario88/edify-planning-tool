"""A cluster that HAS an owner must open.

`cluster_detail` resolved its owner with
`StaffProfile.objects.filter(staff_id=...)`. StaffProfile has no `staff_id`
field — it has `id`, `user_id` and `staff_number` — so the lookup raised
FieldError and the page showed "Error loading cluster details: Cannot resolve
keyword 'staff_id' into field" instead of the cluster.

It shipped because nothing ever executed that branch. It runs only when
`cluster.responsible_staff_id` is set, and every Cluster built in the test
suite (and by the seed) is created without one — so every test opened an
unowned cluster, took the "Unassigned" path, and passed. A page can be broken
for every real cluster in production while its tests are green.

The other half of the rule is which id the field holds. Operational records
carry EITHER a StaffProfile id or a legacy User id — see
apps.core.calendar_policy.resolve_scheduling_user — so resolving only one of
them shows "Unassigned" for a cluster that plainly has an owner.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.clusters.models import Cluster
from apps.clusters.services import cluster_detail
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty


class ClusterDetailResolvesItsOwnerTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="cluster-owner@edify.test",
            password="password123",
            name="Cluster Owner",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            is_active=True,
        )
        cls.profile = StaffProfile.objects.create(
            user=cls.user, title="CD", country="Uganda", staff_number="ST-OWNER"
        )
        cls.region = Region.objects.create(name="Owner Region")
        cls.district = District.objects.create(name="Owner District", region=cls.region)
        cls.sub_county = SubCounty.objects.create(
            name="Owner Sub-County", district=cls.district
        )
        cls.cluster = Cluster.objects.create(
            name="Owned Cluster",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            status="active",
        )

    def _detail_with_owner(self, owner_id):
        Cluster.objects.filter(id=self.cluster.id).update(responsible_staff_id=owner_id)
        return cluster_detail(self.cluster.id, self.user)

    def test_an_owner_stored_as_a_staff_profile_id_opens_and_names_them(self):
        detail = self._detail_with_owner(self.profile.id)
        self.assertEqual(detail["assignedStaff"], "Cluster Owner")

    def test_an_owner_stored_as_a_legacy_user_id_resolves_to_the_same_person(self):
        """Both id spaces are live. Resolving one and not the other reports a
        cluster with a named owner as Unassigned."""
        detail = self._detail_with_owner(self.user.id)
        self.assertEqual(detail["assignedStaff"], "Cluster Owner")

    def test_an_unowned_cluster_still_reads_unassigned(self):
        detail = self._detail_with_owner(None)
        self.assertEqual(detail["assignedStaff"], "Unassigned")

    def test_an_owner_id_matching_nothing_does_not_raise(self):
        """Dangling ids exist (a staff member deleted after assignment). The
        page must still open — that is the whole failure being fixed."""
        detail = self._detail_with_owner("no-such-staff-id")
        self.assertIn("assignedStaff", detail)
