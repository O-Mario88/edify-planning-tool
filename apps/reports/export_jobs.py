"""Exports prepared in the background (owner, 2026-10-26: big exports are
"Prepared in background": Export shows "Preparing your file…", the file
downloads by itself when ready, or a notification links to it if the person
left the page).

A country's Planning Oversight export took three minutes on production and
the gateway gave up after two, while the request held a web worker. Now the
export drawer queues the export's own address (``queue``); the scheduler
worker answers it through the export's own view, as the person who asked,
and keeps the file (``work`` / ``run``); the drawer asks how it is going and
offers the file when it is ready.

Where no worker is running (a laptop, the test suite, a stopped scheduler)
an export is built at once in the request that asked for it, as before.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.urls import Resolver404, resolve
from django.utils import timezone

from .models import ExportJob

logger = logging.getLogger("edify.exports")

#: The scheduler job that builds queued exports (apps.realtime.registry).
JOB_NAME = "export_jobs"
#: A worker that ran this recently is taken to be alive.
WORKER_FRESH = timedelta(minutes=3)
#: A job running longer than this lost its worker (a restart, a deploy).
CLAIM_TIMEOUT = timedelta(minutes=15)
#: Tries before a job is given up as failed.
MAX_ATTEMPTS = 2
#: How long a prepared file is kept.
KEEP_FOR = timedelta(days=2)
#: A drawer that asked within this long is still waiting on screen.
WATCHING = timedelta(seconds=20)
#: How often the worker looks for queued exports while its run lasts.
POLL_SECONDS = 5

#: Export views reached without `require_export_permission`'s mark, by name.
_UNMARKED_EXPORTS = {"apps.frontend.views.budget_views.budget_export_view"}
#: Pages that answer with a file only when asked for their export.
_PAGES_WITH_AN_EXPORT = {
    "apps.frontend.views.my_plan_views.my_plan_view",
    "apps.frontend.views.budget_views.weekly_fund_requests_view",
}

FAILED_MESSAGE = "This export could not be prepared. Please try again."


class NotAnExport(ValueError):
    """The address is not one of the platform's exports."""


def _view_name(func) -> str:
    return f"{func.__module__}.{func.__name__}"


def _export_match(url: str):
    """The resolved export view for ``url``, or ``NotAnExport``."""
    parts = urlsplit(url or "")
    if parts.scheme or parts.netloc or not parts.path.startswith("/"):
        raise NotAnExport(url)
    try:
        match = resolve(parts.path)
    except Resolver404 as exc:
        raise NotAnExport(url) from exc
    name = _view_name(match.func)
    if getattr(match.func, "export_permission", False) and "export" in parts.path:
        return match
    if name in _UNMARKED_EXPORTS:
        return match
    if name in _PAGES_WITH_AN_EXPORT and parse_qs(parts.query).get("export"):
        return match
    raise NotAnExport(url)


def queue(user, url: str) -> ExportJob:
    """Queue the export at ``url`` (its address and query) for ``user``."""
    _export_match(url)
    return ExportJob.objects.create(user=user, path=url, last_polled_at=timezone.now())


def worker_is_running() -> bool:
    """Whether the scheduler's export job has run recently."""
    from apps.realtime.models import ScheduledJobExecution

    return ScheduledJobExecution.objects.filter(
        job_name=JOB_NAME,
        status__in=("success", "running"),
        started_at__gte=timezone.now() - WORKER_FRESH,
    ).exists()


def _request_host() -> str:
    from django.conf import settings

    for host in getattr(settings, "ALLOWED_HOSTS", []) or []:
        host = host.lstrip(".")
        if host and host != "*":
            return host
    return "localhost"


def _answer(user, url: str):
    """The export view's response to ``user`` asking for ``url``, through
    the view and its own permission checks, as their browser would ask."""
    # RequestFactory builds the GET the drawer would have sent; it is the
    # documented way to call a view outside the request cycle.
    from django.test.client import RequestFactory

    from apps.acting import services as acting_services
    from apps.core import acting as acting_api
    from apps.core.request_cache import scoped

    match = _export_match(url)
    request = RequestFactory().get(url, HTTP_HOST=_request_host())
    request.user = user
    with scoped():
        acting_services.attach(user)
        acting_api.remember_request_capacity(user)
        return match.func(request, *match.args, **match.kwargs)


def _filename(disposition: str) -> str:
    found = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disposition or "")
    name = (found.group(1) if found else "export.xlsx").strip()
    name = re.sub(r"[^A-Za-z0-9._ -]", "-", name.rsplit("/", 1)[-1])[:120]
    return name or "export.xlsx"


def run(job_id: str) -> None:
    """Build one job's file. A refusal or an error fails the job with a
    plain message; the person sees it in the drawer."""
    job = ExportJob.objects.select_related("user").get(id=job_id)
    if job.status == ExportJob.READY:
        return
    if job.status == ExportJob.PENDING:
        ExportJob.objects.filter(id=job.id).update(
            status=ExportJob.RUNNING,
            started_at=timezone.now(),
            attempts=job.attempts + 1,
        )
    try:
        response = _answer(job.user, job.path)
        if response.streaming:
            content = b"".join(response.streaming_content)
        else:
            content = response.content
        disposition = response.get("Content-Disposition", "")
        if response.status_code != 200 or "attachment" not in disposition:
            _fail(job, "Your role cannot export this.")
            return
        filename = _filename(disposition)
        name = default_storage.save(
            f"exports/{job.id}/{filename}", ContentFile(content)
        )
    except Exception:  # noqa: BLE001 - the drawer says so; the log says why
        logger.exception("export_job failed id=%s path=%s", job.id, job.path[:200])
        _fail(job, FAILED_MESSAGE)
        return
    ExportJob.objects.filter(id=job.id).update(
        status=ExportJob.READY,
        file=name,
        filename=filename,
        content_type=response.get("Content-Type", "")[:128],
        size=len(content),
        finished_at=timezone.now(),
        error="",
    )
    job.refresh_from_db()
    logger.info(
        "export_job ready id=%s bytes=%s seconds=%.1f",
        job.id,
        job.size,
        (job.finished_at - job.started_at).total_seconds() if job.started_at else 0,
    )
    _announce(job)


def _fail(job: ExportJob, message: str) -> None:
    ExportJob.objects.filter(id=job.id).update(
        status=ExportJob.FAILED, error=message, finished_at=timezone.now()
    )


def _announce(job: ExportJob) -> None:
    """Tell the person their file is ready, unless their drawer is still
    open and about to offer it."""
    if job.last_polled_at and timezone.now() - job.last_polled_at < WATCHING:
        return
    from apps.notifications.services import WorkflowNotificationService

    WorkflowNotificationService.trigger(
        event_type="export.ready",
        category="general",
        priority="normal",
        title="Your export is ready",
        body=job.filename,
        context_type="ExportJob",
        context_id=job.id,
        recipients=[job.user],
    )


def _requeue_stuck() -> None:
    stale = ExportJob.objects.filter(
        status=ExportJob.RUNNING, started_at__lt=timezone.now() - CLAIM_TIMEOUT
    )
    stale.filter(attempts__gte=MAX_ATTEMPTS).update(
        status=ExportJob.FAILED, error=FAILED_MESSAGE, finished_at=timezone.now()
    )
    stale.update(status=ExportJob.PENDING)


def _claim() -> str | None:
    with transaction.atomic():
        job = (
            ExportJob.objects.select_for_update(skip_locked=True)
            .filter(status=ExportJob.PENDING)
            .order_by("created_at")
            .first()
        )
        if job is None:
            return None
        ExportJob.objects.filter(id=job.id).update(
            status=ExportJob.RUNNING,
            started_at=timezone.now(),
            attempts=job.attempts + 1,
        )
        return job.id


def work(seconds: float = 55) -> int:
    """Build queued exports, one at a time, for up to ``seconds``: the
    scheduler's job runs once a minute and keeps looking every
    ``POLL_SECONDS`` meanwhile, so a queued export starts within seconds."""
    deadline = time.monotonic() + seconds
    prune()
    built = 0
    while True:
        _requeue_stuck()
        job_id = _claim()
        if job_id is not None:
            run(job_id)
            built += 1
            continue
        if time.monotonic() + POLL_SECONDS > deadline:
            return built
        time.sleep(POLL_SECONDS)


def prune() -> int:
    """Remove jobs, and their files, older than ``KEEP_FOR``."""
    old = list(
        ExportJob.objects.filter(created_at__lt=timezone.now() - KEEP_FOR).only(
            "id", "file"
        )
    )
    for job in old:
        if job.file:
            try:
                default_storage.delete(job.file.name)
            except Exception:  # noqa: BLE001 - a missing file is already gone
                logger.warning("export_job file not removed id=%s", job.id)
    ExportJob.objects.filter(id__in=[job.id for job in old]).delete()
    return len(old)


def owned(user, job_id: str) -> ExportJob | None:
    """The person's own job, or None."""
    return ExportJob.objects.filter(id=job_id, user=user).first()


def seen(job: ExportJob) -> None:
    """The drawer asked how the job is going."""
    ExportJob.objects.filter(id=job.id).update(last_polled_at=timezone.now())
