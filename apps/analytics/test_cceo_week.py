"""The field officer's This Week (owner, 2026-09-26).

"Work on the CCEO dashboard to look like the redesigned PL dashboard, but only
showing their own overdue planned activities, this week's planned
activities ... partner monitoring ... everything we did with the PL
dashboard, except only the CCEO's activities, schools, and the partners they
assigned schools to."

The Programme Lead's week in its solo mode: one person, the officer; their
rows keep their own actions; their completed work waits on their Programme
Lead; partner work read in their own Partner Monitoring scope.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.analytics.pl_week_service import (
    DUE_THIS_WEEK,
    EVERYONE,
    ME,
    OVERDUE,
    OWN_AWAITING_LABEL,
    PARTNERS,
    build_week,
    monday_of,
)
from apps.analytics.test_pl_week import (
    LAST_MONDAY,
    LOCMEM,
    MONDAY,
    THURSDAY,
    PLWeekTest,
)

_pl = PLWeekTest


@override_settings(CACHES=LOCMEM)
class OfficerWeekTest(TestCase):
    setUp = _pl.setUp
    _staff = _pl._staff
    _school = _pl._school
    _act = _pl._act
    _table = _pl._table

    def _week(self, who="", listing=""):
        return build_week(
            self.a1, fy="2026", who=who, today=THURSDAY, listing=listing, solo=True
        )

    def test_one_person_three_tabs_opening_on_my_activities(self):
        week = self._week()
        self.assertTrue(week["solo"])
        self.assertEqual([p["key"] for p in week["people"]], [ME])
        self.assertEqual(
            [(t["key"], t["label"]) for t in week["tabs"]],
            [(ME, "My activities"), (EVERYONE, "My week"), (PARTNERS, "My partners")],
        )
        self.assertEqual(week["who"], ME)
        self.assertIn("person", week)

    def test_only_the_officers_own_work(self):
        mine = self._act(self.a1_sp, self.s1, MONDAY + timedelta(days=4))
        self._act(self.a2_sp, self.s2, MONDAY)
        week = self._week(listing=DUE_THIS_WEEK)
        ids = [r["id"] for r in self._table(week["person"], "visits")]
        self.assertEqual(ids, [mine.id])

    def test_the_week_is_this_weeks_work_and_counts_the_past_due(self):
        """Overdue work of any age is the dashboard's past-due table, so the
        officer's week lists this week's work alone and counts the rest."""
        self._act(self.a1_sp, self.s1, LAST_MONDAY, status="in_progress")
        due = self._act(self.a1_sp, self.s1, THURSDAY)
        week = self._week()
        person = week["person"]
        self.assertEqual(person["listing"], DUE_THIS_WEEK)
        self.assertEqual([item["key"] for item in person["lists"]], [DUE_THIS_WEEK])
        [row] = self._table(person, "visits")
        self.assertEqual(row["id"], due.id)
        # Complete / Reschedule / Cancel, never Verify or Send to.
        self.assertEqual(row["action"], "own")
        self.assertNotEqual(OVERDUE, person["listing"])

    def test_the_tab_counts_what_is_past_due(self):
        from apps.my_plan.past_due_service import get_past_due_dashboard_context

        # The past-due table reads the real clock, so last week is last week
        # of the day the suite runs.
        last_week = monday_of(timezone.localdate()) - timedelta(days=7)
        self._act(self.a1_sp, self.s1, last_week, status="in_progress")
        # Done by its status, missing its form and ID: past due too.
        self._act(self.a1_sp, self.s1, last_week, status="completed", complete=False)
        total = get_past_due_dashboard_context(self.a1)["past_due_total_count"]
        self.assertEqual(total, 2)
        tab = next(t for t in self._week()["tabs"] if t["key"] == ME)
        self.assertEqual(tab["count"], total)

    def test_completed_work_waits_on_their_programme_lead(self):
        done = self._act(
            self.a1_sp,
            self.s1,
            MONDAY,
            status="submitted_to_pl",
            complete=True,
        )
        week = self._week(listing=DUE_THIS_WEEK)
        [row] = [r for r in self._table(week["person"], "visits") if r["id"] == done.id]
        self.assertEqual(row["status_label"], OWN_AWAITING_LABEL)
        self.assertEqual(row["action"], "none")


@override_settings(CACHES=LOCMEM)
class OfficerDashboardTest(TestCase):
    setUp = _pl.setUp
    _staff = _pl._staff
    _school = _pl._school

    def _get(self, url, **headers):
        self.client.force_login(self.a1)
        response = self.client.get(url, **headers)
        self.assertEqual(response.status_code, 200)
        return response

    def test_this_week_opens_the_dashboard(self):
        response = self._get("/dashboard")
        self.assertTemplateUsed(response, "pages/dashboards/cceo.html")
        html = response.content.decode()
        self.assertIn("data-pl-week-panel", html)
        self.assertIn('data-pl-week-who="me"', html)
        for label in (
            "This Week",
            "Urgent schools",
            "My activities",
            "My week",
            "My partners",
        ):
            with self.subTest(label=label):
                self.assertIn(label, html)
        self.assertIn("css/components/pl-week.css", html)

    def test_the_weeks_own_tabs_swap_the_panel_alone(self):
        response = self._get(
            "/dashboard?view=week&who=everyone", HTTP_HX_TARGET="pl-week-panel"
        )
        self.assertTemplateUsed(response, "partials/dashboards/pl/week_panel.html")
        self.assertTemplateNotUsed(response, "pages/dashboards/cceo.html")
        self.assertIn('data-pl-week-who="everyone"', response.content.decode())

    def test_today_is_the_weeks_my_activities(self):
        html = self._get("/dashboard?view=today").content.decode()
        self.assertIn('data-pl-week-who="me"', html)

    def test_urgent_schools_keeps_its_own_tab(self):
        html = self._get("/dashboard?view=operations").content.decode()
        self.assertIn("Schools Needing Urgent Attention", html)
        self.assertNotIn("This Week's Plan", html)
        self.assertNotIn("data-pl-week-panel", html)
