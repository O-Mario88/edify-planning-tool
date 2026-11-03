"""Upload Center pages for bulk completion: upload, preview, confirm, result
and the error report. Each one asks the bulk-completion permission, and a
batch is opened only by a reader it is visible to (report.visible_batches)."""

from __future__ import annotations

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.core.exceptions import BadRequest
from apps.core.permissions import render_access_denied, require_page_permission
from apps.core.redirects import local_redirect

from . import report
from .apply import apply_batch
from .columns import COLUMNS, TEMPLATE_NOTES
from .models import BatchStatus, BulkKind
from .rules import may_bulk_complete
from .staging import MAX_ROWS, cancel_batch, stage_upload
from .template_file import FILE_STEMS, template_sheets

DENIED = (
    "Bulk completion is run by Impact Assessment and administrators. Complete "
    "your own work from its Complete drawer."
)

PAGE_TEXT = {
    BulkKind.VISIT: {
        "title": "Bulk Upload — School Visits",
        "noun": "school visits",
        "id_label": "Visit SF ID",
    },
    BulkKind.TRAINING: {
        "title": "Bulk Upload — Trainings",
        "noun": "trainings",
        "id_label": "Training SF ID",
    },
}


def _kind(value: str) -> str:
    if value not in BulkKind.values:
        raise Http404("Unknown upload.")
    return value


def _denied(request):
    if not may_bulk_complete(request.user):
        return render_access_denied(request, DENIED)
    return None


@require_page_permission("bulk_completion")
def upload_view(request, kind):
    kind = _kind(kind)
    denied = _denied(request)
    if denied:
        return denied
    if request.method == "POST":
        file = request.FILES.get("file")
        if not file:
            messages.error(request, "Choose the completed template to upload.")
            return local_redirect(f"/uploads/bulk-completion/{kind}")
        try:
            batch = stage_upload(file, kind, request.user)
        except BadRequest as exc:
            messages.error(request, str(exc.detail))
            return local_redirect(f"/uploads/bulk-completion/{kind}")
        return local_redirect(f"/uploads/bulk-completion/batch/{batch.id}")
    recent = report.visible_batches(request.user).filter(kind=kind)[:10]
    return render(
        request,
        "pages/bulk_completion/upload.html",
        {
            "kind": kind,
            "text": PAGE_TEXT[kind],
            "columns": COLUMNS[kind],
            "note": TEMPLATE_NOTES[kind],
            "max_rows": MAX_ROWS,
            "recent": recent,
        },
    )


@require_page_permission("bulk_completion")
def template_view(request, kind):
    from apps.core.excel import workbook_response

    kind = _kind(kind)
    denied = _denied(request)
    if denied:
        return denied
    return workbook_response(
        f"{FILE_STEMS[kind]}.xlsx", template_sheets(request.user, kind)
    )


def _batch(request, batch_id):
    return get_object_or_404(report.visible_batches(request.user), pk=batch_id)


@require_page_permission("bulk_completion")
def batch_view(request, batch_id):
    denied = _denied(request)
    if denied:
        return denied
    batch = _batch(request, batch_id)
    return render(
        request,
        "pages/bulk_completion/batch.html",
        {
            "batch": batch,
            "text": PAGE_TEXT[batch.kind],
            "summary": report.summary(batch),
            "sections": report.sections(batch),
            "earlier": report.earlier_upload(batch),
            "back_href": f"/uploads/bulk-completion/{batch.kind}",
            "staged": batch.status == BatchStatus.STAGED,
            "applying": batch.status in (BatchStatus.QUEUED, BatchStatus.APPLYING),
        },
    )


@require_POST
@require_page_permission("bulk_completion")
def confirm_view(request, batch_id):
    denied = _denied(request)
    if denied:
        return denied
    batch = _batch(request, batch_id)
    from .worker import INLINE_LINES, queue, worker_is_running

    counts = report.summary(batch)
    if (
        batch.status == BatchStatus.STAGED
        and counts["ready"] > INLINE_LINES
        and worker_is_running()
    ):
        # Too many lines for one request: the scheduler worker completes it.
        if queue(batch, request.user):
            messages.success(
                request,
                f"Completing {counts['ready']} lines in the background. This page "
                "shows the progress, and you will be notified when it is done.",
            )
    elif batch.status in (BatchStatus.STAGED, BatchStatus.APPLYING):
        batch = apply_batch(batch, request.user)
        counts = report.summary(batch)
        messages.success(
            request,
            f"{counts['completed']} completed, "
            f"{counts['skipped'] + counts['duplicates']} skipped, "
            f"{counts['review'] + counts['invalid'] + counts['failed']} not "
            "completed.",
        )
    return local_redirect(f"/uploads/bulk-completion/batch/{batch.id}")


@require_POST
@require_page_permission("bulk_completion")
def cancel_view(request, batch_id):
    denied = _denied(request)
    if denied:
        return denied
    batch = _batch(request, batch_id)
    if cancel_batch(batch, request.user):
        messages.success(request, "Upload cancelled. Nothing was completed.")
    return local_redirect(f"/uploads/bulk-completion/{batch.kind}")


@require_page_permission("bulk_completion")
def error_report_view(request, batch_id):
    from apps.core.excel import workbook_response

    denied = _denied(request)
    if denied:
        return denied
    batch = _batch(request, batch_id)
    return workbook_response(
        f"{FILE_STEMS[batch.kind]}-not-completed.xlsx",
        report.error_report_sheets(batch),
    )
