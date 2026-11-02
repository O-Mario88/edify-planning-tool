"""Large uploads are completed by the scheduler worker (owner, 2026-11-02:
"hundreds or thousands of school visits"; a web request stops at a minute).

Pinned here:

  1. Confirming more than INLINE_LINES ready lines while the worker runs
     queues the batch; nothing is completed in the request.
  2. The worker completes it as the person who confirmed it and tells them.
  3. A worker whose time runs out stops between lines and the next run
     carries on; no line is completed twice.
  4. With no worker running, the request completes the file itself.
"""

from __future__ import annotations

import time

from django.utils import timezone

from apps.activities.models import Activity
from apps.bulk_completion import worker
from apps.bulk_completion.apply import apply_batch
from apps.bulk_completion.models import BatchStatus, RowStatus
from apps.bulk_completion.test_bulk_visits import BulkFixture
from apps.notifications.models import Notification


class WorkerFixture(BulkFixture):
    def _large_batch(self, n=None):
        n = n or worker.INLINE_LINES + 2
        visits = [self._visit() for _ in range(n)]
        lines = [self._line(v, f"SVE-9{i:04d}") for i, v in enumerate(visits)]
        return self._stage(*lines), visits

    def _worker_runs(self):
        from apps.realtime.models import ScheduledJobExecution

        ScheduledJobExecution.objects.create(
            job_name=worker.JOB_NAME, started_at=timezone.now(), status="success"
        )

    def _confirm(self, batch):
        return self.as_user(self.ia_user).post(
            f"/uploads/bulk-completion/batch/{batch.id}/confirm"
        )

    def _verified(self, visits):
        return Activity.objects.filter(
            pk__in=[v.pk for v in visits], status="ia_verified"
        ).count()


class ALargeFileIsCompletedInTheBackground(WorkerFixture):
    def test_confirming_queues_it_and_completes_nothing_yet(self):
        batch, visits = self._large_batch()
        self._worker_runs()
        self._confirm(batch)
        batch.refresh_from_db()
        self.assertEqual(batch.status, BatchStatus.QUEUED)
        self.assertEqual(batch.applied_by, self.ia_user.id)
        self.assertEqual(self._verified(visits), 0)
        page = self.as_user(self.ia_user).get(
            f"/uploads/bulk-completion/batch/{batch.id}"
        )
        self.assertContains(page, "Completing in the background")

    def test_the_worker_completes_it_as_the_confirmer_and_tells_them(self):
        batch, visits = self._large_batch()
        self._worker_runs()
        self._confirm(batch)

        self.assertEqual(worker.work(seconds=120), 1)

        batch.refresh_from_db()
        self.assertEqual(batch.status, BatchStatus.APPLIED)
        self.assertEqual(self._verified(visits), len(visits))
        notice = Notification.objects.get(
            recipient_id=self.ia_user.id, context_id=batch.id
        )
        # The notice opens the upload it is about.
        self.assertEqual(
            notice.target_route, f"/uploads/bulk-completion/batch/{batch.id}"
        )

    def test_a_run_out_of_time_stops_between_lines_and_the_next_carries_on(self):
        batch, visits = self._large_batch()
        worker.queue(batch, self.ia_user)
        # A deadline already behind us: the run stops before its first line.
        stopped = apply_batch(batch, self.ia_user, deadline=time.monotonic() - 1)
        self.assertEqual(stopped.status, BatchStatus.QUEUED)
        self.assertEqual(
            stopped.rows.filter(status=RowStatus.READY).count(), len(visits)
        )

        worker.work(seconds=120)
        batch.refresh_from_db()
        self.assertEqual(batch.status, BatchStatus.APPLIED)
        self.assertEqual(
            batch.rows.filter(status=RowStatus.COMPLETED).count(), len(visits)
        )


class WithoutAWorkerTheRequestCompletesIt(WorkerFixture):
    def test_no_worker_means_the_file_completes_at_once(self):
        batch, visits = self._large_batch()
        self._confirm(batch)
        batch.refresh_from_db()
        self.assertEqual(batch.status, BatchStatus.APPLIED)
        self.assertEqual(self._verified(visits), len(visits))

    def test_a_small_file_completes_at_once_even_with_a_worker(self):
        batch, _visits = self._large_batch(n=3)
        self._worker_runs()
        self._confirm(batch)
        batch.refresh_from_db()
        self.assertEqual(batch.status, BatchStatus.APPLIED)
