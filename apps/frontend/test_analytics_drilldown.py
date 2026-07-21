"""Regression tests for /analytics/drilldown.

This endpoint had two successive defects in the account-owner column, and the
SECOND one survived a fix because the endpoint had no test at all and was
verified by hand against a dataset whose drill-down querysets returned zero
rows. An empty result set never enters the row-building loop, so the page
rendered 200 and looked healthy while being guaranteed to crash on the first
real row.

Every test here therefore asserts on ROWS, not just on status. A drill-down
that returns 200 with an empty table would pass a status-only assertion and
prove nothing at all -- which is exactly what happened before.

Background: School.account_owner_id is a plain CharField holding a user id.
There is no `account_owner` relation, so both `select_related("account_owner__user")`
(a FieldError at queryset construction) and `s.account_owner.user.name`
(an AttributeError per row) are invalid. The first was fixed; the second was
missed three lines below it.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.geography.models import Region, District
from apps.schools.models import School

# The three metrics whose drawers render the account-owner column. These are
# the ones that crashed; the aggregate metrics above them never touch it.
OWNER_COLUMN_METRICS = ("no_ssa", "not_visited", "not_trained")


class AnalyticsDrilldownOwnerColumnTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.viewer = User.objects.create(
            id="drill-cd",
            email="drill-cd@edify.org",
            name="Drill CD",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )
        cls.viewer.set_password("pass123")
        cls.viewer.save()
        StaffProfile.objects.create(id="drill-staff-cd", user=cls.viewer, title="CD")

        cls.owner = User.objects.create(
            id="drill-owner",
            email="drill-owner@edify.org",
            name="Amina Owner",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )

        region = Region.objects.create(name="Drill Region")
        district = District.objects.create(name="Drill District", region=region)

        # 1. Owner id resolves to a real User -> shows that user's name.
        cls.school_resolved = School.objects.create(
            school_id="DRILL-001",
            name="Resolved Owner School",
            region=region,
            district=district,
            school_type="client",
            current_fy_ssa_status="not_done",
            account_owner_id=cls.owner.id,
            account_owner_name_raw="Stale Raw Name",
        )
        # 2. Owner id points at nothing (legacy Salesforce import) -> falls back
        #    to the denormalised raw name rather than to a dash.
        cls.school_raw_only = School.objects.create(
            school_id="DRILL-002",
            name="Raw Owner School",
            region=region,
            district=district,
            school_type="client",
            current_fy_ssa_status="not_done",
            account_owner_id="user-that-does-not-exist",
            account_owner_name_raw="Legacy Owner",
        )
        # 3. No owner at all -> dash, and must not raise.
        cls.school_no_owner = School.objects.create(
            school_id="DRILL-003",
            name="Unowned School",
            region=region,
            district=district,
            school_type="client",
            current_fy_ssa_status="not_done",
        )

    def setUp(self):
        self.client.force_login(self.viewer)

    def _drilldown(self, metric):
        response = self.client.get("/analytics/drilldown", {"metric": metric})
        self.assertEqual(
            response.status_code,
            200,
            f"/analytics/drilldown?metric={metric} returned " f"{response.status_code}",
        )
        return response

    def test_owner_column_metrics_render_rows_without_crashing(self):
        """The regression itself: these drawers must survive a populated row.

        Asserting the school name proves the loop body actually executed --
        a status-only assertion passes on an empty table, which is how the
        previous fix was verified as working when it was not.
        """
        for metric in OWNER_COLUMN_METRICS:
            with self.subTest(metric=metric):
                response = self._drilldown(metric)
                self.assertContains(response, "Resolved Owner School")

    def test_owner_name_is_resolved_from_the_user_id(self):
        response = self._drilldown("no_ssa")
        self.assertContains(response, "Amina Owner")
        # The live user record wins over the denormalised copy.
        self.assertNotContains(response, "Stale Raw Name")

    def test_owner_falls_back_to_raw_name_when_the_user_is_missing(self):
        """A dangling owner id must not render as "-" when the school does
        have a recorded owner name."""
        response = self._drilldown("no_ssa")
        self.assertContains(response, "Legacy Owner")

    def test_school_without_an_owner_still_renders(self):
        response = self._drilldown("no_ssa")
        self.assertContains(response, "Unowned School")

    def test_owner_lookup_is_batched(self):
        """One query for all owner names regardless of row count.

        Guards against the obvious "fix" of swapping the invalid attribute
        access for a per-row User.objects.get().
        """
        School.objects.bulk_create(
            [
                School(
                    school_id=f"DRILL-N-{i:03d}",
                    name=f"N Plus One School {i:03d}",
                    region=self.school_resolved.region,
                    district=self.school_resolved.district,
                    school_type="client",
                    current_fy_ssa_status="not_done",
                    account_owner_id=self.owner.id,
                )
                for i in range(40)
            ]
        )
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            self._drilldown("no_ssa")
        owner_queries = [q for q in ctx.captured_queries if 'FROM "user"' in q["sql"]]
        self.assertLessEqual(
            len(owner_queries),
            3,
            f"owner resolution issued {len(owner_queries)} user queries for 43 "
            f"rows -- it must be batched, not per row.",
        )
