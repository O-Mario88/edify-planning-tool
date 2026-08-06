"""Purging unmatched SSA must only ever remove genuinely unresolvable rows.

A Salesforce export was filtered wrongly and shipped SSA for closed schools.
Those rows can never be triaged — the schools do not exist in Edify and will
not — so they are deleted rather than left to hide real work in the queue.

`UnmatchedSSARecord` is not soft-deleted, so this is permanent. The properties
below are what make that safe, and each is asserted rather than asserted-in-a-
comment:

* nothing happens without `--apply`;
* a row whose school has appeared in the directory since upload is **refused**,
  because it is now matchable and deleting it would throw away field work;
* `matched` rows are never eligible — they already produced an SsaRecord;
* every deletion leaves an audit row carrying the scores, so a hard delete is
  still answerable afterwards.
"""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School, UnmatchedSSARecord


class PurgeUnmatchedSsaTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="PU Region")
        self.district = District.objects.create(name="PU District", region=self.region)
        self.sub = SubCounty.objects.create(name="PU Sub", district=self.district)
        # One school that exists, one id that does not.
        self.live = School.objects.create(
            school_id="60001",
            name="PU Live School",
            region=self.region,
            district=self.district,
            sub_county=self.sub,
            school_type="client",
        )
        self.orphan = self._unmatched("70001")
        self.resolvable = self._unmatched("60001")

    def _unmatched(self, school_id, status="pending"):
        return UnmatchedSSARecord.objects.create(
            school_id=school_id,
            date_of_ssa="2026-04-05",
            scores={"leadership": 4.2},
            reason="School ID does not exist in School Directory",
            status=status,
        )

    def _run(self, **kwargs):
        out = StringIO()
        call_command("purge_unmatched_ssa", stdout=out, **kwargs)
        return out.getvalue()

    def test_a_dry_run_deletes_nothing(self):
        before = UnmatchedSSARecord.objects.count()
        output = self._run()
        self.assertEqual(UnmatchedSSARecord.objects.count(), before)
        self.assertIn("Dry run", output)

    def test_it_refuses_a_row_whose_school_now_exists(self):
        """The stored reason is a fact about upload time, not about now."""
        self._run(apply=True)
        self.assertTrue(
            UnmatchedSSARecord.objects.filter(pk=self.resolvable.pk).exists(),
            "a row that became matchable must survive — it is work, not noise",
        )

    def test_it_deletes_the_genuinely_orphaned_row(self):
        self._run(apply=True)
        self.assertFalse(UnmatchedSSARecord.objects.filter(pk=self.orphan.pk).exists())

    def test_matched_rows_can_never_be_targeted(self):
        # They already produced an SsaRecord; deleting the source orphans it.
        with self.assertRaises(CommandError):
            self._run(status="matched")

    def test_a_matched_row_is_untouched_even_when_orphaned(self):
        already = self._unmatched("70002", status="matched")
        self._run(apply=True)
        self.assertTrue(UnmatchedSSARecord.objects.filter(pk=already.pk).exists())

    def test_every_deletion_records_what_it_destroyed(self):
        self._run(apply=True, reason="closed schools, SF export filter")
        row = AuditLog.objects.filter(action="ssa.unmatched_purged").latest("id")
        self.assertEqual(row.payload["schoolIdRaw"], "70001")
        # The scores are the thing that cannot be reconstructed, so they must
        # be in the trail for a delete that cannot be undone.
        self.assertEqual(row.payload["scores"], {"leadership": 4.2})
        self.assertIn("closed schools", row.reason)

    def test_running_twice_is_a_no_op(self):
        self._run(apply=True)
        audits = AuditLog.objects.filter(action="ssa.unmatched_purged").count()
        self._run(apply=True)
        self.assertEqual(
            AuditLog.objects.filter(action="ssa.unmatched_purged").count(),
            audits,
            "a second run must not re-audit rows that are already gone",
        )

    def test_limit_caps_a_first_run(self):
        for i in range(4):
            self._unmatched(f"7100{i}")
        self._run(apply=True, limit=2)
        self.assertEqual(
            UnmatchedSSARecord.objects.filter(status="pending").count(),
            # 5 orphans + 1 resolvable, minus the 2 deleted
            4,
        )

    def test_batch_scoping_leaves_other_batches_alone(self):
        from apps.schools.models import SSAImportBatch

        batch = SSAImportBatch.objects.create(
            file_name="ssa_upload_1.xlsx", uploaded_by="tester"
        )
        scoped = self._unmatched("72001")
        scoped.batch = batch
        scoped.save(update_fields=["batch"])

        self._run(apply=True, batch=batch.id)

        self.assertFalse(UnmatchedSSARecord.objects.filter(pk=scoped.pk).exists())
        self.assertTrue(
            UnmatchedSSARecord.objects.filter(pk=self.orphan.pk).exists(),
            "a row outside the named batch must not be touched",
        )
