"""The export drawer's file, prepared in the background (apps.reports.export_jobs).

The drawer posts its choices here instead of downloading the export at once:
the export is queued for the scheduler worker, the drawer shows "Preparing
your file…" and asks again every few seconds, and offers the file when it is
ready. Each job is its owner's alone.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from apps.reports import export_jobs

STATUS_TEMPLATE = "partials/exports/status.html"
#: The drawer's own fields that are not the export's query.
_NOT_THE_QUERY = {"export_url", "csrfmiddlewaretoken"}


def _export_address(post) -> str:
    """The address the drawer's form would have downloaded: its action with
    the form's fields as the query, as the browser writes a GET form."""
    url = (post.get("export_url") or "").strip()
    pairs = [
        (key, value)
        for key, values in post.lists()
        if key not in _NOT_THE_QUERY
        for value in values
    ]
    if not pairs:
        return url
    return url + ("&" if "?" in url else "?") + urlencode(pairs)


@login_required(login_url="/login")
@require_POST
def export_prepare_view(request):
    try:
        job = export_jobs.queue(request.user, _export_address(request.POST))
    except export_jobs.NotAnExport:
        return HttpResponseBadRequest("This is not an export.")
    if not export_jobs.worker_is_running():
        # No worker to hand it to (a laptop, a stopped scheduler): built now,
        # as every export was before.
        export_jobs.run(job.id)
        job.refresh_from_db()
    return render(request, STATUS_TEMPLATE, {"job": job})


@login_required(login_url="/login")
@require_GET
def export_status_view(request, job_id: str):
    job = export_jobs.owned(request.user, job_id)
    if job is None:
        raise Http404
    export_jobs.seen(job)
    return render(request, STATUS_TEMPLATE, {"job": job})


@login_required(login_url="/login")
@require_GET
def export_download_view(request, job_id: str):
    job = export_jobs.owned(request.user, job_id)
    if job is None or job.status != job.READY or not job.file:
        raise Http404
    return FileResponse(
        default_storage.open(job.file.name, "rb"),
        as_attachment=True,
        filename=job.filename,
        content_type=job.content_type or "application/octet-stream",
    )
