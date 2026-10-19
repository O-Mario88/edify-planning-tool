"""Leadership pages that read decisions and their evidence.

Decision Intelligence, the page for the leadership and budget engines, left
with the Analytics entry; its review is on the Country Profile now
(views/profile_decisions.py, owner, 2026-10-19).
"""

from __future__ import annotations

from apps.core.redirects import local_redirect
from apps.core.fy import fy_options, get_operational_fy
from apps.core.permissions import require_page_permission


@require_page_permission("declining_schools")
def declining_schools_view(request):
    """Which schools are losing ground, and which interventions are failing.

    The platform computed per-school FY-over-FY deltas and per-intervention
    trends but ranked neither: the only school-identified queue sorted by
    absolute low score, so a strong school in freefall stayed invisible while
    perennially-weak schools filled the list.

    IA review (owner, 2026-09-13): both columns follow the one definition of
    declined (apps.ssa.change_rules) and the page names the rule; interventions
    carry their labels and the owner's abbreviations; a school row opens the
    school where the reader may see school detail; and a financial year that is
    not one of the platform's options (a typed ?fy=abc used to raise) falls back
    to the current year, with every year on offer in the select.
    """
    from apps.analytics.decline_service import SEVERE_DROP, declining_schools
    from apps.core.fy import fy_options
    from apps.core.interventions import INTERVENTION_LABELS, intervention_abbr

    from apps.frontend.views.analytics_render import render_analytics_section

    # FY2025 is the platform's first year: it has no year before it to compare.
    options = [option for option in fy_options() if int(option) > 2025]
    fy = (request.GET.get("fy") or "").strip()
    if fy and fy not in options:
        # The workspace around this panel reads ?fy= too (its scope tiles), so
        # an unusable year is replaced in the address rather than only here.
        query = request.GET.copy()
        query["fy"] = get_operational_fy()
        return local_redirect(f"{request.path}?{query.urlencode()}")
    if fy not in options:
        fy = get_operational_fy()
    data = declining_schools(request.user, {"fy": fy})
    for row in data.get("interventions", []):
        row["label"] = INTERVENTION_LABELS.get(row["intervention"], row["intervention"])
        row["abbr"] = intervention_abbr(row["intervention"])
    for row in data.get("schools", []):
        code = row.get("worstIntervention") or ""
        row["worstLabel"] = INTERVENTION_LABELS.get(code, code)
    weakest = data.get("weakestIntervention") or ""
    data["weakestLabel"] = INTERVENTION_LABELS.get(weakest, "")
    data["weakestAbbr"] = intervention_abbr(weakest) if weakest else ""
    return render_analytics_section(
        request,
        "partials/analytics/panels/declining_schools.html",
        {
            "d": data,
            "fy_options": sorted(set(options) | {fy}, reverse=True),
            "severe_drop": SEVERE_DROP,
        },
        section_key="declining_schools",
        panel_title="Declining Schools",
        frame={
            "question": (
                "Which schools are losing ground fastest, where is decline "
                "concentrated, and what support failed to arrest it?"
            ),
            "evidence": "Schools with two confirmed consecutive SSA cycles",
            "freshness": "Selected financial year comparison",
            "confidence": "Confirmed paired assessments",
        },
    )


@require_page_permission("core_school_health")
def core_school_health_view(request):
    """Core-package health for CD and RVP.

    Their dashboards carried "Core Schools On Track / Behind" KPIs that linked
    to /core-schools — a page both roles are 403'd from — so the number had no
    reachable detail. §26 gate stalls were invisible above the field tier.
    """
    from apps.core_schools.leadership_service import core_school_health

    from apps.frontend.views.analytics_render import render_analytics_section

    fy = request.GET.get("fy") or get_operational_fy()
    return render_analytics_section(
        request,
        "partials/analytics/panels/core_school_health.html",
        {
            "d": core_school_health(request.user, {"fy": fy}),
            "fy_options": sorted(set(fy_options()) | {fy}, reverse=True),
        },
        section_key="core_school_health",
        panel_title="Core Verification",
        frame={
            "question": (
                "Which core-school packages are off track or stuck at the "
                "evidence gate, and what must happen next?"
            ),
            "evidence": "Package slots, evidence gates and SSA movement",
            "freshness": "Selected financial year",
            "confidence": "Verified programme records",
        },
    )


@require_page_permission("decision_log")
def decision_log_view(request):
    """Who decided what, scoped to the reader.

    A tamper-evident audit chain already existed, but every surface that reads
    it was Admin-, HR- or Accountant-only — so the roles with the most
    consequential powers had no way to see what had been decided.
    """
    from apps.audit.decision_log_service import decision_log

    from apps.frontend.views.analytics_render import render_analytics_section

    return render_analytics_section(
        request,
        "partials/analytics/panels/decision_log.html",
        {"log": decision_log(request.user, request.GET.dict())},
        section_key="decision_log",
        panel_title="Decision Log",
        frame={
            "question": (
                "What was decided, by whom, on what record, and with what "
                "stated reason?"
            ),
            "evidence": "Tamper-evident audit chain",
            "freshness": "Selected lookback window",
            "confidence": "System-recorded history",
        },
    )
