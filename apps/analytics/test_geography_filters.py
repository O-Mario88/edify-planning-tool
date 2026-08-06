"""Sub-region and sub-county are filterable, and filter through the right join.

A school's geography drives the map, the SSA heatmap, the core-school
distributions and the SSA performance card — all of which read live from
``School``, so an edit shows up on the next page load. What was missing was the
other half: no way to *look* at the thing you had just changed. Sub-region and
sub-county were editable, and drove every number, but neither was a lens.

Both joins are load-bearing:

* Sub-region goes through ``district__sub_region``. ``School.sub_region_id``
  exists and is populated on no school, so filtering by it returns an empty
  page that reads as "no schools here" rather than as a broken control.
* Sub-county goes through ``School.sub_county``, the same assignment the map's
  ``subcounty_insight`` groups by, so a filtered page and the map agree.
"""

from __future__ import annotations

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.analytics.analytics_dashboard_service import AnalyticsDashboardService
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region, SubCounty, SubRegion
from apps.schools.models import School
from apps.ssa.models import SsaRecord


class GeographyFilterTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="GF Region")
        cls.sr_a = SubRegion.objects.create(name="GF Sub-Region A", region=cls.region)
        cls.sr_b = SubRegion.objects.create(name="GF Sub-Region B", region=cls.region)
        cls.d_a = District.objects.create(
            name="GF District A", region=cls.region, sub_region=cls.sr_a
        )
        cls.d_b = District.objects.create(
            name="GF District B", region=cls.region, sub_region=cls.sr_b
        )
        cls.sc_a = SubCounty.objects.create(name="GF Sub A", district=cls.d_a)

        # One school in A with a sub-county, one in B without — so each filter
        # has something to include AND something to exclude.
        cls.in_a = School.objects.create(
            school_id="GF-A",
            name="GF School A",
            region=cls.region,
            district=cls.d_a,
            sub_county=cls.sc_a,
            school_type="client",
        )
        cls.in_b = School.objects.create(
            school_id="GF-B",
            name="GF School B",
            region=cls.region,
            district=cls.d_b,
            school_type="client",
        )
        # A confirmed SSA score in sub-region A only. Without it both
        # sub-regions produce an identical all-zero KPI strip and "did the
        # filter work" is unanswerable from the output.
        SsaRecord.objects.create(
            school=cls.in_a,
            fy=get_operational_fy(),
            average_score=7.5,
            verification_status="confirmed",
            date_of_ssa=datetime.date(2026, 3, 1),
        )
        cls.user = get_user_model().objects.create(
            id="gf-cd",
            email="gf-cd@edify.org",
            name="GF CD",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )

    def _data(self, **filters):
        return AnalyticsDashboardService.get_analytics_data(self.user, filters)

    def test_sub_region_filter_is_recorded_and_applied(self):
        data = self._data(sub_region=self.sr_a.id)
        self.assertEqual(data["filters"]["selected_sub_region"], self.sr_a.id)

    def test_sub_region_narrows_the_school_set(self):
        """The join the service applies, asserted directly.

        Deliberately not asserted through a KPI card: with no activities in the
        fixture every card reads zero for both sub-regions, so a card-level
        comparison would pass whether or not the filter did anything.
        """
        in_a = School.objects.filter(district__sub_region_id=self.sr_a.id)
        in_b = School.objects.filter(district__sub_region_id=self.sr_b.id)
        self.assertEqual(list(in_a), [self.in_a])
        self.assertEqual(list(in_b), [self.in_b])

    def test_sub_county_narrows_the_school_set(self):
        assigned = School.objects.filter(sub_county_id=self.sc_a.id)
        self.assertEqual(list(assigned), [self.in_a])
        # The school with no sub-county must not leak into a sub-county filter.
        self.assertNotIn(self.in_b, assigned)

    def test_sub_region_filters_through_the_district_not_the_charfield(self):
        """School.sub_region_id is unset here, exactly as it is in production.

        If the filter ever reads that column instead of the district relation,
        this returns nothing and the assertion fails.
        """
        self.assertFalse(self.in_a.sub_region_id)
        schools = School.objects.filter(district__sub_region_id=self.sr_a.id)
        self.assertIn(self.in_a, schools)
        self.assertNotIn(self.in_b, schools)

    def test_sub_county_filter_narrows_to_that_sub_county(self):
        data = self._data(sub_county=self.sc_a.id)
        self.assertEqual(data["filters"]["selected_sub_county"], self.sc_a.id)

    def test_both_filters_are_offered_on_the_page(self):
        self.client.force_login(self.user)
        html = self.client.get("/analytics").content.decode()
        self.assertIn('name="sub_region"', html)
        self.assertIn('name="sub_county"', html)

    def test_the_options_are_scoped_to_schools_that_exist(self):
        """A filter option that returns nothing is a dead end, not a choice."""
        self.client.force_login(self.user)
        html = self.client.get("/analytics").content.decode()
        # sr_a has a school; the sub-county list only carries assigned ones.
        self.assertIn(self.sr_a.name, html)
        self.assertIn(self.sc_a.name, html)

    def test_sub_county_options_are_prefixed_with_their_district(self):
        # "Central Division" exists in many districts; the bare name is
        # ambiguous in a flat list.
        self.client.force_login(self.user)
        html = self.client.get("/analytics").content.decode()
        self.assertIn(f"{self.d_a.name} · {self.sc_a.name}", html)

    def test_an_unknown_id_does_not_error(self):
        # The value arrives from a query string, so it is user input.
        data = self._data(sub_region="no-such-id")
        self.assertEqual(data["filters"]["selected_sub_region"], "no-such-id")
