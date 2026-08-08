"""The Planning Progress card's Week / Month / Quarter / FY switch.

The four labels were `<span>` elements: no href, no handler, no target. They
could not be clicked, and the chart drew the same five weeks whichever one
carried `is-active`. These tests pin both halves of the fix -- the series is
real for each period, and the controls actually reach it.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.command_center.planning_progress import (
    BUCKET_COUNT,
    PERIODS,
    buckets_for,
    normalise_period,
    series,
    tabs,
)
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.schools.models import School


class PeriodBucketTests(TestCase):
    """Bucket maths, independent of the database."""

    def test_every_period_produces_its_declared_number_of_buckets(self):
        today = date(2026, 7, 28)
        for period in PERIODS:
            with self.subTest(period):
                self.assertEqual(len(buckets_for(period, today)), BUCKET_COUNT[period])

    def test_buckets_run_oldest_to_newest_and_never_overlap(self):
        today = date(2026, 7, 28)
        for period in PERIODS:
            with self.subTest(period):
                windows = buckets_for(period, today)
                for earlier, later in zip(windows, windows[1:]):
                    self.assertLess(earlier.start, later.start)
                    self.assertLess(earlier.end, later.start)

    def test_the_last_bucket_contains_today(self):
        today = date(2026, 7, 28)
        for period in PERIODS:
            with self.subTest(period):
                last = buckets_for(period, today)[-1]
                self.assertLessEqual(last.start, today)
                self.assertLessEqual(today, last.end)

    def test_the_financial_year_runs_october_to_september(self):
        windows = buckets_for("fy", date(2026, 7, 28))
        self.assertEqual(windows[-1].start, date(2025, 10, 1))
        self.assertEqual(windows[-1].end, date(2026, 9, 30))
        self.assertEqual(windows[-1].label, "FY 2026")

    def test_quarter_one_is_october_to_december(self):
        """FY quarters, not calendar quarters."""
        windows = buckets_for("quarter", date(2025, 11, 15))
        current = windows[-1]
        self.assertEqual(current.start, date(2025, 10, 1))
        self.assertEqual(current.end, date(2025, 12, 31))
        self.assertEqual(current.label, "2026 Q1")

    def test_quarters_walk_back_across_a_financial_year_boundary(self):
        labels = [b.label for b in buckets_for("quarter", date(2025, 11, 15))]
        self.assertEqual(labels, ["2025 Q2", "2025 Q3", "2025 Q4", "2026 Q1"])

    def test_months_walk_back_across_a_calendar_year_boundary(self):
        labels = [b.label for b in buckets_for("month", date(2026, 2, 10))]
        self.assertEqual(
            labels, ["Sep 25", "Oct 25", "Nov 25", "Dec 25", "Jan 26", "Feb 26"]
        )

    def test_an_unknown_period_falls_back_to_the_week_view(self):
        for value in ("", None, "decade", "../etc", "'; drop table"):
            with self.subTest(value):
                self.assertEqual(normalise_period(value), "week")

    def test_a_period_is_recognised_whatever_its_casing_or_padding(self):
        self.assertEqual(normalise_period("QUARTER"), "quarter")
        self.assertEqual(normalise_period(" Month "), "month")
        self.assertEqual(normalise_period("FY"), "fy")

    def test_exactly_one_tab_is_active(self):
        for period in PERIODS:
            with self.subTest(period):
                active = [t for t in tabs(period) if t["active"]]
                self.assertEqual(len(active), 1)
                self.assertEqual(active[0]["period"], period)


class PeriodSeriesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Progress Region")
        cls.district = District.objects.create(
            name="Progress District", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="SCH-PROG-1",
            name="Progress Primary",
            region=cls.region,
            district=cls.district,
        )
        cls.user = User.objects.create(
            id="progress-admin",
            email="progress-admin@edify.org",
            name="Progress Admin",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        StaffProfile.objects.create(
            id="progress-admin-sp", user=cls.user, title="Admin"
        )

    def _activity(self, planned: date, status: str = "scheduled"):
        return Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status=status,
            fy=get_operational_fy(planned),
            school=self.school,
            planned_date=planned,
            scheduled_date=planned,
        )

    def _all(self):
        return Activity.objects.filter(deleted_at__isnull=True)

    def test_a_bucket_with_nothing_planned_is_not_zero_percent(self):
        """ "Nothing planned" and "everything missed" are different facts."""
        points = series(self._all(), "week", date(2026, 7, 28))
        for point in points:
            self.assertIsNone(point["percentage"])
            self.assertFalse(point["measured"])
            self.assertEqual(point["total"], 0)

    def test_completion_is_counted_against_what_was_planned(self):
        today = date(2026, 7, 28)  # a Tuesday
        this_week = today - timedelta(days=today.weekday())
        self._activity(this_week, status="completed")
        self._activity(this_week + timedelta(days=1), status="scheduled")

        current = series(self._all(), "week", today)[-1]
        self.assertEqual(current["total"], 2)
        self.assertEqual(current["done"], 1)
        self.assertEqual(current["percentage"], 50)

    def test_accountant_confirmed_work_counts_as_done(self):
        """The canonical done-set, not a hand-written list that forgets it."""
        today = date(2026, 7, 28)
        this_week = today - timedelta(days=today.weekday())
        self._activity(this_week, status="accountant_confirmed")

        current = series(self._all(), "week", today)[-1]
        self.assertEqual(current["percentage"], 100)

    def test_each_period_buckets_the_same_activity_differently(self):
        """One activity, four periods -- each must place it in its own last
        bucket, which is what proves the tabs are doing real work."""
        today = date(2026, 7, 28)
        this_week = today - timedelta(days=today.weekday())
        self._activity(this_week, status="completed")

        for period in PERIODS:
            with self.subTest(period):
                points = series(self._all(), period, today)
                self.assertEqual(points[-1]["total"], 1, period)
                self.assertEqual(points[-1]["percentage"], 100, period)

    def test_a_wider_period_gathers_work_a_narrower_one_misses(self):
        today = date(2026, 7, 28)
        # Three months ago: outside the 5-week window, inside the 6-month one.
        self._activity(date(2026, 4, 15), status="completed")

        week = series(self._all(), "week", today)
        month = series(self._all(), "month", today)

        self.assertEqual(sum(p["total"] for p in week), 0)
        self.assertEqual(sum(p["total"] for p in month), 1)

    def test_the_fy_view_reaches_past_the_current_financial_year(self):
        """The regression this guards: building the series from an fy-filtered
        queryset would show the current year beside two empty ones."""
        self._activity(date(2024, 11, 5), status="completed")  # FY 2025
        self._activity(date(2026, 2, 10), status="completed")  # FY 2026

        points = series(self._all(), "fy", date(2026, 7, 28))
        by_label = {p["label"]: p for p in points}
        self.assertEqual(by_label["FY 2025"]["total"], 1)
        self.assertEqual(by_label["FY 2026"]["total"], 1)

    def test_activities_outside_every_bucket_are_ignored(self):
        self._activity(date(2019, 1, 1), status="completed")
        points = series(self._all(), "fy", date(2026, 7, 28))
        self.assertEqual(sum(p["total"] for p in points), 0)

    def test_a_series_costs_one_query_whatever_the_period(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        today = date(2026, 7, 28)
        for i in range(20):
            self._activity(today - timedelta(days=i * 9), status="completed")

        for period in PERIODS:
            with self.subTest(period):
                with CaptureQueriesContext(connection) as queries:
                    series(self._all(), period, today)
                self.assertEqual(len(queries.captured_queries), 1)


class PeriodSwitchPageTests(TestCase):
    """The controls themselves — the half that was missing entirely."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create(
            id="progress-page-admin",
            email="progress-page@edify.org",
            name="Progress Page Admin",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        StaffProfile.objects.create(
            id="progress-page-sp", user=cls.admin, title="Admin"
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)

    def test_the_tabs_are_reachable_controls_not_decorative_spans(self):
        body = self.client.get("/dashboard").content.decode()
        for period in PERIODS:
            with self.subTest(period):
                self.assertIn(f'href="?progress_period={period}"', body)
                self.assertIn(f'data-admin-progress-period="{period}"', body)
        self.assertIn("data-edify-tablist", body)
        self.assertEqual(body.count("data-edify-tab\n"), len(PERIODS))
        self.assertNotIn(
            '<span class="is-active">Week</span><span>Month</span>',
            body,
            "the decorative switch markup must be gone",
        )

    def test_the_tabs_and_details_link_share_the_card_header(self):
        body = self.client.get("/dashboard").content.decode()
        header_start = body.index(
            '<header class="admin-panel__header admin-planning-progress__header">'
        )
        header_end = body.index("</header>", header_start)
        header = body[header_start:header_end]

        self.assertIn('class="admin-panel__header-actions"', header)
        self.assertIn('class="admin-period-switch"', header)
        self.assertIn('href="/planning">View Details</a>', header)
        self.assertNotIn("<figure", header)

    def test_each_period_renders_its_own_series(self):
        expectations = {
            "week": "five most recent planning weeks",
            "month": "six most recent months",
            "quarter": "four most recent financial quarters",
            "fy": "three most recent financial years",
        }
        for period, description in expectations.items():
            with self.subTest(period):
                response = self.client.get(f"/dashboard?progress_period={period}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["progress_period"], period)
                self.assertIn(description, response.content.decode())

    def test_the_selected_tab_is_the_marked_one(self):
        response = self.client.get("/dashboard?progress_period=quarter")
        active = [t for t in response.context["progress_tabs"] if t["active"]]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["period"], "quarter")
        self.assertIn('aria-current="true"', response.content.decode())

    def test_the_bucket_count_changes_with_the_period(self):
        for period in PERIODS:
            with self.subTest(period):
                response = self.client.get(f"/dashboard?progress_period={period}")
                self.assertEqual(
                    len(response.context["weekly_progress"]), BUCKET_COUNT[period]
                )

    def test_the_htmx_fragment_returns_just_the_chart(self):
        response = self.client.get(
            "/dashboard/planning-progress?progress_period=month",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertNotIn("<!DOCTYPE html>", body)
        self.assertIn('id="admin-planning-progress-body"', body)
        self.assertIn("six most recent months", body)

    def test_the_fragment_and_the_page_agree(self):
        page = self.client.get("/dashboard?progress_period=quarter")
        fragment = self.client.get(
            "/dashboard/planning-progress?progress_period=quarter"
        )
        self.assertEqual(
            [p["label"] for p in page.context["weekly_progress"]],
            [p["label"] for p in fragment.context["weekly_progress"]],
        )

    def test_a_junk_period_falls_back_rather_than_erroring(self):
        response = self.client.get("/dashboard?progress_period=../../etc/passwd")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["progress_period"], "week")

    def test_the_fragment_is_not_open_to_anonymous_visitors(self):
        client = Client()
        response = client.get("/dashboard/planning-progress?progress_period=fy")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response["Location"])
