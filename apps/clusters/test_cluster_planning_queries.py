"""`cluster_planning` must cost the same whether there are 4 clusters or 40.

Every figure on a cluster planning row -- school counts, SSA coverage,
readiness splits, meeting and training counts, last/next meeting dates, and the
visited/trained school sets -- used to be its own query inside the per-cluster
loop. That is about a dozen round trips per row: 51 queries for the four
seeded clusters, and over six hundred for a fifty-cluster deployment.

A count assertion alone would not catch a regression here, because a reviewer
can always argue the number crept up for a good reason. What matters is the
*shape*: adding clusters must not add queries.
"""

from __future__ import annotations

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import StaffProfile, User
from apps.clusters.models import Cluster
from apps.clusters.services import cluster_planning
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


class ClusterPlanningQueryShapeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(
            id="cluster-perf-cd",
            email="cluster-perf-cd@edify.org",
            name="Cluster Perf CD",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )
        StaffProfile.objects.create(id="cluster-perf-staff", user=cls.user, title="CD")
        cls.region = Region.objects.create(name="Cluster Perf Region")
        cls.district = District.objects.create(
            name="Cluster Perf District", region=cls.region
        )
        # School.save() reconciles `cluster_id` against sub-county coverage:
        # a school whose sub-county the cluster does not cover has its
        # cluster cleared. The fixture therefore has to assign schools the
        # way production does, through a shared sub-county, or every row
        # comes back with zero schools.
        cls.sub_county = SubCounty.objects.create(
            name="Cluster Perf Sub-County", district=cls.district
        )

    def _make_clusters(self, count, prefix):
        for i in range(count):
            cluster = Cluster.objects.create(
                name=f"{prefix} Cluster {i}",
                region=self.region,
                district=self.district,
                sub_county=self.sub_county,
                status="active",
            )
            School.objects.create(
                school_id=f"SCH-{prefix}-{i}",
                name=f"{prefix} School {i}",
                region=self.region,
                district=self.district,
                sub_county=self.sub_county,
                cluster_id=cluster.id,
            )

    def _query_count(self):
        cluster_planning(self.user)  # warm any per-process caches
        with CaptureQueriesContext(connection) as queries:
            cluster_planning(self.user)
        return len(queries.captured_queries)

    def test_query_count_does_not_grow_with_the_number_of_clusters(self):
        self._make_clusters(3, "small")
        small = self._query_count()

        self._make_clusters(12, "large")
        large = self._query_count()

        self.assertEqual(
            small,
            large,
            f"{small} queries for 3 clusters but {large} for 15 -- a query "
            f"has moved back inside the per-cluster loop",
        )

    def test_the_page_section_stays_within_a_small_fixed_budget(self):
        self._make_clusters(5, "budget")
        self.assertLessEqual(
            self._query_count(),
            12,
            "cluster_planning should issue a handful of grouped reads",
        )

    def test_rows_are_still_produced_for_every_cluster(self):
        self._make_clusters(4, "rows")
        rows = cluster_planning(self.user)
        self.assertEqual(len(rows), 4)

    def test_school_and_coverage_figures_survive_the_grouping(self):
        """The grouped reads must reproduce the per-cluster numbers exactly."""
        cluster = Cluster.objects.create(
            name="Coverage Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            status="active",
        )
        for i in range(3):
            School.objects.create(
                school_id=f"SCH-COV-{i}",
                name=f"Coverage School {i}",
                region=self.region,
                district=self.district,
                sub_county=self.sub_county,
                cluster_id=cluster.id,
                current_fy_ssa_status="done" if i < 2 else "pending",
            )

        row = next(r for r in cluster_planning(self.user) if r["id"] == cluster.id)
        self.assertEqual(row["schoolsCount"], 3)
        self.assertEqual(row["schoolsWithSsa"], 2)
        self.assertEqual(row["schoolsWithoutSsa"], 1)
        self.assertEqual(row["ssaCoveragePct"], 66.7)

    def test_a_cluster_with_no_schools_reports_zero_not_an_error(self):
        cluster = Cluster.objects.create(
            name="Empty Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            status="active",
        )
        row = next(r for r in cluster_planning(self.user) if r["id"] == cluster.id)
        self.assertEqual(row["schoolsCount"], 0)
        self.assertEqual(row["ssaCoveragePct"], 0.0)
        self.assertIsNone(row["lastMeetingDate"])
