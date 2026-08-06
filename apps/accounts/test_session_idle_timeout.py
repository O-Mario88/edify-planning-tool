"""A session ends after thirty minutes of inactivity, not after thirty minutes.

The distinction is the whole feature. Someone working through a long planning
session must never be signed out mid-task; a laptop left open in a shared
office must stop being a way in once it has been idle for half an hour.

SESSION_COOKIE_AGE alone is a hard cap that signs people out mid-sentence, so
something has to re-stamp the expiry while they work. Django's own answer,
SESSION_SAVE_EVERY_REQUEST, writes the session row on every request;
SlidingSessionMiddleware does it on a throttle instead. What is tested here is
the behaviour either would give, plus the bound on what the throttle costs.

Idleness is simulated by ageing the stored session rather than by freezing the
clock, because the stored expiry is what Django actually consults (the loader
filters on `expire_date__gt=now`) and freezegun segfaults against pandas' lazy
imports in this suite.

A session lives in two places when Redis is available — the database row and
the cache entry — and it is only really gone when both have let go. So the
simulation ages both, and CachedSessionTest is what makes that faithful: it
pins the cache TTL to the same window, so evicting the entry in the helper is
what a real cache would have done on its own.
"""

from __future__ import annotations

import time
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends import cached_db
from django.contrib.sessions.models import Session
from django.core.cache import caches
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.core.middleware import SlidingSessionMiddleware
from apps.core.rbac import EdifyRole

IDLE_LIMIT = timedelta(seconds=settings.SESSION_COOKIE_AGE)


def _user(email="idle@edify.test"):
    return get_user_model().objects.create_user(
        email=email,
        password="password123",
        name="Idle Tester",
        roles=[EdifyRole.CCEO.value],
        active_role=EdifyRole.CCEO.value,
        is_active=True,
    )


def _row(client) -> Session:
    return Session.objects.get(session_key=client.session.session_key)


def _idle_for(client, elapsed: timedelta) -> None:
    """Age the whole session as though the user had done nothing for `elapsed`.

    Everything that records when the user was last seen moves back together:
    the throttle's own timestamp inside the session data, the row's expiry, and
    — once the window is past — the cache entry, which a lapsed TTL would have
    taken by then anyway.
    """
    seconds = elapsed.total_seconds()

    store = client.session
    store[SlidingSessionMiddleware.TOUCHED_AT] = int(time.time() - seconds)
    store.save()

    key = store.session_key
    Session.objects.filter(session_key=key).update(
        expire_date=timezone.now() + IDLE_LIMIT - elapsed
    )
    if elapsed >= IDLE_LIMIT:
        caches[settings.SESSION_CACHE_ALIAS].delete(cached_db.KEY_PREFIX + key)


class ConfigurationTest(TestCase):
    def test_the_window_is_thirty_minutes(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 30 * 60)

    def test_something_is_sliding_the_window(self):
        """Without one of these the setting is a hard cap, and a user gets
        signed out in the middle of typing."""
        self.assertTrue(
            settings.SESSION_SAVE_EVERY_REQUEST
            or "apps.core.middleware.SlidingSessionMiddleware" in settings.MIDDLEWARE,
            "nothing re-stamps the session expiry, so the idle window is a "
            "hard cap on the whole session",
        )

    def test_the_slider_runs_before_the_session_is_saved(self):
        """Response phases run in reverse order, so touching the session has to
        be listed *after* SessionMiddleware to happen *before* its save."""
        if settings.SESSION_SAVE_EVERY_REQUEST:
            self.skipTest("Django is saving every request; ordering is moot")
        order = list(settings.MIDDLEWARE)
        self.assertGreater(
            order.index("apps.core.middleware.SlidingSessionMiddleware"),
            order.index("django.contrib.sessions.middleware.SessionMiddleware"),
        )

    def test_the_session_does_not_outlive_the_browser_by_accident(self):
        """A persistent cookie is intended here — the idle window, not the
        browser lifetime, is what ends the session."""
        self.assertFalse(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)


class CachedSessionTest(TestCase):
    """The cache copy must not outlive the window the database row obeys.

    With `cached_db` the session is read from cache first, so a cache entry
    that lingered after the row expired would keep an abandoned laptop signed
    in — the idle timeout would be enforced only for whoever missed the cache.
    Exercised against a cached_db store directly rather than the configured
    engine, because the configured engine is `db` wherever Redis is absent and
    this is precisely the risk that only appears when it is present.
    """

    def _ttls_written_by(self, action) -> list[int]:
        cache = caches[settings.SESSION_CACHE_ALIAS]
        seen = []
        original = cache.set

        def spy(key, value, timeout=None, **kwargs):
            if key.startswith(cached_db.KEY_PREFIX):
                seen.append(timeout)
            return original(key, value, timeout, **kwargs)

        with mock.patch.object(cache, "set", spy):
            action(cached_db.SessionStore())
        return seen

    def test_saving_gives_the_cache_entry_exactly_the_idle_window(self):
        def save(store):
            store["_auth_user_id"] = "1"
            store.save()

        ttls = self._ttls_written_by(save)
        self.assertTrue(ttls, "the session was never cached at all")
        self.assertEqual(set(ttls), {settings.SESSION_COOKIE_AGE})

    def test_no_cache_write_may_outlive_the_window(self):
        """`timeout=None` means "cache forever" — a session that never ends."""

        def save_then_reload(store):
            store["_auth_user_id"] = "1"
            store.save()
            caches[settings.SESSION_CACHE_ALIAS].delete(store.cache_key)
            cached_db.SessionStore(store.session_key).load()

        for ttl in self._ttls_written_by(save_then_reload):
            self.assertIsNotNone(ttl, "a session was cached with no expiry at all")
            self.assertLessEqual(ttl, settings.SESSION_COOKIE_AGE)


class SlidingWindowTest(TestCase):
    """The half of the requirement that is about *not* signing people out."""

    def setUp(self):
        self.user = _user()
        self.client = Client()
        self.client.force_login(self.user)

    def test_a_request_pushes_the_expiry_back_out_to_a_full_window(self):
        _idle_for(self.client, timedelta(minutes=29))
        before = _row(self.client).expire_date

        self.assertEqual(self.client.get("/dashboard").status_code, 200)

        after = _row(self.client).expire_date
        self.assertGreater(
            after,
            before,
            "the expiry did not move, so the window is a hard cap and an "
            "active user will be signed out mid-task",
        )
        expected = timezone.now() + IDLE_LIMIT
        self.assertLess(
            abs((after - expected).total_seconds()),
            10,
            "activity should restore the whole window, not a fraction of it",
        )

    def test_working_steadily_keeps_the_session_alive_indefinitely(self):
        """Two hours of work with a gap just under the limit before each
        action. The user is never signed out."""
        for minute in range(4):
            _idle_for(self.client, timedelta(minutes=29))
            self.assertEqual(
                self.client.get("/dashboard").status_code,
                200,
                f"signed out while still working (interval {minute + 1})",
            )

    def test_a_background_poll_counts_as_activity(self):
        """Pages poll; if those requests did not slide the window, someone
        reading a dashboard would be signed out while looking at it."""
        _idle_for(self.client, timedelta(minutes=29))
        self.client.get("/api/health/live")
        _idle_for(self.client, timedelta(minutes=29))
        self.assertEqual(self.client.get("/dashboard").status_code, 200)


class ThrottleTest(TestCase):
    """What the throttle saves, and what it costs.

    Sliding the window by saving on every request is correct and expensive: an
    UPDATE on one hot session row for every request in the product. These pin
    both halves of the trade, so neither can quietly change — the writes cannot
    creep back to one-per-request, and the imprecision cannot grow.
    """

    def setUp(self):
        self.user = _user("throttle@edify.test")
        self.client = Client()
        self.client.force_login(self.user)
        self.client.get("/dashboard")

    def _session_writes(self, count: int) -> int:
        """Writes only. The `db` engine also SELECTs the row on every request,
        which is Django loading the session and not this middleware saving it —
        counting those would make the test pass or fail on whether a cache
        happened to be configured."""
        with CaptureQueriesContext(connection) as queries:
            for _ in range(count):
                self.client.get("/api/health/live")
        return len(
            [
                q
                for q in queries.captured_queries
                if "django_session" in q["sql"].lower()
                and q["sql"].lstrip().upper().startswith(("UPDATE", "INSERT"))
            ]
        )

    def test_a_burst_of_requests_writes_the_session_at_most_once(self):
        """The regression this exists for: every request writing the row."""
        self.assertLessEqual(
            self._session_writes(10),
            1,
            "the session row is being written per request again",
        )

    def test_a_request_after_the_interval_does_write(self):
        """The saving must not be so eager that it stops sliding."""
        _idle_for(self.client, timedelta(seconds=IDLE_LIMIT.total_seconds() // 2))
        self.assertGreaterEqual(self._session_writes(1), 1)

    def test_the_imprecision_stays_a_small_fraction_of_the_window(self):
        """A session can end up to one interval early. That is the whole cost,
        and it is only tolerable while it stays small."""
        interval = SlidingSessionMiddleware(lambda r: None).refresh_interval
        self.assertLessEqual(interval, settings.SESSION_COOKIE_AGE * 0.05)
        self.assertGreaterEqual(interval, 1)

    def test_an_anonymous_visitor_is_given_no_session_at_all(self):
        """Touching an empty session would mint a row and a cookie for every
        crawler that ever hit the login page."""
        before = Session.objects.count()
        anonymous = Client()
        anonymous.get("/login")
        self.assertEqual(Session.objects.count(), before)


class IdleExpiryTest(TestCase):
    """The half that is about actually ending an unattended session."""

    def setUp(self):
        self.user = _user("idle2@edify.test")
        self.client = Client()
        self.client.force_login(self.user)

    def test_the_session_survives_just_under_the_limit(self):
        _idle_for(self.client, IDLE_LIMIT - timedelta(minutes=1))
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_it_is_gone_just_past_the_limit(self):
        _idle_for(self.client, IDLE_LIMIT + timedelta(minutes=1))
        response = self.client.get("/dashboard")
        self.assertNotEqual(
            response.status_code,
            200,
            "a session idle beyond the window is still serving pages",
        )

    def test_the_idle_user_lands_on_login(self):
        _idle_for(self.client, IDLE_LIMIT + timedelta(minutes=1))
        response = self.client.get("/dashboard", follow=True)
        self.assertIn("/login", response.redirect_chain[-1][0])

    def test_the_expired_session_cookie_no_longer_identifies_anyone(self):
        """Not merely a redirect: the credential itself must stop working."""
        _idle_for(self.client, IDLE_LIMIT + timedelta(minutes=1))
        self.client.get("/dashboard")
        self.assertNotIn("_auth_user_id", self.client.session)


class RememberMeTest(TestCase):
    """The checkbox still does something, and that something is not holding an
    unattended session open."""

    EMAIL = "remember@edify.test"

    def setUp(self):
        self.user = _user(self.EMAIL)

    def _sign_in(self, remember: bool):
        client = Client()
        form = {"email": self.EMAIL, "password": "password123"}
        if remember:
            form["remember_me"] = "on"
        client.post("/login", form)
        return client

    def test_it_does_not_extend_the_idle_window(self):
        client = self._sign_in(remember=True)
        self.assertIn("_auth_user_id", client.session)
        _idle_for(client, IDLE_LIMIT + timedelta(minutes=1))
        self.assertNotEqual(
            client.get("/dashboard").status_code,
            200,
            "'remember me' must not keep an idle session alive",
        )

    def test_it_prefills_the_address_next_time(self):
        signed_in = self._sign_in(remember=True)
        returning = Client()
        returning.cookies.update(signed_in.cookies)
        returning.cookies.pop(settings.SESSION_COOKIE_NAME, None)
        self.assertIn(self.EMAIL, returning.get("/login").content.decode())

    def test_leaving_it_unticked_remembers_nothing(self):
        signed_in = self._sign_in(remember=False)
        returning = Client()
        returning.cookies.update(signed_in.cookies)
        returning.cookies.pop(settings.SESSION_COOKIE_NAME, None)
        self.assertNotIn(self.EMAIL, returning.get("/login").content.decode())
