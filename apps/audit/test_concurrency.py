"""Concurrency guarantees for the tamper-evident audit chain."""

from __future__ import annotations

import threading

from django.db import connections
from django.test import TransactionTestCase

from apps.audit.models import AuditLog
from apps.audit.services import log, verify_chain


class ConcurrentAuditAppendTest(TransactionTestCase):
    reset_sequences = False

    def test_every_concurrent_append_is_retained_in_one_valid_chain(self):
        workers = 8
        barrier = threading.Barrier(workers)
        failures: list[Exception] = []

        def append(index: int) -> None:
            try:
                barrier.wait(timeout=10)
                log(
                    action="audit.concurrency_probe",
                    subject_kind="AuditProbe",
                    subject_id=str(index),
                    payload={"index": index},
                )
            except Exception as exc:  # pragma: no cover - assertion reports it
                failures.append(exc)
            finally:
                for db_connection in connections.all():
                    db_connection.close()

        threads = [
            threading.Thread(target=append, args=(index,)) for index in range(workers)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertFalse(failures)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        rows = AuditLog.objects.filter(action="audit.concurrency_probe").order_by("seq")
        self.assertEqual(rows.count(), workers)
        self.assertEqual(rows.values("seq").distinct().count(), workers)
        # verify_chain() now also reports how much it checked and where it
        # resumed from, so this asserts the fields rather than the whole dict.
        # It gets stricter, not looser: the chain must be valid AND every row
        # the workers appended must actually have been walked — an incremental
        # verifier that returned ok=True having checked nothing would satisfy
        # the old equality but not this.
        result = verify_chain()
        self.assertTrue(result["ok"])
        self.assertIsNone(result["brokenAt"])
        self.assertGreaterEqual(
            result["checkedRows"],
            workers,
            "every concurrently appended row must have been verified",
        )
