"""A save marks its officer's ledger when it commits, not while it runs.

The mark is one row an officer and year. Written inside the save, the row
stayed locked until the save committed, and a second save for the same
officer waited behind the whole of the first: in production the one-row
write averaged 25.6 ms over 26,777 calls and waited up to 22.9 s
(pg_stat_statements, 2026-10-12). Measured on a copy the same day, a save
behind another open save for the same officer took 3.4 s before and 0.34 s
after.

`LEDGER_MARKS_AFTER_COMMIT` is off under the test runner, where a test's own
transaction never commits; these tests turn it on and run the commit's
callbacks themselves.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from apps.activities.models import Activity
from apps.targets import ledger_sync
from apps.targets.models import TargetLedgerDirty
from apps.targets.my_targets import TargetAchievementService
from apps.targets.test_rebuild_many_matches_rebuild import FY, RosterFixture


def _marks():
    return set(TargetLedgerDirty.objects.values_list("owner_id", "fy"))


@override_settings(LEDGER_MARKS_AFTER_COMMIT=True)
class MarksAfterCommitTest(RosterFixture, TestCase):
    def setUp(self):
        super().setUp()
        TargetAchievementService.rebuild_many(self.users, FY)
        TargetLedgerDirty.objects.all().delete()

    def _work(self, user, day=date(2026, 5, 5)):
        return self._activity(user.id, self._visit_type(), day, "completed")

    def test_nothing_is_written_until_the_save_commits(self):
        with self.captureOnCommitCallbacks() as at_commit:
            with transaction.atomic():
                self._work(self.users[3])
                self.assertEqual(_marks(), set())
        self.assertEqual(_marks(), set())
        for callback in at_commit:
            callback()
        self.assertEqual(_marks(), {(self.users[3].id, FY)})

    def test_every_save_of_the_transaction_is_marked_in_one_statement(self):
        with self.captureOnCommitCallbacks() as at_commit:
            with transaction.atomic():
                first = self._work(self.users[3])
                first.status = "ia_verified"
                first.save()
                Activity.objects.get(pk=first.pk).save()
                self._work(self.users[2])
        with CaptureQueriesContext(connection) as queries:
            for callback in at_commit:
                callback()
        written = [
            q["sql"]
            for q in queries.captured_queries
            if q["sql"].startswith("INSERT") and "target_ledger_dirty" in q["sql"]
        ]
        self.assertEqual(len(written), 1, written)
        self.assertEqual(_marks(), {(self.users[3].id, FY), (self.users[2].id, FY)})

    def test_a_save_that_is_undone_marks_nobody(self):
        class Undo(Exception):
            pass

        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    self._work(self.users[3])
                    raise Undo
            except Undo:
                pass
        self.assertEqual(_marks(), set())

    def test_a_savepoint_that_is_undone_takes_its_marks_and_the_rest_stand(self):
        class Undo(Exception):
            pass

        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                try:
                    with transaction.atomic():
                        self._work(self.users[3])
                        raise Undo
                except Undo:
                    pass
                self._work(self.users[2])
        self.assertEqual(_marks(), {(self.users[2].id, FY)})

    def test_a_read_inside_the_transaction_sees_what_it_changed(self):
        """A page that saves and then reads the ledger in one transaction
        rebuilds what it changed, as it did when the mark was written with
        the save."""
        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                self._work(self.users[3])
                with patch.object(
                    TargetAchievementService,
                    "rebuild_many",
                    wraps=TargetAchievementService.rebuild_many,
                ) as rebuild:
                    ledger_sync.refresh_many(self.users, FY)
                self.assertEqual(
                    [u.id for u in rebuild.call_args.args[0]], [self.users[3].id]
                )
        self.assertEqual(_marks(), set())

    def test_outside_a_transaction_the_mark_is_written_at_once(self):
        self._work(self.users[3])
        self.assertEqual(_marks(), {(self.users[3].id, FY)})

    def test_the_rebuild_still_reaches_what_a_full_rebuild_would(self):
        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                work = self._work(self.users[3])
                work.status = "ia_verified"
                work.salesforce_activity_id = "SF-MC-1"
                work.save()
        ledger_sync.refresh_many(self.users, FY)
        from apps.targets.test_rebuild_many_matches_rebuild import ledger_snapshot

        before = ledger_snapshot()
        TargetAchievementService.rebuild_many(self.users, FY)
        self.assertEqual(before, ledger_snapshot())


class TheSwitchTest(RosterFixture, TestCase):
    @override_settings(LEDGER_MARKS_AFTER_COMMIT=False)
    def test_off_the_mark_is_written_inside_the_save(self):
        TargetLedgerDirty.objects.all().delete()
        with transaction.atomic():
            self._activity(
                self.users[3].id, self._visit_type(), date(2026, 5, 5), "completed"
            )
            self.assertEqual(_marks(), {(self.users[3].id, FY)})
