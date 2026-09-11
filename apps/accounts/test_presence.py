"""Who is online, and how many signed in (owner, 2026-09-12).

"The admin should also be able to see who is online. The number of logins
per day, per week."
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import LoginEvent, StaffProfile
from apps.accounts.presence import ONLINE_WINDOW, presence_summary, record_login, touch_presence

User = get_user_model()


def _user(uid, role="CCEO"):
    user = User.objects.create(
        id=uid, email=f"{uid}@edify.org", name=uid.title(), roles=[role],
        active_role=role, is_active=True,
    )
    StaffProfile.objects.create(id=f"{uid}-sp", user=user, title=role, country="Uganda")
    return user


class PresenceServiceTest(TestCase):
    def setUp(self):
        self.anna = _user("anna")
        self.ben = _user("ben", "Program Lead")
        self.rf = RequestFactory()

    def test_a_sign_in_is_recorded_with_its_role_and_address(self):
        request = self.rf.post("/login", HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.1", HTTP_USER_AGENT="Edify/1")
        record_login(request, self.anna)
        event = LoginEvent.objects.get(user=self.anna)
        self.assertEqual(event.role, "CCEO")
        self.assertEqual(event.ip, "203.0.113.9")
        self.assertEqual(event.user_agent, "Edify/1")
        self.anna.refresh_from_db()
        self.assertIsNotNone(self.anna.last_seen_at)

    def test_online_means_seen_within_the_window(self):
        now = timezone.now()
        User.objects.filter(pk=self.anna.pk).update(last_seen_at=now - timedelta(minutes=3))
        User.objects.filter(pk=self.ben.pk).update(last_seen_at=now - ONLINE_WINDOW - timedelta(minutes=1))
        summary = presence_summary(now=now)
        self.assertEqual([p["name"] for p in summary["online"]], ["Anna"])
        self.assertEqual(summary["online_count"], 1)

    def test_logins_are_counted_per_day_and_per_week(self):
        now = timezone.now()
        local_today = timezone.localtime(now).date()
        for days_ago in (0, 0, 1, 8, 20):
            LoginEvent.objects.create(user=self.anna, at=now - timedelta(days=days_ago), role="CCEO")
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
        request = self.rf.post("/login", HTTP_X_FORWARDED_FOR="not-an-address", REMOTE_ADDR="10.1.2.3")
        record_login(request, self.ben)
        self.assertIsNone(LoginEvent.objects.get(user=self.ben).ip)

    def test_touch_marks_the_person_seen(self):
        touch_presence(self.ben)
        self.ben.refresh_from_db()
        self.assertLess(timezone.now() - self.ben.last_seen_at, timedelta(seconds=5))


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
        self.assertIn("data-admin-logins", html)
        self.assertIn("1 today", html)
