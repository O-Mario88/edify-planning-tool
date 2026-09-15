"""One row shape for the module To-Do builders added on 2026-09-15.

The builders registered in ``todo_service.MODULE_TODO_BUILDERS`` each return
rows in the queue's shape. The partner-engagement builder carries its own copy
of the constructor; the builders written for the 2026-09-15 brief (partner
logins, school coverage, ownership transfers, FY planning, project schools)
share this one so the shape cannot drift between them.

Every row is derived from records and vanishes when its condition stops
holding. None of them is ticked off, stored or re-sent.
"""

from __future__ import annotations

from datetime import date


def todo_row(
    key: str,
    *,
    title: str,
    description: str,
    category: str,
    priority: str,
    url: str,
    action: str,
    linked: str,
    today: date,
    source: str,
    due: date | None = None,
) -> dict:
    overdue = bool(due and due < today)
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
        "source": source,
        "_due_sort": due or today,
    }


__all__ = ["todo_row"]
