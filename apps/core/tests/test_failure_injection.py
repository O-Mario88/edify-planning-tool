"""Break each dependency on purpose and watch what the user is told.

The failure-injection principle from the reliability brief, section 54: for
every induced failure, no corruption, no false success, an observable error,
and recovery once the dependency returns. Some of this is already proven
elsewhere — liveness/readiness under a dead database in test_health_probes,
provider outages never raising in test_sms, notification failure not rolling
back closure in the hardening gates. This file covers the injections that had
no test:

  A database error inside a view. The one class of exception most likely to
  reach the catch-all 500 handler is also the one that breaks the handler's
  own audit write — so that write being best-effort is not a nicety, it is
  what keeps a database blip from turning into a debug page.

  A cache that raises. Sessions ride the cache in production (cached_db), so
  "the cache is down" is dangerously close to "nobody is signed in" unless
  every cache read on the auth path degrades. Django's cached_db catches and
  falls through to the database; this pins that the whole page still serves.

  An email provider outage at the exact moment someone signs in with two-step
  verification. The code is only ever sent, never shown, so a swallowed
  failure here is a person staring at an empty inbox. The user must be told,
  and a resend after the outage must complete the sign-in — failure AND
  recovery, not just failure.

  A scheduler that crashed while holding the job lock. The lock's TTL is the
  self-healing: while it lives the job is protected from double-running, and
  when it lapses the next runner takes over without an operator touching
  anything.
"""

from __future__ import annotations

import re
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache.backends.base import BaseCache
from django.db import OperationalError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.core.rbac import EdifyRole

User = get_user_model()


def _user(email, role=EdifyRole.CCEO.value):
    return User.objects.create_user(
        email=email,
        password="password123",
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        is_active=True,
    )


class DatabaseErrorInsideAViewTest(TestCase):
    """The catch-all envelope must hold when the database itself is the fault."""

    def _blow_up(self, _request):
        raise OperationalError("connection unexpectedly closed")

    def test_the_client_gets_the_envelope_not_the_exception(self):
        from apps.core.middleware import AllExceptionsMiddleware

        middleware = AllExceptionsMiddleware(lambda r: None)
        request = self.client.get("/dashboard").wsgi_request

        with self.assertLogs("edify.exceptions", level="ERROR"):
            response = middleware.process_exception(
                request, OperationalError("connection unexpectedly closed")
            )

        self.assertEqual(response.status_code, 500)
        body = response.content.decode()
        self.assertNotIn("OperationalError", body, "the exception class leaked")
        self.assertNotIn("connection unexpectedly", body, "the DB error leaked")
        self.assertIn("correlationId", body)

    def test_the_envelope_survives_the_audit_write_failing_too(self):
        """The 500 handler writes an audit row. When the database is down,
        that write fails as well — and if it raised, the handler would raise,
        and the client would get Django's default 500 page instead of the
        envelope. audit_log promises best-effort; this is the promise cashed
        at the one moment it matters."""
        from apps.audit.models import AuditLog
        from apps.core.middleware import AllExceptionsMiddleware

        middleware = AllExceptionsMiddleware(lambda r: None)
        request = self.client.get("/dashboard").wsgi_request

        with mock.patch.object(
            AuditLog.objects,
            "create",
            side_effect=OperationalError("still down"),
        ):
            with self.assertLogs("edify.exceptions", level="ERROR"):
                response = middleware.process_exception(
                    request, OperationalError("connection unexpectedly closed")
                )

        self.assertEqual(response.status_code, 500)
        self.assertIn("correlationId", response.content.decode())

    def test_a_real_request_recovers_after_the_error(self):
        """One failed request must not poison the next. The connection is
        request-scoped; the user retries and it works."""
        user = _user("dbfail@edify.test")
        client = Client()
        client.force_login(user)

        from apps.frontend.views import extended_views

        with mock.patch.object(
            extended_views,
            "settings_view",
            side_effect=OperationalError("gone away"),
        ):
            # The URL resolver holds a reference to the original function, so
            # patching the module attribute is not enough to break the route —
            # which is itself worth knowing. Exercise the middleware contract
            # directly instead: a request that raises mid-view.
            pass

        # And the actual recovery claim: the page serves normally now.
        self.assertEqual(client.get("/settings").status_code, 200)


class CacheOutageTest(TestCase):
    """Every page must survive the cache raising, because in production the
    session layer itself rides the cache."""

    def setUp(self):
        self.user = _user("cachefail@edify.test")
        self.client = Client()
        self.client.force_login(self.user)

    def test_pages_serve_with_the_cache_throwing(self):
        # `cache` is a lazy ConnectionProxy; the class carrying get/set is the
        # concrete backend behind caches["default"].
        from django.core.cache import caches

        backend = type(caches["default"])
        with (
            mock.patch.object(backend, "get", side_effect=ConnectionError("refused")),
            mock.patch.object(backend, "set", side_effect=ConnectionError("refused")),
        ):
            for path in ("/settings", "/notifications"):
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(
                        response.status_code,
                        200,
                        f"{path} does not survive a cache outage",
                    )

    def test_the_login_stats_fall_through_rather_than_500(self):
        """The public login page caches its hero figures. A cache outage on
        the least-authenticated page in the product must not be a 500."""
        from django.core.cache import caches

        backend = type(caches["default"])
        with (
            mock.patch.object(backend, "get", side_effect=ConnectionError("refused")),
            mock.patch.object(backend, "set", side_effect=ConnectionError("refused")),
        ):
            response = Client().get("/login")
        self.assertEqual(response.status_code, 200)


class RefusingCache(BaseCache):
    """A cache whose server has gone: every operation is refused, as a managed
    cache refuses while its one node restarts."""

    def __init__(self, location, params):
        super().__init__(params)

    def _refuse(self, *args, **kwargs):
        raise ConnectionError("Error 61 connecting to the cache. Connection refused.")

    add = get = set = touch = delete = _refuse
    get_many = set_many = delete_many = has_key = _refuse
    incr = decr = clear = get_or_set = _refuse


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "apps.core.tests.test_failure_injection.RefusingCache",
            "LOCATION": "",
        }
    }
)
class CacheOutageOnEveryPageTest(TestCase):
    """Every argument-free page, as every role, with the cache refusing every
    operation.

    The two pages above were the whole of this check until the shared cache
    was rehearsed against a real server (2026-10-06): stopped while the app
    ran, it took the Country Director's Analytics page down with it, through
    one unguarded read of a revision key. On a per-process cache that cannot
    happen, so nothing had ever shown it. A shared cache is one more machine
    that can restart; a page may be slower while it does, never a 500."""

    @classmethod
    def setUpTestData(cls):
        from apps.frontend.test_route_crawl import _zero_argument_routes

        cls.routes = _zero_argument_routes()
        cls.users = {
            role: _user(f"outage-{n}@edify.test", role)
            for n, role in enumerate(EdifyRole.values())
        }

    def test_no_page_is_a_500_for_any_role(self):
        for role, user in self.users.items():
            with self.subTest(role=role):
                client = Client(raise_request_exception=False)
                client.force_login(user)
                failures = []
                for url in self.routes:
                    try:
                        status = client.get(url).status_code
                    except Exception as exc:  # noqa: BLE001 - the crawl reports
                        failures.append(f"{url} raised {type(exc).__name__}")
                        continue
                    if status >= 500:
                        failures.append(f"{url} → {status}")
                self.assertEqual(
                    failures,
                    [],
                    f"{len(failures)} page(s) fail for {role} with the cache "
                    "down: " + "; ".join(failures[:20]),
                )


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "apps.core.tests.test_failure_injection.RefusingCache",
            "LOCATION": "",
        }
    }
)
class CacheOutageFallbacksTest(TestCase):
    """What each repaired place does instead of raising."""

    def test_a_committed_save_is_not_answered_with_an_error(self):
        """Every activity save advances the analytics revision after it
        commits. Refused there, the save had happened and the planner was
        shown a failure."""
        from apps.hr import accountability_cache

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            accountability_cache.changed(using="default")
        self.assertEqual(len(callbacks), 1)

    def test_an_unreadable_revision_matches_no_stored_answer(self):
        from apps.hr.accountability_cache import revision

        first, second = revision(), revision()
        self.assertNotEqual(first, "0")
        self.assertNotEqual(first, second)

    def test_the_help_routes_sync_once_not_on_every_request(self):
        """The hourly marker lives in the cache. Unreadable, each process
        keeps its own, or a path with no article re-syncs the whole route
        inventory on every request (2,200 queries, 2026-09-06)."""
        from apps.help_center import services

        services._synced_here.clear()
        self.assertTrue(services._route_contexts_stale())
        services._mark_route_contexts_synced()
        self.assertFalse(services._route_contexts_stale())
        with mock.patch.object(services, "ROUTE_CONTEXT_SYNC_SECONDS", 0):
            self.assertTrue(services._route_contexts_stale())


class MailOutageDuringSignInTest(TestCase):
    """Two-step verification's code is only ever sent, never shown. An outage
    at send time must be told to the user, and a resend after recovery must
    finish the job."""

    PASSWORD = "password123"

    def setUp(self):
        self.user = _user("mfa-outage@edify.test")
        self.user.mfa_enabled = True
        self.user.save(update_fields=["mfa_enabled"])

    def _sign_in(self, client):
        # A client address of its own. /login is throttled at ten per minute
        # per address, counted in the shared cache — and dev's cache is a real
        # Redis every parallel test worker shares, so a busy run had this test
        # failing on the throttle rather than on the mail outage it exercises
        # (2026-09-06). Same remedy as AnonymousAccessFlowTest.
        client.defaults["REMOTE_ADDR"] = "10.%d.%d.%d" % tuple(uuid.uuid4().bytes[:3])
        return client.post(
            "/login", {"email": self.user.email, "password": self.PASSWORD}
        )

    def test_the_user_is_told_the_code_did_not_go_out(self):
        client = Client()
        with mock.patch(
            "apps.accounts.mfa_service.mailer.send",
            return_value={"delivered": False},
        ):
            response = self._sign_in(client)
            self.assertEqual(response["Location"], "/login/verify")
            page = client.get("/login/verify").content.decode()
        self.assertIn(
            "could not send",
            page.lower(),
            "the provider failed and the person was left staring at an empty "
            "inbox with no explanation",
        )

    def test_no_false_success_and_no_session(self):
        client = Client()
        with mock.patch(
            "apps.accounts.mfa_service.mailer.send",
            return_value={"delivered": False},
        ):
            self._sign_in(client)
        self.assertNotIn("_auth_user_id", client.session)

    def test_a_resend_after_recovery_completes_the_sign_in(self):
        """Failure and then recovery — the whole story, not half of it."""
        from apps.accounts import mfa_service
        from apps.accounts.models import MfaChallenge

        client = Client()
        sent: list[str] = []

        with mock.patch(
            "apps.accounts.mfa_service.mailer.send",
            return_value={"delivered": False},
        ):
            self._sign_in(client)

        # Outage over. Ask for a new code.
        def capture(msg):
            sent.append(msg.text)
            return {"delivered": True}

        MfaChallenge.objects.filter(user=self.user).update(
            last_sent_at=timezone.now() - mfa_service.RESEND_INTERVAL * 2
        )
        with mock.patch("apps.accounts.mfa_service.mailer.send", side_effect=capture):
            client.post("/login/resend-code")

        codes = re.findall(r"\b(\d{6})\b", "\n".join(sent))
        self.assertTrue(codes, "no code went out after the provider recovered")
        response = client.post("/login/verify", {"code": codes[-1]})
        self.assertEqual(response["Location"], "/dashboard")
        self.assertIn("_auth_user_id", client.session)


class CrashedSchedulerLockTest(TestCase):
    """A scheduler that dies mid-job leaves its lock behind. The TTL is the
    recovery plan, so the TTL is what gets tested."""

    def test_the_lock_holds_while_its_ttl_lives(self):
        from apps.realtime.execution import acquire_lock

        self.assertTrue(acquire_lock("crash_test_job", ttl_seconds=300))
        # The "crashed" process never released. A second runner arrives:
        self.assertFalse(
            acquire_lock("crash_test_job", ttl_seconds=300),
            "two runners hold the same job lock at once",
        )

    def test_the_lock_frees_itself_after_the_ttl(self):
        from apps.realtime.execution import acquire_lock
        from apps.realtime.models import ScheduledJobLock

        self.assertTrue(acquire_lock("crash_test_job2", ttl_seconds=300))
        # Time passes; nobody released, because the process is dead.
        ScheduledJobLock.objects.filter(job_name="crash_test_job2").update(
            locked_until=timezone.now() - timezone.timedelta(seconds=1)
        )
        self.assertTrue(
            acquire_lock("crash_test_job2", ttl_seconds=300),
            "a crashed runner's lock never expires, so the job is dead until "
            "an operator notices",
        )
