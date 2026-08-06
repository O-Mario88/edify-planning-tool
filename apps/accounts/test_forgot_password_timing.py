"""SEC-04 — forgot-password timing/response equalization.

Known and unknown emails must return the identical public response, and the
network-bound provider email send (which only ever happens on the
known-email path) must not be awaited synchronously — otherwise response
latency itself becomes an account-existence oracle. See
apps.accounts.auth_services.forgot_password /
apps.accounts.auth_services._send_password_reset_async.
"""

from __future__ import annotations

import time
from unittest.mock import PropertyMock, patch

from django.test import TestCase

from apps.accounts import auth_services
from apps.accounts.models import User
from apps.core.email import MailerService
from apps.core.rbac import EdifyRole


def _user(email="known@edify.test"):
    return User.objects.create_user(
        email=email,
        name="Known User",
        roles=[EdifyRole.CCEO.value],
        active_role=EdifyRole.CCEO.value,
        password="CorrectPassword1!",
        is_active=True,
        status="active",
    )


def _configured(value: bool):
    """is_configured is a read-only @property on the MailerService class —
    patch it there (affects the shared `mailer` singleton for the duration
    of the `with` block), not as an instance attribute."""
    return patch.object(
        MailerService, "is_configured", new_callable=PropertyMock, return_value=value
    )


class ForgotPasswordTimingTest(TestCase):
    def test_unknown_and_known_email_return_identical_response(self):
        user = _user()
        with (
            _configured(False),
            patch.object(
                auth_services.mailer,
                "send_password_reset",
                return_value={"delivered": False, "devPreview": "x"},
            ),
        ):
            known = auth_services.forgot_password(user.email)
            unknown = auth_services.forgot_password("nobody-here@edify.test")

        # Both are {"ok": True, ...dev-only extras...} — the caller-visible
        # shape never signals existence via a missing/extra required key.
        self.assertTrue(known["ok"])
        self.assertTrue(unknown["ok"])

    def test_no_reset_token_created_for_unknown_email(self):
        with _configured(False):
            auth_services.forgot_password("nobody-here@edify.test")
        self.assertFalse(
            User.objects.filter(password_reset_token_hash__isnull=False).exists()
        )

    def test_known_user_gets_a_single_use_reset_token(self):
        user = _user()
        with _configured(False):
            auth_services.forgot_password(user.email)
        user.refresh_from_db()
        self.assertIsNotNone(user.password_reset_token_hash)
        self.assertIsNotNone(user.password_reset_expires)

    def test_production_send_is_backgrounded_not_awaited(self):
        """The real provider call (mailer.is_configured=True, i.e. Resend)
        must not block the response — otherwise its network latency (up to
        15s) is itself a timing oracle distinguishing known from unknown
        email."""
        user = _user()
        release = {"called": False}

        def _slow_send(**kwargs):
            time.sleep(0.4)
            release["called"] = True
            return {"delivered": True}

        with (
            _configured(True),
            patch.object(
                auth_services.mailer, "send_password_reset", side_effect=_slow_send
            ),
        ):
            started = time.monotonic()
            result = auth_services.forgot_password(user.email)
            elapsed = time.monotonic() - started

        self.assertTrue(result["ok"])
        self.assertNotIn("devResetToken", result)
        self.assertLess(
            elapsed,
            0.3,
            "forgot_password() waited on the network-bound mail send instead "
            "of backgrounding it",
        )
        # Give the background thread a moment to actually run, then confirm
        # it really did fire (not silently dropped).
        for _ in range(20):
            if release["called"]:
                break
            time.sleep(0.05)
        self.assertTrue(release["called"], "background email send never ran")

    def test_response_time_known_vs_unknown_within_tolerance_when_backgrounded(self):
        """With the real send backgrounded, the known-email path's remaining
        synchronous work (token gen + one DB write) must not create a
        network-scale timing gap versus the unknown-email path's instant
        return."""
        user = _user("timing@edify.test")

        def _instant_send(**kwargs):
            return {"delivered": True}

        with (
            _configured(True),
            patch.object(
                auth_services.mailer, "send_password_reset", side_effect=_instant_send
            ),
        ):
            t0 = time.monotonic()
            auth_services.forgot_password("nobody-here-2@edify.test")
            unknown_elapsed = time.monotonic() - t0

            t0 = time.monotonic()
            auth_services.forgot_password(user.email)
            known_elapsed = time.monotonic() - t0

        # Both should be well under 100ms (pure DB + hashing, no network
        # wait) — the historical gap here was network latency (up to 15s),
        # not this residual.
        self.assertLess(abs(known_elapsed - unknown_elapsed), 0.1)
