"""The decision review, on the Country Profile.

Two rules engines recommend decisions to leadership: the Leadership Decision
Engine (apps/leadership: recruitment gaps, staff capacity, partner performance,
HR risk, regional investment) and Budget Intelligence (apps/budget_intelligence:
aged advances, cash variance, returned cash, oversized advances). Their review
was the Decision Intelligence page until that page left with the Analytics
entry; the owner moved it here (2026-10-19: "Move the Decision Intelligence
review (leadership and budget insights, review and rescan) into the Country
Profile's Needs Attention for the CD and RVP").

So the Country Profile's Overview carries both queues, unreviewed and riskiest
first, with the Record form and the rescan, for a reader who holds the
`decision_intelligence` page; Needs Attention counts what awaits them and opens
the queue. The engines recommend; recording a decision changes nothing else.
"""

from __future__ import annotations

from django.contrib import messages
from django.views.decorators.http import require_POST

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.permissions import (
    RolePermissionService,
    has_permission,
    require_page_permission,
)
from apps.core.rbac import Permission
from apps.core.redirects import local_redirect

#: Where the queue sits on the Overview, and where its Record forms post.
ANCHOR = "profile-decisions"
REVIEW_URL = "/country-profile/decisions"

_RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

#: Statuses meaning "still needs a human decision" (DecisionStatus.NEW /
#: UNDER_REVIEW). The engines emit NEW, not a generic "pending".
UNDECIDED = {"new", "under_review"}

#: The decisions a reviewer may record: the terminal states a person chooses,
#: not the engines' own bookkeeping.
REVIEW_CHOICES = [
    ("accepted", "Accept"),
    ("accepted_with_conditions", "Accept with conditions"),
    ("rejected", "Reject"),
    ("deferred", "Defer"),
]


def open_first(insights: list[dict]) -> list[dict]:
    """Unreviewed and riskiest first: this is a work queue, not an archive.

    Also stamps `isUndecided` so the row asks one clear question instead of
    re-deriving the status vocabulary."""
    for insight in insights:
        insight["isUndecided"] = insight.get("status") in UNDECIDED
    return sorted(
        insights,
        key=lambda i: (
            not i["isUndecided"],
            _RISK_ORDER.get((i.get("riskLevel") or "").lower(), 9),
            -(i.get("confidenceScore") or 0),
        ),
    )


def for_reader(user, fy: str) -> dict | None:
    """Both queues for ``fy`` as ``user`` may review them; None for a reader
    who does not hold the decision review."""
    if not RolePermissionService.can_view_page(user, "decision_intelligence"):
        return None
    from apps.budget_intelligence import services as budget_engine
    from apps.leadership import services as leadership_engine

    query = {"fy": fy}
    operational = open_first(
        [
            insight
            for board in leadership_engine.boards(user, query).get("boards", [])
            for insight in board.get("insights", [])
        ]
    )
    financial = open_first(budget_engine.boards(user, query).get("insights", []))
    return {
        "fy": fy,
        "anchor": ANCHOR,
        "review_url": REVIEW_URL,
        "operational": operational,
        "financial": financial,
        "open_operational": sum(1 for i in operational if i["isUndecided"]),
        "open_financial": sum(1 for i in financial if i["isUndecided"]),
        "can_review_operational": has_permission(
            user, Permission.LEADERSHIP_DECISION_REVIEW.value
        ),
        "can_review_financial": has_permission(
            user, Permission.BUDGET_DECISION_REVIEW.value
        ),
        "statuses": REVIEW_CHOICES,
    }


def attention_links(decisions: dict) -> list[dict]:
    """Needs Attention's lines for the decisions awaiting the reader."""
    lines = []
    for kind in ("operational", "financial"):
        count = decisions[f"open_{kind}"]
        if count:
            noun = "decision awaits" if count == 1 else "decisions await"
            lines.append(
                {
                    "name": f"{count} {kind} {noun} you",
                    "href": f"#{ANCHOR}",
                    "key": f"decisions_{kind}",
                }
            )
    return lines


@require_POST
@require_page_permission("decision_intelligence")
def country_profile_decisions_view(request):
    """Record a decision on an insight, or rescan both engines, then return to
    the queue on the Country Profile."""
    from apps.budget_intelligence import services as budget_engine
    from apps.core.fy import fy_options, get_operational_fy
    from apps.leadership import services as leadership_engine

    fy = request.POST.get("fy", "")
    if fy not in fy_options():
        fy = str(get_operational_fy())
    action = request.POST.get("action")
    decision = {
        "status": request.POST.get("status"),
        "note": request.POST.get("note"),
    }
    may_review_operational = has_permission(
        request.user, Permission.LEADERSHIP_DECISION_REVIEW.value
    )
    may_review_financial = has_permission(
        request.user, Permission.BUDGET_DECISION_REVIEW.value
    )
    try:
        if action in ("review_leadership", "review_budget") and decision[
            "status"
        ] not in dict(REVIEW_CHOICES):
            raise BadRequest("Choose a decision.")
        if action == "review_leadership":
            if not may_review_operational:
                raise Forbidden("You may not review operational decisions.")
            leadership_engine.review(
                request.POST.get("insight_id"), decision, request.user
            )
            messages.success(request, "Decision recorded.")
        elif action == "review_budget":
            if not may_review_financial:
                raise Forbidden("You may not review financial decisions.")
            budget_engine.review(request.POST.get("insight_id"), decision, request.user)
            messages.success(request, "Decision recorded.")
        elif action == "recompute":
            # Regenerating both engines country-wide is a leadership act.
            if not (may_review_operational or may_review_financial):
                raise Forbidden("You may not rescan the decision engines.")
            lead = leadership_engine.recompute({"fy": fy}, request.user)
            budget = budget_engine.recompute({"fy": fy}, request.user)
            messages.success(
                request,
                f"Rescanned {fy}: {lead.get('generatedCount', 0)} operational "
                f"and {budget.get('generatedCount', 0)} financial insights.",
            )
        else:
            messages.error(request, "Unknown action.")
    except (BadRequest, Forbidden, NotFoundError) as exc:
        messages.error(request, str(exc))
    return local_redirect(f"/country-profile?fy={fy}#{ANCHOR}")
