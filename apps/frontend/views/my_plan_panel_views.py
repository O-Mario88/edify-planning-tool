"""The parts of My Plan that are asked for once the page has been drawn.

Read from production on 2026-10-13: My Plan took a median of 4.5 seconds to
answer, and the person's own Planned and remaining was more than a quarter of
it. That table reads every school the person holds (one and a half thousand
for some) to put six lines above the plan, and the plan below it waited for
them. The page now answers with the plan and leaves a place for the table,
which is asked for straight after (`templates/partials/my_plan/readiness.html`).

The panel is given the page's own query string, so the year it shows and the
links its figures carry are the page's.
"""

from __future__ import annotations

from datetime import date

from django.shortcuts import render

from apps.core.fy import get_operational_fy
from apps.core.permissions import require_page_permission


def plans_visits(principal) -> bool:
    """Whether this person has a Planned and remaining of their own: a
    Programme Lead or a CCEO. Asked without reading anything, as
    `planning_monitor.own_monitor` asks it before it reads."""
    from apps.planning.country_oversight import rules
    from apps.planning.monitor_roster import _role_code

    return bool(
        _role_code(
            rules.planning_role(
                getattr(principal, "roles", None),
                getattr(principal, "active_role", None),
            )
            or ""
        )
    )


def training_summary(principal, fy: str) -> dict:
    """My Training Summary (owner, 2026-10-06): the reader's own training
    ceilings and what they have scheduled under them, never another
    officer's, with the line over the card in the Project Capacity shape."""
    from apps.planning.training_ceilings import own_summary, summary_totals

    rows = own_summary(principal, str(fy))
    return {"my_training_summary": rows, "my_training_totals": summary_totals(rows)}


@require_page_permission("my_plan")
def my_plan_readiness_view(request):
    """The person's own Planned and remaining and their training summary,
    for the place My Plan left."""
    from apps.frontend.views.my_plan_views import _readiness_list
    from apps.my_plan.services import _own_readiness

    # The year My Plan itself resolves (`get_frontend_context`).
    fy = request.GET.get("fy") or get_operational_fy(date.today())
    context = {
        "fy": fy,
        "readiness": _own_readiness(request.user, fy),
        **training_summary(request.user, fy),
    }
    context["plan_list"] = _readiness_list(request, context)
    return render(request, "partials/my_plan/readiness_panel.html", context)
