"""Exports, for the native app: the export drawers open and save as any
drawer does (the save posts to /exports/prepare, which queues the file as
the web's does); the app asks how the file is coming along, and once it is
ready the phone's browser downloads it from a link signed for the reader and
that file, good for a few minutes. The browser carries no app token, so the
link itself is the reader's permission — bound to their id, the job and a
time — and the file is still only ever the reader's own export.
"""

from __future__ import annotations

import re

from django.core import signing
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

#: The export drawers the app opens (each page's Export button).
EXPORT_DRAWERS = frozenset(
    {
        "my_plan_export_drawer",
        "budget_export_drawer",
        "fund_requests_export_drawer",
        "team_planning_oversight_export_drawer",
        "country_planning_oversight_export_drawer",
        "special_projects_export_drawer",
        "partner_oversight_export_drawer",
        "export_drawer",
    }
)
#: The save every export drawer posts to.
PREPARE = "export_prepare"
#: How long a download link opens the file.
LINK_SECONDS = 300
SALT = "edify.mobile.export-download"
#: The job the status the prepare view draws is about (/exports/<id>).
JOB_IN_STATUS = re.compile(r'/exports/([A-Za-z0-9_-]{1,64})(?:/download)?"')


def job_in(html: str) -> str:
    """The export job the prepare view's status is about, or ''."""
    found = JOB_IN_STATUS.search(html)
    return found.group(1) if found else ""


def export_download_url(user_id, job_id: str) -> str:
    """A link the phone's browser downloads the reader's file from."""
    token = signing.TimestampSigner(salt=SALT).sign(f"{user_id}:{job_id}")
    return f"/api/mobile/v1/exports/{job_id}/file?sig={token}"


class ExportStatusFeedView(APIView):
    """How the reader's export is coming along, and its link once ready."""

    def get(self, request: Request, job_id: str) -> Response:
        from apps.mobile_feed.views import reader
        from apps.reports import export_jobs

        user = reader(request)
        job = export_jobs.owned(user, job_id)
        if job is None:
            return Response({"error": "This export was not found."}, status=404)
        export_jobs.seen(job)
        ready = job.status == job.READY and bool(job.file)
        return Response(
            {
                "status": job.status,
                "filename": job.filename or "",
                "error": getattr(job, "error", "") or "",
                "downloadUrl": export_download_url(user.id, job.id) if ready else "",
            }
        )


class ExportFileView(APIView):
    """The file itself, for a signed link (no app token: the phone's browser
    opens it). A changed, stale or someone else's link finds nothing."""

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request, job_id: str):
        from django.contrib.auth import get_user_model

        from apps.reports import export_jobs

        try:
            signed = signing.TimestampSigner(salt=SALT).unsign(
                request.query_params.get("sig", ""), max_age=LINK_SECONDS
            )
        except signing.BadSignature:
            raise Http404 from None
        user_id, _, signed_job = signed.partition(":")
        if signed_job != job_id:
            raise Http404
        user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
        job = export_jobs.owned(user, job_id) if user is not None else None
        if job is None or job.status != job.READY or not job.file:
            raise Http404
        return FileResponse(
            default_storage.open(job.file.name, "rb"),
            as_attachment=True,
            filename=job.filename,
            content_type=job.content_type or "application/octet-stream",
        )
