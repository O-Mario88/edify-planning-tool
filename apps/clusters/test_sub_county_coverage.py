"""A cluster that names no sub-county cannot claim a school, and says so.

`active_cluster_for_geography` matches on district AND sub-county. A cluster
carrying only a district therefore resolves to nothing everywhere — the
Add-to-Cluster drawer, the School Profile, and School.save() — and all three
fail identically to "no cluster covers this area", which is a different
problem with a different fix.
"""

from __future__ import annotations

from django.core.management import call_command
from django.test import TestCase
from io import StringIO

from apps.clusters.eligibility import (
    active_cluster_for_school_geography,
    declare_sub_county_coverage,
)
from apps.clusters.services import set_school_cluster_membership
from apps.clusters.models import Cluster, ClusterSubCounty
from apps.geography.models import District, Parish, Region, SubCounty
from apps.schools.models import School


class CoverageFixture(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(
            name="Dist", region=self.region, district_type="primary"
        )
        self.sub_county = SubCounty.objects.create(name="Kira", district=self.district)
        self.cluster = Cluster.objects.create(
            name="Cluster A",
            district=self.district,
            region=self.region,
            status="active",
        )

    def _school(self, sid, *, sub_county=None, cluster_id=None):
        school = School.objects.create(
            school_id=f"S-{sid}",
            name=f"School {sid}",
            region=self.region,
            district=self.district,
            sub_county=sub_county,
            enrollment=100,
        )
        if cluster_id:
            # Written past save(), on purpose. A new school has no membership
            # for save() to preserve — the row is created first and pointed at
            # a cluster afterwards — so its geography lookup runs against an
            # uncovered sub-county and lands on none. That is exactly the
            # legacy state the backfill exists to repair, and going through
            # save() could never build it.
            School.objects.filter(pk=school.pk).update(
                cluster_id=cluster_id, cluster_status="clustered"
            )
            school.refresh_from_db()
        return school


class ResolutionTests(CoverageFixture):
    def test_a_cluster_with_no_sub_county_claims_nothing(self):
        school = self._school("A", sub_county=self.sub_county)

        self.assertIsNone(active_cluster_for_school_geography(school))

    def test_declaring_the_sub_county_makes_the_cluster_findable(self):
        ClusterSubCounty.objects.create(
            cluster=self.cluster, sub_county=self.sub_county
        )
        school = self._school("B", sub_county=self.sub_county)

        found = active_cluster_for_school_geography(school)

        self.assertEqual(found.id, self.cluster.id)

    def test_a_school_with_no_sub_county_resolves_to_nothing(self):
        ClusterSubCounty.objects.create(
            cluster=self.cluster, sub_county=self.sub_county
        )
        school = self._school("C")

        # Absence of geography is not evidence of absence of a cluster; the
        # lookup simply cannot run.
        self.assertIsNone(active_cluster_for_school_geography(school))


class BackfillTests(CoverageFixture):
    def _run(self, *args):
        out = StringIO()
        call_command("backfill_cluster_sub_counties", *args, stdout=out)
        return out.getvalue()

    def test_it_reads_coverage_off_the_schools_already_in_the_cluster(self):
        self._school("D", sub_county=self.sub_county, cluster_id=self.cluster.id)

        self._run("--commit")

        self.assertTrue(
            ClusterSubCounty.objects.filter(
                cluster=self.cluster, sub_county=self.sub_county
            ).exists()
        )

    def test_it_writes_nothing_without_commit(self):
        self._school("E", sub_county=self.sub_county, cluster_id=self.cluster.id)

        output = self._run()

        self.assertFalse(ClusterSubCounty.objects.exists())
        self.assertIn("Nothing written", output)

    def test_a_school_whose_sub_county_is_in_another_district_is_not_adopted(self):
        # That school has a geography error of its own; spreading it into the
        # cluster's declared coverage would make the error permanent.
        other = District.objects.create(
            name="Elsewhere", region=self.region, district_type="primary"
        )
        stray = SubCounty.objects.create(name="Stray", district=other)
        self._school("F", sub_county=stray, cluster_id=self.cluster.id)

        self._run("--commit")

        self.assertFalse(ClusterSubCounty.objects.exists())

    def test_a_cluster_with_nothing_to_read_from_says_so(self):
        output = self._run()

        self.assertIn("no member school", output)


class HealthCheckTests(CoverageFixture):
    def test_an_uncovered_cluster_is_reported_as_critical(self):
        from apps.system_health.data_quality_health import data_quality_health

        keys = {
            check["key"]: check for check in data_quality_health().get("checks", [])
        }

        self.assertIn("cluster_without_sub_county_coverage", keys)
        self.assertEqual(
            keys["cluster_without_sub_county_coverage"]["severity"], "critical"
        )

    def test_the_check_clears_once_coverage_is_declared(self):
        from apps.system_health.data_quality_health import data_quality_health

        ClusterSubCounty.objects.create(
            cluster=self.cluster, sub_county=self.sub_county
        )

        keys = {check["key"] for check in data_quality_health().get("checks", [])}

        self.assertNotIn("cluster_without_sub_county_coverage", keys)


class CoverageLearnedFromAssignmentTests(CoverageFixture):
    """A cluster learns its ground from the schools put into it.

    Coverage could previously only be typed in when the cluster was created, and
    `backfill_cluster_sub_counties` derives it from member schools — so a
    cluster created with only a district had no way to acquire any: the members
    the backfill reads are the ones the missing coverage prevents. Every cluster
    in the live deployment sits in that loop, which is why no school has ever
    seen "Cluster selected automatically".
    """

    def test_assigning_a_school_declares_its_sub_county(self):
        school = self._school("A", sub_county=self.sub_county)

        set_school_cluster_membership(school, self.cluster, "tester")

        self.assertTrue(
            ClusterSubCounty.objects.filter(
                cluster=self.cluster, sub_county=self.sub_county
            ).exists()
        )

    def test_the_next_school_in_that_sub_county_resolves_automatically(self):
        first = self._school("A", sub_county=self.sub_county)
        second = self._school("B", sub_county=self.sub_county)
        self.assertIsNone(active_cluster_for_school_geography(second))

        set_school_cluster_membership(first, self.cluster, "tester")

        self.assertEqual(
            active_cluster_for_school_geography(second).id, self.cluster.id
        )

    def test_coverage_is_refused_when_another_cluster_already_claims_it(self):
        rival = Cluster.objects.create(
            name="Cluster B",
            district=self.district,
            region=self.region,
            sub_county=self.sub_county,
            status="active",
        )
        ClusterSubCounty.objects.create(cluster=rival, sub_county=self.sub_county)
        school = self._school("A", sub_county=self.sub_county)

        set_school_cluster_membership(school, self.cluster, "tester")

        # One active cluster per sub-county is the rule `create_cluster`
        # enforces; coverage acquired sideways must not evade it.
        self.assertFalse(
            ClusterSubCounty.objects.filter(
                cluster=self.cluster, sub_county=self.sub_county
            ).exists()
        )

    def test_a_sub_county_in_another_district_is_never_adopted(self):
        elsewhere = District.objects.create(
            name="Other", region=self.region, district_type="primary"
        )
        foreign = SubCounty.objects.create(name="Foreign", district=elsewhere)

        self.assertFalse(declare_sub_county_coverage(self.cluster, foreign.id))


class SubCountyEditKeepsMembershipTests(CoverageFixture):
    """Filling in the sub-county must not be what removes the school.

    `School.save()` re-derived membership whenever the sub-county changed and
    unclustered the school when the lookup found nothing — including when
    nothing *could* be found, because no cluster declared any coverage. The edit
    intended to make clustering work was therefore the edit that undid it, and
    silently: the cluster page went on listing the school.
    """

    def test_setting_a_sub_county_keeps_a_hand_made_membership(self):
        school = self._school("A", cluster_id=self.cluster.id)

        school.sub_county = self.sub_county
        school.save()
        school.refresh_from_db()

        self.assertEqual(school.cluster_id, self.cluster.id)
        self.assertEqual(school.cluster_status, "clustered")

    def test_and_the_cluster_adopts_the_sub_county_it_kept(self):
        school = self._school("A", cluster_id=self.cluster.id)

        school.sub_county = self.sub_county
        school.save()

        self.assertTrue(
            ClusterSubCounty.objects.filter(
                cluster=self.cluster, sub_county=self.sub_county
            ).exists()
        )

    def test_a_cluster_that_really_covers_the_new_sub_county_still_wins(self):
        # An explicit membership yields to a better answer — just never to the
        # absence of one.
        covering = Cluster.objects.create(
            name="Cluster B",
            district=self.district,
            region=self.region,
            status="active",
        )
        ClusterSubCounty.objects.create(cluster=covering, sub_county=self.sub_county)
        school = self._school("A", cluster_id=self.cluster.id)

        school.sub_county = self.sub_county
        school.save()
        school.refresh_from_db()

        self.assertEqual(school.cluster_id, covering.id)

    def test_a_membership_the_lookup_produced_still_lapses_with_the_geography(self):
        # The mirror of the rule above, and the reason it is narrow. This
        # cluster claims the old sub-county, so the lookup itself could have
        # produced the membership; the claim was geographic and moving the
        # school out of that ground ends it. Only a membership no lookup could
        # have made is treated as a person's decision.
        ClusterSubCounty.objects.create(
            cluster=self.cluster, sub_county=self.sub_county
        )
        school = self._school("A", sub_county=self.sub_county)
        school.refresh_from_db()
        self.assertEqual(school.cluster_id, self.cluster.id)

        elsewhere = SubCounty.objects.create(name="Nansana", district=self.district)
        school.sub_county = elsewhere
        school.save()
        school.refresh_from_db()

        self.assertIsNone(school.cluster_id)
        self.assertEqual(school.cluster_status, "unclustered")
