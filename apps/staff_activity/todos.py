"""Staff Activity follow-ups on the To-Do list (owner, 2026-09-29; §9.5).

Derived from the follow-up rows, nothing stored: a follow-up sent to someone —
a staff member, or a Programme Lead asked by the Country Director — is on
their list until it is acknowledged and worked; an escalated one is on the
Country Director's. The row disappears when the follow-up resolves, including
when the platform sees the condition met (``sweep_auto_resolutions``).
"""

from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

_PRIORITY = {"high": "high", "normal": "medium", "low": "low"}


def follow_up_todos(principal, role, today) -> list[dict]:
    try:
        from django.db.models import Q

        from .follow_ups import sweep_auto_resolutions
        from .models import FollowUpRoute, FollowUpStatus, StaffUsageFollowUp

        today = today or timezone.localdate()
        me = getattr(principal, "user_id", None) or getattr(principal, "id", None)
        if not me:
            return []
        waiting = [
            FollowUpStatus.SENT,
            FollowUpStatus.ACKNOWLEDGED,
            FollowUpStatus.SUPPORT_SCHEDULED,
            FollowUpStatus.WAITING_FOR_STAFF,
        ]
        # One query for the whole list: sent to me, sent back to me, and —
        # for the Country Director — escalated (the To-Do page has a query
        # budget; apps/command_center/test_todo_query_budget.py).
        mine = Q(assignee_id=me, status__in=waiting) | Q(
            created_by_id=me, status=FollowUpStatus.RETURNED
        )
        if role == "CountryDirector":
            mine |= Q(status=FollowUpStatus.ESCALATED)
        rows = list(
            StaffUsageFollowUp.objects.filter(mine)
            .select_related("subject", "created_by")
            .order_by("due_date")[:100]
        )
        sweep_auto_resolutions(rows)
        out = []
        for fu in rows:
            if fu.status in (
                FollowUpStatus.RESOLVED_BY_ACTIVITY,
                FollowUpStatus.RESOLVED_BY_MANAGER,
                FollowUpStatus.CLOSED,
                FollowUpStatus.CANCELED,
            ):
                continue
            overdue = fu.due_date < today
            subject = fu.subject.name or fu.subject.email
            sender = (fu.created_by.name if fu.created_by else "") or "Your manager"
            if fu.status == FollowUpStatus.RETURNED:
                title = f"Clarify your follow-up with {subject}"
            elif fu.status == FollowUpStatus.ESCALATED:
                title = f"Escalated follow-up: {subject}"
            elif fu.route == FollowUpRoute.DIRECTOR_TO_MANAGER:
                title = f"Follow up with {subject}"
            else:
                title = f"Respond to {sender}'s follow-up"
            out.append(
                {
                    "id": f"staff-follow-up-{fu.id}",
                    "title": title,
                    "description": f"{fu.get_trigger_display()} — {fu.note}"[:180],
                    "category": "Team Leadership",
                    "priority": "critical"
                    if overdue
                    else _PRIORITY.get(fu.priority, "medium"),
                    "status_key": "overdue" if overdue else "waiting_me",
                    "status_label": "Overdue" if overdue else "Waiting on Me",
                    "status_tone": "danger" if overdue else "warning",
                    "due_label": f"{fu.due_date:%-d %b}",
                    "due_tone": "danger" if overdue else "warning",
                    "linked": f"Staff Activity · {fu.get_status_display()}",
                    "action_label": "Open",
                    "action_url": f"/staff-activity/follow-ups/{fu.id}",
                    "actionable": True,
                    "source": "Staff Activity",
                    "_due_sort": fu.due_date,
                }
            )
        return out
    except Exception:  # pragma: no cover - one builder never breaks the queue
        logger.exception("staff activity: follow-up To-Dos failed")
        return []
