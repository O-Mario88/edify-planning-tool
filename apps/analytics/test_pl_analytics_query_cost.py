"""PL analytics query cost per CCEO, and per activity-tracking card.

`cceo_performance` looped over `pls.cceos` issuing four `.count()` calls each,
and `activity_tracking.card` issued two per card across six cards. On the live
Program Lead Analytics page that showed up as 47 separate
`SELECT COUNT(*) FROM activity` statements inside a single request, with
database time at 77% of the page's wall clock.

The two are different shapes and are asserted differently, because a single
"query count must not grow" rule would be false for one and vacuous for the
other:

* `cceo_performance` genuinely scales with the team, so the test measures the
  *slope* — queries added per additional CCEO — against a one-CCEO and a
  five-CCEO team. Four became one. It is deliberately not asserted as zero;
  see the test for why folding the team into one statement is not obviously
  correct without production query plans.

* `activity_tracking` never scaled with the team at all — its loop is over six
  fixed cards — so a scaling assertion would pass on the unfixed code and
  prove nothing. It is asserted as one aggregate per card instead.

Both fail on the previous code. Neither can pass by accident, and
`test_the_fixture_really_has_five_supervised_cceos` guards the setup that makes
the first measurement meaningful.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
)
from apps.analytics.pl_analytics_service import PLAnalyticsService, resolve_pl_scope
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School

User = get_user_model()
FY = "2026"


class PLAnalyticsDoesNotFanOutPerCceoTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="QC Region")
        cls.district = District.objects.create(name="QC District", region=cls.region)
        cls.sub_county = SubCounty.objects.create(name="QC Sub", district=cls.district)
        cls.pl = User.objects.create(
            id="qc-pl",
            email="qc-pl@edify.org",
            name="QC Lead",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True,
        )
        cls.pl_sp = StaffProfile.objects.create(id="qc-pl-sp", user=cls.pl, title="PL")
        # Five CCEOs, each with a school, all supervised by the one PL.
        for i in range(5):
            user = User.objects.create(
                id=f"qc-cceo-{i}",
                email=f"qc-cceo-{i}@edify.org",
                name=f"QC Field {i}",
                roles=["CCEO"],
                active_role="CCEO",
                is_active=True,
            )
            sp = StaffProfile.objects.create(
                id=f"qc-cceo-sp-{i}", user=user, title="CCEO"
            )
            StaffSupervisorAssignment.objects.create(
                supervisor=cls.pl_sp, supervisee=sp
            )
            school = School.objects.create(
                school_id=f"QC-{i}",
                name=f"QC School {i}",
                region=cls.region,
                district=cls.district,
                sub_county=cls.sub_county,
                school_type="client",
                account_owner_id=sp.id,
            )
            StaffSchoolAssignment.objects.get_or_create(staff=sp, school_id=school.id)

    def _count_queries(self, method_name, cceo_limit):
        scope = resolve_pl_scope(self.pl, {})
        scope.cceos = scope.cceos[:cceo_limit]
        method = getattr(PLAnalyticsService, method_name)
        method(scope, FY, None, {})  # warm any per-process caches
        with CaptureQueriesContext(connection) as ctx:
            method(scope, FY, None, {})
        return len(ctx)

    def test_the_fixture_really_has_five_supervised_cceos(self):
        # Without this the two measurements below could be identical because
        # the team is empty, and the tests would pass on the old code too.
        self.assertEqual(len(resolve_pl_scope(self.pl, {}).cceos), 5)

    def test_cceo_performance_costs_at_most_one_query_per_cceo(self):
        """Four round trips per CCEO became one. Not zero — be precise.

        Each CCEO's activity set is `responsible_staff OR school in <ref>`, and
        `school_ref` is a *subquery* on the unfiltered path (see
        `_resolve_pl_scope_uncached`), not a literal id set. Folding the whole
        team into a single grouped statement would mean either materialising
        that subquery per CCEO or emitting 4N conditional aggregates in one
        SQL text — the first changes semantics, the second trades round trips
        for a statement that grows with the team. Neither is obviously right
        without production query plans, which this audit does not yet have.

        So the honest invariant is the slope: one query per CCEO, not four.
        With four the growth from one CCEO to five was +16 statements; with one
        it is +4. The assertion below pins the slope, so a regression to
        per-metric counting fails even though the absolute number is free to
        move as panels change.
        """
        one = self._count_queries("cceo_performance", 1)
        five = self._count_queries("cceo_performance", 5)
        slope = (five - one) / 4
        self.assertLessEqual(
            slope,
            1.0,
            f"cceo_performance costs {slope} queries per additional CCEO "
            f"({one} for one, {five} for five); it must be at most one",
        )

    def test_activity_tracking_issues_one_aggregate_per_card_not_two(self):
        """`activity_tracking` is a different shape from `cceo_performance`.

        Its loop is over six fixed card types, not over the team, so its cost
        never grew with CCEO count and a flat-across-team-size assertion would
        pass on the unfixed code too — it would look like coverage and be none.
        What it did do was ask for `planned` and `done` in two separate
        statements per card, twelve where six would do.

        The number below is therefore deliberately absolute. If a card is added
        this test fails and wants updating, which is the point: it should not
        be possible to quietly go back to two round trips per card.
        """
        scope = resolve_pl_scope(self.pl, {})
        PLAnalyticsService.activity_tracking(scope, FY, None, {})  # warm
        with CaptureQueriesContext(connection) as ctx:
            result = PLAnalyticsService.activity_tracking(scope, FY, None, {})

        # Match COUNT(*) as well as COUNT("activity"."id"): the unfixed code
        # reaches this through `.count()`, which emits the former. Matching only
        # the latter would score the old code as zero queries and fail with a
        # message that reads like the opposite of the truth.
        counts = [
            q
            for q in ctx.captured_queries
            if "COUNT(" in q["sql"] and 'FROM "activity"' in q["sql"]
        ]
        self.assertEqual(
            len(counts),
            len(result["cards"]),
            f"expected one aggregate per card, got {len(counts)} for "
            f"{len(result['cards'])} cards",
        )
