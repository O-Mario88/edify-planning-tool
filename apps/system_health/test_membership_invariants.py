"""§14: the membership invariants have to be countable, not just refusable.

Every write path refuses a school joining another owner's cluster, or one
outside its district or sub-county. That protects new rows and says nothing
about the ones already there — so System Health counts the violations, and the
count has to be exact.

The audit command that reports these caps its row list at 200 so a report stays
readable. A count that inherited that cap would report "200 problems" against a
population of 17,000 and read as nearly clean. These tests seed more violations
than any such cap and assert the real number comes back.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.clusters.models import Cluster, ClusterSubCounty
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School
from apps.system_health.services import _workflow_issues


class MembershipInvariantsAreCountedTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Invariant Region")
        self.district = District.objects.create(
            name="Invariant District", region=self.region
        )
        self.other_district = District.objects.create(
            name="Other Invariant District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Invariant SubCounty", district=self.district
        )
        self.other_sub_county = SubCounty.objects.create(
            name="Other Invariant SubCounty", district=self.district
        )

        self.owner = self._staff("owner@invariant.test")
        self.rival = self._staff("rival@invariant.test")

        self.cluster = Cluster.objects.create(
            name="Owner Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            cluster_type="mixed",
            status="active",
            responsible_staff_id=self.owner.id,
        )
        ClusterSubCounty.objects.create(
            cluster=self.cluster, sub_county=self.sub_county
        )

    def _staff(self, email):
        user = User.objects.create(
            email=email,
            name=email.split("@")[0],
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
            status="active",
        )
        return StaffProfile.objects.create(user=user, title="CCEO")

    def _school(self, ref, *, owner, district=None, sub_county=None, cluster=None):
        """Force the membership past `School.save()`.

        Two layers refuse these rows, and the fixture has to get past both. The
        service refuses them at the write, which is the rule under test — and
        `School.save()` re-derives membership from geography, so a school
        created with a mismatched sub-county comes back `unclustered` and the
        violation the test meant to seed never exists. A silent `None` there
        made the sub-county check look like it counted nothing.

        `.update()` writes the row the way history wrote it: directly, before
        the rule existed.
        """
        school = School.objects.create(
            school_id=ref,
            name=f"School {ref}",
            region=self.region,
            district=district or self.district,
            sub_county=sub_county if sub_county is not None else self.sub_county,
            school_type="client",
            account_owner_id=owner.id if owner else "",
        )
        target = (cluster or self.cluster).id
        School.objects.filter(pk=school.pk).update(
            cluster_id=target, cluster_status="clustered"
        )
        school.refresh_from_db()
        self.assertEqual(
            school.cluster_id, target, "the fixture failed to seed the membership"
        )
        return school

    def _metrics(self):
        return _workflow_issues()

    def test_a_clean_membership_reports_nothing(self):
        self._school("INV-CLEAN", owner=self.owner)

        metrics = self._metrics()

        self.assertEqual(metrics["membershipOwnerMismatch"], 0)

    def test_schools_in_another_owners_cluster_are_counted(self):
        for i in range(3):
            self._school(f"INV-OWNER-{i}", owner=self.rival)

        self.assertEqual(self._metrics()["membershipOwnerMismatch"], 3)

    def test_the_owner_check_understands_both_id_spaces(self):
        """`account_owner_id` and `responsible_staff_id` are plain CharFields
        that hold a StaffProfile id on some paths and a User id on others.
        Comparing one space against the other matches nothing, and every school
        in the country would read as a violation."""
        cluster = Cluster.objects.create(
            name="User Id Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            cluster_type="mixed",
            status="active",
            responsible_staff_id=self.owner.user_id,
        )
        ClusterSubCounty.objects.create(cluster=cluster, sub_county=self.sub_county)
        self._school("INV-SPACES", owner=self.owner, cluster=cluster)

        self.assertEqual(self._metrics()["membershipOwnerMismatch"], 0)

    def test_geography_is_not_an_invariant_any_more(self):
        """Owner, 2026-09-21: a school joins its owner's cluster in ANY
        district, so a membership sitting outside the cluster's geography is
        a deliberate arrangement, not drift.

        This used to be counted and reported as a System Health blocker. Left
        in, it would have put a permanent red row there for exactly the work
        the platform now invites. The metric is gone; the portfolio half of
        the check, which did not change, is asserted above.
        """
        self._school(
            "INV-DISTRICT",
            owner=self.owner,
            district=self.other_district,
            sub_county=None,
        )
        self._school(
            "INV-SUBCOUNTY", owner=self.owner, sub_county=self.other_sub_county
        )

        metrics = self._metrics()

        self.assertNotIn("membershipGeographyMismatch", metrics)
        # The owner rule still holds over the same rows.
        self.assertEqual(metrics["membershipOwnerMismatch"], 0)

    def test_the_count_is_not_capped_at_a_report_sized_page(self):
        """More violations than the audit command's 200-row display limit.

        A count that quietly stopped at the cap would look like a small,
        manageable problem no matter how large the real one was.
        """
        School.objects.bulk_create(
            [
                School(
                    school_id=f"INV-BULK-{i}",
                    name=f"School INV-BULK-{i}",
                    region=self.region,
                    district=self.district,
                    sub_county=self.sub_county,
                    school_type="client",
                    account_owner_id=self.rival.id,
                    cluster_id=self.cluster.id,
                    cluster_status="clustered",
                )
                for i in range(250)
            ]
        )
        # bulk_create skips save(), so these keep the membership as written —
        # which is what makes it the right tool here.

        self.assertEqual(self._metrics()["membershipOwnerMismatch"], 250)
