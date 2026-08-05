"""The SSA heatmap answers the same question at four geographic levels.

It was district-only, in one card. A sub-region tells you where to send a
Program Lead; a sub-county tells you which communities are actually underserved,
which is the level "dire need" becomes actionable at once schools are mapped to
it.

The top level is SUB-region, not region. Uganda has four regions, so a region
heatmap is four rows and the eight-intervention grid averages away the very
differences it exists to show. There are ten sub-regions.

It groups through `district__sub_region`, not `School.sub_region_id`. That
column exists and is populated on no school at all, so grouping by it would put
every school in `unassigned` and render an empty card — a wiring failure that
looks exactly like a data failure. The district route reaches 99%.

Two properties matter more than the grouping itself, and both are about not
lying with an average:

**Coverage travels with the number.** Sub-county is unset on ~96% of schools
today and cluster on ~95%. A mean taken over the assigned few would read as a
national figure while describing a rounding error, so `unassigned` and
`total_schools` come back with every level and the card states them.

**Rows are clickable only where a drawer exists.** `CDAnalyticsService.drilldown`
has branches for sub_region, district and cluster but none for sub-county, so
sub-county rows must not carry a click target. A control that opens nothing is
the defect this platform's audit specifically forbids.
"""

from __future__ import annotations

from django.test import TestCase

from apps.analytics.cd_analytics_service import CDAnalyticsService, resolve_cd_scope
from apps.geography.models import District, Region, SubCounty, SubRegion
from apps.schools.models import School


class SsaHeatmapLevelsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="HM Region")
        cls.sub_region = SubRegion.objects.create(
            name="HM Sub-Region", region=cls.region
        )
        # The sub-region reaches schools through the district, so the district
        # must carry it — School.sub_region_id is not the route.
        cls.district = District.objects.create(
            name="HM District", region=cls.region, sub_region=cls.sub_region
        )
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
        for level in ("sub_region", "district", "sub_county", "cluster"):
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
        for level in ("sub_region", "district", "cluster"):
            with self.subTest(level=level):
                self.assertTrue(self._heatmap(level)["drillable"])

    def test_each_level_carries_its_own_column_header(self):
        self.assertEqual(self._heatmap("sub_county")["level_label"], "Sub-County")
        self.assertEqual(self._heatmap("sub_region")["level_label"], "Sub-Region")

    def test_the_intervention_columns_are_the_same_eight_everywhere(self):
        """The grid is the SSA framework; only the row grouping changes."""
        district = self._heatmap("district")
        for level in ("sub_region", "sub_county", "cluster"):
            with self.subTest(level=level):
                self.assertEqual(self._heatmap(level)["codes"], district["codes"])
                self.assertEqual(len(district["codes"]), 8)

    def test_district_heatmap_still_works_for_existing_callers(self):
        # The CD body, export and drilldown all call the old name.
        legacy = CDAnalyticsService.district_heatmap(resolve_cd_scope("2026"))
        self.assertEqual(legacy["level"], "district")
        self.assertEqual(legacy["rows"], self._heatmap("district")["rows"])


class SsaHeatmapEndpointTest(TestCase):
    """The tab endpoint is reachable with no query string at all.

    It shipped 500ing on a bare GET: `resolve_cd_scope` is called directly here
    rather than through `get_dashboard`, which is what normally defaults the
    fiscal year, and a None fy reaches a queryset as `fy=None` —
    "Cannot use None as a query value". The route crawl caught it, which is the
    right outcome but the slow one; this pins it at the unit level.
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model

        cls.cd = get_user_model().objects.create(
            id="hm-cd",
            email="hm-cd@edify.org",
            name="HM CD",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )

    def setUp(self):
        self.client.force_login(self.cd)

    def test_a_bare_get_does_not_error(self):
        self.assertEqual(
            self.client.get("/analytics/country-director/ssa-heatmap").status_code,
            200,
        )

    def test_every_level_renders_over_http(self):
        for level in ("sub_region", "district", "sub_county", "cluster"):
            with self.subTest(level=level):
                response = self.client.get(
                    f"/analytics/country-director/ssa-heatmap?level={level}"
                )
                self.assertEqual(response.status_code, 200)

    def test_a_junk_level_from_the_query_string_is_survivable(self):
        response = self.client.get(
            "/analytics/country-director/ssa-heatmap?level=../../etc/passwd"
        )
        self.assertEqual(response.status_code, 200)


class SsaHeatmapSubRegionRouteTest(TestCase):
    """The sub-region level must group through the district, not the CharField.

    School.sub_region_id exists and is empty on every school in production
    (0 of 16,974). Grouping by it produces a card where `unassigned` equals
    `total_schools` and no rows render — indistinguishable, from the outside,
    from "no SSA data yet". These pin the route rather than the symptom.
    """

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="SR Region")
        cls.sub_region = SubRegion.objects.create(name="SR Sub", region=cls.region)
        cls.district = District.objects.create(
            name="SR District", region=cls.region, sub_region=cls.sub_region
        )
        # Deliberately leaves School.sub_region_id unset, exactly as production
        # has it, so a regression to that column shows up here.
        School.objects.create(
            school_id="SR-1",
            name="SR School",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )

    def test_a_school_with_no_sub_region_column_still_counts(self):
        heatmap = CDAnalyticsService.ssa_heatmap(resolve_cd_scope("2026"), "sub_region")
        self.assertEqual(
            heatmap["unassigned"],
            0,
            "the school reaches its sub-region through the district, so it must "
            "not be counted unassigned — if this is 1, the grouping has "
            "regressed to School.sub_region_id, which is empty in production",
        )
        self.assertEqual(heatmap["total_schools"], 1)

    def test_the_grouping_field_walks_the_district_relation(self):
        group_field, name_field, _label = CDAnalyticsService.HEATMAP_LEVELS[
            "sub_region"
        ]
        self.assertEqual(group_field, "district__sub_region_id")
        self.assertEqual(name_field, "district__sub_region__name")

    def test_region_stays_available_for_the_regional_summary_card(self):
        # partials/analytics/cd/regional_summary.html still drills to region;
        # replacing the heatmap level must not remove that branch.
        self.assertNotIn("region", CDAnalyticsService.HEATMAP_LEVELS)
        self.assertTrue(hasattr(CDAnalyticsService, "_drill_region"))
        self.assertTrue(hasattr(CDAnalyticsService, "_drill_sub_region"))


class SsaHeatmapTabsTest(TestCase):
    """Every level in HEATMAP_LEVELS must appear as a tab.

    The tab list used to be a second hardcoded order filtered by
    `if key in levels`, so a level in one and not the other disappeared without
    a word: renaming `region` to `sub_region` left `region` in the order (gone,
    no longer a level) and `sub_region` out of it (gone, not in the order). The
    level still answered when requested by URL, so every service-level test
    passed while the heatmap quietly lost a tab.
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model

        cls.cd = get_user_model().objects.create(
            id="tab-cd",
            email="tab-cd@edify.org",
            name="Tab CD",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )

    def test_the_tab_list_is_exactly_the_level_list(self):
        from apps.frontend.views.analytics_views import _heatmap_level_choices

        self.assertEqual(
            [key for key, _label in _heatmap_level_choices()],
            list(CDAnalyticsService.HEATMAP_LEVELS),
            "the tabs and the levels have drifted — every level must be "
            "reachable, and a tab must not point at a level that is gone",
        )

    def test_sub_region_is_offered_as_a_tab(self):
        from apps.frontend.views.analytics_views import _heatmap_level_choices

        self.assertIn(("sub_region", "Sub-Region"), _heatmap_level_choices())

    def test_every_level_renders_a_tab_for_every_other_level(self):
        """Whichever level you are on, you can still reach the others."""
        self.client.force_login(self.cd)
        for level in CDAnalyticsService.HEATMAP_LEVELS:
            with self.subTest(level=level):
                html = self.client.get(
                    f"/analytics/country-director/ssa-heatmap?level={level}"
                ).content.decode()
                for other in CDAnalyticsService.HEATMAP_LEVELS:
                    self.assertIn(f"level={other}", html)
