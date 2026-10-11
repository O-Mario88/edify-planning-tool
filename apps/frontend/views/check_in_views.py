"""The Programme Lead's weekly check-in: one page per officer.

The Lead opens an officer, reads the week with them, records what was agreed
through the coaching drawer, and moves to the next officer. See
apps.cce_leadership.check_in.
"""

from __future__ import annotations

from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.cce_leadership import check_in, coaching
from apps.core.permissions import require_page_permission
from apps.core.rbac import EdifyRole

COACHING_URL = "/team/coaching"


def _is_lead(request) -> bool:
    return request.user.active_role == EdifyRole.COUNTRY_PROGRAM_LEAD.value


@require_page_permission("team_coaching")
@require_http_methods(["GET"])
def check_in_start_view(request):
    """Open the first officer not yet checked in with this week."""
    members = check_in.team_order(request.user) if _is_lead(request) else []
    if not members:
        return redirect(COACHING_URL)
    held = check_in.held_this_week(members)
    first = next((m for m in members if m.id not in held), members[0])
    return redirect(f"{check_in.URL}/{first.id}")


@require_page_permission("team_coaching")
@require_http_methods(["GET"])
def check_in_view(request, staff_id):
    """One officer's week, what was agreed last time, and the way onward."""
    if not _is_lead(request):
        return redirect(COACHING_URL)
    member = coaching.officer_for(request.user, staff_id)
    if member is None:
        return redirect(COACHING_URL)
    today = timezone.localdate()
    members = check_in.team_order(request.user)
    previous, following = check_in.neighbours(members, member)
    held = check_in.held_this_week(members, today=today)
    start, end = check_in.week_of(today)
    return render(
        request,
        "pages/check_in/index.html",
        {
            "member": member,
            "officer_name": getattr(member.user, "name", "") or "Officer",
            "facts": check_in.week_facts(member, today=today),
            "last": check_in.last_check_in(member, today=today),
            "held_this_week": member.id in held,
            "held_count": len(held),
            "team_count": len(members),
            "position": members.index(member) + 1,
            "previous": previous,
            "following": following,
            "week_start": start,
            "week_end": end,
        },
    )
