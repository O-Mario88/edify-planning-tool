"""HR Today — the exception queue HR triages from (§6).

The page holds no state of its own. Everything on it comes from
`apps.hr.hr_exceptions`, which reads current workflow state, so there is
nothing to tick off and no way for the page to drift from the records.
"""

from __future__ import annotations

from django.shortcuts import render
from django.utils import timezone

from apps.accounts.hr_dashboard_service import HRDashboardService
from apps.core.permissions import require_page_permission
from apps.hr.hr_exceptions import (
    DEADLINES,
    MANAGER_OVERDUE,
    PEOPLE_RISK,
    WAITING_ON_HR,
    grouped_hr_exceptions,
    scoped_profiles,
)

VISIBLE_PER_QUEUE = 10

_CARD_HELPERS = {
    WAITING_ON_HR: "HR is the actor",
    MANAGER_OVERDUE: "past their decision window",
    PEOPLE_RISK: "need a decision or a repair",
    DEADLINES: "inside the next 30 days",
}


@require_page_permission("hr_today")
def hr_today_page(request):
    today = timezone.localdate()
    data = grouped_hr_exceptions(request.user, today)
    scope_label, scope_warning = HRDashboardService._scope_label(
        request.user, None, None, scoped_profiles(request.user).count()
    )

    cards = [
        {
            "key": group["key"],
            "label": group["label"],
            "count": len(group["items"]),
            "helper": _CARD_HELPERS[group["key"]],
        }
        for group in data["groups"]
    ]

    # The count above is the true total; the list below shows the worst few.
    # A queue that prints 27 identical rows is a wall, not a triage surface —
    # and the headline number has to stay honest about what it left out.
    for group in data["groups"]:
        group["total"] = len(group["items"])
        group["overflow"] = max(0, group["total"] - VISIBLE_PER_QUEUE)
        group["items"] = group["items"][:VISIBLE_PER_QUEUE]

    return render(
        request,
        "pages/hr/hr_today.html",
        {
            "cards": cards,
            "groups": data["groups"],
            "total": data["total"],
            "scope_label": scope_label,
            "scope_warning": scope_warning,
            "page_key": "hr_today",
        },
    )
