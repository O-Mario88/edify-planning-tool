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

from apps.clusters.eligibility import active_cluster_for_school_geography
from apps.clusters.models import Cluster, ClusterSubCounty
from apps.geography.models import District, Parish, Region, SubCounty
from apps.schools.models import School


class CoverageFixture(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(
            name="Dist", region=self.region, district_type="primary"
        )
        self.sub_county = SubCounty.objects.create(
            name="Kira", district=self.district
        )
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
            # Written past save(), on purpose. save() drops a membership whose
            # cluster declares no coverage of the school's sub-county — which
            # is exactly the state the backfill exists to repair, and exactly
            # the state that predates that rule in the live database. Creating
            # it through save() would have save() undo it, so the fixture
            # could never build the legacy row the command reads.
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
