"""This year's SSA scores beside last year's (owner, 2026-10-09: "we shall be
comparing previous FY SSA scores with the current SSA Scores to measure
improvement").

`apps.ssa.year_comparison.intervention_comparison` is the one definition the
school, cluster, district and staff profiles and the Admin dashboard draw.
"""

from __future__ import annotations

from datetime import datetime, timezone as dt_tz

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore
from apps.ssa.year_comparison import fy_label, intervention_comparison

ALL = [value for value, _label in SsaIntervention.choices]


class YearComparisonTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Years Region")
        district = District.objects.create(name="Years District", region=region)
        cls.schools = [
            School.objects.create(
                school_id=f"YEARS-{n}",
                name=f"Years School {n}",
                region=region,
                district=district,
            )
            for n in range(3)
        ]
        cls.this_fy = str(get_operational_fy())
        cls.last_fy = str(int(cls.this_fy) - 1)
        cls.before_fy = str(int(cls.this_fy) - 2)

    def record(self, school, fy, score, *, status="confirmed", day=1, scores=None):
        record = SsaRecord.objects.create(
            school=school,
            fy=fy,
            date_of_ssa=datetime(int(fy) - 1, 11, day, tzinfo=dt_tz.utc),
            average_score=score,
            verification_status=status,
        )
        for intervention in ALL:
            SsaScore.objects.create(
                ssa_record=record,
                intervention=intervention,
                score=(scores or {}).get(intervention, score),
            )
        return record

    def ids(self):
        return [school.id for school in self.schools]

    def test_each_intervention_has_this_year_and_last_year(self):
        first, second, _third = self.schools
        self.record(first, self.last_fy, 4.0)
        self.record(second, self.last_fy, 6.0)
        self.record(first, self.this_fy, 7.0, scores={"leadership": 9.0})

        result = intervention_comparison(self.ids(), self.this_fy)

        self.assertEqual(
            (result["label"], result["previous_label"]),
            (fy_label(self.this_fy), fy_label(self.last_fy)),
        )
        self.assertEqual(len(result["rows"]), len(ALL))
        leadership = next(r for r in result["rows"] if r["key"] == "leadership")
        self.assertEqual((leadership["previous"], leadership["current"]), (5.0, 9.0))
        other = next(r for r in result["rows"] if r["key"] != "leadership")
        self.assertEqual((other["previous"], other["current"]), (5.0, 7.0))
        self.assertEqual((result["previous"], result["current"]), (5.0, 7.0))
        self.assertEqual((result["previous_schools"], result["schools"]), (2, 1))

    def test_a_school_counts_its_latest_confirmed_record_of_the_year(self):
        school = self.schools[0]
        self.record(school, self.this_fy, 3.0, day=1)
        self.record(school, self.this_fy, 8.0, day=20)
        # Newer still, and not confirmed: it is not the year's score yet.
        self.record(school, self.this_fy, 1.0, day=25, status="pending")

        result = intervention_comparison([school.id], self.this_fy)

        self.assertEqual(result["current"], 8.0)
        self.assertEqual({row["current"] for row in result["rows"]}, {8.0})

    def test_a_year_with_nothing_confirmed_is_not_measured_never_zero(self):
        self.record(self.schools[0], self.this_fy, 6.5)

        result = intervention_comparison(self.ids(), self.this_fy)

        self.assertTrue(result["has_current"])
        self.assertFalse(result["has_previous"])
        self.assertIsNone(result["previous"])
        self.assertEqual({row["previous"] for row in result["rows"]}, {None})

    def test_with_no_year_named_it_is_the_latest_year_with_a_record(self):
        """The weeks after 1 October have no confirmed record of the new year:
        the chart compares the last measured year with the one before, as
        the Programme Lead's and Country Director's analytics do."""
        self.record(self.schools[0], self.before_fy, 4.0)
        self.record(self.schools[0], self.last_fy, 5.5)

        result = intervention_comparison(self.ids())

        self.assertEqual(
            (result["fy"], result["previous_fy"]), (self.last_fy, self.before_fy)
        )
        self.assertEqual((result["previous"], result["current"]), (4.0, 5.5))

        # The first confirmed record of the running year moves it on.
        self.record(self.schools[1], self.this_fy, 7.0)
        moved = intervention_comparison(self.ids())
        self.assertEqual(
            (moved["fy"], moved["previous_fy"]), (self.this_fy, self.last_fy)
        )

    def test_no_school_and_no_record_are_empty_not_an_error(self):
        for schools in ([], self.ids()):
            with self.subTest(schools=len(schools)):
                result = intervention_comparison(schools)
                self.assertFalse(result["has_any"])
                self.assertEqual(len(result["rows"]), len(ALL))

    def test_the_cost_does_not_grow_with_the_schools(self):
        for school in self.schools:
            self.record(school, self.last_fy, 5.0)
            self.record(school, self.this_fy, 6.0)

        with CaptureQueriesContext(connection) as named:
            intervention_comparison(self.ids(), self.this_fy)
        with CaptureQueriesContext(connection) as found:
            intervention_comparison(
                School.objects.filter(id__in=self.ids()).values("id")
            )

        self.assertEqual(len(named), 2)
        self.assertEqual(len(found), 3)
