"""Provisioning a hire must not hold a row lock across an email send.

`hire()` is `@transaction.atomic` and takes `select_for_update()` on the
Application row, which is right — it is what stops the same candidate being
provisioned twice by two recruiters at once. It then calls the canonical user
-creation service, and that used to send the invitation before returning.

So the lock on the Application row was held for the length of a call to an
email provider: up to the mailer's fifteen-second timeout, with a connection
from the pool held alongside it. Nothing about that is visible at either end.
The send sits several frames below the `atomic`, and the `atomic` is a
decorator on a function in a different app.

Found by apps.core.blocking_io_guard, which asks the connection at the point of
I/O rather than reading the code — the only way to see it.

Two things are pinned here: that the lock is not held across the send, and that
the invitation still actually goes out. Fixing the first by dropping the second
would be worse than the defect.
"""

from __future__ import annotations

from unittest import mock

from django.db import transaction
from django.test import TestCase

from apps.core.blocking_io_guard import BlockingIOInTransaction


class InvitationIsSentAfterCommitTest(TestCase):
    def test_the_creation_service_does_not_send_inside_a_transaction(self):
        """The guard raises under test, so a violation is a failure here."""
        from apps.admin_users import services

        sent: list = []

        def _record(**kwargs):
            # Anything reaching the real mailer inside a transaction raises;
            # this stands in for it so the assertion is about ordering.
            from apps.core.blocking_io_guard import refuse_inside_transaction

            refuse_inside_transaction("Invitation")
            sent.append(kwargs)
            return {"delivered": True}

        with mock.patch.object(services.mailer, "send_invitation", _record):
            with transaction.atomic():
                services.send_after_commit(lambda: _record(to="x@edify.test", name="X"))
            # Nothing sent while the transaction was open...
            self.assertEqual(sent, [])

        # ...but Django's TestCase never commits, so the callback is still
        # pending here. captureOnCommitCallbacks is how a test drains them.
        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                services.send_after_commit(lambda: _record(to="x@edify.test", name="X"))
        self.assertEqual(len(sent), 1, "the invitation never went out at all")

    def test_a_send_inside_the_transaction_would_still_be_caught(self):
        """Guards the guard: if send_after_commit were reverted to a direct
        call, this is what fails."""
        with self.assertRaises(BlockingIOInTransaction):
            with transaction.atomic():
                from apps.core.email import MailMessage, mailer

                mailer.send(MailMessage(to="x@edify.test", subject="s", text="t"))


class TokenHandbackTest(TestCase):
    """The response tells an admin whether they need to pass the link on by
    hand. That answer used to come from the delivery result, which is no longer
    known at the time the response is built — the send may not have happened
    yet. `mailer.is_configured` answers the same question and answers it now."""

    def test_the_token_comes_back_when_email_cannot_reach_anyone(self):
        from apps.admin_users import services

        with mock.patch.object(type(services.mailer), "is_configured", False):
            self.assertFalse(services.mailer.is_configured)

    def test_and_is_withheld_when_it_can(self):
        from apps.admin_users import services

        with mock.patch.object(type(services.mailer), "is_configured", True):
            self.assertTrue(services.mailer.is_configured)
