"""Coaching To-Dos (owner, 2026-09-13).

Registered in apps.command_center.todo_service.MODULE_TODO_BUILDERS. Every row
is derived from the coaching records, so it disappears the moment the work is
done — nobody ticks it off:

* Programme Lead: "Hold <Month> one-to-one with <officer>" from the tenth of
  the month while none is recorded (coaching.monthly_one_to_ones, the rule the
  Coaching page and the dashboard read); "Share coaching notes with
  <officer>" for a draft older than two days; "Follow up agreed actions with
  <officer>" once the follow-up date arrives; "Acknowledge Regional Lead
  coaching" for coaching the Regional Lead shared with them.
* Officer: "Acknowledge coaching from <Programme Lead>".

The lead's coaching rows carry the "Performance & Coaching" responsibility and
the Regional Lead row "Collaboration" (todo_service.PL_RESPONSIBILITY_CATEGORIES),
so the lead's queue groups them as the sidebar does; the officer's row keeps
"Coaching".

A fixed number of queries whatever the team size
(apps/cce_leadership/test_coaching.py pins it).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from urllib.parse import urlencode

from django.utils import timezone

logger = logging.getLogger(__name__)

LEAD_CATEGORY = "Performance & Coaching"

TEAM_COACHING_URL = "/team/coaching"
MY_COACHING_URL = "/my-coaching"
REGIONAL_COACHING_URL = "/cce-leadership/coaching"

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
    due=None,
    category="Coaching",
    source="Coaching",
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
        "source": source,
        "_due_sort": due or today,
    }


def _open(url: str, **params) -> str:
    return f"{url}?{urlencode({k: v for k, v in params.items() if v})}"


def coaching_todos(principal, role, today) -> list[dict]:
    if role not in ("Program Lead", "CCEO"):
        return []
    today = today or timezone.localdate()
    try:
        if role == "Program Lead":
            return _lead_todos(principal, today)
        return _officer_todos(principal, today)
    except Exception:  # noqa: BLE001 - one source never breaks the queue
        logger.exception("Coaching To-Dos failed")
        return []


def _lead_todos(principal, today: date) -> list[dict]:
    from apps.cce_leadership import coaching, services

    out: list[dict] = []
    members = coaching._team(principal)
    names = {m.id: getattr(m.user, "name", "") or "officer" for m in members}

    if members:
        month = coaching.monthly_one_to_ones(principal, today=today, members=members)
        for entry in [r for r in month["rows"] if r["state"] == "due"][:ROW_LIMIT]:
            out.append(
                _row(
                    f"coaching-one-to-one-{month['month']:%Y-%m}-{entry['staff_id']}",
                    title=f"Hold {month['month']:%B} one-to-one with {entry['name']}",
                    description=(
                        "The monthly one-to-one with each officer on your team is "
                        "not recorded for this month yet."
                    ),
                    priority="high" if today.day >= 20 else "medium",
                    url=_open(
                        TEAM_COACHING_URL,
                        open="new",
                        cceo=entry["staff_id"],
                        kind="one_to_one",
                    ),
                    action="Log one-to-one",
                    category=LEAD_CATEGORY,
                    linked=entry["name"],
                    today=today,
                    due=month["month_end"],
                )
            )

        visible = coaching.coaching_visible_to(principal, team_ids=list(names))
        stale = timezone.now() - timedelta(days=coaching.DRAFT_REMINDER_DAYS)
        drafts = list(
            visible.filter(shared_at__isnull=True, created_at__lte=stale).order_by(
                "held_on", "created_at"
            )[:ROW_LIMIT]
        )
        follow_ups = list(
            visible.filter(
                follow_up_due__lte=today, follow_up_done_at__isnull=True
            ).order_by("follow_up_due", "created_at")[:ROW_LIMIT]
        )
        for record in drafts:
            name = names.get(record.cceo_staff_id, "officer")
            out.append(
                _row(
                    f"coaching-share-{record.id}",
                    title=f"Share coaching notes with {name}",
                    description=record.subject,
                    priority="medium",
                    url=_open(TEAM_COACHING_URL, open=record.id, step="share"),
                    action="Share",
                    category=LEAD_CATEGORY,
                    linked=name,
                    today=today,
                )
            )
        for record in follow_ups:
            name = names.get(record.cceo_staff_id, "officer")
            out.append(
                _row(
                    f"coaching-follow-up-{record.id}",
                    title=f"Follow up agreed actions with {name}",
                    description=record.agreed_actions or record.subject,
                    priority="high",
                    url=_open(TEAM_COACHING_URL, open=record.id, step="follow-up"),
                    action="Follow up",
                    category=LEAD_CATEGORY,
                    linked=name,
                    today=today,
                    due=record.follow_up_due,
                    overdue=record.follow_up_due < today,
                )
            )

    for engagement in (
        services.regional_coaching_visible_to(principal)
        .filter(acknowledged_at__isnull=True)
        .order_by("held_on", "created_at")[:ROW_LIMIT]
    ):
        out.append(
            _row(
                f"cce-pl-coaching-{engagement.id}",
                title="Acknowledge Regional Lead coaching",
                description=engagement.agreed_actions or engagement.subject,
                priority="high",
                url=_open(REGIONAL_COACHING_URL, open=engagement.id),
                action="Acknowledge",
                linked=engagement.subject,
                today=today,
                due=engagement.follow_up_due,
                category="Collaboration",
                source="Regional Lead coaching",
            )
        )
    return out


def _officer_todos(principal, today: date) -> list[dict]:
    from apps.accounts.models import User
    from apps.cce_leadership import coaching

    records = list(
        coaching.coaching_visible_to(principal)
        .filter(acknowledged_at__isnull=True)
        .order_by("shared_at", "created_at")[:ROW_LIMIT]
    )
    if not records:
        return []
    authors = dict(
        User.objects.filter(id__in={r.author_id for r in records}).values_list(
            "id", "name"
        )
    )
    out = []
    for record in records:
        lead = authors.get(record.author_id) or "your Programme Lead"
        out.append(
            _row(
                f"coaching-acknowledge-{record.id}",
                title=f"Acknowledge coaching from {lead}",
                description=record.subject,
                priority="high",
                url=_open(MY_COACHING_URL, open=record.id),
                action="Acknowledge",
                linked=coaching.KIND_LABELS.get(record.kind, "Coaching"),
                today=today,
            )
        )
    return out
