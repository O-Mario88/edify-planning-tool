"""The audit rows of one transaction are projected together when it commits.

Each row written inside a caller's transaction used to be projected by a
commit callback of its own: it read back the number the seal had just given
it and wrote one domain event, two statements a row. A reschedule that
re-priced nine visits wrote ten rows. The seal now hands its numbers on and
the events are written in one statement (apps.audit.services).
"""

from __future__ import annotations

from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.audit.models import AuditLog, DomainEventLog
from apps.audit.services import log as audit_log


def _log(n):
    audit_log(
        action=f"test.together.{n}",
        subject_kind="Thing",
        subject_id=f"thing-{n}",
        payload={"n": n},
    )


def _events():
    return list(
        DomainEventLog.objects.filter(event_type__startswith="test.together.")
        .order_by("event_type")
        .values_list("event_type", "aggregate_id", "payload")
    )


class EventsWrittenTogetherTest(TestCase):
    def test_each_row_has_its_event_and_its_number(self):
        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                for n in range(4):
                    _log(n)
        events = _events()
        self.assertEqual(
            [(kind, subject) for kind, subject, _payload in events],
            [(f"test.together.{n}", f"thing-{n}") for n in range(4)],
        )
        numbers = dict(
            AuditLog.objects.filter(action__startswith="test.together.").values_list(
                "action", "seq"
            )
        )
        self.assertNotIn(None, numbers.values())
        for kind, _subject, payload in events:
            self.assertEqual(payload["auditSeq"], numbers[kind])
            self.assertEqual(payload["data"], {"n": int(kind[-1])})
            self.assertTrue(payload["success"])

    def test_the_events_are_one_statement_and_no_number_is_read_back(self):
        with self.captureOnCommitCallbacks() as at_commit:
            with transaction.atomic():
                for n in range(5):
                    _log(n)
        with CaptureQueriesContext(connection) as queries:
            for callback in at_commit:
                callback()
        sqls = [q["sql"] for q in queries.captured_queries]
        self.assertEqual(
            len([s for s in sqls if s.startswith('INSERT INTO "domain_event_log"')]), 1
        )
        read_back = [
            s for s in sqls if s.startswith("SELECT") and '"audit_log"."id" IN' in s
        ]
        self.assertEqual(read_back, [])
        self.assertEqual(len(_events()), 5)

    def test_a_row_undone_with_its_savepoint_has_no_event(self):
        class Undo(Exception):
            pass

        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                _log(0)
                try:
                    with transaction.atomic():
                        _log(1)
                        raise Undo
                except Undo:
                    pass
                _log(2)
        self.assertEqual(
            [kind for kind, _subject, _payload in _events()],
            ["test.together.0", "test.together.2"],
        )

    def test_a_row_outside_any_transaction_is_projected_on_its_own(self):
        with self.captureOnCommitCallbacks(execute=True):
            _log(7)
        ((kind, _subject, payload),) = _events()
        self.assertEqual(kind, "test.together.7")
        self.assertEqual(
            payload["auditSeq"], AuditLog.objects.get(action="test.together.7").seq
        )
