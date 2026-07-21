"""Decision Intelligence — the page for engines that had none.

Two complete rules engines were shipped without any way to open them:

  • The Leadership Decision Engine (apps/leadership) runs five detectors —
    recruitment gaps, staff capacity overload, partner performance, HR risk and
    regional investment — and CD/RVP/PL all hold leadership.view and
    leadership.review.
  • Budget Intelligence (apps/budget_intelligence) runs four financial
    detectors — aged unaccounted advances, disbursed-vs-accounted cash
    variance, returned cash, and oversized pending advances.

Both were wired only as /api/* endpoints. Every insight they produced was
computed, scored, stored — and seen by nobody, because there was no template,
no route and no sidebar entry anywhere in the platform.

This page is that missing surface, and it deliberately merges the two: a
decision-maker does not think in terms of which subsystem generated a signal,
and splitting them across two pages would recreate the fragmentation the audit
found everywhere else.
"""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect, render

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy
from apps.core.permissions import has_permission, require_page_permission
from apps.core.rbac import Permission


_RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# Statuses meaning "still needs a human decision" (DecisionStatus.NEW /
# UNDER_REVIEW). The engines emit NEW, not a generic "pending".
UNDECIDED = {"new", "under_review"}

# The decisions a reviewer may record. A subset of DecisionStatus — the
# terminal states a person actually chooses, not the engine's own bookkeeping.
REVIEW_CHOICES = [
    ("accepted", "Accept"),
    ("accepted_with_conditions", "Accept with conditions"),
    ("rejected", "Reject"),
    ("deferred", "Defer"),
]


@require_page_permission("decision_intelligence")
def decision_intelligence_view(request):
    from apps.budget_intelligence import services as budget_engine
    from apps.leadership import services as leadership_engine

    fy = request.GET.get("fy") or get_operational_fy()
    can_review_leadership = has_permission(
        request.user, Permission.LEADERSHIP_DECISION_REVIEW.value
    )
    can_review_budget = has_permission(
        request.user, Permission.BUDGET_DECISION_REVIEW.value
    )

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "review_leadership":
                if not can_review_leadership:
                    raise Forbidden("You may not review leadership insights.")
                leadership_engine.review(
                    request.POST.get("insight_id"),
                    {
                        "status": request.POST.get("status"),
                        "note": request.POST.get("note"),
                    },
                    request.user,
                )
                messages.success(request, "Decision recorded.")
            elif action == "review_budget":
                if not can_review_budget:
                    raise Forbidden("You may not review financial insights.")
                budget_engine.review(
                    request.POST.get("insight_id"),
                    {
                        "status": request.POST.get("status"),
                        "note": request.POST.get("note"),
                    },
                    request.user,
                )
                messages.success(request, "Decision recorded.")
            elif action == "recompute":
                # Regenerating both engines country-wide is a leadership act.
                # This branch had no permission check at all, so any role that
                # could open the page could trigger it.
                if not (can_review_leadership or can_review_budget):
                    raise Forbidden("You may not regenerate the decision engines.")
                lead = leadership_engine.recompute({"fy": fy}, request.user)
                budget = budget_engine.recompute({"fy": fy}, request.user)
                messages.success(
                    request,
                    f"Rescanned {fy}: {lead.get('generatedCount', 0)} leadership "
                    f"and {budget.get('generatedCount', 0)} financial insights.",
                )
            else:
                messages.error(request, "Unknown action.")
        except (BadRequest, Forbidden, NotFoundError) as exc:
            messages.error(request, str(exc))
        return redirect(f"/decisions?fy={fy}")

    leadership = leadership_engine.boards(request.user, {"fy": fy})
    leadership_snapshot = leadership_engine.snapshot(request.user, {"fy": fy})
    budget = budget_engine.boards(request.user, {"fy": fy})
    budget_snapshot = budget_engine.snapshot(request.user, {"fy": fy})

    leadership_insights = _open_first(
        [i for board in leadership.get("boards", []) for i in board.get("insights", [])]
    )
    budget_insights = _open_first(budget.get("insights", []))

    return render(
        request,
        "pages/decisions/index.html",
        {
            "fy": fy,
            "fy_options": [fy, str(int(fy) - 1)],
            "leadership_insights": leadership_insights,
            "budget_insights": budget_insights,
            "leadership_snapshot": leadership_snapshot,
            "budget_snapshot": budget_snapshot,
            "can_review_leadership": can_review_leadership,
            "can_review_budget": can_review_budget,
            "open_leadership": sum(
                1 for i in leadership_insights if i["status"] in UNDECIDED
            ),
            "open_budget": sum(1 for i in budget_insights if i["status"] in UNDECIDED),
            "statuses": REVIEW_CHOICES,
            "undecided": sorted(UNDECIDED),
        },
    )


@require_page_permission("declining_schools")
def declining_schools_view(request):
    """Which schools are losing ground, and which interventions are failing.

    The platform computed per-school FY-over-FY deltas and per-intervention
    trends but ranked neither: the only school-identified queue sorted by
    absolute low score, so a strong school in freefall stayed invisible while
    perennially-weak schools filled the list.
    """
    from apps.analytics.decline_service import MATERIAL_DROP, declining_schools

    fy = request.GET.get("fy") or get_operational_fy()
    data = declining_schools(request.user, {"fy": fy})
    return render(
        request,
        "pages/analytics/declining_schools.html",
        {
            "d": data,
            "fy_options": [fy, str(int(fy) - 1)],
            "material_drop": MATERIAL_DROP,
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

    fy = request.GET.get("fy") or get_operational_fy()
    return render(
        request,
        "pages/core_schools/leadership.html",
        {
            "d": core_school_health(request.user, {"fy": fy}),
            "fy_options": [fy, str(int(fy) - 1)],
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

    return render(
        request,
        "pages/audit/decision_log.html",
        {"log": decision_log(request.user, request.GET.dict())},
    )


def _open_first(insights: list[dict]) -> list[dict]:
    """Unreviewed and riskiest first — this is a work queue, not an archive.

    Also stamps `isUndecided` so templates ask one clear question instead of
    each re-deriving the status vocabulary (and getting it wrong).
    """
    for i in insights:
        i["isUndecided"] = i.get("status") in UNDECIDED
    return sorted(
        insights,
        key=lambda i: (
            not i["isUndecided"],
            _RISK_ORDER.get((i.get("riskLevel") or "").lower(), 9),
            -(i.get("confidenceScore") or 0),
        ),
    )
