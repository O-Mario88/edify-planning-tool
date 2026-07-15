"""Issue 3 of the audit — dedicated tests proving the unified authentication
lockout policy (AuthenticationLockoutService + LockoutEnforcingModelBackend)
behaves identically across every login surface (web session login, DRF API
login, Django's own /admin/login/ via authenticate()), is race-safe, and
safely migrates the legacy pre-unification lock convention.

See also apps/core/tests/test_admin_user_operations.py for the admin-panel
UI-level lockout/unlock/reset flows, and docs/auth-lockout-policy.md for the
full policy writeup.
"""

from __future__ import annotations

import json
import threading
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.accounts.lockout_service import AuthenticationLockoutService
from apps.accounts.models import User
from apps.core.rbac import EdifyRole
from apps.core.throttling import _window as _rate_window
from apps.notifications.models import Notification

API_LOGIN_URL = "/api/auth/login"
WEB_LOGIN_URL = "/login"


def _max_failed() -> int:
    return getattr(settings, "AUTH_MAX_FAILED_LOGINS", 10)


class LockoutUnificationTest(TestCase):
    def setUp(self):
        # The DRF login endpoint is rate-limited at the same default (10/min)
        # as AUTH_MAX_FAILED_LOGINS -- a fresh window per test keeps that
        # limit from colliding with a *different* test's recent hits on the
        # same test-client IP (the limiter is a process-global in-memory
        # singleton, not reset by TestCase's transaction rollback).
        _rate_window._hits.clear()

    def _create_user(self, email, password="CorrectPassword1!", **extra):
        return User.objects.create_user(
            email=email,
            name=extra.pop("name", "Test User"),
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password=password,
            is_active=True,
            status="active",
            **extra,
        )

    def _api_login(self, email, password):
        return self.client.post(
            API_LOGIN_URL,
            data=json.dumps({"email": email, "password": password}),
            content_type="application/json",
        )

    def _web_login(self, email, password):
        return self.client.post(WEB_LOGIN_URL, {"email": email, "password": password})

    # ── 1. All three surfaces share one policy ──────────────────────────────
    def test_all_login_paths_use_same_lockout_policy(self):
        """Web session login, DRF API login, and Django admin login (proven
        via the literal django.contrib.auth.authenticate() call admin's
        AdminAuthenticationForm makes) all route through the ONE configured
        backend, and locking the account on ANY surface blocks ALL three."""
        backends = list(getattr(settings, "AUTHENTICATION_BACKENDS", []))
        self.assertEqual(
            backends, ["apps.accounts.auth_backend.LockoutEnforcingModelBackend"]
        )

        target = self._create_user("all-paths@edify.test")

        # Lock the account via repeated wrong-password authenticate() calls
        # -- the exact call every one of the three surfaces makes.
        for _ in range(_max_failed()):
            self.assertIsNone(
                authenticate(email="all-paths@edify.test", password="wrong")
            )

        target.refresh_from_db()
        self.assertIsNotNone(target.locked_until)

        # Surface 1: the mechanism /admin/login/ itself uses.
        self.assertIsNone(
            authenticate(email="all-paths@edify.test", password="CorrectPassword1!")
        )

        # Surface 2: web session login.
        res = self._web_login("all-paths@edify.test", "CorrectPassword1!")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "locked")

        # Surface 3: DRF API login.
        res = self._api_login("all-paths@edify.test", "CorrectPassword1!")
        self.assertEqual(res.status_code, 403)

    # ── 2. Atomic increment ──────────────────────────────────────────────────
    def test_failed_logins_increment_atomically(self):
        target = self._create_user("increment@edify.test")
        for i in range(1, _max_failed()):
            state = AuthenticationLockoutService.record_failed_attempt(target.id)
            target.refresh_from_db()
            self.assertEqual(target.failed_login_count, i)
            self.assertFalse(state.locked)

    # ── 3. Temporary lock activates at threshold ─────────────────────────────
    def test_temporary_lock_activates_at_threshold(self):
        target = self._create_user("threshold@edify.test")
        for _ in range(_max_failed()):
            AuthenticationLockoutService.record_failed_attempt(target.id)
        target.refresh_from_db()

        self.assertIsNotNone(target.locked_until)
        self.assertFalse(target.lockout_escalated)
        self.assertEqual(target.failed_login_count, 0)  # reset on lock
        self.assertEqual(target.lockout_cycle_count, 1)

        minutes = getattr(settings, "AUTH_LOCKOUT_DURATION_MINUTES", 15)
        expected = timezone.now() + timedelta(minutes=minutes)
        self.assertAlmostEqual(
            target.locked_until.timestamp(),
            expected.timestamp(),
            delta=10,
        )

    # ── 4. Temporary lock expires ─────────────────────────────────────────────
    def test_temporary_lock_expires(self):
        target = self._create_user("expires@edify.test")
        for _ in range(_max_failed()):
            AuthenticationLockoutService.record_failed_attempt(target.id)
        target.refresh_from_db()
        self.assertIsNotNone(target.locked_until)

        state = AuthenticationLockoutService.check_lockout(target)
        self.assertTrue(state.locked)

        # Simulate the lock window having elapsed.
        target.locked_until = timezone.now() - timedelta(seconds=1)
        target.save(update_fields=["locked_until"])

        state = AuthenticationLockoutService.check_lockout(target)
        self.assertFalse(state.locked)

        # And the correct password now succeeds end-to-end via authenticate().
        user = authenticate(email="expires@edify.test", password="CorrectPassword1!")
        self.assertIsNotNone(user)

    # ── 5. Successful login resets the counter ────────────────────────────────
    def test_successful_login_resets_counter(self):
        target = self._create_user("resets@edify.test")
        for _ in range(_max_failed() - 1):  # stay under the threshold
            AuthenticationLockoutService.record_failed_attempt(target.id)
        target.refresh_from_db()
        self.assertGreater(target.failed_login_count, 0)

        AuthenticationLockoutService.record_success(target.id)
        target.refresh_from_db()
        self.assertEqual(target.failed_login_count, 0)
        self.assertIsNone(target.failed_login_streak_started_at)
        self.assertIsNone(target.locked_until)

    # ── 6. No account-existence leak ──────────────────────────────────────────
    def test_unknown_email_does_not_leak_account_existence(self):
        self._create_user("known@edify.test")

        res_unknown = self._web_login("nobody-here@edify.test", "whatever")
        res_wrong_pw = self._web_login("known@edify.test", "WrongPassword")
        self.assertEqual(res_unknown.status_code, res_wrong_pw.status_code)
        self.assertContains(res_unknown, "Invalid email or password.")
        self.assertContains(res_wrong_pw, "Invalid email or password.")

        _rate_window._hits.clear()
        api_unknown = self._api_login("nobody-here-2@edify.test", "whatever")
        api_wrong_pw = self._api_login("known@edify.test", "AnotherWrongPassword")
        self.assertEqual(api_unknown.status_code, 401)
        self.assertEqual(api_wrong_pw.status_code, 401)
        self.assertEqual(api_unknown.json()["message"], api_wrong_pw.json()["message"])

    # ── 7. API and web login behave identically ───────────────────────────────
    def test_api_and_web_login_have_same_behavior(self):
        web_user = self._create_user("web-lock@edify.test")
        api_user = self._create_user("api-lock@edify.test")

        for _ in range(_max_failed()):
            res = self._web_login("web-lock@edify.test", "WrongPassword")
            self.assertEqual(res.status_code, 200)
        for _ in range(_max_failed()):
            res = self._api_login("api-lock@edify.test", "WrongPassword")
            self.assertEqual(res.status_code, 401)

        web_user.refresh_from_db()
        api_user.refresh_from_db()
        self.assertIsNotNone(web_user.locked_until)
        self.assertIsNotNone(api_user.locked_until)
        self.assertEqual(web_user.lockout_cycle_count, api_user.lockout_cycle_count)
        self.assertEqual(web_user.lockout_escalated, api_user.lockout_escalated)

        # Both now reject the CORRECT password identically (locked, not a
        # credentials error).
        web_res = self._web_login("web-lock@edify.test", "CorrectPassword1!")
        self.assertContains(web_res, "locked")
        api_res = self._api_login("api-lock@edify.test", "CorrectPassword1!")
        self.assertEqual(api_res.status_code, 403)

    # ── 8. Switching endpoints doesn't bypass the lock ─────────────────────────
    def test_switching_login_endpoint_does_not_bypass_lock(self):
        self._create_user("switcher@edify.test")

        # Lock via the WEB endpoint.
        for _ in range(_max_failed()):
            self._web_login("switcher@edify.test", "WrongPassword")

        # Correct password via the API endpoint must still be rejected.
        api_res = self._api_login("switcher@edify.test", "CorrectPassword1!")
        self.assertEqual(api_res.status_code, 403)

        # ...and via the raw authenticate() call (the admin-login mechanism).
        self.assertIsNone(
            authenticate(email="switcher@edify.test", password="CorrectPassword1!")
        )

    # ── 9. Escalation respects configured knobs ────────────────────────────────
    @override_settings(
        AUTH_MAX_FAILED_LOGINS=2,
        AUTH_LOCKOUT_ESCALATION_COUNT=2,
        AUTH_LOCKOUT_ESCALATION_WINDOW_HOURS=24,
        AUTH_REQUIRE_ADMIN_UNLOCK_AFTER_ESCALATION=True,
    )
    def test_repeated_lock_cycles_escalate_when_configured(self):
        admin = User.objects.create_user(
            email="escalation-admin@edify.test",
            name="Escalation Admin",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            password="pwd",
            is_active=True,
            status="active",
        )
        target = self._create_user("escalates@edify.test")

        # Cycle 1: 2 failures -> temporary lock, not yet escalated (count=1 < 2).
        for _ in range(2):
            AuthenticationLockoutService.record_failed_attempt(target.id)
        target.refresh_from_db()
        self.assertFalse(target.lockout_escalated)
        self.assertEqual(target.lockout_cycle_count, 1)

        # Simulate the temporary lock expiring, then trigger cycle 2 within
        # the escalation window -> escalation_count (2) reached.
        target.locked_until = timezone.now() - timedelta(seconds=1)
        target.save(update_fields=["locked_until"])
        for _ in range(2):
            AuthenticationLockoutService.record_failed_attempt(target.id)
        target.refresh_from_db()

        self.assertTrue(target.lockout_escalated)
        self.assertIsNone(target.locked_until)
        self.assertEqual(target.lockout_cycle_count, 2)

        self.assertTrue(
            Notification.objects.filter(
                recipient_id=admin.id,
                source_event_type="account_lockout",
            ).exists()
        )

    # ── 10. Admin unlock ─────────────────────────────────────────────────────
    def test_admin_unlock_works(self):
        actor = User.objects.create_user(
            email="unlocker@edify.test",
            name="Unlocker",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            password="pwd",
            is_active=True,
            status="active",
        )
        target = self._create_user("unlockme@edify.test")
        for _ in range(_max_failed()):
            AuthenticationLockoutService.record_failed_attempt(target.id)
        target.refresh_from_db()
        self.assertIsNotNone(target.locked_until)

        AuthenticationLockoutService.admin_unlock(target.id, actor=actor)
        target.refresh_from_db()
        self.assertIsNone(target.locked_until)
        self.assertFalse(target.lockout_escalated)
        self.assertEqual(target.lockout_cycle_count, 0)
        self.assertEqual(target.failed_login_count, 0)

        user = authenticate(email="unlockme@edify.test", password="CorrectPassword1!")
        self.assertIsNotNone(user)

        from apps.audit.models import AuditLog

        self.assertTrue(
            AuditLog.objects.filter(
                action="auth.admin_unlock", subject_id=target.id
            ).exists()
        )

    # ── 11. Manual admin lock ────────────────────────────────────────────────
    def test_manual_admin_lock_works(self):
        actor = User.objects.create_user(
            email="locker@edify.test",
            name="Locker",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            password="pwd",
            is_active=True,
            status="active",
        )
        target = self._create_user("lockmenow@edify.test")
        self.assertIsNone(
            authenticate(email="lockmenow@edify.test", password="wrong-first")
        )  # sanity, no lock yet
        target.refresh_from_db()
        self.assertFalse(target.lockout_escalated)

        AuthenticationLockoutService.admin_lock(
            target.id, actor=actor, reason="Suspected compromise."
        )
        target.refresh_from_db()
        self.assertTrue(target.lockout_escalated)

        self.assertIsNone(
            authenticate(email="lockmenow@edify.test", password="CorrectPassword1!")
        )

        from apps.audit.models import AuditLog

        entry = AuditLog.objects.get(action="auth.admin_lock", subject_id=target.id)
        self.assertEqual(entry.reason, "Suspected compromise.")

    # ── 13. Legacy lock records migrate safely ──────────────────────────────
    def test_legacy_lock_records_are_migrated_safely(self):
        from io import StringIO

        legacy = self._create_user("legacy@edify.test")
        legacy.locked_until = timezone.now() + timedelta(
            days=36500
        )  # the old "permanent lock"
        legacy.lockout_escalated = False
        legacy.save(update_fields=["locked_until", "lockout_escalated"])

        recent = self._create_user("recent-lock@edify.test")
        recent.locked_until = timezone.now() + timedelta(
            minutes=10
        )  # a normal temp lock
        recent.save(update_fields=["locked_until"])

        out = StringIO()
        call_command("repair_legacy_lock_records", "--dry-run", stdout=out)
        self.assertIn("legacy@edify.test", out.getvalue())
        legacy.refresh_from_db()
        self.assertFalse(legacy.lockout_escalated)  # dry run touched nothing

        out = StringIO()
        call_command("repair_legacy_lock_records", stdout=out)
        legacy.refresh_from_db()
        recent.refresh_from_db()
        self.assertTrue(legacy.lockout_escalated)
        self.assertEqual(legacy.lockout_cycle_count, 1)
        self.assertFalse(recent.lockout_escalated)  # untouched -- not a legacy row

        # Idempotent: running again finds nothing left to do.
        out = StringIO()
        call_command("repair_legacy_lock_records", stdout=out)
        self.assertIn("No inconsistent legacy lock records found", out.getvalue())
        legacy.refresh_from_db()
        self.assertEqual(legacy.lockout_cycle_count, 1)  # not double-touched

    # ── Bonus: System Health check + the admin-reset regression fix ─────────
    def test_health_check_detects_legacy_lock_inconsistency(self):
        from apps.accounts.health import auth_lockout_health

        clean = auth_lockout_health()
        legacy_check = next(
            c for c in clean["checks"] if c["key"] == "legacy_lock_records"
        )
        self.assertEqual(legacy_check["severity"], "ok")

        legacy = self._create_user("unhealthy@edify.test")
        legacy.locked_until = timezone.now() + timedelta(days=36500)
        legacy.save(update_fields=["locked_until"])

        dirty = auth_lockout_health()
        legacy_check = next(
            c for c in dirty["checks"] if c["key"] == "legacy_lock_records"
        )
        self.assertEqual(legacy_check["severity"], "critical")
        self.assertIn("unhealthy@edify.test", legacy_check["current_state"])

    def test_admin_password_reset_clears_escalation(self):
        """Regression test: the admin 'reset_password' action used to
        hand-clear only failed_login_count/locked_until, leaving an
        escalated account's lockout_escalated flag set -- so the user still
        couldn't log in after their "reset". It must now fully delegate to
        AuthenticationLockoutService.admin_unlock()."""
        admin = User.objects.create_user(
            email="reset-admin@edify.test",
            name="Reset Admin",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            password="pwd",
            is_active=True,
            status="active",
        )
        target = self._create_user("escalated-reset@edify.test")
        AuthenticationLockoutService.admin_lock(target.id, actor=admin, reason="test")
        target.refresh_from_db()
        self.assertTrue(target.lockout_escalated)

        self.client.force_login(admin)
        res = self.client.post(
            f"/admin-panel/users/{target.id}",
            {"action": "reset_password", "new_password": "BrandNewPassword1!"},
        )
        self.assertEqual(res.status_code, 302)

        target.refresh_from_db()
        self.assertFalse(target.lockout_escalated)
        self.assertIsNone(target.locked_until)
        user = authenticate(
            email="escalated-reset@edify.test", password="BrandNewPassword1!"
        )
        self.assertIsNotNone(user)


class ConcurrentLockoutTest(TransactionTestCase):
    """TransactionTestCase + real threads: a plain TestCase wraps everything
    in one transaction and can't reproduce genuinely concurrent DB
    transactions racing on the same row."""

    # TransactionTestCase truncates every table after each test, which would
    # otherwise silently wipe migration-seeded rows (e.g. the default
    # TargetArea set) that other test modules in the same run depend on.
    # serialized_rollback=True would only restore that seeded state
    # transiently in THIS class's own setUp (not permanently -- under
    # --keepdb the next `manage.py test` invocation reuses a database left
    # flushed), AND it collides with the explicit reseed below (Django
    # inserts the ORIGINAL serialized snapshot's rows on top of what the
    # previous test's teardown already reseeded -- duplicate-key IntegrityError
    # on CostCatalogue's natural-key unique constraint). Deliberately NOT
    # using serialized_rollback; _post_teardown is the single source of
    # truth that leaves the kept database in a good state either way --
    # matches the DisbursementDoubleClickRaceTest pattern.

    def _post_teardown(self):
        super()._post_teardown()
        from apps.core.test_seed_utils import reseed_migration_data

        reseed_migration_data()

    def test_concurrent_failed_attempts_do_not_bypass_threshold(self):
        target = User.objects.create_user(
            email="race@edify.test",
            name="Race Target",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="CorrectPassword1!",
            is_active=True,
            status="active",
        )
        n = _max_failed()
        errors = []

        def attempt():
            try:
                AuthenticationLockoutService.record_failed_attempt(target.id)
            except Exception as exc:  # noqa: BLE001 — surfaced via `errors`, not swallowed
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=attempt) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        target.refresh_from_db()
        # Exactly one lock cycle fired from exactly `n` concurrent failures --
        # select_for_update serializes the increments so none are lost and
        # none double-count past the threshold.
        self.assertEqual(target.lockout_cycle_count, 1)
        self.assertEqual(target.failed_login_count, 0)
        self.assertIsNotNone(target.locked_until)
        self.assertFalse(target.lockout_escalated)
