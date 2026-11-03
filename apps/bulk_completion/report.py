"""What a batch holds, for its preview and result pages and its error report."""

from __future__ import annotations

from django.db.models import Count, Q

from .models import (
    PROBLEM_STATUSES,
    SKIPPED_STATUSES,
    BulkCompletionBatch,
    RowStatus,
)

#: The preview's and the result's sections, in reading order.
SECTIONS = (
    ("ready", "Ready to complete", (RowStatus.READY, RowStatus.MERGED)),
    ("completed", "Completed", (RowStatus.COMPLETED,)),
    ("skipped", "Already completed", (RowStatus.ALREADY_COMPLETED,)),
    ("duplicates", "Duplicates in this file", (RowStatus.DUPLICATE,)),
    ("review", "Needs review", (RowStatus.REVIEW,)),
    ("invalid", "Invalid or unmatched", (RowStatus.INVALID,)),
    ("failed", "Not completed", (RowStatus.FAILED,)),
)


def visible_batches(principal):
    """The uploads this reader may open: their own; Impact Assessment the
    uploads of staff in its country; Admin every upload (the SSA import's
    rule, apps.frontend.views.ssa_views._visible_batches)."""
    from apps.core.rbac import EdifyRole
    from apps.core.scoping import person_country_q, resolve_user_scope

    batches = BulkCompletionBatch.objects.all()
    role = getattr(principal, "active_role", "")
    if role == EdifyRole.ADMIN.value:
        return batches
    mine = Q(uploaded_by=getattr(principal, "user_id", "") or principal.id)
    if role == EdifyRole.IMPACT_ASSESSMENT.value:
        scope = resolve_user_scope(principal)
        return batches.filter(person_country_q(scope, "uploaded_by") | mine)
    return batches.filter(mine)


def summary(batch: BulkCompletionBatch) -> dict:
    """The validation summary: one count per kind of outcome."""
    counts = {
        row["status"]: row["n"]
        for row in batch.rows.order_by().values("status").annotate(n=Count("id"))
    }
    return {
        "total": batch.total_rows,
        "ready": counts.get(RowStatus.READY, 0) + counts.get(RowStatus.MERGED, 0),
        "completed": counts.get(RowStatus.COMPLETED, 0),
        "skipped": counts.get(RowStatus.ALREADY_COMPLETED, 0),
        "duplicates": counts.get(RowStatus.DUPLICATE, 0),
        "review": counts.get(RowStatus.REVIEW, 0),
        "invalid": counts.get(RowStatus.INVALID, 0),
        "failed": counts.get(RowStatus.FAILED, 0),
    }


def activity_statuses(activity_ids) -> dict[str, tuple[str, str]]:
    """{activity id: (label, pill classes)}: each activity's status as My Plan
    shows it (owner, 2026-11-02: the upload's status "should match with the
    status on the actual planned activity")."""
    from django.utils import timezone

    from apps.activities.models import Activity
    from apps.my_plan.services import get_activity_status_label_and_class

    today = timezone.localdate()
    found = Activity.all_objects.in_bulk([i for i in set(activity_ids) if i])
    return {
        pk: get_activity_status_label_and_class(activity, today)
        for pk, activity in found.items()
    }


def _decorated(rows) -> list[dict]:
    rows = list(rows)
    statuses = activity_statuses(row.activity_id for row in rows)
    out = []
    for row in rows:
        label, tone = statuses.get(row.activity_id, ("Not matched", ""))
        out.append(
            {
                "row": row,
                # The uploaded ID names an activity Edify holds: it links.
                "found": row.activity_id in statuses,
                "status_label": label,
                "status_class": tone,
                # Why a line was not completed; a completed one needs no note.
                "note": "" if row.status == RowStatus.COMPLETED else row.message,
            }
        )
    return out


def sections(batch: BulkCompletionBatch) -> list[dict]:
    """Each non-empty section with its rows, as the page lists them."""
    out = []
    for key, label, statuses in SECTIONS:
        rows = batch.rows.filter(status__in=statuses).order_by("row_number")
        if rows.exists():
            out.append(
                {
                    "key": key,
                    "label": label,
                    "rows": _decorated(rows),
                    "param": f"{key}_page",
                }
            )
    return out


def earlier_upload(batch: BulkCompletionBatch):
    """The same file uploaded before by anyone, or None."""
    return (
        BulkCompletionBatch.objects.filter(
            file_sha256=batch.file_sha256, created_at__lt=batch.created_at
        )
        .exclude(pk=batch.pk)
        .order_by("-created_at")
        .first()
    )


#: The ID columns whose values must already be in Edify, in report order.
ID_COLUMNS = ("planned_activity_id", "school_id")


def missing_ids(batch: BulkCompletionBatch) -> list[tuple[str, str, str]]:
    """(column, ID, rows) for each ID the file gives that Edify does not
    hold: every planned_activity_id first, then every school_id, each once."""
    rows_of: dict[tuple[str, str], list[str]] = {}
    noted = (
        batch.rows.exclude(missing_ids={})
        .order_by("row_number")
        .values_list("row_number", "missing_ids")
    )
    for column in ID_COLUMNS:
        for number, missing in noted:
            if missing.get(column):
                rows_of.setdefault((column, missing[column]), []).append(str(number))
    return [
        (column, value, ", ".join(rows)) for (column, value), rows in rows_of.items()
    ]


def error_report_sheets(batch: BulkCompletionBatch) -> list[dict]:
    """The lines that were not completed, as uploaded, with the reason; and
    the IDs Edify does not hold, on a sheet of their own."""
    sheets = [_not_completed_sheet(batch)]
    missing = missing_ids(batch)
    if missing:
        sheets.append(
            {
                "title": "Missing IDs",
                "headers": ["Column", "ID", "Rows"],
                "rows": [list(item) for item in missing],
            }
        )
    return sheets


def _not_completed_sheet(batch: BulkCompletionBatch) -> dict:
    rows = batch.rows.filter(
        status__in=(*PROBLEM_STATUSES, *SKIPPED_STATUSES)
    ).order_by("row_number")
    headings: list[str] = []
    for row in rows:
        for heading in row.raw or {}:
            if heading not in headings:
                headings.append(heading)
    statuses = activity_statuses(row.activity_id for row in rows)
    return {
        "title": "Not completed",
        "headers": ["Row", "Outcome", "Status", "Reason", *headings],
        "rows": [
            [
                row.row_number,
                row.get_status_display(),
                statuses.get(row.activity_id, ("Not matched", ""))[0],
                row.message,
                *[(row.raw or {}).get(h, "") for h in headings],
            ]
            for row in rows
        ],
    }
