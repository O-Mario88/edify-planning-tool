"""Who is online, and how many signed in (owner, 2026-09-12).

"The admin should also be able to see who is online. The number of logins
per day, per week."
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.accounts.models import LoginEvent, StaffProfile, StaffSupervisorAssignment
from apps.accounts.presence import (
    ONLINE_WINDOW,
    format_duration,
    presence_summary,
    record_login,
    request_footprint,
    touch_presence,
)
from apps.accounts.presence_labels import activity_for, section_for

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


class PresenceServiceTest(TestCase):
    def setUp(self):
        self.anna = _user("anna")
        self.ben = _user("ben", "Program Lead")
        self.rf = RequestFactory()

    def test_a_sign_in_is_recorded_with_its_role_and_address(self):
        request = self.rf.post(
            "/login",
            HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.1",
            HTTP_USER_AGENT="Edify/1",
        )
        record_login(request, self.anna)
        event = LoginEvent.objects.get(user=self.anna)
        self.assertEqual(event.role, "CCEO")
        self.assertEqual(event.ip, "203.0.113.9")
        self.assertEqual(event.user_agent, "Edify/1")
        self.anna.refresh_from_db()
        self.assertIsNotNone(self.anna.last_seen_at)

    def test_online_means_seen_within_the_window(self):
        now = timezone.now()
        User.objects.filter(pk=self.anna.pk).update(
            last_seen_at=now - timedelta(minutes=3)
        )
        User.objects.filter(pk=self.ben.pk).update(
            last_seen_at=now - ONLINE_WINDOW - timedelta(minutes=1)
        )
        summary = presence_summary(now=now)
        self.assertEqual([p["name"] for p in summary["online"]], ["Anna"])
        self.assertEqual(summary["online_count"], 1)
        self.assertTrue(summary["online"][0]["online"])

    def test_everyone_else_is_listed_as_offline_most_recent_first(self):
        now = timezone.now()
        cara = _user("cara")
        dan = _user("dan")  # never signed in
        User.objects.filter(pk=self.anna.pk).update(
            last_seen_at=now - timedelta(minutes=3)
        )
        User.objects.filter(pk=self.ben.pk).update(last_seen_at=now - timedelta(days=2))
        User.objects.filter(pk=cara.pk).update(last_seen_at=now - timedelta(hours=1))
        summary = presence_summary(now=now)
        self.assertEqual([p["name"] for p in summary["online"]], ["Anna"])
        self.assertEqual(
            [p["name"] for p in summary["offline"]], ["Cara", "Ben", "Dan"]
        )
        self.assertEqual(summary["offline_count"], 3)
        self.assertFalse(summary["offline"][0]["online"])
        self.assertIsNone(summary["offline"][-1]["last_seen_at"])
        # A deactivated or deleted account is nobody's colleague any more.
        User.objects.filter(pk=dan.pk).update(is_active=False)
        summary = presence_summary(now=now)
        self.assertEqual([p["name"] for p in summary["offline"]], ["Cara", "Ben"])

    def test_logins_are_counted_per_day_and_per_week(self):
        now = timezone.now()
        local_today = timezone.localtime(now).date()
        for days_ago in (0, 0, 1, 8, 20):
            LoginEvent.objects.create(
                user=self.anna, at=now - timedelta(days=days_ago), role="CCEO"
            )
        summary = presence_summary(now=now)
        self.assertEqual(summary["logins_today"], 2)
        self.assertEqual(summary["logins_last_7_days"], 3)
        self.assertEqual(len(summary["daily"]), 14)
        self.assertEqual(summary["daily"][-1]["date"], local_today)
        self.assertEqual(summary["daily"][-1]["count"], 2)
        self.assertEqual(summary["daily"][-2]["count"], 1)
        self.assertEqual(len(summary["weekly"]), 8)
        self.assertEqual(sum(w["count"] for w in summary["weekly"]), 5)
        self.assertGreaterEqual(summary["logins_this_week"], 2)

    def test_a_malformed_address_never_breaks_the_sign_in(self):
        request = self.rf.post("/login", REMOTE_ADDR="2001:db8::a237098e4ed6691c")
        record_login(request, self.anna)  # must not raise
        event = LoginEvent.objects.get(user=self.anna)
        self.assertIsNone(event.ip)
        request = self.rf.post(
            "/login", HTTP_X_FORWARDED_FOR="not-an-address", REMOTE_ADDR="10.1.2.3"
        )
        record_login(request, self.ben)
        self.assertIsNone(LoginEvent.objects.get(user=self.ben).ip)

    def test_touch_marks_the_person_seen(self):
        touch_presence(self.ben)
        self.ben.refresh_from_db()
        self.assertLess(timezone.now() - self.ben.last_seen_at, timedelta(seconds=5))

    def test_a_touch_starts_a_sitting_and_a_gap_starts_a_new_one(self):
        now = timezone.now()
        touch_presence(self.ben)
        self.ben.refresh_from_db()
        first_since = self.ben.online_since
        self.assertIsNotNone(first_since)
        # A beat within the window keeps the sitting.
        touch_presence(self.ben)
        self.ben.refresh_from_db()
        self.assertEqual(self.ben.online_since, first_since)
        # A gap longer than the window is a new sitting.
        User.objects.filter(pk=self.ben.pk).update(
            last_seen_at=now - ONLINE_WINDOW - timedelta(minutes=5)
        )
        touch_presence(self.ben)
        self.ben.refresh_from_db()
        self.assertGreater(self.ben.online_since, first_since)

    def test_a_touch_records_the_page_and_the_action(self):
        request = self.rf.get("/planning?tab=client")
        touch_presence(self.ben, request)
        self.ben.refresh_from_db()
        self.assertEqual(self.ben.last_seen_path, "/planning")
        self.assertEqual(self.ben.last_seen_action, "")
        # A drawer opened over htmx: the page is where the person is, the
        # action is what they opened.
        request = self.rf.get(
            "/planning/schedule-modal?school_id=S-1",
            HTTP_HX_REQUEST="true",
            HTTP_HX_CURRENT_URL="https://edify.test/planning?tab=client",
        )
        touch_presence(self.ben, request)
        self.ben.refresh_from_db()
        self.assertEqual(self.ben.last_seen_path, "/planning")
        self.assertEqual(self.ben.last_seen_action, "GET /planning/schedule-modal")
        # A write on the page.
        request = self.rf.post("/planning/schedule-action")
        touch_presence(self.ben, request)
        self.ben.refresh_from_db()
        self.assertEqual(self.ben.last_seen_action, "POST /planning/schedule-action")
        # Machinery is not a page.
        self.assertIsNone(request_footprint(self.rf.get("/api/realtime/stream")))

    def test_paths_read_as_a_section_and_an_activity(self):
        self.assertEqual(section_for("/planning?tab=client"), "Planning")
        self.assertEqual(section_for("/my-plan"), "My Plan")
        self.assertEqual(section_for("/clusters/cmsaketxn00h3gvfkdf4u"), "Clusters")
        self.assertEqual(section_for("/core-schools"), "Core Schools")
        self.assertEqual(section_for("/"), "Dashboard")
        self.assertEqual(
            activity_for("/planning", "POST /planning/schedule-action"),
            "Scheduling an activity",
        )
        self.assertEqual(
            activity_for("/schools", "GET /schools/abc/add-to-cluster"),
            "Adding schools to a cluster",
        )
        self.assertEqual(
            activity_for("/clusters/cmsaketxn00h3gvfkdf4u"), "Viewing a cluster record"
        )
        self.assertEqual(activity_for("/my-plan"), "Viewing My Plan")

    def test_durations_read_as_people_say_them(self):
        self.assertEqual(format_duration(10), "just now")
        self.assertEqual(format_duration(50), "<1m")
        self.assertEqual(format_duration(12 * 60), "12m")
        self.assertEqual(format_duration(65 * 60), "1h 05m")
        self.assertEqual(format_duration(27 * 3600), "1d 3h")
        self.assertEqual(format_duration(None), "—")

    def test_the_table_folds_cceos_under_their_program_lead(self):
        now = timezone.now()
        pl = _user("paula", "Program Lead")
        StaffSupervisorAssignment.objects.create(
            supervisor=pl.staff_profile, supervisee=self.anna.staff_profile
        )
        cd = _user("dan", "CountryDirector")
        _user("eve")  # a CCEO nobody leads yet
        User.objects.filter(pk=self.anna.pk).update(
            last_seen_at=now - timedelta(minutes=2),
            online_since=now - timedelta(minutes=47),
            last_seen_path="/planning",
            last_seen_action="POST /planning/schedule-action",
        )
        User.objects.filter(pk=pl.pk).update(
            last_seen_at=now - timedelta(days=1),
            online_since=now - timedelta(days=1, minutes=30),
            last_seen_path="/team-planning-oversight/",
        )
        summary = presence_summary(now=now)
        groups = {g["key"]: g for g in summary["groups"]}
        paula = groups[f"pl:{pl.id}"]
        self.assertEqual(paula["kind"], "program_lead")
        self.assertEqual(paula["lead"]["name"], "Paula")
        self.assertEqual([p["name"] for p in paula["members"]], ["Anna"])
        self.assertEqual((paula["online"], paula["total"]), (1, 2))
        self.assertTrue(paula["open"])
        anna = paula["members"][0]
        self.assertTrue(anna["online"])
        self.assertEqual(anna["duration_label"], "47m")
        self.assertEqual(anna["section"], "Planning")
        self.assertEqual(anna["working_on"], "Scheduling an activity")
        # Paula's last sitting, and where she was.
        self.assertFalse(paula["lead"]["online"])
        self.assertEqual(paula["lead"]["duration_label"], "30m")
        self.assertEqual(paula["lead"]["section"], "Team Oversight")
        # Ben is a Program Lead with nobody under him yet; Eve has no Program
        # Lead; Dan groups under his role.
        self.assertEqual(groups[f"pl:{self.ben.id}"]["total"], 1)
        self.assertEqual([p["name"] for p in groups["cceo:unled"]["members"]], ["Eve"])
        self.assertEqual(groups["role:CountryDirector"]["label"], "Country Directors")
        self.assertEqual(
            [p["name"] for p in groups["role:CountryDirector"]["members"]], ["Dan"]
        )
        self.assertEqual(
            groups["role:CountryDirector"]["members"][0]["working_on"],
            "Never signed in",
        )
        self.assertEqual(cd.name, "Dan")
        # Program Lead groups come first.
        self.assertEqual(summary["groups"][0]["key"], f"pl:{pl.id}")


class PresenceSurfaceTest(TestCase):
    def setUp(self):
        self.admin = _user("root", "Admin")
        self.cceo = _user("cara")

    def test_an_active_session_marks_the_person_seen_once_a_minute(self):
        self.client.force_login(self.cceo)
        self.client.get("/dashboard")
        self.cceo.refresh_from_db()
        first = self.cceo.last_seen_at
        self.assertIsNotNone(first)
        # A second request within the minute does not write again.
        self.client.get("/dashboard")
        self.cceo.refresh_from_db()
        self.assertEqual(self.cceo.last_seen_at, first)

    def test_the_admin_dashboard_shows_who_is_online_and_the_sign_in_counts(self):
        User.objects.filter(pk=self.cceo.pk).update(last_seen_at=timezone.now())
        LoginEvent.objects.create(user=self.cceo, role="CCEO")
        self.client.force_login(self.admin)
        html = self.client.get("/dashboard?view=operations").content.decode()
        self.assertIn("data-admin-presence", html)
        self.assertIn("Cara", html)
        # The table: status light, name, duration, working on, section.
        for column in (
            "Staff name",
            "Duration",
            "Working on what",
            "Part of the system accessed",
        ):
            self.assertIn(column, html)
        # Cara is online: a pulsing green light. Root, who has never signed in,
        # is offline with a grey one.
        self.assertIn('data-presence="online"', html)
        self.assertIn("admin-presence-light--online", html)
        self.assertIn('data-presence="offline"', html)
        self.assertIn("admin-presence-light--offline", html)
        self.assertIn("never signed in", html)
        self.assertIn("data-admin-logins", html)
        self.assertIn("1 today", html)

    def test_a_write_touches_between_the_minute_beats(self):
        self.client.force_login(self.cceo)
        self.client.get("/dashboard")
        self.cceo.refresh_from_db()
        first = self.cceo.last_seen_at
        # A drawer opened over htmx within the minute is recorded as the action.
        self.client.get(
            "/planning/schedule-modal?school_id=nope",
            HTTP_HX_REQUEST="true",
            HTTP_HX_CURRENT_URL="http://testserver/planning",
        )
        self.cceo.refresh_from_db()
        self.assertGreaterEqual(self.cceo.last_seen_at, first)
        self.assertEqual(self.cceo.last_seen_path, "/planning")
        self.assertEqual(self.cceo.last_seen_action, "GET /planning/schedule-modal")

    def test_the_country_director_sees_the_same_table(self):
        cd = _user("clara", "CountryDirector")
        pl = _user("paula", "Program Lead")
        StaffSupervisorAssignment.objects.create(
            supervisor=pl.staff_profile, supervisee=self.cceo.staff_profile
        )
        User.objects.filter(pk=self.cceo.pk).update(last_seen_at=timezone.now())
        self.client.force_login(cd)
        html = self.client.get("/dashboard?view=operations").content.decode()
        self.assertIn("data-admin-presence", html)
        self.assertIn("Who's Online", html)
        self.assertIn("Cara", html)
        self.assertIn('data-presence="online"', html)
        self.assertIn("Part of the system accessed", html)
        # Cara folds under Paula, whose own row leads the group.
        self.assertIn("PL · Paula", html)
        self.assertIn("presence-row--lead", html)
        self.assertIn(
            'data-presence-group="program_lead" data-presence-online="1"', html
        )
