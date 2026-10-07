"""Staff Activity Log (owner, 2026-09-29) — replaces Who's Online.

Active time is measured by the server, excludes idle and background tabs and
is never counted twice across tabs or devices; meaningful actions come from
the audit chain; a Programme Lead reads their team and the Country Director
the country by Programme Lead; follow-ups run the supervision line.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    Leave,
    LoginEvent,
    PresenceTime,
    PublicHoliday,
    StaffProfile,
    StaffSupervisorAssignment,
)
from apps.accounts.presence import (
    FINAL_BEAT_SECONDS,
    LOGIN_EVENT_SESSION_KEY,
    device_category,
    touch_presence,
)
from apps.audit.services import log as audit_log
from apps.notifications.models import Notification

from .follow_ups import (
    FollowUpError,
    create_follow_up,
    queue_for,
    resolve_by_activity,
    sweep_auto_resolutions,
    transition,
)
from .models import FollowUpStatus, StaffUsageFollowUp
from .services import activity_log, activity_period, person_detail, viewer_scope
from .todos import follow_up_todos

User = get_user_model()

# A Wednesday well inside FY2026's Q4 (July–September), so no weekend or FY
# edge decides the result.
WEDNESDAY = date(2026, 9, 23)


def _user(uid, role="CCEO", *, name=None):
    user = User.objects.create(
        id=uid,
        email=f"{uid}@edify.org",
        name=name or uid.title(),
        roles=[role],
        active_role=role,
        is_active=True,
    )
    StaffProfile.objects.create(id=f"{uid}-sp", user=user, title=role, country="Uganda")
    return user


def _supervise(lead, officer):
    StaffSupervisorAssignment.objects.create(
        supervisor=lead.staff_profile, supervisee=officer.staff_profile
    )


def _at(day: date, hour: int, minute: int = 0):
    return timezone.make_aware(
        datetime(day.year, day.month, day.day, hour, minute),
        timezone.get_current_timezone(),
    )


#: What the Programme Lead's dashboard section sends with its requests.
EMBED = {"HTTP_HX_REQUEST": "true", "HTTP_X_EDIFY_EMBED": "dashboard"}


class Team(TestCase):
    def setUp(self):
        # These tests write audit rows directly, outside any request. A
        # request made earlier on this thread leaves its context behind, and
        # the rows would all carry that one request's id.
        from apps.core.request_context import set_request_context

        set_request_context(None)
        self.director = _user("clara", "CountryDirector")
        self.admin = _user("root", "Admin")
        self.accountant = _user("abby", "Accountant")
        self.lead = _user("lena", "Program Lead")
        self.other_lead = _user("olive", "Program Lead")
        self.mina = _user("mina")
        self.max = _user("max")
        self.otto = _user("otto")
        _supervise(self.lead, self.mina)
        _supervise(self.lead, self.max)
        _supervise(self.other_lead, self.otto)


class ActiveTimeIsMeasuredTest(Team):
    """§5: active time, not the time a session stayed open."""

    def _beat(self, user, *, at, path, login_id=None):
        from unittest.mock import patch

        class Request:
            method = "GET"
            headers = {}
            session = {LOGIN_EVENT_SESSION_KEY: login_id} if login_id else {}

            def __init__(self, path):
                self.path = path

        user.refresh_from_db()
        with patch("apps.accounts.presence.timezone.now", return_value=at):
            touch_presence(user, Request(path))

    def test_an_untouched_tab_stops_counting_after_the_idle_threshold(self):
        start = timezone.now() - timedelta(hours=1)
        self._beat(self.mina, at=start, path="/my-plan")
        self._beat(self.mina, at=start + timedelta(minutes=4), path="/my-plan")
        # Six minutes with no beat: idle. Only the final-beat credit counts.
        self._beat(self.mina, at=start + timedelta(minutes=10), path="/my-plan")
        total = sum(
            PresenceTime.objects.filter(user=self.mina).values_list(
                "seconds", flat=True
            )
        )
        self.assertEqual(total, 4 * 60 + FINAL_BEAT_SECONDS)

    def test_two_devices_at_once_are_counted_once(self):
        """Laptop 09:00–09:30 and phone 09:15–09:45 is 45 minutes, not 60."""
        laptop = LoginEvent.objects.create(
            user=self.mina, role="CCEO", device="desktop"
        )
        phone = LoginEvent.objects.create(user=self.mina, role="CCEO", device="mobile")
        base = timezone.now() - timedelta(hours=2)
        beats = []
        for minute in range(0, 31, 3):
            beats.append((minute, laptop.pk))
        for minute in [m + 0.5 for m in range(15, 45, 3)] + [45]:
            beats.append((minute, phone.pk))
        for minute, login_id in sorted(beats):
            self._beat(
                self.mina,
                at=base + timedelta(minutes=minute),
                path="/planning",
                login_id=login_id,
            )
        total = sum(
            PresenceTime.objects.filter(user=self.mina).values_list(
                "seconds", flat=True
            )
        )
        self.assertEqual(total, 45 * 60)
        # The sessions share those 45 minutes between them; together they
        # hold exactly the overall active time.
        sessions = sum(
            LoginEvent.objects.filter(user=self.mina).values_list(
                "active_seconds", flat=True
            )
        )
        self.assertEqual(sessions, total)

    def test_a_background_request_is_not_activity(self):
        self.client.force_login(self.mina)
        self.client.get("/dashboard", HTTP_X_EDIFY_BACKGROUND="1")
        self.mina.refresh_from_db()
        self.assertIsNone(self.mina.last_seen_at)
        # A person's own htmx request is activity (the throttled beat has
        # just been spent on the background one, so a plain page load within
        # the minute would not write).
        self.client.get("/dashboard", HTTP_HX_REQUEST="true")
        self.mina.refresh_from_db()
        self.assertIsNotNone(self.mina.last_seen_at)

    def test_a_page_keeping_up_with_the_plan_is_not_activity(self):
        """Owner, 2026-10-05: every page that shows the plan reads itself
        again when a colleague changes it (static/js/live-regions.js). That
        is their work arriving, not this person working."""
        self.client.force_login(self.mina)
        self.client.get("/my-plan", HTTP_X_REQUESTED_WITH="EdifyLive")
        self.mina.refresh_from_db()
        self.assertIsNone(self.mina.last_seen_at)

    def test_the_heartbeat_names_its_page_and_keeps_an_open_drawer(self):
        self.client.force_login(self.mina)
        response = self.client.post("/staff-activity/beat", {"page": "/planning?x=1"})
        self.assertEqual(response.status_code, 200)
        self.mina.refresh_from_db()
        self.assertEqual(self.mina.last_seen_path, "/planning")
        User.objects.filter(pk=self.mina.pk).update(
            last_seen_action="GET /planning/schedule-modal"
        )
        self.client.post("/staff-activity/beat", {"page": "/planning"})
        self.mina.refresh_from_db()
        self.assertEqual(self.mina.last_seen_action, "GET /planning/schedule-modal")
        # The browser's machinery is never a page.
        self.client.post("/staff-activity/beat", {"page": "/sw.js"})
        self.mina.refresh_from_db()
        self.assertEqual(self.mina.last_seen_path, "/planning")
        self.assertEqual(self.client.get("/staff-activity/beat").status_code, 405)

    def test_signing_out_ends_the_session(self):
        self.client.force_login(self.mina)
        event = LoginEvent.objects.create(user=self.mina, role="CCEO")
        session = self.client.session
        session[LOGIN_EVENT_SESSION_KEY] = event.pk
        session.save()
        self.client.post("/logout")
        event.refresh_from_db()
        self.assertIsNotNone(event.ended_at)

    def test_the_device_is_a_category_only(self):
        iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148"
        tablet = (
            "Mozilla/5.0 (Linux; Android 13; SM-X200) AppleWebKit/537.36 Safari/537.36"
        )
        mac = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"
        self.assertEqual(device_category(iphone), "mobile")
        self.assertEqual(device_category(tablet), "tablet")
        self.assertEqual(device_category(mac), "desktop")
        self.assertEqual(device_category(""), "")


class WhoReadsWhomTest(Team):
    """§8: the supervision model."""

    def test_a_programme_lead_reads_their_own_officers_only(self):
        scope = viewer_scope(self.lead)
        self.assertEqual(scope["mode"], "team")
        # Themselves too (owner, 2026-09-29: "Add the PL on staff activity
        # table too").
        self.assertEqual(scope["ids"], {self.lead.id, self.mina.id, self.max.id})
        self.assertEqual(scope["self_id"], self.lead.id)
        self.assertTrue(scope["can_follow_up"])

    def test_the_lead_s_own_row_comes_first_and_is_never_followed_up(self):
        log = activity_log(self.lead)
        first = log["people"][0]
        self.assertEqual(first["name"], "Lena")
        self.assertTrue(first["is_self"])
        self.assertEqual(first["suggestions"], [])
        self.assertFalse(any(p["is_self"] for p in log["people"][1:]))
        with self.assertRaises(FollowUpError):
            create_follow_up(
                self.lead,
                self.lead.id,
                trigger="no_login",
                note="Me",
                priority="normal",
                due_date=timezone.localdate(),
                period=activity_period(None, None),
                snapshot={},
            )
        self.client.force_login(self.lead)
        html = self.client.get("/staff-activity", **EMBED).content.decode()
        own = html.index(f'data-sal-person="{self.lead.id}"')
        mina = html.index(f'data-sal-person="{self.mina.id}"')
        self.assertLess(own, mina)
        # No Follow up in the Lead's own row, nor in their own detail.
        self.assertNotIn(f"/people/{self.lead.id}/follow-up", html)
        self.assertIn(f"/people/{self.mina.id}/follow-up", html)
        detail = self.client.get(f"/staff-activity/people/{self.lead.id}")
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, "/follow-up")
        self.assertEqual(
            self.client.get(
                f"/staff-activity/people/{self.lead.id}/follow-up",
                HTTP_HX_REQUEST="true",
            ).status_code,
            403,
        )

    def test_the_director_reads_the_country_grouped_by_programme_lead(self):
        log = activity_log(self.director)
        self.assertEqual(log["scope"]["mode"], "country")
        names = {p["name"] for p in log["people"]}
        self.assertIn("Mina", names)
        self.assertIn("Otto", names)
        self.assertNotIn("Clara", names)  # not the reader
        self.assertNotIn("Root", names)  # the Admin account is technical
        # CCEOs and PLs only (owner, 2026-09-29).
        self.assertEqual(
            {p["active_role"] for p in log["people"]}, {"CCEO", "Program Lead"}
        )
        lena = next(g for g in log["groups"] if g["label"] == "Lena")
        self.assertEqual(lena["lead"]["name"], "Lena")
        self.assertEqual({p["name"] for p in lena["members"]}, {"Mina", "Max"})

    def test_the_admin_reads_but_does_not_follow_up(self):
        scope = viewer_scope(self.admin)
        self.assertEqual(scope["mode"], "country")
        self.assertFalse(scope["can_follow_up"])

    def test_other_roles_have_no_log(self):
        self.assertIsNone(viewer_scope(self.mina))
        self.client.force_login(self.mina)
        response = self.client.get("/staff-activity", HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 403)

    def test_a_lead_cannot_open_another_team_s_person(self):
        with self.assertRaises(PermissionError):
            person_detail(self.lead, self.otto.id)
        self.client.force_login(self.lead)
        self.assertEqual(
            self.client.get(f"/staff-activity/people/{self.otto.id}").status_code, 403
        )
        self.assertEqual(
            self.client.get(f"/staff-activity/people/{self.mina.id}").status_code, 200
        )


class PeriodsTest(TestCase):
    def test_quarters_and_years_follow_the_october_calendar(self):
        quarter = activity_period("quarter", "2026-11-15", today=date(2026, 11, 20))
        self.assertEqual(
            (quarter["start"], quarter["end"]), (date(2026, 10, 1), date(2026, 12, 31))
        )
        fy = activity_period("fy", "2026-11-15", today=date(2026, 11, 20))
        self.assertEqual(
            (fy["start"], fy["end"]), (date(2026, 10, 1), date(2027, 9, 30))
        )
        # The days still to come are not judged.
        self.assertEqual(fy["elapsed_end"], date(2026, 11, 20))


class UsageStatusTest(Team):
    """§6 and §9.1: no-login flags respect leave, holidays and weekends."""

    def _log(self, day=WEDNESDAY, period="day"):
        return {
            p["name"]: p
            for p in activity_log(
                self.lead, period=period, on=day.isoformat(), now=_at(day, 17)
            )["people"]
        }

    def test_no_login_on_an_expected_working_day_suggests_a_follow_up(self):
        LoginEvent.objects.create(user=self.max, role="CCEO", at=_at(WEDNESDAY, 8))
        people = self._log()
        self.assertEqual(people["Mina"]["usage_key"], "no_login")
        self.assertEqual(people["Mina"]["suggestions"][0]["trigger"], "no_login")
        self.assertEqual(people["Max"]["usage_key"], "normal")

    def test_approved_leave_is_not_a_missed_login(self):
        Leave.objects.create(
            staff=self.mina.staff_profile,
            type="personal_time_off",
            start_date=WEDNESDAY.isoformat(),
            end_date=WEDNESDAY.isoformat(),
            days=1,
            status="approved",
        )
        self.assertEqual(self._log()["Mina"]["usage_key"], "on_leave")

    def test_weekends_and_public_holidays_expect_nothing(self):
        saturday = WEDNESDAY + timedelta(days=3)
        self.assertEqual(self._log(saturday)["Mina"]["usage_key"], "not_expected")
        PublicHoliday.objects.create(name="Test Day", date=WEDNESDAY)
        self.assertEqual(self._log()["Mina"]["usage_key"], "not_expected")

    def test_logins_are_sign_ins_and_time_is_active_time(self):
        for hour in (8, 13):
            LoginEvent.objects.create(
                user=self.max, role="CCEO", at=_at(WEDNESDAY, hour)
            )
        PresenceTime.objects.create(
            user=self.max,
            day=WEDNESDAY,
            section="Planning",
            working_on="Scheduling an activity",
            seconds=1800,
        )
        PresenceTime.objects.create(
            user=self.max,
            day=WEDNESDAY,
            section="My Plan",
            working_on="Viewing My Plan",
            seconds=1080,
        )
        max_ = self._log()["Max"]
        self.assertEqual(max_["logins"], 2)
        self.assertEqual(max_["active_label"], "48m")
        # Time by module adds up to the overall active time.
        self.assertEqual(sum(max_["sections"].values()), max_["active_seconds"])
        week = {
            p["name"]: p
            for p in activity_log(
                self.lead,
                period="week",
                on=WEDNESDAY.isoformat(),
                now=_at(WEDNESDAY, 17),
            )["people"]
        }
        self.assertEqual(week["Max"]["active_seconds"], 2880)

    def test_each_period_adds_up_its_days(self):
        # Owner, 2026-09-29: the day's time on the app for Day; Week, Month,
        # Quarter and FY the days added up, so time per day can be followed.
        for day, seconds in (
            (WEDNESDAY, 1800),
            (WEDNESDAY - timedelta(days=1), 1200),  # same week
            (WEDNESDAY - timedelta(days=7), 600),  # last week
            (WEDNESDAY - timedelta(days=45), 3000),  # an earlier month
            (WEDNESDAY - timedelta(days=400), 9000),  # another FY
        ):
            PresenceTime.objects.create(
                user=self.max,
                day=day,
                section="Planning",
                working_on="Viewing Planning",
                seconds=seconds,
            )

        def total(period):
            return self._log(period=period)["Max"]["active_seconds"]

        in_period = {}
        for period in ("day", "week", "month", "quarter", "fy"):
            chosen = activity_period(period, WEDNESDAY.isoformat(), today=WEDNESDAY)
            in_period[period] = sum(
                PresenceTime.objects.filter(
                    user=self.max, day__gte=chosen["start"], day__lte=chosen["end"]
                ).values_list("seconds", flat=True)
            )
            with self.subTest(period=period):
                self.assertEqual(total(period), in_period[period])
        self.assertEqual(in_period["day"], 1800)
        self.assertEqual(in_period["week"], 3000)
        self.assertLessEqual(in_period["week"], in_period["month"])
        self.assertLessEqual(in_period["month"], in_period["quarter"])
        self.assertLessEqual(in_period["quarter"], in_period["fy"])
        self.assertLess(in_period["fy"], 1800 + 1200 + 600 + 3000 + 9000)


class MeaningfulActionsTest(Team):
    """§3.2: governed actions from the audit chain; a page view is not one,
    and a failed transition is not a completed action."""

    def test_actions_failures_and_schools(self):
        audit_log(
            action="upload_evidence",
            subject_kind="school",
            subject_id="S1",
            actor_id=self.mina.id,
        )
        audit_log(
            action="start_activity",
            subject_kind="school",
            subject_id="S2",
            actor_id=self.mina.id,
        )
        audit_log(
            action="start_activity",
            subject_kind="school",
            subject_id="S2",
            actor_id=self.mina.id,
        )
        audit_log(
            action="upload_evidence",
            subject_kind="school",
            subject_id="S3",
            actor_id=self.mina.id,
            success=False,
        )
        audit_log(
            action="request_failed",
            subject_kind="Request",
            subject_id="x",
            actor_id=self.mina.id,
            success=False,
        )
        audit_log(
            action="documents.opened",
            subject_kind="document",
            subject_id="d",
            actor_id=self.mina.id,
        )
        mina = {p["name"]: p for p in activity_log(self.lead)["people"]}["Mina"]
        self.assertEqual(mina["actions"], 3)
        self.assertEqual(mina["failed"], 2)
        self.assertEqual(mina["schools"], 2)
        self.assertEqual(mina["last_action"], "Started an activity")
        detail = person_detail(self.lead, self.mina.id)
        self.assertEqual(detail["timeline_total"], 5)
        self.assertIn("/schools/S2", [a["link"] for a in detail["timeline"]])


class FollowUpTest(Team):
    """§9: the follow-up workflow runs the supervision line."""

    def _send(self, sender, subject, trigger="no_login", **extra):
        values = {
            "trigger": trigger,
            "note": "Let's talk about signing in.",
            "priority": "normal",
            "due_date": timezone.localdate() + timedelta(days=2),
            "period": activity_period("day"),
            "snapshot": {"logins": 0},
        }
        values.update(extra)
        # Notices are sent when the follow-up commits.
        with self.captureOnCommitCallbacks(execute=True):
            return create_follow_up(sender, subject.id, **values)

    def test_a_lead_follows_up_with_their_officer(self):
        fu = self._send(self.lead, self.mina)
        self.assertEqual(fu.assignee_id, self.mina.id)
        self.assertEqual(fu.route, "manager_to_staff")
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.mina.id, context_id=fu.id
            ).exists()
        )
        rows = follow_up_todos(self.mina, "CCEO", timezone.localdate())
        self.assertEqual([r["id"] for r in rows], [f"staff-follow-up-{fu.id}"])

    def test_the_director_goes_through_the_programme_lead(self):
        fu = self._send(self.director, self.mina)
        self.assertEqual(fu.assignee_id, self.lead.id)
        self.assertEqual(fu.route, "director_to_manager")
        # The Lead works it; the officer is not bypassed and not told by the
        # Director.
        self.assertFalse(
            Notification.objects.filter(recipient_id=self.mina.id).exists()
        )
        fu = transition(fu, self.lead, "acknowledge")
        fu = transition(fu, self.lead, "resolve", "Spoke with Mina; phone was broken.")
        self.assertEqual(fu.status, FollowUpStatus.RESOLVED_BY_MANAGER)
        fu = transition(fu, self.director, "close")
        self.assertEqual(fu.status, FollowUpStatus.CLOSED)

    def test_out_of_scope_and_duplicates_are_refused(self):
        with self.assertRaises(FollowUpError):
            self._send(self.lead, self.otto)
        with self.assertRaises(FollowUpError):
            self._send(self.admin, self.mina)
        self._send(self.lead, self.mina)
        with self.assertRaises(FollowUpError):
            self._send(self.lead, self.mina)
        with self.assertRaises(FollowUpError):
            self._send(self.lead, self.max, note="  ")

    def test_only_the_parties_may_move_it(self):
        fu = self._send(self.lead, self.mina)
        with self.assertRaises(FollowUpError):
            transition(fu, self.max, "acknowledge")
        with self.assertRaises(FollowUpError):
            transition(fu, self.mina, "resolve", "done")  # the manager resolves
        fu = transition(fu, self.mina, "acknowledge")
        self.assertEqual(fu.status, FollowUpStatus.ACKNOWLEDGED)
        with self.assertRaises(FollowUpError):
            transition(fu, self.lead, "cancel")  # a note is required
        self.assertEqual([h["status"] for h in fu.history], ["sent", "acknowledged"])

    def test_signing_in_resolves_a_no_login_follow_up(self):
        fu = self._send(self.lead, self.mina)
        conversation = self._send(self.lead, self.mina, trigger="training")
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(resolve_by_activity(self.mina, "login"), 1)
        fu.refresh_from_db()
        conversation.refresh_from_db()
        self.assertEqual(fu.status, FollowUpStatus.RESOLVED_BY_ACTIVITY)
        # A conversation or training the manager asked for is closed by a person.
        self.assertEqual(conversation.status, FollowUpStatus.SENT)
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.mina.id, context_id=fu.id, resolved_at__isnull=False
            ).exists()
        )
        self.assertEqual(
            [r["id"] for r in follow_up_todos(self.mina, "CCEO", timezone.localdate())],
            [f"staff-follow-up-{conversation.id}"],
        )

    def test_the_work_asked_about_resolves_it(self):
        fu = self._send(self.lead, self.mina, trigger="evidence_not_done")
        audit_log(
            action="start_activity",
            subject_kind="school",
            subject_id="S1",
            actor_id=self.mina.id,
        )
        sweep_auto_resolutions([fu])
        fu.refresh_from_db()
        self.assertEqual(fu.status, FollowUpStatus.SENT)  # not evidence work
        audit_log(
            action="upload_evidence",
            subject_kind="school",
            subject_id="S1",
            actor_id=self.mina.id,
        )
        sweep_auto_resolutions([fu])
        fu.refresh_from_db()
        self.assertEqual(fu.status, FollowUpStatus.RESOLVED_BY_ACTIVITY)

    def test_the_queue_and_the_pages(self):
        fu = self._send(self.director, self.mina)
        self.assertEqual([f.id for f in queue_for(self.lead)["to_me"]], [fu.id])
        self.assertEqual([f.id for f in queue_for(self.director)["from_me"]], [fu.id])
        self.client.force_login(self.lead)
        self.assertEqual(
            self.client.get(f"/staff-activity/follow-ups/{fu.id}").status_code, 200
        )
        response = self.client.post(
            f"/staff-activity/follow-ups/{fu.id}/acknowledge", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 204)
        self.client.force_login(self.otto)
        self.assertEqual(
            self.client.get(f"/staff-activity/follow-ups/{fu.id}").status_code, 403
        )

    def test_the_drawer_sends_one(self):
        self.client.force_login(self.lead)
        drawer = self.client.get(
            f"/staff-activity/people/{self.mina.id}/follow-up", HTTP_HX_REQUEST="true"
        )
        self.assertContains(drawer, "Follow up: Mina")
        response = self.client.post(
            f"/staff-activity/people/{self.mina.id}/follow-up/send",
            {
                "trigger": "training",
                "note": "A walk-through of evidence upload.",
                "priority": "high",
                "due_date": (timezone.localdate() + timedelta(days=1)).isoformat(),
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 204)
        fu = StaffUsageFollowUp.objects.get(subject=self.mina)
        self.assertEqual(fu.priority, "high")
        self.assertIn("logins", fu.snapshot)


class PageTest(Team):
    def test_the_page_the_detail_and_the_export(self):
        PresenceTime.objects.create(
            user=self.mina,
            day=timezone.localdate(),
            section="Planning",
            working_on="Viewing Planning",
            seconds=600,
        )
        LoginEvent.objects.create(user=self.mina, role="CCEO", device="mobile")
        for reader in (self.director, self.admin):
            self.client.force_login(reader)
            html = self.client.get("/staff-activity").content.decode()
            self.assertIn("Staff Activity Log", html)
            self.assertIn("Mina", html)
            self.assertIn('data-table-fit="scroll"', html)
            self.assertEqual("Follow-up Queue" in html, reader != self.admin)
        # The Programme Lead reads it on their dashboard (owner, 2026-09-29):
        # the section's requests get the workspace with its heading and
        # actions, and no history entry.
        self.client.force_login(self.lead)
        embedded = self.client.get("/staff-activity", **EMBED)
        self.assertEqual(embedded["HX-Push-Url"], "false")
        html = embedded.content.decode()
        self.assertNotIn("<html", html)
        self.assertIn('id="pl-staff-activity-title"', html)
        self.assertIn("Mina", html)
        self.assertIn('data-table-fit="scroll"', html)
        self.assertIn("Follow-up Queue", html)
        self.assertIn('href="/staff-activity/export?', html)
        self.assertNotIn("Otto", html)
        detail = self.client.get(f"/staff-activity/people/{self.mina.id}?period=week")
        self.assertContains(detail, "Sign-in history")
        self.assertContains(detail, "Time by module")
        export = self.client.get("/staff-activity/export")
        self.assertEqual(export.status_code, 200)
        self.assertIn(".xlsx", export["Content-Disposition"])

    def test_the_dashboard_runs_insights_table_then_the_person(self):
        # Owner, 2026-09-29: on the Programme Lead's dashboard Team Insights
        # runs across above the table and the opened person below it; the
        # page of its own keeps the right column.
        self.client.force_login(self.lead)
        html = self.client.get("/staff-activity", **EMBED).content.decode()
        self.assertIn('data-sal-flow="row"', html)
        self.assertNotIn('class="sal-side"', html)
        self.assertLess(
            html.index('id="sal-insights-title"'), html.index('id="sal-table-title"')
        )
        self.assertLess(
            html.index('id="sal-table-title"'), html.index('id="sal-picked"')
        )
        self.client.force_login(self.director)
        page = self.client.get("/staff-activity").content.decode()
        self.assertNotIn("data-sal-flow", page)
        self.assertIn('class="sal-side"', page)
        self.assertLess(
            page.index('id="sal-table-title"'), page.index('id="sal-insights-title"')
        )

    def test_filters_narrow_every_figure(self):
        self.client.force_login(self.director)
        html = self.client.get(
            f"/staff-activity?pl={self.other_lead.id}"
        ).content.decode()
        self.assertIn("Otto", html)
        self.assertNotIn(">Mina<", html)
        log = activity_log(self.director, program_lead=self.other_lead.id)
        self.assertEqual({p["name"] for p in log["people"]}, {"Olive", "Otto"})
        self.assertEqual(log["kpis"]["staff_total"], 2)

    def test_the_sidebar_offers_it_to_its_readers(self):
        # The Programme Lead's is on their dashboard, not in the sidebar
        # (owner, 2026-09-29).
        for reader, in_sidebar, on_dashboard in (
            (self.lead, False, True),
            (self.director, True, False),
            (self.mina, False, False),
        ):
            self.client.force_login(reader)
            html = self.client.get("/dashboard", follow=True).content.decode()
            self.assertEqual(
                'href="/staff-activity"' in html, in_sidebar, reader.active_role
            )
            self.assertEqual(
                'id="staff-activity"' in html, on_dashboard, reader.active_role
            )

    def test_a_lead_opening_the_page_lands_on_their_dashboard(self):
        self.client.force_login(self.lead)
        response = self.client.get("/staff-activity?period=week")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"], "/dashboard?sa=period%3Dweek#staff-activity"
        )
        dashboard = self.client.get(response["Location"].split("#")[0])
        self.assertContains(dashboard, 'hx-get="/staff-activity?period=week"')
