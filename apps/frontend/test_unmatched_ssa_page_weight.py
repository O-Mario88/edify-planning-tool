"""The unmatched-SSA queue must not ship the school list once per row.

Live production returned **37.3 MB in 61 seconds** for this page. The picker in
each row rendered every active school, so the response was
(rows on the page) x (16,274 schools) options — roughly half a million option
elements. That is the §47 "unbounded production queryset" gate, and the page
was effectively unusable.

The list is identical for every row, so it is now emitted once. These tests pin
the property that matters: response size must stay flat as rows are added.
"""

from __future__ import annotations

import re

from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.accounts.models import User
from apps.geography.models import District, Region
from apps.schools.models import School, UnmatchedSSARecord


SCHOOL_COUNT = 60


class UnmatchedSsaQueueWeightTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Weight Region")
        district = District.objects.create(name="Weight District", region=region)
        for i in range(SCHOOL_COUNT):
            School.objects.create(
                school_id=f"WGT-{i:04d}",
                name=f"Weight Primary {i}",
                region=region,
                district=district,
            )
        cls.admin = User.objects.create(
            id="wgt-admin",
            email="wgt-admin@edify.org",
            name="Weight Admin",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
        StaffProfile.objects.create(id="wgt-admin-sp", user=cls.admin, title="Admin")

    def setUp(self):
        self.client.force_login(self.admin)

    @staticmethod
    def _unmatched(n):
        for i in range(n):
            UnmatchedSSARecord.objects.create(
                school_id=f"UNKNOWN-{i:04d}",
                scores={"leadership": 4.0},
                status="pending",
            )

    def _fetch(self):
        response = self.client.get("/ssa/unmatched")
        self.assertEqual(response.status_code, 200)
        return response.content

    def test_option_count_does_not_multiply_by_the_number_of_rows(self):
        self._unmatched(6)
        body = self._fetch().decode("utf-8", "replace")

        options = len(re.findall(r"<option ", body))
        self.assertLess(
            options,
            SCHOOL_COUNT * 2,
            "the school list must be rendered once for the page, not once per "
            f"row — found {options} options for {SCHOOL_COUNT} schools",
        )

    def test_the_school_list_is_not_repeated_as_rows_are_added(self):
        """The precise property: adding a row must not add a school list.

        Asserted on option COUNT rather than byte size, because a table row
        here legitimately carries two forms, two CSRF tokens and a lot of
        utility classes — several KB that has nothing to do with this defect.
        Each new row is allowed exactly its own "-- Select school --"
        placeholder; anything more means the 16,274-school list came back.
        """

        def options_for(rows):
            UnmatchedSSARecord.objects.all().delete()
            self._unmatched(rows)
            body = self._fetch().decode("utf-8", "replace")
            return len(re.findall(r"<option ", body))

        small = options_for(2)
        large = options_for(20)

        self.assertLessEqual(
            large - small,
            18,
            "18 extra rows may add at most their 18 placeholder options — "
            f"they added {large - small}, so the school list is per-row again",
        )

    def test_the_shared_list_is_present_and_carries_every_school(self):
        self._unmatched(1)
        body = self._fetch().decode("utf-8", "replace")

        self.assertIn(
            'id="ssa-school-options"',
            body,
            "the shared option list must still be shipped — the picker is "
            "useless without it",
        )
        self.assertIn("Weight Primary 0", body)
        self.assertIn(f"Weight Primary {SCHOOL_COUNT - 1}", body)

    def test_the_posted_field_is_unchanged(self):
        self._unmatched(1)
        body = self._fetch().decode("utf-8", "replace")

        self.assertIn(
            'name="school_id"',
            body,
            "the form contract must not change — the server still resolves a "
            "School pk from this field",
        )
