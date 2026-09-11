"""The sub-region table's three wide columns (owner, 2026-09-12).

"On tablet mode and desktop screens larger than 12 inches, add more columns
on the distribution table since it is below the map and occupying the whole
row: # Schools Trained, # Schools Visited, Students impacted (the total
enrollment of all the schools in each sub-region). On 11-to-12-inch desktop
screens keep the current table. On mobile keep the current table."
"""

from __future__ import annotations

from datetime import date

from django.test import SimpleTestCase, TestCase

from apps.activities.models import Activity
from apps.analytics.district_insight import district_insight
from apps.analytics.subregion_analytics import subregion_performance
from apps.frontend.test_design_system_quality import _read
from apps.geography.models import District, Region, SubRegion
from apps.schools.models import School


class SubRegionColumnsServiceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Col Region")
        cls.sub = SubRegion.objects.create(name="Col Sub", region=cls.region)
        cls.district = District.objects.create(name="Col District", region=cls.region, sub_region=cls.sub)
        cls.a = School.objects.create(school_id="COL-1", name="Col A", region=cls.region, district=cls.district, enrollment=320)
        cls.b = School.objects.create(school_id="COL-2", name="Col B", region=cls.region, district=cls.district, enrollment=180)
        cls.c = School.objects.create(school_id="COL-3", name="Col C", region=cls.region, district=cls.district, enrollment=None)
        for school, kind, status in (
            (cls.a, "school_visit", "completed"),
            (cls.a, "school_visit", "completed"),   # a second visit: still one school
            (cls.b, "school_visit", "scheduled"),   # not delivered: not visited
            (cls.b, "in_school_training", "completed"),
        ):
            Activity.objects.create(
                activity_type=kind, status=status, school=school,
                planned_date=date(2026, 3, 3), fy="2026",
            )

    def test_the_sub_region_row_carries_the_three_figures(self):
        rows = {r["name"]: r for r in subregion_performance("2026")["subregions"]}
        row = rows["Col Sub"]
        self.assertEqual(row["schools"], 3)
        self.assertEqual(row["enrollment"], 500)
        self.assertEqual(row["schools_visited"], 1)
        self.assertEqual(row["schools_trained"], 1)

    def test_the_district_hover_carries_enrolment_too(self):
        metric = district_insight("2026")["Col District"]
        self.assertEqual((metric["visited"], metric["trained"], metric["enrollment"]), (1, 1, 500))


class SubRegionColumnsMarkupTest(SimpleTestCase):
    def test_the_columns_exist_and_show_only_where_there_is_room(self):
        html = _read("templates/partials/analytics/regional_performance.html")
        for label in ("Visited", "Trained", "Students"):
            self.assertIn(f'text-right sr-wide" title=', html)
            self.assertIn(f">{label}</th>", html)
        self.assertEqual(html.count('sr-wide"\n                    x-text='), 3)
        script = _read("templates/partials/analytics/_regional_performance_script.html")
        self.assertIn("students:row.enrollment || 0", script)
        self.assertIn("visited:metric.visited || 0", script)
        # Visibility is the component's: the platform's no-stacked-pairs rule
        # forces every table cell visible with !important and yields only to
        # an inline display:none, which is what x-show writes.
        self.assertEqual(html.count('x-show="wideColumns"'), 6)
        self.assertIn("'(min-width: 48rem) and (max-width: 63.999rem), (min-width: 100rem)'", script)
        css = _read("static/css/pages/analytics-dashboard.css")
        self.assertIn("@media (min-width: 100rem) {\n  .analytics-geo-card .sr-distribution-panel { flex: 0 0 32rem; width: 32rem; }", css)
