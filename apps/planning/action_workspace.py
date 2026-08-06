"""Read models for the two action surfaces.

"Actions Sent" answers the sender's question — *I delegated these; where are
they?* "My Actions" answers the recipient's — *what have I been handed, and by
when?* They are the same rows read from opposite ends, so they share one
serializer and can never disagree about a state or a due date.

History is deliberately included rather than filtered away. The point of
persisting a TeamAction was that a school which keeps needing the same thing
should be visible as such; a view that showed only open work would throw that
away every time an action closed.
"""

from __future__ import annotations

from datetime import date

from apps.planning.action_models import ACTIVE_STATES, ActionState, TeamAction

# The tabs, and what each one means. "Open" is the working set; "Overdue" is
# the subset that needs chasing; "Resolved" is the evidence the loop closes.
TABS = (
    ("open", "Open"),
    ("overdue", "Overdue"),
    ("resolved", "Resolved"),
    ("all", "All"),
)

# Issue labels, written out rather than derived. `"no_ssa".title()` gives
# "No Ssa", which reads as a typo on a page senior staff use daily.
ISSUE_LABELS = {
    "no_ssa": "No SSA",
    "low_ssa": "Low SSA",
    "no_visit": "No visit",
    "no_training": "No training",
    "no_visit_or_training": "No visit or training",
    "intervention_critical": "Critical intervention area",
    "intervention_warning": "Weak intervention area",
    "intervention_follow_up": "Intervention follow-up",
}

_STATE_TONE = {
    ActionState.OPEN: ("Open", "info"),
    ActionState.ACKNOWLEDGED: ("Acknowledged", "info"),
    ActionState.IN_PROGRESS: ("In progress", "info"),
    ActionState.BLOCKED: ("Blocked", "neutral"),
    ActionState.OVERDUE: ("Overdue", "danger"),
    ActionState.ESCALATED: ("Escalated", "danger"),
    ActionState.RESOLVED: ("Resolved", "success"),
    ActionState.RETURNED: ("Returned", "warning"),
    ActionState.CANCELLED: ("Cancelled", "neutral"),
}


def _apply_tab(qs, tab: str):
    if tab == "open":
        return qs.filter(state__in=ACTIVE_STATES).exclude(state=ActionState.OVERDUE)
    if tab == "overdue":
        return qs.filter(state__in=[ActionState.OVERDUE, ActionState.ESCALATED])
    if tab == "resolved":
        return qs.filter(state=ActionState.RESOLVED)
    return qs


def _serialize(actions: list[TeamAction], *, perspective: str) -> list[dict]:
    """One row shape for both surfaces. `perspective` decides whose name the
    row leads with — the sender wants to see who owes them, the recipient wants
    to see who asked."""
    if not actions:
        return []

    from apps.accounts.models import User
    from apps.schools.models import School

    people = {a.sender_id for a in actions} | {a.recipient_id for a in actions}
    names = dict(User.objects.filter(id__in=people).values_list("id", "name"))
    schools = {
        s["id"]: s
        for s in School.objects.filter(id__in={a.school_id for a in actions}).values(
            "id", "name", "school_id", "district__name"
        )
    }

    today = date.today()
    rows = []
    for a in actions:
        school = schools.get(a.school_id, {})
        label, tone = _STATE_TONE.get(a.state, (a.state.title(), "neutral"))
        counterparty = a.recipient_id if perspective == "sender" else a.sender_id
        overdue_by = (
            (today - a.due_date).days
            if a.due_date and a.due_date < today and a.state in ACTIVE_STATES
            else 0
        )
        rows.append(
            {
                "id": a.id,
                "school": school.get("name") or "School",
                "school_pk": a.school_id,
                "school_ref": school.get("school_id") or "",
                "district": school.get("district__name") or "—",
                "issue": ISSUE_LABELS.get(
                    a.issue_type, a.issue_type.replace("_", " ").capitalize()
                ),
                "requested_action": a.requested_action,
                "counterparty": names.get(counterparty) or "—",
                "counterparty_label": (
                    "Assigned to" if perspective == "sender" else "Sent by"
                ),
                "state": a.state,
                "state_label": label,
                "state_tone": tone,
                "priority": a.priority,
                "due_date": a.due_date,
                "overdue_by": overdue_by,
                "sent_on": a.created_at,
                "resolved_at": a.resolved_at,
                # Distinguishing these two matters: a system-resolved action is
                # evidence the work was done, a hand-closed one is somebody's
                # word for it.
                "resolved_by_system": a.resolved_by_system,
                "route": a.workflow_route,
                "note": a.message,
                "returned_reason": a.returned_reason,
                "blocked_reason": a.blocked_reason,
                "is_active": a.state in ACTIVE_STATES,
                "can_escalate": a.state == ActionState.OVERDUE,
            }
        )
    return rows


def _counts(qs) -> dict:
    from django.db.models import Count, Q

    agg = qs.aggregate(
        total=Count("id"),
        open=Count(
            "id",
            filter=Q(state__in=ACTIVE_STATES) & ~Q(state=ActionState.OVERDUE),
        ),
        overdue=Count(
            "id", filter=Q(state__in=[ActionState.OVERDUE, ActionState.ESCALATED])
        ),
        resolved=Count("id", filter=Q(state=ActionState.RESOLVED)),
        returned=Count(
            "id", filter=Q(state__in=[ActionState.RETURNED, ActionState.CANCELLED])
        ),
    )
    # Of the resolved ones, how many closed because the record proved it. A
    # queue draining mostly by hand is a queue being cleared, not worked.
    agg["auto_resolved"] = qs.filter(
        state=ActionState.RESOLVED, resolved_by_system=True
    ).count()
    return agg


def actions_sent(user, *, tab: str = "open", limit: int = 100) -> dict:
    """What this user has delegated."""
    base = TeamAction.objects.filter(sender_id=getattr(user, "id", ""))
    rows = list(_apply_tab(base, tab).order_by("due_date", "-created_at")[:limit])
    return {
        "rows": _serialize(rows, perspective="sender"),
        "counts": _counts(base),
        "tab": tab,
        "tabs": TABS,
        "perspective": "sender",
    }


def actions_received(user, *, tab: str = "open", limit: int = 100) -> dict:
    """What this user has been handed."""
    base = TeamAction.objects.filter(recipient_id=getattr(user, "id", ""))
    rows = list(_apply_tab(base, tab).order_by("due_date", "-created_at")[:limit])
    return {
        "rows": _serialize(rows, perspective="recipient"),
        "counts": _counts(base),
        "tab": tab,
        "tabs": TABS,
        "perspective": "recipient",
    }


def school_action_history(school_id: str, limit: int = 25) -> list[dict]:
    """Every action ever raised about one school, newest first.

    This is the payoff for persisting rather than notifying: a school profile
    can now show "third No SSA action this year" instead of a clean slate that
    hides a pattern.
    """
    actions = list(
        TeamAction.objects.filter(school_id=school_id).order_by("-created_at")[:limit]
    )
    return _serialize(actions, perspective="sender")
