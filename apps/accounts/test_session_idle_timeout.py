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

    def test_a_request_the_person_made_counts_wherever_it_goes(self):
        """Not only pages: a save, a search, a file asked for."""
        _idle_for(self.client, timedelta(minutes=29))
        self.client.get("/api/health/live")
        _idle_for(self.client, timedelta(minutes=29))
        self.assertEqual(self.client.get("/dashboard").status_code, 200)


#: What a page asks for without anyone at it, as the browser sends it.
UNATTENDED = {
    "the page reading itself again when the plan changes": (
        "/dashboard",
        {"HTTP_X_REQUESTED_WITH": "EdifyLive"},
    ),
    "an htmx request from a page nobody has touched": (
        "/dashboard",
        {"HTTP_HX_REQUEST": "true", "HTTP_X_EDIFY_BACKGROUND": "1"},
    ),
    "the page asking whether it is still signed in": ("/login/state", {}),
    "the service worker being fetched": ("/sw.js", {}),
}


class OnlyAPersonSlidesTheWindowTest(TestCase):
    """Owner, 2026-10-08: "make sure the session expires after 30 minutes of
    idle". Every request used to slide the window, the page's own included, so
    a page left on screen never signed anyone out."""

    def setUp(self):
        self.user = _user("unattended@edify.test")
        self.client = Client()
        self.client.force_login(self.user)
        self.client.get("/dashboard")

    def test_a_page_left_open_does_not_keep_the_session(self):
        for what, (path, headers) in UNATTENDED.items():
            with self.subTest(what):
                _idle_for(self.client, timedelta(minutes=29))
                before = _row(self.client).expire_date
                touched = self.client.session[SlidingSessionMiddleware.TOUCHED_AT]

                self.client.get(path, **headers)

                self.assertEqual(
                    _row(self.client).expire_date,
                    before,
                    f"{what} pushed the session's expiry out",
                )
                self.assertEqual(
                    self.client.session[SlidingSessionMiddleware.TOUCHED_AT], touched
                )

    def test_opening_the_live_stream_does_not_keep_it_either(self):
        """Asked of the middleware itself: the stream's view closes its
        database connection, which a test's transaction cannot survive."""
        from django.http import HttpResponse
        from django.test import RequestFactory

        _idle_for(self.client, timedelta(minutes=29))
        request = RequestFactory().get("/api/realtime/stream")
        request.session = self.client.session
        request.user = self.user

        SlidingSessionMiddleware(lambda r: HttpResponse())(request)

        self.assertFalse(request.session.modified)

    def test_it_ends_at_the_window_however_much_the_page_asked_for(self):
        """Thirty-one minutes of a page keeping up with the plan, nobody at
        it. The next thing asked of the session finds it ended."""
        _idle_for(self.client, timedelta(minutes=20))
        for path, headers in UNATTENDED.values():
            self.client.get(path, **headers)
        _idle_for(self.client, timedelta(minutes=31))
        response = self.client.get(
            "/dashboard", HTTP_X_REQUESTED_WITH="EdifyLive", follow=True
        )
        self.assertIn("/login", response.redirect_chain[-1][0])
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_rule_is_the_last_use_not_the_last_save(self):
        """Any view may save the session, and saving pushes the row's expiry
        out. A row that is still good for half an hour is ended all the same
        when nobody has used it for the window."""
        store = self.client.session
        store[SlidingSessionMiddleware.TOUCHED_AT] = int(
            time.time() - IDLE_LIMIT.total_seconds() - 5
        )
        store.save()
        self.assertGreater(_row(self.client).expire_date, timezone.now())

        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response["Location"])
        self.assertFalse(
            Session.objects.filter(session_key=store.session_key).exists(),
            "the idle session's row is still there to be presented again",
        )

    def test_a_beat_counts_from_the_touch_it_reports(self):
        """The heartbeat goes on for five minutes after the last touch. Each
        one says how long ago that was, so a sitting ends thirty minutes after
        the person stopped and not thirty-five."""
        _idle_for(self.client, timedelta(minutes=10))
        self.client.post("/staff-activity/beat", {"page": "/my-plan", "idle": "4"})
        fresh = self.client.session[SlidingSessionMiddleware.TOUCHED_AT]
        self.assertAlmostEqual(fresh, time.time() - 4, delta=3)

        # Four more minutes of beats from the same untouched page.
        store = self.client.session
        store[SlidingSessionMiddleware.TOUCHED_AT] = fresh - 240
        store.save()
        self.client.post("/staff-activity/beat", {"page": "/my-plan", "idle": "244"})
        self.assertEqual(
            self.client.session[SlidingSessionMiddleware.TOUCHED_AT],
            fresh - 240,
            "a beat from an untouched page moved the last use forward",
        )

    def test_a_beat_cannot_claim_more_than_the_threshold_or_less_than_now(self):
        _idle_for(self.client, timedelta(minutes=20))
        self.client.post("/staff-activity/beat", {"page": "/my-plan", "idle": "-900"})
        self.assertLessEqual(
            self.client.session[SlidingSessionMiddleware.TOUCHED_AT], time.time()
        )
        _idle_for(self.client, timedelta(minutes=20))
        self.client.post("/staff-activity/beat", {"page": "/my-plan", "idle": "x"})
        self.assertAlmostEqual(
            self.client.session[SlidingSessionMiddleware.TOUCHED_AT],
            time.time(),
            delta=3,
        )


class StillSignedInTest(TestCase):
    """What an untouched page is told when it asks (/login/state)."""

    def setUp(self):
        self.user = _user("state@edify.test")
        self.client = Client()
        self.client.force_login(self.user)
        self.client.get("/dashboard")

    def test_it_says_how_long_is_left(self):
        _idle_for(self.client, timedelta(minutes=10))
        state = self.client.get("/login/state").json()
        self.assertTrue(state["signedIn"])
        self.assertAlmostEqual(state["remaining"], 20 * 60, delta=5)

    def test_it_says_signed_out_once_the_window_has_passed(self):
        _idle_for(self.client, IDLE_LIMIT + timedelta(seconds=5))
        response = self.client.get("/login/state")
        self.assertEqual(response.json(), {"signedIn": False, "remaining": 0})
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_it_answers_a_browser_that_was_never_signed_in(self):
        response = Client().get("/login/state")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"signedIn": False, "remaining": 0})

    def test_someone_who_must_change_their_password_is_still_answered(self):
        """It sits under /login, which the forced password change lets
        through: the page would otherwise be handed the change form."""
        self.user.must_change_password = True
        self.user.save(update_fields=["must_change_password"])
        self.assertTrue(self.client.get("/login/state").json()["signedIn"])

    def test_the_page_is_told_the_window_it_counts(self):
        body = self.client.get("/dashboard").content.decode()
        self.assertIn(f'data-edify-session-idle="{settings.SESSION_COOKIE_AGE}"', body)


class StreamEndsWithTheSessionTest(TestCase):
    """A live stream is admitted once and then runs by itself, so it is given
    the end of the session it was opened under."""

    def _deadline_in(self, idle: timedelta | None) -> float | None:
        from django.test import RequestFactory

        from apps.realtime.views import _session_deadline

        client = Client()
        client.force_login(_user("stream@edify.test"))
        client.get("/dashboard")
        if idle is not None:
            _idle_for(client, idle)
        request = RequestFactory().get("/api/realtime/stream")
        request.user = get_user_model().objects.get(email="stream@edify.test")
        request.session = client.session
        return _session_deadline(request) - time.monotonic()

    def test_it_closes_when_the_window_does(self):
        self.assertAlmostEqual(
            self._deadline_in(timedelta(minutes=12)), 18 * 60, delta=5
        )

    def test_a_fresh_session_gets_the_whole_window(self):
        self.assertAlmostEqual(
            self._deadline_in(None), settings.SESSION_COOKIE_AGE, delta=5
        )

    def test_a_token_stream_is_left_to_its_token(self):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory

        from apps.realtime.views import _session_deadline

        request = RequestFactory().get("/api/realtime/stream")
        request.user = AnonymousUser()
        self.assertIsNone(_session_deadline(request))


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
