"""The Distribution by Sub-Region table's columns (owner, 2026-09-15).

"Sub-Region, School, Cluster, # Visit Planned, School Visit achieved
(Achieved/Planned), # Cluster Meeting Planned, Cluster Meetings Achieved
(Achieved/Planned), # Cluster Trainings Planned, Cluster trainings achieved
(Achieved/Planned), # Assigned to Partner."

The figures come from one definition (apps.analytics.plan_progress) at every
level the table can show -- sub-region, district and sub-county -- so the
three cannot disagree about what "planned" means.
"""

from __future__ import annotations

from datetime import date

from django.test import SimpleTestCase, TestCase

from apps.activities.models import Activity
from apps.analytics.district_insight import district_insight
from apps.analytics.plan_progress import PLAN_PROGRESS_FIELDS, empty_progress
from apps.analytics.subcounty_insight import subcounty_insight
from apps.analytics.subregion_analytics import (
    combine_district_rows,
    subregion_performance,
)
from apps.clusters.models import Cluster
from apps.frontend.test_design_system_quality import _read
from apps.geography.models import District, Region, SubCounty, SubRegion
from apps.schools.models import School

EXPECTED = {
    # School A: one visit delivered, one still scheduled. School B: a visit
    # handed to a partner (planned, not achieved) and a cancelled one
    # (nobody's plan). Three planned, one achieved.
    "visits_planned": 3,
    "visits_achieved": 1,
    # The cluster: one meeting closed and one planned; one training verified
    # and one scheduled.
    "cluster_meetings_planned": 2,
    "cluster_meetings_achieved": 1,
    "cluster_trainings_planned": 2,
    "cluster_trainings_achieved": 1,
    # The partner visit alone.
    "assigned_to_partner": 1,
}


class SubRegionColumnsServiceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Col Region")
        cls.sub = SubRegion.objects.create(name="Col Sub", region=cls.region)
        cls.district = District.objects.create(
            name="Col District", region=cls.region, sub_region=cls.sub
        )
        cls.sub_county = SubCounty.objects.create(
            name="Col Sub-County", district=cls.district, pcode="COL-SC-1"
        )
        cls.cluster = Cluster.objects.create(
            name="Col Cluster",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            status="active",
        )
        cls.a = School.objects.create(
            school_id="COL-1",
            name="Col A",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            cluster_id=cls.cluster.id,
            enrollment=320,
        )
        cls.b = School.objects.create(
            school_id="COL-2",
            name="Col B",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            cluster_id=cls.cluster.id,
            enrollment=180,
        )
        for school, kind, status, delivery in (
            (cls.a, "school_visit", "completed", "staff"),
            (cls.a, "school_visit", "scheduled", "staff"),
            (cls.b, "follow_up_visit", "assigned_to_partner", "partner"),
            (cls.b, "school_visit", "cancelled", "staff"),
            (cls.b, "school_visit", "not_planned", "staff"),
        ):
            Activity.objects.create(
                activity_type=kind,
                status=status,
                school=school,
                delivery_type=delivery,
                planned_date=date(2026, 3, 3),
                fy="2026",
            )
        for kind, status in (
            ("cluster_meeting", "closed"),
            ("cluster_meeting", "planned"),
            ("cluster_training", "ia_verified"),
            ("cluster_training", "scheduled"),
            ("cluster_training", "rejected"),
        ):
            Activity.objects.create(
                activity_type=kind,
                status=status,
                cluster=cls.cluster,
                planned_date=date(2026, 3, 4),
                fy="2026",
            )
        # Last year's work is not this year's plan.
        Activity.objects.create(
            activity_type="school_visit",
            status="completed",
            school=cls.a,
            planned_date=date(2025, 3, 3),
            fy="2025",
        )

    def _figures(self, row) -> dict:
        return {field: row[field] for field in PLAN_PROGRESS_FIELDS}

    def test_the_sub_region_row_carries_the_seven_figures(self):
        rows = {r["name"]: r for r in subregion_performance("2026")["subregions"]}
        row = rows["Col Sub"]
        self.assertEqual(row["schools"], 2)
        self.assertEqual(row["clusters"], 1)
        self.assertEqual(self._figures(row), EXPECTED)

    def test_the_district_row_reads_the_same_definition(self):
        districts = {
            d["district"]: d for d in subregion_performance("2026")["districts"]
        }
        self.assertEqual(self._figures(districts["Col District"]), EXPECTED)
        self.assertEqual(
            self._figures(district_insight("2026")["Col District"]), EXPECTED
        )

    def test_the_sub_county_row_reads_the_same_definition(self):
        entries = {e["subcounty"]: e for e in subcounty_insight("2026")["entries"]}
        self.assertEqual(self._figures(entries["Col Sub-County"]), EXPECTED)

    def test_a_year_with_nothing_planned_is_all_zero_not_absent(self):
        rows = {r["name"]: r for r in subregion_performance("2024")["subregions"]}
        self.assertEqual(self._figures(rows["Col Sub"]), empty_progress())
        self.assertEqual(
            self._figures(district_insight("2024")["Col District"]), empty_progress()
        )

    def test_combined_boundaries_add_the_figures(self):
        """A map boundary spanning several rows sums them, like the other
        counts, so the sub-county table under a district zoom agrees with
        the rows it was built from."""
        left = {**empty_progress(), "visits_planned": 2, "visits_achieved": 1}
        right = {**empty_progress(), "visits_planned": 3, "assigned_to_partner": 2}
        combined = combine_district_rows([left, right])
        self.assertEqual(combined["visits_planned"], 5)
        self.assertEqual(combined["visits_achieved"], 1)
        self.assertEqual(combined["assigned_to_partner"], 2)
        self.assertEqual(combine_district_rows([])["cluster_meetings_planned"], 0)


class SubRegionColumnsMarkupTest(SimpleTestCase):
    def test_the_columns_are_the_owners_list_in_order(self):
        html = _read("templates/partials/analytics/regional_performance.html")
        titles = (
            "# Visit Planned",
            "School Visit achieved (Achieved/Planned)",
            "# Cluster Meeting Planned",
            "Cluster Meetings Achieved (Achieved/Planned)",
            "# Cluster Trainings Planned",
            "Cluster trainings achieved (Achieved/Planned)",
            "# Assigned to Partner",
        )
        positions = [html.index(f'title="{title}"') for title in titles]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(html.index('title="Schools"'), positions[0])
        self.assertLess(html.index('title="Clusters"'), positions[0])
        for field in PLAN_PROGRESS_FIELDS:
            self.assertIn(f"row.{field}", html)
        for gone in ("SSA", ">Visited</th>", ">Trained</th>", ">Students</th>"):
            self.assertNotIn(gone, html)
        self.assertIn('colspan="10"', html)

    def test_the_planned_columns_give_way_on_a_phone(self):
        """The three "# planned" columns repeat the denominator of the ratio
        beside them, so they are the ones that hide below tablet width; the
        ratios and the partner count show everywhere. Visibility is the
        component's: the platform's no-stacked-pairs rule forces every table
        cell visible with !important and yields only to an inline
        display:none, which is what x-show writes."""
        html = _read("templates/partials/analytics/regional_performance.html")
        self.assertEqual(
            html.count('text-right sr-wide" x-show="wideColumns" x-cloak title='), 3
        )
        self.assertEqual(
            html.count(
                'sr-wide" x-show="wideColumns" x-cloak\n                    x-text='
            ),
            3,
        )
        # Three <col>s, three headers, three cells.
        self.assertEqual(html.count('x-show="wideColumns"'), 9)
        script = _read("templates/partials/analytics/_regional_performance_script.html")
        self.assertIn("window.matchMedia('(min-width: 48rem)')", script)
        css = _read("static/css/pages/analytics-dashboard.css")
        self.assertIn(
            ".analytics-geo-card .sr-distribution-panel { flex: 0 0 auto; width: 100%; }",
            css,
        )
        self.assertIn(".sr-distribution-col--achieved", css)
        self.assertIn(".sr-distribution-col--partner", css)
        self.assertNotIn(".sr-distribution-col--ssa", css)

    def test_every_level_of_the_table_carries_the_figures(self):
        """Sub-region rows, district rows and sub-county rows (both the
        pre-fetched metrics and the boundary rows built on a district zoom)
        all read the seven fields; the ratio is only formatted here."""
        script = _read("templates/partials/analytics/_regional_performance_script.html")
        for field in PLAN_PROGRESS_FIELDS:
            self.assertEqual(script.count(f"{field}:metric.{field} || 0"), 3, field)
            self.assertEqual(script.count(f"{field}:row.{field} || 0"), 1, field)
            self.assertIn(f"{field}:0", script)
        self.assertIn("achievedOfPlanned(achieved, planned){", script)
        self.assertNotIn("distributionCoverageText", script)
