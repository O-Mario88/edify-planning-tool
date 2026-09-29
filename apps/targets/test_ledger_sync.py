"""Leadership pages rebuild only the officers whose ledger sources changed.

Team Targets, CD/RVP analytics and team rosters rebuilt every officer's
ledger on each load (2026-09-24 A+ audit, F-D). With the owner's approval a
source write now marks its officer and year, and the page rebuilds only the
marked members (apps.targets.ledger_sync). These tests hold the guarantee
that makes the change safe: after saved changes of every kind, a page's
refresh leaves the ledger where a full rebuild would, so a full rebuild has
nothing left to do. They also hold that a page with nothing marked writes
nothing.
"""

from __future__ import annotations

from datetime import date, datetime, timezone as dt_timezone
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.targets import ledger_sync
from apps.targets.models import MostSignificantChangeStory, TargetLedgerDirty
from apps.targets.my_targets import TargetAchievementService
from apps.targets.test_rebuild_many_matches_rebuild import (
    FY,
    RosterFixture,
    ledger_snapshot,
)

PREVIOUS_FY = str(int(FY) - 1)


class LedgerSyncTest(RosterFixture, TestCase):
    def setUp(self):
        super().setUp()
        for fy in (FY, PREVIOUS_FY):
            TargetAchievementService.rebuild_many(self.users, fy)
        TargetLedgerDirty.objects.all().delete()

    def _refresh(self):
        for fy in (FY, PREVIOUS_FY):
            ledger_sync.refresh_many(self.users, fy)

    def _full_rebuild_changes(self):
        before = ledger_snapshot()
        for fy in (FY, PREVIOUS_FY):
            TargetAchievementService.rebuild_many(self.users, fy)
        return before, ledger_snapshot()

    def test_refresh_reaches_what_a_full_rebuild_would(self):
        from apps.activities.models import Activity
        from apps.ssa.models import SsaRecord

        visit_type = self._visit_type()
        # New completed work, then IA-verified with its Salesforce id.
        new = self._activity(
            self.users[3].id, visit_type, date(2026, 4, 2), "completed"
        )
        new.status = "ia_verified"
        new.salesforce_activity_id = "SF-LS-1"
        new.save()
        # Work reassigned from one officer (by user id) to another (by
        # staff-profile id): both ledgers change.
        moved = Activity.objects.get(responsible_staff_id=self.users[0].id)
        moved.responsible_staff_id = self.users[3].staff_profile.id
        moved.save()
        # Work whose date moves back across the fiscal-year boundary.
        shifted = Activity.objects.filter(
            responsible_staff_id=self.users[1].staff_profile.id, delivery_type=""
        ).get()
        shifted.planned_date = date(2025, 9, 20)
        shifted.save()
        # An assessment returned, and a story deleted.
        ssa = SsaRecord.objects.get(
            collected_by_user_id=self.users[2].id, date_of_ssa__year=2026
        )
        ssa.verification_status = "returned"
        ssa.save()
        MostSignificantChangeStory.objects.filter(status="approved").get().delete()

        marked = set(TargetLedgerDirty.objects.values_list("owner_id", "fy"))
        self.assertIn((self.users[0].id, FY), marked)
        self.assertIn((self.users[3].staff_profile.id, FY), marked)
        self.assertIn((self.users[1].staff_profile.id, PREVIOUS_FY), marked)

        before_refresh = ledger_snapshot()
        self._refresh()
        self.assertNotEqual(ledger_snapshot(), before_refresh)
        before, after = self._full_rebuild_changes()
        self.assertEqual(after, before)
        self.assertFalse(TargetLedgerDirty.objects.exists())

    def test_nothing_marked_means_nothing_written(self):
        with CaptureQueriesContext(connection) as queries:
            self._refresh()
        writes = [
            q["sql"]
            for q in queries.captured_queries
            if q["sql"].split()[0] in ("INSERT", "UPDATE", "DELETE")
        ]
        self.assertEqual(writes, [])

    def test_only_the_marked_members_are_rebuilt(self):
        self._activity(
            self.users[3].id, self._visit_type(), date(2026, 5, 5), "completed"
        )
        with patch.object(
            TargetAchievementService,
            "rebuild_many",
            wraps=TargetAchievementService.rebuild_many,
        ) as rebuild:
            ledger_sync.refresh_many(self.users, FY)
        rebuilt = [u.id for u in rebuild.call_args.args[0]]
        self.assertEqual(rebuilt, [self.users[3].id])

    def test_a_mark_made_during_the_rebuild_survives_it(self):
        self._activity(
            self.users[0].id, self._visit_type(), date(2026, 5, 5), "completed"
        )
        original = TargetAchievementService.rebuild_many

        def rebuild_while_another_write_lands(users, fy):
            original(users, fy)
            ledger_sync.mark({self.users[0].id}, {fy})

        with patch.object(
            TargetAchievementService,
            "rebuild_many",
            side_effect=rebuild_while_another_write_lands,
        ):
            ledger_sync.refresh_many(self.users, FY)
        self.assertTrue(
            TargetLedgerDirty.objects.filter(owner_id=self.users[0].id, fy=FY).exists()
        )

    def test_a_bulk_import_marks_its_collectors(self):
        ledger_sync.mark_sources(
            [
                (self.users[2].id, datetime(2026, 2, 1, tzinfo=dt_timezone.utc)),
                (self.users[3].id, date(2025, 9, 1)),
                (None, date(2026, 1, 1)),
            ]
        )
        self.assertEqual(
            set(TargetLedgerDirty.objects.values_list("owner_id", "fy")),
            {(self.users[2].id, FY), (self.users[3].id, PREVIOUS_FY)},
        )


class OneMarkPerRowPerTransactionTest(RosterFixture, TestCase):
    """Within a request, scheduling one visit saves its Activity five times;
    the mark is upserted once while its transaction is open (2026-09-29)."""

    def setUp(self):
        from apps.core import request_cache

        super().setUp()
        self.activity = self._activity(
            self.users[1].id, self._visit_type(), date(2026, 5, 5), "scheduled"
        )
        TargetLedgerDirty.objects.all().delete()
        request_cache.begin()
        self.addCleanup(request_cache.end)

    def _mark_writes(self, fn):
        with CaptureQueriesContext(connection) as queries:
            fn()
        return [
            q
            for q in queries.captured_queries
            if q["sql"].startswith("INSERT") and "target_ledger_dirty" in q["sql"]
        ]

    def _marked(self, user):
        return TargetLedgerDirty.objects.filter(owner_id=user.id, fy=FY).exists()

    def test_repeat_saves_of_one_row_mark_once(self):
        from apps.activities.models import Activity

        def resave():
            self.activity.save()
            self.activity.save()
            # A fresh copy of the same row, as the pricing steps read it.
            Activity.objects.get(pk=self.activity.pk).save()

        self.assertEqual(len(self._mark_writes(resave)), 1)
        self.assertTrue(self._marked(self.users[1]))

    def test_a_new_owner_is_marked(self):
        self.activity.save()
        self.activity.responsible_staff_id = self.users[2].id
        self.assertEqual(len(self._mark_writes(self.activity.save)), 1)
        self.assertTrue(self._marked(self.users[2]))

    def test_a_mark_lost_to_a_savepoint_rollback_is_written_again(self):
        from django.db import transaction

        from apps.activities.models import Activity

        class Undo(Exception):
            pass

        try:
            with transaction.atomic():
                moved = Activity.objects.get(pk=self.activity.pk)
                moved.responsible_staff_id = self.users[2].id
                moved.save()
                raise Undo
        except Undo:
            pass
        self.assertFalse(TargetLedgerDirty.objects.exists())
        again = Activity.objects.get(pk=self.activity.pk)
        again.responsible_staff_id = self.users[2].id
        again.save()
        self.assertTrue(self._marked(self.users[1]))
        self.assertTrue(self._marked(self.users[2]))

    def test_a_refresh_between_saves_ends_the_remembered_mark(self):
        self.activity.status = "completed"
        self.activity.save()
        ledger_sync.refresh_many(self.users, FY)
        self.assertFalse(TargetLedgerDirty.objects.exists())
        self.activity.status = "ia_verified"
        self.activity.save()
        self.assertTrue(self._marked(self.users[1]))

    def test_outside_a_request_every_save_marks(self):
        from apps.core import request_cache

        request_cache.end()
        self.addCleanup(request_cache.begin)

        def resave():
            self.activity.save()
            self.activity.save()

        self.assertEqual(len(self._mark_writes(resave)), 2)
