"""Team Guidance To-Dos (owner, 2026-09-13).

Registered in apps.command_center.todo_service.MODULE_TODO_BUILDERS. Every row
is derived from the guidance records, so it disappears the moment the work is
done — nobody ticks it off:

* Officer: "Acknowledge guidance from <Programme Lead>" for each piece issued
  to them and not yet acknowledged (withdrawing it closes the row too).
* Programme Lead: "Review guidance responses — <title>" once the review date
  of issued guidance arrives; recording the review (a next date, or none)
  closes it.

The lead's row carries the "Strategic Direction" responsibility
(todo_service.PL_RESPONSIBILITY_CATEGORIES) so the lead's queue groups it as
the sidebar does. Two queries at most, whatever the team size
(apps/cce_leadership/test_guidance.py pins it).
"""

from __future__ import annotations

import logging
from datetime import date
from urllib.parse import urlencode

from django.utils import timezone

logger = logging.getLogger(__name__)

LEAD_CATEGORY = "Strategic Direction"
OFFICER_CATEGORY = "Priorities"
SOURCE = "Team Guidance"

# How many rows of one kind the queue shows; the page lists the rest.
ROW_LIMIT = 8


def _row(
    key,
    *,
    title,
    description,
    priority,
    url,
    action,
    linked,
    today,
    category,
    due=None,
    overdue=False,
):
    if overdue:
        status = ("overdue", "Overdue", "danger")
    elif due == today:
        status = ("due_today", "Due Today", "warning")
    else:
        status = ("waiting_me", "Waiting on Me", "warning")
    return {
        "id": key,
        "title": title,
        "description": (description or "")[:180],
        "category": category,
        "priority": priority,
        "status_key": status[0],
        "status_label": status[1],
        "status_tone": status[2],
        "due_label": f"{due:%-d %b}" if due else "—",
        "due_tone": "danger" if overdue else ("warning" if due else "neutral"),
        "linked": linked,
        "action_label": action,
        "action_url": url,
        "actionable": True,
        "source": SOURCE,
        "_due_sort": due or today,
    }


def _open(url: str, **params) -> str:
    return f"{url}?{urlencode({k: v for k, v in params.items() if v})}"


def guidance_todos(principal, role, today) -> list[dict]:
    if role not in ("Program Lead", "CCEO"):
        return []
    today = today or timezone.localdate()
    try:
        if role == "Program Lead":
            return _lead_todos(principal, today)
        return _officer_todos(principal, today)
    except Exception:  # noqa: BLE001 - one source never breaks the queue
        logger.exception("Team Guidance To-Dos failed")
        return []


def _lead_todos(principal, today: date) -> list[dict]:
    from apps.cce_leadership import guidance as service

    due = list(
        service.with_receipt_counts(
            service.guidance_visible_to(principal).filter(
                issued_at__isnull=False,
                withdrawn_at__isnull=True,
                review_on__lte=today,
            )
        ).order_by("review_on", "created_at")[:ROW_LIMIT]
    )
    out = []
    for guidance in due:
        waiting = guidance.recipient_count - guidance.acknowledged_count
        out.append(
            _row(
                f"guidance-review-{guidance.id}",
                title=f"Review guidance responses — {guidance.title}",
                description=(
                    f"{guidance.acknowledged_count} of {guidance.recipient_count} "
                    "officers acknowledged"
                    + (f"; {waiting} still to answer." if waiting else ".")
                ),
                priority="high" if guidance.review_on < today else "medium",
                url=_open(
                    service.LEAD_URL,
                    fy=guidance.fy,
                    open=guidance.id,
                    step="review",
                ),
                action="Review",
                linked=guidance.title,
                today=today,
                category=LEAD_CATEGORY,
                due=guidance.review_on,
                overdue=guidance.review_on < today,
            )
        )
    return out


def _officer_todos(principal, today: date) -> list[dict]:
    from apps.accounts.models import User
    from apps.cce_leadership import guidance as service

    receipts = list(
        service.receipts_for_officer(principal)
        .filter(acknowledged_at__isnull=True)
        .select_related("guidance")
        .order_by("guidance__issued_at", "created_at")[:ROW_LIMIT]
    )
    if not receipts:
        return []
    authors = dict(
        User.objects.filter(
            id__in={receipt.guidance.author_id for receipt in receipts}
        ).values_list("id", "name")
    )
    out = []
    for receipt in receipts:
        guidance = receipt.guidance
        lead = authors.get(guidance.author_id) or "your Programme Lead"
        review_on = guidance.review_on
        out.append(
            _row(
                f"guidance-acknowledge-{receipt.id}",
                title=f"Acknowledge guidance from {lead}",
                description=guidance.title,
                priority="high",
                url=_open(service.OFFICER_URL, guidance=guidance.id),
                action="Acknowledge",
                linked=guidance.title,
                today=today,
                category=OFFICER_CATEGORY,
                due=review_on,
                overdue=bool(review_on and review_on < today),
            )
        )
    return out
