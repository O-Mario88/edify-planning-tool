"""Audit rows written inside a caller's transaction are chained at commit.

The chain lock used to be taken inside the caller's transaction and held until
it committed, so one long unit of work (a bulk schedule, a batch approval)
kept every other audited action on the platform waiting (2026-09-13 peak-load
audit: six visits held an unrelated audit write for four seconds).
"""

from __future__ import annotations

import threading
import time

from django.db import connections, transaction
from django.test import TestCase, TransactionTestCase

from apps.audit.models import AuditLog
from apps.audit.services import log, seal_pending, verify_chain


def _close_connections():
    for db_connection in connections.all():
        db_connection.close()


class CommitTimeSealTest(TransactionTestCase):
    reset_sequences = False

    def test_a_row_written_in_a_transaction_is_chained_when_it_commits(self):
        with transaction.atomic():
            log(action="audit.seal_probe", subject_kind="Probe", subject_id="1")
            inside = AuditLog.objects.get(action="audit.seal_probe")
            self.assertIsNone(inside.seq, "the chain lock is not taken mid-transaction")
        sealed = AuditLog.objects.get(action="audit.seal_probe")
        self.assertIsNotNone(sealed.seq)
        self.assertIsNotNone(sealed.hash)
        self.assertTrue(verify_chain(full=True)["ok"])

    def test_a_rolled_back_transaction_leaves_no_audit_row(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                log(action="audit.rolled_back_probe")
                raise RuntimeError("the unit of work failed")
        self.assertFalse(
            AuditLog.objects.filter(action="audit.rolled_back_probe").exists()
        )

    def test_a_long_transaction_no_longer_holds_other_audit_writes(self):
        logged = threading.Event()
        release = threading.Event()
        waits = {}

        def long_unit_of_work():
            try:
                with transaction.atomic():
                    log(action="audit.long_unit", subject_id="long")
                    logged.set()
                    release.wait(10)
            finally:
                _close_connections()

        def unrelated_action():
            try:
                logged.wait(10)
                started = time.monotonic()
                log(action="audit.unrelated", subject_id="other")
                waits["unrelated"] = time.monotonic() - started
            finally:
                _close_connections()

        worker = threading.Thread(target=long_unit_of_work)
        other = threading.Thread(target=unrelated_action)
        worker.start()
        other.start()
        other.join(10)
        release.set()
        worker.join(10)

        self.assertLess(
            waits["unrelated"],
            2.0,
            "the unrelated write waited on the open transaction",
        )
        rows = AuditLog.objects.filter(
            action__in=["audit.long_unit", "audit.unrelated"]
        )
        self.assertEqual(
            rows.filter(seq__isnull=True).count(), 0, "both rows are chained"
        )
        self.assertEqual(rows.values("seq").distinct().count(), 2)
        self.assertTrue(verify_chain(full=True)["ok"])

    def test_every_call_of_a_decorated_save_is_chained_when_it_commits(self):
        """A decorated function reuses one atomic block for every call.

        The seal used to be marked on that block, so after the first call
        each later call's rows waited unsealed for some other commit.
        """

        @transaction.atomic
        def decorated_save(n):
            log(action="audit.decorated_save", subject_id=str(n))

        for n in range(3):
            decorated_save(n)
            row = AuditLog.objects.get(action="audit.decorated_save", subject_id=str(n))
            self.assertIsNotNone(row.seq, f"call {n + 1} was chained at its commit")
        self.assertTrue(verify_chain(full=True)["ok"])

    def test_a_seal_lost_with_a_rolled_back_savepoint_is_registered_again(self):
        with transaction.atomic():
            try:
                with transaction.atomic():
                    log(action="audit.undone_probe")
                    raise RuntimeError("the inner step failed")
            except RuntimeError:
                pass
            log(action="audit.kept_probe")
        self.assertFalse(AuditLog.objects.filter(action="audit.undone_probe").exists())
        kept = AuditLog.objects.get(action="audit.kept_probe")
        self.assertIsNotNone(kept.seq, "the kept row was chained at the commit")
        self.assertTrue(verify_chain(full=True)["ok"])

    def test_the_scheduled_seal_chains_rows_whose_commit_seal_never_ran(self):
        log(action="audit.chained_first")
        AuditLog.objects.create(action="audit.orphaned_unsealed", subject_id="x")
        self.assertTrue(verify_chain(full=True)["ok"], "unsealed rows are not a break")
        self.assertEqual(seal_pending(), 1)
        self.assertEqual(seal_pending(), 0)
        orphan = AuditLog.objects.get(action="audit.orphaned_unsealed")
        self.assertIsNotNone(orphan.seq)
        self.assertTrue(verify_chain(full=True)["ok"])
        # A direct append after the seal continues the same chain.
        log(action="audit.chained_after")
        self.assertTrue(verify_chain(full=True)["ok"])


class TestCaseAppendsStayImmediateTest(TestCase):
    def test_a_direct_append_in_a_test_case_is_chained_at_once(self):
        """TestCase's wrapping transaction never commits, so it must not defer."""
        log(action="audit.testcase_probe")
        row = AuditLog.objects.get(action="audit.testcase_probe")
        self.assertIsNotNone(row.seq)
        self.assertIsNotNone(row.hash)
