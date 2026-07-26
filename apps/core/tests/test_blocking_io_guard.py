"""The guard has to be right in both directions.

A guard that never fires is decoration. A guard that fires on the test
harness's own transaction is worse — it fails builds for a condition that is
not there, and the fix people reach for is deleting the guard.

The first version of this one did exactly that: it assumed a savepoint depth of
0 meant "only the harness", which is true under `TransactionTestCase` and wrong
under `TestCase`, where the harness already holds one. It reported two ordinary
password-reset sends as lock-holding violations. So both directions are pinned
here, under both harnesses.
"""

from __future__ import annotations

from unittest import mock

from django.db import transaction
from django.test import TestCase, TransactionTestCase

from apps.core.blocking_io_guard import (
    BlockingIOInTransaction,
    refuse_inside_transaction,
)
from apps.core.email import MailMessage, mailer
from apps.core.sms import SmsMessage, sms


class QuietOnTheHarnessTest(TestCase):
    """`TestCase` holds a transaction of its own. That is not a violation."""

    def test_a_bare_send_is_allowed(self):
        refuse_inside_transaction("nothing in particular")

    def test_the_real_mailer_can_send(self):
        mailer.send(MailMessage(to="x@edify.test", subject="s", text="t"))

    def test_the_real_sms_sender_can_send(self):
        sms.send(SmsMessage(to="+256700000000", text="t"))


class QuietOnTheOtherHarnessTest(TransactionTestCase):
    """`TransactionTestCase` holds none. Also not a violation."""

    def test_a_bare_send_is_allowed(self):
        refuse_inside_transaction("nothing in particular")

    def test_the_real_mailer_can_send(self):
        mailer.send(MailMessage(to="x@edify.test", subject="s", text="t"))


class FiresOnARealViolationTest(TestCase):
    def test_a_send_inside_an_application_transaction_is_refused(self):
        with self.assertRaises(BlockingIOInTransaction):
            with transaction.atomic():
                refuse_inside_transaction("Email to someone")

    def test_the_mailer_itself_is_wired_to_it(self):
        """Not just the helper — the actual send path."""
        with self.assertRaises(BlockingIOInTransaction):
            with transaction.atomic():
                mailer.send(MailMessage(to="x@edify.test", subject="s", text="t"))

    def test_the_sms_sender_is_wired_to_it(self):
        with self.assertRaises(BlockingIOInTransaction):
            with transaction.atomic():
                sms.send(SmsMessage(to="+256700000000", text="t"))

    def test_it_reaches_through_a_call_chain(self):
        """The whole reason this is a runtime guard rather than a grep: the
        send is normally several frames below the atomic that opened."""

        def deep():
            mailer.send(MailMessage(to="x@edify.test", subject="s", text="t"))

        def middle():
            deep()

        with self.assertRaises(BlockingIOInTransaction):
            with transaction.atomic():
                middle()

    def test_nesting_below_the_harness_still_counts(self):
        with self.assertRaises(BlockingIOInTransaction):
            with transaction.atomic():
                with transaction.atomic():
                    refuse_inside_transaction("Email to someone")


class FiresOnARealViolationWithoutTheHarnessTest(TransactionTestCase):
    def test_a_send_inside_an_application_transaction_is_refused(self):
        with self.assertRaises(BlockingIOInTransaction):
            with transaction.atomic():
                refuse_inside_transaction("Email to someone")


class ProductionDegradesRatherThanBreaksTest(TestCase):
    """Outside tests this must not raise. The send is already committed to by
    the time it reaches here; refusing it would turn a latency problem into a
    person never receiving their sign-in code."""

    def test_it_logs_and_proceeds(self):
        with mock.patch(
            "apps.core.blocking_io_guard._tests_are_running", lambda: False
        ):
            with transaction.atomic():
                with self.assertLogs("edify.blocking_io", level="WARNING") as logs:
                    refuse_inside_transaction("Email to someone")
        self.assertIn("on_commit", "\n".join(logs.output))

    def test_the_advice_names_the_fix(self):
        """A warning nobody knows how to action is noise."""
        with mock.patch(
            "apps.core.blocking_io_guard._tests_are_running", lambda: False
        ):
            with transaction.atomic():
                with self.assertLogs("edify.blocking_io", level="WARNING") as logs:
                    mailer.send(MailMessage(to="x@edify.test", subject="s", text="t"))
        joined = "\n".join(logs.output)
        self.assertIn("transaction.on_commit()", joined)
        self.assertIn("x@edify.test", joined)
