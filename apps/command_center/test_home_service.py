"""Home (owner, 2026-10-21): the phone's first tab and the native app's start.

What matters is that Home tells the truth and agrees with the pages it opens:
each plan figure counts one disjoint slice of the reader's own My Plan in the
operational financial year, and the My Plan list it links to shows exactly
those activities. Priority actions are the To-Do queue's own first entries,
and a role with no plan of its own gets queue figures, not misleading zeros.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.command_center import home_service
from apps.command_center.home_service import (
    build_home,
    build_home_queue,
    build_home_todo_figures,
    greeting_for,
    priority_actions,
)
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.schools.models import School

LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "home-service",
    }
}


def _staff(email, name, role):
    user = User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    return user, StaffProfile.objects.create(user=user, title=role)


@override_settings(CACHES=LOCMEM)
class HomePlanFiguresTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.fy = get_operational_fy()
        region = Region.objects.create(name="Home Region")
        district = District.objects.create(name="Home District", region=region)
        cls.school = School.objects.create(
            school_id="HOME-1",
            name="Greenwood School",
            region=region,
            district=district,
        )
        cls.cceo, cls.cceo_sp = _staff("home-cceo@t.org", "Sarah Achieng", "CCEO")
        cls.other, cls.other_sp = _staff("home-other@t.org", "Other Officer", "CCEO")

        def visit(status, days, owner=None, **extra):
            return Activity.objects.create(
                school=cls.school,
                activity_type="school_visit",
                delivery_type=extra.pop("delivery_type", "staff"),
                status=status,
                responsible_staff_id=(owner or cls.cceo_sp).id,
                fy=extra.pop("fy", cls.fy),
                quarter="Q1",
                planned_date=cls.today + timedelta(days=days),
                **extra,
            )

        cls.ahead = visit("scheduled", 3)
        cls.ahead_later = visit("rescheduled", 9)
        cls.passed = visit("scheduled", -4)
        cls.started = visit("in_progress", -1)
        cls.with_reviewer = visit("submitted_to_pl", -6)
        # None of these is the officer's open plan.
        cls.done = visit("completed", -10)
        cls.called_off = visit("cancelled", 2)
        cls.someone_elses = visit("scheduled", 3, owner=cls.other_sp)
        cls.last_year = visit("scheduled", 3, fy=str(int(cls.fy) - 1))
        # A visit handed to a partner is the partner's to execute, never the
        # officer's planned or completed visit.
        cls.partner_work = visit(
            "assigned_to_partner",
            5,
            delivery_type="partner",
            monitored_by_staff_id=cls.cceo_sp.id,
        )

    def _figures(self, user):
        figures = build_home(user)["figures"] + build_home_queue(user)["queue_figures"]
        return {f["key"]: f for f in figures}

    def test_each_open_activity_is_counted_in_exactly_one_figure(self):
        figures = self._figures(self.cceo)
        self.assertEqual(figures["upcoming"]["value"], 2)
        self.assertEqual(figures["under_way"]["value"], 2)
        self.assertEqual(figures["overdue"]["value"], 1)

    def test_figures_count_only_the_readers_own_plan(self):
        figures = self._figures(self.other)
        self.assertEqual(figures["upcoming"]["value"], 1)
        self.assertEqual(figures["under_way"]["value"], 0)
        self.assertEqual(figures["overdue"]["value"], 0)

    def test_each_figure_opens_the_my_plan_list_of_exactly_its_activities(self):
        self.client.force_login(self.cceo)
        expected = {
            "upcoming": {self.ahead, self.ahead_later},
            "under_way": {self.started, self.with_reviewer},
            "overdue": {self.passed},
        }
        everyone = {
            self.ahead,
            self.ahead_later,
            self.passed,
            self.started,
            self.with_reviewer,
            self.done,
            self.called_off,
            self.someone_elses,
            self.last_year,
            self.partner_work,
        }
        for key, figure in self._figures(self.cceo).items():
            if key not in expected:
                continue
            with self.subTest(figure=key):
                html = self.client.get(figure["url"]).content.decode()
                for activity in expected[key]:
                    self.assertIn(activity.id, html)
                for activity in everyone - expected[key]:
                    self.assertNotIn(activity.id, html)
                if key != "upcoming":
                    # The note that past-dated work is "not in the tables
                    # below" would be wrong on a list that holds it.
                    self.assertNotIn("data-my-plan-past-due", html)

    def test_upcoming_lists_the_next_dated_activities_soonest_first(self):
        upcoming = build_home(self.cceo)["upcoming"]
        self.assertEqual(
            [a["id"] for a in upcoming], [self.ahead.id, self.ahead_later.id]
        )
        self.assertEqual(upcoming[0]["where"], "Greenwood School")
        self.assertEqual(upcoming[0]["url"], f"/my-plan/{self.ahead.id}")

    def test_header_names_the_reader_and_role(self):
        home = build_home(self.cceo)
        self.assertEqual(home["first_name"], "Sarah")
        self.assertEqual(home["role_title"], "CCEO")


@override_settings(CACHES=LOCMEM)
class HomeRolesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hr, _ = _staff("home-hr@t.org", "Grace Hr", "Human Resources")
        cls.cceo, _ = _staff("home-cceo2@t.org", "Paul Field", "CCEO")

    def test_a_role_without_a_plan_gets_queue_figures_not_plan_zeros(self):
        home = build_home(self.hr)
        keys = [f["key"] for f in home["figures"]]
        self.assertEqual(keys, ["waiting_me", "due_today", "critical"])
        self.assertFalse(home["has_plan"])
        self.assertEqual(home["upcoming"], [])
        # Drawn as loading tiles, then filled from the queue.
        self.assertEqual({f["loading"] for f in home["figures"]}, {True})
        queue = build_home_queue(self.hr)["queue_figures"]
        self.assertEqual([f["value"] for f in queue], [0, 0, 0])

    def test_a_planner_with_no_work_sees_zeros_not_a_missing_figure(self):
        figures = build_home(self.cceo)["figures"][:3]
        figures += build_home_todo_figures(self.cceo)["queue_figures"]
        keys_values = {f["key"]: f["value"] for f in figures}
        self.assertEqual(
            keys_values,
            {"upcoming": 0, "under_way": 0, "overdue": 0, "waiting_me": 0},
        )

    def test_shortcuts_are_never_tabs_already_in_the_bar(self):
        from apps.core.navigation import build_mobile_nav_for_user

        user = self.hr
        bar = {i["url"] for i in build_mobile_nav_for_user(user, "/home")}
        shortcuts = {i["url"] for i in build_home(user)["shortcuts"]}
        self.assertTrue(shortcuts)
        self.assertFalse(bar & shortcuts)

    def test_a_cceo_and_a_lead_get_the_owners_four_shortcuts(self):
        # Owner, 2026-10-24: "Quick Access should be Dashboard, Cluster, My
        # Plan, Calendar" — My Plan too, although it is also a tab.
        lead, _ = _staff("home-pl@t.org", "Lena Lead", "Program Lead")
        for user in (self.cceo, lead):
            with self.subTest(role=user.active_role):
                self.assertEqual(
                    [s["page_key"] for s in build_home(user)["shortcuts"]],
                    ["dashboard", "clusters", "my_plan", "calendar"],
                )

    def test_home_page_renders_the_readers_sections(self):
        self.client.force_login(self.cceo)
        response = self.client.get("/home")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Today’s overview", html)
        self.assertIn("Priority actions", html)
        self.assertIn("Upcoming activities", html)
        self.assertIn('hx-get="/home/queue"', html)

    def test_queue_fragment_fills_priority_actions_and_the_todo_tile(self):
        # A role whose Priority actions are its To-Dos; a CCEO's are their
        # role's own list (test_home_priorities).
        self.client.force_login(self.hr)
        response = self.client.get("/home/queue")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('id="home-priority-body"', html)
        self.assertIn('data-home-empty="priority"', html)
        self.assertIn('id="home-figure-critical"', html)
        self.assertIn('hx-swap-oob="true"', html)
        self.assertNotIn("aria-busy", html)

    def test_home_page_leaves_out_the_plan_for_a_role_without_one(self):
        self.client.force_login(self.hr)
        html = self.client.get("/home").content.decode()
        self.assertNotIn("Upcoming activities", html)
        self.assertNotIn("/my-plan?status=", html)

    def test_phone_top_bar_keeps_messages_and_the_bell(self):
        # Both inboxes stay on the top bar on a phone, Home included, and
        # Messages is a bottom-bar tab as well (owner, 2026-10-21).
        import re

        self.client.force_login(self.cceo)
        for url in ("/home", "/todos"):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                for inbox in ("messages", "notifications"):
                    control = re.search(
                        rf'class="[^"]*edify-topbar__utility--{inbox}[^"]*"', html
                    )
                    self.assertNotIn("mobile-redundant", control.group(0))
                self.assertIn('class="edify-bottom-nav', html)

    def test_top_bar_shows_todays_date_and_week_on_every_load(self):
        # The second load answers the counts from the cache; the date went
        # missing on that path ("· Wk 43" with no date, 2026-10-21).
        from django.core.cache import cache

        today = timezone.localdate()
        expected = f"Today is {today:%A}, {today:%B} {today.day}, {today:%Y}, week {today.isocalendar()[1]}"
        self.client.force_login(self.cceo)
        cache.clear()
        with self.settings(IS_TESTING=False):
            for attempt in (1, 2):
                with self.subTest(load=attempt):
                    html = self.client.get("/todos").content.decode()
                    self.assertIn(expected, html)
                    self.assertIn('class="edify-topbar__when-week"', html)

    def test_home_can_be_restored_from_the_back_forward_cache(self):
        """Back to Home in the phone app restores it at once (2026-10-24):
        `no-store` kept it out of the back/forward cache, so every back
        rebuilt it. It is still never served from a cache without asking;
        a restored Home brings its rows up to date (partials/home/queue.html)."""
        self.client.force_login(self.cceo)
        header = self.client.get("/home")["Cache-Control"]
        self.assertIn("no-cache", header)
        self.assertIn("private", header)
        self.assertNotIn("no-store", header)
        queue = self.client.get("/home/queue")
        self.assertIn("no-store", queue["Cache-Control"])
        self.assertIn("pageshow[persisted] from:window", queue.content.decode())

    def test_signed_out_visitor_is_sent_to_sign_in(self):
        for url in ("/home", "/home/queue"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login", response["Location"])


def _todo(title, priority="high", **extra):
    return {
        "id": extra.pop("id", title),
        "title": title,
        "category": extra.pop("category", "Execution"),
        "priority": priority,
        "priority_label": priority.title(),
        "status_label": "Due Today",
        "status_tone": "warning",
        "due_label": "Today",
        "due_tone": "warning",
        "linked": "Greenwood School · School Visit",
        "action_label": "Complete",
        "action_url": "/activities/a1/complete",
        **extra,
    }


class PriorityActionsTest(SimpleTestCase):
    def test_rows_keep_the_queue_order_and_link_to_the_record(self):
        rows = priority_actions([_todo("Complete visit"), _todo("Upload SSA")])
        self.assertEqual([r["title"] for r in rows], ["Complete visit", "Upload SSA"])
        self.assertEqual(rows[0]["url"], "/activities/a1/complete")
        self.assertEqual(rows[0]["action_label"], "Complete")
        self.assertEqual(rows[0]["context"], "Greenwood School · School Visit")

    def test_identical_todos_are_one_row_with_their_count(self):
        todos = [
            _todo("Plan new school", id=f"p{i}", priority="medium") for i in range(4)
        ]
        rows = priority_actions([*todos, _todo("Complete visit")])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["count"], 4)
        self.assertEqual(rows[0]["url"], "/todos")

    def test_at_most_the_limit_is_shown(self):
        todos = [_todo(f"Task {i}") for i in range(9)]
        self.assertEqual(len(priority_actions(todos)), home_service.PRIORITY_LIMIT)

    def test_the_second_line_does_not_repeat_a_place_the_title_names(self):
        rows = priority_actions(
            [
                _todo(
                    "Schedule V1 Core Visit — Nakifuma School",
                    linked="Nakifuma School · Core Visit",
                )
            ]
        )
        self.assertEqual(rows[0]["context"], "Core Visit")
        rows = priority_actions(
            [
                _todo(
                    "Schedule Core Assessment — Nakifuma School",
                    linked="Nakifuma School",
                )
            ]
        )
        self.assertEqual(rows[0]["context"], "")

    def test_a_due_label_that_repeats_the_status_is_not_shown_twice(self):
        rows = priority_actions(
            [_todo("Complete", status_label="Overdue", due_label="Overdue")]
        )
        self.assertEqual(rows[0]["status_label"], "Overdue")
        self.assertEqual(rows[0]["due_label"], "")

    def test_a_todo_without_a_date_shows_no_due_label(self):
        rows = priority_actions([_todo("Review", due_label="—")])
        self.assertEqual(rows[0]["due_label"], "")


class GreetingTest(SimpleTestCase):
    def test_greeting_follows_the_local_hour(self):
        for hour, expected in (
            (0, "Good morning"),
            (11, "Good morning"),
            (12, "Good afternoon"),
            (16, "Good afternoon"),
            (17, "Good evening"),
            (23, "Good evening"),
        ):
            with self.subTest(hour=hour):
                self.assertEqual(greeting_for(datetime(2026, 10, 21, hour)), expected)
