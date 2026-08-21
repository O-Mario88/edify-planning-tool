import time

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import User
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School

from . import lending_impact


class LendingFiftyThousandSchoolScaleTests(TestCase):
    """The geographic spine must stay server-side and query-count bounded."""

    @classmethod
    def setUpTestData(cls):
        cls.rvp = User.objects.create_user(
            email="lending-scale-rvp@example.org",
            name="Lending Scale RVP",
            roles=[EdifyRole.REGIONAL_VICE_PRESIDENT.value],
            active_role=EdifyRole.REGIONAL_VICE_PRESIDENT.value,
        )
        region = Region.objects.create(name="Scale Region")
        district = District.objects.create(name="Scale District", region=region)
        School.objects.bulk_create(
            [
                School(
                    school_id=f"UG-SCALE-{index:05d}",
                    name=f"Scale School {index:05d}",
                    region=region,
                    district=district,
                )
                for index in range(50_000)
            ],
            batch_size=2_000,
        )

    def test_geographic_equity_is_bounded_at_fifty_thousand_schools(self):
        started = time.monotonic()
        with CaptureQueriesContext(connection) as queries:
            report = lending_impact.geographic_equity(self.rvp)
        elapsed = time.monotonic() - started

        self.assertEqual(report["rows"][0]["eligibleSchools"], 50_000)
        self.assertEqual(report["rows"][0]["dataState"], "zero")
        self.assertLessEqual(len(queries), 5)
        self.assertLess(elapsed, 5.0)
