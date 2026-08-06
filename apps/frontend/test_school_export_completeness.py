"""The school export returns every school in scope, not the first 5,000.

Found during the live production audit. `/schools?export=csv` carried a bare
`[:5000]`, so a country-scope export of 16,274 schools produced a 5,000-row
file with nothing — no banner, no header, no truncation notice — to say the
other 11,274 were missing. Scoped roles never reached the limit, so the only
people it misled were the ones looking at the whole country. It cost me a
wrong conclusion during the audit itself: an id was "absent from the
directory" because it sat past row 5,000.

A truncated export that looks complete is worse than a refused one. These are
used as reconciliation sources.

The test creates more than the old limit deliberately. A fixture of ten rows
would pass whether or not the cap exists, and a test that cannot fail is the
thing this file is guarding against.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School

User = get_user_model()

OLD_CAP = 5000
TOTAL = OLD_CAP + 25


class SchoolExportIsNotTruncatedTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="EX Region")
        cls.district = District.objects.create(name="EX District", region=cls.region)
        cls.sub = SubCounty.objects.create(name="EX Sub", district=cls.district)
        School.objects.bulk_create(
            [
                School(
                    school_id=f"EX-{i:05d}",
                    name=f"EX School {i}",
                    region=cls.region,
                    district=cls.district,
                    sub_county=cls.sub,
                    school_type="client",
                )
                for i in range(TOTAL)
            ],
            batch_size=1000,
        )
        # Country scope, so the export is not narrowed by assignment.
        cls.admin = User.objects.create(
            id="ex-admin",
            email="ex-admin@edify.org",
            name="EX Admin",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_the_fixture_really_exceeds_the_old_cap(self):
        # Without this the assertions below could pass on a small dataset and
        # prove nothing about truncation.
        self.assertGreater(School.objects.count(), OLD_CAP)

    def test_csv_export_contains_every_school(self):
        response = self.client.get("/schools?export=csv")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        rows = [line for line in body.splitlines() if line.strip()]
        self.assertEqual(
            len(rows) - 1,  # minus the header
            School.objects.count(),
            "the export must contain every school in scope, not the first 5,000",
        )

    def test_the_last_school_is_present_not_just_the_count(self):
        """A count can be right while the tail is wrong — assert the boundary.

        The row that used to disappear is the one just past the old limit.
        """
        response = self.client.get("/schools?export=csv")
        body = response.content.decode()
        self.assertIn(f"EX-{TOTAL - 1:05d}", body)
        self.assertIn(f"EX-{OLD_CAP:05d}", body)
