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

#: From this many, rows that say the same thing about different people are one
#: row (2026-10-01). A year's missed review cycle put "Performance review
#: overdue · FY2026 review is 335 days late" on the page thirty-three times,
#: one per person: the ten rows shown were the same sentence ten times and the
#: other queues' items never got a line. Two alike stay as two — a pair is
#: quicker to read than to unfold.
FOLD_FROM = 3


def _fold_identical(items: list[dict]) -> list[dict]:
    """One row per distinct exception; who it concerns becomes a list.

    Rows are alike when what, why, when and how serious all match. A folded
    row keeps the first one's place in the queue, so urgency order holds.
    """
    alike: dict[tuple, list[dict]] = {}
    for item in items:
        key = (item["title"], item["detail"], item["due_label"], item["severity"])
        alike.setdefault(key, []).append(item)
    rows = []
    for same in alike.values():
        if len(same) < FOLD_FROM:
            rows.extend(same)
            continue
        rows.append(
            {
                **same[0],
                "count": len(same),
                "people": [
                    {"name": item["person"] or "Unnamed", "url": item["url"]}
                    for item in same
                ],
            }
        )
    return rows


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
    # and the headline number has to stay honest about what it left out. Rows
    # alike in everything but the person are folded first, so the ten lines
    # shown are ten different things; the overflow counts what is not shown,
    # in exceptions, as the total does.
    for group in data["groups"]:
        group["total"] = len(group["items"])
        rows = _fold_identical(group["items"])
        group["items"] = rows[:VISIBLE_PER_QUEUE]
        shown = sum(row.get("count", 1) for row in group["items"])
        group["overflow"] = max(0, group["total"] - shown)
        group["folded"] = len(rows) < group["total"]

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
