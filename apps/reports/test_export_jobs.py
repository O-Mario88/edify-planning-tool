"""Exports are prepared in the background (owner, 2026-10-26: big exports
"Prepare in background": Export shows "Preparing your file…", the file
downloads when it is ready, and a notification links to it if the person left
the page).

A country's Planning Oversight export took three minutes on production and
the gateway gave up after two; the request held a web worker the whole time.
The scheduler worker now builds a queued export, as the person who asked,
through the export's own view, so the file is the one a direct download gives.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.core.files.storage import default_storage
from django.test import Client
from django.utils import timezone

from apps.frontend.test_export_my_plan_tables import (
    PL_EXPORT,
    MyPlanTablesFixture,
    book,
)
from apps.reports import export_jobs
from apps.reports.models import ExportJob


def _export_url(fixture, **params) -> str:
    from urllib.parse import urlencode

    query = {
        "fy": fixture.fy,
        "format": "xlsx",
        "status": "all",
        "owner": fixture.james.id,
        **params,
    }
    return f"{PL_EXPORT}?{urlencode(query)}"


def _worker_running():
    """Make the scheduler's export job look alive."""
    from apps.realtime.models import ScheduledJobExecution

    now = timezone.now()
    ScheduledJobExecution.objects.create(
        job_name=export_jobs.JOB_NAME,
        started_at=now,
        completed_at=now,
        status="success",
    )


class ExportJobFixture(MyPlanTablesFixture):
    def tearDown(self):
        for job in ExportJob.objects.exclude(file=""):
            default_storage.delete(job.file.name)
        super().tearDown()


class TheFileIsTheExportsOwnFile(ExportJobFixture):
    def test_a_prepared_export_is_the_file_a_direct_download_gives(self):
        url = _export_url(self)
        direct = book(self.as_pl().get(url))

        job = export_jobs.queue(self.pl_user, url)
        export_jobs.run(job.id)
        job.refresh_from_db()

        self.assertEqual(job.status, ExportJob.READY)
        self.assertTrue(job.filename.endswith(".xlsx"))
        response = self.as_pl().get(f"/exports/{job.id}/download")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(book(_Body(response)), direct)

    def test_the_export_runs_as_the_person_who_asked(self):
        url = _export_url(self)
        job = export_jobs.queue(self.james_user, url)

        export_jobs.run(job.id)
        job.refresh_from_db()

        # A CCEO may not open a Lead's team oversight: the export's own
        # permission check refuses, and nothing is kept.
        self.assertEqual(job.status, ExportJob.FAILED)
        self.assertFalse(job.file)


class _Body:
    """A streamed download as the `book` reader expects it."""

    def __init__(self, response):
        self.content = b"".join(response.streaming_content)


class OnlyExportsArePrepared(ExportJobFixture):
    def test_addresses_that_are_not_exports_are_refused(self):
        for url in (
            "/home",
            "/my-plan/",
            "https://example.com/team-planning-oversight/export",
            "//example.com/team-planning-oversight/export",
            "/team-planning-oversight/",
            "/no-such-page/export",
        ):
            with self.subTest(url=url):
                with self.assertRaises(export_jobs.NotAnExport):
                    export_jobs.queue(self.pl_user, url)

    def test_my_plan_is_prepared_when_it_asks_for_its_export(self):
        job = export_jobs.queue(self.james_user, f"/my-plan/?fy={self.fy}&export=xlsx")

        self.assertEqual(job.status, ExportJob.PENDING)

    def test_the_prepare_page_refuses_an_address_that_is_not_an_export(self):
        response = self.as_pl().post("/exports/prepare", {"export_url": "/home"})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ExportJob.objects.exists())


class OnlyTheOwnerDownloads(ExportJobFixture):
    def test_another_person_cannot_read_or_download_it(self):
        job = export_jobs.queue(self.pl_user, _export_url(self))
        export_jobs.run(job.id)
        other = Client()
        other.force_login(self.ia_user)

        self.assertEqual(other.get(f"/exports/{job.id}").status_code, 404)
        self.assertEqual(other.get(f"/exports/{job.id}/download").status_code, 404)


class WhereTheExportIsBuilt(ExportJobFixture):
    def _prepare(self):
        return self.as_pl().post(
            "/exports/prepare",
            {"export_url": PL_EXPORT, "fy": self.fy, "format": "xlsx", "status": "all"},
            HTTP_HX_REQUEST="true",
        )

    def test_without_a_running_worker_it_is_built_at_once(self):
        response = self._prepare()

        job = ExportJob.objects.get()
        self.assertEqual(job.status, ExportJob.READY)
        self.assertIn(f"/exports/{job.id}/download", response.content.decode())

    def test_with_a_running_worker_it_waits_for_the_worker(self):
        _worker_running()

        response = self._prepare()

        job = ExportJob.objects.get()
        self.assertEqual(job.status, ExportJob.PENDING)
        body = response.content.decode()
        self.assertIn("Preparing your file", body)
        self.assertIn(f'hx-get="/exports/{job.id}"', body)

    def test_the_worker_builds_it_and_the_page_then_offers_the_download(self):
        _worker_running()
        self._prepare()
        job = ExportJob.objects.get()

        export_jobs.work(seconds=0)

        job.refresh_from_db()
        self.assertEqual(job.status, ExportJob.READY)
        body = self.as_pl().get(f"/exports/{job.id}").content.decode()
        self.assertIn(f"/exports/{job.id}/download", body)
        self.assertNotIn("Preparing your file", body)


class APersonWhoLeftIsTold(ExportJobFixture):
    def _ready(self, *, watched: bool):
        from apps.notifications.models import Notification

        job = export_jobs.queue(self.pl_user, _export_url(self))
        if watched:
            self.as_pl().get(f"/exports/{job.id}")
        else:
            ExportJob.objects.filter(id=job.id).update(
                last_polled_at=timezone.now() - timedelta(minutes=5)
            )
        export_jobs.run(job.id)
        return Notification.objects.filter(
            recipient_id=self.pl_user.id, context_id=job.id
        )

    def test_a_notification_links_to_the_file_when_the_page_was_left(self):
        notices = self._ready(watched=False)

        self.assertEqual(notices.count(), 1)
        self.assertIn("/download", notices.get().target_route)

    def test_no_notification_while_the_drawer_is_still_waiting(self):
        self.assertFalse(self._ready(watched=True).exists())


class AStuckExportIsRetriedOnce(ExportJobFixture):
    def test_a_job_whose_worker_died_runs_again_then_fails(self):
        job = export_jobs.queue(self.pl_user, _export_url(self))
        stale = timezone.now() - export_jobs.CLAIM_TIMEOUT - timedelta(seconds=1)
        ExportJob.objects.filter(id=job.id).update(
            status=ExportJob.RUNNING, started_at=stale, attempts=1
        )

        export_jobs.work(seconds=0)
        job.refresh_from_db()
        self.assertEqual(job.status, ExportJob.READY)

        ExportJob.objects.filter(id=job.id).update(
            status=ExportJob.RUNNING,
            started_at=stale,
            attempts=export_jobs.MAX_ATTEMPTS,
        )
        export_jobs.work(seconds=0)
        job.refresh_from_db()
        self.assertEqual(job.status, ExportJob.FAILED)


class OldFilesAreRemoved(ExportJobFixture):
    def test_a_file_older_than_the_keep_period_is_deleted(self):
        job = export_jobs.queue(self.pl_user, _export_url(self))
        export_jobs.run(job.id)
        job.refresh_from_db()
        name = job.file.name
        ExportJob.objects.filter(id=job.id).update(
            created_at=timezone.now() - export_jobs.KEEP_FOR - timedelta(minutes=1)
        )

        export_jobs.prune()

        self.assertFalse(ExportJob.objects.filter(id=job.id).exists())
        self.assertFalse(default_storage.exists(name))


class TheDrawerPreparesTheFile(ExportJobFixture):
    def test_every_export_drawer_posts_to_prepare(self):
        with mock.patch.object(export_jobs, "worker_is_running", return_value=True):
            for drawer in (
                "/team-planning-oversight/export-drawer",
                "/country-planning-oversight/export-drawer",
                "/partner-oversight/export-drawer",
                "/my-plan/export-drawer",
            ):
                with self.subTest(drawer=drawer):
                    body = self.as_pl().get(drawer, {"fy": self.fy}).content.decode()
                    self.assertIn('hx-post="/exports/prepare"', body)
                    self.assertIn('name="export_url"', body)
                    # The drawer stays open to show the file's progress
                    # (drawer-submit.js closes a drawer after a save).
                    self.assertIn("data-drawer-stay-open", body)
