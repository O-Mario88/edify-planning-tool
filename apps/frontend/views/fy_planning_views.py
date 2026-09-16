"""Fiscal Year Planning — the governed planning window and follow-up rule.

Owner, 2026-09-15: FY2027 opens for planning while FY2026 is still being
closed, and school visit follow-ups may be planned without a prior training.
Both are policy, set here by the Country Director or Admin through
apps.planning.fy_policy, audited, never edited in the database.
"""

from __future__ import annotations

from datetime import datetime

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.core.permissions import require_page_permission


@require_page_permission("fy_planning_policy")
def fiscal_year_planning_view(request):
    from apps.planning import fy_policy
    from apps.planning.models import FiscalYearPlanningPolicy

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        fy = (request.POST.get("fy") or "").strip()
        try:
            if action == "open":
                raw_open = (request.POST.get("planning_open_at") or "").strip()
                open_at = (
                    timezone.make_aware(datetime.fromisoformat(raw_open))
                    if raw_open
                    else None
                )
                fy_policy.open_fy_planning(
                    fy,
                    request.user,
                    planning_open_at=open_at,
                    follow_up_visit_requires_prior_training=(
                        request.POST.get("follow_up_requires_training") == "yes"
                    ),
                    notes=(request.POST.get("notes") or "").strip(),
                )
                messages.success(request, f"FY{fy} is open for planning.")
            elif action == "follow_up_rule":
                fy_policy.set_follow_up_rule(
                    fy,
                    request.POST.get("follow_up_requires_training") == "yes",
                    request.user,
                    reason=request.POST.get("reason", ""),
                )
                messages.success(request, f"FY{fy} follow-up rule updated.")
            else:
                raise BadRequest("Choose an action.")
        except ValueError:
            messages.error(request, "Enter the opening date as a date and time.")
        except (BadRequest, Forbidden) as exc:
            messages.error(request, str(getattr(exc, "detail", exc)))
        return redirect("/planning/fiscal-years")

    operational = get_operational_fy()
    now = timezone.now()
    policies = list(FiscalYearPlanningPolicy.objects.order_by("-fy"))
    # A display annotation, derived by the policy service and never saved.
    # It is `window_state`, not `state`: a year's state is what the service
    # decides, and a view that writes a field called `state` on a workflow
    # record is exactly what the production-readiness scanner exists to catch.
    for policy in policies:
        policy.window_state = fy_policy.window_state(
            policy, at=now, operational=operational
        )
    next_fy = str(int(operational) + 1)
    context = {
        "policies": policies,
        "operational_fy": operational,
        "next_fy": next_fy,
        "next_fy_open": fy_policy.is_planning_open(next_fy),
        "can_manage": fy_policy.may_manage(request.user),
    }
    return render(request, "pages/planning/fiscal_years.html", context)
