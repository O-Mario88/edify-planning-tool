"""School Visit Effectiveness — one shared module, role-scoped depth.

Every role lands on the same canonical analysis (the engine applies scope);
the template varies emphasis: CCEO sees own-portfolio delivery quality, PL
team practice, IA cohort/data quality, CD-RVP strategy (quadrants, regional
variation, aggregate-only rows for RVP)."""

from __future__ import annotations

import json

from django.shortcuts import render

from apps.core.permissions import require_page_permission


@require_page_permission("visit_effectiveness")
def visit_effectiveness_view(request):
    from apps.analytics.visit_effectiveness_engine import (
        SchoolVisitEffectivenessAnalyticsService,
    )

    query = {
        "school_type": request.GET.get("school_type") or None,
        "baseline_fy": request.GET.get("baseline_fy") or None,
        "followup_fy": request.GET.get("followup_fy") or None,
    }
    data = SchoolVisitEffectivenessAnalyticsService.build_dashboard(
        request.user, query
    )

    role = getattr(request.user, "active_role", "")
    context = {
        "d": data,
        "chart_payload": {
            k: json.loads(v) for k, v in data.get("charts", {}).items()
        },
        "selected_school_type": query["school_type"] or "",
        "is_field_role": role in ("CCEO", "ProjectCoordinator"),
        "is_pl": role == "Program Lead",
        "is_ia": role == "ImpactAssessment",
        "is_strategic": role in ("CountryDirector", "RegionalVicePresident", "Admin"),
        "debrief_context": _debrief_context(request.user),
    }
    if request.headers.get("HX-Request") == "true":
        return render(
            request, "partials/analytics/visit_effectiveness_workspace.html", context
        )
    return render(request, "pages/analytics/visit_effectiveness.html", context)


def _debrief_context(principal) -> list[dict]:
    """'What the Data Does Not Explain' (mandate §17): consolidated debrief
    challenge themes from the last 30 days in the viewer's scope — context
    for why the same visit model performs differently, never scores."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.debriefs.field_debrief_service import FieldDebriefService
    from apps.debriefs.models import DebriefKind
    from apps.debriefs.weekly_report_service import _consolidate

    try:
        debriefs = list(
            FieldDebriefService.scoped_queryset(principal)
            .filter(
                kind=DebriefKind.DAILY,
                date__gte=timezone.now() - timedelta(days=30),
                is_restricted_incident=False,
            )
            .order_by("-date")[:400]
        )
        clusters = _consolidate(debriefs)
        return [
            c for c in clusters if c["kind"] == "challenge"
        ][:6]
    except Exception:  # context enrichment must never break the analysis page
        return []
