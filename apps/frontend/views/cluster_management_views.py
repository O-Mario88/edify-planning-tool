"""Cluster Management: one page, its sections as tabs, and the scoring page.

Owner brief, 2026-10-08. The page is a reader over the clusters in the
person's own scope (apps.clusters.workspace); every section is one table from
the same reads the cluster profile's tabs make, and every section downloads
as CSV. The scoring page is where the Country Director and Impact Assessment
set what the scores weigh (apps.clusters.scores).
"""

from __future__ import annotations

import csv

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.clusters import scores, workspace
from apps.core.exceptions import BadRequest
from apps.core.fy import fy_options, get_operational_fy
from apps.core.permissions import (
    RolePermissionService,
    require_export_permission,
    require_page_permission,
)


def _fy(request) -> tuple[str, list[str]]:
    options = sorted(fy_options(), reverse=True)
    asked = (request.GET.get("fy") or "").strip()
    return (asked if asked in options else get_operational_fy()), options


def _csv(table, section_key: str, fy: str) -> HttpResponse:
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="cluster-management-{section_key}-fy{fy}.csv"'
    )
    writer = csv.writer(response)
    for line in table.as_csv_rows():
        # A cell that begins with =, +, - or @ is a formula to a spreadsheet;
        # a quote in front keeps a school's name from being run as one. A
        # signed figure ("+1.5", "-0.3") is a number and is left as it is.
        writer.writerow(
            [
                f"'{value}"
                if value[:1] in ("=", "@")
                or (value[:1] in ("+", "-") and not _is_number(value))
                else value
                for value in line
            ]
        )
    return response


def _is_number(value: str) -> bool:
    try:
        float(value.replace(",", "").rstrip("%"))
    except ValueError:
        return False
    return True


@require_page_permission("cluster_management")
@require_export_permission
def cluster_management_view(request, section: str = ""):
    key = section or workspace.DEFAULT_SECTION
    chosen = workspace.SECTION_BY_KEY.get(key)
    if chosen is None:
        return redirect("/cluster-management/")
    if chosen.url:
        return redirect(chosen.url)

    fy, options = _fy(request)
    ws = workspace.load(request.user, fy=fy)
    area = (request.GET.get("area") or "").strip()
    view = (request.GET.get("view") or "").strip()
    if view not in workspace.IMPACT_VIEWS:
        view = workspace.IMPACT_VIEWS[0]
    table = workspace.build(ws, key, area=area, view=view)

    if request.GET.get("format") == "csv":
        return _csv(table, key, fy)

    for row in table.rows:
        for column, cell in zip(table.columns, row["cells"]):
            cell["numeric"] = column["numeric"]
            cell["label"] = column["label"]

    from apps.core.enums import SsaIntervention

    sections = [
        {
            "key": s.key,
            "label": s.label,
            "description": s.description,
            "is_active": s.key == key,
            "is_door": bool(s.url),
        }
        for s in workspace.SECTIONS
        # My Clusters is for someone who holds one.
        if s.key != "my" or ws.my_ids
    ]
    return render(
        request,
        "pages/cluster_management/index.html",
        {
            "section": chosen,
            "sections": sections,
            "table": table,
            "fy": fy,
            "fy_options": options,
            "ssa_area": area if area in dict(SsaIntervention.choices) else "",
            "ssa_areas": SsaIntervention.choices,
            "impact_view": view,
            "can_export": RolePermissionService.can_export(request.user, request.path),
            "can_set_weights": RolePermissionService.can_view_page(
                request.user, "cluster_scoring"
            ),
        },
    )


@require_page_permission("cluster_scoring")
@require_http_methods(["GET", "POST"])
def cluster_scoring_view(request):
    """What each score weighs, and what each maturity level asks."""
    if request.method == "POST":
        weights = {
            key: {
                dim: request.POST.get(f"{key}__{dim}", "")
                for dim, _label, _default in dimensions
            }
            for key, (_title, dimensions) in scores.SCORES.items()
        }
        maturity = {
            rule: request.POST.get(f"maturity__{rule}", "")
            for rule in scores.MATURITY_DEFAULTS
        }
        try:
            scores.save_settings(
                weights=weights,
                maturity=maturity,
                actor_id=str(request.user.id),
                note=request.POST.get("note", ""),
            )
        except BadRequest as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                "Weights saved. Every cluster's scores now use them.",
            )
        return redirect("/cluster-management/scoring")

    settings = scores.current_settings()
    groups = []
    for key, (title, dimensions) in scores.SCORES.items():
        weights = settings.weights[key]
        total = sum(weights.values()) or 1
        groups.append(
            {
                "key": key,
                "title": title,
                "not_collected": scores.NOT_COLLECTED.get(key, ()),
                "parts": [
                    {
                        "key": dim,
                        "label": label,
                        "weight": weights[dim],
                        "default": default,
                        "share": round(100 * weights[dim] / total),
                    }
                    for dim, label, default in dimensions
                ],
            }
        )
    from apps.accounts.models import User

    return render(
        request,
        "pages/cluster_management/scoring.html",
        {
            "groups": groups,
            "maturity": [
                {
                    "key": rule,
                    "label": scores.MATURITY_LABELS[rule],
                    "value": settings.maturity[rule],
                    "default": default,
                }
                for rule, default in scores.MATURITY_DEFAULTS.items()
            ],
            "settings": settings,
            "set_by_name": (
                User.objects.filter(id=settings.set_by)
                .values_list("name", flat=True)
                .first()
                if settings.set_by
                else ""
            ),
        },
    )
