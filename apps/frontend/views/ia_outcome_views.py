"""Download the live evidence annex of the project cohort (IA review, 2026-09-13).

This was the whole "impact report": a CSV of the outcome workspace with the
assessor's interpretation typed into three textareas, for every recorded
enrolment whatever the period, naming nobody who generated it and auditing
nothing. Reports now live in apps.impact.reports, where submission freezes
their own annex; this download stays as the live, draft annex:

  - the period chosen (a financial year, and optional dates within it)
    reaches every row and count — a measured enrolment by its follow-up
    assessment, any other by its follow-up due date;
  - the header names who generated it, in which role, and carries a sha256 of
    the rows, so a file can be matched to what the platform held;
  - numbers stay numbers (only text a spreadsheet would read as a formula is
    neutralised);
  - every download writes an audit row, without the narrative.
"""

import hashlib
from datetime import date, timedelta

from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.http import require_POST

from apps.analytics.ia_workflow import outcome_workspace
from apps.core.permissions import RolePermissionService, require_page_permission

ROW_KEYS = (
    "project",
    "project_id",
    "school",
    "school_id",
    "intervention",
    "status",
    "baseline",
    "follow_up",
    "delta",
    "baseline_date",
    "follow_up_date",
    "baseline_id",
    "follow_up_id",
    "mapping_version",
    "due",
    "owner",
    "action",
)


def _period(data) -> tuple[date | None, date | None, str]:
    """(start, end, label) from a financial year and optional dates."""
    from apps.core.fy import fy_options, get_fy_date_range

    fy = str(data.get("fy") or "").strip()
    start = end = None
    if fy:
        if fy not in fy_options():
            raise ValueError("Choose a financial year from the list.")
        fy_start, fy_end = get_fy_date_range(fy)
        start, end = fy_start.date(), (fy_end - timedelta(days=1)).date()
    for key in ("period_start", "period_end"):
        raw = str(data.get(key) or "").strip()
        if not raw:
            continue
        try:
            chosen = date.fromisoformat(raw)
        except ValueError:
            raise ValueError("Period dates must be dates (YYYY-MM-DD).") from None
        if key == "period_start":
            start = max(start, chosen) if start else chosen
        else:
            end = min(end, chosen) if end else chosen
    if start and end and start > end:
        raise ValueError("The period must start before it ends.")
    if not start and not end:
        return (
            None,
            None,
            "All recorded project enrolments; each uses its own assessment window",
        )
    label = f"{start.isoformat() if start else 'the start'} to {end.isoformat() if end else 'today'}"
    if fy:
        label = f"FY{fy}: {label}"
    return start, end, label


@require_POST
@require_page_permission("ia_dashboard")
def impact_report_download(request):
    from apps.audit.services import log as audit_log
    from apps.core.audit_hash import stable_stringify
    from apps.impact.reports import rows_in_period, summarise_rows, write_csv

    if not RolePermissionService.can_export(request.user, "ia_dashboard"):
        return HttpResponseForbidden("Export permission required.")
    try:
        start, end, period = _period(request.POST)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    snapshot = outcome_workspace(request.user, request.POST)
    rows, undated = rows_in_period(snapshot["rows"], start, end)
    summary = summarise_rows(rows)
    data_rows = [[item.get(key) for key in ROW_KEYS] for item in rows]
    payload_hash = hashlib.sha256(
        stable_stringify([list(ROW_KEYS), *data_rows]).encode("utf-8")
    ).hexdigest()

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="ia-impact-evidence.csv"'
    response["Cache-Control"] = "no-store"
    out: list[list] = [
        ["Impact Assessment evidence annex", "Draft for review"],
        ["generated_at", snapshot["generated_at"]],
        ["generated_by", request.user.name],
        ["generated_by_role", request.user.active_role],
        ["scope_label", snapshot["scope_label"]],
        ["period", period],
        ["rows_sha256", payload_hash],
    ]
    for key in (
        "total",
        "unique_schools",
        "measured",
        "unmeasured",
        "improved",
        "declined",
        "maintained",
        "no_change",
        "baseline_missing",
        "overdue",
    ):
        out.append([key, summary[key]])
    if start or end:
        out.append(["enrolments_without_a_date_in_any_period", undated])
    out += [
        ["limitation", snapshot["limitation"]],
        ["Counting unit", "Project-school enrolments, not unique schools"],
    ]
    for key, label in (
        ("findings", "Findings and qualitative evidence references"),
        ("limitations", "Additional limitations"),
        ("recommendations", "Recommendations, action owners and follow-up dates"),
    ):
        text = request.POST.get(key, "")[:10000]
        if text:
            out.append([label, text])
    out.append([])
    out.append(list(ROW_KEYS))
    out += data_rows
    write_csv(response, out)
    audit_log(
        action="ia.evidence_annex.downloaded",
        subject_kind="IAEvidenceAnnex",
        subject_id=payload_hash[:32],
        actor_id=str(request.user.id),
        actor_role=request.user.active_role,
        payload={
            "project": request.POST.get("project") or None,
            "period": period,
            "scope_label": snapshot["scope_label"],
            "row_count": len(rows),
            "measured": summary["measured"],
            "rows_sha256": payload_hash,
        },
    )
    return response
