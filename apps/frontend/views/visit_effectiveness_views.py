"""School Visit Effectiveness — one shared module, role-scoped depth.

Every role lands on the same canonical analysis (the engine applies scope);
the template varies emphasis: CCEO sees own-portfolio delivery quality, PL
team practice, IA cohort/data quality, CD-RVP strategy (quadrants, regional
variation, aggregate-only rows for RVP)."""

from __future__ import annotations

import json

from django.shortcuts import render

from apps.core.rbac import EdifyRole
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
    data = SchoolVisitEffectivenessAnalyticsService.build_dashboard(request.user, query)

    role = getattr(request.user, "active_role", "")
    context = {
        "d": data,
        "chart_payload": {k: json.loads(v) for k, v in data.get("charts", {}).items()},
        "selected_school_type": query["school_type"] or "",
        "is_field_role": role in ("CCEO", "ProjectCoordinator"),
        "is_pl": role == "Program Lead",
        "is_ia": role == "ImpactAssessment",
        "is_strategic": role in ("CountryDirector", "RegionalVicePresident", "Admin"),
        "debrief_context": _debrief_context(request.user),
        "visit_feedback_review": _visit_feedback_review(request.user),
    }
    # This section's own filter form swaps its workspace and nothing else. It
    # has to name its target: a tab click and a scope change are HX requests
    # too, and they ask for different shapes.
    if request.headers.get("HX-Target") == "vfx-workspace":
        return render(
            request, "partials/analytics/visit_effectiveness_workspace.html", context
        )
    from apps.frontend.views.analytics_render import render_analytics_section

    return render_analytics_section(
        request,
        "partials/analytics/panels/visit_effectiveness.html",
        context,
        section_key="visit_effectiveness",
        panel_title="School Visit Effectiveness",
        frame={
            "question": (
                "Are school visits reaching the right schools with enough "
                "quality and frequency to support improvement?"
            ),
            "evidence": "Delivered visits and comparable confirmed SSA cycles",
            "freshness": "Current comparison cohort",
            "confidence": "Association, not attribution",
        },
    )


def _visit_feedback_review(principal) -> list[dict]:
    """Recent field feedback for the four decision-review roles.

    IA/CD see their country, PL sees their assigned and supervised portfolios,
    and RVP sees its regional scope with school identity redacted in line with
    the existing summary-only policy.
    """
    review_roles = {
        EdifyRole.IMPACT_ASSESSMENT.value,
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        EdifyRole.REGIONAL_VICE_PRESIDENT.value,
    }
    if getattr(principal, "active_role", "") not in review_roles:
        return []

    from apps.activities.models import Activity, SchoolVisitFeedback
    from apps.core.scoping import resolve_user_scope, scoped_school_queryset

    scope = resolve_user_scope(principal)
    schools = scoped_school_queryset(scope)
    feedback_rows = list(
        SchoolVisitFeedback.objects.filter(
            activity__school_id__in=schools.values("id"),
            activity__deleted_at__isnull=True,
        )
        .select_related(
            "activity",
            "activity__school",
            "activity__school__region",
            "activity__school__district",
            "activity__follow_up_of_activity",
        )
        .order_by("-created_at")[:30]
    )
    paired_trainings = {
        activity.paired_school_visit_id: activity
        for activity in Activity.objects.filter(
            paired_school_visit_id__in=[row.activity_id for row in feedback_rows],
            deleted_at__isnull=True,
        )
    }
    can_view_school_details = scope.can_view_school_level_detail
    return [
        {
            "feedback": row,
            "activity": row.activity,
            "activity_date": (
                row.activity.actual_delivery_date
                or row.activity.planned_date
                or (
                    row.activity.scheduled_date.date()
                    if row.activity.scheduled_date
                    else None
                )
            ),
            "related_activity": paired_trainings.get(row.activity_id)
            or row.activity.follow_up_of_activity,
            "school_name": row.activity.school.name
            if can_view_school_details
            else "School identity protected",
            "school_id": row.activity.school.school_id
            if can_view_school_details
            else "",
            "location": " · ".join(
                value
                for value in (
                    getattr(row.activity.school.district, "name", ""),
                    getattr(row.activity.school.region, "name", ""),
                )
                if value
            ),
            "can_link_school": can_view_school_details
            and getattr(principal, "active_role", "")
            in {
                EdifyRole.IMPACT_ASSESSMENT.value,
                EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            },
        }
        for row in feedback_rows
    ]


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
        return [c for c in clusters if c["kind"] == "challenge"][:6]
    except Exception:  # context enrichment must never break the analysis page
        return []
