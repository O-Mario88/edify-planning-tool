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
