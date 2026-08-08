"""The eligible-cluster rule, and the scenario it was specified with.

    Eligible cluster
      = active cluster
      + owned by the school's own staff owner
      + in the school's district
      + in the school's sub-county, when the school has one

The worked example from the specification is the acceptance case, so it is
written here as given rather than paraphrased into something easier to pass:
James owns Chegere North and Chegere South in Apac; Mary owns Chegere Central;
James also owns Akokoro. Assigning St. Mary Primary — James's school, in Apac,
in Chegere — must offer exactly two clusters.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.clusters.eligibility import (
    eligible_clusters_for_school,
    ineligibility_reason,
)
from apps.clusters.models import Cluster, ClusterSubCounty
from apps.core.enums import ClusterRecordStatus
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


class EligibilityFixture(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="North")
        self.apac = District.objects.create(name="Apac", region=self.region)
        self.kole = District.objects.create(name="Kole", region=self.region)
        self.chegere = SubCounty.objects.create(name="Chegere", district=self.apac)
        self.akokoro = SubCounty.objects.create(name="Akokoro", district=self.apac)

        self.james, self.james_profile = self._staff("james@edify.test")
        self.mary, self.mary_profile = self._staff("mary@edify.test")

        self.school = self._school(
            "ST-MARY",
            "St. Mary Primary School",
            self.james_profile,
            district=self.apac,
            sub_county=self.chegere,
        )

        self.chegere_north = self._cluster(
            "Chegere North Cluster", self.james, self.apac, self.chegere
        )
        self.chegere_south = self._cluster(
            "Chegere South Cluster", self.james, self.apac, self.chegere
        )
        self.chegere_central = self._cluster(
            "Chegere Central Cluster", self.mary, self.apac, self.chegere
        )
        self.akokoro_cluster = self._cluster(
            "Akokoro Cluster", self.james, self.apac, self.akokoro
        )

    def _staff(self, email):
        user = User.objects.create(
            email=email,
            name=email.split("@")[0].title(),
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
        )
        return user, StaffProfile.objects.create(user=user, title="CCEO")

    def _school(self, ref, name, owner_profile, *, district, sub_county):
        school = School.objects.create(
            school_id=ref,
            name=name,
            region=self.region,
            district=district,
            sub_county=sub_county,
            school_type="client",
            account_owner_id=owner_profile.id,
            account_owner_status="matched",
        )
        StaffSchoolAssignment.objects.get_or_create(
            staff=owner_profile, school_id=school.id
        )
        return school

    def _cluster(self, name, owner_user, district, sub_county, *, status=None):
        return Cluster.objects.create(
            name=name,
            region=self.region,
            district=district,
            sub_county=sub_county,
            cluster_type="mixed",
            status=status or ClusterRecordStatus.ACTIVE,
            responsible_staff_id=owner_user.user_id,
        )

    def _names(self, school=None):
        return set(
            eligible_clusters_for_school(school or self.school).values_list(
                "name", flat=True
            )
        )


class TheWorkedExampleTest(EligibilityFixture):
    def test_it_offers_exactly_the_two_clusters_named(self):
        self.assertEqual(
            self._names(),
            {"Chegere North Cluster", "Chegere South Cluster"},
        )

    def test_it_excludes_another_owners_cluster_in_the_same_sub_county(self):
        """Mary's Chegere Central sits in the same district and sub-county;
        only the owner differs, which is the whole rule."""
        self.assertNotIn("Chegere Central Cluster", self._names())

    def test_it_excludes_the_owners_own_cluster_in_another_sub_county(self):
        """James owns Akokoro, and it is still wrong for a Chegere school."""
        self.assertNotIn("Akokoro Cluster", self._names())

    def test_it_excludes_another_district(self):
        far = self._cluster(
            "Kole Cluster",
            self.james,
            self.kole,
            SubCounty.objects.create(name="Kole SC", district=self.kole),
        )

        self.assertNotIn(far.name, self._names())

    def test_it_excludes_inactive_and_archived_clusters(self):
        for status in (ClusterRecordStatus.INACTIVE, ClusterRecordStatus.NEEDS_REVIEW):
            with self.subTest(status=status):
                Cluster.objects.filter(id=self.chegere_north.id).update(status=status)
                self.assertNotIn("Chegere North Cluster", self._names())

    def test_it_excludes_deleted_clusters(self):
        from django.utils import timezone

        Cluster.objects.filter(id=self.chegere_north.id).update(
            deleted_at=timezone.now()
        )

        self.assertNotIn("Chegere North Cluster", self._names())

    def test_declared_coverage_counts_as_the_sub_county(self):
        """A cluster reaches a sub-county as its primary one or through its
        declared coverage; both are the cluster claiming that ground."""
        ClusterSubCounty.objects.create(
            cluster=self.akokoro_cluster, sub_county=self.chegere
        )

        self.assertIn("Akokoro Cluster", self._names())


class TheSubCountyFallbackTest(EligibilityFixture):
    """A school without a sub-county still has to be clusterable."""

    def test_without_a_sub_county_it_widens_to_the_district(self):
        School.objects.filter(id=self.school.id).update(sub_county=None)
        self.school.refresh_from_db()

        names = self._names()

        self.assertIn("Chegere North Cluster", names)
        self.assertIn("Akokoro Cluster", names)
        self.assertNotIn("Chegere Central Cluster", names, "owner still applies")

    def test_it_never_widens_past_the_district_or_the_owner(self):
        School.objects.filter(id=self.school.id).update(sub_county=None)
        self.school.refresh_from_db()
        self._cluster(
            "Kole Cluster",
            self.james,
            self.kole,
            SubCounty.objects.create(name="Kole SC", district=self.kole),
        )

        names = self._names()

        self.assertNotIn("Kole Cluster", names)
        self.assertNotIn("Chegere Central Cluster", names)


class MissingOwnerOrDistrictTest(EligibilityFixture):
    """No owner or no district is a data-quality problem, not a licence to
    offer everything."""

    def test_a_school_with_no_owner_gets_nothing_and_a_reason(self):
        School.objects.filter(id=self.school.id).update(account_owner_id="")
        self.school.refresh_from_db()

        self.assertEqual(self._names(), set())
        self.assertIn("no assigned staff owner", ineligibility_reason(self.school))

    def test_a_school_with_no_district_gets_nothing_and_a_reason(self):
        School.objects.filter(id=self.school.id).update(district=None)
        self.school.refresh_from_db()

        self.assertEqual(self._names(), set())
        self.assertIn("no district", ineligibility_reason(self.school))

    def test_a_complete_school_has_no_reason_to_show(self):
        self.assertIsNone(ineligibility_reason(self.school))


class BothIdSpacesResolveTest(EligibilityFixture):
    """`School.account_owner_id` and `Cluster.responsible_staff_id` are plain
    CharFields written by paths that disagree about which id they store."""

    def test_a_cluster_owned_by_the_profile_id_still_matches(self):
        Cluster.objects.filter(id=self.chegere_north.id).update(
            responsible_staff_id=self.james_profile.id
        )

        self.assertIn("Chegere North Cluster", self._names())

    def test_a_school_owned_by_the_user_id_still_matches(self):
        School.objects.filter(id=self.school.id).update(
            account_owner_id=self.james.user_id
        )
        self.school.refresh_from_db()

        self.assertIn("Chegere North Cluster", self._names())


class TheServiceEnforcesItToo(EligibilityFixture):
    """Filtering a dropdown is not a rule. Bulk assignment, the API and a
    management command all reach the setter without passing a dropdown."""

    def _assign(self, cluster):
        from apps.clusters.services import set_school_cluster_membership

        return set_school_cluster_membership(self.school, cluster, "tester")

    def test_an_eligible_cluster_is_accepted(self):
        self._assign(self.chegere_north)

        self.school.refresh_from_db()
        self.assertEqual(self.school.cluster_id, self.chegere_north.id)

    def test_another_owners_cluster_is_refused(self):
        with self.assertRaises(BadRequest) as caught:
            self._assign(self.chegere_central)

        self.assertIn("another staff member", str(caught.exception))

    def test_another_sub_county_is_refused(self):
        with self.assertRaises(BadRequest) as caught:
            self._assign(self.akokoro_cluster)

        self.assertIn("sub-county", str(caught.exception))

    def test_a_school_with_no_sub_county_is_not_blocked_by_the_sub_county_rule(self):
        School.objects.filter(id=self.school.id).update(sub_county=None)
        self.school.refresh_from_db()

        self._assign(self.akokoro_cluster)

        self.school.refresh_from_db()
        self.assertEqual(self.school.cluster_id, self.akokoro_cluster.id)


class ADistrictLevelClusterIsNotAnotherSubCountyTest(EligibilityFixture):
    """A cluster with no sub-county has not claimed one, so it is offered to a
    school that has one. Excluding it would make every district-level cluster
    unusable by exactly the schools whose geography is most complete."""

    def setUp(self):
        super().setUp()
        self.district_level = Cluster.objects.create(
            name="Apac District Cluster",
            region=self.region,
            district=self.apac,
            cluster_type="mixed",
            status=ClusterRecordStatus.ACTIVE,
            responsible_staff_id=self.james.user_id,
        )

    def test_it_is_offered_to_a_school_with_a_sub_county(self):
        self.assertIn("Apac District Cluster", self._names())

    def test_the_setter_accepts_it(self):
        from apps.clusters.services import set_school_cluster_membership

        set_school_cluster_membership(self.school, self.district_level, "tester")

        self.school.refresh_from_db()
        self.assertEqual(self.school.cluster_id, self.district_level.id)

    def test_a_cluster_naming_a_different_sub_county_is_still_excluded(self):
        """The relaxation is only for clusters that name none."""
        self.assertNotIn("Akokoro Cluster", self._names())
