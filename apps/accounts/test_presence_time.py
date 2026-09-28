"""Who's Online keeps a record of time (owner, 2026-09-28).

"On who is online table, duration column should show a record of how long the
user spend on the planning tool. Which part of the tool they accessed and for
how long - Working on What should be clear. How many times they logged in.
When they logged in. Add the filter of day, week, month, quarter and FY."

Asked about the Staff Time Standard's rule against showing a named person's
minutes, the owner chose to show them here, to the Admin, the Country Director
and each Programme Lead for their own team.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.accounts.models import (
    LoginEvent,
    PresenceTime,
    StaffProfile,
    StaffSupervisorAssignment,
)
from apps.accounts.presence import (
    FINAL_BEAT_SECONDS,
    ONLINE_WINDOW,
    credit_presence_time,
    format_minutes,
    presence_period,
    presence_summary,
    touch_presence,
)

User = get_user_model()


def _user(uid, role="CCEO"):
    user = User.objects.create(
        id=uid,
        email=f"{uid}@edify.org",
        name=uid.title(),
        roles=[role],
        active_role=role,
        is_active=True,
    )
    StaffProfile.objects.create(id=f"{uid}-sp", user=user, title=role, country="Uganda")
    return user


def _local(day: date, hour: int, minute: int = 0):
    return timezone.make_aware(
        datetime(day.year, day.month, day.day, hour, minute),
        timezone.get_current_timezone(),
    )


def _seen(user, *, ago: timedelta, path="/my-plan", action=""):
    """The beat the person's last request left, in the database and on the
    object the next request loads."""
    at = timezone.now() - ago
    User.objects.filter(pk=user.pk).update(
        last_seen_at=at, online_since=at, last_seen_path=path, last_seen_action=action
    )
    user.refresh_from_db()
    return at


class TimeIsCreditedBetweenBeatsTest(TestCase):
    def setUp(self):
        self.cara = _user("cara")
        self.rf = RequestFactory()

    def _slots(self):
        return {
            (slot.section, slot.working_on): slot.seconds
            for slot in PresenceTime.objects.filter(user=self.cara)
        }

    def test_the_minutes_since_the_last_beat_go_to_the_page_it_was_on(self):
        _seen(self.cara, ago=timedelta(minutes=3))
        touch_presence(self.cara, self.rf.get("/schools"))
        seconds = self._slots()[("My Plan", "Viewing My Plan")]
        self.assertGreaterEqual(seconds, 179)
        self.assertLessEqual(seconds, 185)
        # The new beat is the schools page, which has earned nothing yet.
        self.assertNotIn(("Schools", "Viewing Schools"), self._slots())

    def test_the_task_is_the_action_the_beat_recorded(self):
        _seen(
            self.cara,
            ago=timedelta(minutes=2),
            path="/planning",
            action="POST /planning/schedule-action",
        )
        touch_presence(self.cara, self.rf.get("/planning"))
        self.assertIn(("Planning", "Scheduling an activity"), self._slots())

    def test_a_gap_past_the_online_window_earns_only_the_final_credit(self):
        # The tab was left open and the person went home: the hours between
        # are not time on the tool, only the last page read.
        _seen(self.cara, ago=ONLINE_WINDOW + timedelta(hours=3))
        touch_presence(self.cara, self.rf.get("/dashboard"))
        self.assertEqual(
            self._slots(), {("My Plan", "Viewing My Plan"): FINAL_BEAT_SECONDS}
        )

    def test_repeated_beats_add_up_in_one_record_per_day_part_and_task(self):
        for _ in range(3):
            _seen(self.cara, ago=timedelta(minutes=1))
            touch_presence(self.cara, self.rf.get("/my-plan"))
        self.assertEqual(PresenceTime.objects.filter(user=self.cara).count(), 1)
        self.assertGreaterEqual(self._slots()[("My Plan", "Viewing My Plan")], 179)

    def test_two_requests_on_one_beat_credit_it_once(self):
        _seen(self.cara, ago=timedelta(minutes=4))
        # Both requests loaded the person before either wrote.
        first = User.objects.get(pk=self.cara.pk)
        second = User.objects.get(pk=self.cara.pk)
        touch_presence(first, self.rf.get("/schools"))
        touch_presence(second, self.rf.get("/clusters"))
        seconds = self._slots()[("My Plan", "Viewing My Plan")]
        self.assertLessEqual(seconds, 245)
        second.refresh_from_db()
        # The second request still moved the presence on.
        self.assertEqual(second.last_seen_path, "/clusters")

    def test_the_first_beat_after_a_sign_in_starts_from_the_sign_in(self):
        # Nothing seen before: nothing to credit, and nothing breaks.
        touch_presence(self.cara, self.rf.get("/dashboard"))
        self.assertEqual(PresenceTime.objects.count(), 0)

    def test_a_signed_in_session_records_time_through_the_middleware(self):
        self.client.force_login(self.cara)
        _seen(self.cara, ago=timedelta(minutes=2), path="/clusters")
        self.client.get("/dashboard")
        self.assertIn(("Clusters", "Viewing Clusters"), self._slots())

    def test_a_page_stored_on_the_service_worker_is_credited_to_no_part(self):
        """Production, 2026-09-29: the page stored before the service worker
        was left out was "/sw.js", and the next beat credited its minutes to
        a part of the tool called "Sw.Js"."""
        self.client.force_login(self.cara)
        _seen(self.cara, ago=timedelta(minutes=2), path="/sw.js")
        self.client.get("/dashboard")
        self.assertEqual(self._slots(), {})
        self.cara.refresh_from_db()
        self.assertEqual(self.cara.last_seen_path, "/dashboard")

    def test_the_defect_beacon_is_not_what_the_person_was_doing(self):
        """The page posts the beacon on its own when a script throws; it read
        as "Viewing Support · client defect" and took the next minutes."""
        self.client.force_login(self.cara)
        _seen(self.cara, ago=timedelta(minutes=2), path="/planning")
        self.client.post(
            "/support/client-defect",
            data='{"kind": "js_error", "route": "/planning", "component": "table"}',
            content_type="application/json",
        )
        self.cara.refresh_from_db()
        self.assertEqual(self.cara.last_seen_path, "/planning")
        self.assertIn(("Planning", "Viewing Planning"), self._slots())
        self.assertNotIn("Support", {section for section, _task in self._slots()})

    def test_no_part_of_the_tool_is_ever_the_browser_s_machinery(self):
        for path in ("/sw.js", "/manifest.webmanifest", "/support/client-defect"):
            with self.subTest(path=path):
                credit_presence_time(self.cara.pk, timezone.now(), path, "", seconds=60)
        self.assertEqual(PresenceTime.objects.count(), 0)

    def test_a_page_stored_on_the_service_worker_reads_as_no_page(self):
        _seen(self.cara, ago=timedelta(minutes=1), path="/sw.js")
        cara = next(
            person
            for group in presence_summary()["groups"]
            for person in [group.get("lead"), *group["members"]]
            if person and person["id"] == self.cara.id
        )
        self.assertEqual((cara["section"], cara["working_on"]), ("—", "—"))

    def test_the_migration_forgets_the_machinery_already_recorded(self):
        import importlib

        from django.apps import apps

        _seen(self.cara, ago=timedelta(minutes=1), path="/sw.js")
        today = timezone.localdate()
        for section, task in (
            ("Sw.Js", "Viewing Sw.Js"),
            ("Support", "Viewing Support · client defect"),
            ("Planning", "Viewing Planning"),
        ):
            PresenceTime.objects.create(
                user=self.cara, day=today, section=section, working_on=task, seconds=120
            )

        importlib.import_module(
            "apps.accounts.migrations.0033_forget_browser_machinery_presence"
        ).forget(apps, None)

        self.assertEqual(self._slots(), {("Planning", "Viewing Planning"): 120})
        self.cara.refresh_from_db()
        self.assertEqual(self.cara.last_seen_path, "")

    def test_the_credit_lands_on_the_day_of_the_beat(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        credit_presence_time(
            self.cara.pk, _local(yesterday, 23, 58), "/schools", "", seconds=90
        )
        slot = PresenceTime.objects.get(user=self.cara)
        self.assertEqual(slot.day, yesterday)
        self.assertEqual(slot.seconds, 90)


class PeriodsTest(TestCase):
    def test_each_period_is_its_run_of_days(self):
        monday = date(2026, 9, 28)
        cases = {
            "day": (monday, monday),
            "week": (date(2026, 9, 28), date(2026, 10, 4)),
            "month": (date(2026, 9, 1), date(2026, 9, 30)),
            "quarter": (date(2026, 7, 1), date(2026, 9, 30)),
            "fy": (date(2025, 10, 1), date(2026, 9, 30)),
        }
        for key, (start, end) in cases.items():
            with self.subTest(period=key):
                period = presence_period(key, monday, today=monday)
                self.assertEqual((period["start"], period["end"]), (start, end))

    def test_quarters_and_years_are_the_operational_ones(self):
        november = date(2025, 11, 14)
        quarter = presence_period("quarter", november, today=november)
        self.assertEqual(
            (quarter["start"], quarter["end"]), (date(2025, 10, 1), date(2025, 12, 31))
        )
        self.assertTrue(quarter["label"].startswith("Q1 FY2026"))
        self.assertTrue(
            presence_period("fy", november, today=november)["label"].startswith(
                "FY2026"
            )
        )

    def test_a_week_across_the_year_names_both_years(self):
        period = presence_period("week", date(2026, 12, 30), today=date(2026, 12, 30))
        self.assertEqual(period["label"], "week of 28 Dec 2026 – 3 Jan 2027")

    def test_unknown_input_falls_back_to_today(self):
        today = date(2026, 9, 28)
        period = presence_period("decade", "not-a-date", today=today)
        self.assertEqual((period["key"], period["start"]), ("day", today))
        self.assertTrue(period["is_default"])
        self.assertEqual(period["label"], "today")

    def test_minutes_read_as_hours_and_minutes(self):
        self.assertEqual(format_minutes(0), "0m")
        self.assertEqual(format_minutes(45), "<1m")
        self.assertEqual(format_minutes(25 * 60), "25m")
        self.assertEqual(format_minutes(3 * 3600 + 5 * 60), "3h 05m")
        # A year's hours stay hours.
        self.assertEqual(format_minutes(130 * 3600), "130h 00m")


class SummaryForAPeriodTest(TestCase):
    """The record the table reads: time, parts and tasks with their minutes,
    and the sign-ins — each inside the chosen period and nowhere else."""

    def setUp(self):
        self.cara = _user("cara")
        self.dan = _user("dan")
        self.today = date(2026, 9, 30)  # a Wednesday
        self.now = _local(self.today, 16)
        rows = [
            (self.today, "My Plan", "Scheduling an activity", 1500),
            (self.today, "My Plan", "Viewing My Plan", 600),
            (self.today, "Schools", "Viewing Schools", 300),
            (self.today - timedelta(days=2), "Clusters", "Viewing Clusters", 1200),
            (self.today - timedelta(days=20), "Dashboard", "Viewing Dashboard", 900),
            (date(2025, 9, 10), "Dashboard", "Viewing Dashboard", 5000),  # FY2025
        ]
        for day, section, task, seconds in rows:
            PresenceTime.objects.create(
                user=self.cara,
                day=day,
                section=section,
                working_on=task,
                seconds=seconds,
            )
        for day, hour in (
            (self.today, 8),
            (self.today, 13),
            (self.today - timedelta(days=2), 9),
            (self.today - timedelta(days=20), 10),
        ):
            LoginEvent.objects.create(
                user=self.cara, role="CCEO", at=_local(day, hour, 15)
            )

    def _cara(self, **filters):
        summary = presence_summary(now=self.now, **filters)
        return summary, next(
            person
            for group in summary["groups"]
            for person in group["members"]
            if person["id"] == self.cara.id
        )

    def test_a_day_holds_that_day_only(self):
        summary, cara = self._cara()
        self.assertEqual(summary["period"]["key"], "day")
        self.assertEqual(cara["period_seconds"], 2400)
        self.assertEqual(cara["period_time_label"], "40m")
        # Parts, biggest first, each with its tasks and minutes.
        self.assertEqual(
            [(p["section"], p["label"]) for p in cara["period_sections"]],
            [("My Plan", "35m"), ("Schools", "5m")],
        )
        self.assertEqual(
            [
                (t["working_on"], t["label"])
                for t in cara["period_sections"][0]["tasks"]
            ],
            [("Scheduling an activity", "25m"), ("Viewing My Plan", "10m")],
        )
        self.assertEqual(
            cara["period_tasks"][0]["working_on"], "Scheduling an activity"
        )
        # Sign-ins: how many and when, latest first.
        self.assertEqual(cara["period_logins"], 2)
        self.assertEqual(
            [timezone.localtime(at).hour for at in cara["period_login_times"]], [13, 8]
        )
        self.assertEqual(cara["period_last_login_label"], "13:15")

    def test_a_week_month_quarter_and_year_widen_the_record(self):
        expected = {
            "week": (3600, 3),
            "month": (4500, 4),
            "quarter": (4500, 4),
            "fy": (4500, 4),
        }
        for key, (seconds, logins) in expected.items():
            with self.subTest(period=key):
                _, cara = self._cara(period=key, on=self.today.isoformat())
                self.assertEqual(cara["period_seconds"], seconds)
                self.assertEqual(cara["period_logins"], logins)

    def test_another_day_can_be_chosen(self):
        _, cara = self._cara(on=(self.today - timedelta(days=2)).isoformat())
        self.assertEqual(cara["period_seconds"], 1200)
        self.assertEqual(cara["period_logins"], 1)
        # Not today, so the day is written before the time.
        self.assertEqual(cara["period_last_login_label"], "28/09 09:15")

    def test_the_earlier_year_is_its_own(self):
        _, cara = self._cara(period="fy", on="2025-09-10")
        self.assertEqual(cara["period_seconds"], 5000)

    def test_the_panel_totals_the_period(self):
        summary, _ = self._cara(period="week", on=self.today.isoformat())
        self.assertEqual(summary["period_seconds"], 3600)
        self.assertEqual(summary["period_logins"], 3)
        group = next(g for g in summary["groups"] if g["members"])
        self.assertEqual(group["period_time_label"], "1h 00m")

    def test_someone_with_no_time_carries_zeroes(self):
        summary = presence_summary(now=self.now, period="month")
        dan = next(
            p for g in summary["groups"] for p in g["members"] if p["id"] == self.dan.id
        )
        self.assertEqual(dan["period_seconds"], 0)
        self.assertEqual(dan["period_sections"], [])
        self.assertEqual(dan["period_logins"], 0)
        self.assertEqual(dan["period_login_times"], [])


class WhosOnlineEndpointTest(TestCase):
    """The filter and the pager fetch the panel alone; its readers are the
    Admin and the Country Director (the country) and a Programme Lead (their
    own reporting line)."""

    def setUp(self):
        self.admin = _user("root", "Admin")
        self.director = _user("clara", "CountryDirector")
        self.lead = _user("lena", "Program Lead")
        self.mine = _user("mina")
        self.other_lead = _user("olive", "Program Lead")
        self.theirs = _user("otto")
        StaffSupervisorAssignment.objects.create(
            supervisor=self.lead.staff_profile, supervisee=self.mine.staff_profile
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.other_lead.staff_profile,
            supervisee=self.theirs.staff_profile,
        )
        today = timezone.localdate()
        for person in (self.mine, self.theirs):
            PresenceTime.objects.create(
                user=person,
                day=today,
                section="My Plan",
                working_on="Scheduling an activity",
                seconds=1500,
            )
            LoginEvent.objects.create(user=person, role="CCEO")

    def _get(self, user, query=""):
        self.client.force_login(user)
        return self.client.get(f"/dashboard/whos-online{query}", HTTP_HX_REQUEST="true")

    def test_the_admin_reads_the_country_with_links_to_each_record(self):
        response = self._get(self.admin)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Mina", html)
        self.assertIn("Otto", html)
        self.assertIn(f'href="/admin-panel/users/{self.mine.id}"', html)
        # The panel alone: the host it swaps into is the page's.
        self.assertNotIn('class="presence-host"', html)
        self.assertIn("data-admin-presence", html)

    def test_the_country_director_reads_the_country_without_links(self):
        html = self._get(self.director).content.decode()
        self.assertIn("Mina", html)
        self.assertIn("Otto", html)
        self.assertNotIn("/admin-panel/users/", html)

    def test_a_programme_lead_reads_their_own_team_only(self):
        html = self._get(self.lead).content.decode()
        self.assertIn("Mina", html)
        self.assertNotIn("Otto", html)
        self.assertIn("in your team", html)

    def test_other_roles_are_refused(self):
        self.assertEqual(self._get(self.mine).status_code, 403)

    def test_the_period_is_the_one_asked_for(self):
        month = timezone.localdate().strftime("%B %Y")
        html = self._get(self.admin, "?presence_period=month").content.decode()
        self.assertIn(f"{month}:", html)
        self.assertIn('<option value="month" selected>', html)
        # Every sign-in time and each part's minutes sit in the person's detail.
        self.assertIn('class="presence-detail"', html)
        self.assertIn("Scheduling an activity <b>25m</b>", html)
        self.assertIn("My Plan <b>25m</b>", html)

    def test_every_detail_is_shown_and_nothing_folds(self):
        """Owner, 2026-09-29: "everything should be visible"."""
        html = self._get(self.lead, "?presence_period=month").content.decode()
        self.assertIn('<tr class="edify-group-head">', html)
        self.assertNotIn("aria-expanded", html)
        self.assertIn(
            f'<tr class="presence-detail" id="presence-person-{self.mine.id}">', html
        )
        self.assertIn("Scheduling an activity <b>25m</b>", html)

    def test_the_dashboard_panel_is_a_fragment_host_for_the_pager(self):
        self.client.force_login(self.admin)
        html = self.client.get("/dashboard?view=operations").content.decode()
        self.assertIn('data-pager-fragment="/dashboard/whos-online"', html)
        self.assertIn('hx-get="/dashboard/whos-online"', html)


class TidyTableTest(TestCase):
    """Owner, 2026-09-28: "page accessed should be in their own column and
    doing what on that page on its own column" — Staff name, Title, # of
    logins, login day & date & time, page accessed, working on what, duration
    online, other parts accessed with their time, overall time; whoever is
    online highlighted green across the whole row."""

    def setUp(self):
        self.admin = _user("root", "Admin")
        self.cara = _user("cara")
        self.lead = _user("lena", "Program Lead")
        StaffSupervisorAssignment.objects.create(
            supervisor=self.lead.staff_profile, supervisee=self.cara.staff_profile
        )
        today = timezone.localdate()
        for section, task, seconds in (
            ("My Plan", "Scheduling an activity", 1500),
            ("Schools", "Viewing Schools", 600),
        ):
            PresenceTime.objects.create(
                user=self.cara,
                day=today,
                section=section,
                working_on=task,
                seconds=seconds,
            )
        LoginEvent.objects.create(user=self.cara, role="CCEO", at=_local(today, 8, 5))
        User.objects.filter(pk=self.cara.pk).update(
            last_seen_at=timezone.now(),
            online_since=timezone.now() - timedelta(minutes=40),
            last_seen_path="/my-plan",
            last_seen_action="",
        )

    def _cara(self):
        summary = presence_summary()
        return next(
            p
            for g in summary["groups"]
            for p in ([g["lead"]] if g["lead"] else []) + g["members"]
            if p["id"] == self.cara.id
        )

    def test_the_page_and_what_is_done_on_it_are_two_columns(self):
        cara = self._cara()
        self.assertEqual(cara["section"], "My Plan")
        # Reading the page is "Viewing" beside it, not the page said twice.
        self.assertEqual(cara["working_label"], "Viewing")
        # Other parts: every part but the page they are on, with its time.
        self.assertEqual(
            [(p["section"], p["label"]) for p in cara["other_sections"]],
            [("Schools", "10m")],
        )
        self.assertEqual(cara["title"], "CCEO")
        self.assertEqual(cara["duration_label"], "40m")
        self.assertEqual(cara["period_time_label"], "35m")

    def test_the_row_reads_in_the_owner_s_order_and_online_is_green(self):
        self.client.force_login(self.admin)
        html = self.client.get(
            "/dashboard/whos-online", HTTP_HX_REQUEST="true"
        ).content.decode()
        row = html.split(f'data-presence-person="presence-person-{self.cara.id}"')[0]
        row = html[len(row) :].split("</tr>")[0]
        # Online: the whole row is marked, and the light sits in the name.
        self.assertIn('<tr class="presence-row" data-presence="online"', html)
        self.assertIn("admin-presence-light--online", row)
        cells = [
            "Cara",
            ">CCEO<",
            ">1</a>",
            f"{timezone.localdate().strftime('%a').upper()} ",
            "My Plan",
            ">Viewing<",
            "40m",
            "Schools <b>10m</b>",
            "<b>35m</b>",
        ]
        positions = [row.index(cell) for cell in cells]
        self.assertEqual(positions, sorted(positions))
        # A lead's title is the short one, PL.
        self.assertIn(">PL<", html)

    def test_the_service_worker_is_not_a_part_of_the_tool(self):
        from apps.accounts.presence import request_footprint

        rf = RequestFactory()
        for path in ("/sw.js", "/manifest.webmanifest", "/robots.txt", "/app.js.map"):
            with self.subTest(path=path):
                self.assertIsNone(request_footprint(rf.get(path)))
        self.assertEqual(request_footprint(rf.get("/my-plan"))[0], "/my-plan")

    def test_a_role_without_a_plural_label_reads_as_words(self):
        _user("bea", "BusinessTransformationOfficer")
        labels = [g["label"] for g in presence_summary()["groups"]]
        self.assertIn("Business Transformation Officer", labels)
