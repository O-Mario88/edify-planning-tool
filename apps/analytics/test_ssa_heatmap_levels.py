"""The SSA heatmap answers the same question at four geographic levels.

It was district-only, in one card. A region tells you where to send a Program
Lead; a sub-county tells you which communities are actually underserved, which
is the level "dire need" becomes actionable at once schools are mapped to it.

Two properties matter more than the grouping itself, and both are about not
lying with an average:

**Coverage travels with the number.** Sub-county is unset on ~96% of schools
today and cluster on ~95%. A mean taken over the assigned few would read as a
national figure while describing a rounding error, so `unassigned` and
`total_schools` come back with every level and the card states them.

**Rows are clickable only where a drawer exists.** `CDAnalyticsService.drilldown`
has branches for region, district and cluster but none for sub-county, so
sub-county rows must not carry a click target. A control that opens nothing is
the defect this platform's audit specifically forbids.
"""

from __future__ import annotations

from django.test import TestCase

from apps.analytics.cd_analytics_service import CDAnalyticsService, resolve_cd_scope
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


class SsaHeatmapLevelsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="HM Region")
        cls.district = District.objects.create(name="HM District", region=cls.region)
        cls.sub = SubCounty.objects.create(name="HM Sub", district=cls.district)
        # Two schools with a sub-county, one without — so `unassigned` has
        # something real to count rather than being trivially zero.
        for i in range(2):
            School.objects.create(
                school_id=f"HM-{i}",
                name=f"HM School {i}",
                region=cls.region,
                district=cls.district,
                sub_county=cls.sub,
                school_type="client",
            )
        School.objects.create(
            school_id="HM-NOSUB",
            name="HM No Subcounty",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )

    def _heatmap(self, level):
        return CDAnalyticsService.ssa_heatmap(resolve_cd_scope("2026"), level)

    def test_every_level_is_reachable(self):
        for level in ("region", "district", "sub_county", "cluster"):
            with self.subTest(level=level):
                self.assertEqual(self._heatmap(level)["level"], level)

    def test_an_unknown_level_falls_back_to_district_rather_than_erroring(self):
        # The level arrives from a query string, so it is user input.
        self.assertEqual(self._heatmap("province")["level"], "district")

    def test_coverage_is_reported_per_level(self):
        sub = self._heatmap("sub_county")
        self.assertEqual(
            sub["unassigned"],
            1,
            "the school with no sub-county must be counted as unassigned, not "
            "silently dropped from the denominator",
        )
        self.assertEqual(sub["total_schools"], 3)

    def test_district_coverage_differs_from_sub_county_coverage(self):
        # Guards the guard: if `unassigned` were hardcoded or level-blind these
        # two would agree and the previous test would prove nothing.
        self.assertNotEqual(
            self._heatmap("district")["unassigned"],
            self._heatmap("sub_county")["unassigned"],
        )

    def test_sub_county_rows_are_not_drillable(self):
        """`drilldown` has no sub_county branch, so the rows must stay inert."""
        self.assertFalse(self._heatmap("sub_county")["drillable"])

    def test_the_levels_with_a_drawer_are_drillable(self):
        for level in ("region", "district", "cluster"):
            with self.subTest(level=level):
                self.assertTrue(self._heatmap(level)["drillable"])

    def test_each_level_carries_its_own_column_header(self):
        self.assertEqual(self._heatmap("sub_county")["level_label"], "Sub-County")
        self.assertEqual(self._heatmap("region")["level_label"], "Region")

    def test_the_intervention_columns_are_the_same_eight_everywhere(self):
        """The grid is the SSA framework; only the row grouping changes."""
        district = self._heatmap("district")
        for level in ("region", "sub_county", "cluster"):
            with self.subTest(level=level):
                self.assertEqual(self._heatmap(level)["codes"], district["codes"])
                self.assertEqual(len(district["codes"]), 8)

    def test_district_heatmap_still_works_for_existing_callers(self):
        # The CD body, export and drilldown all call the old name.
        legacy = CDAnalyticsService.district_heatmap(resolve_cd_scope("2026"))
        self.assertEqual(legacy["level"], "district")
        self.assertEqual(legacy["rows"], self._heatmap("district")["rows"])
