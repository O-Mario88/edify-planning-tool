"""Download a scoped evidence report with the assessor's interpretation."""

import csv

from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST

from apps.analytics.ia_workflow import outcome_workspace
from apps.core.permissions import RolePermissionService, require_page_permission


def csv_cell(value):
    text = "" if value is None else str(value)
    return (
        "'" + text
        if text.lstrip().startswith(("=", "+", "-", "@"))
        or text.startswith(("\t", "\r", "\n"))
        else text
    )


@require_POST
@require_page_permission("ia_dashboard")
def impact_report_download(request):
    if not RolePermissionService.can_export(request.user, "ia_dashboard"):
        return HttpResponseForbidden("Export permission required.")
    snapshot = outcome_workspace(request.user, request.POST)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="ia-impact-evidence.csv"'
    response["Cache-Control"] = "no-store"
    writer = csv.writer(response)

    def row(values):
        writer.writerow([csv_cell(value) for value in values])

    row(["Impact Assessment evidence report", "Draft for review"])
    for key in (
        "generated_at",
        "scope_label",
        "period",
        "total",
        "measured",
        "unmeasured",
        "improved",
        "declined",
        "maintained",
        "no_change",
        "limitation",
    ):
        row([key, snapshot[key]])
    row(["Counting unit", "Project-school enrolments, not unique schools"])
    for key, label in (
        ("findings", "Findings and qualitative evidence references"),
        ("limitations", "Additional limitations"),
        ("recommendations", "Recommendations, action owners and follow-up dates"),
    ):
        row([label, request.POST.get(key, "")[:10000]])
    row([])
    keys = (
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
    row(keys)
    for item in snapshot["rows"]:
        row([item[key] for key in keys])
    return response
