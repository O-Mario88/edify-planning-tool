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
        # A line per page and task, longest first, each with its minutes;
        # "Viewing My Plan" beside "My Plan" reads "Viewing".
        self.assertEqual(
            [(r["section"], r["working_label"], r["label"]) for r in cara["rows"]],
            [
                ("My Plan", "Scheduling an activity", "25m"),
                ("My Plan", "Viewing", "10m"),
                ("Schools", "Viewing", "5m"),
            ],
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
        self.assertEqual(dan["period_time_label"], "0m")
        # One line all the same, reading "—".
        self.assertEqual([r["section"] for r in dan["rows"]], [""])
        self.assertEqual(dan["period_logins"], 0)
        self.assertEqual(dan["period_login_times"], [])


class WhosOnlineEndpointTest(TestCase):
    """Who's Online became the Staff Activity Log (owner, 2026-09-29). Its old
    address — an open tab's pager, a bookmark — goes to the log."""

    def test_the_old_address_goes_to_the_staff_activity_log(self):
        self.client.force_login(_user("clara", "CountryDirector"))
        response = self.client.get("/dashboard/whos-online")
        self.assertRedirects(response, "/staff-activity", fetch_redirect_response=False)
        fragment = self.client.get("/dashboard/whos-online", HTTP_HX_REQUEST="true")
        self.assertEqual(fragment["HX-Redirect"], "/staff-activity")


class TidyTableTest(TestCase):
    """Owner, 2026-09-28: "page accessed should be in their own column and
    doing what on that page on its own column" — Staff name, Title, # of
    logins, login day & date & time, page accessed, working on what, duration
    online, overall time; whoever is online highlighted green. Owner,
    2026-09-29: "NO Wrapping and everything should be accurate" — a line per
    page and task, every cell on one line."""

    def setUp(self):
        self.admin = _user("root", "Admin")
        self.cara = _user("cara")
        self.lead = _user("lena", "Program Lead")
        StaffSupervisorAssignment.objects.create(
            supervisor=self.lead.staff_profile, supervisee=self.cara.staff_profile
        )
        self.now = timezone.now()
        # The day of Cara's last beat, which is the day its minutes go to.
        day = timezone.localtime(self.now - timedelta(minutes=2)).date()
        self.on = day.isoformat()
        for section, task, seconds in (
            ("My Plan", "Scheduling an activity", 1500),
            ("Schools", "Viewing Schools", 600),
        ):
            PresenceTime.objects.create(
                user=self.cara,
                day=day,
                section=section,
                working_on=task,
                seconds=seconds,
            )
        LoginEvent.objects.create(user=self.cara, role="CCEO", at=_local(day, 0, 1))
        User.objects.filter(pk=self.cara.pk).update(
            last_seen_at=self.now - timedelta(minutes=2),
            online_since=self.now - timedelta(minutes=40),
            last_seen_path="/my-plan",
            last_seen_action="",
        )

    def _cara(self):
        summary = presence_summary(now=self.now, on=self.on)
        return next(
            p
            for g in summary["groups"]
            for p in ([g["lead"]] if g["lead"] else []) + g["members"]
            if p["id"] == self.cara.id
        )

    def test_a_line_per_page_and_task_the_page_they_are_on_first(self):
        cara = self._cara()
        # On My Plan now: its two minutes since the last beat lead, then the
        # day's other lines, longest first. Reading the page is "Viewing"
        # beside it, not the page said twice.
        self.assertEqual(
            [
                (r["section"], r["working_label"], r["label"], r["current"])
                for r in cara["rows"]
            ],
            [
                ("My Plan", "Viewing", "2m", True),
                ("My Plan", "Scheduling an activity", "25m", False),
                ("Schools", "Viewing", "10m", False),
            ],
        )
        self.assertEqual(cara["title"], "CCEO")
        # The sitting is the name's title; Overall is the lines added up.
        self.assertEqual(cara["duration_label"], "40m")
        self.assertEqual(cara["period_time_label"], "37m")

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


class EveryMinuteIsCountedTest(TestCase):
    """Owner, 2026-09-29: "I WANT IT TO CALCULATE sum up the oveall time for
    the whole day, whole week, whole month ... so that the filter can filter
    the right item with accurate time. do the same for duration. we want the
    actual calculation of how long a person spent doing what they are doing"."""

    def setUp(self):
        self.cara = _user("cara")
        self.lead = _user("lena", "Program Lead")
        StaffSupervisorAssignment.objects.create(
            supervisor=self.lead.staff_profile, supervisee=self.cara.staff_profile
        )
        self.rf = RequestFactory()

    def _record(self, user, day, section, task, seconds):
        PresenceTime.objects.create(
            user=user, day=day, section=section, working_on=task, seconds=seconds
        )

    def _read(self, user=None, **filters):
        user = user or self.cara
        summary = presence_summary(**filters)
        for group in summary["groups"]:
            for person in ([group["lead"]] if group["lead"] else []) + group["members"]:
                if person["id"] == user.id:
                    return summary, group, person
        raise AssertionError(f"{user.id} is not in the table")

    def _lines(self, person):
        return [(r["section"], r["working_label"], r["label"]) for r in person["rows"]]

    def _slots(self):
        return {
            (slot.day, slot.section, slot.working_on): slot.seconds
            for slot in PresenceTime.objects.filter(user=self.cara)
        }

    def test_a_task_s_duration_is_its_time_in_the_chosen_period(self):
        today = date(2026, 9, 30)  # a Wednesday
        monday = date(2026, 9, 28)
        self._record(self.cara, today, "My Plan", "Scheduling an activity", 1500)
        self._record(self.cara, monday, "My Plan", "Scheduling an activity", 1200)
        self._record(self.cara, monday, "Clusters", "Viewing Clusters", 600)
        self._record(self.cara, date(2026, 9, 3), "Schools", "Viewing Schools", 900)
        expected = {
            "day": ([("My Plan", "Scheduling an activity", "25m")], "25m"),
            "week": (
                [
                    ("My Plan", "Scheduling an activity", "45m"),
                    ("Clusters", "Viewing", "10m"),
                ],
                "55m",
            ),
            "month": (
                [
                    ("My Plan", "Scheduling an activity", "45m"),
                    ("Schools", "Viewing", "15m"),
                    ("Clusters", "Viewing", "10m"),
                ],
                "1h 10m",
            ),
        }
        for period, (lines, overall) in expected.items():
            with self.subTest(period=period):
                _, _, cara = self._read(
                    now=_local(today, 16), period=period, on=today.isoformat()
                )
                self.assertEqual(self._lines(cara), lines)
                self.assertEqual(cara["period_time_label"], overall)

    def test_the_durations_add_up_to_the_overall_time_as_shown(self):
        today = date(2026, 9, 30)
        self._record(self.cara, today, "My Plan", "Scheduling an activity", 1610)
        self._record(self.cara, today, "Field Debrief", "Writing a field debrief", 890)
        self._record(self.cara, today, "Schools", "Viewing Schools", 30)
        self._record(self.lead, today, "Dashboard", "Viewing Dashboard", 3599)
        summary, group, cara = self._read(now=_local(today, 16), on=today.isoformat())
        # 26m 50s, 14m 50s and 30s are 42m 10s: each line shows its minutes to
        # the one below or above, and together they are the 42m of Overall
        # (each on its own would read 26m + 14m = 40m beside 42m).
        self.assertEqual([r["label"] for r in cara["rows"]], ["27m", "15m", "<1m"])
        self.assertEqual(cara["period_time_label"], "42m")
        # The heading adds up its people as shown — Lena's 59m 59s reads 59m —
        # not their seconds, which would make 1h 42m over rows of 1h 41m.
        self.assertEqual(group["period_time_label"], "1h 41m")
        self.assertEqual(summary["period_time_label"], "1h 41m")

    def test_the_time_since_the_last_beat_counts_and_the_next_beat_keeps_it(self):
        beat = timezone.now() - timedelta(minutes=4)
        day = timezone.localtime(beat).date()
        self._record(self.cara, day, "My Plan", "Scheduling an activity", 1500)
        _seen(
            self.cara,
            ago=timedelta(minutes=4),
            path="/my-plan",
            action="POST /planning/schedule-action",
        )
        _, _, before = self._read(on=day.isoformat())
        # Online, on the task her last beat recorded: 25m on the record and
        # the four minutes since, which the next beat will write.
        self.assertTrue(before["online"])
        self.assertEqual(
            self._lines(before), [("My Plan", "Scheduling an activity", "29m")]
        )
        self.assertTrue(before["rows"][0]["current"])

        touch_presence(self.cara, self.rf.get("/clusters"))

        _, _, after = self._read(on=day.isoformat())
        scheduling = next(
            r for r in after["rows"] if r["working_on"] == "Scheduling an activity"
        )
        # The next beat wrote those minutes; the table read the same before.
        self.assertEqual(scheduling["label"], "29m")
        self.assertEqual(after["period_time_label"], "29m")
        self.assertEqual(after["rows"][0]["section"], "Clusters")

    def test_someone_who_has_left_carries_their_last_page_s_final_beat(self):
        beat = timezone.now() - timedelta(hours=2)
        day = timezone.localtime(beat).date()
        self._record(self.cara, day, "Clusters", "Viewing Clusters", 600)
        _seen(self.cara, ago=timedelta(hours=2), path="/clusters")
        _, _, cara = self._read(on=day.isoformat())
        self.assertFalse(cara["online"])
        self.assertEqual(
            [(r["section"], r["seconds"], r["current"]) for r in cara["rows"]],
            [("Clusters", 600 + FINAL_BEAT_SECONDS, True)],
        )

        # Signing in again writes that final beat instead of dropping it.
        from apps.accounts.presence import record_login

        record_login(self.rf.post("/login"), User.objects.get(pk=self.cara.pk))
        self.assertEqual(
            self._slots()[(day, "Clusters", "Viewing Clusters")],
            600 + FINAL_BEAT_SECONDS,
        )

    def test_a_day_gone_by_shows_that_day_s_lines_not_the_page_now(self):
        beat = timezone.now() - timedelta(minutes=1)
        earlier = timezone.localtime(beat).date() - timedelta(days=1)
        self._record(self.cara, earlier, "Clusters", "Viewing Clusters", 1200)
        _seen(self.cara, ago=timedelta(minutes=1), path="/my-plan")
        _, _, cara = self._read(on=earlier.isoformat())
        self.assertTrue(cara["online"])
        self.assertEqual(self._lines(cara), [("Clusters", "Viewing", "20m")])
        self.assertEqual(cara["period_time_label"], "20m")

    def test_signing_in_leaves_the_person_on_the_dashboard(self):
        """The sign-in's own POST replaced the Dashboard record_login wrote,
        so the minutes after every sign-in went to "Sign-in · Signing in"."""
        import uuid

        self.cara.set_password("Secret-1!")
        self.cara.save()
        _seen(self.cara, ago=timedelta(hours=2), path="/clusters")
        beat_day = timezone.localtime(self.cara.last_seen_at).date()
        # The sign-in route is throttled per client address.
        self.client.defaults["REMOTE_ADDR"] = "10.%d.%d.%d" % tuple(
            uuid.uuid4().bytes[:3]
        )
        response = self.client.post(
            "/login", {"email": self.cara.email, "password": "Secret-1!"}
        )
        self.assertEqual(response.status_code, 302)
        self.cara.refresh_from_db()
        self.assertEqual(
            (self.cara.last_seen_path, self.cara.last_seen_action), ("/dashboard", "")
        )
        # The last sitting's final beat is on the page it ended on.
        self.assertEqual(
            self._slots(),
            {(beat_day, "Clusters", "Viewing Clusters"): FINAL_BEAT_SECONDS},
        )
        # The next beat credits the Dashboard, and nothing is ever "Sign-in".
        User.objects.filter(pk=self.cara.pk).update(
            last_seen_at=timezone.now() - timedelta(minutes=3)
        )
        touch_presence(User.objects.get(pk=self.cara.pk), self.rf.get("/my-plan"))
        sections = {section for _day, section, _task in self._slots()}
        self.assertEqual(sections, {"Clusters", "Dashboard"})

    def test_signing_in_and_out_are_not_pages(self):
        from apps.accounts.presence import is_untracked_path, request_footprint

        for path in ("/login", "/login/verify", "/login/resend-code", "/logout"):
            with self.subTest(path=path):
                self.assertTrue(is_untracked_path(path))
                self.assertIsNone(request_footprint(self.rf.post(path)))

    def test_the_migration_gives_sign_in_minutes_to_the_dashboard(self):
        import importlib

        from django.apps import apps

        today = timezone.localdate()
        before = today - timedelta(days=1)
        self._record(self.cara, today, "Sign-in", "Signing in", 90)
        self._record(self.cara, today, "Sign-in", "Verifying work", 30)
        self._record(self.cara, today, "Dashboard", "Viewing Dashboard", 600)
        self._record(self.cara, before, "Sign-in", "Signing in", 45)
        _seen(self.cara, ago=timedelta(minutes=1), path="/login", action="POST /login")
        _seen(self.lead, ago=timedelta(minutes=1), path="/login/verify")

        importlib.import_module(
            "apps.accounts.migrations.0034_sign_in_minutes_belong_to_the_dashboard"
        ).move(apps, None)

        self.assertEqual(
            self._slots(),
            {
                (today, "Dashboard", "Viewing Dashboard"): 720,
                (before, "Dashboard", "Viewing Dashboard"): 45,
            },
        )
        for person in (self.cara, self.lead):
            person.refresh_from_db()
            self.assertEqual(
                (person.last_seen_path, person.last_seen_action), ("/dashboard", "")
            )
