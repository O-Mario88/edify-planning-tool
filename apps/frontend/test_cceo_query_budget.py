"""The CCEO's four daily surfaces, each pinned to its query cost.

A CCEO opens /dashboard, /today, /planning and /fund-requests/weekly many
times a day, on a phone, on field data. Nothing pinned what those pages cost,
so a per-row lookup could land on any of them and only show up months later
as "the dashboard feels slow". This module measures each page over the real
request cycle (the same CaptureQueriesContext-over-client pattern as
apps/command_center/test_todo_query_budget.py) and holds two things:

1. A ceiling per page, set at the measured count plus a small margin. A
   ceiling, never a target: a page may get cheaper without touching this
   file, and may not get dearer without someone reading it.

2. A shape: doubling the CCEO's scheduled activities may not move the count
   at all. Every list the dashboard renders is capped and select_related, so
   the cost of the page is a function of its sections, not of the week's
   plan. Where a page is O(activities) today that is documented on the test
   and the absolute number is pinned instead.

Measured after the first request of a session: the first request also writes
django_session, which is the cost of logging in and not of the page. The
cache is cleared before every measurement so a To-Do snapshot left behind by
one page cannot make the next one look cheaper than it is.
"""

from __future__ import annotations

import datetime

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.schools.models import School

PAGES = ("/dashboard", "/today", "/planning", "/fund-requests/weekly")

# Measured on 2026-09-04 against the fixture below, at 6 scheduled activities
# and again at 12. Each ceiling is the measured count plus at most ten per
# cent. /dashboard was 103 before the unrendered right rail (alerts, donut,
# upcoming week, pending approvals, the To-Do queue, the notification badge)
# stopped being computed, and 29 before monthly_urgent_schools joined the
# district it reads per row.
#
#   page                    @6    @12   ceiling
#   /dashboard              25     25   27
#   /today                  78     78   85
#   /planning               38     38   41
#   /fund-requests/weekly   71     72   79
CEILINGS = {
    "/dashboard": 27,
    "/today": 85,
    "/planning": 41,
    "/fund-requests/weekly": 79,
}

# Pages whose cost may not move at all when the week's activities double.
# /fund-requests/weekly is not among them: it measured one query more at 12
# activities than at 6 (an extra advance_request read in the fund-requests
# workspace, outside this module's remit), so it is held to its ceiling only.
FLAT = ("/dashboard", "/today", "/planning")


class CceoQueryBudgetTests(TestCase):
    """Ceilings and shapes for the CCEO's daily pages."""

    ACTIVITIES = 6

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Budget Region")
        cls.district = District.objects.create(
            name="Budget District", region=cls.region, district_type="primary"
        )
        cls.schools = [
            School.objects.create(
                school_id=f"QB-{index}",
                name=f"Query Budget School {index}",
                region=cls.region,
                district=cls.district,
                school_type="client",
            )
            for index in range(4)
        ]
        cls.cluster = Cluster.objects.create(
            name="Query Budget Cluster", region=cls.region, district=cls.district
        )
        cls.cceo = User.objects.create_user(
            email="qb-cceo@edify.org",
            name="Query Budget CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        cls.cceo_sp = StaffProfile.objects.create(
            user=cls.cceo, staff_number="QB-CCEO", country="Uganda", title="CCEO"
        )
        for school in cls.schools:
            StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=school.id)

        cls.today = timezone.localdate()
        cls.week_start = cls.today - datetime.timedelta(days=cls.today.weekday())
        cls.fy = get_operational_fy(cls.today)
        cls.seeded = 0
        cls._seed_activities(cls.ACTIVITIES)

    @classmethod
    def _seed_activities(cls, count):
        """`count` more scheduled, costed activities on today's date.

        Dated today so every page's window (this week, this day, this fund
        request) contains them all; a mix of school visits and one cluster
        meeting per batch so both dashboard lists have rows.
        """
        from apps.fund_requests.advance_service import sync_for_activity
        from apps.fund_requests.weekly_service import generate_weekly_fund_request

        at = timezone.make_aware(
            datetime.datetime.combine(cls.today, datetime.time(9, 0))
        )
        for offset in range(count):
            index = cls.seeded + offset
            is_cluster = offset == count - 1
            activity = Activity.objects.create(
                activity_type="cluster_meeting" if is_cluster else "school_visit",
                delivery_type="staff",
                status="scheduled",
                fy=cls.fy,
                school=None if is_cluster else cls.schools[index % len(cls.schools)],
                cluster=cls.cluster if is_cluster else None,
                responsible_staff_id=cls.cceo.id,
                scheduled_date=at,
                planned_date=cls.today,
                expected_participants=20,
                activity_purpose_text=f"Budget visit {index}",
            )
            ActivityScheduleCostLine.objects.create(
                activity=activity,
                cost_setting_key="primary_transport_per_day",
                line_item_type="transport",
                label="Transport",
                quantity=1,
                unit_cost=50_000,
                amount=50_000,
                planned_date=cls.today,
                month=cls.today.month,
                fiscal_year=cls.fy,
                responsible_user=cls.cceo.id,
            )
            sync_for_activity(activity, cls.cceo.id)
        cls.seeded += count
        generate_weekly_fund_request(cls.cceo.id, cls.week_start.isoformat())

    def _queries(self, url):
        self.client.force_login(self.cceo)
        self.assertEqual(self.client.get(url).status_code, 200)
        cache.clear()
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return len(captured.captured_queries)

    def test_each_page_stays_within_its_ceiling(self):
        for url in PAGES:
            with self.subTest(page=url):
                count = self._queries(url)
                self.assertLessEqual(
                    count,
                    CEILINGS[url],
                    f"{url} cost {count} queries for a CCEO with "
                    f"{self.ACTIVITIES} scheduled activities, over a ceiling of "
                    f"{CEILINGS[url]}. Something on the page is paying per row.",
                )

    def test_doubling_the_weeks_activities_does_not_move_the_cost(self):
        """The regression that matters, stated as a shape rather than a number.

        Every list these pages render is capped and joined up front, so twice
        the activities is the same number of queries. The dashboard does still
        carry one per-school term -- resolve_urgent_issue asks each school
        planned this month about its SSA and verified support one at a time --
        which this fixture holds constant (the doubled activities land on the
        same four schools) and the ceiling above bounds.
        """
        baseline = {url: self._queries(url) for url in PAGES}
        self._seed_activities(self.ACTIVITIES)
        grown = {url: self._queries(url) for url in PAGES}

        for url in PAGES:
            with self.subTest(page=url):
                self.assertLessEqual(grown[url], CEILINGS[url])
                if url in FLAT:
                    self.assertEqual(
                        baseline[url],
                        grown[url],
                        f"{url} cost {baseline[url]} queries with "
                        f"{self.ACTIVITIES} activities and {grown[url]} with "
                        f"{2 * self.ACTIVITIES}. Something on this page is "
                        "resolving activities one at a time.",
                    )
