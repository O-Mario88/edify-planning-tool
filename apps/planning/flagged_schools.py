"""Flagged schools, grouped by the person who owns them.

§12's Team School Oversight, delivered as a section on Team Oversight rather
than a page of its own: plans, clusters and flagged schools are three lenses on
one team, and splitting them across three pages makes a supervisor visit three
places to answer one question.

**The flag vocabulary is not defined here.** `urgent_attention.resolve_urgent_issue`
is the canonical classifier — no SSA first, then no visit or training, then the
recommendation engine's top unresolved item — and a second definition of
"flagged" living in an oversight page is exactly the parallel system that makes
two surfaces disagree about the same school. This module asks a different
*question* of that classifier, not a different classification.

The question differs from the dashboard card in one deliberate way. The card is
an **unassigned queue**: it hides a school once somebody owns the problem, so
two people cannot send the same action twice. Oversight is the opposite — a
supervisor needs to see that a flagged school *is* being handled, and by whom.
So delegated schools stay, carrying the state of the action that covers them.

Read-only by construction: it returns rows, no action ids and no forms. §12
says team oversight opens an oversight record rather than an editable school
page, and the way to guarantee that is to hand the template nothing it could
submit.
"""

from __future__ import annotations

from datetime import date

from apps.planning.oversight_service import resolve_oversight_scope

# A supervisor scanning for problems does not need the tail. Past this many the
# page stops being a decision aid and becomes a report, and the count above the
# list still reports the true total — see `total` below.
MAX_ROWS_PER_OWNER = 25


def _month_bounds(fy: str, month: int):
    from apps.core.fy import get_fy_date_range

    start, end = get_fy_date_range(fy)
    year = start.year if month >= start.month else start.year + 1
    first = date(year, month, 1)
    last = date(year + (month == 12), (month % 12) + 1, 1)
    return first, last


def team_flagged_schools(principal, *, fy: str, month: int | None = None) -> dict:
    """Flagged schools in this principal's oversight scope, grouped by owner.

    Returns `{"groups": [...], "total": int, "flagged_owners": int}`. A group
    is one staff member and the flagged schools they own, so the supervisor's
    next move — asking that person — is the shape of the data.
    """
    from apps.activities.models import Activity
    from apps.core.fy import get_operational_fy
    from apps.planning.action_models import ACTIVE_STATES, TeamAction
    from apps.planning.urgent_attention import _PRECEDENCE, resolve_urgent_issue

    fy = fy or get_operational_fy()
    month = int(month or date.today().month)
    start, end = _month_bounds(fy, month)

    scope = resolve_oversight_scope(principal)
    if scope.kind == "pl" and not scope.team_ids:
        return {"groups": [], "total": 0, "flagged_owners": 0}

    planned = (
        Activity.objects.filter(
            fy=fy,
            planned_date__gte=start,
            planned_date__lt=end,
            deleted_at__isnull=True,
        )
        .exclude(status__in=("cancelled", "rejected", "deferred"))
        .select_related("school", "school__district")
    )
    if not scope.is_country:
        # Owner, not geography. The same rule the rest of oversight uses, and
        # the reason a Program Lead sees their team and not their district.
        planned = planned.filter(responsible_staff_id__in=scope.team_ids)

    by_school: dict[str, list] = {}
    for activity in planned.order_by("planned_date"):
        if activity.school_id:
            by_school.setdefault(activity.school_id, []).append(activity)

    if not by_school:
        return {"groups": [], "total": 0, "flagged_owners": 0}

    # Which flagged schools already have somebody on them. Not used to hide
    # them — see the module docstring — but to say so on the row, which is the
    # difference between "nobody has looked at this" and "Grace is on it".
    delegated = set(
        TeamAction.objects.filter(
            school_id__in=list(by_school),
            fy=fy,
            state__in=ACTIVE_STATES,
        ).values_list("school_id", flat=True)
    )

    from apps.planning.oversight_service import _StaffDirectory

    directory = _StaffDirectory([a for acts in by_school.values() for a in acts], [])

    buckets: dict[tuple[str, str], list] = {}
    total = 0
    for school_id, acts in by_school.items():
        school = acts[0].school
        issue = resolve_urgent_issue(school, fy, acts)
        # "Support complete" is not a flag. The card drops these for the same
        # reason: a page of problems that lists non-problems trains people to
        # skim it.
        if issue.get("key") == "intervention_follow_up" and (
            issue.get("severity") == "normal"
        ):
            continue

        owner_id = acts[0].responsible_staff_id or ""
        owner_name = directory.name(owner_id) or "Unassigned"
        buckets.setdefault((owner_id, owner_name), []).append(
            {
                "school_id": school.id,
                "school_ref": school.school_id,
                "name": school.name,
                "district": getattr(getattr(school, "district", None), "name", "")
                or "",
                "planned_date": acts[0].planned_date,
                "delegated": school.id in delegated,
                **issue,
            }
        )
        total += 1

    groups = []
    for (owner_id, owner_name), rows in buckets.items():
        rows.sort(
            key=lambda r: (
                _PRECEDENCE.get(r.get("key"), 9),
                r["planned_date"] or date.max,
                r["name"],
            )
        )
        groups.append(
            {
                "owner_id": owner_id,
                "owner_name": owner_name,
                "rows": rows[:MAX_ROWS_PER_OWNER],
                # The true count, so a truncated list never reads as the whole
                # problem. `hidden` is what the template says out loud.
                "count": len(rows),
                "hidden": max(0, len(rows) - MAX_ROWS_PER_OWNER),
                "critical": sum(1 for r in rows if r.get("severity") == "critical"),
                "delegated": sum(1 for r in rows if r["delegated"]),
            }
        )

    # Most critical first, then most flagged — a supervisor reads the top of
    # this list and stops, so the top has to be the person to talk to.
    groups.sort(key=lambda g: (-g["critical"], -g["count"], g["owner_name"]))
    return {"groups": groups, "total": total, "flagged_owners": len(groups)}
